"""Auto-create + populate the plugin-owned KB "SAP Metadata — <connection>".

The KB is materialised on the very first sync of a connection. Every later
sync diffs the new ``$metadata`` against the rows already in the KB and:

* **updates** rows whose ``entity_set_name`` is already present (the entity
  set may have gained / lost properties between SAP releases);
* **inserts** rows for entity sets new since the previous snapshot.

The description column is text-rich on purpose: the host's auto-embedding
pipeline indexes it for the RAG agent (Phase 2 tool ``sap_search_entity``).
Truncation to the first 15 properties keeps the description bounded — a
typical S/4HANA entity has 20-40 properties, the most semantic ones tend
to appear first and that's enough signal for the embedder.

The KB is ``schema_locked=True`` so the schema cannot be tampered with from
the UI: rows live and die with the plugin.
"""

from __future__ import annotations

from typing import TypedDict

from piilot.sdk.knowledge import (
    add_column,
    create_kb,
    find_kb,
    find_rows,
    insert_batch,
    update_row,
)

from piilot_pack_sap.introspect import EntitySet, SchemaSnapshot

KB_NAME_PREFIX = "SAP Metadata"
KB_DESCRIPTION = (
    "OData $metadata introspection cache — one row per EntitySet exposed "
    "by the SAP service. Used by the RAG agent to map natural language "
    "questions to concrete entity sets (sap_search_entity tool)."
)

# Cap on the number of properties listed in the embeddable description.
# 15 covers the bulk of SAP signal without exploding the embedding cost.
DESCRIPTION_PROPERTY_CAP = 15

# Hard limit on rows fetched when diffing existing entries. SAP services
# rarely exceed a few hundred entity sets, but we cap defensively.
FIND_ROWS_LIMIT = 10_000

# Column layout — must stay in lock-step with :func:`_build_row_data`.
KB_COLUMNS: list[dict] = [
    {"name": "entity_set_name", "column_type": "text", "position": 0, "is_required": True},
    {"name": "entity_type", "column_type": "text", "position": 1},
    {"name": "description", "column_type": "text", "position": 2},
    {"name": "key_fields", "column_type": "text", "position": 3},
    {"name": "properties_count", "column_type": "numeric", "position": 4},
]


class SeedResult(TypedDict):
    """Outcome of a single :func:`seed_metadata_kb` call."""

    kb_id: str
    inserted: int
    updated: int
    total: int
    created: bool


def seed_metadata_kb(
    *,
    company_id: str,
    connection_label: str,
    snapshot: SchemaSnapshot,
) -> SeedResult:
    """Create-or-update the "SAP Metadata — <connection_label>" KB.

    Idempotent. Safe to call after every ``$metadata`` re-sync.
    """
    kb_name = _kb_name(connection_label)
    kb = find_kb(company_id=company_id, name=kb_name)
    created = kb is None

    if kb is None:
        kb = create_kb(
            company_id=company_id,
            name=kb_name,
            description=KB_DESCRIPTION,
            schema_locked=True,
        )
        for column in KB_COLUMNS:
            add_column(
                kb["id"],
                name=column["name"],
                column_type=column["column_type"],
                position=column["position"],
                is_required=column.get("is_required", False),
            )
        existing_by_name: dict[str, dict] = {}
    else:
        existing_rows = find_rows(kb_id=kb["id"], filters={}, limit=FIND_ROWS_LIMIT)
        existing_by_name = {
            row["data"]["entity_set_name"]: row
            for row in existing_rows
            if "data" in row and "entity_set_name" in row["data"]
        }

    to_insert: list[dict] = []
    updated = 0
    for entity_set in snapshot.entity_sets:
        data = _build_row_data(entity_set)
        match = existing_by_name.get(entity_set.name)
        if match is not None:
            update_row(match["id"], data)
            updated += 1
        else:
            to_insert.append({"data": data})

    inserted = 0
    if to_insert:
        inserted = len(insert_batch(kb["id"], to_insert))

    return {
        "kb_id": kb["id"],
        "inserted": inserted,
        "updated": updated,
        "total": inserted + updated,
        "created": created,
    }


def _kb_name(connection_label: str) -> str:
    label = (connection_label or "").strip() or "default"
    return f"{KB_NAME_PREFIX} — {label}"


def _build_row_data(entity_set: EntitySet) -> dict:
    """Build a row payload keyed by KB column name.

    The ``description`` column is intentionally rich (sap:label annotations,
    leading properties) so the auto-embedder produces a semantic vector
    that matches natural language queries like "facture" / "achat".
    """
    return {
        "entity_set_name": entity_set.name,
        "entity_type": entity_set.entity_type or "",
        "description": _build_description(entity_set),
        "key_fields": ",".join(entity_set.key),
        "properties_count": len(entity_set.properties),
    }


def _build_description(entity_set: EntitySet) -> str:
    parts: list[str] = [f"EntitySet {entity_set.name}"]
    type_local = entity_set.entity_type.rsplit(".", 1)[-1] if entity_set.entity_type else ""
    if type_local:
        parts.append(f"type {type_local}")

    prop_chunks: list[str] = []
    for prop in entity_set.properties[:DESCRIPTION_PROPERTY_CAP]:
        if prop.sap_label:
            prop_chunks.append(f"{prop.name} ({prop.sap_label})")
        else:
            prop_chunks.append(prop.name)
    if prop_chunks:
        parts.append("properties: " + ", ".join(prop_chunks))
        if len(entity_set.properties) > DESCRIPTION_PROPERTY_CAP:
            extra = len(entity_set.properties) - DESCRIPTION_PROPERTY_CAP
            parts.append(f"+{extra} more")

    if entity_set.key:
        parts.append("key: " + ",".join(entity_set.key))

    return ". ".join(parts)


__all__ = ["KB_COLUMNS", "KB_DESCRIPTION", "KB_NAME_PREFIX", "SeedResult", "seed_metadata_kb"]
