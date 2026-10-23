"""Génère l'échantillon synthétique samples/meeting_demo à partir de script.json.

Utilise la synthèse vocale Windows (voix française « Hortense ») ; aucune donnée réelle.
Produit : system.wav, microphone.wav (pistes séparées alignées), mixed.wav et timeline.json
(vérité terrain des horodatages, utilisée par les tests).

Usage : python scripts/make_samples.py
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

RATE = 16000
GAP_S = 0.8  # silence entre deux répliques
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "samples" / "meeting_demo"

PS_TEMPLATE = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('Microsoft Hortense Desktop')
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('{out}', $fmt)
$s.Speak([IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8))
$s.Dispose()
"""


def synthesize(text: str, work: Path, index: int) -> np.ndarray:
    # Synthèse d'une réplique via PowerShell / System.Speech
    txt, out = work / f"{index}.txt", work / f"{index}.wav"
    txt.write_text(text, encoding="utf-8")
    script = PS_TEMPLATE.format(out=out, txt=txt)
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    with wave.open(str(out), "rb") as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.astype(np.int16).tobytes())


def build(lines: list[dict[str, str]], work: Path) -> tuple[dict[str, np.ndarray], list[dict[str, object]]]:
    clips = [synthesize(line["text"], work, i) for i, line in enumerate(lines)]
    total = int(sum(len(c) for c in clips) + RATE * GAP_S * (len(clips) + 1))
    tracks = {"system": np.zeros(total, np.int16), "microphone": np.zeros(total, np.int16)}
    timeline: list[dict[str, object]] = []
    cursor = int(RATE * GAP_S)
    for line, clip in zip(lines, clips):
        tracks[line["source"]][cursor:cursor + len(clip)] = clip
        timeline.append({"source": line["source"], "text": line["text"],
                         "start_s": round(cursor / RATE, 2), "end_s": round((cursor + len(clip)) / RATE, 2)})
        cursor += len(clip) + int(RATE * GAP_S)
    return tracks, timeline


def main() -> None:
    script = json.loads((SAMPLE_DIR / "script.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        tracks, timeline = build(script["lines"], Path(tmp))
    for name, samples in tracks.items():
        write_wav(SAMPLE_DIR / f"{name}.wav", samples)
    mixed = np.clip(tracks["system"].astype(np.int32) + tracks["microphone"], -32768, 32767)
    write_wav(SAMPLE_DIR / "mixed.wav", mixed)
    (SAMPLE_DIR / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    print(f"Échantillon généré : {SAMPLE_DIR} ({len(mixed) / RATE:.1f} s)")


if __name__ == "__main__":
    main()
