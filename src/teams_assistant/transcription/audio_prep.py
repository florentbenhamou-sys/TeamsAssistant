"""Préparation de l'audio : décodage 16 kHz mono, mixage, découpage aux silences."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from teams_assistant.transcription.types import SAMPLE_RATE, Samples, TranscriptionError

CHUNK_TARGET_S = 300.0  # tronçons d'environ 5 minutes : reprise possible tronçon par tronçon
CHUNK_SEARCH_S = 20.0  # fenêtre de recherche du point le plus silencieux autour de la cible
ENERGY_FRAME_S = 0.25


def load_audio(path: Path) -> Samples:
    """Décode n'importe quel format lisible par PyAV (wav, mp3, m4a, mp4…) en 16 kHz mono.

    Décodeur propre plutôt que faster_whisper.decode_audio : ce dernier (v1.2.1) utilise une
    option retirée de PyAV 19 (constaté sur le poste).
    """
    if not path.exists():
        raise TranscriptionError(f"Fichier audio introuvable : {path}")
    try:
        samples = _decode_with_av(path)
    except TranscriptionError:
        raise
    except Exception as exc:  # PyAV lève des erreurs variées selon le format
        raise TranscriptionError(f"Décodage impossible de {path.name} : {exc}") from exc
    if samples.size == 0:
        raise TranscriptionError(f"Le fichier {path.name} ne contient aucun échantillon audio.")
    return samples


def _decode_with_av(path: Path) -> Samples:
    try:
        import av
    except ImportError as exc:
        raise TranscriptionError("PyAV n'est pas installé (scripts\\setup.ps1).") from exc
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    parts: list[np.ndarray] = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise TranscriptionError(f"{path.name} ne contient pas de piste audio.")
        for frame in container.decode(audio=0):
            parts.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
        parts.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return (np.concatenate(parts).astype(np.float32) / 32768.0).astype(np.float32)


def mix(tracks: list[Samples]) -> Samples:
    """Additionne des pistes alignées sur la même origine, en évitant la saturation."""
    length = max(len(t) for t in tracks)
    mixed = np.zeros(length, dtype=np.float32)
    for track in tracks:
        mixed[: len(track)] += track
    peak = float(np.abs(mixed).max(initial=0.0))
    return mixed / peak if peak > 1.0 else mixed


def quietest_offset(window: Samples, rate: int = SAMPLE_RATE) -> int:
    """Position (en échantillons) du centre de la trame la moins énergétique."""
    frame = max(1, int(ENERGY_FRAME_S * rate))
    count = len(window) // frame
    if count == 0:
        return len(window) // 2
    energy = np.square(window[: count * frame].reshape(count, frame)).mean(axis=1)
    return int(np.argmin(energy)) * frame + frame // 2


def split_bounds(samples: Samples, rate: int = SAMPLE_RATE, target_s: float = CHUNK_TARGET_S,
                 search_s: float = CHUNK_SEARCH_S) -> list[tuple[int, int]]:
    """Découpe en tronçons d'environ target_s secondes, coupés au point le plus silencieux."""
    total, bounds = len(samples), [0]
    target, search = int(target_s * rate), int(min(search_s, target_s / 4) * rate)
    while total - bounds[-1] > target + search:
        low = bounds[-1] + target - search
        window = samples[low: low + 2 * search]
        bounds.append(low + quietest_offset(window, rate))
    bounds.append(total)
    return list(zip(bounds[:-1], bounds[1:]))
