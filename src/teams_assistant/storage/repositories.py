"""Accès aux données : un dépôt par agrégat, requêtes paramétrées uniquement.

Les noms de tables et de colonnes proviennent exclusivement des dataclasses du code
(jamais d'une saisie), les valeurs passent toujours par des paramètres « ? ».
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import fields
from enum import Enum
from typing import Any, TypeVar

from teams_assistant.models import (
    ActionItem,
    AudioFile,
    IdentityStatus,
    MeetingSession,
    MeetingSummary,
    Participant,
    SessionStatus,
    Transcript,
    TranscriptOrigin,
    TranscriptSegment,
    TranscriptStatus,
    now_iso,
)

T = TypeVar("T")
# Champs stockés en JSON : nom du champ -> nom de colonne
JSON_COLUMNS = {"warnings": "warnings_json", "segment_refs": "segment_refs_json",
                "content": "content_json", "options": "options_json"}
ENUM_FIELDS: dict[str, type[Enum]] = {"status": SessionStatus, "origin": TranscriptOrigin,
                                      "identity": IdentityStatus}
SKIPPED_PROPERTIES = {"edited"}


def _column(name: str) -> str:
    return JSON_COLUMNS.get(name, name)


def _to_db(value: Any, name: str) -> Any:
    if name in JSON_COLUMNS:
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return int(value)
    return value


def _from_row(cls: type[T], row: sqlite3.Row, enums: dict[str, type[Enum]] | None = None) -> T:
    values: dict[str, Any] = {}
    keys = row.keys()
    for f in fields(cls):  # type: ignore[arg-type]
        column = _column(f.name)
        if column not in keys:
            continue
        raw = row[column]
        if f.name in JSON_COLUMNS:
            raw = json.loads(raw)
        elif enums and f.name in enums and raw is not None:
            raw = enums[f.name](raw)
        elif f.type in ("bool", bool):
            raw = bool(raw)
        values[f.name] = raw
    return cls(**values)


class Database:
    """Enveloppe de connexion partagée, protégée par un verrou (threads UI + traitements)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.lock = threading.RLock()

    def insert(self, table: str, entity: Any) -> None:
        names = [f.name for f in fields(entity) if f.name not in SKIPPED_PROPERTIES]
        columns = ", ".join(_column(n) for n in names)
        marks = ", ".join("?" for _ in names)
        params = [_to_db(getattr(entity, n), n) for n in names]
        with self.lock:
            self.conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", params)

    def update(self, table: str, entity: Any) -> None:
        names = [f.name for f in fields(entity) if f.name != "id"]
        assignments = ", ".join(f"{_column(n)} = ?" for n in names)
        params = [_to_db(getattr(entity, n), n) for n in names] + [entity.id]
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", params)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(sql, params).fetchall())

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self.lock:
            return self.conn.execute(sql, params).rowcount


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, session: MeetingSession) -> MeetingSession:
        self.db.insert("meeting_session", session)
        return session

    def save(self, session: MeetingSession) -> None:
        session.updated_at = now_iso()
        self.db.update("meeting_session", session)

    def get(self, session_id: str) -> MeetingSession | None:
        rows = self.db.query("SELECT * FROM meeting_session WHERE id = ?", (session_id,))
        return _from_row(MeetingSession, rows[0], {"status": SessionStatus}) if rows else None

    def search(self, text: str = "", limit: int = 200) -> list[MeetingSession]:
        pattern = f"%{text}%"
        rows = self.db.query(
            "SELECT DISTINCT s.* FROM meeting_session s "
            "LEFT JOIN transcript t ON t.session_id = s.id "
            "LEFT JOIN transcript_segment g ON g.transcript_id = t.id "
            "WHERE ? = '' OR s.title LIKE ? OR g.text LIKE ? "
            "ORDER BY s.created_at DESC LIMIT ?", (text, pattern, pattern, limit))
        return [_from_row(MeetingSession, r, {"status": SessionStatus}) for r in rows]

    def delete(self, session_id: str) -> None:
        self.db.execute("DELETE FROM meeting_session WHERE id = ?", (session_id,))

    # --- fichiers audio --------------------------------------------------------------
    def add_audio(self, audio: AudioFile) -> None:
        self.db.insert("audio_file", audio)

    def save_audio(self, audio: AudioFile) -> None:
        self.db.update("audio_file", audio)

    def audio_files(self, session_id: str, include_deleted: bool = False) -> list[AudioFile]:
        rows = self.db.query("SELECT * FROM audio_file WHERE session_id = ? "
                             "AND (? = 1 OR deleted_at IS NULL) ORDER BY created_at",
                             (session_id, int(include_deleted)))
        return [_from_row(AudioFile, r) for r in rows]

    def owned_audio_older_than(self, iso_date: str) -> list[AudioFile]:
        rows = self.db.query("SELECT * FROM audio_file WHERE owned = 1 AND deleted_at IS NULL "
                             "AND created_at < ?", (iso_date,))
        return [_from_row(AudioFile, r) for r in rows]

    # --- participants ----------------------------------------------------------------
    def add_participant(self, participant: Participant) -> None:
        self.db.insert("participant", participant)

    def participants(self, session_id: str) -> list[Participant]:
        rows = self.db.query("SELECT * FROM participant WHERE session_id = ? ORDER BY display_name",
                             (session_id,))
        return [_from_row(Participant, r, {"identity": IdentityStatus}) for r in rows]

    def clear_participants(self, session_id: str) -> None:
        self.db.execute("DELETE FROM participant WHERE session_id = ?", (session_id,))


class TranscriptRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, transcript: Transcript) -> Transcript:
        self.db.insert("transcript", transcript)
        return transcript

    def save(self, transcript: Transcript) -> None:
        transcript.updated_at = now_iso()
        self.db.update("transcript", transcript)

    def get(self, transcript_id: str) -> Transcript | None:
        rows = self.db.query("SELECT * FROM transcript WHERE id = ?", (transcript_id,))
        return self._map(rows[0]) if rows else None

    def latest_for_session(self, session_id: str) -> Transcript | None:
        rows = self.db.query("SELECT * FROM transcript WHERE session_id = ? "
                             "ORDER BY created_at DESC, rowid DESC LIMIT 1", (session_id,))
        return self._map(rows[0]) if rows else None

    def recent(self, limit: int = 10) -> list[Transcript]:
        rows = self.db.query("SELECT * FROM transcript ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [self._map(r) for r in rows]

    @staticmethod
    def _map(row: sqlite3.Row) -> Transcript:
        return _from_row(Transcript, row, {"origin": TranscriptOrigin, "status": TranscriptStatus})

    # --- tronçons (reprise) et segments ----------------------------------------------------
    def save_chunk(self, transcript_id: str, chunk_index: int, segments: list[TranscriptSegment]) -> None:
        """Enregistre un tronçon terminé et ses segments de façon atomique."""
        with self.db.lock:
            self.db.conn.execute("BEGIN")
            try:
                self.db.conn.execute("DELETE FROM transcript_segment WHERE transcript_id = ? AND chunk_index = ?",
                                     (transcript_id, chunk_index))
                for segment in segments:
                    self.db.insert("transcript_segment", segment)
                self.db.conn.execute("INSERT OR REPLACE INTO transcript_chunk VALUES (?, ?, ?)",
                                     (transcript_id, chunk_index, now_iso()))
                self.db.conn.execute("COMMIT")
            except Exception:
                self.db.conn.execute("ROLLBACK")
                raise

    def completed_chunks(self, transcript_id: str) -> set[int]:
        rows = self.db.query("SELECT chunk_index FROM transcript_chunk WHERE transcript_id = ?",
                             (transcript_id,))
        return {int(r[0]) for r in rows}

    def segments(self, transcript_id: str) -> list[TranscriptSegment]:
        rows = self.db.query("SELECT * FROM transcript_segment WHERE transcript_id = ? ORDER BY seq",
                             (transcript_id,))
        return [_from_row(TranscriptSegment, r) for r in rows]

    def replace_segments(self, transcript_id: str, segments: list[TranscriptSegment]) -> None:
        with self.db.lock:
            self.db.conn.execute("BEGIN")
            try:
                self.db.conn.execute("DELETE FROM transcript_segment WHERE transcript_id = ?", (transcript_id,))
                for segment in segments:
                    self.db.insert("transcript_segment", segment)
                self.db.conn.execute("COMMIT")
            except Exception:
                self.db.conn.execute("ROLLBACK")
                raise

    def update_segment_text(self, segment_id: str, text: str) -> None:
        # Le texte d'origine est conservé lors de la première correction
        self.db.execute("UPDATE transcript_segment SET original_text = COALESCE(original_text, text), "
                        "text = ? WHERE id = ?", (text, segment_id))

    def update_segment_speaker(self, segment_id: str, speaker: str) -> None:
        self.db.execute("UPDATE transcript_segment SET speaker = ? WHERE id = ?", (speaker, segment_id))


class SummaryRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, summary: MeetingSummary, actions: list[ActionItem]) -> None:
        self.db.insert("meeting_summary", summary)
        for action in actions:
            self.db.insert("action_item", action)

    def save(self, summary: MeetingSummary, actions: list[ActionItem]) -> None:
        summary.updated_at = now_iso()
        self.db.update("meeting_summary", summary)
        self.db.execute("DELETE FROM action_item WHERE summary_id = ?", (summary.id,))
        for action in actions:
            self.db.insert("action_item", action)

    def latest_for_session(self, session_id: str) -> MeetingSummary | None:
        rows = self.db.query("SELECT * FROM meeting_summary WHERE session_id = ? "
                             "ORDER BY created_at DESC, rowid DESC LIMIT 1", (session_id,))
        return _from_row(MeetingSummary, rows[0]) if rows else None

    def recent(self, limit: int = 10) -> list[MeetingSummary]:
        rows = self.db.query("SELECT * FROM meeting_summary ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [_from_row(MeetingSummary, r) for r in rows]

    def actions(self, summary_id: str) -> list[ActionItem]:
        rows = self.db.query("SELECT * FROM action_item WHERE summary_id = ? ORDER BY rowid", (summary_id,))
        return [_from_row(ActionItem, r) for r in rows]


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_all(self) -> dict[str, Any]:
        rows = self.db.query("SELECT key, value_json FROM application_settings")
        return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def set(self, key: str, value: Any) -> None:
        self.db.execute("INSERT INTO application_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
                        "updated_at = excluded.updated_at", (key, json.dumps(value), now_iso()))
