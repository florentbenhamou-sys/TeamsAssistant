"""Parcours complet de l'interface hors écran (QT_QPA_PLATFORM=offscreen), sans matériel réel.

Le backend audio et le moteur sont des doublures de test : ce test vérifie le câblage des écrans,
pas la capture réelle (voir test_hardware_audio.py).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QThreadPool  # noqa: E402

from fakes import FakeBackend, FakeSpeechEngine, sine_block  # noqa: E402
from teams_assistant.app_context import build_context  # noqa: E402
from teams_assistant.audio.types import DeviceKind  # noqa: E402
from teams_assistant.config import AppPaths  # noqa: E402
from teams_assistant.models import SessionStatus  # noqa: E402
from teams_assistant.ui import pages  # noqa: E402,F401
from teams_assistant.ui.controller import Controller  # noqa: E402
from teams_assistant.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture()
def window(app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch) -> Iterator[MainWindow]:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    backend = FakeBackend()
    ctx = build_context(app_paths, engine=FakeSpeechEngine())
    for module in ("history", "summary", "settings"):
        monkeypatch.setattr(f"teams_assistant.ui.pages.{module}.confirm", lambda *a, **k: True)
    monkeypatch.setattr("teams_assistant.ui.pages.settings.get_secret", lambda name: None)
    win = MainWindow(Controller(ctx, backend_factory=lambda _name: backend))
    win.fake_backend = backend  # type: ignore[attr-defined]
    yield win
    win.controller.capture = None
    win.close()
    app.processEvents()


def _wait() -> None:
    QThreadPool.globalInstance().waitForDone(10000)
    QtWidgets.QApplication.processEvents()


def test_full_flow_capture_transcribe_summarize_delete(window: MainWindow) -> None:
    new = window.pages["new"]
    window.go("new")
    assert not new.start_btn.isEnabled()  # pas de capture sans confirmation des autorisations
    new.title_edit.setText("Démo UI")
    new.consent.setChecked(True)
    new.start_btn.click()
    assert window.controller.capture_active and window.banner.isVisibleTo(window)
    assert "ENREGISTREMENT" in window.banner.text()
    window.fake_backend.streams[DeviceKind.LOOPBACK].emit(sine_block(3.0))  # type: ignore[attr-defined]
    live = window.pages["live"]
    live.pause_btn.click()
    window.update_banner()
    assert "SUSPENDUE" in window.banner.text()
    live.resume_btn.click()
    live.stop_btn.click()
    assert not window.controller.capture_active
    session_id = window.controller.current_session_id
    assert session_id and window.controller.ctx.sessions.get(session_id).status is SessionStatus.RECORDED

    window.go("transcript")
    transcript_page = window.pages["transcript"]
    transcript_page.run_btn.click()
    _wait()
    assert transcript_page.table.rowCount() == 3
    transcript_page.table.item(0, 4).setText("Texte corrigé à la main")
    first = window.controller.ctx.transcription.segments(
        window.controller.ctx.transcription.latest(session_id).id)[0]  # type: ignore[union-attr]
    assert first.text == "Texte corrigé à la main" and first.original_text

    window.go("summary")
    summary_page = window.pages["summary"]
    summary_page.generate()
    _wait()
    assert summary_page.summary is not None, (summary_page.status.text(), summary_page.generator.count(), summary_page.generator.currentData())
    summary_page.validate()
    assert window.controller.ctx.summaries.latest(session_id).validated  # type: ignore[union-attr]

    window.go("history")
    history = window.pages["history"]
    assert history.table.rowCount() == 1
    history.table.selectRow(0)
    history.delete()
    assert history.table.rowCount() == 0


def test_all_pages_render(window: MainWindow) -> None:
    for key in ["home", "new", "live", "transcript", "summary", "history", "settings"]:
        window.go(key)
    assert window.stack.currentWidget() is window.pages["settings"]
