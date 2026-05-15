"""Unit tests for ``piilot_pack_sap.odata_client`` using :mod:`respx` mocks.

Tests exercise the client without any network calls. Live sandbox tests
live in ``tests/integration/test_live_sandbox.py``.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from piilot_pack_sap.auth import ApiKeyAuth, BasicAuth
from piilot_pack_sap.odata_client import (
    ODataClient,
    ODataConnectionError,
    ODataHTTPError,
)
from piilot_pack_sap.odata_validator import ValidationError
from piilot_pack_sap.query_builder import ODataQuery

BASE_V2 = "https://example.sap/sap/opu/odata/sap/API_BUSINESS_PARTNER"
BASE_V4 = "https://example.sap/sap/opu/odata4/sap/demo"


@pytest.fixture
def fake_sleep():
    """Drop-in replacement for asyncio.sleep that does not actually wait."""
    calls: list[float] = []

    async def _sleep(seconds: float) -> None:
        calls.append(seconds)

    _sleep.calls = calls  # type: ignore[attr-defined]
    return _sleep


# ---------- Successful GET --------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_request_success_returns_parsed_json() -> None:
    payload = {"d": {"results": [{"BusinessPartner": "1"}]}}
    route = respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        return_value=httpx.Response(200, json=payload)
    )

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="k"), version="v2") as client:
        data = await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert data == payload
    assert route.called
    assert route.calls[0].request.headers["APIKey"] == "k"
    assert route.calls[0].request.headers["Accept"] == "application/json"
    assert "OData-Version" not in route.calls[0].request.headers


@pytest.mark.asyncio
@respx.mock
async def test_request_sends_querystring_with_dollar_params() -> None:
    route = respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        return_value=httpx.Response(200, json={"d": {"results": []}})
    )

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="k"), version="v2") as client:
        await client.request(
            ODataQuery(
                entity_set="A_BusinessPartner",
                select=("BusinessPartner", "FirstName"),
                filter="FirstName eq 'John'",
                top=5,
            )
        )

    sent = str(route.calls[0].request.url)
    assert "%24select=BusinessPartner%2CFirstName" in sent
    assert "%24top=5" in sent
    assert "%24format=json" in sent
    assert "%24filter=FirstName+eq+%27John%27" in sent


@pytest.mark.asyncio
@respx.mock
async def test_request_v4_sets_odata_version_headers() -> None:
    route = respx.get(f"{BASE_V4}/Orders").mock(
        return_value=httpx.Response(200, json={"value": []})
    )

    async with ODataClient(base_url=BASE_V4, auth=ApiKeyAuth(api_key="k"), version="v4") as client:
        await client.request(ODataQuery(entity_set="Orders", top=1))

    headers = route.calls[0].request.headers
    assert headers["OData-Version"] == "4.0"
    assert headers["OData-MaxVersion"] == "4.0"


@pytest.mark.asyncio
@respx.mock
async def test_count_v2_response_parsed_as_int() -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner/$count").mock(
        return_value=httpx.Response(200, text="42")
    )

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="k"), version="v2") as client:
        result = await client.request(ODataQuery(entity_set="A_BusinessPartner", count=True))

    assert result == {"count": 42}


@pytest.mark.asyncio
@respx.mock
async def test_count_v2_response_with_non_integer_raises() -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner/$count").mock(
        return_value=httpx.Response(200, text="not-a-number")
    )

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="k"), version="v2") as client:
        with pytest.raises(ODataHTTPError, match="unexpected"):
            await client.request(ODataQuery(entity_set="A_BusinessPartner", count=True))


# ---------- $metadata -------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_metadata_returns_raw_xml() -> None:
    xml = '<?xml version="1.0"?><edmx:Edmx/>'
    respx.get(f"{BASE_V2}/$metadata").mock(return_value=httpx.Response(200, text=xml))

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="k")) as client:
        result = await client.get_metadata()

    assert result == xml


@pytest.mark.asyncio
@respx.mock
async def test_get_metadata_raises_on_error_status() -> None:
    respx.get(f"{BASE_V2}/$metadata").mock(return_value=httpx.Response(403, text="Forbidden"))

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="bad")) as client:
        with pytest.raises(ODataHTTPError) as exc:
            await client.get_metadata()
    assert exc.value.status == 403


# ---------- BasicAuth integration with client -------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_basic_auth_propagates_through_client() -> None:
    route = respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        return_value=httpx.Response(200, json={"d": {"results": []}})
    )

    async with ODataClient(
        base_url=BASE_V2,
        auth=BasicAuth(username="u", password="p"),
        version="v2",
    ) as client:
        await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    auth_header = route.calls[0].request.headers["Authorization"]
    assert auth_header.startswith("Basic ")


# ---------- Client errors (non-retryable) -----------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
@pytest.mark.asyncio
@respx.mock
async def test_non_retryable_status_raises_immediately(status: int, fake_sleep) -> None:
    route = respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        return_value=httpx.Response(status, text=f"err {status}")
    )

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=3,
    ) as client:
        with pytest.raises(ODataHTTPError) as exc:
            await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert exc.value.status == status
    assert route.call_count == 1  # no retry
    assert fake_sleep.calls == []


# ---------- Retry on 429 + Retry-After --------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_429_retries_then_succeeds_with_retry_after(fake_sleep) -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        side_effect=[
            httpx.Response(429, text="slow down", headers={"Retry-After": "2"}),
            httpx.Response(200, json={"d": {"results": [{"x": 1}]}}),
        ]
    )

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=3,
    ) as client:
        result = await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert result["d"]["results"][0]["x"] == 1
    assert fake_sleep.calls == [2.0]


@pytest.mark.asyncio
@respx.mock
async def test_429_no_retry_after_falls_back_to_backoff(fake_sleep) -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        side_effect=[
            httpx.Response(429, text="slow down"),
            httpx.Response(200, json={"d": {"results": []}}),
        ]
    )

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=3,
    ) as client:
        await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert len(fake_sleep.calls) == 1
    assert 0.0 <= fake_sleep.calls[0] <= 0.5  # jittered from initial 0.5s


@pytest.mark.asyncio
@respx.mock
async def test_429_exhausts_retries_returns_last_response(fake_sleep) -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(return_value=httpx.Response(429, text="slow"))

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=2,
    ) as client:
        with pytest.raises(ODataHTTPError) as exc:
            await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert exc.value.status == 429
    assert len(fake_sleep.calls) == 2  # max_retries attempts before giving up


# ---------- Retry on 5xx ----------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
@pytest.mark.asyncio
@respx.mock
async def test_5xx_is_retried(status: int, fake_sleep) -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        side_effect=[
            httpx.Response(status, text="oops"),
            httpx.Response(200, json={"d": {"results": []}}),
        ]
    )

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=3,
    ) as client:
        result = await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert result == {"d": {"results": []}}
    assert len(fake_sleep.calls) == 1


# ---------- Connection errors -----------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_retries_then_raises(fake_sleep) -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(side_effect=httpx.ConnectError("network down"))

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=2,
    ) as client:
        with pytest.raises(ODataConnectionError) as exc:
            await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert "network down" in str(exc.value)
    assert len(fake_sleep.calls) == 2


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_recovers_on_retry(fake_sleep) -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        side_effect=[
            httpx.ConnectError("transient"),
            httpx.Response(200, json={"d": {"results": []}}),
        ]
    )

    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
        max_retries=3,
    ) as client:
        result = await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    assert result == {"d": {"results": []}}


# ---------- Validation surfaces through client ------------------------------


@pytest.mark.asyncio
async def test_invalid_query_propagates_validation_error_without_network(
    fake_sleep,
) -> None:
    # respx not used — the validator must fail before any HTTP call is made.
    async with ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        version="v2",
        sleep=fake_sleep,
    ) as client:
        with pytest.raises(ValidationError) as exc:
            await client.request(
                ODataQuery(
                    entity_set="A_BusinessPartner",
                    filter="contains(Name, 'foo')",
                )
            )
    assert exc.value.code == "function_call_forbidden"
    assert fake_sleep.calls == []


# ---------- Bad JSON response ----------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_response_raises_odata_http_error() -> None:
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        return_value=httpx.Response(200, text="<html>nope</html>")
    )

    async with ODataClient(base_url=BASE_V2, auth=ApiKeyAuth(api_key="k")) as client:
        with pytest.raises(ODataHTTPError, match="not valid JSON"):
            await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))


# ---------- Lifecycle -------------------------------------------------------


@pytest.mark.asyncio
async def test_constructor_rejects_empty_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        ODataClient(base_url="", auth=ApiKeyAuth(api_key="k"))


@pytest.mark.asyncio
@respx.mock
async def test_external_client_is_not_closed_by_us() -> None:
    external = httpx.AsyncClient()
    respx.get(f"{BASE_V2}/A_BusinessPartner").mock(
        return_value=httpx.Response(200, json={"d": {"results": []}})
    )
    client = ODataClient(
        base_url=BASE_V2,
        auth=ApiKeyAuth(api_key="k"),
        http_client=external,
    )
    async with client:
        await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))
    # External client must still be usable.
    assert not external.is_closed
    await external.aclose()
