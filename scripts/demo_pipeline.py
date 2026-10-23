"""Exemple reproductible de bout en bout sur l'échantillon synthétique (aucune donnée réelle).

Import des pistes system.wav + microphone.wav -> transcription locale -> compte rendu local -> exports.
Les résultats sont écrits dans samples/meeting_demo/ (transcription-exemple.md, compte-rendu-exemple.md).
Base de données temporaire : vos données réelles ne sont pas touchées.

Usage : python scripts/demo_pipeline.py [--profile rapide]
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from teams_assistant import exports
from teams_assistant.app_context import build_context
from teams_assistant.config import AppPaths
from teams_assistant.models import AudioFile
from teams_assistant.summary.local_generator import LocalSummaryGenerator
from teams_assistant.transcription.types import TranscriptionOptions
from teams_assistant.transcription.whisper_engine import PROFILES, FasterWhisperEngine

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "meeting_demo"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=list(PROFILES), default="rapide")
    args = parser.parse_args()
    engine = FasterWhisperEngine(AppPaths.default().ensure().models)  # modèles partagés
    with tempfile.TemporaryDirectory() as tmp:
        ctx = build_context(AppPaths(Path(tmp)), engine=engine)
        session = ctx.sessions.create("Réunion de cadrage — projet Atlas (données fictives)")
        for kind in ("system", "microphone"):  # pistes séparées, comme une vraie capture
            ctx.sessions.repo.add_audio(AudioFile(session_id=session.id, kind=kind, owned=False,
                                                  path=str(SAMPLE / f"{kind}.wav"), has_signal=True))
        started = time.perf_counter()
        transcript = ctx.transcription.transcribe(session.id, TranscriptionOptions(profile=args.profile))
        print(f"Transcription : {time.perf_counter() - started:.1f} s ({transcript.model})")
        segments = ctx.transcription.segments(transcript.id)
        session = ctx.sessions.get(session.id)
        exports.write_text(SAMPLE / "transcription-exemple.md", exports.transcript_md(session, transcript, segments))
        summary = ctx.summaries.generate(session.id, LocalSummaryGenerator())
        exports.write_text(SAMPLE / "compte-rendu-exemple.md",
                           exports.summary_md(ctx.summaries.content(summary), summary.validated))
        ctx.close()
    print(f"Exemples écrits dans {SAMPLE}")


if __name__ == "__main__":
    main()
