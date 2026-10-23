"""Microsoft Graph sans réseau : réponses simulées. Aucun test réel n'est réalisé ici."""

from __future__ import annotations

from typing import Any

import pytest

from teams_assistant.m365.graph import GraphClient, GraphError, TranscriptAvailability, to_meeting
from teams_assistant.m365.vtt import parse_vtt
from teams_assistant.services.m365_service import participants_from_meeting


class FakeResponse:
    def __init__(self, status: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("pas de JSON")
        return self._payload


class FakeHttp:
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str] | None, dict[str, str]]] = []

    def get(self, url: str, headers: dict[str, str], params: dict[str, str] | None = None,
            timeout: float = 30) -> FakeResponse:
        self.calls.append((url, params, headers))
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response
        return FakeResponse(404, {"error": {"code": "NotFound"}})


JOIN = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0"


def _client(routes: dict[str, FakeResponse]) -> tuple[GraphClient, FakeHttp]:
    http = FakeHttp(routes)
    return GraphClient(http, lambda: "jeton-factice"), http


def test_transcript_available() -> None:
    client, http = _client({"/me/onlineMeetings": FakeResponse(200, {"value": [{"id": "M1"}]}),
                            "/me/onlineMeetings/M1/transcripts": FakeResponse(200, {"value": [{"id": "T1"}]})})
    check = client.check_transcripts(JOIN)
    assert check.availability is TranscriptAvailability.AVAILABLE and check.transcript_ids == ["T1"]
    assert http.calls[0][1] == {"$filter": f"JoinWebUrl eq '{JOIN}'"}
    assert http.calls[0][2]["Authorization"] == "Bearer jeton-factice"


def test_external_meeting_is_reported_as_not_accessible() -> None:
    client, _ = _client({"/me/onlineMeetings": FakeResponse(200, {"value": []})})
    assert client.check_transcripts(JOIN).availability is TranscriptAvailability.MEETING_NOT_ACCESSIBLE


def test_admin_disabled_access_is_forbidden_not_bypassed() -> None:
    body = {"error": {"code": "Forbidden", "innerError": {"code": "GraphAccessToTranscriptsDisabled"}}}
    client, http = _client({"/me/onlineMeetings": FakeResponse(200, {"value": [{"id": "M1"}]}),
                            "/transcripts": FakeResponse(403, body)})
    check = client.check_transcripts(JOIN)
    assert check.availability is TranscriptAvailability.FORBIDDEN
    assert check.detail == "GraphAccessToTranscriptsDisabled"
    assert len(http.calls) == 2  # aucune tentative alternative


def test_meeting_without_transcript_and_non_teams_event() -> None:
    client, _ = _client({"/me/onlineMeetings": FakeResponse(200, {"value": [{"id": "M1"}]}),
                         "/transcripts": FakeResponse(200, {"value": []})})
    assert client.check_transcripts(JOIN).availability is TranscriptAvailability.NO_TRANSCRIPT
    assert client.check_transcripts("").availability is TranscriptAvailability.NOT_A_TEAMS_MEETING


def test_server_errors_are_raised() -> None:
    client, _ = _client({"/me/onlineMeetings": FakeResponse(503, {"error": {"code": "ServiceUnavailable"}})})
    with pytest.raises(GraphError):
        client.check_transcripts(JOIN)


def test_quote_in_join_url_is_escaped() -> None:
    client, http = _client({"/me/onlineMeetings": FakeResponse(200, {"value": []})})
    client.check_transcripts("https://teams.microsoft.com/x'y")
    assert http.calls[0][1] == {"$filter": "JoinWebUrl eq 'https://teams.microsoft.com/x''y'"}


def test_calendar_event_mapping_and_participants() -> None:
    event = {"id": "E1", "subject": "Démo", "start": {"dateTime": "2026-10-24T08:00:00.0000000"},
             "end": {"dateTime": "2026-10-24T09:00:00.0000000"},
             "organizer": {"emailAddress": {"name": "Organisateur Externe"}},
             "attendees": [{"emailAddress": {"name": "Personne A"}}, {"emailAddress": {"address": "b@ex.test"}}],
             "onlineMeeting": {"joinUrl": JOIN}}
    meeting = to_meeting(event)
    assert meeting.is_teams and meeting.start == "2026-10-24T08:00:00+00:00"
    names = [p.display_name for p in participants_from_meeting("s", meeting)]
    assert names == ["Organisateur Externe", "Personne A", "b@ex.test"]


def test_parse_vtt_with_speakers() -> None:
    content = ("WEBVTT\n\n0f1c/12-0\n00:00:01.500 --> 00:00:04.000\n<v Alice Martin>Bonjour à tous.</v>\n\n"
               "00:00:05.000 --> 00:00:07.250\n<v Bob>On valide le pilote.</v>\n")
    cues = parse_vtt(content)
    assert [(c.speaker, c.start_s, c.text) for c in cues] == [("Alice Martin", 1.5, "Bonjour à tous."),
                                                              ("Bob", 5.0, "On valide le pilote.")]
