"""Async OData v2 / v4 HTTP client used by the SAP plugin.

Wraps :class:`httpx.AsyncClient` with:

* Auth injection (any :class:`piilot_pack_sap.auth.Auth` strategy).
* Whitelist validation on every outgoing request (via
  :class:`piilot_pack_sap.query_builder.ODataQuery`).
* Bounded retries with exponential backoff on transient failures
  (``429`` honoring ``Retry-After``, ``5xx``, connection errors).
* Version-aware headers (``OData-MaxVersion`` / ``OData-Version`` on v4,
  ``Accept: application/json`` everywhere).
* ``$count`` path responses parsed as ``{"count": <int>}`` for consistency.

The client never retries client-side errors (``4xx`` other than ``429``);
those are raised to the caller as :class:`ODataHTTPError` immediately.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Iterable
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from piilot_pack_sap.auth import Auth
from piilot_pack_sap.odata_validator import DEFAULT_MAX_TOP, ODataVersion
from piilot_pack_sap.query_builder import ODataQuery

logger = logging.getLogger("piilot_pack_sap.odata_client")

DEFAULT_USER_AGENT = "piilot-pack-sap/0.1.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
INITIAL_RETRY_DELAY_SECONDS = 0.5
MAX_RETRY_DELAY_SECONDS = 30.0

NON_RETRYABLE_STATUS: frozenset[int] = frozenset(
    {400, 401, 403, 404, 405, 410, 422, 451}
)


class ODataConnectionError(Exception):
    """Raised when the OData service cannot be reached after retries."""


class ODataHTTPError(Exception):
    """Raised when the server returns a non-success HTTP status.

    Plain ``Exception`` subclass (not a frozen dataclass) so that the Python
    runtime can attach ``__traceback__`` and ``__cause__`` when the exception
    propagates through ``async with`` and ``raise … from …`` contexts.
    """

    def __init__(self, status: int, message: str, response_body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.response_body = response_body

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.status}] {self.message}"


class ODataClient:
    """Async OData client. Use as an async context manager.

    Example::

        async with ODataClient(
            base_url="https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_BUSINESS_PARTNER",
            auth=ApiKeyAuth(api_key="..."),
            version="v2",
        ) as client:
            metadata_xml = await client.get_metadata()
            data = await client.request(
                ODataQuery(entity_set="A_BusinessPartner", top=5)
            )

    :param base_url: full URL to the OData service root, e.g.
        ``"https://host/sap/opu/odata/sap/API_BUSINESS_PARTNER"``. Should
        NOT include a trailing entity set name.
    :param auth: any :class:`Auth` strategy from :mod:`piilot_pack_sap.auth`.
    :param version: ``"v2"`` (default) or ``"v4"``.
    :param timeout: per-request timeout in seconds.
    :param max_retries: how many retry attempts to make on transient errors.
    :param max_top: hard cap on ``$top`` propagated to the validator.
    :param user_agent: HTTP User-Agent header value.
    :param http_client: optional :class:`httpx.AsyncClient` to reuse — handy
        for tests with :mod:`respx`. If ``None`` a client is created and
        managed by this object.
    :param sleep: optional async sleep function — replace with a stub in tests
        to avoid wall-clock waits during retry exercises.
    """

    def __init__(
        self,
        base_url: str,
        auth: Auth,
        *,
        version: ODataVersion = "v2",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_top: int = DEFAULT_MAX_TOP,
        user_agent: str = DEFAULT_USER_AGENT,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._version: ODataVersion = version
        self._max_top = max_top
        self._max_retries = max(0, max_retries)
        self._user_agent = user_agent
        self._sleep = sleep or asyncio.sleep

        self._owns_client = http_client is None
        self._client: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=timeout
        )

    async def __aenter__(self) -> ODataClient:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def version(self) -> ODataVersion:
        return self._version

    async def request(
        self,
        query: ODataQuery,
        *,
        allowed_properties: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Validate and execute the query. Returns the parsed JSON payload.

        ``$count`` responses are normalized to ``{"count": <int>}``.

        Raises :class:`piilot_pack_sap.odata_validator.ValidationError` on
        whitelist violations, :class:`ODataHTTPError` on non-success status,
        :class:`ODataConnectionError` when the service is unreachable.
        """
        path, params = query.build_url(
            "/",
            version=self._version,
            max_top=self._max_top,
            allowed_properties=allowed_properties,
        )
        url = self._base_url + path
        response = await self._send_get(url, params)

        if response.status_code >= 400:
            raise ODataHTTPError(
                status=response.status_code,
                message=(
                    f"OData {self._version} request to "
                    f"{path} failed with HTTP {response.status_code}"
                ),
                response_body=_truncate(response.text),
            )

        if path.endswith("/$count"):
            return _parse_count_response(response)

        try:
            return response.json()
        except ValueError as exc:
            raise ODataHTTPError(
                status=response.status_code,
                message="OData response is not valid JSON",
                response_body=_truncate(response.text),
            ) from exc

    async def request_raw(
        self,
        path_after_base: str,
        *,
        params: dict[str, str] | None = None,
        accept_override: str | None = None,
    ) -> dict[str, Any]:
        """Execute a GET on an arbitrary path appended to ``base_url``.

        Used for queries whose URL shape does not fit
        :class:`ODataQuery` (the standard composer assumes a flat
        ``base_url + entity_set + query options`` layout). Examples:

        * Navigation property fetches —
          ``/A_BusinessPartner('11')/to_Address``.
        * Function imports —
          ``/InvokeMyFunction(Param='X')``.

        The caller is responsible for constructing a valid OData path
        AND for whitelisting any query options it passes — this method
        does NOT run the query through the validator. Use the
        higher-level :meth:`request` for any query that the standard
        composer can produce.
        """
        if not path_after_base.startswith("/"):
            path_after_base = "/" + path_after_base
        url = self._base_url + path_after_base
        response = await self._send_get(
            url, params or {}, accept_override=accept_override
        )
        if response.status_code >= 400:
            raise ODataHTTPError(
                status=response.status_code,
                message=(
                    f"OData {self._version} request to {path_after_base} "
                    f"failed with HTTP {response.status_code}"
                ),
                response_body=_truncate(response.text),
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ODataHTTPError(
                status=response.status_code,
                message="OData response is not valid JSON",
                response_body=_truncate(response.text),
            ) from exc

    async def get_metadata(self) -> str:
        """Fetch the raw ``$metadata`` XML at ``<base_url>/$metadata``.

        Uses ``Accept: application/xml`` — sending ``application/json`` here
        triggers a ``406 Not Acceptable`` against SAP gateways because
        ``$metadata`` is exclusively XML (CSDL).
        """
        url = f"{self._base_url}/$metadata"
        response = await self._send_get(
            url, params={}, accept_override="application/xml"
        )
        if response.status_code >= 400:
            raise ODataHTTPError(
                status=response.status_code,
                message=f"$metadata fetch failed with HTTP {response.status_code}",
                response_body=_truncate(response.text),
            )
        return response.text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_headers(self, *, accept_override: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": accept_override or "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": self._user_agent,
        }
        if self._version == "v4":
            headers["OData-MaxVersion"] = "4.0"
            headers["OData-Version"] = "4.0"
        return headers

    async def _send_get(
        self,
        url: str,
        params: dict[str, str],
        *,
        accept_override: str | None = None,
    ) -> httpx.Response:
        last_response: httpx.Response | None = None
        delay = INITIAL_RETRY_DELAY_SECONDS

        for attempt in range(self._max_retries + 1):
            request = self._client.build_request(
                "GET",
                url,
                params=params,
                headers=self._build_headers(accept_override=accept_override),
            )
            await self._auth.apply(request)

            try:
                response = await self._client.send(request)
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise ODataConnectionError(
                        f"network error after {attempt + 1} attempts: {exc}"
                    ) from exc
                await self._sleep(_jitter(delay))
                delay = min(delay * 2, MAX_RETRY_DELAY_SECONDS)
                continue

            if response.status_code < 400:
                return response

            if response.status_code in NON_RETRYABLE_STATUS:
                return response

            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_response = response
                if attempt >= self._max_retries:
                    return response
                wait = _retry_after_seconds(response) or _jitter(delay)
                logger.info(
                    "OData transient error %s on %s — retrying in %.2fs (attempt %d)",
                    response.status_code,
                    url,
                    wait,
                    attempt + 1,
                )
                await self._sleep(wait)
                delay = min(delay * 2, MAX_RETRY_DELAY_SECONDS)
                continue

            return response

        return last_response or response  # type: ignore[return-value]


def _truncate(text: str, max_len: int = 1000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...[truncated]"


def _jitter(delay: float) -> float:
    """Full-jitter backoff (AWS architecture blog recommendation)."""
    return random.uniform(0, delay)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse ``Retry-After`` header. Supports seconds or HTTP-date."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    import datetime as _dt

    now = _dt.datetime.now(_dt.UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    delta = (dt - now).total_seconds()
    return max(0.0, delta)


def _parse_count_response(response: httpx.Response) -> dict[str, Any]:
    raw = response.text.strip()
    try:
        return {"count": int(raw)}
    except ValueError as exc:
        raise ODataHTTPError(
            status=response.status_code,
            message=f"unexpected $count response body: {raw!r}",
            response_body=_truncate(response.text),
        ) from exc


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_USER_AGENT",
    "ODataClient",
    "ODataConnectionError",
    "ODataHTTPError",
]
