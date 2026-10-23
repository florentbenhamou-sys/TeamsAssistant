"""Enregistrement d'une source audio vers un WAV, avec pause/reprise et contrôle de santé.

Particularité WASAPI loopback (constatée sur le poste) : aucune trame n'est livrée tant
que rien n'est joué. Le recorder comble ces trous par du silence, en se basant sur
l'horloge système, afin que les horodatages du fichier restent alignés sur la réunion.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from teams_assistant.audio.types import (
    AudioBlock,
    AudioDevice,
    AudioStream,
    CaptureBackend,
    CaptureError,
    DeviceKind,
)
from teams_assistant.audio.wav_utils import WavReport, WavWriter, analyze_wav, block_level_dbfs
from teams_assistant.logging_setup import get_logger

log = get_logger("audio.recorder")
GAP_THRESHOLD_S = 0.5  # trou minimal comblé par du silence
INPUT_STALL_WARNING_S = 3.0  # un micro qui ne livre plus rien est anormal


class CaptureState(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class SourceResult:
    device: AudioDevice
    path: Path
    report: WavReport
    padded_seconds: float
    errors: list[str] = field(default_factory=list)


class ActiveClock:
    """Chronomètre qui ne compte que le temps hors pause."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._accumulated = 0.0
        self._started_at: float | None = None

    def start(self) -> None:
        if self._started_at is None:
            self._started_at = self._clock()

    def pause(self) -> None:
        if self._started_at is not None:
            self._accumulated += self._clock() - self._started_at
            self._started_at = None

    def elapsed(self) -> float:
        running = self._clock() - self._started_at if self._started_at is not None else 0.0
        return self._accumulated + running

    @property
    def running(self) -> bool:
        return self._started_at is not None


class SourceRecorder:
    """Capture d'un périphérique : le callback du flux alimente une file, un thread écrit le WAV."""

    def __init__(self, backend: CaptureBackend, device: AudioDevice, out_path: Path,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.backend = backend
        self.device = device
        self.out_path = out_path
        self._clock = clock
        self._active = ActiveClock(clock)
        self._queue: queue.Queue[tuple[float, AudioBlock]] = queue.Queue()
        self._stop = threading.Event()
        self._stream: AudioStream | None = None
        self._writer: WavWriter | None = None
        self._thread: threading.Thread | None = None
        self._last_block_at: float | None = None
        self.level_dbfs = -math.inf
        self.padded_frames = 0
        self.errors: list[str] = []

    # --- cycle de vie -------------------------------------------------------------
    def start(self) -> None:
        self.open()
        self.begin()

    def open(self) -> None:
        """Ouvre le flux et le fichier sans démarrer la capture (étape lente : énumération)."""
        self._stream = self.backend.open_stream(self.device, self._enqueue)
        self._writer = WavWriter(self.out_path, self._stream.sample_rate, self._stream.channels)
        self._thread = threading.Thread(target=self._write_loop, daemon=True,
                                        name=f"writer-{self.device.kind}")
        self._thread.start()

    def begin(self) -> None:
        """Démarre l'horloge et le flux ; appelé au même instant pour toutes les sources."""
        assert self._stream is not None, "open() doit être appelé avant begin()"
        self._active.start()
        self._last_block_at = self._clock()
        try:
            self._stream.start()
        except Exception as exc:
            self._abort()
            raise CaptureError(f"Démarrage impossible sur « {self.device.name} » : {exc}") from exc

    def active_seconds(self) -> float:
        return self._active.elapsed()

    def pause(self) -> None:
        self._active.pause()

    def resume(self) -> None:
        self._active.start()
        self._last_block_at = self._clock()

    def stop(self) -> SourceResult:
        expected_end = self._active.elapsed()
        self._active.pause()
        self._close_stream()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._finalize(expected_end)
        return SourceResult(device=self.device, path=self.out_path, report=analyze_wav(self.out_path),
                            padded_seconds=self.padded_frames / self._rate(), errors=list(self.errors))

    def _abort(self) -> None:
        self._close_stream()
        self._stop.set()
        if self._writer is not None:
            self._writer.close()

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    # --- flux de données ----------------------------------------------------------
    def _enqueue(self, block: AudioBlock) -> None:
        # Appelé depuis le thread audio : rapide, sans entrée/sortie
        if not self._active.running:
            return  # en pause : on ignore réellement l'audio
        self._last_block_at = self._clock()
        self._queue.put((self._active.elapsed(), block))

    def _write_loop(self) -> None:
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                received_at, block = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._write_block(received_at, block)
            except OSError as exc:
                self.errors.append(f"Écriture disque impossible : {exc}")
                log.error("Écriture WAV échouée : %s", exc)
                return

    def _write_block(self, received_at: float, block: AudioBlock) -> None:
        assert self._writer is not None
        expected_start = int(received_at * self._rate()) - block.shape[0]
        self._pad_to(expected_start)
        self._writer.write(block)
        self.level_dbfs = block_level_dbfs(block)

    def _pad_to(self, expected_frames: int) -> None:
        assert self._writer is not None
        missing = expected_frames - self._writer.frames_written
        if missing > GAP_THRESHOLD_S * self._rate():
            self._writer.write_silence(missing)
            self.padded_frames += missing

    def _finalize(self, expected_end: float) -> None:
        if self._writer is None:
            return
        try:
            self._pad_to(int(expected_end * self._rate()))
        finally:
            self._writer.close()

    # --- état ---------------------------------------------------------------------
    def _rate(self) -> int:
        return self._writer.sample_rate if self._writer else self.device.sample_rate

    def recorded_seconds(self) -> float:
        return self._writer.frames_written / self._rate() if self._writer else 0.0

    def seconds_since_last_block(self) -> float:
        return self._clock() - self._last_block_at if self._last_block_at is not None else 0.0

    def health_alerts(self) -> list[str]:
        """Alertes à afficher en direct ; ne lève pas d'exception."""
        alerts = list(self.errors)
        if self._stream is not None and not self._stream.is_alive():
            alerts.append(f"Flux interrompu sur « {self.device.name} » (périphérique débranché ?)")
        silent_for = self.seconds_since_last_block()
        if self._active.running and silent_for > INPUT_STALL_WARNING_S:
            if self.device.kind is DeviceKind.INPUT:
                alerts.append(f"Le microphone ne transmet plus de données depuis {silent_for:.0f} s")
            else:
                alerts.append(f"Aucun son diffusé sur « {self.device.name} » depuis {silent_for:.0f} s "
                              "(normal en cas de silence ; sinon vérifiez la sortie audio de Teams)")
        return alerts

    @property
    def stream_alive(self) -> bool:
        return self._stream is not None and self._stream.is_alive()
