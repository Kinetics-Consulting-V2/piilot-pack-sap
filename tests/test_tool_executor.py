"""Tests for ``piilot_pack_sap.tool_executor``.

The pipeline is exercised end-to-end with everything mocked:

* ``get_session`` returns a fake state with ``user_infos._organization_id``.
* ``ConnectionResolver.resolve`` is replaced with an async function that
  yields a fake :class:`ResolvedConnection` (or raises).
* ``ODataClient`` is patched at the import site so the executor uses a
  fake client whose ``request`` / ``aclose`` are controllable.
* ``run_in_thread`` becomes a passthrough that runs the sync function inline.
* ``audit.record_call`` is patched to a stub that returns a deterministic id.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from piilot_pack_sap.auth import AuthError, BasicAuth
from piilot_pack_sap.connection_resolver import (
    ResolutionError,
    ResolvedConnection,
)
from piilot_pack_sap.odata_client import ODataConnectionError, ODataHTTPError
from piilot_pack_sap.odata_validator import ValidationError
from piilot_pack_sap.query_builder import ODataQuery
from piilot_pack_sap.tool_executor import (
    SessionUnknownError,
    execute_odata_call,
    resolve_company_id,
)

_BASIC_AUTH = BasicAuth(username="u", password="p")

_RESOLVED = ResolvedConnection(
    connection_id="conn-1",
    company_id="comp-1",
    label="Sandbox",
    base_url="https://erp.example/sap",
    auth=_BASIC_AUTH,
    version="v2",
    auth_mode="basic",
)


async def _passthrough_run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


@pytest.fixture
def fake_session():
    """Stub ``piilot.sdk.session.get`` so it returns a fake state."""
    state = SimpleNamespace(user_infos={"_organization_id": "comp-1"})
    with patch(
        "piilot_pack_sap.tool_executor.get_session", return_value=state
    ) as mock:
        yield mock


@pytest.fixture
def patched_runtime(fake_session):
    """Patch run_in_thread + audit + ConnectionResolver + ODataClient."""
    with (
        patch(
            "piilot_pack_sap.tool_executor.run_in_thread",
            new=_passthrough_run_in_thread,
        ),
        patch(
            "piilot_pack_sap.tool_executor.audit.record_call",
            return_value="audit-uuid",
        ) as mock_audit,
        patch(
            "piilot_pack_sap.tool_executor.ODataClient"
        ) as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.request = AsyncMock()
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client
        yield {
            "audit": mock_audit,
            "client_cls": mock_client_cls,
            "client": mock_client,
        }


def _resolver_returning(resolved):
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=resolved)
    return resolver


def _resolver_raising(exc):
    resolver = MagicMock()
    resolver.resolve = AsyncMock(side_effect=exc)
    return resolver


# ---------- resolve_company_id ---------------------------------------------


def test_resolve_company_id_returns_from_user_infos() -> None:
    state = SimpleNamespace(user_infos={"_organization_id": "comp-1"})
    with patch("piilot_pack_sap.tool_executor.get_session", return_value=state):
        assert resolve_company_id("sess-1") == "comp-1"


def test_resolve_company_id_falls_back_to_alternate_keys() -> None:
    state = SimpleNamespace(user_infos={"company_id": "comp-2"})
    with patch("piilot_pack_sap.tool_executor.get_session", return_value=state):
        assert resolve_company_id("sess-1") == "comp-2"


def test_resolve_company_id_raises_on_empty_session_id() -> None:
    with pytest.raises(SessionUnknownError, match="no session_id"):
        resolve_company_id("")


def test_resolve_company_id_raises_on_unknown_session() -> None:
    with patch("piilot_pack_sap.tool_executor.get_session", return_value=None):
        with pytest.raises(SessionUnknownError, match="unknown or expired"):
            resolve_company_id("sess-1")


def test_resolve_company_id_raises_when_user_infos_lacks_org() -> None:
    state = SimpleNamespace(user_infos={"unrelated": "x"})
    with patch("piilot_pack_sap.tool_executor.get_session", return_value=state):
        with pytest.raises(SessionUnknownError, match="organization/company id"):
            resolve_company_id("sess-1")


# ---------- execute_odata_call — happy path --------------------------------


@pytest.mark.asyncio
async def test_execute_happy_path_returns_ok_with_data(patched_runtime) -> None:
    patched_runtime["client"].request.return_value = {
        "d": {"results": [{"BusinessPartner": "1"}]}
    }
    resolver = _resolver_returning(_RESOLVED)

    result = await execute_odata_call(
        query=ODataQuery(entity_set="A_BusinessPartner", top=1),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )

    assert result.status == "ok"
    assert result.data["d"]["results"][0]["BusinessPartner"] == "1"
    assert result.connection_label == "Sandbox"
    assert result.audit_id == "audit-uuid"
    # Audit row carries the right fields.
    audit_kwargs = patched_runtime["audit"].call_args.kwargs
    assert audit_kwargs["status"] == "ok"
    assert audit_kwargs["tool_id"] == "sap.select"
    assert audit_kwargs["entity_set"] == "A_BusinessPartner"
    assert audit_kwargs["connection_id"] == "conn-1"
    assert audit_kwargs["http_status"] == 200
    assert audit_kwargs["result_count"] == 1
    assert isinstance(audit_kwargs["latency_ms"], int)
    # Client lifecycle: opened then closed.
    patched_runtime["client"].aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_counts_v4_value_list(patched_runtime) -> None:
    patched_runtime["client"].request.return_value = {
        "value": [{"x": 1}, {"x": 2}, {"x": 3}]
    }
    resolver = _resolver_returning(_RESOLVED)
    await execute_odata_call(
        query=ODataQuery(entity_set="X", top=3),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert patched_runtime["audit"].call_args.kwargs["result_count"] == 3


@pytest.mark.asyncio
async def test_execute_counts_count_response(patched_runtime) -> None:
    patched_runtime["client"].request.return_value = {"count": 42}
    resolver = _resolver_returning(_RESOLVED)
    await execute_odata_call(
        query=ODataQuery(entity_set="X", count=True),
        session_id="sess-1",
        tool_id="sap.count",
        resolver=resolver,
    )
    assert patched_runtime["audit"].call_args.kwargs["result_count"] == 42


# ---------- execute_odata_call — error paths -------------------------------


@pytest.mark.asyncio
async def test_execute_session_unknown_returns_session_unknown_status() -> None:
    with patch("piilot_pack_sap.tool_executor.get_session", return_value=None):
        result = await execute_odata_call(
            query=ODataQuery(entity_set="X", top=1),
            session_id="sess-1",
            tool_id="sap.select",
            resolver=_resolver_returning(_RESOLVED),
        )
    assert result.status == "session_unknown"
    assert "unknown" in result.error


@pytest.mark.asyncio
async def test_execute_resolution_error_is_audited(patched_runtime) -> None:
    resolver = _resolver_raising(ResolutionError("no active connection"))

    result = await execute_odata_call(
        query=ODataQuery(entity_set="X", top=1),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert result.status == "resolution_error"
    assert "no active connection" in result.error
    audit_kwargs = patched_runtime["audit"].call_args.kwargs
    assert audit_kwargs["status"] == "resolution_error"
    assert "<unresolved>" in audit_kwargs["odata_url"]


@pytest.mark.asyncio
async def test_execute_validator_rejection_is_audited(patched_runtime) -> None:
    patched_runtime["client"].request.side_effect = ValidationError(
        code="function_call_forbidden", message="contains(...) not allowed"
    )
    resolver = _resolver_returning(_RESOLVED)

    result = await execute_odata_call(
        query=ODataQuery(entity_set="X", top=1, filter="contains(Name,'x')"),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert result.status == "validator_rejected"
    assert "not allowed" in result.error
    assert patched_runtime["audit"].call_args.kwargs["status"] == "validator_rejected"
    patched_runtime["client"].aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_auth_error_is_audited(patched_runtime) -> None:
    patched_runtime["client"].request.side_effect = AuthError("token refused")
    resolver = _resolver_returning(_RESOLVED)

    result = await execute_odata_call(
        query=ODataQuery(entity_set="X", top=1),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert result.status == "auth_error"
    assert result.error == "authentication with SAP failed"
    assert patched_runtime["audit"].call_args.kwargs["status"] == "auth_error"


@pytest.mark.asyncio
async def test_execute_http_error_is_audited(patched_runtime) -> None:
    patched_runtime["client"].request.side_effect = ODataHTTPError(
        status=500, message="boom"
    )
    resolver = _resolver_returning(_RESOLVED)
    result = await execute_odata_call(
        query=ODataQuery(entity_set="X", top=1),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert result.status == "http_error"
    assert "HTTP 500" in result.error
    audit_kwargs = patched_runtime["audit"].call_args.kwargs
    assert audit_kwargs["http_status"] == 500


@pytest.mark.asyncio
async def test_execute_http_429_maps_to_rate_limited(patched_runtime) -> None:
    patched_runtime["client"].request.side_effect = ODataHTTPError(
        status=429, message="slow down"
    )
    resolver = _resolver_returning(_RESOLVED)
    result = await execute_odata_call(
        query=ODataQuery(entity_set="X", top=1),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert result.status == "rate_limited"


@pytest.mark.asyncio
async def test_execute_connection_error_maps_to_timeout(patched_runtime) -> None:
    patched_runtime["client"].request.side_effect = ODataConnectionError("net down")
    resolver = _resolver_returning(_RESOLVED)
    result = await execute_odata_call(
        query=ODataQuery(entity_set="X", top=1),
        session_id="sess-1",
        tool_id="sap.select",
        resolver=resolver,
    )
    assert result.status == "timeout"
    assert result.error == "SAP is unreachable"


# ---------- ToolResult serialization ---------------------------------------


def test_tool_result_to_dict_omits_none_fields() -> None:
    from piilot_pack_sap.tool_executor import ToolResult

    out = ToolResult(status="ok", data={"x": 1}).to_dict()
    assert out == {"status": "ok", "data": {"x": 1}}


def test_tool_result_to_dict_includes_optional_fields() -> None:
    from piilot_pack_sap.tool_executor import ToolResult

    out = ToolResult(
        status="http_error",
        error="boom",
        connection_label="Sandbox",
        audit_id="aid",
    ).to_dict()
    assert out == {
        "status": "http_error",
        "error": "boom",
        "connection_label": "Sandbox",
        "audit_id": "aid",
    }


# ---------- execute_raw_call -----------------------------------------------


@pytest.fixture
def patched_raw_runtime(fake_session):
    """Same as ``patched_runtime`` but ``request_raw`` instead of ``request``."""
    with (
        patch(
            "piilot_pack_sap.tool_executor.run_in_thread",
            new=_passthrough_run_in_thread,
        ),
        patch(
            "piilot_pack_sap.tool_executor.audit.record_call",
            return_value="audit-uuid",
        ) as mock_audit,
        patch("piilot_pack_sap.tool_executor.ODataClient") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.request_raw = AsyncMock()
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client
        yield {
            "audit": mock_audit,
            "client_cls": mock_client_cls,
            "client": mock_client,
        }


@pytest.mark.asyncio
async def test_execute_raw_happy_path(patched_raw_runtime) -> None:
    patched_raw_runtime["client"].request_raw.return_value = {"d": {"x": 1}}
    from piilot_pack_sap.tool_executor import execute_raw_call

    result = await execute_raw_call(
        path_after_base="/A_BusinessPartner('11')/to_Address",
        session_id="sess-1",
        tool_id="sap.navigate",
        entity_set="A_BusinessPartner",
        params={"$top": "10"},
        resolver=_resolver_returning(_RESOLVED),
    )
    assert result.status == "ok"
    assert result.data == {"d": {"x": 1}}
    # request_raw was called with the right path AND $top params.
    call = patched_raw_runtime["client"].request_raw.call_args
    assert call.args[0] == "/A_BusinessPartner('11')/to_Address"
    assert call.kwargs["params"] == {"$top": "10"}
    audit_kwargs = patched_raw_runtime["audit"].call_args.kwargs
    assert audit_kwargs["status"] == "ok"
    assert audit_kwargs["tool_id"] == "sap.navigate"


@pytest.mark.asyncio
async def test_execute_raw_session_unknown_short_circuits() -> None:
    from piilot_pack_sap.tool_executor import execute_raw_call

    with patch("piilot_pack_sap.tool_executor.get_session", return_value=None):
        result = await execute_raw_call(
            path_after_base="/X",
            session_id="sess-1",
            tool_id="sap.navigate",
            resolver=_resolver_returning(_RESOLVED),
        )
    assert result.status == "session_unknown"


@pytest.mark.asyncio
async def test_execute_raw_resolution_error(patched_raw_runtime) -> None:
    from piilot_pack_sap.tool_executor import execute_raw_call

    result = await execute_raw_call(
        path_after_base="/X",
        session_id="sess-1",
        tool_id="sap.navigate",
        resolver=_resolver_raising(ResolutionError("nope")),
    )
    assert result.status == "resolution_error"
    audit_kwargs = patched_raw_runtime["audit"].call_args.kwargs
    assert audit_kwargs["odata_url"] == "<unresolved>/X"


@pytest.mark.asyncio
async def test_execute_raw_http_error(patched_raw_runtime) -> None:
    from piilot_pack_sap.tool_executor import execute_raw_call

    patched_raw_runtime["client"].request_raw.side_effect = ODataHTTPError(
        status=404, message="not found"
    )
    result = await execute_raw_call(
        path_after_base="/X(1)",
        session_id="sess-1",
        tool_id="sap.lookup",
        resolver=_resolver_returning(_RESOLVED),
    )
    assert result.status == "http_error"
    assert patched_raw_runtime["audit"].call_args.kwargs["http_status"] == 404


@pytest.mark.asyncio
async def test_execute_raw_429_maps_to_rate_limited(patched_raw_runtime) -> None:
    from piilot_pack_sap.tool_executor import execute_raw_call

    patched_raw_runtime["client"].request_raw.side_effect = ODataHTTPError(
        status=429, message="slow"
    )
    result = await execute_raw_call(
        path_after_base="/X",
        session_id="sess-1",
        tool_id="sap.invoke_function",
        resolver=_resolver_returning(_RESOLVED),
    )
    assert result.status == "rate_limited"


@pytest.mark.asyncio
async def test_execute_raw_auth_error(patched_raw_runtime) -> None:
    from piilot_pack_sap.tool_executor import execute_raw_call

    patched_raw_runtime["client"].request_raw.side_effect = AuthError("token bad")
    result = await execute_raw_call(
        path_after_base="/X",
        session_id="sess-1",
        tool_id="sap.lookup",
        resolver=_resolver_returning(_RESOLVED),
    )
    assert result.status == "auth_error"


@pytest.mark.asyncio
async def test_execute_raw_connection_error(patched_raw_runtime) -> None:
    from piilot_pack_sap.tool_executor import execute_raw_call

    patched_raw_runtime["client"].request_raw.side_effect = ODataConnectionError(
        "net down"
    )
    result = await execute_raw_call(
        path_after_base="/X",
        session_id="sess-1",
        tool_id="sap.lookup",
        resolver=_resolver_returning(_RESOLVED),
    )
    assert result.status == "timeout"


@pytest.mark.asyncio
async def test_execute_raw_path_without_leading_slash_still_works(
    patched_raw_runtime,
) -> None:
    """The helper must prepend ``/`` when callers omit it."""
    from piilot_pack_sap.tool_executor import execute_raw_call

    patched_raw_runtime["client"].request_raw.return_value = {"value": []}
    await execute_raw_call(
        path_after_base="MyFunction()",
        session_id="sess-1",
        tool_id="sap.invoke_function",
        resolver=_resolver_returning(_RESOLVED),
    )
    audit_kwargs = patched_raw_runtime["audit"].call_args.kwargs
    assert audit_kwargs["odata_url"].endswith("/MyFunction()")
