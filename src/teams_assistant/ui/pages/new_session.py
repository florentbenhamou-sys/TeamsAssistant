"""Écran B — Nouvelle session : titre, réunion Outlook, périphériques, confidentialité, démarrage."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from teams_assistant.audio.capture_session import CaptureSession
from teams_assistant.audio.types import AudioDevice, CaptureError, DeviceKind
from teams_assistant.m365.graph import CalendarMeeting
from teams_assistant.models import SessionStatus
from teams_assistant.services.m365_service import participants_from_meeting
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.pages.home import local_time
from teams_assistant.ui.widgets import button, card, error_box, muted, title

PRIVACY_TEXT = (
    "<b>Avant d'enregistrer :</b><ul>"
    "<li>Vérifiez que vous avez le droit d'enregistrer cette réunion (règles de l'organisateur, de votre "
    "entreprise et de celle des participants, RGPD).</li>"
    "<li>Informez les participants que vous enregistrez l'audio pour produire une transcription.</li>"
    "<li>L'audio et la transcription restent sur ce PC ; rien n'est envoyé à un service cloud sans "
    "action explicite de votre part.</li>"
    "<li>Le micro n'est enregistré que si vous cochez l'option ci-dessus.</li></ul>")


class NewSessionPage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.title_edit = QLineEdit()
        self.meeting_combo = QComboBox()
        self.loopback_combo = QComboBox()
        self.mic_check = QCheckBox("Enregistrer aussi mon microphone (fichier séparé)")
        self.mic_combo = QComboBox()
        self.consent = QCheckBox("J'ai vérifié les autorisations et informé les participants")
        self.start_btn = button("Démarrer la capture", "primary")
        self.devices: list[AudioDevice] = []
        self._build()

    def _build(self) -> None:
        self.title_edit.setPlaceholderText("Titre de la réunion")
        self.meeting_combo.currentIndexChanged.connect(self._meeting_selected)
        self.mic_check.toggled.connect(self.mic_combo.setEnabled)
        self.consent.toggled.connect(self.start_btn.setEnabled)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_capture)
        refresh = button("Actualiser les périphériques")
        refresh.clicked.connect(self.load_devices)
        import_btn = button("Importer un fichier audio existant…")
        import_btn.clicked.connect(self.import_file)
        form = QFormLayout()
        form.addRow("Titre", self.title_edit)
        form.addRow("Réunion Outlook", self.meeting_combo)
        form.addRow("Son de la réunion", self.loopback_combo)
        form.addRow("", muted("Choisissez la sortie utilisée par Teams (casque ou haut-parleurs)."))
        form.addRow("", self.mic_check)
        form.addRow("Microphone", self.mic_combo)
        actions = QHBoxLayout()
        actions.addWidget(refresh)
        actions.addWidget(import_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(title("Nouvelle session"))
        layout.addLayout(form)
        layout.addLayout(actions)
        self.privacy = QLabel(PRIVACY_TEXT)
        self.privacy.setWordWrap(True)
        layout.addWidget(card(self.privacy, self.consent))
        layout.addWidget(self.start_btn)
        layout.addStretch()

    def refresh(self) -> None:
        settings = self.controller.ctx.settings.load()
        self.mic_check.setChecked(settings.record_microphone)
        self.mic_combo.setEnabled(settings.record_microphone)
        self.consent.setChecked(False)  # confirmation exigée à chaque session, quel que soit le réglage
        self.privacy.setVisible(settings.show_consent_reminder)
        self._fill_meetings()
        self.load_devices()

    def _fill_meetings(self) -> None:
        self.meeting_combo.blockSignals(True)
        self.meeting_combo.clear()
        self.meeting_combo.addItem("— Aucune —", None)
        for meeting in self.controller.meetings:
            self.meeting_combo.addItem(f"{local_time(meeting.start)} {meeting.subject}", meeting)
        self.meeting_combo.blockSignals(False)

    def _meeting_selected(self) -> None:
        meeting = self.meeting_combo.currentData()
        if isinstance(meeting, CalendarMeeting) and not self.title_edit.text().strip():
            self.title_edit.setText(meeting.subject)

    def load_devices(self) -> None:
        try:
            self.devices = self.controller.backend().list_devices()
        except CaptureError as exc:
            error_box(self, str(exc), exc.hint)
            self.devices = []
        settings = self.controller.ctx.settings.load()
        self._fill(self.loopback_combo, DeviceKind.LOOPBACK, settings.loopback_device)
        self._fill(self.mic_combo, DeviceKind.INPUT, settings.microphone_device)

    def _fill(self, combo: QComboBox, kind: DeviceKind, preferred: str) -> None:
        combo.clear()
        matching = [d for d in self.devices if d.kind is kind]
        for device in matching:
            combo.addItem(device.label, device)
        names = [d.name for d in matching]
        default = names.index(preferred) if preferred in names else \
            next((i for i, d in enumerate(matching) if d.is_default), 0)
        if matching:
            combo.setCurrentIndex(default)

    def _create_session(self) -> str:
        meeting = self.meeting_combo.currentData()
        sessions = self.controller.ctx.sessions
        if isinstance(meeting, CalendarMeeting):
            session = sessions.create(self.title_edit.text() or meeting.subject, meeting.event_id,
                                      meeting.start, meeting.end, meeting.join_url)
            sessions.set_participants(session.id, participants_from_meeting(session.id, meeting))
        else:
            session = sessions.create(self.title_edit.text())
        return session.id

    def start_capture(self) -> None:
        loopback = self.loopback_combo.currentData()
        mic = self.mic_combo.currentData() if self.mic_check.isChecked() else None
        if not isinstance(loopback, AudioDevice):
            error_box(self, "Aucune sortie audio sélectionnée.", "Actualisez la liste des périphériques.")
            return
        session_id = self._create_session()
        sessions = self.controller.ctx.sessions
        sessions.confirm_consent(session_id)
        capture = CaptureSession(self.controller.backend(), sessions.recording_dir(session_id))
        try:
            capture.start(loopback, mic)
        except CaptureError as exc:
            sessions.set_status(session_id, SessionStatus.ERROR)
            error_box(self, f"La capture n'a pas démarré : {exc}", exc.hint)
            return
        sessions.mark_capture_started(session_id)
        self.controller.capture = capture
        self.controller.open_session(session_id)
        self.navigate("live")

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un enregistrement", "",
                                              "Audio/vidéo (*.wav *.mp3 *.m4a *.mp4 *.ogg *.flac *.webm *.aac *.wma)")
        if not path:
            return
        session_id = self._create_session()
        try:
            self.controller.ctx.sessions.import_audio(session_id, Path(path))
        except Exception as exc:
            error_box(self, f"Import impossible : {exc}")
            return
        self.controller.open_session(session_id)
        self.navigate("transcript")
