"""Authentification Microsoft 365 : MSAL, client public, connexion interactive dans le navigateur.

- Aucun identifiant n'est saisi dans l'application : la page de connexion Microsoft s'ouvre.
- Pas de secret client (application « client public »).
- Le cache de jetons est chiffré par DPAPI (lié à votre session Windows) via msal-extensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from teams_assistant.logging_setup import get_logger

log = get_logger("m365.auth")

# Permissions déléguées minimales, demandées par fonctionnalité (consentement incrémental)
SCOPES_CALENDAR = ["User.Read", "Calendars.Read"]
SCOPES_TRANSCRIPTS = ["OnlineMeetings.Read", "OnlineMeetingTranscript.Read.All"]


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountInfo:
    username: str
    tenant_id: str


class GraphAuth:
    def __init__(self, client_id: str, tenant: str, cache_file: Path) -> None:
        if not client_id:
            raise AuthError("Identifiant d'application (client ID) non configuré : voir docs/microsoft-graph.md.")
        self.client_id = client_id
        self.tenant = tenant or "organizations"
        self.cache_file = cache_file
        self._app: Any = None

    def _application(self) -> Any:
        if self._app is None:
            try:
                import msal
                from msal_extensions import PersistedTokenCache, build_encrypted_persistence
            except ImportError as exc:
                raise AuthError("Modules msal / msal-extensions absents (scripts\\setup.ps1).") from exc
            cache = PersistedTokenCache(build_encrypted_persistence(str(self.cache_file)))
            self._app = msal.PublicClientApplication(
                self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant}", token_cache=cache)
        return self._app

    def account(self) -> AccountInfo | None:
        accounts = self._application().get_accounts()
        if not accounts:
            return None
        first = accounts[0]
        return AccountInfo(first.get("username", ""), first.get("realm", ""))

    def token(self, scopes: list[str], interactive: bool = False) -> str:
        """Jeton silencieux si possible ; connexion interactive seulement sur demande explicite."""
        app = self._application()
        accounts = app.get_accounts()
        result = app.acquire_token_silent(scopes, account=accounts[0]) if accounts else None
        if not result and interactive:
            result = app.acquire_token_interactive(scopes, prompt="select_account")
        if not result:
            raise AuthError("Connexion Microsoft 365 requise (bouton « Se connecter »).")
        if "access_token" not in result:
            raise AuthError(self._explain(result))
        return str(result["access_token"])

    @staticmethod
    def _explain(result: dict[str, Any]) -> str:
        code = str(result.get("error", ""))
        if code == "consent_required" or "AADSTS65001" in str(result.get("error_description", "")):
            return ("Consentement requis : un administrateur doit approuver les permissions de l'application "
                    "(voir docs/microsoft-graph.md).")
        if code == "access_denied":
            return "Connexion annulée ou refusée."
        return f"Échec d'authentification ({code})."  # description non journalisée : peut contenir des détails

    def sign_out(self) -> None:
        app = self._application()
        for account in app.get_accounts():
            app.remove_account(account)
        log.info("Déconnexion Microsoft 365 effectuée.")
