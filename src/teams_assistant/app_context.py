"""Assemblage des dépendances (point unique de câblage, facilite les tests et l'évolution)."""

from __future__ import annotations

from dataclasses import dataclass

from teams_assistant.config import AppPaths
from teams_assistant.services.session_service import SessionService
from teams_assistant.services.summary_service import SummaryService
from teams_assistant.services.transcription_service import TranscriptionService
from teams_assistant.settings import SettingsService
from teams_assistant.storage.db import connect
from teams_assistant.storage.repositories import (
    Database,
    SessionRepository,
    SettingsRepository,
    SummaryRepository,
    TranscriptRepository,
)
from teams_assistant.transcription.pipeline import TranscriptionPipeline
from teams_assistant.transcription.types import SpeechEngine


@dataclass
class AppContext:
    paths: AppPaths
    db: Database
    settings: SettingsService
    sessions: SessionService
    transcription: TranscriptionService
    summaries: SummaryService

    def close(self) -> None:
        self.db.conn.close()


def build_context(paths: AppPaths, engine: SpeechEngine | None = None) -> AppContext:
    paths.ensure()
    db = Database(connect(paths.db_file))
    settings = SettingsService(SettingsRepository(db))
    sessions = SessionService(SessionRepository(db), paths)
    if engine is None:
        from teams_assistant.transcription.whisper_engine import FasterWhisperEngine
        engine = FasterWhisperEngine(paths.models, device=settings.load().compute_device)
    transcripts = TranscriptRepository(db)
    transcription = TranscriptionService(transcripts, sessions, TranscriptionPipeline(engine))
    summaries = SummaryService(SummaryRepository(db), transcripts, sessions)
    return AppContext(paths, db, settings, sessions, transcription, summaries)
