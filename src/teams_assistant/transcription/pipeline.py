"""Orchestration : décodage, découpage en tronçons, transcription, fusion des sources, reprise.

Chaque tronçon terminé est remis à `on_chunk` (persistance). En cas d'interruption, la
transcription peut reprendre en fournissant les tronçons déjà terminés (`completed`).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher

from teams_assistant.logging_setup import get_logger
from teams_assistant.transcription.audio_prep import load_audio, mix, split_bounds
from teams_assistant.transcription.diarization import LABEL_PREFIX, Diarizer
from teams_assistant.transcription.types import (
    SAMPLE_RATE,
    SOURCE_LABELS,
    AudioSource,
    DetectedLanguage,
    Progress,
    ProgressCallback,
    RawSegment,
    Samples,
    Segment,
    SourceKind,
    SpeechEngine,
    TranscriptionCancelled,
    TranscriptionError,
    TranscriptionOptions,
    TranscriptResult,
    WordStamp,
)

log = get_logger("transcription.pipeline")
ChunkCallback = Callable[[int, list[Segment]], None]

# Seuils de signalement des passages douteux (valeurs usuelles de Whisper)
LOW_LOGPROB = -1.0
HIGH_NO_SPEECH = 0.6
HIGH_COMPRESSION = 2.4
ECHO_SIMILARITY = 0.6
PAUSE_SPLIT_S = 0.4  # pause entre deux mots à partir de laquelle on coupe la prise de parole
MERGE_GAP_S = 1.5  # regroupement a posteriori des prises de parole d'une même voix
MERGE_MAX_S = 30.0


@dataclass(frozen=True)
class Chunk:
    index: int
    kind: SourceKind
    start: int
    end: int

    @property
    def start_s(self) -> float:
        return self.start / SAMPLE_RATE

    @property
    def duration_s(self) -> float:
        return (self.end - self.start) / SAMPLE_RATE


def is_uncertain(raw: RawSegment) -> bool:
    return (raw.avg_logprob < LOW_LOGPROB or raw.no_speech_prob > HIGH_NO_SPEECH
            or raw.compression_ratio > HIGH_COMPRESSION)


def to_segment(raw: RawSegment, chunk: Chunk) -> Segment:
    return Segment(start_s=round(chunk.start_s + raw.start_s, 2), end_s=round(chunk.start_s + raw.end_s, 2),
                   text=raw.text, source=chunk.kind, speaker=SOURCE_LABELS[chunk.kind],
                   confidence=round(math.exp(min(raw.avg_logprob, 0.0)), 3),
                   uncertain=is_uncertain(raw), chunk_index=chunk.index)


def split_utterances(raw: RawSegment, chunk: Chunk, fine: bool) -> list[Segment]:
    """Segments finaux. En mode séparation des voix, un segment Whisper est coupé en prises de
    parole aux pauses et aux fins de phrase : un changement de voix y survient presque toujours."""
    base = to_segment(raw, chunk)
    if not fine or not raw.words:
        return [base]
    groups: list[list[WordStamp]] = [[]]
    for word in raw.words:
        previous = groups[-1][-1] if groups[-1] else None
        if previous and (word.start_s - previous.end_s >= PAUSE_SPLIT_S or previous.text.rstrip()[-1:] in ".?!"):
            groups.append([])
        groups[-1].append(word)
    offset = chunk.start_s
    return [replace(base, start_s=round(offset + g[0].start_s, 2), end_s=round(offset + g[-1].end_s, 2),
                    text="".join(w.text for w in g).strip()) for g in groups if "".join(w.text for w in g).strip()]


def merge_same_speaker(segments: list[Segment], max_gap_s: float = MERGE_GAP_S,
                       max_length_s: float = MERGE_MAX_S) -> list[Segment]:
    """Après attribution des voix, regroupe les prises de parole consécutives d'une même voix
    (lisibilité) ; une autre voix ou une longue pause entre les deux empêche le regroupement."""
    merged: list[Segment] = []
    for seg in segments:
        last = merged[-1] if merged else None
        if (last and last.source is seg.source and last.speaker == seg.speaker
                and seg.start_s - last.end_s <= max_gap_s and seg.end_s - last.start_s <= max_length_s):
            merged[-1] = replace(last, end_s=seg.end_s, text=f"{last.text} {seg.text}",
                                 confidence=min(last.confidence, seg.confidence),
                                 uncertain=last.uncertain or seg.uncertain)
        else:
            merged.append(seg)
    return merged


def expected_speakers(kind: SourceKind, options: TranscriptionOptions) -> int:
    """Nombre de voix attendu sur une piste (0 = estimation automatique)."""
    if kind is SourceKind.MICROPHONE:
        return options.speakers_mic
    if kind is SourceKind.MIXED and options.speakers_main and options.speakers_mic:
        return options.speakers_main + options.speakers_mic  # piste mixée : toutes les voix
    return 0 if kind is SourceKind.MIXED else options.speakers_main


def _overlap(a: Segment, b: Segment) -> float:
    return max(0.0, min(a.end_s, b.end_s) - max(a.start_s, b.start_s))


def remove_echo(segments: list[Segment]) -> tuple[list[Segment], int]:
    """Supprime les segments micro qui répètent le son du PC (haut-parleurs captés par le micro)."""
    system = [s for s in segments if s.source is SourceKind.SYSTEM]
    kept: list[Segment] = []
    removed = 0
    for seg in segments:
        if seg.source is SourceKind.MICROPHONE and _is_echo(seg, system):
            removed += 1
            continue
        kept.append(seg)
    return kept, removed


def _is_echo(mic: Segment, system: list[Segment]) -> bool:
    duration = max(mic.end_s - mic.start_s, 0.01)
    for other in system:
        if _overlap(mic, other) / duration >= 0.5:
            ratio = SequenceMatcher(None, mic.text.lower(), other.text.lower()).ratio()
            if ratio >= ECHO_SIMILARITY:
                return True
    return False


@dataclass
class _RunState:
    """État partagé d'une exécution (tronçons terminés, langue, progression)."""

    chunks: list[Chunk]
    done: dict[int, list[Segment]]
    total_s: float
    language: DetectedLanguage
    on_progress: ProgressCallback | None
    cancel: threading.Event
    warnings: list[str] = field(default_factory=list)

    def done_seconds(self) -> float:
        return sum(c.duration_s for c in self.chunks if c.index in self.done)

    def report(self, done_s: float, chunk: Chunk) -> None:
        if self.on_progress:
            self.on_progress(Progress(done_s, self.total_s, chunk.index, len(self.chunks)))


class TranscriptionPipeline:
    def __init__(self, engine: SpeechEngine, chunk_target_s: float = 300.0,
                 diarizer_factory: Callable[[], Diarizer] | None = None) -> None:
        self.engine = engine
        self.chunk_target_s = chunk_target_s
        self.diarizer_factory = diarizer_factory  # chargé seulement si la séparation est demandée

    def prepare(self, sources: list[AudioSource], options: TranscriptionOptions
                ) -> tuple[dict[SourceKind, Samples], list[Chunk]]:
        """Décode les sources et planifie les tronçons (plan déterministe, base de la reprise)."""
        if not sources:
            raise TranscriptionError("Aucune source audio à transcrire.")
        tracks = {src.kind: load_audio(src.path) for src in sources}
        if not options.separate_sources and len(tracks) > 1:
            tracks = {SourceKind.MIXED: mix(list(tracks.values()))}
        chunks: list[Chunk] = []
        for kind, samples in tracks.items():
            for start, end in split_bounds(samples, SAMPLE_RATE, self.chunk_target_s):
                chunks.append(Chunk(len(chunks), kind, start, end))
        return tracks, chunks

    def run(self, sources: list[AudioSource], options: TranscriptionOptions,
            on_chunk: ChunkCallback | None = None, on_progress: ProgressCallback | None = None,
            cancel: threading.Event | None = None,
            completed: dict[int, list[Segment]] | None = None) -> TranscriptResult:
        tracks, chunks = self.prepare(sources, options)
        state = _RunState(chunks=chunks, done=dict(completed or {}),
                          total_s=sum(c.duration_s for c in chunks),
                          language=DetectedLanguage(options.language or "", 1.0 if options.language else 0.0),
                          on_progress=on_progress, cancel=cancel or threading.Event())
        for chunk in chunks:
            if chunk.index in state.done:
                continue  # reprise : tronçon déjà transcrit
            segments = self._run_chunk(tracks[chunk.kind], chunk, options, state)
            state.done[chunk.index] = segments
            if on_chunk:
                on_chunk(chunk.index, segments)
        return self._assemble(state, tracks, options)

    def _run_chunk(self, samples: Samples, chunk: Chunk, options: TranscriptionOptions,
                   state: _RunState) -> list[Segment]:
        # La langue détectée sur le premier tronçon est imposée aux suivants (cohérence)
        effective = replace(options, language=state.language.code) if state.language.code else options
        detected, raws = self.engine.transcribe(samples[chunk.start:chunk.end], effective, state.cancel)
        if not state.language.code:
            state.language = detected
        base = state.done_seconds()
        fine = options.diarize and expected_speakers(chunk.kind, options) != 1
        segments: list[Segment] = []
        for raw in raws:
            segments.extend(split_utterances(raw, chunk, fine))
            state.report(base + raw.end_s, chunk)
        state.report(base + chunk.duration_s, chunk)
        return segments

    def _diarize(self, segments: list[Segment], tracks: dict[SourceKind, Samples],
                 options: TranscriptionOptions, state: _RunState) -> list[Segment]:
        """Séparation des voix piste par piste, sur toute la piste (numérotation cohérente,
        y compris après une reprise). Renvoie les segments avec leur libellé de voix."""
        if not options.diarize:
            return segments
        if self.diarizer_factory is None:
            state.warnings.append("Séparation des voix indisponible dans cette configuration.")
            return segments
        diarizer: Diarizer | None = None
        labels: dict[int, str] = {}
        for kind, samples in tracks.items():
            expected = expected_speakers(kind, options)
            members = [i for i, s in enumerate(segments) if s.source is kind]
            if expected == 1 or not members:
                continue  # une seule voix attendue : libellé de la source conservé
            diarizer = diarizer or self.diarizer_factory()
            numbers = diarizer.assign(samples, [(segments[i].start_s, segments[i].end_s) for i in members],
                                      expected, self._diarization_progress(state, kind))
            labels.update({i: f"{LABEL_PREFIX[kind]} {n}" for i, n in zip(members, numbers)})
            state.warnings.append(f"{len(set(numbers))} voix distinguée(s) sur « {SOURCE_LABELS[kind]} » "
                                  "(séparation automatique, à vérifier avant de renommer).")
        labeled = [replace(s, speaker=labels[i]) if i in labels else s for i, s in enumerate(segments)]
        return merge_same_speaker(labeled) if labels else labeled

    @staticmethod
    def _diarization_progress(state: _RunState, kind: SourceKind) -> Callable[[float], None]:
        def report(ratio: float) -> None:
            if state.cancel.is_set():
                raise TranscriptionCancelled("Transcription interrompue par l'utilisateur.")
            if state.on_progress:
                state.on_progress(Progress(state.done_seconds(), state.total_s, 0, len(state.chunks),
                                           f"Séparation des voix ({SOURCE_LABELS[kind]}) : {ratio:.0%}"))
        return report

    def _assemble(self, state: _RunState, tracks: dict[SourceKind, Samples],
                  options: TranscriptionOptions) -> TranscriptResult:
        segments = sorted((s for segs in state.done.values() for s in segs),
                          key=lambda s: (s.start_s, s.source))
        segments = self._diarize(segments, tracks, options, state)
        warnings: list[str] = list(state.warnings)
        if SourceKind.MICROPHONE in tracks and SourceKind.SYSTEM in tracks:
            segments, removed = remove_echo(segments)
            if removed:
                warnings.append(f"{removed} segment(s) du micro ignoré(s) : écho du son du PC.")
        uncertain = sum(1 for s in segments if s.uncertain)
        if uncertain:
            warnings.append(f"{uncertain} passage(s) à faible confiance, à vérifier.")
        if not segments:
            warnings.append("Aucune parole reconnue dans l'audio.")
        duration = max(len(t) for t in tracks.values()) / SAMPLE_RATE
        return TranscriptResult(language=state.language.code, language_probability=state.language.probability,
                                duration_s=round(duration, 2), segments=segments, engine=self.engine.name,
                                model=self.engine.model_name, profile=options.profile, warnings=warnings)
