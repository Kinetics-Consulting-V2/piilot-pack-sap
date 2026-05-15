"""Tests for ``piilot_pack_sap.routes`` — 11 HTTP endpoints.

Strategy:

* Use FastAPI's ``TestClient`` against a minimal app that mounts the
  router directly (no plugin gate middleware in tests — covered by the
  host's integration suite).
* Replace the SDK auth dependencies (``require_user`` /
  ``require_builder`` / ``require_admin``) with stub tuples so each
  test can set the caller's role explicitly.
* Patch the repository + SDK connectors + ``run_in_thread`` at the
  routes import site so no DB / crypto round-trip happens.
"""

from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from piilot.sdk.http import require_admin, require_builder, require_user

from piilot_pack_sap.connection_resolver import (
    ResolutionError,
    ResolvedConnection,
)
from piilot_pack_sap.auth import BasicAuth
from piilot_pack_sap import routes as routes_module
from piilot_pack_sap.odata_client import ODataConnectionError, ODataHTTPError
from piilot_pack_sap.introspect import IntrospectError


_USER = ("user-1", "user", "comp-1")
_BUILDER = ("user-1", "builder", "comp-1")
_ADMIN = ("user-1", "admin", "comp-1")
_OTHER = ("user-2", "user", "OTHER-COMPANY")

_CONNECTION_ROW = {
    "id": "conn-1",
    "company_id": "comp-1",
    "plugin_connection_id": "plug-1",
    "label": "Sandbox",
    "base_url": "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_BP",
    "auth_mode": "basic",
    "is_active": True,
    "last_health_check_at": None,
    "last_health_status": None,
    "last_health_error": None,
    "created_at": "2026-05-15T08:00:00Z",
    "updated_at": "2026-05-15T08:00:00Z",
}

_RESOLVED = ResolvedConnection(
    connection_id="conn-1",
    company_id="comp-1",
    label="Sandbox",
    base_url="https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_BP",
    auth=BasicAuth(username="u", password="p"),
    version="v2",
    auth_mode="basic",
)


async def _passthrough_run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


@pytest.fixture
def app():
    """Build a fresh FastAPI app that mounts the SAP router."""
    instance = FastAPI()
    instance.include_router(routes_module.router, prefix="/plugins/sap")
    return instance


@pytest.fixture
def client(app):
    return TestClient(app)


def _set_role(app, role_tuple):
    """Override every auth dep on the app so the role is deterministic."""

    def _override():
        return role_tuple

    app.dependency_overrides[require_user] = _override
    app.dependency_overrides[require_builder] = _override
    app.dependency_overrides[require_admin] = _override


@pytest.fixture(autouse=True)
def _patched_run_in_thread():
    with patch(
        "piilot_pack_sap.routes.run_in_thread", new=_passthrough_run_in_thread
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the shared rate-limit buckets between tests.

    Without this, every ``POST /test`` and ``POST /sync`` in the suite
    would accumulate into the ``heavy`` bucket (limit 5/min) and the
    6th+ tests would 429 instead of exercising the real route logic.
    """
    from piilot_pack_sap.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


# ---------- Health ---------------------------------------------------------


def test_health_returns_counts(app, client) -> None:
    _set_role(app, _USER)
    with patch(
        "piilot_pack_sap.routes.repository.list_connections",
        return_value=[
            {"is_active": True}, {"is_active": True}, {"is_active": False}
        ],
    ):
        r = client.get("/plugins/sap/health")
    assert r.status_code == 200
    body = r.json()
    assert body["plugin"] == "sap"
    assert body["company_id"] == "comp-1"
    assert body["connections_total"] == 3
    assert body["connections_active"] == 2


# ---------- list / get connections -----------------------------------------


def test_list_connections_returns_serialized_items(app, client) -> None:
    _set_role(app, _USER)
    with patch(
        "piilot_pack_sap.routes.repository.list_connections",
        return_value=[_CONNECTION_ROW],
    ):
        r = client.get("/plugins/sap/connections")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "conn-1"
    assert items[0]["label"] == "Sandbox"
    assert items[0]["auth_mode"] == "basic"


def test_get_connection_returns_404_when_cross_tenant(app, client) -> None:
    _set_role(app, _OTHER)
    with patch(
        "piilot_pack_sap.routes.repository.get_connection_by_id",
        return_value=_CONNECTION_ROW,
    ):
        r = client.get("/plugins/sap/connections/conn-1")
    assert r.status_code == 404


def test_get_connection_404_when_missing(app, client) -> None:
    _set_role(app, _USER)
    with patch(
        "piilot_pack_sap.routes.repository.get_connection_by_id",
        return_value=None,
    ):
        r = client.get("/plugins/sap/connections/ghost")
    assert r.status_code == 404


def test_get_connection_returns_serialized_row(app, client) -> None:
    _set_role(app, _USER)
    with patch(
        "piilot_pack_sap.routes.repository.get_connection_by_id",
        return_value=_CONNECTION_ROW,
    ):
        r = client.get("/plugins/sap/connections/conn-1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "conn-1"
    assert body["plugin_connection_id"] == "plug-1"


# ---------- create ---------------------------------------------------------


def test_create_connection_basic_happy_path(app, client) -> None:
    _set_role(app, _BUILDER)
    with (
        patch(
            "piilot_pack_sap.routes.sdk_save_connection",
            return_value={"id": "plug-new"},
        ) as mock_save,
        patch(
            "piilot_pack_sap.routes.repository.insert_connection",
            return_value="conn-new",
        ) as mock_insert,
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value={**_CONNECTION_ROW, "id": "conn-new"},
        ),
    ):
        r = client.post(
            "/plugins/sap/connections",
            json={
                "label": "New",
                "base_url": "https://example.sap/sap/opu/odata/sap/API_BP/",
                "auth_mode": "basic",
                "credentials": {
                    "basic_username": "u",
                    "basic_password": "p",
                },
            },
        )
    assert r.status_code == 201
    assert r.json()["id"] == "conn-new"
    # base_url stripped before insert.
    insert_kwargs = mock_insert.call_args.kwargs
    assert insert_kwargs["base_url"].endswith("/API_BP")
    assert insert_kwargs["plugin_connection_id"] == "plug-new"
    mock_save.assert_called_once()


def test_create_connection_basic_rejects_missing_credentials(app, client) -> None:
    _set_role(app, _BUILDER)
    r = client.post(
        "/plugins/sap/connections",
        json={
            "label": "X",
            "base_url": "https://x.sap/",
            "auth_mode": "basic",
            "credentials": {"basic_username": "u"},
        },
    )
    assert r.status_code == 422


def test_create_connection_oauth_rejects_missing_token_url(app, client) -> None:
    _set_role(app, _BUILDER)
    r = client.post(
        "/plugins/sap/connections",
        json={
            "label": "X",
            "base_url": "https://x.sap/",
            "auth_mode": "oauth_client_credentials",
            "credentials": {
                "oauth_client_id": "c",
                "oauth_client_secret": "s",
            },
        },
    )
    assert r.status_code == 422


def test_create_connection_rolls_back_plugin_connection_on_failure(
    app, client
) -> None:
    """Verify the rollback path: when insert_connection raises, the
    encrypted plugin_connection row created in the previous step must be
    deleted to avoid orphan secrets accumulating in the core table."""
    _set_role(app, _BUILDER)
    with (
        patch(
            "piilot_pack_sap.routes.sdk_save_connection",
            return_value={"id": "plug-new"},
        ),
        patch(
            "piilot_pack_sap.routes.repository.insert_connection",
            side_effect=RuntimeError("db down"),
        ),
        patch(
            "piilot_pack_sap.routes.sdk_delete_connection"
        ) as mock_delete,
    ):
        # TestClient propagates uncaught exceptions instead of letting
        # the FastAPI default 500 handler do its thing. The behaviour we
        # care about is the rollback side-effect — assert that
        # sdk_delete_connection was invoked before the exception bubbled.
        with pytest.raises(RuntimeError, match="db down"):
            client.post(
                "/plugins/sap/connections",
                json={
                    "label": "X",
                    "base_url": "https://x.sap/",
                    "auth_mode": "basic",
                    "credentials": {
                        "basic_username": "u",
                        "basic_password": "p",
                    },
                },
            )
    mock_delete.assert_called_once_with("plug-new")


# ---------- update ---------------------------------------------------------


def test_patch_connection_updates_label_and_base_url(app, client) -> None:
    _set_role(app, _BUILDER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.update_connection",
            return_value=True,
        ) as mock_update,
    ):
        r = client.patch(
            "/plugins/sap/connections/conn-1",
            json={"label": "Renamed", "base_url": "https://x.sap/"},
        )
    assert r.status_code == 200
    fields = mock_update.call_args.kwargs
    assert fields["label"] == "Renamed"
    assert fields["base_url"] == "https://x.sap"


def test_patch_connection_updates_credentials_via_sdk(app, client) -> None:
    _set_role(app, _BUILDER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.update_connection",
            return_value=True,
        ),
        patch(
            "piilot_pack_sap.routes.sdk_update_config"
        ) as mock_update_config,
    ):
        r = client.patch(
            "/plugins/sap/connections/conn-1",
            json={
                "credentials": {
                    "basic_username": "u2",
                    "basic_password": "p2",
                }
            },
        )
    assert r.status_code == 200
    mock_update_config.assert_called_once()


def test_patch_connection_404_on_cross_tenant(app, client) -> None:
    _set_role(app, _OTHER)
    with patch(
        "piilot_pack_sap.routes.repository.get_connection_by_id",
        return_value=_CONNECTION_ROW,
    ):
        r = client.patch(
            "/plugins/sap/connections/conn-1", json={"label": "X"}
        )
    assert r.status_code == 404


# ---------- delete ---------------------------------------------------------


def test_delete_connection_requires_admin(app, client) -> None:
    _set_role(app, _BUILDER)
    # Builders should be refused by the SDK's require_admin — but we
    # override every dep with the same tuple in this test rig, so we
    # need a separate override that fails the role check explicitly.
    from fastapi import HTTPException

    def _refuse_admin():
        raise HTTPException(status_code=403, detail="admin only")

    app.dependency_overrides[require_admin] = _refuse_admin

    r = client.delete("/plugins/sap/connections/conn-1")
    assert r.status_code == 403


def test_delete_connection_admin_cascades_to_sdk(app, client) -> None:
    _set_role(app, _ADMIN)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.delete_connection",
            return_value=True,
        ) as mock_del_repo,
        patch(
            "piilot_pack_sap.routes.sdk_delete_connection"
        ) as mock_del_sdk,
    ):
        r = client.delete("/plugins/sap/connections/conn-1")
    assert r.status_code == 204
    mock_del_repo.assert_called_once_with("conn-1")
    mock_del_sdk.assert_called_once_with("plug-1")


# ---------- test (live $metadata) -----------------------------------------


@pytest.fixture
def patched_resolver():
    with patch(
        "piilot_pack_sap.routes.ConnectionResolver"
    ) as cls:
        resolver = MagicMock()
        resolver.resolve_for_connection_id = AsyncMock(return_value=_RESOLVED)
        cls.return_value = resolver
        yield resolver


_TINY_METADATA = (
    '<?xml version="1.0"?><edmx:Edmx Version="4.0" '
    'xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">'
    '<edmx:DataServices><Schema Namespace="x" '
    'xmlns="http://docs.oasis-open.org/odata/ns/edm">'
    '<EntityType Name="T"><Key><PropertyRef Name="Id"/></Key>'
    '<Property Name="Id" Type="Edm.String" Nullable="false"/>'
    '</EntityType><EntityContainer Name="C">'
    '<EntitySet Name="Es" EntityType="x.T"/></EntityContainer>'
    '</Schema></edmx:DataServices></edmx:Edmx>'
)


@pytest.fixture
def patched_odata_client():
    with patch("piilot_pack_sap.routes.ODataClient") as cls:
        client = MagicMock()
        client.get_metadata = AsyncMock(return_value=_TINY_METADATA)
        client.aclose = AsyncMock()
        cls.return_value = client
        yield client


def test_test_connection_returns_ok_status(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    with patch(
        "piilot_pack_sap.routes.repository.set_connection_health"
    ) as mock_health:
        r = client.post("/plugins/sap/connections/conn-1/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert body["entity_set_count"] == 1
    assert body["odata_version"] == "v4"
    mock_health.assert_called_once()
    assert mock_health.call_args.kwargs["status"] == "ok"


def test_test_connection_handles_http_error(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    patched_odata_client.get_metadata.side_effect = ODataHTTPError(
        status=403, message="forbidden"
    )
    with patch(
        "piilot_pack_sap.routes.repository.set_connection_health"
    ) as mock_health:
        r = client.post("/plugins/sap/connections/conn-1/test")
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "http_error"
    assert body["http_status"] == 403
    assert mock_health.call_args.kwargs["status"] == "error"


def test_test_connection_handles_connection_error(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    patched_odata_client.get_metadata.side_effect = ODataConnectionError(
        "net down"
    )
    with patch(
        "piilot_pack_sap.routes.repository.set_connection_health"
    ):
        r = client.post("/plugins/sap/connections/conn-1/test")
    assert r.json()["status"] == "unreachable"


def test_test_connection_handles_parse_error(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    patched_odata_client.get_metadata.return_value = "<not valid xml"
    with patch(
        "piilot_pack_sap.routes.repository.set_connection_health"
    ):
        r = client.post("/plugins/sap/connections/conn-1/test")
    assert r.json()["status"] == "parse_error"


def test_test_connection_unresolvable_returns_404(app, client) -> None:
    _set_role(app, _BUILDER)
    with patch("piilot_pack_sap.routes.ConnectionResolver") as cls:
        resolver = MagicMock()
        resolver.resolve_for_connection_id = AsyncMock(
            side_effect=ResolutionError("connection_id='conn-x' not found")
        )
        cls.return_value = resolver
        r = client.post("/plugins/sap/connections/conn-x/test")
    assert r.status_code == 404


# ---------- sync ----------------------------------------------------------


def test_sync_connection_persists_snapshot_and_seeds_kb(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    with (
        patch(
            "piilot_pack_sap.routes.snapshot_service.persist_schema_snapshot",
            return_value=1,
        ) as mock_persist,
        patch(
            "piilot_pack_sap.routes.kb_seeder.seed_metadata_kb",
            return_value={"kb_id": "kb-1", "inserted": 1, "updated": 0, "total": 1, "created": True},
        ) as mock_seed,
        patch(
            "piilot_pack_sap.routes.repository.set_connection_health"
        ),
    ):
        r = client.post("/plugins/sap/connections/conn-1/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["entity_set_count"] == 1
    assert body["snapshot_rows"] == 1
    assert body["kb"]["kb_id"] == "kb-1"
    mock_persist.assert_called_once()
    mock_seed.assert_called_once()


def test_sync_connection_http_error_returns_502(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    patched_odata_client.get_metadata.side_effect = ODataHTTPError(
        status=500, message="boom"
    )
    r = client.post("/plugins/sap/connections/conn-1/sync")
    assert r.status_code == 502


def test_sync_connection_unreachable_returns_504(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    patched_odata_client.get_metadata.side_effect = ODataConnectionError(
        "down"
    )
    r = client.post("/plugins/sap/connections/conn-1/sync")
    assert r.status_code == 504


def test_sync_connection_invalid_metadata_returns_502(
    app, client, patched_resolver, patched_odata_client
) -> None:
    _set_role(app, _BUILDER)
    patched_odata_client.get_metadata.return_value = "<not xml"
    r = client.post("/plugins/sap/connections/conn-1/sync")
    assert r.status_code == 502


# ---------- entities ------------------------------------------------------


def test_list_entities_returns_summaries(app, client) -> None:
    _set_role(app, _USER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.list_schema_snapshot",
            return_value=[
                {
                    "entity_set_name": "A_BP",
                    "service_path": "/sap",
                    "label": "Biz Partner",
                    "description": "desc",
                    "last_synced_at": "2026-05-15T08:00:00Z",
                }
            ],
        ),
    ):
        r = client.get("/plugins/sap/connections/conn-1/entities")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["entity_set_name"] == "A_BP"
    assert "payload" not in items[0]


def test_get_entity_returns_payload(app, client) -> None:
    _set_role(app, _USER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.get_snapshot_entry",
            return_value={
                "entity_set_name": "A_BP",
                "service_path": "/sap",
                "label": None,
                "description": None,
                "payload": {"properties": []},
                "last_synced_at": "2026-05-15T08:00:00Z",
            },
        ),
    ):
        r = client.get("/plugins/sap/connections/conn-1/entities/A_BP")
    assert r.status_code == 200
    assert r.json()["payload"] == {"properties": []}


def test_get_entity_404_when_missing(app, client) -> None:
    _set_role(app, _USER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.get_snapshot_entry",
            return_value=None,
        ),
    ):
        r = client.get("/plugins/sap/connections/conn-1/entities/Unknown")
    assert r.status_code == 404


# ---------- audit ---------------------------------------------------------


def test_list_audit_filters_by_connection(app, client) -> None:
    _set_role(app, _USER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.list_audit_log",
            return_value=[
                {
                    "id": "a1",
                    "connection_id": "conn-1",
                    "tool_id": "sap.select",
                    "status": "ok",
                    "created_at": "2026-05-15T08:00:00Z",
                },
                {
                    "id": "a2",
                    "connection_id": "other-conn",
                    "tool_id": "sap.count",
                    "status": "ok",
                    "created_at": "2026-05-15T08:01:00Z",
                },
            ],
        ),
    ):
        r = client.get("/plugins/sap/connections/conn-1/audit")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "a1"


def test_list_audit_propagates_status_filter(app, client) -> None:
    _set_role(app, _USER)
    with (
        patch(
            "piilot_pack_sap.routes.repository.get_connection_by_id",
            return_value=_CONNECTION_ROW,
        ),
        patch(
            "piilot_pack_sap.routes.repository.list_audit_log",
            return_value=[],
        ) as mock_list,
    ):
        client.get(
            "/plugins/sap/connections/conn-1/audit?status=http_error&limit=25"
        )
    kwargs = mock_list.call_args.kwargs
    assert kwargs["status"] == "http_error"
    assert kwargs["limit"] == 25
