"""Resolve the active SAP connection for an agent session.

The agent tools (Phase 2) don't know which SAP instance to hit by themselves —
the session may have multiple connections wired (e.g. Sandbox + Prod) and the
LLM should not pick. This module is the single source of truth for the
"which connection do I talk to?" decision.

Resolution order:

1. **Session scope** (``piilot.sdk.session.get_scope``) — if the user pinned a
   connection via the UI (or another tool called ``set_scope`` earlier in the
   conversation), use that ``connection_id``.
2. **Default active connection** — fall back to the most recently updated
   ``is_active = TRUE`` row in ``integrations_sap.connections`` for the
   tenant. Surfaces "the obvious connection" when there's only one.

Once the connection row is found, the matching credentials are loaded from
the core's ``plugin_connections`` table via :mod:`piilot.sdk.connectors`
(secrets are encrypted at rest; :mod:`piilot.sdk.crypto.decrypt` opens
them). The right :class:`piilot_pack_sap.auth.Auth` strategy is built
based on ``connections.auth_mode`` (``basic`` or ``oauth_client_credentials``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from piilot.sdk.connectors import get_connection
from piilot.sdk.crypto import decrypt
from piilot.sdk.db import run_in_thread
from piilot.sdk.session import get_scope

from piilot_pack_sap import repository
from piilot_pack_sap.auth import Auth, BasicAuth, OAuthClientCredentials
from piilot_pack_sap.odata_validator import ODataVersion

PLUGIN_NAMESPACE = "sap"
AuthMode = Literal["basic", "oauth_client_credentials"]


class ResolutionError(Exception):
    """Raised when the active SAP connection cannot be determined or loaded."""


@dataclass(frozen=True)
class ResolvedConnection:
    """Outcome of :func:`ConnectionResolver.resolve`.

    Carries everything an :class:`piilot_pack_sap.odata_client.ODataClient`
    needs to start issuing requests — the resolver hides the persistence
    + decryption details from the tool layer.
    """

    connection_id: str
    company_id: str
    label: str
    base_url: str
    auth: Auth
    version: ODataVersion
    auth_mode: AuthMode


class ConnectionResolver:
    """Stateless resolver — instantiate once per call, no shared state.

    Tests can substitute :func:`_load_connection_row` /
    :func:`_load_credentials` via dependency injection (kwargs) without
    monkey-patching the SDK modules.
    """

    def __init__(
        self,
        *,
        default_version: ODataVersion = "v2",
    ) -> None:
        self._default_version = default_version

    async def resolve_for_connection_id(
        self,
        *,
        connection_id: str,
        company_id: str,
    ) -> ResolvedConnection:
        """Resolve a specific connection by id (HTTP route entry point).

        Used by ``/test`` and ``/sync`` routes that already carry an
        explicit connection id in the URL — there's no session scope to
        consult, and the caller doesn't want the resolver's fallback to
        the "active connection" to silently pick a different row.
        """
        if not connection_id:
            raise ResolutionError("connection_id is required")
        if not company_id:
            raise ResolutionError("company_id is required")
        row = await run_in_thread(repository.get_connection_by_id, connection_id)
        if row is None:
            raise ResolutionError(f"connection_id={connection_id!r} not found")
        if row.get("company_id") != company_id:
            raise ResolutionError("connection belongs to another company")
        return await self._build_from_row(row)

    async def resolve(
        self,
        *,
        company_id: str,
        session_id: str | None = None,
    ) -> ResolvedConnection:
        """Resolve the connection to use for this agent call.

        Raises :class:`ResolutionError` when:

        * no scope is set AND no active connection exists for the tenant;
        * the scope points to a connection that no longer exists;
        * the credentials row is missing or cannot be decrypted;
        * the connection's ``auth_mode`` is not recognised.
        """
        if not company_id:
            raise ResolutionError("company_id is required to resolve a SAP connection")

        connection_id = self._pin_from_scope(session_id)

        if connection_id is not None:
            row = await run_in_thread(repository.get_connection_by_id, connection_id)
            if row is None:
                raise ResolutionError(
                    f"session scope points to unknown connection_id={connection_id!r}"
                )
            if row.get("company_id") != company_id:
                raise ResolutionError("session scope's connection belongs to another company")
        else:
            row = await run_in_thread(repository.get_active_connection, company_id)
            if row is None:
                raise ResolutionError("no active SAP connection configured for this tenant")

        return await self._build_from_row(row)

    async def _build_from_row(self, row: dict[str, Any]) -> ResolvedConnection:
        auth_mode: AuthMode = row.get("auth_mode") or "basic"
        version = self._default_version
        # Future: persist a per-connection ``odata_version`` column. For
        # v1 we rely on the resolver default (callers can override).

        auth = await self._build_auth(row, auth_mode)

        return ResolvedConnection(
            connection_id=str(row["id"]),
            company_id=str(row["company_id"]),
            label=row.get("label") or "",
            base_url=str(row["base_url"]).rstrip("/"),
            auth=auth,
            version=version,
            auth_mode=auth_mode,
        )

    @staticmethod
    def _pin_from_scope(session_id: str | None) -> str | None:
        """Return the ``connection_id`` pinned in the session, if any."""
        if not session_id:
            return None
        scope = get_scope(session_id)
        if not scope:
            return None
        if scope.get("plugin") != PLUGIN_NAMESPACE:
            return None
        connection_id = scope.get("connection_id")
        return str(connection_id) if connection_id else None

    async def _build_auth(
        self,
        connection_row: dict[str, Any],
        auth_mode: AuthMode,
    ) -> Auth:
        plugin_connection_id = connection_row.get("plugin_connection_id")
        if not plugin_connection_id:
            raise ResolutionError(
                "connection has no plugin_connection_id — credentials cannot be loaded"
            )
        plaintext = await run_in_thread(self._load_credentials, str(plugin_connection_id))

        if auth_mode == "basic":
            username = plaintext.get("username")
            password = plaintext.get("password")
            if not username or not password:
                raise ResolutionError("basic auth requires both username and password")
            return BasicAuth(username=username, password=password)

        if auth_mode == "oauth_client_credentials":
            token_url = plaintext.get("oauth_token_url")
            client_id = plaintext.get("oauth_client_id")
            client_secret = plaintext.get("oauth_client_secret")
            scope = plaintext.get("oauth_scope") or None
            if not token_url or not client_id or not client_secret:
                raise ResolutionError(
                    "oauth_client_credentials requires oauth_token_url, "
                    "oauth_client_id, and oauth_client_secret"
                )
            return OAuthClientCredentials(
                token_url=token_url,
                client_id=client_id,
                client_secret=client_secret,
                scope=scope,
            )

        raise ResolutionError(f"unknown auth_mode={auth_mode!r}")

    @staticmethod
    def _load_credentials(plugin_connection_id: str) -> dict[str, str]:
        """Read the encrypted creds row and decrypt every secret field.

        Returns a flat ``{field_name: plaintext}`` dict. Non-secret fields are
        returned as-is.
        """
        conn = get_connection(plugin_connection_id)
        if conn is None:
            raise ResolutionError(f"plugin_connection_id={plugin_connection_id!r} not found")
        creds = conn.get("credentials") or {}
        out: dict[str, str] = {}
        for name, value in creds.items():
            if not isinstance(value, str):
                continue
            # Heuristic: encrypted blobs are non-empty strings produced by
            # ``piilot.sdk.crypto.encrypt`` (prefixed). Decrypt failures
            # propagate to the caller; ResolutionError wraps higher up.
            try:
                out[name] = decrypt(value)
            except Exception:  # noqa: BLE001 - fall back to plaintext
                # If a field is intentionally non-encrypted (e.g. a username
                # in some legacy fixtures), preserve it.
                out[name] = value
        return out


__all__ = [
    "ConnectionResolver",
    "ResolutionError",
    "ResolvedConnection",
    "PLUGIN_NAMESPACE",
]
