"""Comptes rendus à partir de la transcription synthétique (samples/meeting_demo/timeline.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teams_assistant.models import IdentityStatus, Participant, TranscriptSegment
from teams_assistant.services.summary_service import SummaryError, generator_for
from teams_assistant.settings import AppSettings
from teams_assistant.summary.claude_generator import ClaudeSummaryGenerator, build_prompt, parse_sections
from teams_assistant.summary.local_generator import LocalSummaryGenerator, utterances
from teams_assistant.summary.schema import INTERPRETATION, SECTION_KEYS, SummaryContent, SummaryInput
from teams_assistant.transcription.types import SOURCE_LABELS, SourceKind

TIMELINE = Path(__file__).resolve().parent.parent / "samples" / "meeting_demo" / "timeline.json"


def demo_input() -> SummaryInput:
    lines = json.loads(TIMELINE.read_text(encoding="utf-8"))
    segments = [TranscriptSegment(transcript_id="t", seq=i + 1, start_s=line["start_s"], end_s=line["end_s"],
                                  text=line["text"], source=line["source"],
                                  speaker=SOURCE_LABELS[SourceKind(line["source"])])
                for i, line in enumerate(lines)]
    participants = [Participant(session_id="s", display_name="Organisateur (invitation)",
                                identity=IdentityStatus.CONFIRMED, origin="outlook")]
    return SummaryInput("Cadrage Atlas", "2026-10-23 10:00", 82.5, participants, segments)


def _texts(content: SummaryContent, key: str) -> str:
    return " | ".join(i.text for i in content.sections[key])


def test_local_summary_extracts_decisions_actions_risks() -> None:
    content = LocalSummaryGenerator().generate(demo_input())
    assert "pilote sur le site de Lyon" in _texts(content, "decisions")
    assert "proposition commerciale" in _texts(content, "commitments")
    assert "inquiétude" in _texts(content, "risks") and "risque" in _texts(content, "risks")
    assert "hébergement" in _texts(content, "open_questions")
    assert "objectif" in _texts(content, "context")
    dues = {i.due for i in content.sections["next_actions"]}
    assert "d'ici vendredi prochain" in dues and "avant le quinze novembre" in dues


def test_local_summary_never_invents_owners_and_keeps_refs() -> None:
    data = demo_input()
    content = LocalSummaryGenerator().generate(data)
    valid = {s.seq for s in data.segments}
    for key in SECTION_KEYS:
        for item in content.sections[key]:
            assert item.owner == ""  # aucun responsable attribué automatiquement
            assert set(item.refs) <= valid
            if item.kind != INTERPRETATION:
                assert item.refs, item.text  # tout fait est rattaché à la transcription


def test_participants_distinguish_confirmed_and_technical_labels() -> None:
    content = LocalSummaryGenerator().generate(demo_input())
    statuses = {p.name: p.status for p in content.participants}
    assert statuses["Organisateur (invitation)"] == "confirmée"
    assert statuses["Micro local"] == "incertaine"


def test_uncertain_segments_are_flagged_for_validation() -> None:
    data = demo_input()
    data.segments[3].uncertain = True
    content = LocalSummaryGenerator().generate(data)
    assert any(4 in i.refs for i in content.sections["validation_points"])


def test_utterances_merge_split_sentences() -> None:
    segs = [TranscriptSegment("t", 1, 0, 1, "avant le 15", "system", "A"),
            TranscriptSegment("t", 2, 1, 2, "novembre.", "system", "A")]
    merged = utterances(segs)
    assert len(merged) == 1 and merged[0].refs == [1, 2]


def test_summary_roundtrip_dict() -> None:
    content = LocalSummaryGenerator().generate(demo_input())
    assert SummaryContent.from_dict(content.to_dict()) == content


def test_cloud_generator_requires_explicit_activation_and_confirmation() -> None:
    settings = AppSettings(summary_generator="claude")
    with pytest.raises(SummaryError, match="désactivée"):
        generator_for(settings, cloud_confirmed=True)
    settings.cloud_ai_enabled = True
    with pytest.raises(SummaryError, match="confirmé"):
        generator_for(settings, cloud_confirmed=False)
    assert isinstance(generator_for(settings, cloud_confirmed=True), ClaudeSummaryGenerator)
    assert isinstance(generator_for(AppSettings(), cloud_confirmed=True), LocalSummaryGenerator)


def test_cloud_response_with_invented_refs_is_downgraded() -> None:
    raw = {key: [] for key in SECTION_KEYS}
    raw["decisions"] = [{"text": "Pilote à Lyon", "kind": "fait", "refs": [7, 999], "owner": "", "due": ""},
                        {"text": "Budget validé", "kind": "fait", "refs": [999], "owner": "", "due": ""}]
    sections = parse_sections(raw, valid_refs={7})
    assert sections["decisions"][0].refs == [7] and sections["decisions"][0].kind == "fait"
    assert sections["decisions"][1].kind == INTERPRETATION  # sans source réelle : pas un fait


def test_cloud_prompt_contains_numbered_segments_only_text() -> None:
    prompt = build_prompt(demo_input())
    assert "[1] (Micro local) Bonjour à tous" in prompt and "Cadrage Atlas" in prompt
