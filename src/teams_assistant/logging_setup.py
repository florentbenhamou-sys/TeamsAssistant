"""Journalisation technique avec masquage des secrets.

Règle : les journaux ne contiennent jamais de transcription, de jeton ou de clé.
Le filtre ci-dessous est un filet de sécurité ; le code ne doit de toute façon pas
journaliser ces données.
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "teams_assistant"

# Motifs de secrets courants : jetons Bearer, JWT, clés API, paramètres sensibles
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    re.compile(r"eyJ[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}\.[a-zA-Z0-9_\-]{8,}"),
    re.compile(r"sk-[a-zA-Z0-9_\-]{16,}"),
    re.compile(r"(?i)(access_token|refresh_token|id_token|client_secret|api[_-]?key|password)"
               r"(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"),
]


def redact(text: str) -> str:
    """Remplace les secrets détectés par un marqueur neutre."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
        else:
            text = pattern.sub("***", text)
    return text


class RedactingFilter(logging.Filter):
    """Filtre appliqué à tous les gestionnaires : masque les secrets dans les messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message)
        record.args = None
        return True


def setup_logging(log_dir: Path | None = None, level: str | None = None) -> logging.Logger:
    """Configure le journal applicatif (console + fichier tournant optionnel)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level or os.environ.get("TEAMS_ASSISTANT_LOG_LEVEL", "INFO"))
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000,
                                            backupCount=3, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
