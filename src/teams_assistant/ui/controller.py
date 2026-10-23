"""État partagé de l'interface : contexte applicatif, session courante, capture active."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from teams_assistant.app_context import AppContext
from teams_assistant.audio.backends import get_backend
from teams_assistant.audio.capture_session import CaptureSession
from teams_assistant.audio.recorder import CaptureState
from teams_assistant.audio.types import CaptureBackend
from teams_assistant.m365.graph import CalendarMeeting
from teams_assistant.services.m365_service import M365Service

BackendFactory = Callable[[str], CaptureBackend]


def default_backend_factory(name: str) -> CaptureBackend:
    return get_backend(name or None)


@dataclass
class Controller:
    ctx: AppContext
    backend_factory: BackendFactory = default_backend_factory
    current_session_id: str | None = None
    capture: CaptureSession | None = None
    meetings: list[CalendarMeeting] = field(default_factory=list)
    _m365: M365Service | None = None
    listeners: list[Callable[[], None]] = field(default_factory=list)

    def backend(self) -> CaptureBackend:
        return self.backend_factory(self.ctx.settings.load().capture_backend)

    @property
    def capture_active(self) -> bool:
        return self.capture is not None and self.capture.state in (CaptureState.RECORDING, CaptureState.PAUSED)

    def m365(self) -> M365Service:
        if self._m365 is None:
            self._m365 = M365Service(self.ctx.settings.load(), self.ctx.paths)
        return self._m365

    def reset_m365(self) -> None:
        self._m365 = None  # après modification des paramètres Graph

    def m365_configured(self) -> bool:
        return bool(self.ctx.settings.load().graph_client_id)

    def open_session(self, session_id: str) -> None:
        self.current_session_id = session_id
        self.notify()

    def notify(self) -> None:
        for listener in list(self.listeners):
            listener()
