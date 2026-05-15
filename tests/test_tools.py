"""Tests for the 9 SAP agent tools in ``piilot_pack_sap.tools``.

Strategy:

* Each ``_fn`` function is called directly (``bind_session`` preserves the
  underlying coroutine via ``functools.wraps`` so unit tests don't go
  through LangGraph).
* ``execute_odata_call`` / ``execute_raw_call`` are patched at the tools
  import site so we never construct a real ``ODataClient``.
* ``ConnectionResolver`` is patched to return a fake resolved connection
  for the 3 tools that don't go through the executor
  (``describe_entity`` / ``search_entity`` short-circuit on the DB cache).
* ``run_in_thread`` is replaced with a passthrough that runs the sync
  function inline.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from piilot_pack_sap.connection_resolver import (
    ResolutionError,
    ResolvedConnection,
)
from piilot_pack_sap.auth import BasicAuth
from piilot_pack_sap import tools
from piilot_pack_sap.tool_executor import ToolResult


async def _passthrough_run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


_RESOLVED = ResolvedConnection(
    connection_id="conn-1",
    company_id="comp-1",
    label="Sandbox",
    base_url="https://erp.example/sap",
    auth=BasicAuth(username="u", password="p"),
    version="v2",
    auth_mode="basic",
)


def _session_state(role: str | None = "user", role_id: int | None = 3):
    user_infos: dict[str, Any] = {"_organization_id": "comp-1"}
    if role is not None:
        user_infos["role"] = role
    if role_id is not None:
        user_infos["role_id"] = role_id
    return SimpleNamespace(user_infos=user_infos)


@pytest.fixture
def patched_session():
    """Patch both ``get_session`` import sites: ``tools.py`` for admin gate +
    role check, ``tool_executor.py`` for ``resolve_company_id``."""
    state = _session_state()
    with (
        patch("piilot_pack_sap.tools.get_session", return_value=state) as mock,
        patch("piilot_pack_sap.tool_executor.get_session", return_value=state),
    ):
        yield mock


@pytest.fixture
def patched_session_admin():
    state = _session_state(role="admin", role_id=1)
    with (
        patch("piilot_pack_sap.tools.get_session", return_value=state) as mock,
        patch("piilot_pack_sap.tool_executor.get_session", return_value=state),
    ):
        yield mock


@pytest.fixture
def patched_resolver():
    """Patch ConnectionResolver inside ``tools`` to return _RESOLVED."""
    with patch("piilot_pack_sap.tools.ConnectionResolver") as cls:
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=_RESOLVED)
        cls.return_value = resolver
        yield resolver


# ---------- sap_describe_entity --------------------------------------------


@pytest.mark.asyncio
async def test_describe_entity_returns_cached_payload(
    patched_session, patched_resolver
) -> None:
    with (
        patch(
            "piilot_pack_sap.tools.run_in_thread", new=_passthrough_run_in_thread
        ),
        patch(
            "piilot_pack_sap.tools.repository.get_snapshot_entry",
            return_value={
                "entity_set_name": "A_BusinessPartner",
                "service_path": "/sap/opu/odata/sap/API_BP",
                "label": "Business Partner",
                "description": "BP master data",
                "payload": {"properties": []},
                "last_synced_at": "2026-05-15T08:00:00Z",
            },
        ),
    ):
        out = await tools.sap_describe_entity_fn(
            entity_set="A_BusinessPartner", session_id="sess-1"
        )
    assert out["status"] == "ok"
    assert out["data"]["entity_set_name"] == "A_BusinessPartner"
    assert out["connection_label"] == "Sandbox"


@pytest.mark.asyncio
async def test_describe_entity_not_found_returns_not_found_status(
    patched_session, patched_resolver
) -> None:
    with (
        patch(
            "piilot_pack_sap.tools.run_in_thread", new=_passthrough_run_in_thread
        ),
        patch(
            "piilot_pack_sap.tools.repository.get_snapshot_entry",
            return_value=None,
        ),
    ):
        out = await tools.sap_describe_entity_fn(
            entity_set="A_Unknown", session_id="sess-1"
        )
    assert out["status"] == "not_found"
    assert "not in the cached snapshot" in out["error"]


@pytest.mark.asyncio
async def test_describe_entity_rejects_non_identifier(patched_session) -> None:
    out = await tools.sap_describe_entity_fn(
        entity_set="bad/path", session_id="sess-1"
    )
    assert out["status"] == "validator_rejected"


@pytest.mark.asyncio
async def test_describe_entity_session_unknown() -> None:
    with (
        patch("piilot_pack_sap.tools.get_session", return_value=None),
        patch("piilot_pack_sap.tool_executor.get_session", return_value=None),
    ):
        out = await tools.sap_describe_entity_fn(
            entity_set="X", session_id="sess-x"
        )
    assert out["status"] == "session_unknown"


@pytest.mark.asyncio
async def test_describe_entity_resolution_error(patched_session) -> None:
    with patch("piilot_pack_sap.tools.ConnectionResolver") as cls:
        resolver = MagicMock()
        resolver.resolve = AsyncMock(side_effect=ResolutionError("nope"))
        cls.return_value = resolver
        out = await tools.sap_describe_entity_fn(
            entity_set="X", session_id="sess-1"
        )
    assert out["status"] == "resolution_error"


# ---------- sap_search_entity ----------------------------------------------


@pytest.mark.asyncio
async def test_search_entity_finds_substring_match(
    patched_session, patched_resolver
) -> None:
    with (
        patch(
            "piilot_pack_sap.tools.run_in_thread", new=_passthrough_run_in_thread
        ),
        patch(
            "piilot_pack_sap.tools.repository.list_schema_snapshot",
            return_value=[
                {
                    "entity_set_name": "A_BillingDocument",
                    "label": "Billing",
                    "description": "Invoice header",
                },
                {
                    "entity_set_name": "A_PurchaseOrder",
                    "label": "Purchase Order",
                    "description": "PO header",
                },
            ],
        ),
    ):
        out = await tools.sap_search_entity_fn(
            query="invoice", limit=10, session_id="sess-1"
        )
    assert out["status"] == "ok"
    names = [m["entity_set_name"] for m in out["data"]["matches"]]
    assert names == ["A_BillingDocument"]


@pytest.mark.asyncio
async def test_search_entity_empty_query_rejected(patched_session) -> None:
    out = await tools.sap_search_entity_fn(query="", session_id="sess-1")
    assert out["status"] == "validator_rejected"


@pytest.mark.asyncio
async def test_search_entity_invalid_limit_rejected(patched_session) -> None:
    out = await tools.sap_search_entity_fn(
        query="x", limit=999, session_id="sess-1"
    )
    assert out["status"] == "validator_rejected"


# ---------- sap_select / count / top_n / aggregate -------------------------


@pytest.fixture
def patched_executor():
    """Patch execute_odata_call to a stub returning a fake ToolResult."""
    with patch("piilot_pack_sap.tools.execute_odata_call") as mock:
        mock.return_value = ToolResult(
            status="ok", data={"d": {"results": [{"x": 1}]}}, connection_label="Sandbox"
        )

        async def _fake(**kwargs):
            return mock.return_value

        mock.side_effect = _fake
        yield mock


@pytest.mark.asyncio
async def test_select_builds_correct_query(patched_executor) -> None:
    out = await tools.sap_select_fn(
        entity_set="A_BusinessPartner",
        filter="BusinessPartnerCategory eq '2'",
        select="BusinessPartner,FirstName",
        order_by="LastName desc",
        top=25,
        session_id="sess-1",
    )
    assert out["status"] == "ok"
    kwargs = patched_executor.call_args.kwargs
    query = kwargs["query"]
    assert query.entity_set == "A_BusinessPartner"
    assert query.filter == "BusinessPartnerCategory eq '2'"
    assert query.select == ("BusinessPartner", "FirstName")
    assert query.order_by == (("LastName", "desc"),)
    assert query.top == 25
    assert kwargs["tool_id"] == "sap.select"


@pytest.mark.asyncio
async def test_select_caps_top_at_max(patched_executor) -> None:
    await tools.sap_select_fn(
        entity_set="X", top=99999, session_id="sess-1"
    )
    assert patched_executor.call_args.kwargs["query"].top <= 1000


@pytest.mark.asyncio
async def test_select_invalid_orderby_returns_validator_rejected() -> None:
    out = await tools.sap_select_fn(
        entity_set="X", order_by="Name ascending", session_id="sess-1"
    )
    assert out["status"] == "validator_rejected"


@pytest.mark.asyncio
async def test_count_builds_count_query(patched_executor) -> None:
    await tools.sap_count_fn(
        entity_set="A_BusinessPartner",
        filter="IsArchived eq false",
        session_id="sess-1",
    )
    query = patched_executor.call_args.kwargs["query"]
    assert query.entity_set == "A_BusinessPartner"
    assert query.count is True
    assert query.filter == "IsArchived eq false"
    assert patched_executor.call_args.kwargs["tool_id"] == "sap.count"


@pytest.mark.asyncio
async def test_top_n_builds_query_with_top_and_orderby(patched_executor) -> None:
    await tools.sap_top_n_fn(
        entity_set="A_BusinessPartner",
        n=5,
        order_by="CreationDate desc",
        session_id="sess-1",
    )
    query = patched_executor.call_args.kwargs["query"]
    assert query.top == 5
    assert query.order_by == (("CreationDate", "desc"),)
    assert patched_executor.call_args.kwargs["tool_id"] == "sap.top_n"


@pytest.mark.asyncio
async def test_aggregate_wraps_in_aggregate_parens(patched_executor) -> None:
    await tools.sap_aggregate_fn(
        entity_set="Orders",
        aggregation="Amount with sum as Total",
        session_id="sess-1",
    )
    query = patched_executor.call_args.kwargs["query"]
    assert query.apply == "aggregate(Amount with sum as Total)"
    assert patched_executor.call_args.kwargs["tool_id"] == "sap.aggregate"


@pytest.mark.asyncio
async def test_aggregate_empty_expression_rejected() -> None:
    out = await tools.sap_aggregate_fn(
        entity_set="X", aggregation="", session_id="sess-1"
    )
    assert out["status"] == "validator_rejected"


# ---------- sap_navigate ---------------------------------------------------


@pytest.fixture
def patched_raw_executor():
    with patch("piilot_pack_sap.tools.execute_raw_call") as mock:

        async def _fake(**kwargs):
            return ToolResult(
                status="ok", data={"d": {"results": []}}, connection_label="Sandbox"
            )

        mock.side_effect = _fake
        yield mock


@pytest.mark.asyncio
async def test_navigate_builds_quoted_path(patched_raw_executor) -> None:
    out = await tools.sap_navigate_fn(
        entity_set="A_BusinessPartner",
        key="11",
        navigation_property="to_BusinessPartnerAddress",
        top=5,
        session_id="sess-1",
    )
    assert out["status"] == "ok"
    kwargs = patched_raw_executor.call_args.kwargs
    assert kwargs["path_after_base"] == "/A_BusinessPartner('11')/to_BusinessPartnerAddress"
    assert kwargs["params"] == {"$top": "5"}
    assert kwargs["tool_id"] == "sap.navigate"
    assert kwargs["entity_set"] == "A_BusinessPartner"


@pytest.mark.asyncio
async def test_navigate_escapes_single_quote_in_key(patched_raw_executor) -> None:
    await tools.sap_navigate_fn(
        entity_set="A_Customer",
        key="O'Brien",
        navigation_property="to_Address",
        session_id="sess-1",
    )
    path = patched_raw_executor.call_args.kwargs["path_after_base"]
    assert "'O''Brien'" in path


@pytest.mark.asyncio
async def test_navigate_rejects_invalid_navigation_property() -> None:
    out = await tools.sap_navigate_fn(
        entity_set="X",
        key="1",
        navigation_property="to_X/bad",
        session_id="sess-1",
    )
    assert out["status"] == "validator_rejected"


@pytest.mark.asyncio
async def test_navigate_rejects_empty_key() -> None:
    out = await tools.sap_navigate_fn(
        entity_set="X", key="", navigation_property="y", session_id="sess-1"
    )
    assert out["status"] == "validator_rejected"


# ---------- sap_lookup (admin gate) ---------------------------------------


@pytest.mark.asyncio
async def test_lookup_refuses_non_admin(patched_session) -> None:
    out = await tools.sap_lookup_fn(
        entity_set="A_BusinessPartner", key="11", session_id="sess-1"
    )
    assert out["status"] == "forbidden"
    assert "admin" in out["error"]


@pytest.mark.asyncio
async def test_lookup_admin_can_call(patched_session_admin, patched_raw_executor) -> None:
    out = await tools.sap_lookup_fn(
        entity_set="A_BusinessPartner",
        key="11",
        select="BusinessPartner,IsArchived",
        session_id="sess-1",
    )
    assert out["status"] == "ok"
    kwargs = patched_raw_executor.call_args.kwargs
    assert kwargs["path_after_base"] == "/A_BusinessPartner('11')"
    assert kwargs["params"] == {"$select": "BusinessPartner,IsArchived"}


@pytest.mark.asyncio
async def test_lookup_admin_no_select_omits_param(
    patched_session_admin, patched_raw_executor
) -> None:
    await tools.sap_lookup_fn(
        entity_set="X", key="1", session_id="sess-1"
    )
    assert patched_raw_executor.call_args.kwargs["params"] is None


@pytest.mark.asyncio
async def test_lookup_role_id_one_is_admin(patched_raw_executor) -> None:
    state = _session_state(role=None, role_id=1)
    with (
        patch("piilot_pack_sap.tools.get_session", return_value=state),
        patch("piilot_pack_sap.tool_executor.get_session", return_value=state),
    ):
        out = await tools.sap_lookup_fn(
            entity_set="X", key="1", session_id="sess-1"
        )
    assert out["status"] == "ok"


# ---------- sap_invoke_function -------------------------------------------


@pytest.mark.asyncio
async def test_invoke_function_refuses_non_admin(patched_session) -> None:
    out = await tools.sap_invoke_function_fn(
        function_name="MyFn", params={"X": "Y"}, session_id="sess-1"
    )
    assert out["status"] == "forbidden"


@pytest.mark.asyncio
async def test_invoke_function_admin_builds_param_path(
    patched_session_admin, patched_raw_executor
) -> None:
    await tools.sap_invoke_function_fn(
        function_name="ComputeBalance",
        params={"CompanyCode": "1000", "Year": 2026, "ActiveOnly": True},
        session_id="sess-1",
    )
    path = patched_raw_executor.call_args.kwargs["path_after_base"]
    assert path.startswith("/ComputeBalance(")
    assert "CompanyCode='1000'" in path
    assert "Year=2026" in path
    assert "ActiveOnly=true" in path


@pytest.mark.asyncio
async def test_invoke_function_rejects_unsupported_param_type(
    patched_session_admin,
) -> None:
    out = await tools.sap_invoke_function_fn(
        function_name="MyFn",
        params={"X": [1, 2]},
        session_id="sess-1",
    )
    assert out["status"] == "validator_rejected"
    assert "unsupported type" in out["error"]


@pytest.mark.asyncio
async def test_invoke_function_rejects_bad_param_name(
    patched_session_admin,
) -> None:
    out = await tools.sap_invoke_function_fn(
        function_name="MyFn",
        params={"Bad/Name": "1"},
        session_id="sess-1",
    )
    assert out["status"] == "validator_rejected"


@pytest.mark.asyncio
async def test_invoke_function_rejects_bad_function_name(
    patched_session_admin,
) -> None:
    out = await tools.sap_invoke_function_fn(
        function_name="bad/name", params={}, session_id="sess-1"
    )
    assert out["status"] == "validator_rejected"


# ---------- wire_tools ----------------------------------------------------


def test_wire_tools_registers_all_nine() -> None:
    with patch("piilot_pack_sap.tools.register_tool") as mock_register:
        tools.wire_tools()
    assert mock_register.call_count == 9
    ids = [call.args[0]["id"] for call in mock_register.call_args_list]
    assert ids == [
        "sap.describe_entity",
        "sap.search_entity",
        "sap.select",
        "sap.count",
        "sap.top_n",
        "sap.aggregate",
        "sap.navigate",
        "sap.lookup",
        "sap.invoke_function",
    ]
    # All wired with the SAP connector dependency.
    for call in mock_register.call_args_list:
        spec = call.args[0]
        assert spec["requires"] == "connectors.sap.s4hana_cloud"
        assert spec["label_key"].startswith("sap.tools.")
        assert spec["description_key"].startswith("sap.tools.")


def test_wire_tools_is_idempotent() -> None:
    with patch("piilot_pack_sap.tools.register_tool") as mock_register:
        tools.wire_tools()
        tools.wire_tools()
    assert mock_register.call_count == 18
    # Idempotency is delegated to the SDK via on_duplicate='replace'.
    for call in mock_register.call_args_list:
        assert call.kwargs.get("on_duplicate") == "replace"


def test_tools_strip_session_id_from_llm_schema() -> None:
    """bind_session must remove session_id from every tool's JSON schema."""
    for spec in tools._TOOL_SPECS:
        tool = spec["tool"]
        fields = tool.args_schema.model_fields
        assert (
            "session_id" not in fields
        ), f"{spec['id']} still exposes session_id to the LLM"
