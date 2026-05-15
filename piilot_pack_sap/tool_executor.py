"""Common execution pipeline for every SAP agent tool.

The 9 tools shipped in Phase 2 all share the same flow:

1. Resolve ``company_id`` from the session state.
2. Resolve the active SAP connection (scope or default).
3. Build an :class:`piilot_pack_sap.odata_client.ODataClient` from the
   connection.
4. Execute the validated :class:`ODataQuery`.
5. Append a row to ``integrations_sap.audit_log`` regardless of outcome.
6. Return a structured ``dict`` the LLM can serialize directly.

Centralising this here keeps individual tool functions small and ensures
audit + status taxonomy stay consistent across the bundle.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from piilot.sdk.db import run_in_thread
from piilot.sdk.session import get as get_session

from piilot_pack_sap import audit
from piilot_pack_sap.auth import AuthError
from piilot_pack_sap.connection_resolver import (
    ConnectionResolver,
    ResolutionError,
)
from piilot_pack_sap.odata_client import (
    ODataClient,
    ODataConnectionError,
    ODataHTTPError,
)
from piilot_pack_sap.odata_validator import ValidationError
from piilot_pack_sap.query_builder import ODataQuery

USER_INFO_COMPANY_KEYS: tuple[str, ...] = (
    "_organization_id",
    "company_id",
    "organization_id",
)


@dataclass(frozen=True)
class ToolResult:
    """Structured result returned by every tool. Easy to serialize to JSON."""

    status: str  # see ``audit.py`` status taxonomy
    data: Any = None
    error: Optional[str] = None
    connection_label: Optional[str] = None
    audit_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.data is not None:
            out["data"] = self.data
        if self.error is not None:
            out["error"] = self.error
        if self.connection_label is not None:
            out["connection_label"] = self.connection_label
        if self.audit_id is not None:
            out["audit_id"] = self.audit_id
        return out


class SessionUnknownError(Exception):
    """Raised when the session_id does not resolve to a known state."""


def resolve_company_id(session_id: str) -> str:
    """Read ``company_id`` from the session state. Raises if not found.

    Plugin tools never accept ``company_id`` as a parameter (the LLM should
    not control it). It is always read from the session that the host has
    populated for the current agent run.
    """
    if not session_id:
        raise SessionUnknownError("no session_id was bound to this tool call")
    state = get_session(session_id)
    if state is None:
        raise SessionUnknownError(f"session_id={session_id!r} is unknown or expired")
    user_infos = getattr(state, "user_infos", None) or {}
    for key in USER_INFO_COMPANY_KEYS:
        value = user_infos.get(key)
        if isinstance(value, str) and value:
            return value
    raise SessionUnknownError(
        "session state does not carry an organization/company id"
    )


async def execute_odata_call(
    *,
    query: ODataQuery,
    session_id: str,
    tool_id: str,
    user_id: Optional[str] = None,
    allowed_properties: Optional[Iterable[str]] = None,
    resolver: Optional[ConnectionResolver] = None,
) -> ToolResult:
    """Run the full pipeline: resolve → execute → audit → return.

    All exceptions are translated to a :class:`ToolResult` with the right
    audit status. Tools never raise — they return a structured payload so
    the LLM can react gracefully.
    """
    resolver = resolver or ConnectionResolver()

    try:
        company_id = resolve_company_id(session_id)
    except SessionUnknownError as exc:
        return ToolResult(status="session_unknown", error=str(exc))

    try:
        resolved = await resolver.resolve(
            company_id=company_id, session_id=session_id
        )
    except ResolutionError as exc:
        audit_id = await _audit_async(
            company_id=company_id,
            tool_id=tool_id,
            odata_url=_describe_query_for_audit(query),
            status="resolution_error",
            entity_set=query.entity_set,
            error=str(exc),
            user_id=user_id,
            session_id=session_id,
        )
        return ToolResult(
            status="resolution_error", error=str(exc), audit_id=audit_id
        )

    odata_url = f"{resolved.base_url}/{query.entity_set}"

    client = ODataClient(
        base_url=resolved.base_url,
        auth=resolved.auth,
        version=resolved.version,
    )
    started = time.monotonic()
    try:
        try:
            payload = await client.request(
                query, allowed_properties=allowed_properties
            )
            latency_ms = int((time.monotonic() - started) * 1000)
        except ValidationError as exc:
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status="validator_rejected",
                entity_set=query.entity_set,
                error=f"[{exc.code}] {exc.message}",
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status="validator_rejected",
                error=exc.message,
                connection_label=resolved.label,
                audit_id=audit_id,
            )
        except AuthError as exc:
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status="auth_error",
                entity_set=query.entity_set,
                error=str(exc),
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status="auth_error",
                error="authentication with SAP failed",
                connection_label=resolved.label,
                audit_id=audit_id,
            )
        except ODataHTTPError as exc:
            status = "rate_limited" if exc.status == 429 else "http_error"
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status=status,
                entity_set=query.entity_set,
                http_status=exc.status,
                error=exc.message,
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status=status,
                error=f"SAP returned HTTP {exc.status}",
                connection_label=resolved.label,
                audit_id=audit_id,
            )
        except ODataConnectionError as exc:
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status="timeout",
                entity_set=query.entity_set,
                error=str(exc),
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status="timeout",
                error="SAP is unreachable",
                connection_label=resolved.label,
                audit_id=audit_id,
            )
    finally:
        await client.aclose()

    audit_id = await _audit_async(
        company_id=company_id,
        connection_id=resolved.connection_id,
        tool_id=tool_id,
        odata_url=odata_url,
        status="ok",
        entity_set=query.entity_set,
        http_status=200,
        latency_ms=latency_ms,
        result_count=_count_results(payload),
        user_id=user_id,
        session_id=session_id,
    )
    return ToolResult(
        status="ok",
        data=payload,
        connection_label=resolved.label,
        audit_id=audit_id,
    )


async def execute_raw_call(
    *,
    path_after_base: str,
    session_id: str,
    tool_id: str,
    entity_set: Optional[str] = None,
    params: Optional[dict[str, str]] = None,
    user_id: Optional[str] = None,
    resolver: Optional[ConnectionResolver] = None,
) -> ToolResult:
    """Same pipeline as :func:`execute_odata_call` but for non-``ODataQuery``
    paths (navigation properties, function imports).

    The caller is responsible for the URL grammar — there is no validator
    on this path. Only use this for inputs that have already been screened
    by the tool layer (simple identifiers, quoted keys).
    """
    resolver = resolver or ConnectionResolver()

    try:
        company_id = resolve_company_id(session_id)
    except SessionUnknownError as exc:
        return ToolResult(status="session_unknown", error=str(exc))

    try:
        resolved = await resolver.resolve(
            company_id=company_id, session_id=session_id
        )
    except ResolutionError as exc:
        audit_id = await _audit_async(
            company_id=company_id,
            tool_id=tool_id,
            odata_url=f"<unresolved>{path_after_base}",
            status="resolution_error",
            entity_set=entity_set,
            error=str(exc),
            user_id=user_id,
            session_id=session_id,
        )
        return ToolResult(
            status="resolution_error", error=str(exc), audit_id=audit_id
        )

    odata_url = f"{resolved.base_url}{path_after_base if path_after_base.startswith('/') else '/' + path_after_base}"
    client = ODataClient(
        base_url=resolved.base_url,
        auth=resolved.auth,
        version=resolved.version,
    )
    started = time.monotonic()
    try:
        try:
            payload = await client.request_raw(path_after_base, params=params)
            latency_ms = int((time.monotonic() - started) * 1000)
        except AuthError as exc:
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status="auth_error",
                entity_set=entity_set,
                error=str(exc),
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status="auth_error",
                error="authentication with SAP failed",
                connection_label=resolved.label,
                audit_id=audit_id,
            )
        except ODataHTTPError as exc:
            status = "rate_limited" if exc.status == 429 else "http_error"
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status=status,
                entity_set=entity_set,
                http_status=exc.status,
                error=exc.message,
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status=status,
                error=f"SAP returned HTTP {exc.status}",
                connection_label=resolved.label,
                audit_id=audit_id,
            )
        except ODataConnectionError as exc:
            audit_id = await _audit_async(
                company_id=company_id,
                connection_id=resolved.connection_id,
                tool_id=tool_id,
                odata_url=odata_url,
                status="timeout",
                entity_set=entity_set,
                error=str(exc),
                user_id=user_id,
                session_id=session_id,
            )
            return ToolResult(
                status="timeout",
                error="SAP is unreachable",
                connection_label=resolved.label,
                audit_id=audit_id,
            )
    finally:
        await client.aclose()

    audit_id = await _audit_async(
        company_id=company_id,
        connection_id=resolved.connection_id,
        tool_id=tool_id,
        odata_url=odata_url,
        status="ok",
        entity_set=entity_set,
        http_status=200,
        latency_ms=latency_ms,
        result_count=_count_results(payload),
        user_id=user_id,
        session_id=session_id,
    )
    return ToolResult(
        status="ok",
        data=payload,
        connection_label=resolved.label,
        audit_id=audit_id,
    )


async def _audit_async(**kwargs: Any) -> str:
    """Write an audit row through the SDK's RLS-aware thread executor."""
    return await run_in_thread(audit.record_call, **kwargs)


def _count_results(payload: Any) -> Optional[int]:
    """Best-effort row count from either v2 (``d.results``) or v4 (``value``)."""
    if not isinstance(payload, dict):
        return None
    if "count" in payload and isinstance(payload["count"], int):
        return payload["count"]
    d = payload.get("d")
    if isinstance(d, dict):
        results = d.get("results")
        if isinstance(results, list):
            return len(results)
    value = payload.get("value")
    if isinstance(value, list):
        return len(value)
    return None


def _describe_query_for_audit(query: ODataQuery) -> str:
    """Render a stable identifier for a query that never reached the network."""
    parts: list[str] = [f"<unresolved>/{query.entity_set or '?'}"]
    if query.count:
        parts.append("$count=true")
    if query.top is not None:
        parts.append(f"$top={query.top}")
    return " ".join(parts)


__all__ = [
    "SessionUnknownError",
    "ToolResult",
    "USER_INFO_COMPANY_KEYS",
    "execute_odata_call",
    "execute_raw_call",
    "resolve_company_id",
]
