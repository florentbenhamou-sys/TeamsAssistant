"""Écran A — Accueil."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from teams_assistant.models import TranscriptOrigin
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.widgets import button, card, muted, title
from teams_assistant.ui.workers import run_async

STATUS_LABELS = {"draft": "brouillon", "recorded": "audio enregistré", "transcribing": "transcription…",
                 "transcribed": "transcrite", "summarized": "compte rendu", "error": "erreur"}


def local_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m %H:%M")
    except ValueError:
        return iso


class HomePage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.app_status = QLabel()
        self.m365_status = QLabel()
        self.meetings = QListWidget()
        self.transcripts = QListWidget()
        self.summaries = QListWidget()
        self._build()

    def _build(self) -> None:
        start = button("Nouvelle session de transcription", "primary")
        start.clicked.connect(lambda: self.navigate("new"))
        refresh = button("Actualiser les réunions")
        refresh.clicked.connect(self.load_meetings)
        for widget in (self.transcripts, self.summaries):
            widget.itemDoubleClicked.connect(self._open_item)
        layout = QVBoxLayout(self)
        layout.addWidget(title("Accueil"))
        layout.addWidget(card(self.app_status, self.m365_status))
        layout.addWidget(start)
        lists = QHBoxLayout()
        lists.addWidget(card(QLabel("<b>Réunions à venir (Outlook)</b>"), self.meetings, refresh))
        lists.addWidget(card(QLabel("<b>Dernières transcriptions</b>"), self.transcripts))
        lists.addWidget(card(QLabel("<b>Derniers comptes rendus</b>"), self.summaries))
        layout.addLayout(lists)
        layout.addWidget(muted("Double-cliquez sur un élément pour l'ouvrir."))

    def refresh(self) -> None:
        settings = self.controller.ctx.settings.load()
        self.app_status.setText(f"Application prête — données : {self.controller.ctx.paths.base}<br>"
                                f"Transcription locale : profil « {settings.transcription_profile} », "
                                f"IA cloud : {'activée' if settings.cloud_ai_enabled else 'désactivée'}")
        self._m365_status()
        self._fill_recent()

    def _m365_status(self) -> None:
        if not self.controller.m365_configured():
            self.m365_status.setText("Microsoft 365 : non configuré (facultatif — voir Paramètres)")
            return
        try:
            account = self.controller.m365().account()
        except Exception as exc:
            self.m365_status.setText(f"Microsoft 365 : indisponible ({exc})")
            return
        self.m365_status.setText(f"Microsoft 365 : connecté ({account.username})" if account
                                 else "Microsoft 365 : non connecté")

    def _fill_recent(self) -> None:
        ctx = self.controller.ctx
        self.transcripts.clear()
        for transcript in ctx.transcription.repo.recent(10):
            session = ctx.sessions.repo.get(transcript.session_id)
            origin = "Teams" if transcript.origin is TranscriptOrigin.TEAMS_OFFICIAL else "locale"
            if session:
                self._add(self.transcripts, f"{session.title} — {origin}, {transcript.status.value}",
                          ("transcript", session.id))
        self.summaries.clear()
        for summary in ctx.summaries.repo.recent(10):
            session = ctx.sessions.repo.get(summary.session_id)
            if session:
                state = "validé" if summary.validated else "brouillon"
                self._add(self.summaries, f"{session.title} — {state}", ("summary", session.id))

    @staticmethod
    def _add(widget: QListWidget, text: str, data: Any) -> None:
        item = QListWidgetItem(text)
        item.setData(256, data)
        widget.addItem(item)

    def _open_item(self, item: QListWidgetItem) -> None:
        page, session_id = item.data(256)
        self.controller.open_session(session_id)
        self.navigate(page)

    def load_meetings(self) -> None:
        if not self.controller.m365_configured():
            self.meetings.clear()
            self.meetings.addItem("Calendrier non configuré")
            return
        self.meetings.clear()
        self.meetings.addItem("Chargement…")
        run_async(lambda _p: self.controller.m365().upcoming(7), self._show_meetings, self._meetings_failed)

    def _meetings_failed(self, message: str) -> None:
        self.meetings.clear()
        self.meetings.addItem(f"Erreur : {message}")

    def _show_meetings(self, meetings: list[Any]) -> None:
        self.controller.meetings = meetings
        self.meetings.clear()
        for meeting in meetings:
            teams = " [Teams]" if meeting.is_teams else ""
            self.meetings.addItem(f"{local_time(meeting.start)} {meeting.subject}{teams}")
        if not meetings:
            self.meetings.addItem("Aucune réunion dans les 7 prochains jours")
