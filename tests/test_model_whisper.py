"""Transcription réelle de l'échantillon synthétique — lancé avec : pytest -m model

Nécessite le modèle « small » (téléchargé au premier lancement, ~480 Mo).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teams_assistant.config import AppPaths
from teams_assistant.transcription.pipeline import TranscriptionPipeline
from teams_assistant.transcription.types import AudioSource, SourceKind, TranscriptionOptions
from teams_assistant.transcription.whisper_engine import FasterWhisperEngine

pytestmark = pytest.mark.model
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "meeting_demo"


def test_sample_meeting_is_transcribed_in_french() -> None:
    engine = FasterWhisperEngine(AppPaths.default().ensure().models)
    sources = [AudioSource(SAMPLE / "system.wav", SourceKind.SYSTEM),
               AudioSource(SAMPLE / "microphone.wav", SourceKind.MICROPHONE)]
    result = TranscriptionPipeline(engine).run(sources, TranscriptionOptions(language=None))
    text = " ".join(s.text for s in result.segments).lower()
    assert result.language == "fr"
    for keyword in ["atlas", "lyon", "novembre", "hébergement", "vendredi"]:
        assert keyword in text, keyword
    first_mic = next(s for s in result.segments if s.source is SourceKind.MICROPHONE and "très bien" in s.text.lower())
    assert abs(first_mic.start_s - 17.63) < 1.5  # vérité terrain : timeline.json
