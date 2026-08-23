from datetime import datetime, timezone
import json

import httpx
import pytest

from app.alchemy_discovery import AlchemyIncidentDiscovery

WALLET = "0x" + "11" * 20
COUNTERPARTY = "0x" + "22" * 20
RISKY_COUNTERPARTY = "0x" + "44" * 20
TX_HASH = "0x" + "ab" * 32
TX_HASH_2 = "0x" + "cd" * 32


def transfer(tx_hash, timestamp, category="erc20", to=COUNTERPARTY):
    return {
        "blockNum": "0x7b",
        "hash": tx_hash,
        "from": WALLET,
        "to": to,
        "value": 1,
        "asset": "USDC",
        "category": category,
        "metadata": {"blockTimestamp": timestamp},
    }


@pytest.mark.asyncio
async def test_alchemy_historical_discovery_paginates_and_ranks_incident_time():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.host == "eth-mainnet.g.alchemy.com"
        assert request.url.path.endswith("/fixture-key")
        body = json.loads(request.content)
        assert body["method"] == "alchemy_getAssetTransfers"
        params = body["params"][0]
        assert params["fromAddress"] == WALLET
        assert params["fromBlock"] == "0x0"
        assert params["toBlock"] == "latest"
        assert params["withMetadata"] is True
        assert params["order"] == "desc"
        if calls == 1:
            assert "pageKey" not in params
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "transfers": [
                            transfer(TX_HASH_2, "2026-08-20T12:00:00Z"),
                        ],
                        "pageKey": "next-page",
                    },
                },
            )
        assert params["pageKey"] == "next-page"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "transfers": [
                        transfer(TX_HASH, "2026-08-22T12:02:00Z", "erc20"),
                        transfer(TX_HASH, "2026-08-22T12:02:00Z", "external"),
                    ]
                },
            },
        )

    discovery = AlchemyIncidentDiscovery(
        api_key="fixture-key",
        transport=httpx.MockTransport(handler),
    )
    result = await discovery.discover(
        "ethereum",
        WALLET,
        datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert calls == 2
    assert result.source == "alchemy"
    assert result.selected_transaction_hash == TX_HASH
    assert result.candidate_count == 2
    assert result.candidates[0].outgoing_transfer_count == 2
    assert any("reported incident time" in reason for reason in result.candidates[0].reasons)


@pytest.mark.asyncio
async def test_alchemy_discovery_without_incident_time_uses_full_history_and_fanout():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        params = body["params"][0]
        assert params["fromBlock"] == "0x0"
        assert params["toBlock"] == "latest"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "transfers": [
                        transfer(TX_HASH, "2024-07-18T07:00:00Z", "erc20"),
                        transfer(TX_HASH, "2024-07-18T07:00:00Z", "erc721"),
                        transfer(TX_HASH, "2024-07-18T07:00:00Z", "external"),
                        transfer(TX_HASH_2, "2026-08-22T12:00:00Z", "erc20"),
                    ]
                },
            },
        )

    discovery = AlchemyIncidentDiscovery(
        api_key="fixture-key",
        transport=httpx.MockTransport(handler),
    )
    result = await discovery.discover("ethereum", WALLET)
    assert result.selected_transaction_hash == TX_HASH
    assert result.incident_time is None
    assert result.candidates[0].outgoing_transfer_count == 3
    assert any("multiple outgoing transfers" in reason for reason in result.candidates[0].reasons)


@pytest.mark.asyncio
async def test_enrichment_can_rerank_lower_candidate_before_selection():
    class GoPlusStub:
        async def check(self, chain, address):
            return {"available": True, "malicious": False, "flags": []}

    class ChainabuseStub:
        async def check(self, address):
            if address == RISKY_COUNTERPARTY:
                return {"available": True, "report_count": 6, "max_confidence": 90}
            return {"available": True, "report_count": 0, "max_confidence": None}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "transfers": [
                        transfer(TX_HASH, "2026-03-23T09:54:47Z", "erc20", COUNTERPARTY),
                        transfer(TX_HASH, "2026-03-23T09:54:47Z", "external", COUNTERPARTY),
                        transfer(TX_HASH_2, "2026-03-22T16:19:59Z", "erc20", RISKY_COUNTERPARTY),
                    ]
                },
            },
        )

    discovery = AlchemyIncidentDiscovery(
        api_key="fixture-key",
        goplus=GoPlusStub(),
        chainabuse=ChainabuseStub(),
        transport=httpx.MockTransport(handler),
    )
    result = await discovery.discover("ethereum", WALLET)

    assert result.selected_transaction_hash == TX_HASH_2
    assert result.candidates[0].chainabuse_report_count == 6
    assert any("Chainabuse has reports" in reason for reason in result.candidates[0].reasons)


@pytest.mark.asyncio
async def test_alchemy_base_uses_base_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "base-mainnet.g.alchemy.com"
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"transfers": []}},
        )

    discovery = AlchemyIncidentDiscovery(
        api_key="fixture-key",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LookupError):
        await discovery.discover("base", WALLET)
