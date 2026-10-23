"""Fenêtre principale : navigation, pile d'écrans, bandeau permanent d'état de la capture."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from teams_assistant.audio.recorder import CaptureState
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.pages.history import HistoryPage
from teams_assistant.ui.pages.home import HomePage
from teams_assistant.ui.pages.live_session import LiveSessionPage
from teams_assistant.ui.pages.new_session import NewSessionPage
from teams_assistant.ui.pages.settings import SettingsPage
from teams_assistant.ui.pages.summary import SummaryPage
from teams_assistant.ui.pages.transcript import TranscriptPage
from teams_assistant.ui.widgets import STYLE, confirm, format_hms

APP_TITLE = "TeamsAssistant — prototype"
BANNER_STYLE = "background: {color}; color: white; font-weight: 700; font-size: 12pt; padding: 6px 12px;"
NAVIGATION = [("home", "Accueil"), ("new", "Nouvelle session"), ("live", "Session en cours"),
              ("transcript", "Transcription"), ("summary", "Compte rendu"), ("history", "Historique"),
              ("settings", "Paramètres")]


class Page(Protocol):
    def refresh(self) -> None: ...


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 780)
        self.setStyleSheet(STYLE)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(200)
        self.stack = QStackedWidget()
        self.banner = QLabel()
        self.transcript_page = TranscriptPage(controller, self.go)
        self.pages: dict[str, QWidget] = {
            "home": HomePage(controller, self.go), "new": NewSessionPage(controller, self.go),
            "live": LiveSessionPage(controller, self.go), "transcript": self.transcript_page,
            "summary": SummaryPage(controller, self.go, self.show_segments),
            "history": HistoryPage(controller, self.go), "settings": SettingsPage(controller, self.go)}
        self._build()
        self.banner_timer = QTimer(self)
        self.banner_timer.timeout.connect(self.update_banner)
        self.banner_timer.start(500)
        controller.listeners.append(self.update_banner)  # mise à jour immédiate à chaque changement d'état
        self.go("home")

    def _build(self) -> None:
        for key, label in NAVIGATION:
            self.nav.addItem(label)
            self.stack.addWidget(self.pages[key])
        self.nav.currentRowChanged.connect(lambda row: self.go(NAVIGATION[row][0]))
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.banner)
        layout.addLayout(body)
        self.setCentralWidget(root)
        self.update_banner()

    def go(self, key: str) -> None:
        keys = [k for k, _ in NAVIGATION]
        index = keys.index(key)
        if self.nav.currentRow() != index:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(index)
            self.nav.blockSignals(False)
        self.stack.setCurrentIndex(index)
        page = self.pages[key]
        if hasattr(page, "refresh"):
            page.refresh()

    def show_segments(self, seqs: list[int]) -> None:
        self.go("transcript")
        self.transcript_page.highlight(seqs)

    def update_banner(self) -> None:
        """Indicateur permanent, visible sur tous les écrans, reflétant l'état réel de la capture."""
        capture = self.controller.capture
        state = capture.state if capture else CaptureState.IDLE
        if state is CaptureState.RECORDING and capture:
            self.banner.setStyleSheet(BANNER_STYLE.format(color="#dc2626"))
            self.banner.setText(f"● ENREGISTREMENT EN COURS — {format_hms(capture.elapsed())}")
            self.setWindowTitle(f"● REC {format_hms(capture.elapsed())} — {APP_TITLE}")
        elif state is CaptureState.PAUSED and capture:
            self.banner.setStyleSheet(BANNER_STYLE.format(color="#d97706"))
            self.banner.setText(f"❚❚ CAPTURE SUSPENDUE — {format_hms(capture.elapsed())} enregistrées")
            self.setWindowTitle(f"❚❚ PAUSE — {APP_TITLE}")
        else:
            self.banner.clear()
            self.setWindowTitle(APP_TITLE)
        self.banner.setVisible(state in (CaptureState.RECORDING, CaptureState.PAUSED))

    def closeEvent(self, event: QCloseEvent) -> None:
        # Jamais de capture qui continuerait en arrière-plan après fermeture
        if self.controller.capture_active:
            if not confirm(self, "Une capture est en cours. L'arrêter et quitter ?",
                           "L'audio déjà enregistré est conservé et pourra être transcrit."):
                event.ignore()
                return
            live = self.pages["live"]
            assert isinstance(live, LiveSessionPage)
            live.stop()
        self.controller.ctx.close()
        event.accept()
