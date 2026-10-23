"""Session de capture : son du PC (obligatoire) + microphone (optionnel), fichiers séparés.

Les deux sources sont enregistrées dans des WAV distincts plutôt que mixées en direct :
- pas de dérive d'horloge entre périphériques pendant l'enregistrement ;
- la provenance (micro local / son distant) reste disponible pour la transcription.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from teams_assistant.audio.recorder import ActiveClock, CaptureState, SourceRecorder, SourceResult
from teams_assistant.audio.types import AudioDevice, CaptureBackend, CaptureError, DeviceKind
from teams_assistant.logging_setup import get_logger

log = get_logger("audio.session")


@dataclass
class CaptureResult:
    sources: list[SourceResult]
    duration_s: float
    errors: list[str] = field(default_factory=list)

    @property
    def usable_files(self) -> list[Path]:
        """Fichiers réellement exploitables (lisibles et contenant du signal)."""
        return [s.path for s in self.sources if s.report.has_signal]

    @property
    def succeeded(self) -> bool:
        return bool(self.usable_files)


class CaptureSession:
    """Orchestre plusieurs SourceRecorder ; démarrage toujours explicite (jamais automatique)."""

    def __init__(self, backend: CaptureBackend, output_dir: Path,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.backend = backend
        self.output_dir = output_dir
        self._clock = clock
        self._timer = ActiveClock(clock)
        self.recorders: list[SourceRecorder] = []
        self.state = CaptureState.IDLE
        self.last_error = ""

    def start(self, loopback: AudioDevice, microphone: AudioDevice | None = None) -> None:
        if self.state is not CaptureState.IDLE:
            raise CaptureError("Une capture est déjà en cours ou terminée pour cette session.")
        self._check_kinds(loopback, microphone)
        self.recorders = [SourceRecorder(self.backend, loopback, self.output_dir / "system.wav",
                                         self._clock)]
        if microphone is not None:
            self.recorders.append(SourceRecorder(self.backend, microphone,
                                                 self.output_dir / "microphone.wav", self._clock))
        self._start_all()

    @staticmethod
    def _check_kinds(loopback: AudioDevice, microphone: AudioDevice | None) -> None:
        if loopback.kind is not DeviceKind.LOOPBACK:
            raise CaptureError("La source principale doit être un périphérique de sortie (loopback).")
        if microphone is not None and microphone.kind is not DeviceKind.INPUT:
            raise CaptureError("La source microphone doit être un périphérique d'entrée.")

    def _start_all(self) -> None:
        # Ouverture de toutes les sources d'abord, puis démarrage simultané :
        # les fichiers partagent ainsi la même origine de temps
        opened: list[SourceRecorder] = []
        try:
            for recorder in self.recorders:
                recorder.open()
                opened.append(recorder)
            for recorder in self.recorders:
                recorder.begin()
        except CaptureError as exc:
            for recorder in opened:
                recorder.stop()
            self.state = CaptureState.ERROR
            self.last_error = str(exc)
            raise
        self._timer.start()
        self.state = CaptureState.RECORDING
        log.info("Capture démarrée (%d source(s))", len(self.recorders))

    def pause(self) -> None:
        if self.state is CaptureState.RECORDING:
            for recorder in self.recorders:
                recorder.pause()
            self._timer.pause()
            self.state = CaptureState.PAUSED

    def resume(self) -> None:
        if self.state is CaptureState.PAUSED:
            for recorder in self.recorders:
                recorder.resume()
            self._timer.start()
            self.state = CaptureState.RECORDING

    def stop(self) -> CaptureResult:
        if self.state not in (CaptureState.RECORDING, CaptureState.PAUSED):
            raise CaptureError("Aucune capture active à arrêter.")
        self._timer.pause()
        results = [recorder.stop() for recorder in self.recorders]
        errors = [err for result in results for err in result.errors]
        result = CaptureResult(sources=results, duration_s=self._timer.elapsed(), errors=errors)
        self.state = CaptureState.STOPPED if result.succeeded else CaptureState.ERROR
        log.info("Capture arrêtée : %.1f s, %d fichier(s) exploitable(s)",
                 result.duration_s, len(result.usable_files))
        return result

    # --- informations pour l'interface ---------------------------------------------
    def elapsed(self) -> float:
        return self._timer.elapsed()

    def levels(self) -> dict[DeviceKind, float]:
        return {recorder.device.kind: recorder.level_dbfs for recorder in self.recorders}

    def alerts(self) -> list[str]:
        if self.state is not CaptureState.RECORDING:
            return []
        return [alert for recorder in self.recorders for alert in recorder.health_alerts()]
