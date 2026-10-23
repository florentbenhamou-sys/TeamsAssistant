"""Sélection du backend de capture, avec repli automatique."""

from __future__ import annotations

from teams_assistant.audio.pyaudio_backend import PyAudioBackend
from teams_assistant.audio.soundcard_backend import SoundcardBackend
from teams_assistant.audio.types import AudioDevice, CaptureBackend, CaptureError, DeviceKind
from teams_assistant.logging_setup import get_logger

log = get_logger("audio.backends")
BACKENDS: dict[str, type[PyAudioBackend] | type[SoundcardBackend]] = {
    PyAudioBackend.name: PyAudioBackend,
    SoundcardBackend.name: SoundcardBackend,
}
DEFAULT_ORDER = [PyAudioBackend.name, SoundcardBackend.name]


def get_backend(name: str | None = None) -> CaptureBackend:
    """Renvoie le backend demandé, ou le premier qui sait énumérer les périphériques."""
    if name:
        if name not in BACKENDS:
            raise CaptureError(f"Backend inconnu : {name}", f"Choix possibles : {', '.join(BACKENDS)}")
        return BACKENDS[name]()
    failures: list[str] = []
    for candidate in DEFAULT_ORDER:
        backend = BACKENDS[candidate]()
        try:
            backend.list_devices()
            return backend
        except CaptureError as exc:
            failures.append(f"{candidate} : {exc}")
            log.warning("Backend %s indisponible : %s", candidate, exc)
    raise CaptureError("Aucun backend audio utilisable.", " | ".join(failures))


def default_device(devices: list[AudioDevice], kind: DeviceKind) -> AudioDevice | None:
    matching = [d for d in devices if d.kind is kind]
    return next((d for d in matching if d.is_default), matching[0] if matching else None)


def find_device(devices: list[AudioDevice], key: str, kind: DeviceKind | None = None) -> AudioDevice:
    """Recherche par identifiant exact ou par fragment de nom (insensible à la casse)."""
    pool = [d for d in devices if kind is None or d.kind is kind]
    for device in pool:
        if device.device_id == key:
            return device
    matches = [d for d in pool if key.lower() in d.name.lower()]
    if len(matches) == 1:
        return matches[0]
    detail = "plusieurs correspondances" if matches else "aucune correspondance"
    raise CaptureError(f"Périphérique « {key} » : {detail}.",
                       "Utilisez la commande 'list' pour obtenir l'identifiant exact.")
