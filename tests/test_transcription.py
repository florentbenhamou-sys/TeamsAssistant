from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from fakes import FakeSpeechEngine, tone, write_wav
from teams_assistant.transcription.audio_prep import load_audio, mix, split_bounds
from teams_assistant.transcription.pipeline import TranscriptionPipeline, remove_echo
from teams_assistant.transcription.types import (
    AudioSource,
    Segment,
    SourceKind,
    TranscriptionCancelled,
    TranscriptionError,
    TranscriptionOptions,
)

RATE = 16000


def test_load_audio_resamples_to_16k_mono(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    write_wav(path, tone(2.0, rate=44100), rate=44100)
    samples = load_audio(path)
    assert samples.dtype == np.float32
    assert abs(len(samples) / RATE - 2.0) < 0.05


def test_load_audio_errors_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="introuvable"):
        load_audio(tmp_path / "absent.wav")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"ceci n'est pas de l'audio")
    with pytest.raises(TranscriptionError):
        load_audio(bad)


def test_split_bounds_cuts_on_silence() -> None:
    samples = np.concatenate([tone(290), np.zeros(RATE * 2, np.float32), tone(300)])
    bounds = split_bounds(samples, RATE, target_s=300, search_s=20)
    assert len(bounds) == 2
    cut_s = bounds[0][1] / RATE
    assert 290 <= cut_s <= 292  # au milieu du silence, pas dans la parole
    assert bounds[-1][1] == len(samples)


def test_short_audio_is_a_single_chunk() -> None:
    assert split_bounds(tone(10), RATE) == [(0, 10 * RATE)]


def test_mix_avoids_clipping() -> None:
    mixed = mix([np.ones(10, np.float32), np.ones(5, np.float32)])
    assert len(mixed) == 10 and float(np.abs(mixed).max()) <= 1.0


def _sample(tmp_path: Path, seconds: float = 3) -> Path:
    path = tmp_path / "talk.wav"
    write_wav(path, tone(seconds))
    return path


def test_pipeline_offsets_and_labels(tmp_path: Path) -> None:
    signal = np.concatenate([tone(3), np.zeros(RATE * 2, np.float32), tone(3)])
    path = tmp_path / "long.wav"
    write_wav(path, signal)
    pipeline = TranscriptionPipeline(FakeSpeechEngine(), chunk_target_s=4)
    result = pipeline.run([AudioSource(path, SourceKind.IMPORTED)], TranscriptionOptions())
    starts = [s.start_s for s in result.segments]
    assert starts == sorted(starts) and starts[-1] >= 5.0  # second tronçon décalé
    assert {s.speaker for s in result.segments} == {"Fichier importé"}
    assert result.language == "fr"


def test_pipeline_resume_skips_completed_chunks(tmp_path: Path) -> None:
    path = tmp_path / "long.wav"
    write_wav(path, tone(12))
    saved: dict[int, list[Segment]] = {}
    engine = FakeSpeechEngine(fail_after=1)
    pipeline = TranscriptionPipeline(engine, chunk_target_s=4)
    with pytest.raises(TranscriptionCancelled):
        pipeline.run([AudioSource(path, SourceKind.IMPORTED)], TranscriptionOptions(),
                     on_chunk=lambda i, segs: saved.__setitem__(i, segs))
    assert list(saved) == [0]
    resumed_engine = FakeSpeechEngine()
    resumed = TranscriptionPipeline(resumed_engine, chunk_target_s=4)
    sources = [AudioSource(path, SourceKind.IMPORTED)]
    _tracks, chunks = resumed.prepare(sources, TranscriptionOptions())
    result = resumed.run(sources, TranscriptionOptions(), completed=saved)
    assert len(chunks) >= 3
    assert resumed_engine.calls == len(chunks) - 1  # seuls les tronçons manquants sont retraités
    assert {s.chunk_index for s in result.segments} == {c.index for c in chunks}


def test_pipeline_cancel(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()

    class CancellingEngine(FakeSpeechEngine):
        def transcribe(self, samples, options, cancel_event):  # type: ignore[no-untyped-def]
            raise TranscriptionCancelled("stop") if cancel_event.is_set() else AssertionError()

    with pytest.raises(TranscriptionCancelled):
        TranscriptionPipeline(CancellingEngine()).run(
            [AudioSource(_sample(tmp_path), SourceKind.IMPORTED)], TranscriptionOptions(), cancel=cancel)


def test_mix_mode_produces_single_track(tmp_path: Path) -> None:
    sys_path, mic_path = tmp_path / "s.wav", tmp_path / "m.wav"
    write_wav(sys_path, tone(2))
    write_wav(mic_path, tone(2))
    sources = [AudioSource(sys_path, SourceKind.SYSTEM), AudioSource(mic_path, SourceKind.MICROPHONE)]
    result = TranscriptionPipeline(FakeSpeechEngine()).run(
        sources, TranscriptionOptions(separate_sources=False))
    assert {s.source for s in result.segments} == {SourceKind.MIXED}


def _seg(source: SourceKind, start: float, text: str) -> Segment:
    return Segment(start, start + 2, text, source, None, 0.9, False, 0)


def test_echo_from_speakers_is_removed() -> None:
    segments = [_seg(SourceKind.SYSTEM, 0, "nous validons le pilote à Lyon"),
                _seg(SourceKind.MICROPHONE, 0.1, "nous validons le pilote a Lyon"),
                _seg(SourceKind.MICROPHONE, 5, "je vous envoie la proposition")]
    kept, removed = remove_echo(segments)
    assert removed == 1 and [s.start_s for s in kept] == [0, 5]


def test_empty_audio_warns_no_speech(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    write_wav(path, np.zeros(RATE * 2, np.float32))
    result = TranscriptionPipeline(FakeSpeechEngine()).run(
        [AudioSource(path, SourceKind.IMPORTED)], TranscriptionOptions())
    assert not result.segments and any("Aucune parole" in w for w in result.warnings)
