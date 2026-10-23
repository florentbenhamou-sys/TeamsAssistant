"""Gestion des sessions : création, capture, import, renommage, conservation et suppression."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from teams_assistant.audio.capture_session import CaptureResult
from teams_assistant.audio.types import DeviceKind
from teams_assistant.audio.wav_utils import analyze_wav
from teams_assistant.config import AppPaths
from teams_assistant.logging_setup import get_logger
from teams_assistant.models import AudioFile, MeetingSession, Participant, SessionStatus, now_iso
from teams_assistant.storage.repositories import SessionRepository

log = get_logger("services.session")
AUDIO_KIND = {DeviceKind.LOOPBACK: "system", DeviceKind.INPUT: "microphone"}
SUPPORTED_IMPORTS = {".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".flac", ".webm", ".aac", ".wma"}


class SessionError(RuntimeError):
    pass


class SessionService:
    def __init__(self, repo: SessionRepository, paths: AppPaths) -> None:
        self.repo = repo
        self.paths = paths

    def create(self, title: str, outlook_event_id: str | None = None, outlook_start: str | None = None,
               outlook_end: str | None = None, join_url: str | None = None) -> MeetingSession:
        clean = title.strip() or f"Réunion du {datetime.now():%d/%m/%Y %H:%M}"
        session = MeetingSession(title=clean, outlook_event_id=outlook_event_id, outlook_start=outlook_start,
                                 outlook_end=outlook_end, join_url=join_url)
        self.repo.add(session)
        log.info("Session créée %s", session.id)
        return session

    def get(self, session_id: str) -> MeetingSession:
        session = self.repo.get(session_id)
        if session is None:
            raise SessionError(f"Session introuvable : {session_id}")
        return session

    def recording_dir(self, session_id: str) -> Path:
        return self.paths.recordings / session_id

    def confirm_consent(self, session_id: str) -> None:
        session = self.get(session_id)
        session.consent_confirmed_at = now_iso()
        self.repo.save(session)

    def mark_capture_started(self, session_id: str) -> None:
        session = self.get(session_id)
        if session.consent_confirmed_at is None:
            raise SessionError("La vérification des autorisations doit être confirmée avant la capture.")
        session.started_at = now_iso()
        self.repo.save(session)

    def attach_capture(self, session_id: str, result: CaptureResult) -> list[AudioFile]:
        """Enregistre les fichiers produits ; seuls ceux contenant du signal sont exploitables."""
        session = self.get(session_id)
        files = []
        for source in result.sources:
            audio = AudioFile(session_id=session_id, kind=AUDIO_KIND[source.device.kind], path=str(source.path), owned=True, duration_s=source.report.duration_s,
                              has_signal=source.report.has_signal)
            self.repo.add_audio(audio)
            files.append(audio)
        session.ended_at = now_iso()
        session.duration_s = result.duration_s
        session.status = SessionStatus.RECORDED if result.succeeded else SessionStatus.ERROR
        self.repo.save(session)
        return files

    def import_audio(self, session_id: str, path: Path) -> AudioFile:
        """Associe un fichier existant ; il n'est jamais supprimé par la politique de conservation."""
        self.get(session_id)
        if not path.is_file():
            raise SessionError(f"Fichier introuvable : {path}")
        if path.suffix.lower() not in SUPPORTED_IMPORTS:
            raise SessionError(f"Format non pris en charge : {path.suffix} ({', '.join(sorted(SUPPORTED_IMPORTS))})")
        report = analyze_wav(path) if path.suffix.lower() == ".wav" else None
        audio = AudioFile(session_id=session_id, kind="imported", path=str(path.resolve()), owned=False,
                          duration_s=report.duration_s if report else 0.0,
                          has_signal=report.has_signal if report else True)
        self.repo.add_audio(audio)
        session = self.get(session_id)
        session.status = SessionStatus.RECORDED
        session.duration_s = max(session.duration_s, audio.duration_s)
        self.repo.save(session)
        return audio

    def rename(self, session_id: str, title: str) -> MeetingSession:
        if not title.strip():
            raise SessionError("Le titre ne peut pas être vide.")
        session = self.get(session_id)
        session.title = title.strip()
        self.repo.save(session)
        return session

    def set_status(self, session_id: str, status: SessionStatus) -> None:
        session = self.get(session_id)
        session.status = status
        self.repo.save(session)

    def set_participants(self, session_id: str, participants: list[Participant]) -> None:
        self.repo.clear_participants(session_id)
        for participant in participants:
            self.repo.add_participant(participant)

    def search(self, text: str = "") -> list[MeetingSession]:
        return self.repo.search(text.strip())

    # --- suppression et conservation ---------------------------------------------------
    def delete_audio(self, session_id: str) -> int:
        """Supprime les fichiers audio temporaires (créés par l'application) d'une session."""
        removed = 0
        for audio in self.repo.audio_files(session_id):
            if audio.owned:
                removed += self._remove_file(audio)
        return removed

    def _remove_file(self, audio: AudioFile) -> int:
        Path(audio.path).unlink(missing_ok=True)
        audio.deleted_at = now_iso()
        self.repo.save_audio(audio)
        return 1

    def delete_session(self, session_id: str) -> None:
        """Suppression complète : fichiers temporaires, dossier d'enregistrement, données en base."""
        self.get(session_id)
        self.delete_audio(session_id)
        shutil.rmtree(self.recording_dir(session_id), ignore_errors=True)
        self.repo.delete(session_id)  # cascade : transcriptions, segments, comptes rendus, actions
        log.info("Session supprimée %s", session_id)

    def purge_expired_audio(self, retention_days: int) -> int:
        limit = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        return sum(self._remove_file(audio) for audio in self.repo.owned_audio_older_than(limit))
