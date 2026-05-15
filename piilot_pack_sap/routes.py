"""HTTP routes mounted under ``/plugins/sap/*``.

The router is the single entry point the frontend hits to manage SAP
connections, trigger ``$metadata`` syncs and read the audit trail.
Authentication is delegated to the SDK helpers (``require_user`` /
``require_builder`` / ``require_admin``); the host's ``plugin_gate``
middleware enforces ``X-Company-Id`` on every call.

Routes:

* ``GET    /plugins/sap/health``                          plugin health snapshot
* ``GET    /plugins/sap/connections``                     list tenant connections
* ``GET    /plugins/sap/connections/{id}``                fetch one connection
* ``POST   /plugins/sap/connections``                     create connection (builder)
* ``PATCH  /plugins/sap/connections/{id}``                update connection (builder)
* ``DELETE /plugins/sap/connections/{id}``                delete connection (admin)
* ``POST   /plugins/sap/connections/{id}/test``           live ``$metadata`` reachability
* ``POST   /plugins/sap/connections/{id}/sync``           refresh snapshot + KB
* ``GET    /plugins/sap/connections/{id}/entities``       list cached EntitySets
* ``GET    /plugins/sap/connections/{id}/entities/{name}`` describe one entity
* ``GET    /plugins/sap/connections/{id}/audit``          paginated audit log

Credentials (``basic_username/basic_password`` or ``oauth_*``) are
forwarded to ``piilot.sdk.connectors.save_connection`` which encrypts
the ``type: secret`` fields at rest. The plugin never logs cleartext
secrets.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from piilot.sdk.connectors import (
    delete_connection as sdk_delete_connection,
    get_connection as sdk_get_connection,
    save_connection as sdk_save_connection,
    update_config as sdk_update_config,
)
from piilot.sdk.db import run_in_thread
from piilot.sdk.http import (
    register_router,
    require_admin,
    require_builder,
    require_user,
)
from pydantic import BaseModel, Field

from piilot_pack_sap import audit, kb_seeder, repository, snapshot_service
from piilot_pack_sap.connection_resolver import ConnectionResolver, ResolutionError
from piilot_pack_sap.introspect import IntrospectError, parse_metadata
from piilot_pack_sap.odata_client import (
    ODataClient,
    ODataConnectionError,
    ODataHTTPError,
)
from piilot_pack_sap.rate_limit import limiter as rate_limiter

logger = logging.getLogger("piilot_pack_sap.routes")

router = APIRouter()

# Rate-limit deps. The limiter itself is a module-level singleton that
# the host shares across requests (process-local). Three buckets:
# - read   : cheap GET endpoints (60/min).
# - write  : CRUD POST/PATCH/DELETE (10/min).
# - heavy  : POST /test and /sync — one $metadata fetch each (5/min).
_RL_READ = Depends(rate_limiter.depends_read())
_RL_WRITE = Depends(rate_limiter.depends_write())
_RL_HEAVY = Depends(rate_limiter.depends_heavy())

AuthUser = Annotated[tuple, Depends(require_user)]
AuthBuilder = Annotated[tuple, Depends(require_builder)]
AuthAdmin = Annotated[tuple, Depends(require_admin)]

AuthMode = Literal["basic", "oauth_client_credentials"]
PLUGIN_PROVIDER = "sap.s4hana_cloud"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ConnectionCredentials(BaseModel):
    """Cleartext credentials POSTed by the UI.

    Encrypted at rest by ``piilot.sdk.connectors.save_connection`` (every
    field marked ``type: secret`` in the manifest's ``credentials_schema``
    is routed through ``piilot.sdk.crypto.encrypt``).
    """

    basic_username: Optional[str] = None
    basic_password: Optional[str] = None
    oauth_token_url: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_scope: Optional[str] = None


class ConnectionCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=8, max_length=500)
    auth_mode: AuthMode
    credentials: ConnectionCredentials


class ConnectionUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    base_url: Optional[str] = Field(None, min_length=8, max_length=500)
    auth_mode: Optional[AuthMode] = None
    is_active: Optional[bool] = None
    credentials: Optional[ConnectionCredentials] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health", dependencies=[_RL_READ])
async def health(auth: AuthUser) -> dict:
    """Plugin health snapshot for the caller's company.

    Returns connection / snapshot / audit counts so the UI can render
    the dashboard without N round-trips.
    """
    user_id, role, company_id = auth
    connections = await run_in_thread(
        repository.list_connections, company_id=company_id, active_only=False
    )
    return {
        "plugin": "sap",
        "version": "0.1.0",
        "company_id": company_id,
        "user_id": user_id,
        "role": role,
        "connections_total": len(connections),
        "connections_active": sum(
            1 for c in connections if c.get("is_active")
        ),
    }


# ---------------------------------------------------------------------------
# Connections — list / get / create / update / delete
# ---------------------------------------------------------------------------


@router.get("/connections", dependencies=[_RL_READ])
async def list_connections(
    auth: AuthUser,
    active_only: bool = Query(False),
) -> dict:
    _, _, company_id = auth
    rows = await run_in_thread(
        repository.list_connections,
        company_id=company_id,
        active_only=active_only,
    )
    return {"items": [_serialize_connection(r) for r in rows]}


@router.get("/connections/{connection_id}", dependencies=[_RL_READ])
async def get_connection(
    auth: AuthUser,
    connection_id: str = Path(...),
) -> dict:
    _, _, company_id = auth
    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    _assert_visible(row, company_id)
    return _serialize_connection(row)


@router.post("/connections", status_code=201, dependencies=[_RL_WRITE])
async def create_connection(
    auth: AuthBuilder,
    payload: ConnectionCreate,
) -> dict:
    _, _, company_id = auth
    _validate_credentials(payload.auth_mode, payload.credentials)
    base_url = payload.base_url.rstrip("/")

    sdk_row = await run_in_thread(
        sdk_save_connection,
        provider=PLUGIN_PROVIDER,
        company_id=company_id,
        credentials=_credentials_to_dict(payload.credentials),
        config={"label": payload.label, "base_url": base_url, "auth_mode": payload.auth_mode},
    )
    plugin_connection_id = sdk_row.get("id") if isinstance(sdk_row, dict) else None

    try:
        connection_id = await run_in_thread(
            repository.insert_connection,
            company_id=company_id,
            label=payload.label,
            base_url=base_url,
            auth_mode=payload.auth_mode,
            plugin_connection_id=plugin_connection_id,
        )
    except Exception:
        # Roll back the encrypted-credentials row so the company doesn't
        # accumulate orphaned secrets when the table-row insert fails.
        if plugin_connection_id:
            try:
                await run_in_thread(sdk_delete_connection, plugin_connection_id)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                logger.exception(
                    "failed to roll back orphan plugin_connection %s",
                    plugin_connection_id,
                )
        raise

    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    return _serialize_connection(row)


@router.patch("/connections/{connection_id}", dependencies=[_RL_WRITE])
async def update_connection(
    auth: AuthBuilder,
    payload: ConnectionUpdate,
    connection_id: str = Path(...),
) -> dict:
    _, _, company_id = auth
    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    _assert_visible(row, company_id)

    fields: dict[str, Any] = {}
    if payload.label is not None:
        fields["label"] = payload.label
    if payload.base_url is not None:
        fields["base_url"] = payload.base_url.rstrip("/")
    if payload.auth_mode is not None:
        fields["auth_mode"] = payload.auth_mode
    if payload.is_active is not None:
        fields["is_active"] = payload.is_active

    if fields:
        await run_in_thread(
            repository.update_connection, connection_id, **fields
        )

    if payload.credentials is not None:
        _validate_credentials(
            payload.auth_mode or row["auth_mode"], payload.credentials
        )
        plugin_connection_id = row.get("plugin_connection_id")
        if not plugin_connection_id:
            raise HTTPException(
                status_code=409,
                detail="connection has no encrypted credentials row to update",
            )
        await run_in_thread(
            sdk_update_config,
            plugin_connection_id,
            credentials=_credentials_to_dict(payload.credentials),
        )

    fresh = await run_in_thread(
        repository.get_connection_by_id, connection_id
    )
    return _serialize_connection(fresh)


@router.delete("/connections/{connection_id}", status_code=204, dependencies=[_RL_WRITE])
async def delete_connection(
    auth: AuthAdmin,
    connection_id: str = Path(...),
) -> None:
    _, _, company_id = auth
    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    _assert_visible(row, company_id)
    plugin_connection_id = row.get("plugin_connection_id")

    await run_in_thread(repository.delete_connection, connection_id)
    if plugin_connection_id:
        try:
            await run_in_thread(sdk_delete_connection, plugin_connection_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to delete plugin_connection %s for connection %s",
                plugin_connection_id,
                connection_id,
            )


# ---------------------------------------------------------------------------
# Connection actions — test / sync
# ---------------------------------------------------------------------------


@router.post("/connections/{connection_id}/test", dependencies=[_RL_HEAVY])
async def test_connection(
    auth: AuthBuilder,
    connection_id: str = Path(...),
) -> dict:
    """Fetch ``$metadata`` once and report success / failure.

    Does NOT persist the snapshot — this is a quick reachability + auth
    check used by the Connection panel's "Test" button. Use the
    ``/sync`` route to actually refresh the cache.
    """
    _, _, company_id = auth
    resolved, base_url = await _resolve_for_company(
        connection_id=connection_id, company_id=company_id
    )

    client = ODataClient(
        base_url=base_url, auth=resolved.auth, version=resolved.version
    )
    try:
        try:
            xml = await client.get_metadata()
        except ODataHTTPError as exc:
            await run_in_thread(
                repository.set_connection_health,
                connection_id=connection_id,
                status="error",
                error=f"HTTP {exc.status}: {exc.message}",
            )
            return {
                "ok": False,
                "status": "http_error",
                "http_status": exc.status,
                "error": exc.message,
            }
        except ODataConnectionError as exc:
            await run_in_thread(
                repository.set_connection_health,
                connection_id=connection_id,
                status="error",
                error=str(exc),
            )
            return {"ok": False, "status": "unreachable", "error": str(exc)}
    finally:
        await client.aclose()

    # Lightweight smoke parse to make sure the payload is real XML.
    try:
        snapshot = parse_metadata(xml)
        entity_count = len(snapshot.entity_sets)
    except IntrospectError as exc:
        await run_in_thread(
            repository.set_connection_health,
            connection_id=connection_id,
            status="error",
            error=f"parse_error: {exc}",
        )
        return {"ok": False, "status": "parse_error", "error": str(exc)}

    await run_in_thread(
        repository.set_connection_health,
        connection_id=connection_id,
        status="ok",
    )
    return {
        "ok": True,
        "status": "ok",
        "entity_set_count": entity_count,
        "odata_version": snapshot.version,
    }


@router.post("/connections/{connection_id}/sync", dependencies=[_RL_HEAVY])
async def sync_connection(
    auth: AuthBuilder,
    connection_id: str = Path(...),
) -> dict:
    """Fetch ``$metadata``, persist the snapshot, refresh the KB."""
    _, _, company_id = auth
    resolved, base_url = await _resolve_for_company(
        connection_id=connection_id, company_id=company_id
    )

    client = ODataClient(
        base_url=base_url, auth=resolved.auth, version=resolved.version
    )
    try:
        xml = await client.get_metadata()
    except ODataHTTPError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=502, detail=f"SAP returned HTTP {exc.status}"
        ) from exc
    except ODataConnectionError as exc:
        await client.aclose()
        raise HTTPException(
            status_code=504, detail=f"SAP unreachable: {exc}"
        ) from exc
    finally:
        await client.aclose()

    try:
        snapshot = parse_metadata(xml)
    except IntrospectError as exc:
        raise HTTPException(
            status_code=502, detail=f"failed to parse $metadata: {exc}"
        ) from exc

    persisted = await run_in_thread(
        snapshot_service.persist_schema_snapshot,
        connection_id=connection_id,
        company_id=company_id,
        service_path=_service_path_from_base_url(base_url),
        snapshot=snapshot,
    )
    kb_outcome = await run_in_thread(
        kb_seeder.seed_metadata_kb,
        company_id=company_id,
        connection_label=resolved.label,
        snapshot=snapshot,
    )
    await run_in_thread(
        repository.set_connection_health,
        connection_id=connection_id,
        status="ok",
    )
    return {
        "ok": True,
        "entity_set_count": len(snapshot.entity_sets),
        "snapshot_rows": persisted,
        "kb": kb_outcome,
    }


# ---------------------------------------------------------------------------
# Entities — list / detail
# ---------------------------------------------------------------------------


@router.get("/connections/{connection_id}/entities", dependencies=[_RL_READ])
async def list_entities(
    auth: AuthUser,
    connection_id: str = Path(...),
    limit: int = Query(500, ge=1, le=10_000),
) -> dict:
    _, _, company_id = auth
    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    _assert_visible(row, company_id)
    rows = await run_in_thread(
        repository.list_schema_snapshot,
        connection_id=connection_id,
        limit=limit,
    )
    return {"items": [_serialize_entity_summary(r) for r in rows]}


@router.get(
    "/connections/{connection_id}/entities/{entity_name}",
    dependencies=[_RL_READ],
)
async def get_entity(
    auth: AuthUser,
    connection_id: str = Path(...),
    entity_name: str = Path(...),
) -> dict:
    _, _, company_id = auth
    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    _assert_visible(row, company_id)
    entry = await run_in_thread(
        repository.get_snapshot_entry,
        connection_id=connection_id,
        entity_set_name=entity_name,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="entity not found in snapshot")
    return _serialize_entity_full(entry)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@router.get("/connections/{connection_id}/audit", dependencies=[_RL_READ])
async def list_connection_audit(
    auth: AuthUser,
    connection_id: str = Path(...),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[str] = Query(None),
) -> dict:
    _, _, company_id = auth
    row = await run_in_thread(repository.get_connection_by_id, connection_id)
    _assert_visible(row, company_id)
    rows = await run_in_thread(
        repository.list_audit_log,
        company_id=company_id,
        limit=limit,
        status=status,
    )
    # Restrict to entries that belong to this connection — list_audit_log
    # returns the whole tenant's history.
    filtered = [r for r in rows if r.get("connection_id") == connection_id]
    return {"items": [_serialize_audit_row(r) for r in filtered]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_visible(row: Optional[dict], company_id: str) -> None:
    """Raise 404 if the connection is missing OR belongs to another tenant.

    A 403 would leak the existence of the row to a member of a different
    company. ``404 Not found`` keeps the surface uniform.
    """
    if row is None or row.get("company_id") != company_id:
        raise HTTPException(status_code=404, detail="connection not found")


def _validate_credentials(
    auth_mode: AuthMode,
    creds: ConnectionCredentials,
) -> None:
    if auth_mode == "basic":
        if not creds.basic_username or not creds.basic_password:
            raise HTTPException(
                status_code=422,
                detail="basic_username and basic_password are required for basic auth",
            )
    elif auth_mode == "oauth_client_credentials":
        if not creds.oauth_token_url or not creds.oauth_client_id or not creds.oauth_client_secret:
            raise HTTPException(
                status_code=422,
                detail=(
                    "oauth_token_url, oauth_client_id and oauth_client_secret "
                    "are required for oauth_client_credentials auth"
                ),
            )


def _credentials_to_dict(creds: ConnectionCredentials) -> dict[str, str]:
    """Drop None values — SDK only encrypts the fields it actually receives."""
    return {k: v for k, v in creds.model_dump().items() if v is not None}


async def _resolve_for_company(
    *, connection_id: str, company_id: str
) -> tuple[Any, str]:
    """Resolve the explicit connection id under tenant isolation.

    Raises ``HTTPException`` on missing row / cross-tenant / unresolvable
    creds — frontends never see a stack trace.
    """
    try:
        resolved = await ConnectionResolver().resolve_for_connection_id(
            connection_id=connection_id, company_id=company_id
        )
    except ResolutionError as exc:
        # Differentiate "not found" (cross-tenant or missing) from "bad
        # credentials state": the resolver's own error messages already
        # contain "not found" or "belongs to another company" — surface
        # them as 404 to keep tenant existence opaque.
        message = str(exc)
        if "not found" in message or "another company" in message:
            raise HTTPException(status_code=404, detail="connection not found") from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return resolved, resolved.base_url


def _service_path_from_base_url(base_url: str) -> str:
    """Extract the SAP service path from a full URL.

    ``https://erp.example/sap/opu/odata/sap/API_BP`` →
    ``/sap/opu/odata/sap/API_BP``. Falls back to the full base_url if
    it doesn't start with a scheme — defensive for legacy rows.
    """
    if "://" not in base_url:
        return base_url
    after_scheme = base_url.split("://", 1)[1]
    if "/" not in after_scheme:
        return "/"
    return "/" + after_scheme.split("/", 1)[1].rstrip("/")


def _serialize_connection(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "company_id": str(row["company_id"]),
        "label": row.get("label") or "",
        "base_url": row.get("base_url") or "",
        "auth_mode": row.get("auth_mode") or "basic",
        "is_active": bool(row.get("is_active")),
        "plugin_connection_id": (
            str(row["plugin_connection_id"])
            if row.get("plugin_connection_id")
            else None
        ),
        "last_health_check_at": _stringify(row.get("last_health_check_at")),
        "last_health_status": row.get("last_health_status"),
        "last_health_error": row.get("last_health_error"),
        "created_at": _stringify(row.get("created_at")),
        "updated_at": _stringify(row.get("updated_at")),
    }


def _serialize_entity_summary(row: dict) -> dict:
    return {
        "entity_set_name": row["entity_set_name"],
        "service_path": row.get("service_path"),
        "label": row.get("label"),
        "description": row.get("description"),
        "last_synced_at": _stringify(row.get("last_synced_at")),
    }


def _serialize_entity_full(row: dict) -> dict:
    return {
        **_serialize_entity_summary(row),
        "payload": row.get("payload") or {},
    }


def _serialize_audit_row(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "tool_id": row.get("tool_id"),
        "entity_set": row.get("entity_set"),
        "odata_url": row.get("odata_url"),
        "status": row.get("status"),
        "http_status": row.get("http_status"),
        "latency_ms": row.get("latency_ms"),
        "result_count": row.get("result_count"),
        "error": row.get("error"),
        "created_at": _stringify(row.get("created_at")),
    }


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def wire_routes() -> None:
    """Register the router under ``/plugins/sap``.

    Called from :meth:`Plugin.register`. Empty prefix → routes land at
    ``/plugins/sap/health``, ``/plugins/sap/connections``, etc.
    """
    register_router(router, prefix="")


__all__ = ["router", "wire_routes"]
