"""Écran D — Transcription : lancement/reprise, texte horodaté, corrections, recherche, exports."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTableWidgetSelectionRange,
    QVBoxLayout,
    QWidget,
)

from teams_assistant import exports
from teams_assistant.m365.graph import AVAILABILITY_LABELS, TranscriptAvailability, TranscriptCheck
from teams_assistant.models import TranscriptSegment, TranscriptStatus
from teams_assistant.transcription.types import Progress, TranscriptionOptions
from teams_assistant.transcription.whisper_engine import PROFILES
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.widgets import button, error_box, format_hms, muted, title
from teams_assistant.ui.workers import run_async

COLUMNS = ["#", "Début", "Fin", "Intervenant (source)", "Texte", "Fiabilité"]
TEXT_COLUMN = 4
STATUS_FR = {TranscriptStatus.IN_PROGRESS: "en cours", TranscriptStatus.COMPLETED: "terminée",
             TranscriptStatus.INTERRUPTED: "interrompue", TranscriptStatus.ERROR: "en erreur"}


class TranscriptPage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.header = title("Transcription")
        self.info = muted("")
        self.profile = QComboBox()
        self.language = QComboBox()
        self.run_btn = button("Transcrire", "primary")
        self.cancel_btn = button("Interrompre")
        self.progress = QProgressBar()
        self.official_btn = button("Vérifier le transcript Teams officiel")
        self.import_official_btn = button("Importer le transcript officiel")
        self.official_label = muted("")
        self.search = QLineEdit()
        self.diarize = QCheckBox("Distinguer les voix")
        self.speakers_main = count_spin(0)
        self.speakers_mic = count_spin(1)
        self.speaker_combo = QComboBox()
        self.table = QTableWidget(0, len(COLUMNS))
        self.segments: list[TranscriptSegment] = []
        self.cancel_event = threading.Event()
        self.official_check: TranscriptCheck | None = None
        self._loading = False
        self._build()

    def _build(self) -> None:
        for key, profile in PROFILES.items():
            self.profile.addItem(profile.label, key)
        for code, label in (("fr", "Français"), ("auto", "Détection automatique"), ("en", "Anglais")):
            self.language.addItem(label, code)
        self.run_btn.clicked.connect(self.start_transcription)
        self.cancel_btn.clicked.connect(self.cancel_event.set)
        self.official_btn.clicked.connect(self.check_official)
        self.import_official_btn.clicked.connect(self.import_official)
        self.search.setPlaceholderText("Rechercher dans la transcription…")
        self.search.textChanged.connect(self.apply_filter)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        header = self.table.horizontalHeader()
        for column in range(len(COLUMNS)):
            mode = header.ResizeMode.Stretch if column == TEXT_COLUMN else header.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.cellChanged.connect(self._cell_changed)
        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.info)
        layout.addLayout(self._run_bar())
        layout.addLayout(self._voices_bar())
        layout.addWidget(self.progress)
        layout.addLayout(self._official_bar())
        layout.addWidget(self.search)
        layout.addWidget(self.table)
        layout.addLayout(self._export_bar())

    def _run_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        for widget in (QLabel("Profil"), self.profile, QLabel("Langue"), self.language, self.run_btn, self.cancel_btn):
            bar.addWidget(widget)
        return bar

    def _voices_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.diarize.setToolTip("Regroupe les passages par voix (Intervenant 1, 2…). Aucune empreinte "
                                "vocale n'est conservée ; les numéros ne valent que pour cette réunion.")
        self.diarize.toggled.connect(self.speakers_main.setEnabled)
        self.diarize.toggled.connect(self.speakers_mic.setEnabled)
        for widget in (self.diarize, QLabel("Voix sur le son du PC / fichier"), self.speakers_main,
                       QLabel("Voix au micro"), self.speakers_mic):
            bar.addWidget(widget)
        bar.addStretch()
        return bar

    def _official_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(self.official_btn)
        bar.addWidget(self.import_official_btn)
        bar.addWidget(self.official_label, 1)
        return bar

    def _export_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        speaker_btn = button("Renommer…")
        speaker_btn.clicked.connect(self.rename_speaker)
        self.speaker_combo.currentIndexChanged.connect(self._select_speaker_rows)
        bar.addWidget(QLabel("Intervenant"))
        bar.addWidget(self.speaker_combo)
        bar.addWidget(speaker_btn)
        bar.addStretch()
        for fmt in ("txt", "md", "json"):
            btn = button(f"Exporter {fmt.upper()}")
            btn.clicked.connect(lambda _=False, f=fmt: self.export(f))
            bar.addWidget(btn)
        summary_btn = button("Compte rendu →", "primary")
        summary_btn.clicked.connect(lambda: self.navigate("summary"))
        bar.addWidget(summary_btn)
        return bar

    # --- chargement ------------------------------------------------------------------
    def refresh(self) -> None:
        settings = self.controller.ctx.settings.load()
        self.profile.setCurrentIndex(max(0, self.profile.findData(settings.transcription_profile)))
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.diarize.setChecked(settings.diarize_speakers)
        self.speakers_main.setValue(settings.speakers_main)
        self.speakers_mic.setValue(settings.speakers_mic)
        self.speakers_main.setEnabled(settings.diarize_speakers)
        self.speakers_mic.setEnabled(settings.diarize_speakers)
        self.progress.setValue(0)
        self.cancel_btn.setEnabled(False)
        self.official_check = None
        self.import_official_btn.setEnabled(False)
        self.official_label.clear()
        self.load()

    def load(self) -> None:
        session_id = self.controller.current_session_id
        if session_id is None:
            self.header.setText("Transcription — aucune session sélectionnée")
            self._set_rows([])
            self.run_btn.setEnabled(False)
            return
        ctx = self.controller.ctx
        session = ctx.sessions.get(session_id)
        transcript = ctx.transcription.latest(session_id)
        self.header.setText(f"Transcription — {session.title}")
        self.official_btn.setEnabled(bool(session.join_url) and self.controller.m365_configured())
        self.run_btn.setEnabled(bool(ctx.transcription.sources_for(session_id)))
        self.run_btn.setText("Reprendre" if ctx.transcription.can_resume(session_id, self.options()) else "Transcrire")
        self.info.setText(self._describe(transcript, session_id))
        self._set_rows(ctx.transcription.segments(transcript.id) if transcript else [])

    def _describe(self, transcript: Any, session_id: str) -> str:
        sources = len(self.controller.ctx.transcription.sources_for(session_id))
        if transcript is None:
            return f"Pas encore de transcription. {sources} fichier(s) audio exploitable(s)."
        origin = "Transcript officiel Teams" if transcript.origin.value == "teams_official" \
            else f"Transcription locale ({transcript.engine} {transcript.model}, {transcript.profile})"
        warnings = " ".join(f"⚠ {w}" for w in transcript.warnings)
        error = f" Erreur : {transcript.error}" if transcript.status is not TranscriptStatus.COMPLETED else ""
        return f"{origin} — statut : {STATUS_FR[transcript.status]}. {warnings}{error}"

    def _set_rows(self, segments: list[TranscriptSegment]) -> None:
        self._loading = True
        self.segments = segments
        self.table.setRowCount(len(segments))
        for row, seg in enumerate(segments):
            values = [str(seg.seq), format_hms(seg.start_s), format_hms(seg.end_s), seg.speaker or "",
                      seg.text, ("⚠ à vérifier" if seg.uncertain else "") + (" ✎ corrigé" if seg.edited else "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col != TEXT_COLUMN:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()
        self._loading = False
        self._fill_speakers(segments)
        self.apply_filter()

    def _fill_speakers(self, segments: list[TranscriptSegment]) -> None:
        """Liste des intervenants avec nombre de passages et première prise de parole."""
        first: dict[str, float] = {}
        counts: dict[str, int] = {}
        for seg in segments:
            label = seg.speaker or ""
            first.setdefault(label, seg.start_s)
            counts[label] = counts.get(label, 0) + 1
        self.speaker_combo.blockSignals(True)
        self.speaker_combo.clear()
        for label in sorted(first, key=lambda name: first[name]):
            self.speaker_combo.addItem(f"{label or '(sans libellé)'} — {counts[label]} passage(s), "
                                       f"dès {format_hms(first[label])}", label)
        self.speaker_combo.setPlaceholderText("Choisir un intervenant…")
        self.speaker_combo.setCurrentIndex(-1)
        self.speaker_combo.blockSignals(False)

    def _select_speaker_rows(self) -> None:
        """Sélectionne tous les passages de l'intervenant choisi pour faciliter l'identification."""
        label = self.speaker_combo.currentData()
        self.highlight([s.seq for s in self.segments if (s.speaker or "") == label])

    def _cell_changed(self, row: int, column: int) -> None:
        if self._loading or column != TEXT_COLUMN:
            return
        cell = self.table.item(row, column)
        if cell is not None:
            self.controller.ctx.transcription.correct_text(self.segments[row].id, cell.text())

    def apply_filter(self) -> None:
        needle = self.search.text().strip().lower()
        for row, seg in enumerate(self.segments):
            self.table.setRowHidden(row, bool(needle) and needle not in seg.text.lower())

    def highlight(self, seqs: list[int]) -> None:
        """Sélectionne les segments cités par le compte rendu (traçabilité)."""
        self.search.clear()
        self.table.clearSelection()
        rows = [row for row, seg in enumerate(self.segments) if seg.seq in seqs]
        for row in rows:
            self.table.setRangeSelected(QTableWidgetSelectionRange(row, 0, row, len(COLUMNS) - 1), True)
        target = self.table.item(rows[0], 0) if rows else None
        if target is not None:
            self.table.scrollToItem(target)

    # --- transcription -------------------------------------------------------------------
    def options(self) -> TranscriptionOptions:
        settings = self.controller.ctx.settings.load()
        language = self.language.currentData()
        return TranscriptionOptions(language=None if language == "auto" else language,
                                    profile=self.profile.currentData(), separate_sources=settings.separate_sources,
                                    diarize=self.diarize.isChecked(), speakers_main=self.speakers_main.value(),
                                    speakers_mic=self.speakers_mic.value())

    def start_transcription(self) -> None:
        session_id = self.controller.current_session_id
        if session_id is None:
            return
        settings = self.controller.ctx.settings.load()
        options, self.cancel_event = self.options(), threading.Event()
        cancel = self.cancel_event
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.info.setText("Transcription en cours… (premier usage : téléchargement du modèle)")

        def job(emit: Callable[[Any], None]) -> Any:
            return self.controller.ctx.transcription.transcribe(
                session_id, options, on_progress=emit, cancel=cancel,
                delete_audio_after=settings.delete_audio_after_transcription)

        run_async(job, self._done, self._failed, self._progress)

    def _progress(self, progress: Progress) -> None:
        self.progress.setValue(int(progress.ratio * 100))
        step = progress.message or f"tronçon {progress.chunk_index + 1}/{progress.chunk_count}"
        self.progress.setFormat(f"%p % — {step}")

    def _done(self, _result: Any) -> None:
        self.cancel_btn.setEnabled(False)
        self.progress.setValue(100)
        self.load()
        self.controller.notify()

    def _failed(self, message: str) -> None:
        self.cancel_btn.setEnabled(False)
        self.load()
        if self.cancel_event.is_set():
            self.info.setText(self.info.text() + " — interrompue à votre demande, reprise possible.")
        else:
            error_box(self, f"Transcription interrompue : {message}",
                      "Les tronçons terminés sont conservés : « Reprendre » relance la suite.")

    # --- transcript officiel ---------------------------------------------------------------
    def check_official(self) -> None:
        session = self.controller.ctx.sessions.get(self.controller.current_session_id or "")
        self.official_label.setText("Vérification…")
        run_async(lambda _e: self.controller.m365().check_transcripts(session.join_url or "", interactive=True),
                  self._official_checked, lambda err: self.official_label.setText(f"Erreur : {err}"))

    def _official_checked(self, check: TranscriptCheck) -> None:
        self.official_check = check
        self.official_label.setText(AVAILABILITY_LABELS[check.availability])
        self.import_official_btn.setEnabled(check.availability is TranscriptAvailability.AVAILABLE)

    def import_official(self) -> None:
        if self.official_check is None or self.controller.current_session_id is None:
            return
        ctx, session_id, check = self.controller.ctx, self.controller.current_session_id, self.official_check
        run_async(lambda _e: self.controller.m365().import_official_transcript(
            ctx.sessions, ctx.transcription.repo, session_id, check),
            lambda _r: self.load(), lambda err: error_box(self, f"Import impossible : {err}"))

    # --- actions ---------------------------------------------------------------------------
    def rename_speaker(self) -> None:
        transcript = self.controller.ctx.transcription.latest(self.controller.current_session_id or "")
        old = self.speaker_combo.currentData()
        if old is None and self.table.currentRow() >= 0:
            old = self.segments[self.table.currentRow()].speaker or ""
        if transcript is None or old is None:
            return
        new, ok = QInputDialog.getText(
            self, "Renommer", f"Nom pour « {old} » (uniquement si vous l'avez reconnu).\n"
            "Donner le même nom à deux intervenants les fusionne.", text=old)
        if ok and new.strip():
            self.controller.ctx.transcription.rename_speaker(transcript.id, old, new)
            self.load()

    def export(self, fmt: str) -> None:
        ctx = self.controller.ctx
        session_id = self.controller.current_session_id
        transcript = ctx.transcription.latest(session_id or "")
        if session_id is None or transcript is None:
            return
        session = ctx.sessions.get(session_id)
        default = ctx.paths.exports / f"{exports.safe_filename(session.title)}-transcription.{fmt}"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter", str(default))
        if not path:
            return
        segments = ctx.transcription.segments(transcript.id)
        text = {"txt": lambda: exports.transcript_txt(session, segments),
                "md": lambda: exports.transcript_md(session, transcript, segments),
                "json": lambda: exports.transcript_json(session, transcript, segments)}[fmt]()
        exports.write_text(Path(path), text)


def count_spin(default: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 20)
    spin.setValue(default)
    spin.setSpecialValueText("auto")  # 0 = estimation automatique
    spin.setToolTip("Indiquer le nombre de personnes améliore nettement la séparation. 1 = pas de séparation.")
    return spin
