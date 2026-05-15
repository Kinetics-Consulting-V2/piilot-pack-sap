"""Tests for ``piilot_pack_sap.snapshot_service``."""

from __future__ import annotations

from unittest.mock import patch

from piilot_pack_sap.introspect import parse_metadata
from piilot_pack_sap.snapshot_service import persist_schema_snapshot

V4_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="com.example.Demo" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="OrderType">
        <Key>
          <PropertyRef Name="OrderID"/>
        </Key>
        <Property Name="OrderID" Type="Edm.String" Nullable="false"/>
        <Property Name="Amount" Type="Edm.Decimal" Precision="15" Scale="2"/>
      </EntityType>
      <EntityContainer Name="C">
        <EntitySet Name="Orders" EntityType="com.example.Demo.OrderType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def test_persist_serialises_each_entity_set_and_calls_repo() -> None:
    snapshot = parse_metadata(V4_FIXTURE)
    with patch(
        "piilot_pack_sap.snapshot_service.repository.upsert_schema_snapshot",
        return_value=1,
    ) as mock_upsert:
        rows = persist_schema_snapshot(
            connection_id="conn-1",
            company_id="comp-1",
            service_path="/odata4/sap/demo",
            snapshot=snapshot,
        )

    assert rows == 1
    assert mock_upsert.call_count == 1
    kwargs = mock_upsert.call_args.kwargs
    assert kwargs["connection_id"] == "conn-1"
    assert kwargs["company_id"] == "comp-1"
    assert kwargs["service_path"] == "/odata4/sap/demo"
    entries = list(kwargs["entries"])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entity_set_name"] == "Orders"
    # Label derived from the local type name (no sap:label in the fixture).
    assert entry["label"] == "OrderType"
    payload = entry["payload"]
    assert payload["name"] == "Orders"
    assert payload["entity_type"].endswith(".OrderType")
    assert payload["key"] == ["OrderID"]
    assert [p["name"] for p in payload["properties"]] == ["OrderID", "Amount"]
    # Decimal facets propagate to the JSON payload.
    amount = next(p for p in payload["properties"] if p["name"] == "Amount")
    assert amount["precision"] == 15
    assert amount["scale"] == 2


def test_persist_handles_empty_snapshot() -> None:
    empty_xml = (
        '<edmx:Edmx Version="4.0" '
        'xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">'
        '<edmx:DataServices>'
        '<Schema Namespace="x" xmlns="http://docs.oasis-open.org/odata/ns/edm"/>'
        '</edmx:DataServices></edmx:Edmx>'
    )
    snapshot = parse_metadata(empty_xml)
    with patch(
        "piilot_pack_sap.snapshot_service.repository.upsert_schema_snapshot",
        return_value=0,
    ) as mock_upsert:
        rows = persist_schema_snapshot(
            connection_id="c",
            company_id="co",
            service_path="/x",
            snapshot=snapshot,
        )
    assert rows == 0
    assert list(mock_upsert.call_args.kwargs["entries"]) == []


def test_persist_pulls_description_from_sap_labels() -> None:
    fixture = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="ns" xmlns="http://schemas.microsoft.com/ado/2008/09/edm" xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <EntityType Name="BPType">
        <Key><PropertyRef Name="ID"/></Key>
        <Property Name="ID" Type="Edm.String" Nullable="false"/>
        <Property Name="Name" Type="Edm.String" sap:label="Full name"/>
        <Property Name="Email" Type="Edm.String" sap:label="Email address"/>
      </EntityType>
      <EntityContainer Name="C"><EntitySet Name="BPs" EntityType="ns.BPType"/></EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    snapshot = parse_metadata(fixture)
    with patch(
        "piilot_pack_sap.snapshot_service.repository.upsert_schema_snapshot",
        return_value=1,
    ) as mock_upsert:
        persist_schema_snapshot(
            connection_id="c",
            company_id="co",
            service_path="/sap",
            snapshot=snapshot,
        )
    entries = list(mock_upsert.call_args.kwargs["entries"])
    desc = entries[0]["description"]
    assert "Full name" in desc
    assert "Email address" in desc


def test_persist_propagates_navigation_metadata() -> None:
    fixture = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="ns" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="ParentType">
        <Key><PropertyRef Name="Id"/></Key>
        <Property Name="Id" Type="Edm.String" Nullable="false"/>
        <NavigationProperty Name="Items" Type="Collection(ns.ChildType)"/>
      </EntityType>
      <EntityType Name="ChildType">
        <Key><PropertyRef Name="ChildId"/></Key>
        <Property Name="ChildId" Type="Edm.String" Nullable="false"/>
      </EntityType>
      <EntityContainer Name="C">
        <EntitySet Name="Parents" EntityType="ns.ParentType"/>
        <EntitySet Name="Children" EntityType="ns.ChildType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    snapshot = parse_metadata(fixture)
    with patch(
        "piilot_pack_sap.snapshot_service.repository.upsert_schema_snapshot",
        return_value=2,
    ) as mock_upsert:
        persist_schema_snapshot(
            connection_id="c",
            company_id="co",
            service_path="/ns",
            snapshot=snapshot,
        )
    entries = list(mock_upsert.call_args.kwargs["entries"])
    parent = next(e for e in entries if e["entity_set_name"] == "Parents")
    nav = parent["payload"]["navigations"][0]
    assert nav["name"] == "Items"
    assert nav["multiplicity"] == "*"
    assert nav["target_entity_type"] == "ChildType"
