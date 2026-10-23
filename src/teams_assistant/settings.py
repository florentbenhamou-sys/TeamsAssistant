"""Paramètres applicatifs (table ApplicationSettings). Aucun secret n'est stocké ici :
les clés API et jetons vont dans le Gestionnaire d'identification Windows (voir secrets.py)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

from teams_assistant.storage.repositories import SettingsRepository


@dataclass
class AppSettings:
    # Audio
    capture_backend: str = ""  # vide = automatique (PyAudioWPatch puis soundcard)
    loopback_device: str = ""  # nom du périphérique ; vide = sortie par défaut
    microphone_device: str = ""
    record_microphone: bool = False  # désactivé par défaut (minimisation des données)
    # Transcription
    transcription_profile: str = "rapide"
    language: str = "fr"  # "auto" = détection
    separate_sources: bool = True
    compute_device: str = "cpu"
    diarize_speakers: bool = True  # distinguer les voix (aucune empreinte vocale conservée)
    speakers_main: int = 0  # voix sur le son du PC / fichier importé, 0 = estimation automatique
    speakers_mic: int = 1  # voix au micro, 1 = vous seul (casque)
    # Compte rendu
    summary_generator: str = "local"  # local | claude
    cloud_ai_enabled: bool = False  # aucun envoi cloud tant que non activé explicitement
    cloud_model: str = "claude-opus-5-5"
    # Microsoft 365
    graph_client_id: str = ""
    graph_tenant: str = "organizations"
    # Conservation
    delete_audio_after_transcription: bool = True
    audio_retention_days: int = 7
    # Confidentialité
    show_consent_reminder: bool = True


class SettingsService:
    def __init__(self, repo: SettingsRepository) -> None:
        self.repo = repo

    def load(self) -> AppSettings:
        stored = self.repo.get_all()
        known = {f.name for f in fields(AppSettings)}
        return AppSettings(**{k: v for k, v in stored.items() if k in known})

    def save(self, settings: AppSettings) -> None:
        for key, value in asdict(settings).items():
            self.repo.set(key, value)

    def update(self, **changes: Any) -> AppSettings:
        settings = self.load()
        for key, value in changes.items():
            if not hasattr(settings, key):
                raise KeyError(f"Paramètre inconnu : {key}")
            setattr(settings, key, value)
        self.save(settings)
        return settings
