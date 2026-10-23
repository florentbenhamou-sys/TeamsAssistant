"""Séparation des voix : regroupement, numérotation, découpage, intégration au pipeline."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fakes import FakeDiarizer, FakeSpeechEngine, tone, write_wav
from teams_assistant.transcription.diarization import attach_short, cluster, model_path, renumber
from teams_assistant.transcription.pipeline import (
    Chunk,
    TranscriptionPipeline,
    expected_speakers,
    merge_same_speaker,
    split_utterances,
)
from teams_assistant.transcription.types import (
    AudioSource,
    RawSegment,
    Segment,
    SourceKind,
    TranscriptionOptions,
    WordStamp,
)


def _voices(count_a: int, count_b: int, seed: int = 0) -> np.ndarray:
    # Deux « voix » = deux directions bien distinctes, avec un peu de bruit
    rng = np.random.default_rng(seed)
    a, b = np.zeros(16), np.zeros(16)
    a[0], b[1] = 1.0, 1.0
    rows = [a + rng.normal(0, 0.1, 16) for _ in range(count_a)] + [b + rng.normal(0, 0.1, 16) for _ in range(count_b)]
    return np.array(rows)


def test_cluster_with_known_number_of_speakers() -> None:
    labels = cluster(_voices(4, 3), num_speakers=2)
    assert len(set(labels[:4])) == 1 and len(set(labels[4:])) == 1 and labels[0] != labels[4]


def test_cluster_auto_uses_threshold() -> None:
    assert len(set(cluster(_voices(5, 5), num_speakers=0, threshold=0.45))) == 2
    assert len(set(cluster(_voices(3, 0), num_speakers=0, threshold=0.45))) == 1
    assert cluster(np.zeros((0, 16))) == []


def test_renumber_follows_first_appearance() -> None:
    # ordre chronologique : groupe 3 (0 s) -> 1, groupe 9 (2 s) -> 2, groupe 7 (5 s) -> 3
    assert renumber([7, 3, 7, 9], [(5.0, 6.0), (0.0, 1.0), (7.0, 8.0), (2.0, 3.0)]) == [3, 1, 3, 2]


def test_short_utterances_are_attached() -> None:
    a, b = np.eye(4)[0], np.eye(4)[1]
    vectors = {0: a, 1: b, 2: b * 0.9 + a * 0.1}  # le 3e est court mais ressemble à la voix 2
    spans = [(0.0, 2.0), (3.0, 5.0), (5.1, 5.5), (5.6, 5.7)]  # le 4e n'a pas de vecteur : voisin
    labels = attach_short([1, 2, None, None], {k: v / np.linalg.norm(v) for k, v in vectors.items()}, spans)
    assert labels == [1, 2, 2, 2]


def test_split_utterances_at_pauses_and_sentence_ends() -> None:
    words = (WordStamp(0.0, 0.4, " Très"), WordStamp(0.45, 0.8, " bien."), WordStamp(0.9, 1.2, " Est-ce"),
             WordStamp(1.25, 1.5, " prêt"), WordStamp(2.5, 2.9, " Oui"))
    raw = RawSegment(0.0, 2.9, "Très bien. Est-ce prêt Oui", words=words)
    chunk = Chunk(0, SourceKind.MICROPHONE, 16000 * 10, 16000 * 20)  # tronçon débutant à 10 s
    pieces = split_utterances(raw, chunk, fine=True)
    assert [p.text for p in pieces] == ["Très bien.", "Est-ce prêt", "Oui"]
    assert pieces[0].start_s == 10.0 and pieces[2].start_s == 12.5
    assert len(split_utterances(raw, chunk, fine=False)) == 1


def test_consecutive_utterances_of_same_voice_are_merged() -> None:
    def seg(start: float, end: float, text: str, speaker: str) -> Segment:
        return Segment(start, end, text, SourceKind.IMPORTED, speaker, 0.9, False, 0)

    merged = merge_same_speaker([seg(0, 1, "Parfait,", "A"), seg(1.2, 1.6, "merci.", "A"),
                                 seg(2, 3, "Oui.", "B"), seg(10, 11, "Bien.", "B")])
    assert [(s.text, s.speaker) for s in merged] == [("Parfait, merci.", "A"), ("Oui.", "B"), ("Bien.", "B")]


def test_expected_speakers_per_track() -> None:
    options = TranscriptionOptions(diarize=True, speakers_main=3, speakers_mic=2)
    assert expected_speakers(SourceKind.SYSTEM, options) == 3
    assert expected_speakers(SourceKind.MICROPHONE, options) == 2
    assert expected_speakers(SourceKind.MIXED, options) == 5
    assert expected_speakers(SourceKind.MIXED, TranscriptionOptions(speakers_main=0)) == 0


def _two_tracks(tmp_path: Path) -> list[AudioSource]:
    sys_path, mic_path = tmp_path / "system.wav", tmp_path / "mic.wav"
    write_wav(sys_path, tone(4))
    write_wav(mic_path, np.concatenate([np.zeros(16000 * 5, np.float32), tone(2)]))
    return [AudioSource(sys_path, SourceKind.SYSTEM), AudioSource(mic_path, SourceKind.MICROPHONE)]


def test_pipeline_labels_voices_per_track(tmp_path: Path) -> None:
    diarizer = FakeDiarizer(switch_s=2.0)
    pipeline = TranscriptionPipeline(FakeSpeechEngine(), diarizer_factory=lambda: diarizer)
    result = pipeline.run(_two_tracks(tmp_path), TranscriptionOptions(diarize=True, speakers_main=2, speakers_mic=1))
    system = [s.speaker for s in result.segments if s.source is SourceKind.SYSTEM]
    mic = {s.speaker for s in result.segments if s.source is SourceKind.MICROPHONE}
    assert system == ["Distant 1", "Distant 2"]  # passages consécutifs d'une même voix regroupés
    assert mic == {"Micro local"}  # 1 voix attendue au micro : pas de séparation
    assert diarizer.calls == [(4, 2)]
    assert any("2 voix distinguée(s)" in w for w in result.warnings)


def test_pipeline_without_diarization_keeps_source_labels(tmp_path: Path) -> None:
    diarizer = FakeDiarizer()
    pipeline = TranscriptionPipeline(FakeSpeechEngine(), diarizer_factory=lambda: diarizer)
    result = pipeline.run(_two_tracks(tmp_path), TranscriptionOptions(diarize=False))
    assert {s.speaker for s in result.segments} == {"Participants distants (son du PC)", "Micro local"}
    assert diarizer.calls == []


def test_model_location() -> None:
    assert model_path(Path("models")) == Path("models") / "diarization" / "nemo_en_titanet_small.onnx"
