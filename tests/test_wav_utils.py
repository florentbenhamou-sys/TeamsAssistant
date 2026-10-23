from __future__ import annotations

from pathlib import Path

import numpy as np

from fakes import sine_block
from teams_assistant.audio.wav_utils import WavWriter, analyze_wav


def _write(path: Path, block: np.ndarray, rate: int = 16000) -> None:
    writer = WavWriter(path, rate, block.shape[1])
    writer.write(block)
    writer.close()


def test_sine_file_has_signal(tmp_path: Path) -> None:
    path = tmp_path / "sine.wav"
    _write(path, sine_block(2.0))
    report = analyze_wav(path)
    assert report.readable and report.has_signal
    assert abs(report.duration_s - 2.0) < 0.01
    assert report.channels == 2 and report.sample_rate == 16000
    assert -12 < report.peak_dbfs < -9  # amplitude 0.3 ≈ -10.5 dBFS


def test_silence_is_not_reported_as_signal(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    _write(path, np.zeros((16000, 1), dtype=np.int16))
    report = analyze_wav(path)
    assert report.readable and not report.has_signal
    assert "AUCUN SIGNAL" in report.summary()


def test_unreadable_file_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "broken.wav"
    path.write_bytes(b"pas un wav")
    report = analyze_wav(path)
    assert not report.readable and not report.has_signal
    assert analyze_wav(tmp_path / "absent.wav").readable is False


def test_file_stays_readable_without_close(tmp_path: Path) -> None:
    # Simule un arrêt brutal : l'en-tête est mis à jour à chaque bloc
    path = tmp_path / "crash.wav"
    writer = WavWriter(path, 16000, 2)
    writer.write(sine_block(1.0))
    writer._wav._file.flush()  # type: ignore[attr-defined]
    report = analyze_wav(path)
    writer.close()
    assert report.readable and abs(report.duration_s - 1.0) < 0.01


def test_channel_mismatch_is_rejected(tmp_path: Path) -> None:
    writer = WavWriter(tmp_path / "x.wav", 16000, 1)
    try:
        writer.write(sine_block(0.1, channels=2))
    except ValueError:
        pass
    else:
        raise AssertionError("un bloc stéréo ne doit pas être accepté dans un fichier mono")
    finally:
        writer.close()
