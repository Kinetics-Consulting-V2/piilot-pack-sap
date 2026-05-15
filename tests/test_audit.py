"""Tests for ``piilot_pack_sap.audit.record_call``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from piilot_pack_sap import audit


def test_record_call_inserts_via_repository_and_returns_id() -> None:
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="audit-uuid",
    ) as mock_insert:
        audit_id = audit.record_call(
            company_id="comp-1",
            tool_id="sap.select",
            odata_url="/A_BusinessPartner?$top=10",
            status="ok",
            entity_set="A_BusinessPartner",
            http_status=200,
            latency_ms=120,
            result_count=10,
        )
    assert audit_id == "audit-uuid"
    entry = mock_insert.call_args[0][0]
    assert entry["company_id"] == "comp-1"
    assert entry["tool_id"] == "sap.select"
    assert entry["odata_url"] == "/A_BusinessPartner?$top=10"
    assert entry["status"] == "ok"
    assert entry["http_method"] == "GET"
    assert entry["entity_set"] == "A_BusinessPartner"
    assert entry["http_status"] == 200
    assert entry["latency_ms"] == 120
    assert entry["result_count"] == 10


def test_record_call_truncates_long_error() -> None:
    long_error = "X" * 5000
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="x",
    ) as mock_insert:
        audit.record_call(
            company_id="c",
            tool_id="t",
            odata_url="/u",
            status="http_error",
            error=long_error,
        )
    entry = mock_insert.call_args[0][0]
    assert entry["error"] is not None
    assert len(entry["error"]) <= 2020  # 2000 chars + truncation suffix
    assert entry["error"].endswith("...[truncated]")


def test_record_call_keeps_short_error_intact() -> None:
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="x",
    ):
        audit.record_call(
            company_id="c",
            tool_id="t",
            odata_url="/u",
            status="http_error",
            error="short error",
        )
    # Re-call to capture the entry via a new mock for inspection.
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="x",
    ) as mock_insert:
        audit.record_call(
            company_id="c",
            tool_id="t",
            odata_url="/u",
            status="http_error",
            error="short error",
        )
    assert mock_insert.call_args[0][0]["error"] == "short error"


def test_record_call_none_error_stays_none() -> None:
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="x",
    ) as mock_insert:
        audit.record_call(
            company_id="c",
            tool_id="t",
            odata_url="/u",
            status="ok",
        )
    assert mock_insert.call_args[0][0]["error"] is None


@pytest.mark.parametrize(
    "kwargs,missing",
    [
        ({"company_id": "", "tool_id": "t", "odata_url": "/u", "status": "ok"}, "company_id"),
        ({"company_id": "c", "tool_id": "", "odata_url": "/u", "status": "ok"}, "tool_id"),
        ({"company_id": "c", "tool_id": "t", "odata_url": "", "status": "ok"}, "odata_url"),
        ({"company_id": "c", "tool_id": "t", "odata_url": "/u", "status": ""}, "status"),
    ],
)
def test_record_call_rejects_missing_required_fields(kwargs, missing) -> None:
    with pytest.raises(ValueError, match=missing):
        audit.record_call(**kwargs)


def test_record_call_propagates_optional_fields() -> None:
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="x",
    ) as mock_insert:
        audit.record_call(
            company_id="comp-1",
            tool_id="sap.aggregate",
            odata_url="/Orders?$apply=aggregate(...)",
            status="validator_rejected",
            connection_id="conn-1",
            user_id="user-1",
            session_id="sess-1",
            error="function_call_forbidden",
        )
    entry = mock_insert.call_args[0][0]
    assert entry["connection_id"] == "conn-1"
    assert entry["user_id"] == "user-1"
    assert entry["session_id"] == "sess-1"
    assert entry["error"] == "function_call_forbidden"


@pytest.mark.parametrize(
    "status",
    [
        "ok",
        "validator_rejected",
        "auth_error",
        "http_error",
        "parse_error",
        "rate_limited",
        "timeout",
    ],
)
def test_record_call_accepts_all_documented_statuses(status: str) -> None:
    """The taxonomy is documented in the module docstring and migration."""
    with patch(
        "piilot_pack_sap.audit.repository.insert_audit_log",
        return_value="x",
    ) as mock_insert:
        audit.record_call(company_id="c", tool_id="t", odata_url="/u", status=status)
    assert mock_insert.call_args[0][0]["status"] == status
