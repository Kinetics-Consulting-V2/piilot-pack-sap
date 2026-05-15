"""Persist a parsed ``$metadata`` snapshot into ``integrations_sap.schema_snapshot``.

Bridges the :mod:`piilot_pack_sap.introspect` typed snapshot with the SQL
repository. This is the cache that downstream agent tools (Phase 2) hit on
every ``sap_describe_entity`` call — the host re-fetches ``$metadata`` from
SAP only on explicit re-sync.
"""

from __future__ import annotations

from piilot_pack_sap import repository
from piilot_pack_sap.introspect import EntitySet, SchemaSnapshot


def persist_schema_snapshot(
    *,
    connection_id: str,
    company_id: str,
    service_path: str,
    snapshot: SchemaSnapshot,
) -> int:
    """Upsert one row per EntitySet in ``integrations_sap.schema_snapshot``.

    Returns the number of rows touched (insert + update combined). The unique
    key on the table is ``(connection_id, service_path, entity_set_name)`` so
    re-syncing the same connection refreshes the payload in place.
    """
    entries = [_to_entry(es) for es in snapshot.entity_sets]
    return repository.upsert_schema_snapshot(
        connection_id=connection_id,
        company_id=company_id,
        service_path=service_path,
        entries=entries,
    )


def _to_entry(entity_set: EntitySet) -> repository.SnapshotEntry:
    """Convert a typed :class:`EntitySet` to the dict shape the repo expects.

    The ``payload`` JSONB column carries the full serialised entity set so
    downstream consumers (tools, UI browser) don't need to re-parse XML.
    """
    label = _extract_label(entity_set)
    description = _extract_description(entity_set)
    return {
        "entity_set_name": entity_set.name,
        "label": label,
        "description": description,
        "payload": _serialise(entity_set),
    }


def _extract_label(entity_set: EntitySet) -> str | None:
    """Use the entity-type local name as a fallback label.

    SAP gateways sometimes attach ``sap:label`` on the EntitySet itself, but
    parsing that is out of scope for the v1 introspector. We derive a
    reasonable default from the technical type so the UI has something to
    show before a human curates the label.
    """
    qualified = entity_set.entity_type
    if not qualified:
        return None
    return qualified.rsplit(".", 1)[-1]


def _extract_description(entity_set: EntitySet) -> str | None:
    """Build a one-line description from the top SAP property labels.

    Used as the human-readable summary stored in
    ``integrations_sap.schema_snapshot.description``. Keep it short — the
    KB seeder (cf. ``kb_seeder.py``) produces a richer text for embeddings.
    """
    labelled = [
        f"{p.name}: {p.sap_label}"
        for p in entity_set.properties
        if p.sap_label
    ][:3]
    if not labelled:
        return None
    return " · ".join(labelled)


def _serialise(entity_set: EntitySet) -> dict:
    """Convert the immutable Pydantic model to a JSON-able dict."""
    return {
        "name": entity_set.name,
        "entity_type": entity_set.entity_type,
        "key": list(entity_set.key),
        "properties": [
            {
                "name": p.name,
                "type": p.type,
                "nullable": p.nullable,
                "max_length": p.max_length,
                "precision": p.precision,
                "scale": p.scale,
                "sap_label": p.sap_label,
                "sap_filterable": p.sap_filterable,
                "sap_sortable": p.sap_sortable,
                "sap_creatable": p.sap_creatable,
                "sap_updatable": p.sap_updatable,
                "sap_semantics": p.sap_semantics,
            }
            for p in entity_set.properties
        ],
        "navigations": [
            {
                "name": n.name,
                "target_entity_type": n.target_entity_type,
                "multiplicity": n.multiplicity,
                "relationship": n.relationship,
                "from_role": n.from_role,
                "to_role": n.to_role,
            }
            for n in entity_set.navigations
        ],
    }


__all__ = ["persist_schema_snapshot"]
