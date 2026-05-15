"""Tests for ``piilot_pack_sap.kb_seeder``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from piilot_pack_sap.introspect import parse_metadata
from piilot_pack_sap.kb_seeder import (
    DESCRIPTION_PROPERTY_CAP,
    KB_COLUMNS,
    _build_description,
    _build_row_data,
    seed_metadata_kb,
)


SIMPLE_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="ns" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="OrderType">
        <Key><PropertyRef Name="Id"/></Key>
        <Property Name="Id" Type="Edm.String" Nullable="false"/>
        <Property Name="Amount" Type="Edm.Decimal"/>
      </EntityType>
      <EntityContainer Name="C">
        <EntitySet Name="Orders" EntityType="ns.OrderType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


@pytest.fixture
def snapshot():
    return parse_metadata(SIMPLE_FIXTURE)


# ---------- First seed (KB does not exist yet) ------------------------------


def test_first_seed_creates_kb_and_columns(snapshot) -> None:
    with (
        patch("piilot_pack_sap.kb_seeder.find_kb", return_value=None) as mock_find,
        patch(
            "piilot_pack_sap.kb_seeder.create_kb", return_value={"id": "kb-1"}
        ) as mock_create,
        patch("piilot_pack_sap.kb_seeder.add_column") as mock_add_col,
        patch("piilot_pack_sap.kb_seeder.find_rows") as mock_find_rows,
        patch(
            "piilot_pack_sap.kb_seeder.insert_batch", return_value=[{"id": "r1"}]
        ) as mock_insert,
        patch("piilot_pack_sap.kb_seeder.update_row") as mock_update,
    ):
        result = seed_metadata_kb(
            company_id="comp-1",
            connection_label="Sandbox",
            snapshot=snapshot,
        )

    assert result["kb_id"] == "kb-1"
    assert result["created"] is True
    assert result["inserted"] == 1
    assert result["updated"] == 0
    assert result["total"] == 1

    mock_find.assert_called_once_with(company_id="comp-1", name="SAP Metadata — Sandbox")
    mock_create.assert_called_once()
    create_kwargs = mock_create.call_args.kwargs
    assert create_kwargs["company_id"] == "comp-1"
    assert create_kwargs["name"] == "SAP Metadata — Sandbox"
    assert create_kwargs["schema_locked"] is True
    # All 5 columns are created in order.
    assert mock_add_col.call_count == len(KB_COLUMNS)
    for call, expected in zip(mock_add_col.call_args_list, KB_COLUMNS):
        assert call.args[0] == "kb-1"
        assert call.kwargs["name"] == expected["name"]
        assert call.kwargs["column_type"] == expected["column_type"]
        assert call.kwargs["position"] == expected["position"]
    # No find_rows / update_row when the KB is freshly created.
    mock_find_rows.assert_not_called()
    mock_update.assert_not_called()
    # insert_batch carries the single entity set.
    inserted_rows = mock_insert.call_args[0][1]
    assert len(inserted_rows) == 1
    assert inserted_rows[0]["data"]["entity_set_name"] == "Orders"
    assert inserted_rows[0]["data"]["entity_type"].endswith(".OrderType")
    assert inserted_rows[0]["data"]["key_fields"] == "Id"
    assert inserted_rows[0]["data"]["properties_count"] == 2


# ---------- Re-sync (KB exists with overlapping entities) -------------------


def test_resync_updates_known_and_inserts_new(snapshot) -> None:
    existing_rows = [
        {
            "id": "row-old",
            "data": {"entity_set_name": "Orders", "properties_count": 1},
        }
    ]
    with (
        patch(
            "piilot_pack_sap.kb_seeder.find_kb", return_value={"id": "kb-1"}
        ),
        patch("piilot_pack_sap.kb_seeder.create_kb") as mock_create,
        patch("piilot_pack_sap.kb_seeder.add_column") as mock_add_col,
        patch(
            "piilot_pack_sap.kb_seeder.find_rows", return_value=existing_rows
        ),
        patch(
            "piilot_pack_sap.kb_seeder.insert_batch", return_value=[]
        ) as mock_insert,
        patch("piilot_pack_sap.kb_seeder.update_row") as mock_update,
    ):
        result = seed_metadata_kb(
            company_id="comp-1",
            connection_label="Sandbox",
            snapshot=snapshot,
        )

    assert result["created"] is False
    assert result["updated"] == 1
    assert result["inserted"] == 0
    mock_create.assert_not_called()
    mock_add_col.assert_not_called()
    mock_update.assert_called_once()
    # Update payload should be the freshly built data (properties_count = 2 now).
    update_args = mock_update.call_args[0]
    assert update_args[0] == "row-old"
    assert update_args[1]["entity_set_name"] == "Orders"
    assert update_args[1]["properties_count"] == 2
    mock_insert.assert_not_called()


def test_resync_inserts_brand_new_entity_sets() -> None:
    fixture = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="ns" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="OrderType">
        <Key><PropertyRef Name="Id"/></Key>
        <Property Name="Id" Type="Edm.String" Nullable="false"/>
      </EntityType>
      <EntityType Name="InvoiceType">
        <Key><PropertyRef Name="Num"/></Key>
        <Property Name="Num" Type="Edm.String" Nullable="false"/>
      </EntityType>
      <EntityContainer Name="C">
        <EntitySet Name="Orders" EntityType="ns.OrderType"/>
        <EntitySet Name="Invoices" EntityType="ns.InvoiceType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    snap = parse_metadata(fixture)
    existing_rows = [
        {"id": "row-1", "data": {"entity_set_name": "Orders"}}
    ]
    with (
        patch("piilot_pack_sap.kb_seeder.find_kb", return_value={"id": "kb-1"}),
        patch("piilot_pack_sap.kb_seeder.find_rows", return_value=existing_rows),
        patch(
            "piilot_pack_sap.kb_seeder.insert_batch",
            return_value=[{"id": "new-row"}],
        ) as mock_insert,
        patch("piilot_pack_sap.kb_seeder.update_row") as mock_update,
    ):
        result = seed_metadata_kb(
            company_id="comp-1",
            connection_label="Prod",
            snapshot=snap,
        )

    assert result["updated"] == 1  # Orders
    assert result["inserted"] == 1  # Invoices
    inserted = mock_insert.call_args[0][1]
    assert inserted[0]["data"]["entity_set_name"] == "Invoices"


# ---------- Edge cases ------------------------------------------------------


def test_default_label_when_empty_connection_label() -> None:
    with (
        patch("piilot_pack_sap.kb_seeder.find_kb", return_value=None) as mock_find,
        patch("piilot_pack_sap.kb_seeder.create_kb", return_value={"id": "k"}),
        patch("piilot_pack_sap.kb_seeder.add_column"),
        patch("piilot_pack_sap.kb_seeder.insert_batch", return_value=[]),
    ):
        seed_metadata_kb(
            company_id="c", connection_label="", snapshot=parse_metadata(SIMPLE_FIXTURE)
        )
    assert mock_find.call_args.kwargs["name"] == "SAP Metadata — default"


def test_existing_rows_with_missing_data_field_are_ignored() -> None:
    """Defensive guard: malformed rows in the KB don't crash the seeder."""
    bad_rows = [{"id": "x", "data": {}}, {"id": "y"}]
    with (
        patch("piilot_pack_sap.kb_seeder.find_kb", return_value={"id": "kb-1"}),
        patch("piilot_pack_sap.kb_seeder.find_rows", return_value=bad_rows),
        patch("piilot_pack_sap.kb_seeder.insert_batch", return_value=[{"id": "r"}]),
        patch("piilot_pack_sap.kb_seeder.update_row") as mock_update,
    ):
        result = seed_metadata_kb(
            company_id="c",
            connection_label="x",
            snapshot=parse_metadata(SIMPLE_FIXTURE),
        )
    # No match found, so everything inserts; no updates triggered on bad rows.
    assert result["inserted"] == 1
    assert result["updated"] == 0
    mock_update.assert_not_called()


# ---------- Description / row data helpers ----------------------------------


def test_build_description_includes_entity_name_and_type() -> None:
    snap = parse_metadata(SIMPLE_FIXTURE)
    orders = snap.find("Orders")
    desc = _build_description(orders)
    assert "EntitySet Orders" in desc
    assert "type OrderType" in desc
    assert "Id" in desc
    assert "Amount" in desc
    assert "key: Id" in desc


def test_build_description_caps_property_listing() -> None:
    """Entity sets with > 15 properties get a `+N more` suffix."""
    cols = "\n".join(
        f'<Property Name="P{i}" Type="Edm.String"/>'
        for i in range(20)
    )
    fixture = f"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="ns" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="WideType">
        <Key><PropertyRef Name="P0"/></Key>
        {cols}
      </EntityType>
      <EntityContainer Name="C">
        <EntitySet Name="Wide" EntityType="ns.WideType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    snap = parse_metadata(fixture)
    desc = _build_description(snap.find("Wide"))
    extra = 20 - DESCRIPTION_PROPERTY_CAP
    assert f"+{extra} more" in desc


def test_build_description_includes_sap_label_when_present() -> None:
    fixture = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="ns" xmlns="http://schemas.microsoft.com/ado/2008/09/edm" xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <EntityType Name="BPType">
        <Key><PropertyRef Name="Id"/></Key>
        <Property Name="Id" Type="Edm.String" Nullable="false"/>
        <Property Name="Email" Type="Edm.String" sap:label="Email address"/>
      </EntityType>
      <EntityContainer Name="C">
        <EntitySet Name="BPs" EntityType="ns.BPType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    snap = parse_metadata(fixture)
    desc = _build_description(snap.find("BPs"))
    assert "Email (Email address)" in desc


def test_build_row_data_shape() -> None:
    snap = parse_metadata(SIMPLE_FIXTURE)
    data = _build_row_data(snap.find("Orders"))
    assert set(data.keys()) == {
        "entity_set_name",
        "entity_type",
        "description",
        "key_fields",
        "properties_count",
    }
    assert data["entity_set_name"] == "Orders"
    assert data["properties_count"] == 2
