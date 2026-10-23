"""Transcription d'une session : persistance par tronçon, reprise, corrections manuelles."""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

from teams_assistant.logging_setup import get_logger
from teams_assistant.models import SessionStatus, Transcript, TranscriptSegment, TranscriptStatus
from teams_assistant.services.session_service import SessionService
from teams_assistant.storage.repositories import TranscriptRepository
from teams_assistant.transcription.pipeline import TranscriptionPipeline
from teams_assistant.transcription.types import (
    AudioSource,
    ProgressCallback,
    Segment,
    SourceKind,
    TranscriptionCancelled,
    TranscriptionError,
    TranscriptionOptions,
    TranscriptResult,
)

log = get_logger("services.transcription")
SEQ_PER_CHUNK = 100_000  # numérotation provisoire des segments pendant le traitement


def to_db_segment(transcript_id: str, seq: int, seg: Segment) -> TranscriptSegment:
    return TranscriptSegment(transcript_id=transcript_id, seq=seq, start_s=seg.start_s, end_s=seg.end_s,
                             text=seg.text, source=seg.source.value, speaker=seg.speaker,
                             confidence=seg.confidence, uncertain=seg.uncertain, chunk_index=seg.chunk_index)


def from_db_segment(seg: TranscriptSegment) -> Segment:
    return Segment(start_s=seg.start_s, end_s=seg.end_s, text=seg.text, source=SourceKind(seg.source),
                   speaker=seg.speaker, confidence=seg.confidence, uncertain=seg.uncertain,
                   chunk_index=seg.chunk_index)


class TranscriptionService:
    def __init__(self, repo: TranscriptRepository, sessions: SessionService,
                 pipeline: TranscriptionPipeline) -> None:
        self.repo = repo
        self.sessions = sessions
        self.pipeline = pipeline

    def sources_for(self, session_id: str) -> list[AudioSource]:
        sources = []
        for audio in self.sessions.repo.audio_files(session_id):
            if audio.has_signal and Path(audio.path).exists():
                sources.append(AudioSource(Path(audio.path), SourceKind(audio.kind)))
        return sources

    def _resumable(self, session_id: str, options: TranscriptionOptions) -> Transcript | None:
        latest = self.repo.latest_for_session(session_id)
        if latest and latest.status in (TranscriptStatus.INTERRUPTED, TranscriptStatus.IN_PROGRESS) \
                and latest.options == asdict(options):
            return latest
        return None

    def can_resume(self, session_id: str, options: TranscriptionOptions) -> bool:
        return self._resumable(session_id, options) is not None

    def transcribe(self, session_id: str, options: TranscriptionOptions,
                   on_progress: ProgressCallback | None = None, cancel: threading.Event | None = None,
                   delete_audio_after: bool = False) -> Transcript:
        sources = self.sources_for(session_id)
        if not sources:
            raise TranscriptionError("Aucun fichier audio exploitable pour cette session "
                                     "(capture sans signal, fichier supprimé ou import manquant).")
        transcript = self._resumable(session_id, options) or self.repo.add(
            Transcript(session_id=session_id, options=asdict(options), profile=options.profile))
        self.sessions.set_status(session_id, SessionStatus.TRANSCRIBING)
        try:
            result = self._run(transcript, sources, options, on_progress, cancel)
        except TranscriptionCancelled:
            self._finish(transcript, TranscriptStatus.INTERRUPTED, "Interrompue — reprise possible.")
            self.sessions.set_status(session_id, SessionStatus.RECORDED)
            raise
        except TranscriptionError as exc:
            self._finish(transcript, TranscriptStatus.ERROR, str(exc))
            self.sessions.set_status(session_id, SessionStatus.ERROR)
            raise
        self._store_result(transcript, result)
        self.sessions.set_status(session_id, SessionStatus.TRANSCRIBED)
        if delete_audio_after:
            self.sessions.delete_audio(session_id)
        return transcript

    def _run(self, transcript: Transcript, sources: list[AudioSource], options: TranscriptionOptions,
             on_progress: ProgressCallback | None, cancel: threading.Event | None) -> TranscriptResult:
        completed = self._completed(transcript.id)
        transcript.status = TranscriptStatus.IN_PROGRESS
        self.repo.save(transcript)

        def on_chunk(index: int, segments: list[Segment]) -> None:
            rows = [to_db_segment(transcript.id, index * SEQ_PER_CHUNK + i, s) for i, s in enumerate(segments)]
            self.repo.save_chunk(transcript.id, index, rows)

        return self.pipeline.run(sources, options, on_chunk=on_chunk, on_progress=on_progress,
                                 cancel=cancel, completed=completed)

    def _completed(self, transcript_id: str) -> dict[int, list[Segment]]:
        done = self.repo.completed_chunks(transcript_id)
        grouped: dict[int, list[Segment]] = {index: [] for index in done}
        for seg in self.repo.segments(transcript_id):
            if seg.chunk_index in grouped:
                grouped[seg.chunk_index].append(from_db_segment(seg))
        return grouped

    def _store_result(self, transcript: Transcript, result: TranscriptResult) -> None:
        # Version finale : ordre chronologique, écho retiré, numérotation définitive 1..n
        rows = [to_db_segment(transcript.id, i + 1, s) for i, s in enumerate(result.segments)]
        self.repo.replace_segments(transcript.id, rows)
        transcript.engine, transcript.model = result.engine, result.model
        transcript.language, transcript.language_probability = result.language, result.language_probability
        transcript.warnings = result.warnings
        self._finish(transcript, TranscriptStatus.COMPLETED, "")
        log.info("Transcription terminée %s : %d segments", transcript.id, len(rows))

    def _finish(self, transcript: Transcript, status: TranscriptStatus, error: str) -> None:
        transcript.status = status
        transcript.error = error
        self.repo.save(transcript)

    # --- consultation et corrections -------------------------------------------------
    def latest(self, session_id: str) -> Transcript | None:
        return self.repo.latest_for_session(session_id)

    def segments(self, transcript_id: str) -> list[TranscriptSegment]:
        return self.repo.segments(transcript_id)

    def correct_text(self, segment_id: str, text: str) -> None:
        self.repo.update_segment_text(segment_id, text.strip())

    def rename_speaker(self, transcript_id: str, old_label: str, new_label: str) -> int:
        """Renomme un libellé d'intervenant sur toute la transcription (décision de l'utilisateur)."""
        count = 0
        for seg in self.repo.segments(transcript_id):
            if seg.speaker == old_label:
                self.repo.update_segment_speaker(seg.id, new_label.strip())
                count += 1
        return count

    def search(self, transcript_id: str, text: str) -> list[TranscriptSegment]:
        needle = text.lower().strip()
        return [s for s in self.repo.segments(transcript_id) if needle and needle in s.text.lower()]
