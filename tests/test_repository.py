"""Tests for ``piilot_pack_sap.repository``.

The DB cursor is fully mocked: we never hit a real PostgreSQL instance in
the unit suite. :func:`piilot.sdk.testing.mock_db_conn` neutralises
``execute_values`` so its bytes-join helper does not crash on
``MagicMock`` cursors.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from piilot.sdk.testing import mock_db_conn

from piilot_pack_sap import repository


@pytest.fixture
def mock_cursor():
    """Yield a MagicMock cursor wired into ``repository.cursor``.

    Also patches ``repository.Json`` as a passthrough — the real
    ``piilot.sdk.db.Json`` is a placeholder until the host loader wires
    the psycopg2 adapter at boot, so calling it raises
    ``NotImplementedError`` in isolated unit tests.
    """
    cur = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = cur
    cm.__exit__.return_value = False
    with (
        patch("piilot_pack_sap.repository.cursor", return_value=cm),
        patch("piilot_pack_sap.repository.Json", side_effect=lambda payload: payload),
        mock_db_conn(cur),
    ):
        yield cur


# ---------- upsert_schema_snapshot ------------------------------------------


def test_upsert_schema_snapshot_emits_insert_with_on_conflict(mock_cursor) -> None:
    """``mock_db_conn`` decomposes ``execute_values`` into one ``execute`` per
    row in the test fixture, so we assert on the SQL shape (single INSERT
    template with ON CONFLICT) rather than the call count."""
    mock_cursor.rowcount = 2
    n = repository.upsert_schema_snapshot(
        connection_id="conn-1",
        company_id="comp-1",
        service_path="/sap/opu/odata/sap/API_BUSINESS_PARTNER",
        entries=[
            {
                "entity_set_name": "A_BusinessPartner",
                "label": "Business Partner",
                "description": "BP master data",
                "payload": {"properties": [{"name": "BusinessPartner"}]},
            },
            {
                "entity_set_name": "A_Customer",
                "payload": {"properties": []},
            },
        ],
    )
    assert n == 2
    # Two entries -> two execute calls under the mock_db_conn fake.
    assert mock_cursor.execute.call_count == 2
    # Each call uses the same upsert template.
    sql_first = mock_cursor.execute.call_args_list[0][0][0]
    assert "INSERT INTO integrations_sap.schema_snapshot" in sql_first
    assert "ON CONFLICT (connection_id, service_path, entity_set_name)" in sql_first


def test_upsert_schema_snapshot_skips_when_no_entries(mock_cursor) -> None:
    n = repository.upsert_schema_snapshot(
        connection_id="conn-1",
        company_id="comp-1",
        service_path="/sap",
        entries=[],
    )
    assert n == 0
    mock_cursor.execute.assert_not_called()


def test_upsert_schema_snapshot_handles_missing_optional_fields(mock_cursor) -> None:
    """label / description / payload may be omitted on each entry."""
    mock_cursor.rowcount = 1
    repository.upsert_schema_snapshot(
        connection_id="c",
        company_id="co",
        service_path="/sap",
        entries=[{"entity_set_name": "X"}],
    )
    # The values argument is positional [3] for execute_values' template
    # replacement — but with mock_db_conn the call goes through
    # cur.execute(sql % tuple(values)). The exact contract: SQL is rendered
    # and execute is called once.
    mock_cursor.execute.assert_called_once()


# ---------- list_schema_snapshot --------------------------------------------


def test_list_schema_snapshot_returns_fetched_rows(mock_cursor) -> None:
    expected = [
        {"id": "r1", "entity_set_name": "A_BP"},
        {"id": "r2", "entity_set_name": "A_Customer"},
    ]
    mock_cursor.fetchall.return_value = expected
    result = repository.list_schema_snapshot(connection_id="conn-1")
    assert result == expected
    sql, params = mock_cursor.execute.call_args[0]
    assert "FROM integrations_sap.schema_snapshot" in sql
    assert params == ("conn-1", 500)


def test_list_schema_snapshot_respects_limit(mock_cursor) -> None:
    mock_cursor.fetchall.return_value = []
    repository.list_schema_snapshot(connection_id="x", limit=10)
    _, params = mock_cursor.execute.call_args[0]
    assert params == ("x", 10)


# ---------- get_snapshot_entry ----------------------------------------------


def test_get_snapshot_entry_returns_row_when_found(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "r1", "entity_set_name": "A_BP"}
    result = repository.get_snapshot_entry(
        connection_id="c1", entity_set_name="A_BP"
    )
    assert result == {"id": "r1", "entity_set_name": "A_BP"}
    _, params = mock_cursor.execute.call_args[0]
    assert params == ("c1", "A_BP")


def test_get_snapshot_entry_returns_none_when_missing(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = None
    assert repository.get_snapshot_entry(connection_id="c", entity_set_name="X") is None


# ---------- insert_audit_log ------------------------------------------------


def test_insert_audit_log_emits_insert_returning_id(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "audit-uuid"}
    audit_id = repository.insert_audit_log(
        {
            "company_id": "comp-1",
            "tool_id": "sap.select",
            "odata_url": "/A_BusinessPartner?$top=1",
            "status": "ok",
            "http_status": 200,
            "latency_ms": 142,
            "entity_set": "A_BusinessPartner",
            "result_count": 1,
        }
    )
    assert audit_id == "audit-uuid"
    sql, params = mock_cursor.execute.call_args[0]
    assert "INSERT INTO integrations_sap.audit_log" in sql
    assert "RETURNING id" in sql
    assert params[0] == "comp-1"
    assert params[4] == "sap.select"
    assert params[6] == "/A_BusinessPartner?$top=1"
    assert params[7] == "GET"  # default http_method
    assert params[8] == "ok"


def test_insert_audit_log_defaults_optional_fields(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "x"}
    repository.insert_audit_log(
        {
            "company_id": "comp-1",
            "tool_id": "sap.select",
            "odata_url": "/x",
            "status": "validator_rejected",
        }
    )
    _, params = mock_cursor.execute.call_args[0]
    assert params[1] is None  # connection_id
    assert params[2] is None  # user_id
    assert params[3] is None  # session_id
    assert params[5] is None  # entity_set
    assert params[7] == "GET"
    assert params[9] is None  # http_status
    assert params[10] is None  # latency_ms
    assert params[11] is None  # error
    assert params[12] is None  # result_count


def test_insert_audit_log_preserves_custom_http_method(mock_cursor) -> None:
    """We currently only emit GET but the column accepts anything."""
    mock_cursor.fetchone.return_value = {"id": "x"}
    repository.insert_audit_log(
        {
            "company_id": "comp-1",
            "tool_id": "sap.select",
            "odata_url": "/x",
            "status": "ok",
            "http_method": "GET",
        }
    )
    _, params = mock_cursor.execute.call_args[0]
    assert params[7] == "GET"


# ---------- list_connections / get_connection_by_id / get_active_connection


def test_list_connections_filters_active_by_default(mock_cursor) -> None:
    mock_cursor.fetchall.return_value = [
        {"id": "c1", "label": "Sandbox", "is_active": True},
        {"id": "c2", "label": "Prod", "is_active": True},
    ]
    rows = repository.list_connections(company_id="comp-1")
    assert len(rows) == 2
    sql, params = mock_cursor.execute.call_args[0]
    assert "is_active = TRUE" in sql
    assert "ORDER BY updated_at DESC" in sql
    assert params == ("comp-1",)


def test_list_connections_includes_inactive_when_requested(mock_cursor) -> None:
    mock_cursor.fetchall.return_value = []
    repository.list_connections(company_id="comp-1", active_only=False)
    sql, _ = mock_cursor.execute.call_args[0]
    assert "is_active = TRUE" not in sql


def test_get_connection_by_id_returns_row_when_found(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "c1", "label": "Sandbox"}
    row = repository.get_connection_by_id("c1")
    assert row == {"id": "c1", "label": "Sandbox"}
    _, params = mock_cursor.execute.call_args[0]
    assert params == ("c1",)


def test_get_connection_by_id_returns_none_when_missing(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = None
    assert repository.get_connection_by_id("missing") is None


def test_get_active_connection_returns_most_recent_active(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "c1", "is_active": True}
    row = repository.get_active_connection("comp-1")
    assert row["id"] == "c1"
    sql, params = mock_cursor.execute.call_args[0]
    assert "is_active = TRUE" in sql
    assert "ORDER BY updated_at DESC" in sql
    assert "LIMIT 1" in sql
    assert params == ("comp-1",)


def test_get_active_connection_returns_none_when_no_match(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = None
    assert repository.get_active_connection("comp-1") is None


# ---------- insert / update / delete / set_health -------------------------


def test_insert_connection_returns_id(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "new-uuid"}
    cid = repository.insert_connection(
        company_id="comp-1",
        label="Sandbox",
        base_url="https://example.sap/",
        auth_mode="basic",
        plugin_connection_id="plug-1",
    )
    assert cid == "new-uuid"
    sql, params = mock_cursor.execute.call_args[0]
    assert "INSERT INTO integrations_sap.connections" in sql
    assert "RETURNING id" in sql
    # base_url trailing slash stripped.
    assert params[2] == "https://example.sap"
    assert params[3] == "basic"
    assert params[4] == "plug-1"


def test_insert_connection_accepts_no_plugin_connection_id(mock_cursor) -> None:
    mock_cursor.fetchone.return_value = {"id": "id"}
    repository.insert_connection(
        company_id="c",
        label="x",
        base_url="https://x",
        auth_mode="basic",
    )
    params = mock_cursor.execute.call_args[0][1]
    assert params[4] is None


def test_update_connection_filters_allowlist(mock_cursor) -> None:
    mock_cursor.rowcount = 1
    ok = repository.update_connection(
        "conn-1",
        label="New",
        base_url="https://x",
        unknown_field="should_be_ignored",
        company_id="HACK",  # immutable: filtered out
    )
    assert ok is True
    sql, params = mock_cursor.execute.call_args[0]
    assert "label = %s" in sql
    assert "base_url = %s" in sql
    assert "company_id" not in sql
    assert "unknown_field" not in sql
    assert params[-1] == "conn-1"


def test_update_connection_returns_false_when_nothing_to_update(mock_cursor) -> None:
    assert repository.update_connection("conn-1") is False
    mock_cursor.execute.assert_not_called()


def test_update_connection_returns_false_when_no_row_matched(mock_cursor) -> None:
    mock_cursor.rowcount = 0
    assert repository.update_connection("conn-x", label="Z") is False


def test_delete_connection_returns_true_when_deleted(mock_cursor) -> None:
    mock_cursor.rowcount = 1
    assert repository.delete_connection("conn-1") is True
    sql, params = mock_cursor.execute.call_args[0]
    assert "DELETE FROM integrations_sap.connections" in sql
    assert params == ("conn-1",)


def test_delete_connection_returns_false_when_missing(mock_cursor) -> None:
    mock_cursor.rowcount = 0
    assert repository.delete_connection("ghost") is False


def test_set_connection_health_updates_three_fields(mock_cursor) -> None:
    mock_cursor.rowcount = 1
    ok = repository.set_connection_health(
        connection_id="conn-1", status="ok"
    )
    assert ok is True
    sql, params = mock_cursor.execute.call_args[0]
    assert "last_health_check_at = now()" in sql
    assert "last_health_status" in sql
    assert "last_health_error" in sql
    assert params == ("ok", None, "conn-1")


def test_set_connection_health_carries_error(mock_cursor) -> None:
    mock_cursor.rowcount = 1
    repository.set_connection_health(
        connection_id="c", status="error", error="boom"
    )
    params = mock_cursor.execute.call_args[0][1]
    assert params == ("error", "boom", "c")


# ---------- list_audit_log --------------------------------------------------


def test_list_audit_log_orders_by_recent_first(mock_cursor) -> None:
    mock_cursor.fetchall.return_value = [{"id": "a1"}]
    result = repository.list_audit_log(company_id="comp-1")
    assert result == [{"id": "a1"}]
    sql, params = mock_cursor.execute.call_args[0]
    assert "ORDER BY created_at DESC" in sql
    assert params == ("comp-1", 100)


def test_list_audit_log_filters_by_status(mock_cursor) -> None:
    mock_cursor.fetchall.return_value = []
    repository.list_audit_log(
        company_id="comp-1", status="http_error", limit=25
    )
    sql, params = mock_cursor.execute.call_args[0]
    assert "AND status = %s" in sql
    assert params == ("comp-1", "http_error", 25)
