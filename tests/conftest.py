"""Configuration commune : chaque test travaille dans un dossier de données temporaire."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from teams_assistant.config import DATA_DIR_ENV, AppPaths


@pytest.fixture()
def app_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppPaths]:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "data"))
    yield AppPaths.default().ensure()
