"""Lecture d'un bip de test discret sur une sortie, pour l'autotest du loopback."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from teams_assistant.audio.types import CaptureError

TONE_AMPLITUDE = 0.05  # environ -26 dBFS : audible mais discret
TONE_FREQUENCY_HZ = 440.0


def make_tone(seconds: float, sample_rate: int, channels: int = 2) -> bytes:
    """Sinusoïde 440 Hz avec fondu d'entrée/sortie, en PCM 16 bits entrelacé."""
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    envelope = np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.05) if t.size else t
    wave = TONE_AMPLITUDE * envelope * np.sin(2 * np.pi * TONE_FREQUENCY_HZ * t)
    pcm = (wave * 32767).astype(np.int16)
    return np.repeat(pcm[:, None], channels, axis=1).tobytes()


def _find_output(pa: Any, pa_module: Any, output_name: str) -> dict[str, Any]:
    wasapi = pa.get_host_api_info_by_type(pa_module.paWASAPI)
    for info in pa.get_device_info_generator_by_host_api(host_api_index=wasapi["index"]):
        if info["maxOutputChannels"] > 0 and not info.get("isLoopbackDevice") \
                and info["name"] == output_name:
            return dict(info)
    raise CaptureError(f"Sortie « {output_name} » introuvable pour le bip de test.")


def play_tone(output_name: str, seconds: float) -> None:
    """Joue le bip de façon bloquante sur la sortie nommée (WASAPI partagé)."""
    import pyaudiowpatch as pa_module

    pa = pa_module.PyAudio()
    try:
        info = _find_output(pa, pa_module, output_name)
        rate = int(info["defaultSampleRate"])
        stream = pa.open(format=pa_module.paInt16, channels=2, rate=rate, output=True,
                         output_device_index=int(info["index"]))
        stream.write(make_tone(seconds, rate))
        stream.stop_stream()
        stream.close()
    finally:
        pa.terminate()


def play_tone_async(output_name: str, seconds: float, delay: float = 0.5) -> threading.Thread:
    """Joue le bip après un court délai, pour laisser la capture démarrer."""
    def runner() -> None:
        threading.Event().wait(delay)
        play_tone(output_name, seconds)

    thread = threading.Thread(target=runner, daemon=True, name="test-tone")
    thread.start()
    return thread
