"""Chemins de stockage et configuration de base de l'application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "TeamsAssistant"
DATA_DIR_ENV = "TEAMS_ASSISTANT_DATA_DIR"


def default_base_dir() -> Path:
    """Dossier de données par défaut, volontairement hors OneDrive (données confidentielles)."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / APP_NAME / "data"


@dataclass(frozen=True)
class AppPaths:
    """Arborescence des fichiers locaux de l'application."""

    base: Path

    @property
    def db_file(self) -> Path:
        return self.base / "teams_assistant.db"

    @property
    def recordings(self) -> Path:
        return self.base / "recordings"

    @property
    def exports(self) -> Path:
        return self.base / "exports"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def models(self) -> Path:
        return self.base / "models"

    def ensure(self) -> AppPaths:
        # Crée les dossiers manquants et renvoie l'instance pour chaînage
        for folder in (self.base, self.recordings, self.exports, self.logs, self.models):
            folder.mkdir(parents=True, exist_ok=True)
        return self

    @classmethod
    def default(cls) -> AppPaths:
        return cls(default_base_dir())
