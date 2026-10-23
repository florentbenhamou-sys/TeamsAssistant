"""Connexion SQLite et schéma versionné.

Toutes les requêtes du projet sont paramétrées (jamais de concaténation de valeurs).
Le schéma reste portable vers PostgreSQL (types simples, clés UUID texte).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meeting_session (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    duration_s REAL NOT NULL DEFAULT 0,
    outlook_event_id TEXT,
    outlook_start TEXT,
    outlook_end TEXT,
    join_url TEXT,
    consent_confirmed_at TEXT,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audio_file (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES meeting_session(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    owned INTEGER NOT NULL,
    duration_s REAL NOT NULL DEFAULT 0,
    has_signal INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS transcript (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES meeting_session(id) ON DELETE CASCADE,
    origin TEXT NOT NULL,
    status TEXT NOT NULL,
    engine TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    profile TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT '',
    language_probability REAL NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transcript_chunk (
    transcript_id TEXT NOT NULL REFERENCES transcript(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (transcript_id, chunk_index)
);
CREATE TABLE IF NOT EXISTS transcript_segment (
    id TEXT PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES transcript(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    source TEXT NOT NULL,
    speaker TEXT,
    text TEXT NOT NULL,
    original_text TEXT,
    confidence REAL NOT NULL DEFAULT 1,
    uncertain INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_segment_transcript ON transcript_segment(transcript_id, seq);
CREATE TABLE IF NOT EXISTS participant (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES meeting_session(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    identity TEXT NOT NULL,
    origin TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meeting_summary (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES meeting_session(id) ON DELETE CASCADE,
    transcript_id TEXT NOT NULL REFERENCES transcript(id) ON DELETE CASCADE,
    generator TEXT NOT NULL,
    content_json TEXT NOT NULL,
    validated INTEGER NOT NULL DEFAULT 0,
    validated_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_item (
    id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL REFERENCES meeting_summary(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    due TEXT NOT NULL DEFAULT '',
    segment_refs_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS application_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_file: Path) -> sqlite3.Connection:
    """Ouvre la base, active les clés étrangères et applique les migrations."""
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version < 1:
        conn.executescript(SCHEMA_V1)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")  # constante interne, pas une saisie
