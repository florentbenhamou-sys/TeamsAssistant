"""Moteur local faster-whisper (CTranslate2). Aucun audio ne quitte le poste.

Le modèle est téléchargé une seule fois depuis Hugging Face (gratuit) dans le dossier
models des données locales, puis utilisé hors connexion.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from teams_assistant.logging_setup import get_logger
from teams_assistant.transcription.types import (
    DetectedLanguage,
    RawSegment,
    Samples,
    TranscriptionCancelled,
    TranscriptionError,
    TranscriptionOptions,
    WordStamp,
)

log = get_logger("transcription.whisper")


@dataclass(frozen=True)
class QualityProfile:
    key: str
    label: str
    model: str
    compute_type: str
    beam_size: int
    approx_download_mb: int


PROFILES: dict[str, QualityProfile] = {
    "rapide": QualityProfile("rapide", "Rapide (small)", "small", "int8", 1, 480),
    "equilibre": QualityProfile("equilibre", "Équilibré (medium)", "medium", "int8", 3, 1500),
    "precis": QualityProfile("precis", "Précis (large-v3-turbo)", "large-v3-turbo", "int8", 5, 1600),
}


def get_profile(key: str) -> QualityProfile:
    if key not in PROFILES:
        raise TranscriptionError(f"Profil inconnu : {key} (choix : {', '.join(PROFILES)})")
    return PROFILES[key]


class FasterWhisperEngine:
    name = "faster-whisper"

    def __init__(self, models_dir: Path, device: str = "cpu", cpu_threads: int | None = None) -> None:
        self.models_dir = models_dir
        self.device = device
        self.cpu_threads = cpu_threads or max(1, (os.cpu_count() or 2) // 2)
        self._models: dict[str, Any] = {}
        self._loaded_name = ""

    @property
    def model_name(self) -> str:
        return self._loaded_name

    def _load(self, profile: QualityProfile) -> Any:
        if profile.model in self._models:
            return self._models[profile.model]
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError("faster-whisper n'est pas installé (scripts\\setup.ps1).") from exc
        log.info("Chargement du modèle %s (%s, %s)", profile.model, self.device, profile.compute_type)
        try:
            model = WhisperModel(profile.model, device=self.device, compute_type=profile.compute_type,
                                 cpu_threads=self.cpu_threads, download_root=str(self.models_dir))
        except Exception as exc:
            raise TranscriptionError(
                f"Chargement du modèle « {profile.model} » impossible : {exc}. Au premier usage, "
                f"une connexion Internet est nécessaire (~{profile.approx_download_mb} Mo).") from exc
        self._models[profile.model] = model
        return model

    def transcribe(self, samples: Samples, options: TranscriptionOptions,
                   cancel: threading.Event) -> tuple[DetectedLanguage, Iterator[RawSegment]]:
        profile = get_profile(options.profile)
        model = self._load(profile)
        self._loaded_name = profile.model
        segments, info = model.transcribe(
            samples, language=options.language, beam_size=profile.beam_size,
            vad_filter=options.vad, vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=True,  # bornes de segment plus précises (mesuré sur l'échantillon)
            condition_on_previous_text=False)  # limite les boucles de répétition sur les longs silences
        language = DetectedLanguage(info.language, float(info.language_probability))
        return language, self._iterate(segments, cancel)

    @staticmethod
    def _iterate(segments: Any, cancel: threading.Event) -> Iterator[RawSegment]:
        for seg in segments:
            if cancel.is_set():
                raise TranscriptionCancelled("Transcription interrompue par l'utilisateur.")
            words = getattr(seg, "words", None) or []
            start = float(words[0].start) if words else float(seg.start)
            end = float(words[-1].end) if words else float(seg.end)
            yield RawSegment(start_s=start, end_s=end, text=seg.text.strip(),
                             avg_logprob=float(seg.avg_logprob),
                             no_speech_prob=float(seg.no_speech_prob),
                             compression_ratio=float(seg.compression_ratio),
                             words=tuple(WordStamp(float(w.start), float(w.end), str(w.word)) for w in words))
