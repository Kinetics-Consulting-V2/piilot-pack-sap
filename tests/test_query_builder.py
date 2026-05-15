"""Tests for ``piilot_pack_sap.query_builder``."""

from __future__ import annotations

import pytest

from piilot_pack_sap.odata_validator import ValidationError
from piilot_pack_sap.query_builder import ODataQuery

BASE_V2 = "/sap/opu/odata/sap/API_BUSINESS_PARTNER"


def test_minimal_query_emits_format_only() -> None:
    q = ODataQuery(entity_set="A_BusinessPartner")
    path, params = q.build_url(BASE_V2, version="v2")
    assert path == f"{BASE_V2}/A_BusinessPartner"
    assert params == {"$format": "json"}


def test_select_projects_properties() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        select=("BusinessPartner", "FirstName", "LastName"),
    )
    _, params = q.build_url(BASE_V2)
    assert params["$select"] == "BusinessPartner,FirstName,LastName"


def test_filter_and_top() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        filter="FirstName eq 'John'",
        top=50,
    )
    _, params = q.build_url(BASE_V2)
    assert params["$filter"] == "FirstName eq 'John'"
    assert params["$top"] == "50"


def test_order_by_serializes_pairs() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        order_by=(("LastName", "asc"), ("FirstName", "desc")),
    )
    _, params = q.build_url(BASE_V2)
    assert params["$orderby"] == "LastName asc,FirstName desc"


def test_skip_pagination() -> None:
    q = ODataQuery(entity_set="A_BusinessPartner", top=20, skip=40)
    _, params = q.build_url(BASE_V2)
    assert params["$top"] == "20"
    assert params["$skip"] == "40"


def test_count_v2_uses_path_segment() -> None:
    q = ODataQuery(entity_set="A_BusinessPartner", count=True)
    path, params = q.build_url(BASE_V2, version="v2")
    assert path.endswith("/A_BusinessPartner/$count")
    assert "$count" not in params


def test_count_v2_with_filter_kept() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        filter="Customer eq '11'",
        count=True,
    )
    path, params = q.build_url(BASE_V2, version="v2")
    assert path.endswith("/A_BusinessPartner/$count")
    assert params["$filter"] == "Customer eq '11'"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"select": ("FirstName",)},
        {"order_by": (("FirstName", "asc"),)},
        {"top": 10},
        {"skip": 5},
        {"apply": "aggregate(Amount with sum as Total)"},
    ],
)
def test_count_v2_rejects_other_options(kwargs: dict) -> None:
    q = ODataQuery(entity_set="A_BusinessPartner", count=True, **kwargs)
    with pytest.raises(ValidationError) as exc:
        q.build_url(BASE_V2, version="v2")
    assert exc.value.code == "count_v2_extra_options"


def test_count_v4_inline() -> None:
    q = ODataQuery(entity_set="Orders", count=True, top=10)
    path, params = q.build_url("/odata4/sap/demo", version="v4")
    assert path.endswith("/Orders")
    assert params["$count"] == "true"
    assert params["$top"] == "10"


def test_apply_aggregate_v4() -> None:
    q = ODataQuery(
        entity_set="Orders",
        apply="aggregate(Amount with sum as Total)",
    )
    _, params = q.build_url("/odata4/sap/demo", version="v4")
    assert params["$apply"] == "aggregate(Amount with sum as Total)"


def test_format_can_be_disabled() -> None:
    q = ODataQuery(entity_set="A_BusinessPartner", format=None)
    _, params = q.build_url(BASE_V2)
    assert "$format" not in params


def test_invalid_filter_propagates_validation_error() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        filter="contains(Name, 'foo')",
    )
    with pytest.raises(ValidationError) as exc:
        q.build_url(BASE_V2)
    assert exc.value.code == "function_call_forbidden"


def test_invalid_top_propagates_validation_error() -> None:
    q = ODataQuery(entity_set="A_BusinessPartner", top=99999)
    with pytest.raises(ValidationError) as exc:
        q.build_url(BASE_V2, max_top=1000)
    assert exc.value.code == "top_exceeds_max"


@pytest.mark.parametrize(
    "bad_entity_set",
    ["", "A/B", "A.B", "A B", "1Numeric", "DROP TABLE", "A;"],
)
def test_entity_set_must_be_simple_identifier(bad_entity_set: str) -> None:
    q = ODataQuery(entity_set=bad_entity_set)
    with pytest.raises(ValidationError) as exc:
        q.build_url(BASE_V2)
    assert exc.value.code == "invalid_entity_set"


def test_base_path_trailing_slash_handled() -> None:
    q = ODataQuery(entity_set="A_BusinessPartner")
    path, _ = q.build_url(BASE_V2 + "/")
    assert path == f"{BASE_V2}/A_BusinessPartner"


def test_allowed_properties_propagated_to_validator() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        select=("FirstName", "Phantom"),
    )
    with pytest.raises(ValidationError) as exc:
        q.build_url(BASE_V2, allowed_properties={"FirstName"})
    assert exc.value.code == "unknown_property"


def test_immutable_dataclass() -> None:
    from dataclasses import FrozenInstanceError

    q = ODataQuery(entity_set="A_BusinessPartner")
    with pytest.raises(FrozenInstanceError):
        q.entity_set = "Hacked"  # type: ignore[misc]


def test_full_realistic_v2_query() -> None:
    q = ODataQuery(
        entity_set="A_BusinessPartner",
        select=("BusinessPartner", "BusinessPartnerFullName", "CreationDate"),
        filter=(
            "BusinessPartnerCategory eq '2' and CreationDate ge "
            "datetime'2026-01-01T00:00:00'"
        ),
        order_by=(("CreationDate", "desc"),),
        top=100,
        skip=0,
    )
    path, params = q.build_url(BASE_V2, version="v2")
    assert path == f"{BASE_V2}/A_BusinessPartner"
    assert set(params.keys()) == {
        "$select",
        "$filter",
        "$orderby",
        "$top",
        "$skip",
        "$format",
    }


def test_full_realistic_v4_aggregation() -> None:
    q = ODataQuery(
        entity_set="Orders",
        filter="Year ge 2026",
        apply="aggregate(Amount with sum as Total, Amount with avg as Mean)",
        count=True,
    )
    path, params = q.build_url("/odata4/sap/demo", version="v4")
    assert path == "/odata4/sap/demo/Orders"
    assert params["$apply"].startswith("aggregate(Amount with sum")
    assert params["$count"] == "true"
