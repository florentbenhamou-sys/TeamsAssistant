"""Écran E — Compte rendu : génération, correction, validation, traçabilité, exports."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from teams_assistant import exports
from teams_assistant.models import MeetingSummary
from teams_assistant.services.summary_service import generator_for
from teams_assistant.summary.schema import FACT, SECTIONS, SummaryContent, SummaryItem
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.widgets import button, confirm, error_box, muted, title
from teams_assistant.ui.workers import run_async

COLUMNS = ["Section", "Élément", "Nature", "Responsable", "Échéance", "Segments"]
EDITABLE = {1, 2, 3, 4}
SECTION_LABELS = dict(SECTIONS)
SECTION_KEYS_BY_LABEL = {label: key for key, label in SECTIONS}


class SummaryPage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None],
                 show_segments: Callable[[list[int]], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.show_segments = show_segments
        self.header = title("Compte rendu")
        self.meta = QLabel()
        self.notice = muted("")
        self.generator = QComboBox()
        self.section_combo = QComboBox()
        self.table = QTableWidget(0, len(COLUMNS))
        self.status = QLabel()
        self.summary: MeetingSummary | None = None
        self.content: SummaryContent | None = None
        self._build()

    def _build(self) -> None:
        for key, label in SECTIONS:
            self.section_combo.addItem(label, key)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.meta.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addLayout(self._generate_bar())
        layout.addWidget(self.meta)
        layout.addWidget(self.notice)
        layout.addWidget(self.table)
        layout.addLayout(self._edit_bar())
        layout.addWidget(self.status)

    def _generate_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        generate = button("Générer le compte rendu", "primary")
        generate.clicked.connect(self.generate)
        bar.addWidget(QLabel("Générateur"))
        bar.addWidget(self.generator)
        bar.addWidget(generate)
        bar.addStretch()
        return bar

    def _edit_bar(self) -> QVBoxLayout:
        # Deux lignes de boutons : reste utilisable sur un écran de tablette (1024 px)
        edit_actions: list[tuple[str, Callable[[], None], str]] = [
            ("Ajouter", self.add_item, ""), ("Supprimer la ligne", self.remove_item, ""),
            ("Voir le passage", self.open_refs, "")]
        final_actions: list[tuple[str, Callable[[], None], str]] = [
            ("Enregistrer", self.save, ""), ("Valider le compte rendu", self.validate, "primary"),
            ("Exporter Markdown", lambda: self.export("md"), ""), ("Exporter DOCX", lambda: self.export("docx"), "")]
        rows = QVBoxLayout()
        for prefix, actions in (([self.section_combo], edit_actions), ([], final_actions)):
            bar = QHBoxLayout()
            for widget in prefix:
                bar.addWidget(widget)
            for label, slot, kind in actions:
                btn = button(label, kind)
                btn.clicked.connect(slot)
                bar.addWidget(btn)
            bar.addStretch()
            rows.addLayout(bar)
        return rows

    # --- chargement / affichage ------------------------------------------------------------
    def refresh(self) -> None:
        settings = self.controller.ctx.settings.load()
        self.generator.clear()
        self.generator.addItem("Local, sans IA (aucune donnée envoyée)", "local")
        if settings.cloud_ai_enabled:
            self.generator.addItem(f"IA cloud Claude ({settings.cloud_model}) — envoi du texte", "claude")
        self.load()

    def load(self) -> None:
        session_id = self.controller.current_session_id
        self.summary = self.controller.ctx.summaries.latest(session_id) if session_id else None
        self.content = self.controller.ctx.summaries.content(self.summary) if self.summary else None
        title_text = self.controller.ctx.sessions.get(session_id).title if session_id else "aucune session"
        self.header.setText(f"Compte rendu — {title_text}")
        self._render()

    def _render(self) -> None:
        content = self.content
        rows = [(key, item) for key, _ in SECTIONS for item in (content.sections.get(key, []) if content else [])]
        self.table.setRowCount(len(rows))
        for row, (key, item) in enumerate(rows):
            self._set_row(row, key, item)
        self.table.resizeRowsToContents()
        if content is None:
            self.meta.setText("Aucun compte rendu : générez-le à partir de la transcription terminée.")
            self.notice.clear()
            self.status.clear()
            return
        participants = "; ".join(f"{p.name} ({p.status})" for p in content.participants) or "inconnus"
        self.meta.setText(f"<b>Date</b> : {content.date or 'inconnue'} — <b>Durée</b> : "
                          f"{content.duration or 'inconnue'}<br><b>Participants</b> : {participants}")
        self.notice.setText(content.generator_notice)
        validated = self.summary is not None and self.summary.validated
        self.status.setText("✔ Validé" if validated else "Brouillon — à relire et valider")

    def _set_row(self, row: int, key: str, item: SummaryItem) -> None:
        refs = ", ".join(str(r) for r in item.refs)
        values = [SECTION_LABELS[key], item.text, item.kind, item.owner, item.due, refs]
        for col, value in enumerate(values):
            cell = QTableWidgetItem(value)
            if col not in EDITABLE:
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if col == 0:
                cell.setData(Qt.ItemDataRole.UserRole, item.speaker)  # provenance conservée, non affichée
            self.table.setItem(row, col, cell)

    def _text(self, row: int, column: int) -> str:
        cell = self.table.item(row, column)
        return cell.text() if cell else ""

    def _collect(self) -> SummaryContent | None:
        """Relit le tableau (corrections de l'utilisateur) vers la structure du compte rendu."""
        if self.content is None:
            return None
        sections: dict[str, list[SummaryItem]] = {key: [] for key, _ in SECTIONS}
        for row in range(self.table.rowCount()):
            cells = [self._text(row, c) for c in range(len(COLUMNS))]
            refs = [int(r) for r in cells[5].replace(" ", "").split(",") if r.isdigit()]
            first = self.table.item(row, 0)
            speaker = (first.data(Qt.ItemDataRole.UserRole) if first else "") or ""
            sections[SECTION_KEYS_BY_LABEL[cells[0]]].append(
                SummaryItem(text=cells[1].strip(), kind=cells[2].strip() or FACT, refs=refs,
                            speaker=str(speaker), owner=cells[3].strip(), due=cells[4].strip()))
        self.content.sections = {k: [i for i in v if i.text] for k, v in sections.items()}
        return self.content

    # --- actions ---------------------------------------------------------------------------
    def generate(self) -> None:
        session_id = self.controller.current_session_id
        if session_id is None:
            return
        settings = self.controller.ctx.settings.load()
        settings.summary_generator = self.generator.currentData() or "local"
        confirmed = settings.summary_generator != "claude" or confirm(
            self, "Envoyer le texte de la transcription au service Anthropic (Claude) ?",
            "Seul le texte est envoyé, jamais l'audio. Service payant à l'usage (voir docs/compte-rendu.md).")
        try:
            generator = generator_for(settings, confirmed)
        except Exception as exc:
            error_box(self, str(exc))
            return
        self.status.setText("Génération en cours…")
        run_async(lambda _e: self.controller.ctx.summaries.generate(session_id, generator),
                  self._generated, self._generation_failed)

    def _generated(self, _summary: object) -> None:
        self.load()
        self.controller.notify()

    def _generation_failed(self, message: str) -> None:
        self.status.clear()
        error_box(self, f"Génération impossible : {message}")

    def add_item(self) -> None:
        if self.content is None:
            return
        key = self.section_combo.currentData()
        self._collect()
        self.content.sections[key].append(SummaryItem(text="(nouvel élément — à compléter)", kind=FACT))
        self._render()

    def remove_item(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def open_refs(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        cell = self.table.item(row, 5)
        refs = [int(r) for r in (cell.text() if cell else "").replace(" ", "").split(",") if r.isdigit()]
        if refs:
            self.show_segments(refs)

    def save(self) -> None:
        content = self._collect()
        if self.summary is not None and content is not None:
            self.controller.ctx.summaries.update(self.summary, content)
            self.load()

    def validate(self) -> None:
        if self.summary is None:
            return
        self.save()
        if confirm(self, "Valider ce compte rendu ?", "Confirmez l'avoir relu : décisions, engagements, "
                                                      "responsables et échéances."):
            self.controller.ctx.summaries.validate(self.summary)
            self.load()

    def export(self, fmt: str) -> None:
        if self.summary is None or self.content is None:
            return
        self.save()
        assert self.content is not None and self.summary is not None
        default = self.controller.ctx.paths.exports / f"{exports.safe_filename(self.content.title)}-compte-rendu.{fmt}"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", str(default))
        if not path:
            return
        if fmt == "md":
            exports.write_text(Path(path), exports.summary_md(self.content, self.summary.validated))
        else:
            exports.summary_docx(self.content, self.summary.validated, Path(path))
