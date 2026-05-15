"""Tests for ``piilot_pack_sap.rate_limit``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from piilot.sdk.http import require_user

from piilot_pack_sap import routes as routes_module
from piilot_pack_sap.rate_limit import Limits, RateLimiter, limiter


@pytest.fixture(autouse=True)
def _reset_global():
    limiter.reset()
    yield
    limiter.reset()


# ---------- Unit tests on RateLimiter -------------------------------------


@pytest.mark.asyncio
async def test_allows_calls_up_to_the_limit() -> None:
    rl = RateLimiter(Limits(read=3, write=3, heavy=3, window_seconds=60))
    for _ in range(3):
        await rl.check(company_id="comp-1", bucket="read")


@pytest.mark.asyncio
async def test_refuses_call_above_the_limit() -> None:
    rl = RateLimiter(Limits(read=2, write=2, heavy=2, window_seconds=60))
    await rl.check(company_id="comp-1", bucket="read")
    await rl.check(company_id="comp-1", bucket="read")
    with pytest.raises(Exception) as exc:
        await rl.check(company_id="comp-1", bucket="read")
    assert exc.value.status_code == 429
    # Retry-After is populated and positive.
    retry_after = exc.value.headers.get("Retry-After")
    assert retry_after is not None
    assert int(retry_after) >= 1


@pytest.mark.asyncio
async def test_buckets_are_isolated_per_company() -> None:
    rl = RateLimiter(Limits(read=2, write=2, heavy=2, window_seconds=60))
    await rl.check(company_id="comp-1", bucket="read")
    await rl.check(company_id="comp-1", bucket="read")
    # comp-2 still has full budget.
    await rl.check(company_id="comp-2", bucket="read")
    await rl.check(company_id="comp-2", bucket="read")


@pytest.mark.asyncio
async def test_buckets_are_isolated_per_kind() -> None:
    rl = RateLimiter(Limits(read=2, write=2, heavy=2, window_seconds=60))
    await rl.check(company_id="comp-1", bucket="read")
    await rl.check(company_id="comp-1", bucket="read")
    # ``write`` is a separate bucket — still allowed.
    await rl.check(company_id="comp-1", bucket="write")


@pytest.mark.asyncio
async def test_unknown_bucket_raises_value_error() -> None:
    rl = RateLimiter()
    with pytest.raises(ValueError, match="unknown rate-limit bucket"):
        await rl.check(company_id="c", bucket="xxx")


@pytest.mark.asyncio
async def test_reset_clears_all_buckets() -> None:
    rl = RateLimiter(Limits(read=1, write=1, heavy=1, window_seconds=60))
    await rl.check(company_id="c", bucket="read")
    rl.reset()
    # After reset, the same key can fire again.
    await rl.check(company_id="c", bucket="read")


@pytest.mark.asyncio
async def test_sliding_window_releases_old_entries(monkeypatch) -> None:
    """Entries older than ``window_seconds`` must be released."""
    rl = RateLimiter(Limits(read=2, write=2, heavy=2, window_seconds=10))

    fake_now = 1000.0

    def _clock() -> float:
        return fake_now

    rl._clock = _clock  # type: ignore[assignment]

    await rl.check(company_id="c", bucket="read")
    await rl.check(company_id="c", bucket="read")
    # Move past the window — both entries should age out.
    fake_now += 11
    await rl.check(company_id="c", bucket="read")
    await rl.check(company_id="c", bucket="read")
    with pytest.raises(Exception) as exc:
        await rl.check(company_id="c", bucket="read")
    assert exc.value.status_code == 429


# ---------- Integration with the FastAPI router ---------------------------


@pytest.fixture
def client():
    """Build a test app and stub every auth dep used by the routes."""
    from piilot.sdk.http import require_admin, require_builder

    app = FastAPI()
    app.include_router(routes_module.router, prefix="/plugins/sap")

    def _override():
        return ("user-1", "builder", "comp-1")

    # All three deps must be stubbed because different routes pick
    # different roles, AND the rate-limit dep itself depends on
    # ``require_user``.
    app.dependency_overrides[require_user] = _override
    app.dependency_overrides[require_builder] = _override
    app.dependency_overrides[require_admin] = _override
    return TestClient(app)


def test_read_bucket_429_after_60_calls(monkeypatch, client) -> None:
    """A burst of >60 GETs from the same company gets the 61st rejected."""
    # Patch repository to avoid hitting any DB code.
    from unittest.mock import patch

    async def _passthrough(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch("piilot_pack_sap.routes.run_in_thread", new=_passthrough),
        patch(
            "piilot_pack_sap.routes.repository.list_connections",
            return_value=[],
        ),
    ):
        # 60 allowed
        for _ in range(60):
            r = client.get("/plugins/sap/health")
            assert r.status_code == 200, r.text
        # 61st refused
        r = client.get("/plugins/sap/health")
        assert r.status_code == 429
        assert r.headers.get("Retry-After") is not None


def test_heavy_bucket_429_after_5_calls(monkeypatch, client) -> None:
    """A burst of >5 POST /test from the same company gets the 6th rejected."""
    from unittest.mock import AsyncMock, MagicMock, patch

    async def _passthrough(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    # Bypass the (resolver + ODataClient) path: the route checks the
    # rate limit dep BEFORE doing any work, so we can leave them
    # mocked-out with minimal happy-path behaviour.
    with (
        patch("piilot_pack_sap.routes.run_in_thread", new=_passthrough),
        patch("piilot_pack_sap.routes.ConnectionResolver") as resolver_cls,
        patch("piilot_pack_sap.routes.ODataClient") as client_cls,
        patch("piilot_pack_sap.routes.repository.set_connection_health"),
    ):
        resolver = MagicMock()
        from piilot_pack_sap.auth import BasicAuth
        from piilot_pack_sap.connection_resolver import ResolvedConnection

        resolver.resolve_for_connection_id = AsyncMock(
            return_value=ResolvedConnection(
                connection_id="conn-1",
                company_id="comp-1",
                label="Sandbox",
                base_url="https://x/sap",
                auth=BasicAuth(username="u", password="p"),
                version="v2",
                auth_mode="basic",
            )
        )
        resolver_cls.return_value = resolver

        odata = MagicMock()
        odata.get_metadata = AsyncMock(
            return_value=(
                '<edmx:Edmx Version="4.0" '
                'xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">'
                '<edmx:DataServices><Schema Namespace="x" '
                'xmlns="http://docs.oasis-open.org/odata/ns/edm">'
                '<EntityType Name="T"><Key><PropertyRef Name="Id"/></Key>'
                '<Property Name="Id" Type="Edm.String" Nullable="false"/>'
                '</EntityType><EntityContainer Name="C">'
                '<EntitySet Name="Es" EntityType="x.T"/></EntityContainer>'
                "</Schema></edmx:DataServices></edmx:Edmx>"
            )
        )
        odata.aclose = AsyncMock()
        client_cls.return_value = odata

        for _ in range(5):
            r = client.post("/plugins/sap/connections/conn-1/test")
            assert r.status_code == 200, r.text
        # 6th refused
        r = client.post("/plugins/sap/connections/conn-1/test")
        assert r.status_code == 429
