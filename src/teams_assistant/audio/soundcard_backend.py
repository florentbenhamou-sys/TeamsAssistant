"""Backend de repli : bibliothèque soundcard (WASAPI via COM/cffi, sans PortAudio)."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from teams_assistant.audio.types import (
    AudioDevice,
    AudioStream,
    BlockCallback,
    CaptureError,
    DeviceKind,
)
from teams_assistant.logging_setup import get_logger

log = get_logger("audio.soundcard")
BACKEND_NAME = "wasapi-soundcard"
SAMPLE_RATE = 48000
BLOCK_FRAMES = 2048


def _import_soundcard() -> Any:
    try:
        import soundcard
    except Exception as exc:  # pragma: no cover - dépend de l'installation
        raise CaptureError("La bibliothèque soundcard est indisponible.", str(exc)) from exc
    return soundcard


class SoundcardStream:
    """Lecture bloquante dans un thread dédié, convertie en int16 pour le recorder."""

    def __init__(self, microphone: Any, device: AudioDevice, on_block: BlockCallback) -> None:
        self._microphone = microphone
        self._on_block = on_block
        self.sample_rate = SAMPLE_RATE
        self.channels = device.channels
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="soundcard-reader", daemon=True)
        self._failed = False

    def _run(self) -> None:
        try:
            with self._microphone.recorder(samplerate=self.sample_rate, channels=self.channels,
                                           blocksize=BLOCK_FRAMES) as recorder:
                while not self._stop.is_set():
                    data = recorder.record(numframes=BLOCK_FRAMES)
                    self._on_block(_float_to_int16(data))
        except Exception as exc:
            self._failed = True
            log.error("Lecture soundcard interrompue : %s", exc)

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive() and not self._failed

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)


def _float_to_int16(data: Any) -> np.ndarray[Any, np.dtype[np.int16]]:
    clipped = np.clip(np.asarray(data, dtype=np.float32), -1.0, 1.0)
    if clipped.ndim == 1:
        clipped = clipped[:, None]
    return (clipped * 32767).astype(np.int16)


class SoundcardBackend:
    name = BACKEND_NAME

    def list_devices(self) -> list[AudioDevice]:
        sc = _import_soundcard()
        default_speaker = sc.default_speaker().name
        default_mic = sc.default_microphone().id
        devices: list[AudioDevice] = []
        for mic in sc.all_microphones(include_loopback=True):
            loop = bool(mic.isloopback)
            devices.append(AudioDevice(
                backend=BACKEND_NAME, device_id=str(mic.id), name=str(mic.name),
                kind=DeviceKind.LOOPBACK if loop else DeviceKind.INPUT,
                channels=min(int(mic.channels), 2), sample_rate=SAMPLE_RATE,
                is_default=(mic.name == default_speaker) if loop else (mic.id == default_mic)))
        return devices

    def open_stream(self, device: AudioDevice, on_block: BlockCallback) -> AudioStream:
        sc = _import_soundcard()
        try:
            mic = sc.get_microphone(device.device_id, include_loopback=True)
        except IndexError as exc:
            raise CaptureError(f"Périphérique introuvable : « {device.name} ».",
                               "Actualisez la liste des périphériques.") from exc
        return SoundcardStream(mic, device, on_block)
