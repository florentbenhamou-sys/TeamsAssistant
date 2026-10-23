"""Transcription en ligne de commande (exemple reproductible, sans interface).

    python -m teams_assistant.transcription.cli samples\\meeting_demo\\mixed.wav
    python -m teams_assistant.transcription.cli --system s.wav --microphone m.wav --profile equilibre
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from teams_assistant.config import AppPaths
from teams_assistant.transcription.diarization import EmbeddingDiarizer, ensure_model
from teams_assistant.transcription.pipeline import TranscriptionPipeline
from teams_assistant.transcription.types import (
    AudioSource,
    Progress,
    SourceKind,
    TranscriptionError,
    TranscriptionOptions,
)
from teams_assistant.transcription.whisper_engine import PROFILES, FasterWhisperEngine


def _sources(args: argparse.Namespace) -> list[AudioSource]:
    sources = [AudioSource(Path(p), SourceKind.IMPORTED) for p in args.files]
    if args.system:
        sources.append(AudioSource(Path(args.system), SourceKind.SYSTEM))
    if args.microphone:
        sources.append(AudioSource(Path(args.microphone), SourceKind.MICROPHONE))
    return sources


def _print_progress(progress: Progress) -> None:
    print(f"\r  progression {progress.ratio:6.1%} (tronçon {progress.chunk_index + 1}/{progress.chunk_count})",
          end="", flush=True)


def format_time(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcription locale faster-whisper")
    parser.add_argument("files", nargs="*", help="fichier(s) audio à importer")
    parser.add_argument("--system", help="piste son du PC (loopback)")
    parser.add_argument("--microphone", help="piste micro")
    parser.add_argument("--profile", choices=list(PROFILES), default="rapide")
    parser.add_argument("--language", default="fr", help="code langue, ou 'auto'")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--diarize", action="store_true", help="distinguer les voix")
    parser.add_argument("--speakers", type=int, default=0, help="voix attendues (son du PC / fichier), 0 = auto")
    parser.add_argument("--speakers-mic", type=int, default=1, help="voix attendues au micro, 0 = auto")
    args = parser.parse_args(argv)
    options = TranscriptionOptions(language=None if args.language == "auto" else args.language,
                                   profile=args.profile, diarize=args.diarize, speakers_main=args.speakers,
                                   speakers_mic=args.speakers_mic)
    models = AppPaths.default().ensure().models
    engine = FasterWhisperEngine(models, device=args.device)
    pipeline = TranscriptionPipeline(engine, diarizer_factory=lambda: EmbeddingDiarizer(ensure_model(models)))
    started = time.perf_counter()
    try:
        result = pipeline.run(_sources(args), options, on_progress=_print_progress)
    except TranscriptionError as exc:
        print(f"\nERREUR : {exc}")
        return 1
    elapsed = time.perf_counter() - started
    print(f"\nLangue : {result.language} ({result.language_probability:.0%}) — modèle {result.model}")
    print(f"Durée audio {result.duration_s:.1f} s, traitement {elapsed:.1f} s "
          f"(x{result.duration_s / elapsed:.1f} temps réel)")
    for seg in result.segments:
        flag = " [?]" if seg.uncertain else ""
        print(f"[{format_time(seg.start_s)} → {format_time(seg.end_s)}] {seg.speaker} : {seg.text}{flag}")
    for warning in result.warnings:
        print(f"AVERTISSEMENT : {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
