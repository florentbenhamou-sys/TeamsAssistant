"""Écran G — Paramètres."""

from __future__ import annotations

import os
from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from teams_assistant.audio.backends import BACKENDS
from teams_assistant.audio.types import CaptureError, DeviceKind
from teams_assistant.secret_store import delete_secret, get_secret, set_secret
from teams_assistant.settings import AppSettings
from teams_assistant.summary.claude_generator import API_KEY_SECRET
from teams_assistant.transcription.whisper_engine import PROFILES
from teams_assistant.ui.controller import Controller
from teams_assistant.ui.pages.transcript import count_spin
from teams_assistant.ui.widgets import button, confirm, error_box, info_box, muted, title
from teams_assistant.ui.workers import run_async


class SettingsPage(QWidget):
    def __init__(self, controller: Controller, navigate: Callable[[str], None]) -> None:
        super().__init__()
        self.controller = controller
        self.navigate = navigate
        self.backend = QComboBox()
        self.loopback = QComboBox()
        self.microphone = QComboBox()
        self.record_mic = QCheckBox("Activer le micro par défaut (déconseillé si inutile)")
        self.profile = QComboBox()
        self.language = QComboBox()
        self.separate = QCheckBox("Transcrire micro et son du PC séparément (recommandé avec un casque)")
        self.device = QComboBox()
        self.diarize = QCheckBox("Distinguer les voix (Intervenant 1, 2…) — aucune empreinte vocale conservée")
        self.speakers_main = count_spin(0)
        self.speakers_mic = count_spin(1)
        self.cloud_enabled = QCheckBox("Autoriser l'IA cloud (Claude) — désactivé par défaut")
        self.cloud_model = QLineEdit()
        self.api_key = QLineEdit()
        self.key_state = muted("")
        self.client_id = QLineEdit()
        self.tenant = QLineEdit()
        self.m365_state = muted("")
        self.delete_after = QCheckBox("Supprimer l'audio temporaire après une transcription réussie")
        self.retention = QSpinBox()
        self.reminder = QCheckBox("Afficher le rappel d'autorisation avant chaque capture")
        self._build()

    def _build(self) -> None:
        self.backend.addItem("Automatique", "")
        for name in BACKENDS:
            self.backend.addItem(name, name)
        for key, profile in PROFILES.items():
            self.profile.addItem(f"{profile.label} — ~{profile.approx_download_mb} Mo", key)
        for code, label in (("fr", "Français"), ("auto", "Détection automatique"), ("en", "Anglais")):
            self.language.addItem(label, code)
        self.device.addItem("Processeur (CPU)", "cpu")
        self.device.addItem("GPU NVIDIA (CUDA, nécessite cuBLAS/cuDNN)", "cuda")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Saisir pour enregistrer une nouvelle clé (jamais réaffichée)")
        self.retention.setRange(0, 365)
        self.retention.setSuffix(" jours")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(title("Paramètres"))
        for group in (self._audio(), self._transcription(), self._ai(), self._m365(), self._storage()):
            layout.addWidget(group)
        save = button("Enregistrer les paramètres", "primary")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        QVBoxLayout(self).addWidget(scroll)

    def _group(self, name: str, rows: list[tuple[str, QWidget]]) -> QGroupBox:
        box = QGroupBox(name)
        form = QFormLayout(box)
        for label, widget in rows:
            form.addRow(label, widget)
        return box

    def _audio(self) -> QGroupBox:
        refresh = button("Actualiser les périphériques")
        refresh.clicked.connect(self.load_devices)
        return self._group("Périphériques audio", [("Bibliothèque de capture", self.backend),
                                                   ("Son de la réunion", self.loopback),
                                                   ("Microphone", self.microphone), ("", self.record_mic),
                                                   ("", refresh)])

    def _transcription(self) -> QGroupBox:
        return self._group("Moteur de transcription (faster-whisper, local)", [
            ("Modèle / profil", self.profile), ("Langue", self.language), ("", self.separate),
            ("Calcul", self.device), ("", self.diarize),
            ("Voix sur le son du PC / fichier", self.speakers_main), ("Voix au micro", self.speakers_mic),
            ("", muted("Indiquer le nombre de personnes améliore nettement la séparation des voix ; « auto » "
                       "a tendance à en compter trop (renommez deux libellés à l'identique pour les fusionner).")),
            ("", muted("Les modèles sont téléchargés une fois (Hugging Face et GitHub sherpa-onnx, gratuits), "
                       "puis utilisés hors connexion."))])

    def _ai(self) -> QGroupBox:
        save_key, forget_key = button("Enregistrer la clé"), button("Oublier la clé")
        save_key.clicked.connect(self.save_key)
        forget_key.clicked.connect(self.forget_key)
        keys = QWidget()
        row = QHBoxLayout(keys)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (self.api_key, save_key, forget_key):
            row.addWidget(widget)
        return self._group("Génération des comptes rendus", [
            ("", muted("Par défaut, le compte rendu est produit localement sans IA. L'IA cloud envoie le TEXTE "
                       "de la transcription à Anthropic (payant à l'usage) et demande une confirmation à chaque "
                       "génération.")),
            ("", self.cloud_enabled), ("Modèle", self.cloud_model), ("Clé API Anthropic", keys), ("", self.key_state)])

    def _m365(self) -> QGroupBox:
        connect, disconnect = button("Se connecter"), button("Se déconnecter")
        connect.clicked.connect(self.sign_in)
        disconnect.clicked.connect(self.sign_out)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(connect)
        row.addWidget(disconnect)
        return self._group("Microsoft 365 (facultatif)", [
            ("ID d'application (client)", self.client_id), ("Tenant", self.tenant), ("", buttons),
            ("", self.m365_state),
            ("", muted("La connexion s'ouvre dans le navigateur Microsoft ; aucun mot de passe n'est saisi ici. "
                       "Voir docs/microsoft-graph.md."))])

    def _storage(self) -> QGroupBox:
        paths = self.controller.ctx.paths
        purge, open_btn = button("Supprimer maintenant l'audio expiré"), button("Ouvrir le dossier de données")
        purge.clicked.connect(self.purge)
        open_btn.clicked.connect(lambda: os.startfile(paths.base))
        return self._group("Stockage, conservation et confidentialité", [
            ("Données", QLabel(str(paths.base))), ("Exports", QLabel(str(paths.exports))),
            ("", self.delete_after), ("Conserver l'audio temporaire", self.retention), ("", purge),
            ("", self.reminder), ("", open_btn),
            ("", muted("Les journaux ne contiennent ni transcription ni secret. Les clés et jetons sont stockés "
                       "dans le Gestionnaire d'identification Windows / chiffrés par DPAPI."))])

    # --- chargement / enregistrement --------------------------------------------------------
    def refresh(self) -> None:
        s = self.controller.ctx.settings.load()
        self.backend.setCurrentIndex(max(0, self.backend.findData(s.capture_backend)))
        self.record_mic.setChecked(s.record_microphone)
        self.profile.setCurrentIndex(max(0, self.profile.findData(s.transcription_profile)))
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        self.separate.setChecked(s.separate_sources)
        self.device.setCurrentIndex(max(0, self.device.findData(s.compute_device)))
        self.diarize.setChecked(s.diarize_speakers)
        self.speakers_main.setValue(s.speakers_main)
        self.speakers_mic.setValue(s.speakers_mic)
        self.cloud_enabled.setChecked(s.cloud_ai_enabled)
        self.cloud_model.setText(s.cloud_model)
        self.client_id.setText(s.graph_client_id)
        self.tenant.setText(s.graph_tenant)
        self.delete_after.setChecked(s.delete_audio_after_transcription)
        self.retention.setValue(s.audio_retention_days)
        self.reminder.setChecked(s.show_consent_reminder)
        self.key_state.setText("Clé enregistrée." if self._has_key() else "Aucune clé enregistrée.")
        self.load_devices()

    @staticmethod
    def _has_key() -> bool:
        try:
            return bool(get_secret(API_KEY_SECRET))
        except Exception:
            return False

    def load_devices(self) -> None:
        settings = self.controller.ctx.settings.load()
        try:
            devices = self.controller.backend().list_devices()
        except CaptureError as exc:
            error_box(self, str(exc), exc.hint)
            devices = []
        for combo, kind, current in ((self.loopback, DeviceKind.LOOPBACK, settings.loopback_device),
                                     (self.microphone, DeviceKind.INPUT, settings.microphone_device)):
            combo.clear()
            combo.addItem("Périphérique par défaut de Windows", "")
            for device in (d for d in devices if d.kind is kind):
                combo.addItem(device.name, device.name)
            combo.setCurrentIndex(max(0, combo.findData(current)))

    def collect(self) -> AppSettings:
        s = self.controller.ctx.settings.load()
        s.capture_backend = self.backend.currentData()
        s.loopback_device, s.microphone_device = self.loopback.currentData() or "", self.microphone.currentData() or ""
        s.record_microphone = self.record_mic.isChecked()
        s.transcription_profile, s.language = self.profile.currentData(), self.language.currentData()
        s.separate_sources, s.compute_device = self.separate.isChecked(), self.device.currentData()
        s.diarize_speakers = self.diarize.isChecked()
        s.speakers_main, s.speakers_mic = self.speakers_main.value(), self.speakers_mic.value()
        s.cloud_ai_enabled, s.cloud_model = self.cloud_enabled.isChecked(), self.cloud_model.text().strip()
        s.summary_generator = "claude" if s.cloud_ai_enabled else "local"
        s.graph_client_id, s.graph_tenant = self.client_id.text().strip(), self.tenant.text().strip() or "organizations"
        s.delete_audio_after_transcription = self.delete_after.isChecked()
        s.audio_retention_days, s.show_consent_reminder = self.retention.value(), self.reminder.isChecked()
        return s

    def save(self) -> None:
        self.controller.ctx.settings.save(self.collect())
        self.controller.reset_m365()
        self.controller.notify()
        info_box(self, "Paramètres enregistrés.")

    def save_key(self) -> None:
        key = self.api_key.text().strip()
        self.api_key.clear()
        if key:
            set_secret(API_KEY_SECRET, key)
        self.key_state.setText("Clé enregistrée." if self._has_key() else "Aucune clé enregistrée.")

    def forget_key(self) -> None:
        delete_secret(API_KEY_SECRET)
        self.key_state.setText("Aucune clé enregistrée.")

    def sign_in(self) -> None:
        self.save()
        self.m365_state.setText("Connexion en cours dans le navigateur…")
        run_async(lambda _e: self.controller.m365().sign_in(),
                  lambda acc: self.m365_state.setText(f"Connecté : {acc.username}" if acc else "Non connecté"),
                  lambda err: self.m365_state.setText(f"Échec : {err}"))

    def sign_out(self) -> None:
        try:
            self.controller.m365().sign_out()
            self.m365_state.setText("Déconnecté.")
        except Exception as exc:
            self.m365_state.setText(str(exc))

    def purge(self) -> None:
        days = self.retention.value()
        if confirm(self, f"Supprimer les fichiers audio temporaires de plus de {days} jours ?"):
            count = self.controller.ctx.sessions.purge_expired_audio(days)
            info_box(self, f"{count} fichier(s) supprimé(s).")
