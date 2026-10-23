"""Point d'entrée : python -m teams_assistant"""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from PySide6.QtWidgets import QApplication

    from teams_assistant.app_context import build_context
    from teams_assistant.config import AppPaths
    from teams_assistant.logging_setup import setup_logging
    from teams_assistant.ui.controller import Controller
    from teams_assistant.ui.main_window import MainWindow

    paths = AppPaths.default().ensure()
    log = setup_logging(paths.logs)
    ctx = build_context(paths)
    purged = ctx.sessions.purge_expired_audio(ctx.settings.load().audio_retention_days)
    if purged:
        log.info("Politique de conservation : %d fichier(s) audio expiré(s) supprimé(s)", purged)
    app = QApplication(sys.argv)
    app.setApplicationName("TeamsAssistant")
    window = MainWindow(Controller(ctx))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
