"""Stockage des secrets dans le Gestionnaire d'identification Windows (keyring / DPAPI).

Jamais dans un fichier de configuration, la base SQLite ou les journaux.
"""

from __future__ import annotations

from teams_assistant.logging_setup import get_logger

log = get_logger("secrets")
SERVICE = "TeamsAssistant"


def _keyring() -> object | None:
    try:
        import keyring
    except ImportError:
        log.warning("Module keyring indisponible : les secrets ne peuvent pas être stockés.")
        return None
    return keyring


def get_secret(name: str) -> str | None:
    module = _keyring()
    if module is None:
        return None
    value = module.get_password(SERVICE, name)  # type: ignore[attr-defined]
    return str(value) if value else None


def set_secret(name: str, value: str) -> None:
    module = _keyring()
    if module is None:
        raise RuntimeError("Gestionnaire d'identification indisponible.")
    module.set_password(SERVICE, name, value)  # type: ignore[attr-defined]
    log.info("Secret « %s » enregistré dans le Gestionnaire d'identification Windows.", name)


def delete_secret(name: str) -> None:
    module = _keyring()
    if module is None:
        return
    try:
        module.delete_password(SERVICE, name)  # type: ignore[attr-defined]
    except Exception:  # secret absent : rien à faire
        pass
