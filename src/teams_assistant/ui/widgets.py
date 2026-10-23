"""Composants et utilitaires d'interface partagés."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; }
QListWidget#nav { background: #1f2937; color: #e5e7eb; border: none; font-size: 11pt; }
QListWidget#nav::item { padding: 10px 14px; }
QListWidget#nav::item:selected { background: #2563eb; color: white; }
QLabel[class="title"] { font-size: 16pt; font-weight: 600; }
QLabel[class="muted"] { color: #6b7280; }
QFrame[class="card"] { background: palette(base); border: 1px solid #d1d5db; border-radius: 8px; }
QPushButton[class="primary"] { background: #2563eb; color: white; padding: 8px 16px; border-radius: 6px; }
QPushButton[class="primary"]:disabled { background: #93c5fd; }
QPushButton[class="danger"] { background: #dc2626; color: white; padding: 8px 16px; border-radius: 6px; }
QLabel#recBanner { background: #dc2626; color: white; font-weight: 700; padding: 6px 12px; }
QLabel#pauseBanner { background: #d97706; color: white; font-weight: 700; padding: 6px 12px; }
"""


def title(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "title")
    return label


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("class", "muted")
    label.setWordWrap(True)
    return label


def button(text: str, kind: str = "") -> QPushButton:
    btn = QPushButton(text)
    if kind:
        btn.setProperty("class", kind)
    return btn


def card(*widgets: QWidget) -> QFrame:
    frame = QFrame()
    frame.setProperty("class", "card")
    layout = QVBoxLayout(frame)
    for widget in widgets:
        layout.addWidget(widget)
    return frame


def format_hms(seconds: float) -> str:
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


class LevelMeter(QProgressBar):
    """Vumètre en dBFS (-60 à 0). Affiche le niveau réel du dernier bloc reçu."""

    def __init__(self) -> None:
        super().__init__()
        self.setRange(0, 60)
        self.setTextVisible(True)
        self.set_level(-math.inf)

    def set_level(self, dbfs: float) -> None:
        if math.isinf(dbfs):
            self.setValue(0)
            self.setFormat("aucun signal")
            return
        self.setValue(int(max(0.0, min(60.0, dbfs + 60))))
        self.setFormat(f"{dbfs:.0f} dBFS")


def error_box(parent: QWidget, message: str, hint: str = "") -> None:
    box = QMessageBox(QMessageBox.Icon.Warning, "TeamsAssistant", message, parent=parent)
    if hint:
        box.setInformativeText(hint)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.exec()


def info_box(parent: QWidget, message: str) -> None:
    QMessageBox.information(parent, "TeamsAssistant", message)


def confirm(parent: QWidget, question: str, detail: str = "") -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, "Confirmation", question,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    if detail:
        box.setInformativeText(detail)
    return box.exec() == QMessageBox.StandardButton.Yes
