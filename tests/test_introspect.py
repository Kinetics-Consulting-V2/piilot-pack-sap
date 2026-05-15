"""Tests for ``piilot_pack_sap.introspect`` — OData ``$metadata`` parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from piilot_pack_sap.introspect import (
    EntitySet,
    IntrospectError,
    NavigationProperty,
    Property,
    SchemaSnapshot,
    parse_metadata,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------- v2 — real SAP $metadata fixture (Business Partner sandbox) ----------


@pytest.fixture(scope="module")
def bp_v2_metadata() -> bytes:
    return (FIXTURES / "metadata_business_partner_v2.xml").read_bytes()


@pytest.fixture(scope="module")
def bp_v2_snapshot(bp_v2_metadata: bytes) -> SchemaSnapshot:
    return parse_metadata(bp_v2_metadata)


def test_v2_detects_version(bp_v2_snapshot: SchemaSnapshot) -> None:
    assert bp_v2_snapshot.version == "v2"


def test_v2_namespace_is_bp_api(bp_v2_snapshot: SchemaSnapshot) -> None:
    assert bp_v2_snapshot.namespace == "API_BUSINESS_PARTNER"


def test_v2_lists_all_entity_sets(bp_v2_snapshot: SchemaSnapshot) -> None:
    # Sandbox publishes 65 EntitySets for the Business Partner API.
    assert len(bp_v2_snapshot.entity_sets) == 65


def test_v2_business_partner_entity_set(bp_v2_snapshot: SchemaSnapshot) -> None:
    bp = bp_v2_snapshot.find("A_BusinessPartner")
    assert bp is not None
    assert bp.entity_type.endswith(".A_BusinessPartnerType")
    assert "BusinessPartner" in bp.key
    # Spot-check a handful of properties expected in the BP schema.
    prop_names = {p.name for p in bp.properties}
    assert {
        "BusinessPartner",
        "FirstName",
        "LastName",
        "BusinessPartnerFullName",
        "CreationDate",
    }.issubset(prop_names)


def test_v2_property_types_are_extracted(bp_v2_snapshot: SchemaSnapshot) -> None:
    bp = bp_v2_snapshot.find("A_BusinessPartner")
    assert bp is not None
    by_name = {p.name: p for p in bp.properties}
    assert by_name["BusinessPartner"].type == "Edm.String"
    # SAP marks the key as non-nullable.
    assert by_name["BusinessPartner"].nullable is False
    # MaxLength is captured for string columns when SAP publishes it.
    assert by_name["BusinessPartner"].max_length is not None
    assert by_name["BusinessPartner"].max_length > 0


def test_v2_sap_annotations_are_captured(bp_v2_snapshot: SchemaSnapshot) -> None:
    bp = bp_v2_snapshot.find("A_BusinessPartner")
    assert bp is not None
    by_name = {p.name: p for p in bp.properties}
    # At least one property must expose a SAP label (the SAP gateway always
    # emits sap:label on user-facing columns in the BP API).
    labels = [p.sap_label for p in bp.properties if p.sap_label]
    assert labels, "expected at least one sap:label annotation on BP properties"
    # CreationDate is technical: SAP typically marks it non-updatable. The
    # parser must default to True when the annotation is absent and respect
    # explicit values when present.
    assert isinstance(by_name["CreationDate"].sap_updatable, bool)


def test_v2_navigations_use_relationship_style(bp_v2_snapshot: SchemaSnapshot) -> None:
    bp = bp_v2_snapshot.find("A_BusinessPartner")
    assert bp is not None
    # The BP entity has navigations such as to_BusinessPartnerAddress.
    nav_names = {n.name for n in bp.navigations}
    assert any(name.startswith("to_") for name in nav_names)
    # v2 navigations carry Relationship/FromRole/ToRole, not a v4 Type.
    sample = next(iter(bp.navigations))
    assert sample.relationship is not None
    assert sample.target_entity_type is None
    assert sample.multiplicity is None


# ---------- v4 — small inline fixture (no real SAP v4 sandbox endpoint yet) ----


V4_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="com.example.Demo" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="OrderType">
        <Key>
          <PropertyRef Name="OrderID"/>
        </Key>
        <Property Name="OrderID" Type="Edm.String" Nullable="false" MaxLength="10"/>
        <Property Name="Amount" Type="Edm.Decimal" Precision="15" Scale="2"/>
        <Property Name="CreatedAt" Type="Edm.DateTimeOffset"/>
        <NavigationProperty Name="Items" Type="Collection(com.example.Demo.OrderItemType)"/>
        <NavigationProperty Name="Customer" Type="com.example.Demo.CustomerType"/>
      </EntityType>
      <EntityType Name="OrderItemType">
        <Key>
          <PropertyRef Name="ItemID"/>
        </Key>
        <Property Name="ItemID" Type="Edm.String" Nullable="false"/>
      </EntityType>
      <EntityType Name="CustomerType">
        <Key>
          <PropertyRef Name="CustomerID"/>
        </Key>
        <Property Name="CustomerID" Type="Edm.String" Nullable="false"/>
      </EntityType>
      <EntityContainer Name="DemoContainer">
        <EntitySet Name="Orders" EntityType="com.example.Demo.OrderType"/>
        <EntitySet Name="OrderItems" EntityType="com.example.Demo.OrderItemType"/>
        <EntitySet Name="Customers" EntityType="com.example.Demo.CustomerType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def test_v4_detects_version() -> None:
    snap = parse_metadata(V4_FIXTURE)
    assert snap.version == "v4"
    assert snap.namespace == "com.example.Demo"


def test_v4_parses_entity_sets() -> None:
    snap = parse_metadata(V4_FIXTURE)
    names = {es.name for es in snap.entity_sets}
    assert names == {"Orders", "OrderItems", "Customers"}


def test_v4_parses_property_facets() -> None:
    snap = parse_metadata(V4_FIXTURE)
    orders = snap.find("Orders")
    assert orders is not None
    by_name = {p.name: p for p in orders.properties}
    assert by_name["OrderID"].type == "Edm.String"
    assert by_name["OrderID"].nullable is False
    assert by_name["OrderID"].max_length == 10
    assert by_name["Amount"].type == "Edm.Decimal"
    assert by_name["Amount"].precision == 15
    assert by_name["Amount"].scale == 2


def test_v4_navigations_use_type_style() -> None:
    snap = parse_metadata(V4_FIXTURE)
    orders = snap.find("Orders")
    assert orders is not None
    by_name = {n.name: n for n in orders.navigations}
    assert by_name["Items"].multiplicity == "*"
    assert by_name["Items"].target_entity_type == "OrderItemType"
    assert by_name["Customer"].multiplicity == "0..1"
    assert by_name["Customer"].target_entity_type == "CustomerType"


# ---------- Error paths ----------


def test_invalid_xml_raises() -> None:
    with pytest.raises(IntrospectError, match="Invalid XML"):
        parse_metadata("<not closed")


def test_unknown_namespace_raises() -> None:
    payload = '<root xmlns="http://example.com/not-odata"/>'
    with pytest.raises(IntrospectError, match="Unknown OData edmx namespace"):
        parse_metadata(payload)


def test_no_schema_raises() -> None:
    payload = (
        '<edmx:Edmx Version="4.0" '
        'xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">'
        "<edmx:DataServices/>"
        "</edmx:Edmx>"
    )
    with pytest.raises(IntrospectError, match="No <Schema> element"):
        parse_metadata(payload)


def test_find_returns_none_for_unknown_entity_set() -> None:
    snap = parse_metadata(V4_FIXTURE)
    assert snap.find("Nonexistent") is None


def test_models_are_immutable() -> None:
    snap = parse_metadata(V4_FIXTURE)
    orders = snap.find("Orders")
    assert orders is not None
    with pytest.raises(Exception):
        # Pydantic v2 with model_config frozen=True raises ValidationError
        # when mutating a model instance.
        orders.name = "Hacked"  # type: ignore[misc]
