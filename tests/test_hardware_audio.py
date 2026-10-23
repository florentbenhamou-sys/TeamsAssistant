"""Tests sur périphériques réels — lancés uniquement avec : pytest -m hardware

Ils jouent un bip discret sur la sortie par défaut ; à exécuter hors réunion.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from teams_assistant.audio.backends import BACKENDS, default_device, get_backend
from teams_assistant.audio.capture_session import CaptureSession
from teams_assistant.audio.test_tone import play_tone_async
from teams_assistant.audio.types import DeviceKind

pytestmark = pytest.mark.hardware


@pytest.mark.parametrize("backend_name", list(BACKENDS))
def test_real_loopback_with_pause(backend_name: str, tmp_path: Path) -> None:
    backend = get_backend(backend_name)
    devices = backend.list_devices()
    loopback = default_device(devices, DeviceKind.LOOPBACK)
    mic = default_device(devices, DeviceKind.INPUT)
    assert loopback is not None
    session = CaptureSession(backend, tmp_path)
    session.start(loopback, mic)
    started = time.monotonic()  # les horloges démarrent à la fin de start()
    play_tone_async(loopback.name, 1.5, delay=0.3).join()
    session.pause()
    first_part = time.monotonic() - started
    time.sleep(1.0)
    session.resume()
    time.sleep(1.0)
    result = session.stop()
    system = result.sources[0]
    assert system.report.has_signal, system.report.summary()
    # Le fichier couvre le temps actif uniquement : la seconde de pause est exclue
    active = first_part + 1.0
    assert abs(system.report.duration_s - active) < 0.35, (active, system.report.summary())
    assert abs(result.duration_s - active) < 0.35
    if mic is not None:
        mic_report = result.sources[1].report
        assert mic_report.readable
        # Les deux fichiers couvrent la même période (origine de temps commune).
        # Tolérance mesurée : < 0,05 s avec PyAudioWPatch, ~0,27 s avec soundcard.
        assert abs(mic_report.duration_s - system.report.duration_s) < 0.35
