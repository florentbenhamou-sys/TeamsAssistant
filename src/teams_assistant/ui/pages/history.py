"""Écran F — Historique : rechercher, consulter, renommer, exporter, supprimer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from teams_assistant import exports
from teams_assistant.models import MeetingSession
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.pages.home import STATUS_LABELS, local_time
from teams_assistant.ui.widgets import button, confirm, error_box, info_box, format_hms, title

COLUMNS = ["Titre", "Créée le", "Durée", "Statut"]


class HistoryPage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.search = QLineEdit()
        self.table = QTableWidget(0, len(COLUMNS))
        self.sessions: list[MeetingSession] = []
        self._build()

    def _build(self) -> None:
        self.search.setPlaceholderText("Rechercher (titre ou contenu des transcriptions)…")
        self.search.textChanged.connect(self.refresh)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _i: self.open("transcript"))
        bar = QHBoxLayout()
        actions: list[tuple[str, Callable[[], None], str]] = [
            ("Ouvrir la transcription", lambda: self.open("transcript"), "primary"),
            ("Ouvrir le compte rendu", lambda: self.open("summary"), ""),
            ("Renommer…", self.rename, ""), ("Exporter…", self.export, ""), ("Supprimer…", self.delete, "danger")]
        for label, slot, kind in actions:
            btn = button(label, kind)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        layout = QVBoxLayout(self)
        layout.addWidget(title("Historique"))
        layout.addWidget(self.search)
        layout.addWidget(self.table)
        layout.addLayout(bar)

    def refresh(self) -> None:
        self.sessions = self.controller.ctx.sessions.search(self.search.text())
        self.table.setRowCount(len(self.sessions))
        for row, s in enumerate(self.sessions):
            values = [s.title, local_time(s.created_at), format_hms(s.duration_s), STATUS_LABELS.get(s.status.value, "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)

    def selected(self) -> MeetingSession | None:
        row = self.table.currentRow()
        return self.sessions[row] if 0 <= row < len(self.sessions) else None

    def open(self, page: str) -> None:
        session = self.selected()
        if session:
            self.controller.open_session(session.id)
            self.navigate(page)

    def rename(self) -> None:
        session = self.selected()
        if session is None:
            return
        name, ok = QInputDialog.getText(self, "Renommer", "Nouveau titre :", text=session.title)
        if ok:
            try:
                self.controller.ctx.sessions.rename(session.id, name)
            except Exception as exc:
                error_box(self, str(exc))
            self.refresh()

    def export(self) -> None:
        session = self.selected()
        if session is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Dossier d'export", str(self.controller.ctx.paths.exports))
        if folder:
            written = export_session(self.controller, session, Path(folder))
            info_box(self, f"{len(written)} fichier(s) exporté(s) dans {folder}.") if written else \
                info_box(self, "Rien à exporter : aucune transcription pour cette session.")

    def delete(self) -> None:
        session = self.selected()
        if session is None:
            return
        if self.controller.capture_active and self.controller.current_session_id == session.id:
            error_box(self, "Arrêtez d'abord la capture en cours.")
            return
        detail = ("Seront supprimés définitivement : les fichiers audio temporaires, la transcription, les "
                  "corrections, le compte rendu et les actions. Les fichiers que vous avez importés restent "
                  "sur votre disque.")
        if confirm(self, f"Supprimer la session « {session.title} » ?", detail):
            self.controller.ctx.sessions.delete_session(session.id)
            if self.controller.current_session_id == session.id:
                self.controller.current_session_id = None
            self.refresh()
            self.controller.notify()


def export_session(controller: Controller, session: MeetingSession, folder: Path) -> list[Path]:
    ctx = controller.ctx
    base = folder / exports.safe_filename(session.title)
    written: list[Path] = []
    transcript = ctx.transcription.latest(session.id)
    if transcript:
        segments = ctx.transcription.segments(transcript.id)
        written.append(exports.write_text(base.with_suffix(".transcription.md"),
                                          exports.transcript_md(session, transcript, segments)))
        written.append(exports.write_text(base.with_suffix(".transcription.json"),
                                          exports.transcript_json(session, transcript, segments)))
    summary = ctx.summaries.latest(session.id)
    if summary:
        content = ctx.summaries.content(summary)
        written.append(exports.write_text(base.with_suffix(".compte-rendu.md"),
                                          exports.summary_md(content, summary.validated)))
    return written
