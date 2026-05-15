"""Tests for ``OAuthClientCredentials`` — token cache, refresh, error paths.

Uses :mod:`respx` to mock the IdP token endpoint and a controllable monotonic
clock to exercise expiry behavior without real waits.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Iterator

import httpx
import pytest
import respx

from piilot_pack_sap.auth import AuthError, OAuthClientCredentials

TOKEN_URL = "https://idp.example/oauth/token"


class _FakeClock:
    """Mutable monotonic clock for tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


@pytest.fixture
def http_client() -> Iterator[httpx.AsyncClient]:
    # A reusable async client so respx can intercept it. We don't close it
    # here because respx@mock takes care of teardown.
    client = httpx.AsyncClient()
    yield client


@pytest.mark.asyncio
@respx.mock
async def test_first_apply_fetches_and_sets_bearer(clock, http_client) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok-1", "expires_in": 3600}
        )
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
    )

    request = httpx.Request("GET", "https://example/api")
    await auth.apply(request)

    assert request.headers["Authorization"] == "Bearer tok-1"
    assert route.call_count == 1
    posted = route.calls[0].request
    body = posted.content.decode()
    assert "grant_type=client_credentials" in body
    assert "client_id=cid" in body
    assert "client_secret=sec" in body


@pytest.mark.asyncio
@respx.mock
async def test_token_is_cached_across_apply_calls(clock, http_client) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 3600}
        )
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
    )

    for _ in range(5):
        req = httpx.Request("GET", "https://example/api")
        await auth.apply(req)
        assert req.headers["Authorization"] == "Bearer tok"

    assert route.call_count == 1  # single token fetch


@pytest.mark.asyncio
@respx.mock
async def test_token_refreshes_after_expiry(clock, http_client) -> None:
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok-1", "expires_in": 100}),
            httpx.Response(200, json={"access_token": "tok-2", "expires_in": 100}),
        ]
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
        expiry_buffer_seconds=30,
    )

    req1 = httpx.Request("GET", "https://example/api")
    await auth.apply(req1)
    assert req1.headers["Authorization"] == "Bearer tok-1"

    # Advance past expiry minus buffer (100 - 30 = 70s mark).
    clock.advance(71)

    req2 = httpx.Request("GET", "https://example/api")
    await auth.apply(req2)
    assert req2.headers["Authorization"] == "Bearer tok-2"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_token_kept_when_within_buffer_window(clock, http_client) -> None:
    """Token must still be valid right up to (expiry - buffer)."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 100}
        )
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
        expiry_buffer_seconds=30,
    )

    await auth.apply(httpx.Request("GET", "https://example/api"))
    clock.advance(69)  # one second before refresh threshold
    await auth.apply(httpx.Request("GET", "https://example/api"))

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_scope_is_sent_when_provided(clock, http_client) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 60}
        )
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        scope="API_BUSINESS_PARTNER.Read",
        http_client=http_client,
        clock=clock,
    )

    await auth.apply(httpx.Request("GET", "https://example/api"))

    body = route.calls[0].request.content.decode()
    assert "scope=API_BUSINESS_PARTNER.Read" in body


@pytest.mark.asyncio
@respx.mock
async def test_idp_401_raises_auth_error(clock, http_client) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, text="invalid_client")
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="bad",
        http_client=http_client,
        clock=clock,
    )

    with pytest.raises(AuthError, match="HTTP 401"):
        await auth.apply(httpx.Request("GET", "https://example/api"))


@pytest.mark.asyncio
@respx.mock
async def test_idp_non_json_raises_auth_error(clock, http_client) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, text="<html>oops</html>")
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
    )

    with pytest.raises(AuthError, match="non-JSON"):
        await auth.apply(httpx.Request("GET", "https://example/api"))


@pytest.mark.asyncio
@respx.mock
async def test_idp_missing_access_token_raises(clock, http_client) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"expires_in": 60})
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
    )

    with pytest.raises(AuthError, match="missing access_token"):
        await auth.apply(httpx.Request("GET", "https://example/api"))


@pytest.mark.asyncio
@respx.mock
async def test_idp_missing_expires_in_falls_back_to_one_hour(
    clock, http_client
) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok"})
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
        expiry_buffer_seconds=0,
    )

    await auth.apply(httpx.Request("GET", "https://example/api"))
    clock.advance(3599)
    await auth.apply(httpx.Request("GET", "https://example/api"))
    assert route.call_count == 1  # still cached at 3599s

    clock.advance(2)
    await auth.apply(httpx.Request("GET", "https://example/api"))
    assert route.call_count == 2  # refreshed past 3600s default


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_requests_trigger_single_fetch(clock, http_client) -> None:
    """The asyncio.Lock must serialize concurrent first-fetches."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 3600}
        )
    )

    auth = OAuthClientCredentials(
        token_url=TOKEN_URL,
        client_id="cid",
        client_secret="sec",
        http_client=http_client,
        clock=clock,
    )

    requests = [httpx.Request("GET", "https://example/api") for _ in range(10)]
    await asyncio.gather(*(auth.apply(r) for r in requests))

    assert route.call_count == 1
    assert all(r.headers["Authorization"] == "Bearer tok" for r in requests)
