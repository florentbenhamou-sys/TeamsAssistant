"""Écran C — Session en cours : état réel de la capture, durée, niveaux, alertes, commandes."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from teams_assistant.audio.capture_session import CaptureResult
from teams_assistant.audio.recorder import CaptureState
from teams_assistant.audio.types import CaptureError, DeviceKind
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.widgets import LevelMeter, button, card, error_box, format_hms, muted, title

STATE_LABELS = {
    CaptureState.IDLE: "Aucune capture",
    CaptureState.RECORDING: "● Enregistrement en cours",
    CaptureState.PAUSED: "❚❚ Capture suspendue (rien n'est enregistré)",
    CaptureState.STOPPED: "Capture terminée",
    CaptureState.ERROR: "Capture en erreur",
}


class LiveSessionPage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.session_title = title("Session en cours")
        self.elapsed = QLabel("00:00:00")
        self.state = QLabel()
        self.system_level = LevelMeter()
        self.mic_level = LevelMeter()
        self.alerts = QListWidget()
        self.result = QLabel()
        self.pause_btn = button("Suspendre")
        self.resume_btn = button("Reprendre")
        self.stop_btn = button("Arrêter", "danger")
        self.next_btn = button("Passer à la transcription", "primary")
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self._build()

    def _build(self) -> None:
        self.elapsed.setStyleSheet("font-size: 28pt; font-weight: 600;")
        self.pause_btn.clicked.connect(self.pause)
        self.resume_btn.clicked.connect(self.resume)
        self.stop_btn.clicked.connect(self.stop)
        self.next_btn.clicked.connect(lambda: self.navigate("transcript"))
        self.result.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Son du PC", self.system_level)
        form.addRow("Microphone", self.mic_level)
        buttons = QHBoxLayout()
        for widget in (self.pause_btn, self.resume_btn, self.stop_btn):
            buttons.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.addWidget(self.session_title)
        layout.addWidget(card(self.state, self.elapsed))
        layout.addLayout(form)
        layout.addWidget(muted("Le niveau du son du PC reste à zéro pendant les silences : Windows ne "
                               "transmet alors aucune donnée, l'application comble par du silence."))
        layout.addWidget(QLabel("<b>Alertes</b>"))
        layout.addWidget(self.alerts)
        layout.addLayout(buttons)
        layout.addWidget(self.result)
        layout.addWidget(self.next_btn)

    def refresh(self) -> None:
        session_id = self.controller.current_session_id
        if session_id:
            self.session_title.setText(self.controller.ctx.sessions.get(session_id).title)
        self.result.clear()
        self.next_btn.setVisible(False)
        self.timer.start()
        self.tick()

    def tick(self) -> None:
        capture = self.controller.capture
        state = capture.state if capture else CaptureState.IDLE
        self.state.setText(STATE_LABELS[state])
        self.pause_btn.setEnabled(state is CaptureState.RECORDING)
        self.resume_btn.setEnabled(state is CaptureState.PAUSED)
        self.stop_btn.setEnabled(state in (CaptureState.RECORDING, CaptureState.PAUSED))
        if capture is None:
            return
        self.elapsed.setText(format_hms(capture.elapsed()))
        levels = capture.levels()
        self.system_level.set_level(levels.get(DeviceKind.LOOPBACK, float("-inf")))
        self.mic_level.setEnabled(DeviceKind.INPUT in levels)
        self.mic_level.set_level(levels.get(DeviceKind.INPUT, float("-inf")))
        self._show_alerts(capture.alerts())

    def _show_alerts(self, alerts: list[str]) -> None:
        current = [self.alerts.item(i).text() for i in range(self.alerts.count())]
        if current != alerts:
            self.alerts.clear()
            self.alerts.addItems(alerts or ["Aucune alerte"])

    def pause(self) -> None:
        if self.controller.capture:
            self.controller.capture.pause()
        self.controller.notify()

    def resume(self) -> None:
        if self.controller.capture:
            self.controller.capture.resume()
        self.controller.notify()

    def stop(self) -> None:
        capture, session_id = self.controller.capture, self.controller.current_session_id
        if capture is None or session_id is None:
            return
        try:
            result = capture.stop()
        except CaptureError as exc:
            error_box(self, str(exc))
            return
        self.controller.ctx.sessions.attach_capture(session_id, result)
        self.timer.stop()
        self.tick()
        self._show_result(result)
        self.controller.notify()

    def _show_result(self, result: CaptureResult) -> None:
        lines = [f"Durée enregistrée : {format_hms(result.duration_s)}"]
        for source in result.sources:
            lines.append(f"• {source.device.label} : {source.report.summary()}")
        lines.extend(f"⚠ {error}" for error in result.errors)
        if result.succeeded:
            lines.append("<b>Audio exploitable enregistré.</b>")
        else:
            lines.append("<b style='color:#dc2626'>Aucun signal audio exploitable n'a été capturé.</b> "
                         "Vérifiez la sortie audio de Teams (voir docs/audio-diagnostic.md).")
        self.result.setText("<br>".join(lines))
        self.next_btn.setVisible(result.succeeded)
