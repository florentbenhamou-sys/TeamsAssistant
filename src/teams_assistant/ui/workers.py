"""Exécution des traitements longs hors du fil de l'interface (QThreadPool)."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from teams_assistant.logging_setup import get_logger

log = get_logger("ui.workers")


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    """Exécute fn(progress_emit) dans un thread ; résultat ou erreur renvoyés par signaux."""

    def __init__(self, fn: Callable[[Callable[[Any], None]], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit)
        except Exception as exc:  # toute erreur est remontée à l'écran, jamais masquée
            log.error("Tâche en échec : %s", exc)
            log.debug(traceback.format_exc())
            self.signals.failed.emit(str(exc))
            return
        self.signals.done.emit(result)


_ACTIVE: set[Worker] = set()  # références conservées : sans elles, les signaux peuvent être perdus


def run_async(fn: Callable[[Callable[[Any], None]], Any], on_done: Callable[[Any], None],
              on_error: Callable[[str], None], on_progress: Callable[[Any], None] | None = None) -> Worker:
    worker = Worker(fn)
    worker.setAutoDelete(False)
    _ACTIVE.add(worker)
    worker.signals.done.connect(on_done)
    worker.signals.failed.connect(on_error)
    worker.signals.done.connect(lambda _r: _ACTIVE.discard(worker))
    worker.signals.failed.connect(lambda _e: _ACTIVE.discard(worker))
    if on_progress is not None:
        worker.signals.progress.connect(on_progress)
    QThreadPool.globalInstance().start(worker)
    return worker
