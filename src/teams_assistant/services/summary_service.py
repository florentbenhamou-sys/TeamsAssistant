"""Comptes rendus : génération, correction, validation, actions extraites."""

from __future__ import annotations

from teams_assistant.models import ActionItem, MeetingSummary, SessionStatus, TranscriptStatus, now_iso
from teams_assistant.services.session_service import SessionService
from teams_assistant.settings import AppSettings
from teams_assistant.storage.repositories import SummaryRepository, TranscriptRepository
from teams_assistant.summary import SummaryGenerator
from teams_assistant.summary.claude_generator import ClaudeSummaryGenerator
from teams_assistant.summary.local_generator import LocalSummaryGenerator
from teams_assistant.summary.schema import SummaryContent, SummaryInput


class SummaryError(RuntimeError):
    pass


def generator_for(settings: AppSettings, cloud_confirmed: bool) -> SummaryGenerator:
    """Choisit le générateur ; le cloud exige l'activation ET une confirmation explicite."""
    if settings.summary_generator == "claude":
        if not settings.cloud_ai_enabled:
            raise SummaryError("L'IA cloud est désactivée dans les Paramètres.")
        if not cloud_confirmed:
            raise SummaryError("L'envoi de la transcription au service cloud n'a pas été confirmé.")
        return ClaudeSummaryGenerator(model=settings.cloud_model)
    return LocalSummaryGenerator()


def actions_from(content: SummaryContent, summary_id: str) -> list[ActionItem]:
    return [ActionItem(summary_id=summary_id, description=item.text, owner=item.owner, due=item.due,
                       segment_refs=item.refs) for item in content.sections.get("next_actions", [])]


class SummaryService:
    def __init__(self, repo: SummaryRepository, transcripts: TranscriptRepository,
                 sessions: SessionService) -> None:
        self.repo = repo
        self.transcripts = transcripts
        self.sessions = sessions

    def build_input(self, session_id: str) -> tuple[str, SummaryInput]:
        session = self.sessions.get(session_id)
        transcript = self.transcripts.latest_for_session(session_id)
        if transcript is None or transcript.status is not TranscriptStatus.COMPLETED:
            raise SummaryError("Aucune transcription terminée pour cette session.")
        segments = self.transcripts.segments(transcript.id)
        if not segments:
            raise SummaryError("La transcription est vide : rien à résumer.")
        date = (session.outlook_start or session.started_at or session.created_at)[:16].replace("T", " ")
        data = SummaryInput(title=session.title, date=date, duration_s=session.duration_s,
                            participants=self.sessions.repo.participants(session_id), segments=segments)
        return transcript.id, data

    def generate(self, session_id: str, generator: SummaryGenerator) -> MeetingSummary:
        transcript_id, data = self.build_input(session_id)
        content = generator.generate(data)
        summary = MeetingSummary(session_id=session_id, transcript_id=transcript_id,
                                 content=content.to_dict(), generator=generator.name)
        self.repo.add(summary, actions_from(content, summary.id))
        self.sessions.set_status(session_id, SessionStatus.SUMMARIZED)
        return summary

    def latest(self, session_id: str) -> MeetingSummary | None:
        return self.repo.latest_for_session(session_id)

    def content(self, summary: MeetingSummary) -> SummaryContent:
        return SummaryContent.from_dict(summary.content)

    def update(self, summary: MeetingSummary, content: SummaryContent) -> None:
        """Enregistre les corrections ; toute modification annule une validation antérieure."""
        summary.content = content.to_dict()
        summary.validated, summary.validated_at = False, None
        self.repo.save(summary, actions_from(content, summary.id))

    def validate(self, summary: MeetingSummary) -> None:
        summary.validated, summary.validated_at = True, now_iso()
        self.repo.save(summary, self.repo.actions(summary.id))
