"""Authentication strategies for the OData client.

Three modes are supported by the v1 plugin:

* :class:`ApiKeyAuth` — header-based, used by the SAP API Hub sandbox
  (``APIKey: <key>``). Also useful for some on-prem gateways.
* :class:`BasicAuth` — HTTP Basic, the most common mode for SAP technical
  users on S/4HANA Cloud / on-prem when a custom IdP is not configured.
* :class:`OAuthClientCredentials` — OAuth 2.0 client_credentials grant, the
  standard mode for SAP S/4HANA Cloud with an external IdP. Caches the
  bearer token in memory with a configurable expiry buffer.

All auth strategies expose the same async :meth:`apply` interface so the
:class:`~piilot_pack_sap.odata_client.ODataClient` does not need to know
which mode it uses.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, runtime_checkable

import httpx


class AuthError(Exception):
    """Raised when authentication cannot complete (token endpoint refusal, etc.)."""


@runtime_checkable
class Auth(Protocol):
    """Async auth strategy applied to an outgoing :class:`httpx.Request`."""

    async def apply(self, request: httpx.Request) -> None:
        ...  # pragma: no cover


@dataclass(frozen=True)
class ApiKeyAuth:
    """Inject an API key as a header. Defaults to SAP's ``APIKey`` header name."""

    api_key: str
    header_name: str = "APIKey"

    async def apply(self, request: httpx.Request) -> None:
        request.headers[self.header_name] = self.api_key


@dataclass(frozen=True)
class BasicAuth:
    """HTTP Basic auth (RFC 7617)."""

    username: str
    password: str

    async def apply(self, request: httpx.Request) -> None:
        raw = f"{self.username}:{self.password}".encode("utf-8")
        request.headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")


class OAuthClientCredentials:
    """OAuth 2.0 ``client_credentials`` grant with in-memory token cache.

    Standard SAP S/4HANA Cloud auth mode when an external IdP is configured.
    The token is fetched lazily on the first :meth:`apply` call and reused
    until it is within ``expiry_buffer_seconds`` of expiring.

    Thread-safe across concurrent coroutines via :class:`asyncio.Lock`.

    :param token_url: e.g. ``"https://<tenant>.authentication.sap.hana.ondemand.com/oauth/token"``.
    :param client_id: registered in SAP BTP / IdP.
    :param client_secret: keep out of logs.
    :param scope: optional space-delimited scope string.
    :param http_client: inject a custom :class:`httpx.AsyncClient` (useful for
        tests with :mod:`respx`). If ``None`` a fresh client is created per
        token request — fine for low-frequency auth flows.
    :param clock: monotonic clock function — overridable for tests.
    :param expiry_buffer_seconds: refresh the token this many seconds before
        the server-declared expiry to avoid races at the boundary.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        clock: Callable[[], float] = time.monotonic,
        expiry_buffer_seconds: int = 30,
    ) -> None:
        if not token_url:
            raise ValueError("token_url must not be empty")
        if not client_id or not client_secret:
            raise ValueError("client_id and client_secret are required")
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._http_client = http_client
        self._clock = clock
        self._expiry_buffer = expiry_buffer_seconds
        self._lock = asyncio.Lock()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    async def apply(self, request: httpx.Request) -> None:
        token = await self._get_token()
        request.headers["Authorization"] = f"Bearer {token}"

    async def _get_token(self) -> str:
        async with self._lock:
            now = self._clock()
            if self._access_token and now < self._expires_at - self._expiry_buffer:
                return self._access_token
            return await self._refresh(now)

    async def _refresh(self, now: float) -> str:
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scope:
            data["scope"] = self._scope

        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http_client is None
        try:
            response = await client.post(
                self._token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code != 200:
            raise AuthError(
                f"OAuth token endpoint refused with HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthError(
                f"OAuth token endpoint returned non-JSON: {response.text[:200]}"
            ) from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise AuthError("OAuth response is missing access_token")

        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            # Fallback to 1h when the server doesn't specify — SAP IdPs sometimes
            # omit expires_in on machine-to-machine tokens.
            expires_in = 3600

        self._access_token = token
        self._expires_at = now + float(expires_in)
        return token


__all__ = [
    "Auth",
    "AuthError",
    "ApiKeyAuth",
    "BasicAuth",
    "OAuthClientCredentials",
]
