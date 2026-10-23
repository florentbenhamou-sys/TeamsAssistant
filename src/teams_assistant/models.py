"""Entités métier, indépendantes du stockage et de l'interface."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionStatus(StrEnum):
    DRAFT = "draft"
    RECORDED = "recorded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    SUMMARIZED = "summarized"
    ERROR = "error"


class TranscriptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class TranscriptOrigin(StrEnum):
    LOCAL = "local"  # transcription indépendante (faster-whisper)
    TEAMS_OFFICIAL = "teams_official"  # transcript récupéré via Microsoft Graph


class IdentityStatus(StrEnum):
    CONFIRMED = "confirmed"  # source fiable (invitation Outlook, saisie de l'utilisateur)
    UNCERTAIN = "uncertain"


@dataclass
class MeetingSession:
    title: str
    id: str = field(default_factory=new_id)
    status: SessionStatus = SessionStatus.DRAFT
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    ended_at: str | None = None
    duration_s: float = 0.0
    outlook_event_id: str | None = None
    outlook_start: str | None = None
    outlook_end: str | None = None
    join_url: str | None = None
    consent_confirmed_at: str | None = None
    notes: str = ""


@dataclass
class AudioFile:
    session_id: str
    kind: str  # system | microphone | imported
    path: str
    owned: bool  # True : fichier temporaire créé par l'application (supprimable)
    id: str = field(default_factory=new_id)
    duration_s: float = 0.0
    has_signal: bool = False
    created_at: str = field(default_factory=now_iso)
    deleted_at: str | None = None


@dataclass
class Transcript:
    session_id: str
    id: str = field(default_factory=new_id)
    origin: TranscriptOrigin = TranscriptOrigin.LOCAL
    status: TranscriptStatus = TranscriptStatus.IN_PROGRESS
    engine: str = ""
    model: str = ""
    profile: str = ""
    language: str = ""
    language_probability: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    options: dict[str, object] = field(default_factory=dict)  # options utilisées (condition de reprise)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class TranscriptSegment:
    transcript_id: str
    seq: int
    start_s: float
    end_s: float
    text: str
    source: str
    speaker: str | None = None
    confidence: float = 1.0
    uncertain: bool = False
    chunk_index: int = 0
    original_text: str | None = None  # texte d'origine conservé si l'utilisateur corrige
    id: str = field(default_factory=new_id)

    @property
    def edited(self) -> bool:
        return self.original_text is not None and self.original_text != self.text


@dataclass
class Participant:
    session_id: str
    display_name: str
    id: str = field(default_factory=new_id)
    email: str = ""
    identity: IdentityStatus = IdentityStatus.UNCERTAIN
    origin: str = "manual"  # outlook | manual | teams


@dataclass
class ActionItem:
    summary_id: str
    description: str
    id: str = field(default_factory=new_id)
    owner: str = ""  # vide si non mentionné explicitement
    due: str = ""  # vide si non mentionnée explicitement
    segment_refs: list[int] = field(default_factory=list)  # numéros de segments sources
    status: str = "open"


@dataclass
class MeetingSummary:
    session_id: str
    transcript_id: str
    content: dict[str, object]
    id: str = field(default_factory=new_id)
    generator: str = ""
    validated: bool = False
    validated_at: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
