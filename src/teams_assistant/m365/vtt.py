"""Lecture des transcripts Teams au format WebVTT.

Les noms d'intervenants proviennent de Teams lui-même (balises <v Nom>) : ce sont des
identités fournies par le service, contrairement aux libellés techniques de la transcription locale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CUE_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})")
VOICE = re.compile(r"<v\s+([^>]+)>(.*?)(</v>|$)", re.S)


@dataclass(frozen=True)
class VttCue:
    start_s: float
    end_s: float
    speaker: str
    text: str


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _cue(block: list[str]) -> VttCue | None:
    for i, line in enumerate(block):
        match = CUE_TIME.search(line)
        if match:
            payload = " ".join(block[i + 1:]).strip()
            voice = VOICE.search(payload)
            speaker, text = (voice.group(1).strip(), voice.group(2)) if voice else ("", payload)
            text = re.sub(r"<[^>]+>", "", text).strip()
            if not text:
                return None
            g = match.groups()
            return VttCue(_seconds(*g[:4]), _seconds(*g[4:]), speaker, text)
    return None


def parse_vtt(content: str) -> list[VttCue]:
    blocks = [b.splitlines() for b in re.split(r"\r?\n\s*\r?\n", content.strip())]
    return [cue for cue in (_cue(b) for b in blocks if b and not b[0].startswith("WEBVTT")) if cue]
