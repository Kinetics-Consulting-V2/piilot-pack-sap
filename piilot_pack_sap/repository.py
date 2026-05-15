"""Direct SQL repository over the ``integrations_sap`` schema.

All functions are synchronous and rely on :mod:`piilot.sdk.db.cursor` which
threads the RLS user context through the worker thread. Async handlers must
wrap them with ``await run_in_thread(...)``; never call them through
``asyncio.to_thread`` directly (RLS context would be lost).

Three tables are covered (see ``migrations/001_init_sap.sql`` for DDL):

* ``integrations_sap.connections`` — one row per (company, label) tuple.
* ``integrations_sap.schema_snapshot`` — cached ``$metadata`` introspection,
  one row per (connection, service_path, entity_set) tuple. Upserted on
  every sync.
* ``integrations_sap.audit_log`` — append-only trail of every OData call
  performed by an agent tool or HTTP route.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, TypedDict

from piilot.sdk.db import Json, cursor, execute_values


# ---------------------------------------------------------------------------
# Schema-snapshot rows
# ---------------------------------------------------------------------------


class SnapshotEntry(TypedDict, total=False):
    """Input shape for :func:`upsert_schema_snapshot`.

    ``entity_set_name`` is the only mandatory key. ``payload`` is a JSON-able
    dict (typically the serialised :class:`piilot_pack_sap.introspect.EntitySet`)
    that the host stores as JSONB.
    """

    entity_set_name: str
    label: Optional[str]
    description: Optional[str]
    payload: dict[str, Any]


def upsert_schema_snapshot(
    *,
    connection_id: str,
    company_id: str,
    service_path: str,
    entries: Iterable[SnapshotEntry],
) -> int:
    """Insert or update snapshot rows for a connection. Returns row count.

    The unique key is ``(connection_id, service_path, entity_set_name)`` —
    re-syncing the same connection overwrites ``payload`` / ``label`` /
    ``description`` and bumps ``last_synced_at``.
    """
    rows = [
        (
            connection_id,
            company_id,
            entry["entity_set_name"],
            service_path,
            entry.get("label"),
            entry.get("description"),
            Json(entry.get("payload") or {}),
        )
        for entry in entries
    ]
    if not rows:
        return 0
    with cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO integrations_sap.schema_snapshot
                (connection_id, company_id, entity_set_name, service_path,
                 label, description, payload, last_synced_at)
            VALUES %s
            ON CONFLICT (connection_id, service_path, entity_set_name)
            DO UPDATE SET
                label          = EXCLUDED.label,
                description    = EXCLUDED.description,
                payload        = EXCLUDED.payload,
                last_synced_at = now()
            """,
            rows,
            template=(
                "(%s, %s, %s, %s, %s, %s, %s, now())"
            ),
        )
        return cur.rowcount


def list_schema_snapshot(
    *,
    connection_id: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return cached entity sets for a connection, ordered alphabetically."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                id, connection_id, company_id, entity_set_name, service_path,
                label, description, payload, last_synced_at, created_at,
                updated_at
            FROM integrations_sap.schema_snapshot
            WHERE connection_id = %s
            ORDER BY entity_set_name ASC
            LIMIT %s
            """,
            (connection_id, limit),
        )
        return list(cur.fetchall())


def get_snapshot_entry(
    *,
    connection_id: str,
    entity_set_name: str,
) -> Optional[dict[str, Any]]:
    """Fetch a single snapshot row by (connection, entity_set_name)."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                id, connection_id, company_id, entity_set_name, service_path,
                label, description, payload, last_synced_at, created_at,
                updated_at
            FROM integrations_sap.schema_snapshot
            WHERE connection_id = %s AND entity_set_name = %s
            LIMIT 1
            """,
            (connection_id, entity_set_name),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditEntry(TypedDict, total=False):
    """Input shape for :func:`insert_audit_log`.

    ``company_id``, ``tool_id``, ``odata_url`` and ``status`` are mandatory;
    everything else is optional.
    """

    company_id: str
    connection_id: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    tool_id: str
    entity_set: Optional[str]
    odata_url: str
    http_method: str
    status: str
    http_status: Optional[int]
    latency_ms: Optional[int]
    error: Optional[str]
    result_count: Optional[int]


def insert_audit_log(entry: AuditEntry) -> str:
    """Append a row to ``integrations_sap.audit_log`` and return its ID."""
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO integrations_sap.audit_log (
                company_id, connection_id, user_id, session_id, tool_id,
                entity_set, odata_url, http_method, status, http_status,
                latency_ms, error, result_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                entry["company_id"],
                entry.get("connection_id"),
                entry.get("user_id"),
                entry.get("session_id"),
                entry["tool_id"],
                entry.get("entity_set"),
                entry["odata_url"],
                entry.get("http_method", "GET"),
                entry["status"],
                entry.get("http_status"),
                entry.get("latency_ms"),
                entry.get("error"),
                entry.get("result_count"),
            ),
        )
        row = cur.fetchone()
        return str(row["id"])


def list_audit_log(
    *,
    company_id: str,
    limit: int = 100,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return the most recent audit rows for a company (status filter optional)."""
    params: list[Any] = [company_id]
    where = "company_id = %s"
    if status is not None:
        where += " AND status = %s"
        params.append(status)
    params.append(limit)
    with cursor() as cur:
        cur.execute(
            f"""
            SELECT
                id, company_id, connection_id, user_id, session_id, tool_id,
                entity_set, odata_url, http_method, status, http_status,
                latency_ms, error, result_count, created_at
            FROM integrations_sap.audit_log
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return list(cur.fetchall())


__all__ = [
    "AuditEntry",
    "SnapshotEntry",
    "get_snapshot_entry",
    "insert_audit_log",
    "list_audit_log",
    "list_schema_snapshot",
    "upsert_schema_snapshot",
]
