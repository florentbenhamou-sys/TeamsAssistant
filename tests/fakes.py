"""Doublures de test : backend audio piloté manuellement et horloge contrôlée.

Ces classes n'existent que dans les tests ; l'application n'affiche jamais de capture simulée.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from teams_assistant.audio.types import AudioBlock, AudioDevice, BlockCallback, CaptureError, DeviceKind


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeStream:
    def __init__(self, device: AudioDevice, on_block: BlockCallback) -> None:
        self.sample_rate = device.sample_rate
        self.channels = device.channels
        self.on_block = on_block
        self.alive = False
        self.closed = False

    def start(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def close(self) -> None:
        self.alive = False
        self.closed = True

    def emit(self, block: AudioBlock) -> None:
        self.on_block(block)


class FakeBackend:
    name = "fake"

    def __init__(self, devices: list[AudioDevice] | None = None, fail_open: bool = False) -> None:
        self.devices = devices if devices is not None else default_devices()
        self.fail_open = fail_open
        self.streams: dict[DeviceKind, FakeStream] = {}

    def list_devices(self) -> list[AudioDevice]:
        return list(self.devices)

    def open_stream(self, device: AudioDevice, on_block: BlockCallback) -> FakeStream:
        if self.fail_open:
            raise CaptureError("ouverture refusée", "conseil")
        stream = FakeStream(device, on_block)
        self.streams[device.kind] = stream
        return stream


def default_devices() -> list[AudioDevice]:
    return [
        AudioDevice("fake", "1", "Haut-parleurs test", DeviceKind.LOOPBACK, 2, 16000, True),
        AudioDevice("fake", "2", "Micro test", DeviceKind.INPUT, 1, 16000, True),
    ]


class FakeSpeechEngine:
    """Moteur de transcription factice : renvoie un segment par seconde de signal non nul."""

    name = "fake-engine"

    def __init__(self, language: str = "fr", text: str = "bonjour", fail_after: int | None = None) -> None:
        self.language = language
        self.text = text
        self.calls = 0
        self.fail_after = fail_after

    @property
    def model_name(self) -> str:
        return "fake-model"

    def transcribe(self, samples: Any, options: Any, cancel: Any) -> tuple[Any, Any]:
        from teams_assistant.transcription.types import DetectedLanguage, RawSegment, TranscriptionCancelled
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise TranscriptionCancelled("interruption simulée")
        seconds = len(samples) // 16000
        raws = [RawSegment(float(i), float(i) + 0.9, f"{self.text} {i}", -0.2, 0.01, 1.2)
                for i in range(seconds) if np.abs(samples[i * 16000:(i + 1) * 16000]).max(initial=0) > 0.01]
        return DetectedLanguage(options.language or self.language, 0.99), iter(raws)


class FakeDiarizer:
    """Séparateur factice : voix 1 avant `switch_s`, voix 2 après ; mémorise les appels."""

    def __init__(self, switch_s: float = 2.0) -> None:
        self.switch_s = switch_s
        self.calls: list[tuple[int, int]] = []

    def assign(self, samples: Any, spans: Any, num_speakers: int = 0, progress: Any = None) -> list[int]:
        self.calls.append((len(spans), num_speakers))
        if progress:
            progress(1.0)
        return [1 if start < self.switch_s else 2 for start, _end in spans]


def write_wav(path: Any, samples: Any, rate: int = 16000) -> None:
    import wave
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())


def tone(seconds: float, rate: int = 16000, amplitude: float = 0.3) -> Any:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def sine_block(seconds: float, rate: int = 16000, channels: int = 2, amplitude: float = 0.3) -> AudioBlock:
    t = np.arange(int(seconds * rate)) / rate
    mono = (amplitude * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    return np.repeat(mono[:, None], channels, axis=1)
