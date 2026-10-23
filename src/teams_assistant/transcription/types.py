"""Types du module de transcription (indépendants du moteur utilisé)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

SAMPLE_RATE = 16000
Samples = npt.NDArray[np.float32]


class SourceKind(StrEnum):
    SYSTEM = "system"
    MICROPHONE = "microphone"
    IMPORTED = "imported"
    MIXED = "mixed"
    TEAMS = "teams"  # transcript officiel récupéré via Microsoft Graph


# Libellés de provenance : séparation technique, jamais une identification de personne
SOURCE_LABELS: dict[SourceKind, str] = {
    SourceKind.SYSTEM: "Participants distants (son du PC)",
    SourceKind.MICROPHONE: "Micro local",
    SourceKind.IMPORTED: "Fichier importé",
    SourceKind.MIXED: "Audio mixé",
    SourceKind.TEAMS: "Transcript Teams",
}


class TranscriptionError(RuntimeError):
    pass


class TranscriptionCancelled(TranscriptionError):
    pass


@dataclass(frozen=True)
class AudioSource:
    path: Path
    kind: SourceKind


@dataclass(frozen=True)
class RawSegment:
    """Segment brut renvoyé par un moteur, horodaté relativement au tronçon traité."""

    start_s: float
    end_s: float
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 1.0


@dataclass(frozen=True)
class Segment:
    """Segment final, horodaté par rapport au début de l'enregistrement."""

    start_s: float
    end_s: float
    text: str
    source: SourceKind
    speaker: str | None
    confidence: float
    uncertain: bool
    chunk_index: int


@dataclass(frozen=True)
class TranscriptionOptions:
    language: str | None = "fr"  # None = détection automatique
    profile: str = "rapide"
    vad: bool = True
    separate_sources: bool = True  # False = mixage micro + système avant transcription


@dataclass(frozen=True)
class Progress:
    done_s: float
    total_s: float
    chunk_index: int
    chunk_count: int
    message: str = ""

    @property
    def ratio(self) -> float:
        return min(1.0, self.done_s / self.total_s) if self.total_s else 0.0


@dataclass
class TranscriptResult:
    language: str
    language_probability: float
    duration_s: float
    segments: list[Segment]
    engine: str
    model: str
    profile: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DetectedLanguage:
    code: str
    probability: float


ProgressCallback = Callable[[Progress], None]


class SpeechEngine(Protocol):
    """Interface d'un moteur de reconnaissance vocale."""

    name: str

    @property
    def model_name(self) -> str: ...

    def transcribe(self, samples: Samples, options: TranscriptionOptions,
                   cancel: threading.Event) -> tuple[DetectedLanguage, Iterator[RawSegment]]: ...
