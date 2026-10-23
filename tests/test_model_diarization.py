"""Séparation réelle des voix sur samples/two_voices — lancé avec : pytest -m model

Deux voix de synthèse différentes sur la même piste ; nécessite les modèles Whisper « small »
et TitaNet (téléchargés au premier lancement).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teams_assistant.config import AppPaths
from teams_assistant.transcription.diarization import EmbeddingDiarizer, ensure_model
from teams_assistant.transcription.pipeline import TranscriptionPipeline
from teams_assistant.transcription.types import AudioSource, SourceKind, TranscriptionOptions
from teams_assistant.transcription.whisper_engine import FasterWhisperEngine

pytestmark = pytest.mark.model
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "two_voices"


def _snapshot(*folders: Path) -> set[tuple[str, int]]:
    """Fichiers (chemin, taille) hors journaux, pour vérifier que rien n'est écrit pendant la séparation."""
    return {(str(p), p.stat().st_size) for folder in folders for p in folder.rglob("*")
            if p.is_file() and "logs" not in p.parts}


@pytest.mark.parametrize("speakers", [2, 0])
def test_two_voices_on_same_microphone_are_separated(speakers: int) -> None:
    paths = AppPaths.default().ensure()
    model = ensure_model(paths.models)
    pipeline = TranscriptionPipeline(FasterWhisperEngine(paths.models),
                                     diarizer_factory=lambda: EmbeddingDiarizer(model))
    before = _snapshot(paths.base, SAMPLE)
    result = pipeline.run([AudioSource(SAMPLE / "microphone.wav", SourceKind.IMPORTED)],
                          TranscriptionOptions(diarize=True, speakers_main=speakers))
    assert _snapshot(paths.base, SAMPLE) == before  # aucune empreinte vocale écrite sur le disque
    truth = json.loads((SAMPLE / "timeline.json").read_text(encoding="utf-8"))
    pairs = []  # (voix réelle, libellé attribué) pour chaque segment situé dans une réplique
    for seg in result.segments:
        middle = (seg.start_s + seg.end_s) / 2
        line = next((t for t in truth if t["start_s"] - 0.5 <= middle <= t["end_s"] + 0.5), None)
        if line:
            pairs.append((line["voice"], seg.speaker))
    mapping = {voice: {label for v, label in pairs if v == voice} for voice, _ in pairs}
    assert all(len(labels) == 1 for labels in mapping.values()), mapping  # une voix -> un seul libellé
    assert len({next(iter(labels)) for labels in mapping.values()}) == 2  # deux libellés distincts
