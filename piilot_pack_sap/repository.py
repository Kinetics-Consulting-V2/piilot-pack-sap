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

from collections.abc import Iterable
from typing import Any, TypedDict

from piilot.sdk.db import Json, cursor, execute_values

# ---------------------------------------------------------------------------
# Connections (per-tenant SAP target)
# ---------------------------------------------------------------------------


def list_connections(
    *,
    company_id: str,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """Return SAP connections belonging to the tenant, ordered by recency."""
    with cursor() as cur:
        if active_only:
            cur.execute(
                """
                SELECT
                    id, company_id, plugin_connection_id, label, base_url,
                    auth_mode, is_active, last_health_check_at,
                    last_health_status, last_health_error, created_at,
                    updated_at
                FROM integrations_sap.connections
                WHERE company_id = %s AND is_active = TRUE
                ORDER BY updated_at DESC
                """,
                (company_id,),
            )
        else:
            cur.execute(
                """
                SELECT
                    id, company_id, plugin_connection_id, label, base_url,
                    auth_mode, is_active, last_health_check_at,
                    last_health_status, last_health_error, created_at,
                    updated_at
                FROM integrations_sap.connections
                WHERE company_id = %s
                ORDER BY updated_at DESC
                """,
                (company_id,),
            )
        return list(cur.fetchall())


def get_connection_by_id(connection_id: str) -> dict[str, Any] | None:
    """Fetch a single connection row by id, or ``None`` if not found."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                id, company_id, plugin_connection_id, label, base_url,
                auth_mode, is_active, last_health_check_at,
                last_health_status, last_health_error, created_at, updated_at
            FROM integrations_sap.connections
            WHERE id = %s
            LIMIT 1
            """,
            (connection_id,),
        )
        return cur.fetchone()


def insert_connection(
    *,
    company_id: str,
    label: str,
    base_url: str,
    auth_mode: str,
    plugin_connection_id: str | None = None,
    is_active: bool = True,
) -> str:
    """Create a row in ``integrations_sap.connections`` and return its id.

    ``plugin_connection_id`` is the id of the encrypted-credentials row in
    the core's ``plugin_connections`` table (managed by the SDK
    ``piilot.sdk.connectors`` primitives). Pass ``None`` only for tests or
    legacy connections that don't carry secrets.
    """
    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO integrations_sap.connections
                (company_id, label, base_url, auth_mode,
                 plugin_connection_id, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                company_id,
                label,
                base_url.rstrip("/"),
                auth_mode,
                plugin_connection_id,
                is_active,
            ),
        )
        row = cur.fetchone()
        return str(row["id"])


_UPDATABLE_CONNECTION_FIELDS: frozenset[str] = frozenset(
    {
        "label",
        "base_url",
        "auth_mode",
        "plugin_connection_id",
        "is_active",
    }
)


def update_connection(connection_id: str, **fields: Any) -> bool:
    """Update an allow-listed subset of fields. Returns True if a row matched.

    Ignores unknown fields silently. Whitelist enforced server-side to keep
    the route layer from accidentally exposing immutable columns.
    """
    payload = {k: v for k, v in fields.items() if k in _UPDATABLE_CONNECTION_FIELDS}
    if not payload:
        return False
    set_clause = ", ".join(f"{name} = %s" for name in payload)
    params: list[Any] = list(payload.values())
    params.append(connection_id)
    with cursor() as cur:
        cur.execute(
            f"""
            UPDATE integrations_sap.connections
            SET {set_clause}
            WHERE id = %s
            """,
            tuple(params),
        )
        return cur.rowcount > 0


def delete_connection(connection_id: str) -> bool:
    """Delete a connection. Cascade removes its schema_snapshot rows; the
    audit log keeps its rows (``ON DELETE SET NULL`` on ``connection_id``).
    Returns True if a row was removed."""
    with cursor() as cur:
        cur.execute(
            """
            DELETE FROM integrations_sap.connections
            WHERE id = %s
            """,
            (connection_id,),
        )
        return cur.rowcount > 0


def set_connection_health(
    *,
    connection_id: str,
    status: str,
    error: str | None = None,
) -> bool:
    """Record the outcome of a ``POST /test`` call on a connection."""
    with cursor() as cur:
        cur.execute(
            """
            UPDATE integrations_sap.connections
            SET last_health_check_at = now(),
                last_health_status   = %s,
                last_health_error    = %s
            WHERE id = %s
            """,
            (status, error, connection_id),
        )
        return cur.rowcount > 0


def get_active_connection(company_id: str) -> dict[str, Any] | None:
    """Return the most recently updated active connection for the company.

    Used by :mod:`piilot_pack_sap.connection_resolver` when the agent
    session doesn't pin an explicit ``connection_id`` via
    ``piilot.sdk.session.set_scope``.
    """
    with cursor() as cur:
        cur.execute(
            """
            SELECT
                id, company_id, plugin_connection_id, label, base_url,
                auth_mode, is_active, last_health_check_at,
                last_health_status, last_health_error, created_at, updated_at
            FROM integrations_sap.connections
            WHERE company_id = %s AND is_active = TRUE
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (company_id,),
        )
        return cur.fetchone()


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
    label: str | None
    description: str | None
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
) -> dict[str, Any] | None:
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
    connection_id: str | None
    user_id: str | None
    session_id: str | None
    tool_id: str
    entity_set: str | None
    odata_url: str
    http_method: str
    status: str
    http_status: int | None
    latency_ms: int | None
    error: str | None
    result_count: int | None


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
    status: str | None = None,
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
    "delete_connection",
    "get_active_connection",
    "get_connection_by_id",
    "get_snapshot_entry",
    "insert_audit_log",
    "insert_connection",
    "list_audit_log",
    "list_connections",
    "list_schema_snapshot",
    "set_connection_health",
    "update_connection",
    "upsert_schema_snapshot",
]
