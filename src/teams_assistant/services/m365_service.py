"""Cas d'usage Microsoft 365 : connexion, réunions à venir, import d'un transcript officiel.

Tout est facultatif : en cas d'échec, la transcription locale reste pleinement utilisable.
"""

from __future__ import annotations

from teams_assistant.config import AppPaths
from teams_assistant.m365.auth import SCOPES_CALENDAR, SCOPES_TRANSCRIPTS, AccountInfo, GraphAuth
from teams_assistant.m365.graph import CalendarMeeting, GraphClient, HttpSession, TranscriptCheck
from teams_assistant.m365.vtt import parse_vtt
from teams_assistant.models import (
    IdentityStatus,
    Participant,
    SessionStatus,
    Transcript,
    TranscriptOrigin,
    TranscriptSegment,
    TranscriptStatus,
)
from teams_assistant.services.session_service import SessionService
from teams_assistant.settings import AppSettings
from teams_assistant.storage.repositories import TranscriptRepository
from teams_assistant.transcription.types import SourceKind


def default_http() -> HttpSession:
    import requests

    return requests.Session()  # type: ignore[return-value]


class M365Service:
    def __init__(self, settings: AppSettings, paths: AppPaths, http: HttpSession | None = None,
                 auth: GraphAuth | None = None) -> None:
        self.auth = auth or GraphAuth(settings.graph_client_id, settings.graph_tenant,
                                      paths.base / "msal_token_cache.bin")
        self.http = http
        self._interactive = False

    def _client(self, scopes: list[str]) -> GraphClient:
        http = self.http or default_http()
        return GraphClient(http, lambda: self.auth.token(scopes, interactive=self._interactive))

    def sign_in(self) -> AccountInfo | None:
        """Connexion interactive explicite (ouvre la page Microsoft dans le navigateur)."""
        self.auth.token(SCOPES_CALENDAR, interactive=True)
        return self.auth.account()

    def account(self) -> AccountInfo | None:
        return self.auth.account()

    def sign_out(self) -> None:
        self.auth.sign_out()

    def upcoming(self, days: int = 7) -> list[CalendarMeeting]:
        return self._client(SCOPES_CALENDAR).upcoming_meetings(days)

    def check_transcripts(self, join_url: str, interactive: bool = False) -> TranscriptCheck:
        self._interactive = interactive  # consentement incrémental aux permissions transcripts
        try:
            return self._client(SCOPES_TRANSCRIPTS).check_transcripts(join_url)
        finally:
            self._interactive = False

    def import_official_transcript(self, sessions: SessionService, transcripts: TranscriptRepository,
                                   session_id: str, check: TranscriptCheck) -> Transcript:
        client = self._client(SCOPES_TRANSCRIPTS)
        cues = parse_vtt(client.transcript_vtt(check.meeting_id, check.transcript_ids[-1]))
        transcript = transcripts.add(Transcript(session_id=session_id, origin=TranscriptOrigin.TEAMS_OFFICIAL,
                                                engine="microsoft-teams", model="transcript officiel",
                                                language="", status=TranscriptStatus.COMPLETED))
        rows = [TranscriptSegment(transcript_id=transcript.id, seq=i + 1, start_s=c.start_s, end_s=c.end_s,
                                  text=c.text, source=SourceKind.TEAMS.value, speaker=c.speaker or None)
                for i, c in enumerate(cues)]
        transcripts.replace_segments(transcript.id, rows)
        sessions.set_status(session_id, SessionStatus.TRANSCRIBED)
        return transcript


def participants_from_meeting(session_id: str, meeting: CalendarMeeting) -> list[Participant]:
    """Participants issus de l'invitation : identité confirmée par Outlook (présence non garantie)."""
    names = ([meeting.organizer] if meeting.organizer else []) + meeting.attendees
    return [Participant(session_id=session_id, display_name=name, identity=IdentityStatus.CONFIRMED,
                        origin="outlook (invité)") for name in dict.fromkeys(names)]
