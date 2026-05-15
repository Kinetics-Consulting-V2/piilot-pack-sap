"""Tests for ``piilot_pack_sap.connection_resolver``.

Mocks the SDK primitives (``get_scope``, ``get_connection``, ``decrypt``,
``run_in_thread``) and the repository so the test never touches DB or
crypto state. The resolver is async; ``run_in_thread`` is replaced with a
passthrough that just runs the sync function inline.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from piilot_pack_sap.auth import BasicAuth, OAuthClientCredentials
from piilot_pack_sap.connection_resolver import (
    ConnectionResolver,
    ResolutionError,
)


async def _passthrough_run_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


@pytest.fixture
def patched_runtime():
    """Context that patches all SDK primitives ConnectionResolver depends on."""
    with (
        patch(
            "piilot_pack_sap.connection_resolver.run_in_thread",
            new=_passthrough_run_in_thread,
        ),
        patch("piilot_pack_sap.connection_resolver.get_scope") as mock_get_scope,
        patch("piilot_pack_sap.connection_resolver.get_connection") as mock_get_conn,
        patch("piilot_pack_sap.connection_resolver.decrypt", side_effect=lambda v: f"plain:{v}"),
        patch(
            "piilot_pack_sap.connection_resolver.repository.get_connection_by_id"
        ) as mock_by_id,
        patch(
            "piilot_pack_sap.connection_resolver.repository.get_active_connection"
        ) as mock_active,
    ):
        yield {
            "get_scope": mock_get_scope,
            "get_connection": mock_get_conn,
            "get_connection_by_id": mock_by_id,
            "get_active_connection": mock_active,
        }


_BASIC_ROW = {
    "id": "conn-1",
    "company_id": "comp-1",
    "plugin_connection_id": "plug-1",
    "label": "Sandbox",
    "base_url": "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_BP",
    "auth_mode": "basic",
    "is_active": True,
}

_OAUTH_ROW = {
    "id": "conn-2",
    "company_id": "comp-1",
    "plugin_connection_id": "plug-2",
    "label": "Prod",
    "base_url": "https://erp.example.com/sap/opu/odata4/sap/api",
    "auth_mode": "oauth_client_credentials",
    "is_active": True,
}


# ---------- Happy paths -----------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_falls_back_to_active_connection(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {"username": "encrypted_u", "password": "encrypted_p"}
    }

    resolver = ConnectionResolver()
    resolved = await resolver.resolve(company_id="comp-1", session_id="sess-1")

    assert resolved.connection_id == "conn-1"
    assert resolved.company_id == "comp-1"
    assert resolved.label == "Sandbox"
    assert resolved.base_url.endswith("/API_BP")
    assert resolved.version == "v2"
    assert resolved.auth_mode == "basic"
    assert isinstance(resolved.auth, BasicAuth)
    assert resolved.auth.username == "plain:encrypted_u"
    assert resolved.auth.password == "plain:encrypted_p"
    # Active path used, get_connection_by_id was not.
    patched_runtime["get_connection_by_id"].assert_not_called()


@pytest.mark.asyncio
async def test_resolve_uses_session_scope_when_set(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = {
        "plugin": "sap",
        "connection_id": "conn-2",
    }
    patched_runtime["get_connection_by_id"].return_value = _OAUTH_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {
            "oauth_token_url": "encrypted_url",
            "oauth_client_id": "encrypted_cid",
            "oauth_client_secret": "encrypted_secret",
            "oauth_scope": "encrypted_scope",
        }
    }

    resolved = await ConnectionResolver().resolve(
        company_id="comp-1", session_id="sess-1"
    )

    assert resolved.connection_id == "conn-2"
    assert resolved.auth_mode == "oauth_client_credentials"
    assert isinstance(resolved.auth, OAuthClientCredentials)
    # Decryption happened on every secret string.
    assert resolved.auth._token_url == "plain:encrypted_url"
    assert resolved.auth._client_id == "plain:encrypted_cid"
    assert resolved.auth._client_secret == "plain:encrypted_secret"
    assert resolved.auth._scope == "plain:encrypted_scope"
    # Fallback path was NOT used.
    patched_runtime["get_active_connection"].assert_not_called()


@pytest.mark.asyncio
async def test_resolve_ignores_scope_of_other_plugin(patched_runtime) -> None:
    """A scope set by another plugin must NOT pin our connection."""
    patched_runtime["get_scope"].return_value = {
        "plugin": "pennylane",
        "connection_id": "some-pennylane-conn",
    }
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {"username": "u", "password": "p"}
    }

    resolved = await ConnectionResolver().resolve(
        company_id="comp-1", session_id="sess-1"
    )

    assert resolved.connection_id == "conn-1"
    patched_runtime["get_connection_by_id"].assert_not_called()


@pytest.mark.asyncio
async def test_resolve_without_session_id_uses_active(patched_runtime) -> None:
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {"username": "u", "password": "p"}
    }

    resolved = await ConnectionResolver().resolve(company_id="comp-1")

    assert resolved.connection_id == "conn-1"
    # get_scope was never called when session_id is None.
    patched_runtime["get_scope"].assert_not_called()


# ---------- Error paths -----------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_no_active_connection_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = None

    with pytest.raises(ResolutionError, match="no active SAP connection"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_scope_pointing_to_unknown_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = {
        "plugin": "sap",
        "connection_id": "ghost",
    }
    patched_runtime["get_connection_by_id"].return_value = None

    with pytest.raises(ResolutionError, match="unknown connection_id"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_scope_to_other_company_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = {
        "plugin": "sap",
        "connection_id": "conn-1",
    }
    patched_runtime["get_connection_by_id"].return_value = {
        **_BASIC_ROW,
        "company_id": "OTHER",
    }

    with pytest.raises(ResolutionError, match="belongs to another company"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_missing_plugin_connection_id_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = {
        **_BASIC_ROW,
        "plugin_connection_id": None,
    }

    with pytest.raises(ResolutionError, match="plugin_connection_id"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_basic_missing_credentials_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {"username": "u"}  # password missing
    }

    with pytest.raises(ResolutionError, match="username and password"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_oauth_missing_credentials_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = _OAUTH_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {"oauth_token_url": "u"}  # client_id / secret missing
    }

    with pytest.raises(ResolutionError, match="oauth_token_url"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_unknown_auth_mode_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = {
        **_BASIC_ROW,
        "auth_mode": "kerberos",
    }
    patched_runtime["get_connection"].return_value = {"credentials": {}}

    with pytest.raises(ResolutionError, match="unknown auth_mode"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_missing_plugin_connection_row_raises(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW
    patched_runtime["get_connection"].return_value = None

    with pytest.raises(ResolutionError, match="not found"):
        await ConnectionResolver().resolve(company_id="comp-1", session_id="x")


@pytest.mark.asyncio
async def test_resolve_empty_company_id_raises(patched_runtime) -> None:
    with pytest.raises(ResolutionError, match="company_id is required"):
        await ConnectionResolver().resolve(company_id="", session_id="x")


@pytest.mark.asyncio
async def test_resolve_v4_default_propagates(patched_runtime) -> None:
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW
    patched_runtime["get_connection"].return_value = {
        "credentials": {"username": "u", "password": "p"}
    }

    resolved = await ConnectionResolver(default_version="v4").resolve(
        company_id="comp-1", session_id="x"
    )
    assert resolved.version == "v4"


@pytest.mark.asyncio
async def test_resolve_decrypt_failure_falls_back_to_plaintext(patched_runtime) -> None:
    """If a value can't be decrypted, keep it as-is (legacy non-encrypted fields)."""
    patched_runtime["get_scope"].return_value = None
    patched_runtime["get_active_connection"].return_value = _BASIC_ROW

    def decrypt_one_only(value):
        if value == "encrypted_p":
            return "plain_password"
        raise ValueError("not encrypted")

    patched_runtime["get_connection"].return_value = {
        "credentials": {"username": "legacy_u", "password": "encrypted_p"}
    }
    with patch(
        "piilot_pack_sap.connection_resolver.decrypt", side_effect=decrypt_one_only
    ):
        resolved = await ConnectionResolver().resolve(
            company_id="comp-1", session_id="x"
        )
    assert resolved.auth.username == "legacy_u"
    assert resolved.auth.password == "plain_password"
