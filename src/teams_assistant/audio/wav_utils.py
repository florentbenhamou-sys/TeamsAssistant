"""Écriture et vérification des fichiers WAV PCM 16 bits."""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from teams_assistant.audio.types import AudioBlock

# Seuil en dessous duquel un échantillon est considéré comme du silence (~ -50 dBFS)
SILENCE_THRESHOLD = 100
ANALYSIS_CHUNK_FRAMES = 65536


class WavWriter:
    """Écrit un WAV de façon incrémentale ; l'en-tête est mis à jour à chaque bloc,
    le fichier reste donc lisible même si l'application s'arrête brutalement."""

    def __init__(self, path: Path, sample_rate: int, channels: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.sample_rate = sample_rate
        self.channels = channels
        self.frames_written = 0
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(channels)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    def write(self, block: AudioBlock) -> None:
        if block.shape[1] != self.channels:
            raise ValueError(f"Bloc à {block.shape[1]} canaux pour un fichier à {self.channels}")
        self._wav.writeframes(np.ascontiguousarray(block, dtype=np.int16).tobytes())
        self.frames_written += block.shape[0]

    def write_silence(self, frames: int) -> None:
        if frames > 0:
            self.write(np.zeros((frames, self.channels), dtype=np.int16))

    def close(self) -> None:
        self._wav.close()


@dataclass(frozen=True)
class WavReport:
    """Résultat de vérification d'un fichier audio."""

    path: Path
    readable: bool
    error: str = ""
    sample_rate: int = 0
    channels: int = 0
    duration_s: float = 0.0
    peak_dbfs: float = -math.inf
    rms_dbfs: float = -math.inf
    non_silent_ratio: float = 0.0

    @property
    def has_signal(self) -> bool:
        # Signal réel : crête au-dessus de -50 dBFS et au moins 1 % d'échantillons non silencieux
        return self.readable and self.peak_dbfs > -50.0 and self.non_silent_ratio >= 0.01

    def summary(self) -> str:
        if not self.readable:
            return f"Fichier illisible : {self.error}"
        signal = "signal détecté" if self.has_signal else "AUCUN SIGNAL UTILE (silence)"
        return (f"{self.duration_s:.1f} s, {self.sample_rate} Hz, {self.channels} canal(aux), "
                f"crête {self.peak_dbfs:.1f} dBFS, RMS {self.rms_dbfs:.1f} dBFS, "
                f"{self.non_silent_ratio:.0%} non silencieux — {signal}")


def to_dbfs(value: float) -> float:
    return 20 * math.log10(value / 32768.0) if value > 0 else -math.inf


def block_level_dbfs(block: AudioBlock) -> float:
    """Niveau RMS d'un bloc, utilisé pour le vumètre."""
    if block.size == 0:
        return -math.inf
    return to_dbfs(float(np.sqrt(np.mean(block.astype(np.float64) ** 2))))


def analyze_wav(path: Path) -> WavReport:
    """Vérifie qu'un WAV est lisible et mesure son contenu par morceaux (faible mémoire)."""
    try:
        with wave.open(str(path), "rb") as wav:
            return _measure(path, wav)
    except (OSError, wave.Error, EOFError) as exc:
        return WavReport(path=path, readable=False, error=str(exc))


def _measure(path: Path, wav: wave.Wave_read) -> WavReport:
    if wav.getsampwidth() != 2:
        return WavReport(path=path, readable=False, error="format non PCM 16 bits")
    rate, channels = wav.getframerate(), wav.getnchannels()
    peak, square_sum, loud, total = 0, 0.0, 0, 0
    while chunk := wav.readframes(ANALYSIS_CHUNK_FRAMES):
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.int32)
        peak = max(peak, int(np.abs(samples).max(initial=0)))
        square_sum += float(np.sum(samples.astype(np.float64) ** 2))
        loud += int(np.count_nonzero(np.abs(samples) > SILENCE_THRESHOLD))
        total += samples.size
    rms = math.sqrt(square_sum / total) if total else 0.0
    return WavReport(path=path, readable=True, sample_rate=rate, channels=channels,
                     duration_s=(total / channels / rate) if rate and channels else 0.0,
                     peak_dbfs=to_dbfs(peak), rms_dbfs=to_dbfs(rms),
                     non_silent_ratio=(loud / total) if total else 0.0)
