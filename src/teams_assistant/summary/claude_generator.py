"""Générateur cloud optionnel (API Claude d'Anthropic). DÉSACTIVÉ PAR DÉFAUT.

Conditions d'utilisation, vérifiées par l'appelant (SummaryService) :
1. l'option « IA cloud » est activée dans les Paramètres ;
2. l'utilisateur déclenche explicitement la génération et confirme l'envoi ;
3. une clé API est enregistrée dans le Gestionnaire d'identification Windows.
Seul le texte de la transcription est envoyé (jamais l'audio). Service payant à l'usage :
voir docs/compte-rendu.md pour l'estimation des coûts.
"""

from __future__ import annotations

import json
from typing import Any

from teams_assistant.logging_setup import get_logger
from teams_assistant.secret_store import get_secret
from teams_assistant.summary.schema import (
    FACT,
    INTERPRETATION,
    SECTION_KEYS,
    SECTIONS,
    SummaryContent,
    SummaryInput,
    SummaryItem,
    format_duration,
    participant_entries,
)

log = get_logger("summary.claude")
API_KEY_SECRET = "anthropic_api_key"
DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """Tu rédiges des comptes rendus de réunion professionnels en français à partir d'une \
transcription automatique numérotée. Règles impératives :
- N'invente rien : aucune décision, aucun participant, aucun engagement, aucune date absente du texte.
- Chaque élément cite dans "refs" les numéros de segments qui le justifient.
- "kind" vaut "fait" si l'élément est énoncé explicitement, "interprétation" s'il s'agit d'une déduction.
- "owner" et "due" restent vides sauf mention explicite dans la transcription.
- Les libellés d'intervenants sont des sources audio techniques, pas des personnes : ne les transforme \
jamais en noms.
- Signale dans "validation_points" les passages ambigus, mal transcrits ou contradictoires.
- Une section sans contenu reste une liste vide."""

ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": [FACT, INTERPRETATION]},
        "refs": {"type": "array", "items": {"type": "integer"}},
        "owner": {"type": "string"},
        "due": {"type": "string"},
    },
    "required": ["text", "kind", "refs", "owner", "due"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {key: {"type": "array", "items": ITEM_SCHEMA} for key in SECTION_KEYS},
    "required": SECTION_KEYS,
    "additionalProperties": False,
}


class CloudSummaryError(RuntimeError):
    pass


def build_prompt(data: SummaryInput) -> str:
    lines = [f"[{s.seq}] ({s.speaker or 'inconnu'}) {s.text}" + (" [incertain]" if s.uncertain else "")
             for s in data.segments]
    known = ", ".join(p.display_name for p in data.participants) or "aucun participant confirmé"
    sections = "\n".join(f"- {key} : {label}" for key, label in SECTIONS)
    return (f"Réunion : {data.title}\nDate : {data.date or 'inconnue'}\nParticipants confirmés : {known}\n\n"
            f"Sections attendues :\n{sections}\n\nTranscription :\n" + "\n".join(lines))


def parse_sections(raw: dict[str, Any], valid_refs: set[int]) -> dict[str, list[SummaryItem]]:
    """Convertit la réponse et écarte les références inexistantes (garde-fou anti-invention)."""
    sections: dict[str, list[SummaryItem]] = {}
    for key in SECTION_KEYS:
        items = []
        for entry in raw.get(key, []):
            refs = [r for r in entry.get("refs", []) if r in valid_refs]
            kind = entry.get("kind", INTERPRETATION) if refs else INTERPRETATION
            items.append(SummaryItem(text=str(entry.get("text", "")), kind=kind, refs=refs,
                                     owner=str(entry.get("owner", "")), due=str(entry.get("due", ""))))
        sections[key] = items
    return sections


class ClaudeSummaryGenerator:
    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        self.model = model
        self._api_key = api_key

    def generate(self, data: SummaryInput) -> SummaryContent:
        raw = self._call(build_prompt(data))
        content = SummaryContent(title=data.title, date=data.date, duration=format_duration(data.duration_s),
                                 participants=participant_entries(data),
                                 generator_notice=f"Compte rendu rédigé par IA cloud ({self.model}) : "
                                                  "à relire et valider avant diffusion.")
        content.sections = parse_sections(raw, {s.seq for s in data.segments})
        return content

    def _client(self) -> Any:
        key = self._api_key or get_secret(API_KEY_SECRET)
        if not key:
            raise CloudSummaryError("Aucune clé API Anthropic enregistrée (Paramètres > IA).")
        try:
            import anthropic
        except ImportError as exc:
            raise CloudSummaryError("Le module anthropic n'est pas installé (pip install -e .[cloud]).") from exc
        return anthropic.Anthropic(api_key=key)

    def _call(self, prompt: str) -> dict[str, Any]:
        import anthropic

        client = self._client()
        try:
            response = client.beta.messages.create(
                model=self.model, max_tokens=16000, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "medium",
                               "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except anthropic.AuthenticationError as exc:
            raise CloudSummaryError("Clé API refusée par Anthropic.") from exc
        except anthropic.RateLimitError as exc:
            raise CloudSummaryError("Limite de débit atteinte, réessayez plus tard.") from exc
        except anthropic.APIStatusError as exc:
            raise CloudSummaryError(f"Erreur du service ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise CloudSummaryError("Connexion au service impossible.") from exc
        return self._extract_json(response)

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        if response.stop_reason == "refusal":
            raise CloudSummaryError("Le service a refusé de traiter cette transcription.")
        if response.stop_reason == "max_tokens":
            raise CloudSummaryError("Réponse tronquée (transcription trop longue).")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CloudSummaryError("Réponse illisible du service.") from exc
        log.info("Compte rendu cloud reçu (%d sections)", len(data))
        return data
