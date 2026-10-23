"""Génération des comptes rendus (local par défaut, cloud optionnel)."""

from __future__ import annotations

from typing import Protocol

from teams_assistant.summary.schema import SummaryContent, SummaryInput


class SummaryGenerator(Protocol):
    name: str

    def generate(self, data: SummaryInput) -> SummaryContent: ...
