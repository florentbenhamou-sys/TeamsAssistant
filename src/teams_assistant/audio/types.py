"""Types communs du module de capture audio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import numpy as np
import numpy.typing as npt

# Bloc audio : tableau int16 de forme (trames, canaux)
AudioBlock = npt.NDArray[np.int16]
BlockCallback = Callable[[AudioBlock], None]


class DeviceKind(StrEnum):
    LOOPBACK = "loopback"  # son diffusé par le PC (participants distants)
    INPUT = "input"  # microphone


@dataclass(frozen=True)
class AudioDevice:
    """Périphérique audio exploitable pour la capture."""

    backend: str
    device_id: str
    name: str
    kind: DeviceKind
    channels: int
    sample_rate: int
    is_default: bool = False

    @property
    def label(self) -> str:
        kind = "Son du PC (loopback)" if self.kind is DeviceKind.LOOPBACK else "Microphone"
        default = " — par défaut" if self.is_default else ""
        return f"{kind} : {self.name}{default}"


class CaptureError(RuntimeError):
    """Erreur de capture, accompagnée d'une consigne de diagnostic pour l'utilisateur."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class AudioStream(Protocol):
    """Flux ouvert sur un périphérique ; les blocs arrivent via le callback."""

    sample_rate: int
    channels: int

    def start(self) -> None: ...

    def is_alive(self) -> bool: ...

    def close(self) -> None: ...


class CaptureBackend(Protocol):
    """Abstraction d'une bibliothèque de capture (PyAudioWPatch, soundcard, simulateur de test)."""

    name: str

    def list_devices(self) -> list[AudioDevice]: ...

    def open_stream(self, device: AudioDevice, on_block: BlockCallback) -> AudioStream: ...
