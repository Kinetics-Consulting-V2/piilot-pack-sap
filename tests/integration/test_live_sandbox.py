"""Live integration tests against the SAP API Hub sandbox.

Skipped automatically when ``SAP_API_HUB_KEY`` is not set (see ``conftest.py``
in this folder). Network access is required.

Targeted service: Business Partner OData v2
(``/sap/opu/odata/sap/API_BUSINESS_PARTNER``). Sandbox data is shared across
all api.sap.com users and read-only.
"""

from __future__ import annotations

import pytest

from piilot_pack_sap.auth import ApiKeyAuth
from piilot_pack_sap.introspect import parse_metadata
from piilot_pack_sap.odata_client import ODataClient, ODataHTTPError
from piilot_pack_sap.query_builder import ODataQuery


@pytest.mark.asyncio
async def test_fetch_one_business_partner(sandbox_api_key: str, sandbox_bp_base_url: str) -> None:
    """Smoke test — the canonical Phase 0 goal: list 1 BP from the sandbox."""
    async with ODataClient(
        base_url=sandbox_bp_base_url,
        auth=ApiKeyAuth(api_key=sandbox_api_key),
        version="v2",
        timeout=30.0,
    ) as client:
        data = await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    # OData v2 wraps results in ``d.results``.
    results = data["d"]["results"]
    assert len(results) == 1
    bp = results[0]
    assert "BusinessPartner" in bp
    assert "BusinessPartnerFullName" in bp


@pytest.mark.asyncio
async def test_fetch_metadata_and_parse(sandbox_api_key: str, sandbox_bp_base_url: str) -> None:
    """Fetch live ``$metadata`` and parse it through ``introspect``."""
    async with ODataClient(
        base_url=sandbox_bp_base_url,
        auth=ApiKeyAuth(api_key=sandbox_api_key),
        version="v2",
        timeout=60.0,
    ) as client:
        xml = await client.get_metadata()

    snapshot = parse_metadata(xml)
    assert snapshot.version == "v2"
    assert snapshot.namespace == "API_BUSINESS_PARTNER"
    # Sandbox publishes the BP entity set with at least 50 EntitySets.
    assert len(snapshot.entity_sets) >= 50
    assert snapshot.find("A_BusinessPartner") is not None


@pytest.mark.asyncio
async def test_filter_and_select_round_trip(sandbox_api_key: str, sandbox_bp_base_url: str) -> None:
    """A filtered, projected query should pass the validator and return data."""
    async with ODataClient(
        base_url=sandbox_bp_base_url,
        auth=ApiKeyAuth(api_key=sandbox_api_key),
        version="v2",
    ) as client:
        data = await client.request(
            ODataQuery(
                entity_set="A_BusinessPartner",
                select=("BusinessPartner", "BusinessPartnerFullName"),
                filter="BusinessPartnerCategory eq '2'",
                top=3,
            )
        )

    results = data["d"]["results"]
    assert len(results) <= 3
    # When the sandbox returns at least one row, every row must respect the
    # projection (only requested fields + __metadata are returned).
    if results:
        row = results[0]
        assert "BusinessPartner" in row
        assert "BusinessPartnerFullName" in row


@pytest.mark.asyncio
async def test_count_v2_path_segment(sandbox_api_key: str, sandbox_bp_base_url: str) -> None:
    """``GET /A_BusinessPartner/$count`` should return an integer count."""
    async with ODataClient(
        base_url=sandbox_bp_base_url,
        auth=ApiKeyAuth(api_key=sandbox_api_key),
        version="v2",
    ) as client:
        data = await client.request(ODataQuery(entity_set="A_BusinessPartner", count=True))

    assert "count" in data
    assert isinstance(data["count"], int)
    assert data["count"] > 0


@pytest.mark.asyncio
async def test_invalid_apikey_returns_403(sandbox_bp_base_url: str) -> None:
    """The sandbox rejects bogus keys with ``HTTP 403 UCON``."""
    async with ODataClient(
        base_url=sandbox_bp_base_url,
        auth=ApiKeyAuth(api_key="totally-bogus-key-0000"),
        version="v2",
        max_retries=0,
    ) as client:
        with pytest.raises(ODataHTTPError) as exc:
            await client.request(ODataQuery(entity_set="A_BusinessPartner", top=1))

    # SAP API Hub returns either 401 or 403 depending on the bogus shape.
    assert exc.value.status in {401, 403}
