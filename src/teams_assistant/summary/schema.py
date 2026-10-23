"""Structure du compte rendu, commune à tous les générateurs.

Chaque élément porte :
- `kind` : « fait » (énoncé dans la transcription), « interprétation » (déduction) ou
  « extrait » (citation brute sélectionnée automatiquement) ;
- `refs` : numéros des segments de transcription d'où il provient (traçabilité).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from teams_assistant.models import Participant, TranscriptSegment

FACT, INTERPRETATION, EXTRACT = "fait", "interprétation", "extrait"

# Clé interne -> titre affiché, dans l'ordre du modèle de compte rendu
SECTIONS: list[tuple[str, str]] = [
    ("context", "Contexte et objectif"),
    ("executive_summary", "Résumé exécutif"),
    ("topics", "Principaux sujets abordés"),
    ("decisions", "Décisions prises"),
    ("open_questions", "Questions ouvertes"),
    ("risks", "Difficultés, objections et risques"),
    ("commitments", "Engagements pris"),
    ("next_actions", "Prochaines actions"),
    ("validation_points", "Points nécessitant une validation humaine"),
]
SECTION_KEYS = [key for key, _ in SECTIONS]


@dataclass
class SummaryItem:
    text: str
    kind: str = FACT
    refs: list[int] = field(default_factory=list)
    speaker: str = ""  # provenance technique (source audio), pas une identité
    owner: str = ""  # uniquement si explicitement mentionné
    due: str = ""  # uniquement si explicitement mentionnée


@dataclass
class ParticipantEntry:
    name: str
    status: str  # "confirmée" | "incertaine"
    origin: str


@dataclass
class SummaryContent:
    title: str
    date: str = ""
    duration: str = ""
    participants: list[ParticipantEntry] = field(default_factory=list)
    sections: dict[str, list[SummaryItem]] = field(default_factory=lambda: {k: [] for k in SECTION_KEYS})
    generator_notice: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SummaryContent:
        sections = {key: [SummaryItem(**item) for item in data.get("sections", {}).get(key, [])]
                    for key in SECTION_KEYS}
        participants = [ParticipantEntry(**p) for p in data.get("participants", [])]
        return cls(title=str(data.get("title", "")), date=str(data.get("date", "")),
                   duration=str(data.get("duration", "")), participants=participants,
                   sections=sections, generator_notice=str(data.get("generator_notice", "")))


@dataclass
class SummaryInput:
    title: str
    date: str
    duration_s: float
    participants: list[Participant]
    segments: list[TranscriptSegment]


def format_duration(seconds: float) -> str:
    if seconds <= 0:
        return ""
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def participant_entries(data: SummaryInput) -> list[ParticipantEntry]:
    """Participants connus + libellés techniques des sources audio (jamais de nom deviné)."""
    entries = [ParticipantEntry(p.display_name, "confirmée" if p.identity.value == "confirmed" else "incertaine",
                                p.origin) for p in data.participants]
    labels = sorted({s.speaker for s in data.segments if s.speaker})
    entries.extend(ParticipantEntry(label, "incertaine", "source audio (séparation technique)")
                   for label in labels)
    return entries
