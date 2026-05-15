"""OData ``$metadata`` parser — supports v2 (SAP legacy ADO XML) and v4 (OASIS).

The parser converts the raw ``$metadata`` XML payload exposed by an SAP
S/4HANA OData service into a structured :class:`SchemaSnapshot` that downstream
components (validator, query builder, KB seeder) can rely on without ever
re-parsing XML.

XML parsing goes through :mod:`defusedxml` to neutralize XXE / billion-laughs
style payloads — SAP ``$metadata`` files are produced server-side and trusted,
but the parser is also exposed to plugin authors via tools so we keep the
hardening regardless.
"""

from __future__ import annotations

from typing import Literal
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as DET
from pydantic import BaseModel, ConfigDict

NS_EDMX_V2 = "http://schemas.microsoft.com/ado/2007/06/edmx"
NS_EDMX_V4 = "http://docs.oasis-open.org/odata/ns/edmx"
NS_EDM_V2 = "http://schemas.microsoft.com/ado/2008/09/edm"
NS_EDM_V4 = "http://docs.oasis-open.org/odata/ns/edm"
NS_SAP = "http://www.sap.com/Protocols/SAPData"

ODataVersion = Literal["v2", "v4"]
Multiplicity = Literal["1", "0..1", "*"]


class IntrospectError(Exception):
    """Raised when a ``$metadata`` payload cannot be parsed."""


class Property(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    nullable: bool = True
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    sap_label: str | None = None
    sap_filterable: bool = True
    sap_sortable: bool = True
    sap_creatable: bool = True
    sap_updatable: bool = True
    sap_semantics: str | None = None


class NavigationProperty(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    target_entity_type: str | None = None
    multiplicity: Multiplicity | None = None
    relationship: str | None = None
    from_role: str | None = None
    to_role: str | None = None


class EntitySet(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    entity_type: str
    key: tuple[str, ...] = ()
    properties: tuple[Property, ...] = ()
    navigations: tuple[NavigationProperty, ...] = ()


class SchemaSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: ODataVersion
    namespace: str
    entity_sets: tuple[EntitySet, ...] = ()

    def find(self, entity_set_name: str) -> EntitySet | None:
        for es in self.entity_sets:
            if es.name == entity_set_name:
                return es
        return None


def parse_metadata(xml_content: str | bytes) -> SchemaSnapshot:
    """Parse a SAP OData ``$metadata`` XML payload.

    Auto-detects OData version from the root namespace (``edmx`` Microsoft ADO
    for v2, OASIS for v4) and returns a typed snapshot. Raises
    :class:`IntrospectError` on any malformed input.
    """
    try:
        root: Element = DET.fromstring(xml_content)
    except DET.ParseError as exc:
        raise IntrospectError(f"Invalid XML: {exc}") from exc

    version, edm_ns = _detect_version(root.tag)
    schema_elem = _find_first(root, edm_ns, "Schema")
    if schema_elem is None:
        raise IntrospectError("No <Schema> element found in $metadata")

    namespace = schema_elem.get("Namespace") or ""
    entity_types = _index_entity_types(schema_elem, edm_ns, version)
    entity_sets = _collect_entity_sets(schema_elem, edm_ns, entity_types)

    return SchemaSnapshot(
        version=version,
        namespace=namespace,
        entity_sets=tuple(entity_sets),
    )


def _detect_version(root_tag: str) -> tuple[ODataVersion, str]:
    if root_tag.startswith(f"{{{NS_EDMX_V2}}}"):
        return "v2", NS_EDM_V2
    if root_tag.startswith(f"{{{NS_EDMX_V4}}}"):
        return "v4", NS_EDM_V4
    raise IntrospectError(
        f"Unknown OData edmx namespace in root element: {root_tag!r}"
    )


def _find_first(root: Element, edm_ns: str, local_name: str) -> Element | None:
    for elem in root.iter(f"{{{edm_ns}}}{local_name}"):
        return elem
    return None


def _index_entity_types(
    schema_elem: Element,
    edm_ns: str,
    version: ODataVersion,
) -> dict[str, dict]:
    """Return ``{EntityTypeName: {key, properties, navigations}}``."""
    index: dict[str, dict] = {}
    for et in schema_elem.findall(f"{{{edm_ns}}}EntityType"):
        name = et.get("Name") or ""
        if not name:
            continue
        keys: list[str] = []
        key_elem = et.find(f"{{{edm_ns}}}Key")
        if key_elem is not None:
            for pref in key_elem.findall(f"{{{edm_ns}}}PropertyRef"):
                pname = pref.get("Name")
                if pname:
                    keys.append(pname)
        props = tuple(
            _parse_property(p) for p in et.findall(f"{{{edm_ns}}}Property")
        )
        navs = tuple(
            _parse_navigation(n, version)
            for n in et.findall(f"{{{edm_ns}}}NavigationProperty")
        )
        index[name] = {
            "key": tuple(keys),
            "properties": props,
            "navigations": navs,
        }
    return index


def _collect_entity_sets(
    schema_elem: Element,
    edm_ns: str,
    entity_types: dict[str, dict],
) -> list[EntitySet]:
    sets: list[EntitySet] = []
    for container in schema_elem.findall(f"{{{edm_ns}}}EntityContainer"):
        for es in container.findall(f"{{{edm_ns}}}EntitySet"):
            es_name = es.get("Name") or ""
            et_qualified = es.get("EntityType") or ""
            et_local = et_qualified.rsplit(".", 1)[-1]
            et_data = entity_types.get(et_local, {})
            sets.append(
                EntitySet(
                    name=es_name,
                    entity_type=et_qualified,
                    key=et_data.get("key", ()),
                    properties=et_data.get("properties", ()),
                    navigations=et_data.get("navigations", ()),
                )
            )
    return sets


def _parse_property(p: Element) -> Property:
    return Property(
        name=p.get("Name") or "",
        type=p.get("Type") or "Edm.String",
        nullable=_bool_attr(p, "Nullable", default=True),
        max_length=_int_attr(p, "MaxLength"),
        precision=_int_attr(p, "Precision"),
        scale=_int_attr(p, "Scale"),
        sap_label=p.get(f"{{{NS_SAP}}}label"),
        sap_filterable=_bool_sap_attr(p, "filterable", default=True),
        sap_sortable=_bool_sap_attr(p, "sortable", default=True),
        sap_creatable=_bool_sap_attr(p, "creatable", default=True),
        sap_updatable=_bool_sap_attr(p, "updatable", default=True),
        sap_semantics=p.get(f"{{{NS_SAP}}}semantics"),
    )


def _parse_navigation(n: Element, version: ODataVersion) -> NavigationProperty:
    name = n.get("Name") or ""
    if version == "v2":
        return NavigationProperty(
            name=name,
            relationship=n.get("Relationship"),
            from_role=n.get("FromRole"),
            to_role=n.get("ToRole"),
        )

    type_attr = n.get("Type") or ""
    if type_attr.startswith("Collection(") and type_attr.endswith(")"):
        target = type_attr[len("Collection(") : -1]
        multiplicity: Multiplicity = "*"
    else:
        target = type_attr
        multiplicity = "0..1"
    target_local = target.rsplit(".", 1)[-1] if target else None
    return NavigationProperty(
        name=name,
        target_entity_type=target_local,
        multiplicity=multiplicity,
    )


def _bool_attr(elem: Element, attr: str, *, default: bool) -> bool:
    raw = elem.get(attr)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _bool_sap_attr(elem: Element, local: str, *, default: bool) -> bool:
    raw = elem.get(f"{{{NS_SAP}}}{local}")
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def _int_attr(elem: Element, attr: str) -> int | None:
    raw = elem.get(attr)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


__all__ = [
    "IntrospectError",
    "Property",
    "NavigationProperty",
    "EntitySet",
    "SchemaSnapshot",
    "parse_metadata",
]
