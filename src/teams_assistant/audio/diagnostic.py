"""Module de test audio indépendant (premier jalon).

Exemples :
    python -m teams_assistant.audio.diagnostic list
    python -m teams_assistant.audio.diagnostic record --seconds 5 --tone
    python -m teams_assistant.audio.diagnostic record --device "Jabra" --kind input --seconds 5
    python -m teams_assistant.audio.diagnostic probe --tone
    python -m teams_assistant.audio.diagnostic check chemin\\fichier.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from teams_assistant.audio.backends import BACKENDS, default_device, find_device, get_backend
from teams_assistant.audio.recorder import SourceRecorder, SourceResult
from teams_assistant.audio.test_tone import play_tone_async
from teams_assistant.audio.types import AudioDevice, CaptureBackend, CaptureError, DeviceKind
from teams_assistant.audio.wav_utils import analyze_wav
from teams_assistant.config import AppPaths

NO_SIGNAL_HINTS: dict[DeviceKind, list[str]] = {
    DeviceKind.LOOPBACK: [
        "Vérifiez que du son était réellement joué pendant le test (option --tone).",
        "Sélectionnez la sortie utilisée par Teams (Teams > Paramètres > Périphériques > Haut-parleur).",
        "Navigateur : vérifiez sa sortie (Paramètres Windows > Son > Mélangeur de volume).",
        "Repérez la bonne sortie avec la commande 'probe' pendant que la réunion est audible.",
    ],
    DeviceKind.INPUT: [
        "Parlez distinctement pendant toute la durée du test.",
        "Paramètres Windows > Confidentialité > Microphone > autoriser les applications de bureau.",
        "Vérifiez que le micro n'est pas coupé (bouton mute du casque).",
        "Casque Bluetooth/DECT : l'ouverture du micro peut prendre ~1 s (bascule en mode mains libres).",
    ],
}
FALLBACK_HINT = "Essayez l'autre backend : --backend wasapi-soundcard (ou wasapi-pyaudio)."


def _print_devices(backend: CaptureBackend) -> list[AudioDevice]:
    devices = backend.list_devices()
    print(f"Backend : {backend.name} — {len(devices)} source(s) de capture")
    for device in devices:
        mark = "*" if device.is_default else " "
        print(f" {mark} [{device.device_id:>3}] {device.kind.value:<8} {device.channels} canal(aux) "
              f"{device.sample_rate} Hz  {device.name}")
    print(" (* = périphérique par défaut de Windows)")
    return devices


def cmd_list(args: argparse.Namespace) -> int:
    names = [args.backend] if args.backend else list(BACKENDS)
    for name in names:
        try:
            _print_devices(get_backend(name))
        except CaptureError as exc:
            print(f"Backend {name} : ÉCHEC — {exc} {exc.hint}")
        print()
    return 0


def _pick_device(backend: CaptureBackend, key: str | None, kind: DeviceKind) -> AudioDevice:
    devices = backend.list_devices()
    if key:
        return find_device(devices, key, kind)
    device = default_device(devices, kind)
    if device is None:
        raise CaptureError(f"Aucun périphérique de type {kind.value}.",
                           "Vérifiez qu'un casque ou des haut-parleurs sont activés dans Windows.")
    return device


def _record(backend: CaptureBackend, device: AudioDevice, seconds: float, tone: bool,
            out_path: Path) -> SourceResult:
    recorder = SourceRecorder(backend, device, out_path)
    recorder.start()
    if tone and device.kind is DeviceKind.LOOPBACK:
        play_tone_async(device.name, max(seconds - 1.0, 0.5))
    time.sleep(seconds)
    return recorder.stop()


def _report(result: SourceResult) -> int:
    print(f"Fichier : {result.path}")
    print(f"Vérification : {result.report.summary()}")
    if result.padded_seconds:
        print(f"Silence comblé (aucune trame livrée par Windows) : {result.padded_seconds:.1f} s")
    for error in result.errors:
        print(f"ERREUR : {error}")
    if result.report.has_signal:
        print("RÉSULTAT : capture VALIDÉE (fichier lisible avec signal audio).")
        return 0
    print("RÉSULTAT : capture NON VALIDÉE.")
    for hint in [*NO_SIGNAL_HINTS[result.device.kind], FALLBACK_HINT]:
        print(f"  - {hint}")
    return 2


def _diag_dir(args: argparse.Namespace) -> Path:
    return Path(args.out) if args.out else AppPaths.default().ensure().recordings / "diagnostic"


def cmd_record(args: argparse.Namespace) -> int:
    backend = get_backend(args.backend)
    device = _pick_device(backend, args.device, DeviceKind(args.kind))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = _diag_dir(args) / f"test-{device.kind.value}-{stamp}.wav"
    print(f"Capture de {args.seconds:.0f} s sur : {device.label} ({backend.name})")
    if args.tone and device.kind is DeviceKind.LOOPBACK:
        print("Un bip discret (440 Hz) va être joué sur cette sortie.")
    elif device.kind is DeviceKind.INPUT:
        print("Parlez dans le microphone pendant la capture.")
    return _report(_record(backend, device, args.seconds, args.tone, out_path))


def cmd_probe(args: argparse.Namespace) -> int:
    """Écoute chaque sortie (loopback) pour repérer celle qui reçoit réellement le son."""
    backend = get_backend(args.backend)
    loopbacks = [d for d in backend.list_devices() if d.kind is DeviceKind.LOOPBACK]
    out_dir = _diag_dir(args)
    for device in loopbacks:
        result = _record(backend, device, args.seconds, args.tone, out_dir / f"probe-{device.device_id}.wav")
        state = "SIGNAL" if result.report.has_signal else "silence"
        print(f"{state:<8} crête {result.report.peak_dbfs:6.1f} dBFS  {device.name}")
        result.path.unlink(missing_ok=True)  # fichier de sondage sans intérêt après mesure
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = analyze_wav(Path(args.file))
    print(report.summary())
    return 0 if report.has_signal else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teams-audio-diag", description="Diagnostic de capture audio")
    parser.add_argument("--backend", choices=list(BACKENDS), help="backend de capture à utiliser")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="lister les périphériques").set_defaults(func=cmd_list)
    record = sub.add_parser("record", help="capturer quelques secondes et vérifier le fichier")
    record.add_argument("--device", help="identifiant ou fragment de nom")
    record.add_argument("--kind", choices=[k.value for k in DeviceKind], default="loopback")
    record.add_argument("--seconds", type=float, default=5.0)
    record.add_argument("--tone", action="store_true", help="jouer un bip de test (loopback)")
    record.add_argument("--out", help="dossier de sortie")
    record.set_defaults(func=cmd_record)
    probe = sub.add_parser("probe", help="repérer la sortie qui reçoit du son")
    probe.add_argument("--seconds", type=float, default=3.0)
    probe.add_argument("--tone", action="store_true")
    probe.add_argument("--out", help="dossier temporaire")
    probe.set_defaults(func=cmd_probe)
    check = sub.add_parser("check", help="vérifier un fichier WAV existant")
    check.add_argument("file")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except CaptureError as exc:
        print(f"ERREUR : {exc}")
        if exc.hint:
            print(f"Diagnostic : {exc.hint}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
