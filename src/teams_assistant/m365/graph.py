"""Accès Microsoft Graph : calendrier Outlook et transcripts officiels Teams (lecture seule)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import quote

from teams_assistant.logging_setup import get_logger

log = get_logger("m365.graph")
GRAPH = "https://graph.microsoft.com/v1.0"
TokenProvider = Callable[[], str]


class HttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> Any: ...


class HttpSession(Protocol):
    def get(self, url: str, headers: dict[str, str], params: dict[str, str] | None = None,
            timeout: float = 30) -> HttpResponse: ...


class GraphError(RuntimeError):
    def __init__(self, message: str, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class CalendarMeeting:
    event_id: str
    subject: str
    start: str  # ISO UTC
    end: str
    organizer: str
    attendees: list[str] = field(default_factory=list)
    join_url: str = ""

    @property
    def is_teams(self) -> bool:
        return "teams.microsoft.com" in self.join_url or "teams.live.com" in self.join_url


class TranscriptAvailability(StrEnum):
    AVAILABLE = "available"
    NO_TRANSCRIPT = "no_transcript"  # réunion trouvée, aucun transcript produit
    MEETING_NOT_ACCESSIBLE = "meeting_not_accessible"  # typiquement : réunion d'une autre organisation
    FORBIDDEN = "forbidden"  # consentement manquant ou accès désactivé par l'administrateur
    NOT_A_TEAMS_MEETING = "not_teams"


AVAILABILITY_LABELS = {
    TranscriptAvailability.AVAILABLE: "Transcript officiel accessible",
    TranscriptAvailability.NO_TRANSCRIPT: "Aucun transcript officiel pour cette réunion",
    TranscriptAvailability.MEETING_NOT_ACCESSIBLE:
        "Réunion non accessible via Graph (souvent organisée par une autre entreprise) : "
        "utilisez la transcription locale",
    TranscriptAvailability.FORBIDDEN: "Accès refusé : consentement administrateur requis ou accès "
                                      "aux transcripts désactivé par votre organisation",
    TranscriptAvailability.NOT_A_TEAMS_MEETING: "Pas de lien de réunion Teams",
}


@dataclass(frozen=True)
class TranscriptCheck:
    availability: TranscriptAvailability
    meeting_id: str = ""
    transcript_ids: list[str] = field(default_factory=list)
    detail: str = ""


class GraphClient:
    def __init__(self, session: HttpSession, token: TokenProvider) -> None:
        self.session = session
        self.token = token

    def _get(self, path: str, params: dict[str, str] | None = None, accept: str = "application/json") -> HttpResponse:
        headers = {"Authorization": f"Bearer {self.token()}", "Accept": accept}
        response = self.session.get(f"{GRAPH}{path}", headers=headers, params=params, timeout=30)
        if response.status_code >= 400:
            raise self._error(response)
        return response

    @staticmethod
    def _error(response: HttpResponse) -> GraphError:
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}
        inner = (error.get("innerError") or {}).get("code", "")
        code = inner or error.get("code", "")
        log.warning("Graph a répondu %s (%s)", response.status_code, code)  # jamais le jeton ni le contenu
        return GraphError(str(error.get("message", "Erreur Microsoft Graph")), response.status_code, code)

    # --- calendrier -------------------------------------------------------------------
    def upcoming_meetings(self, days: int = 7, now: datetime | None = None) -> list[CalendarMeeting]:
        start = now or datetime.now(timezone.utc)
        params = {"startDateTime": start.isoformat(), "endDateTime": (start + timedelta(days=days)).isoformat(),
                  "$select": "id,subject,start,end,organizer,attendees,onlineMeeting,isOnlineMeeting",
                  "$orderby": "start/dateTime", "$top": "50"}
        data = self._get("/me/calendarView", params).json()
        return [to_meeting(event) for event in data.get("value", [])]

    # --- transcripts officiels -----------------------------------------------------------
    def check_transcripts(self, join_url: str) -> TranscriptCheck:
        """Vérifie si un transcript officiel est accessible ; n'essaie jamais de contourner un refus."""
        if not join_url:
            return TranscriptCheck(TranscriptAvailability.NOT_A_TEAMS_MEETING)
        try:
            meeting_id = self._meeting_id(join_url)
            if not meeting_id:
                return TranscriptCheck(TranscriptAvailability.MEETING_NOT_ACCESSIBLE)
            data = self._get(f"/me/onlineMeetings/{meeting_id}/transcripts").json()
        except GraphError as exc:
            return classify_error(exc)
        ids = [t["id"] for t in data.get("value", [])]
        status = TranscriptAvailability.AVAILABLE if ids else TranscriptAvailability.NO_TRANSCRIPT
        return TranscriptCheck(status, meeting_id, ids)

    def _meeting_id(self, join_url: str) -> str:
        escaped = join_url.replace("'", "''")  # échappement OData d'une valeur, pas de concaténation libre
        data = self._get("/me/onlineMeetings", {"$filter": f"JoinWebUrl eq '{escaped}'"}).json()
        values = data.get("value", [])
        return str(values[0]["id"]) if values else ""

    def transcript_vtt(self, meeting_id: str, transcript_id: str) -> str:
        path = f"/me/onlineMeetings/{quote(meeting_id)}/transcripts/{quote(transcript_id)}/content"
        return self._get(path, {"$format": "text/vtt"}, accept="text/vtt").text


def classify_error(exc: GraphError) -> TranscriptCheck:
    if exc.status in (401, 403):
        return TranscriptCheck(TranscriptAvailability.FORBIDDEN, detail=exc.code)
    if exc.status == 404:
        return TranscriptCheck(TranscriptAvailability.MEETING_NOT_ACCESSIBLE, detail=exc.code)
    raise exc


def to_meeting(event: dict[str, Any]) -> CalendarMeeting:
    organizer = ((event.get("organizer") or {}).get("emailAddress") or {}).get("name", "")
    attendees = [((a.get("emailAddress") or {}).get("name") or (a.get("emailAddress") or {}).get("address", ""))
                 for a in event.get("attendees", [])]
    join_url = ((event.get("onlineMeeting") or {}).get("joinUrl")) or ""
    return CalendarMeeting(event_id=str(event.get("id", "")), subject=str(event.get("subject") or "(sans objet)"),
                           start=_utc(event.get("start")), end=_utc(event.get("end")), organizer=organizer,
                           attendees=[a for a in attendees if a], join_url=join_url)


def _utc(value: dict[str, str] | None) -> str:
    # Graph renvoie l'heure en UTC par défaut (sans en-tête Prefer), sans suffixe de fuseau
    raw = (value or {}).get("dateTime", "")
    return re.sub(r"\.\d+$", "", raw) + ("+00:00" if raw else "")
