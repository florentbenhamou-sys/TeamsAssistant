from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fakes import FakeBackend, FakeClock, default_devices, sine_block
from teams_assistant.audio.capture_session import CaptureSession
from teams_assistant.audio.recorder import CaptureState, SourceRecorder
from teams_assistant.audio.types import CaptureError, DeviceKind

LOOPBACK, MIC = default_devices()


def _recorder(tmp_path: Path) -> tuple[SourceRecorder, FakeBackend, FakeClock]:
    clock, backend = FakeClock(), FakeBackend()
    return SourceRecorder(backend, LOOPBACK, tmp_path / "out.wav", clock), backend, clock


def test_silence_gaps_are_filled_to_keep_timeline(tmp_path: Path) -> None:
    recorder, backend, clock = _recorder(tmp_path)
    recorder.start()
    stream = backend.streams[DeviceKind.LOOPBACK]
    clock.advance(1.0)
    stream.emit(sine_block(1.0))
    clock.advance(2.0)  # 1 s sans aucune trame (comportement loopback WASAPI)
    stream.emit(sine_block(1.0))
    result = recorder.stop()
    assert abs(result.report.duration_s - 3.0) < 0.01
    assert abs(result.padded_seconds - 1.0) < 0.01
    assert result.report.has_signal


def test_trailing_silence_is_padded_at_stop(tmp_path: Path) -> None:
    recorder, backend, clock = _recorder(tmp_path)
    recorder.start()
    clock.advance(1.0)
    backend.streams[DeviceKind.LOOPBACK].emit(sine_block(1.0))
    clock.advance(4.0)
    result = recorder.stop()
    assert abs(result.report.duration_s - 5.0) < 0.01


def test_pause_discards_audio_and_time(tmp_path: Path) -> None:
    recorder, backend, clock = _recorder(tmp_path)
    recorder.start()
    stream = backend.streams[DeviceKind.LOOPBACK]
    clock.advance(1.0)
    stream.emit(sine_block(1.0))
    recorder.pause()
    clock.advance(5.0)
    stream.emit(sine_block(5.0))  # ignoré : capture suspendue
    recorder.resume()
    clock.advance(1.0)
    stream.emit(sine_block(1.0))
    result = recorder.stop()
    assert abs(result.report.duration_s - 2.0) < 0.01


def test_disconnected_stream_raises_alert(tmp_path: Path) -> None:
    recorder, backend, _clock = _recorder(tmp_path)
    recorder.start()
    backend.streams[DeviceKind.LOOPBACK].alive = False
    assert any("interrompu" in alert for alert in recorder.health_alerts())
    recorder.stop()


def test_stalled_microphone_raises_alert(tmp_path: Path) -> None:
    clock, backend = FakeClock(), FakeBackend()
    recorder = SourceRecorder(backend, MIC, tmp_path / "mic.wav", clock)
    recorder.start()
    clock.advance(5.0)
    assert any("microphone" in alert for alert in recorder.health_alerts())
    recorder.stop()


def test_session_records_separate_files(tmp_path: Path) -> None:
    clock, backend = FakeClock(), FakeBackend()
    session = CaptureSession(backend, tmp_path, clock)
    session.start(LOOPBACK, MIC)
    clock.advance(1.0)
    backend.streams[DeviceKind.LOOPBACK].emit(sine_block(1.0))
    backend.streams[DeviceKind.INPUT].emit(sine_block(1.0, channels=1))
    result = session.stop()
    assert session.state is CaptureState.STOPPED
    assert sorted(p.name for p in result.usable_files) == ["microphone.wav", "system.wav"]


def test_session_without_signal_is_not_a_success(tmp_path: Path) -> None:
    clock, backend = FakeClock(), FakeBackend()
    session = CaptureSession(backend, tmp_path, clock)
    session.start(LOOPBACK)
    clock.advance(2.0)
    backend.streams[DeviceKind.LOOPBACK].emit(np.zeros((16000, 2), dtype=np.int16))
    result = session.stop()
    assert not result.succeeded
    assert session.state is CaptureState.ERROR


def test_session_rejects_wrong_device_kinds_and_double_start(tmp_path: Path) -> None:
    session = CaptureSession(FakeBackend(), tmp_path, FakeClock())
    with pytest.raises(CaptureError):
        session.start(MIC)
    session.start(LOOPBACK)
    with pytest.raises(CaptureError):
        session.start(LOOPBACK)
    session.stop()


def test_open_failure_sets_error_state(tmp_path: Path) -> None:
    session = CaptureSession(FakeBackend(fail_open=True), tmp_path, FakeClock())
    with pytest.raises(CaptureError):
        session.start(LOOPBACK)
    assert session.state is CaptureState.ERROR


def test_microphone_is_not_recorded_unless_requested(tmp_path: Path) -> None:
    backend = FakeBackend()
    session = CaptureSession(backend, tmp_path, FakeClock())
    session.start(LOOPBACK)
    assert DeviceKind.INPUT not in backend.streams
    session.stop()
