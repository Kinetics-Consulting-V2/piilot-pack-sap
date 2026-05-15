"""Unit tests for ``piilot_pack_sap.auth`` (ApiKey + Basic strategies).

OAuth client_credentials tests live in ``test_auth_oauth.py``.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from piilot_pack_sap.auth import (
    ApiKeyAuth,
    Auth,
    BasicAuth,
    OAuthClientCredentials,
)

# ---------- ApiKeyAuth ------------------------------------------------------


@pytest.mark.asyncio
async def test_apikey_auth_injects_default_header() -> None:
    auth = ApiKeyAuth(api_key="abcdef")
    request = httpx.Request("GET", "https://example/api")
    await auth.apply(request)
    assert request.headers["APIKey"] == "abcdef"


@pytest.mark.asyncio
async def test_apikey_auth_custom_header_name() -> None:
    auth = ApiKeyAuth(api_key="x", header_name="X-Api-Token")
    request = httpx.Request("GET", "https://example/api")
    await auth.apply(request)
    assert request.headers["X-Api-Token"] == "x"
    assert "APIKey" not in request.headers


def test_apikey_auth_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    auth = ApiKeyAuth(api_key="x")
    with pytest.raises(FrozenInstanceError):
        auth.api_key = "y"  # type: ignore[misc]


def test_apikey_auth_conforms_to_protocol() -> None:
    assert isinstance(ApiKeyAuth(api_key="x"), Auth)


# ---------- BasicAuth -------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_auth_injects_base64_header() -> None:
    auth = BasicAuth(username="user", password="pass")
    request = httpx.Request("GET", "https://example/api")
    await auth.apply(request)
    expected = "Basic " + base64.b64encode(b"user:pass").decode("ascii")
    assert request.headers["Authorization"] == expected


@pytest.mark.asyncio
async def test_basic_auth_handles_unicode_creds() -> None:
    auth = BasicAuth(username="françois", password="éàü")
    request = httpx.Request("GET", "https://example/api")
    await auth.apply(request)
    header = request.headers["Authorization"]
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
    assert decoded == "françois:éàü"


def test_basic_auth_conforms_to_protocol() -> None:
    assert isinstance(BasicAuth(username="u", password="p"), Auth)


# ---------- OAuthClientCredentials — constructor smoke ---------------------


def test_oauth_constructor_validates_inputs() -> None:
    with pytest.raises(ValueError, match="token_url"):
        OAuthClientCredentials(token_url="", client_id="x", client_secret="y")
    with pytest.raises(ValueError, match="client_id"):
        OAuthClientCredentials(
            token_url="https://x", client_id="", client_secret="y"
        )
    with pytest.raises(ValueError, match="client_id"):
        OAuthClientCredentials(
            token_url="https://x", client_id="x", client_secret=""
        )


def test_oauth_conforms_to_protocol() -> None:
    auth = OAuthClientCredentials(
        token_url="https://idp/token",
        client_id="cid",
        client_secret="sec",
    )
    assert isinstance(auth, Auth)
