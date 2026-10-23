"""Backend principal : WASAPI via PyAudioWPatch (fork de PyAudio avec loopback)."""

from __future__ import annotations

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

log = get_logger("audio.pyaudio")
BACKEND_NAME = "wasapi-pyaudio"
FRAMES_PER_BUFFER = 1024


def _import_pyaudio() -> Any:
    try:
        import pyaudiowpatch
    except ImportError as exc:  # pragma: no cover - dépend de l'installation
        raise CaptureError("PyAudioWPatch n'est pas installé.",
                           "Relancez scripts\\setup.ps1 ou utilisez le backend 'soundcard'.") from exc
    return pyaudiowpatch


class PyAudioStream:
    """Flux en mode callback : PortAudio appelle _callback depuis son propre thread."""

    def __init__(self, pa_module: Any, pa: Any, device: AudioDevice, on_block: BlockCallback) -> None:
        self._pa_module = pa_module
        self._pa = pa
        self._on_block = on_block
        self.sample_rate = device.sample_rate
        self.channels = device.channels
        self._stream = pa.open(format=pa_module.paInt16, channels=self.channels,
                               rate=self.sample_rate, input=True,
                               frames_per_buffer=FRAMES_PER_BUFFER,
                               input_device_index=int(device.device_id),
                               stream_callback=self._callback, start=False)

    def _callback(self, data: bytes | None, frames: int, _info: Any, _status: int) -> tuple[None, int]:
        if data:
            block = np.frombuffer(data, dtype=np.int16).reshape(-1, self.channels).copy()
            self._on_block(block)
        return None, self._pa_module.paContinue

    def start(self) -> None:
        self._stream.start_stream()

    def is_alive(self) -> bool:
        try:
            return bool(self._stream.is_active())
        except OSError:
            return False

    def close(self) -> None:
        try:
            if self._stream.is_active():
                self._stream.stop_stream()
            self._stream.close()
        except OSError as exc:
            log.warning("Fermeture du flux incomplète : %s", exc)
        finally:
            self._pa.terminate()


class PyAudioBackend:
    """Énumère les périphériques WASAPI (entrées et loopbacks) et ouvre les flux."""

    name = BACKEND_NAME

    def list_devices(self) -> list[AudioDevice]:
        pa_module = _import_pyaudio()
        pa = pa_module.PyAudio()
        try:
            return self._collect(pa_module, pa)
        finally:
            pa.terminate()

    def _collect(self, pa_module: Any, pa: Any) -> list[AudioDevice]:
        try:
            wasapi = pa.get_host_api_info_by_type(pa_module.paWASAPI)
        except OSError as exc:
            raise CaptureError("WASAPI indisponible sur ce poste.",
                               "Vérifiez le service Windows Audio (audiosrv).") from exc
        default_in = wasapi.get("defaultInputDevice", -1)
        default_out_name = self._default_output_name(pa, wasapi)
        devices: list[AudioDevice] = []
        for info in pa.get_device_info_generator_by_host_api(host_api_index=wasapi["index"]):
            device = self._to_device(info, default_in, default_out_name)
            if device is not None:
                devices.append(device)
        return devices

    @staticmethod
    def _default_output_name(pa: Any, wasapi: dict[str, Any]) -> str:
        index = wasapi.get("defaultOutputDevice", -1)
        return str(pa.get_device_info_by_index(index)["name"]) if index >= 0 else ""

    @staticmethod
    def _to_device(info: dict[str, Any], default_in: int, default_out_name: str) -> AudioDevice | None:
        if int(info["maxInputChannels"]) <= 0:
            return None  # sortie pure : capturée via son périphérique [Loopback]
        is_loop = bool(info.get("isLoopbackDevice"))
        name = str(info["name"]).replace(" [Loopback]", "")
        is_default = name == default_out_name if is_loop else int(info["index"]) == default_in
        return AudioDevice(backend=BACKEND_NAME, device_id=str(info["index"]), name=name,
                           kind=DeviceKind.LOOPBACK if is_loop else DeviceKind.INPUT,
                           channels=min(int(info["maxInputChannels"]), 2),
                           sample_rate=int(info["defaultSampleRate"]), is_default=is_default)

    def open_stream(self, device: AudioDevice, on_block: BlockCallback) -> AudioStream:
        pa_module = _import_pyaudio()
        pa = pa_module.PyAudio()
        resolved = self._resolve(device)
        try:
            return PyAudioStream(pa_module, pa, resolved, on_block)
        except OSError as exc:
            pa.terminate()
            raise CaptureError(f"Impossible d'ouvrir « {device.name} » : {exc}",
                               "Le périphérique est peut-être débranché, désactivé ou utilisé en mode "
                               "exclusif par une autre application (Paramètres son > Propriétés > "
                               "Avancé > décocher « Autoriser les applications à prendre le contrôle "
                               "exclusif »).") from exc

    def _resolve(self, device: AudioDevice) -> AudioDevice:
        # Les index PortAudio changent quand on branche/débranche : on re-résout par nom et type
        for candidate in self.list_devices():
            if candidate.name == device.name and candidate.kind is device.kind:
                return candidate
        raise CaptureError(f"Périphérique introuvable : « {device.name} ».",
                           "Rebranchez-le ou sélectionnez un autre périphérique, puis actualisez la liste.")
