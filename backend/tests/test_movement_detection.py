import json
from datetime import datetime, timezone

import httpx
import pytest

from app.models import ERC20Transfer, NormalizedTransaction
from app.movement import (
    AlchemyHistoricalMovementDetector,
    BitqueryRealtimeMovementDetector,
    HybridMovementProvider,
)

ADDRESS = "0x" + "11" * 20
DEST = "0x" + "22" * 20
TOKEN = "0x" + "33" * 20
TX = "0x" + "ab" * 32


def normalized(block=1500, outgoing=True):
    return NormalizedTransaction(
        hash=TX,
        chain="ethereum",
        block_number=block,
        timestamp=datetime(2026, 8, 23, tzinfo=timezone.utc),
        status="success",
        from_address=ADDRESS if outgoing else DEST,
        to_address=DEST,
        native_value_wei="0",
        input="0x",
        erc20_transfers=[
            ERC20Transfer(
                log_index=1,
                token_contract=TOKEN,
                from_address=ADDRESS if outgoing else DEST,
                to_address=DEST if outgoing else ADDRESS,
                raw_amount="10",
            )
        ],
    )


class RpcStub:
    def __init__(self, tx=None, latest=2000):
        self.tx = tx or normalized()
        self.latest = latest
        self.fallback_calls = 0

    async def _call(self, chain, method, params):
        assert chain == "ethereum"
        assert method == "eth_blockNumber"
        return hex(self.latest)

    async def get_normalized_transaction(self, chain, tx_hash):
        assert tx_hash == TX
        return self.tx

    async def get_address_movements(self, chain, address, after_block, max_blocks=20):
        self.fallback_calls += 1
        return after_block + max_blocks, []

    async def get_bridge_evidence(self, *args, **kwargs):
        return None

    async def resolve_bridge_destination(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_alchemy_historical_detector_returns_earliest_outgoing_transaction():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        params = body["params"][0]
        assert params["fromBlock"] == hex(101)
        assert params["order"] == "asc"
        assert params["fromAddress"] == ADDRESS
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "transfers": [
                        {"hash": TX, "blockNum": hex(1500), "from": ADDRESS, "to": DEST},
                        {"hash": TX, "blockNum": hex(1500), "from": ADDRESS, "to": DEST},
                    ]
                },
            },
        )

    detector = AlchemyHistoricalMovementDetector("alchemy-key", transport=httpx.MockTransport(handler))
    rows = await detector.find_next("ethereum", ADDRESS, 100)
    assert rows == [
        {
            "transaction_hash": TX,
            "block_number": 1500,
            "kind": "indexed",
            "direction": "out",
            "detector": "alchemy_historical",
            "categories": [],
        }
    ]


@pytest.mark.asyncio
async def test_bitquery_realtime_detector_uses_realtime_dataset_and_block_cursor():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert "dataset: realtime" in body["query"]
        assert "network: eth" in body["query"]
        assert 'Block: {Number: {gt: "1900"}}' in body["query"]
        assert body["variables"] == {"wallet": ADDRESS}
        return httpx.Response(
            200,
            json={
                "data": {
                    "EVM": {
                        "Transfers": [
                            {
                                "Block": {"Number": "1950"},
                                "Transaction": {"Hash": TX},
                                "Transfer": {"Sender": ADDRESS, "Receiver": DEST, "Currency": {"SmartContract": TOKEN, "Native": False}},
                            }
                        ]
                    }
                }
            },
        )

    detector = BitqueryRealtimeMovementDetector(
        "bitquery-key", transport=httpx.MockTransport(handler)
    )
    rows = await detector.find_outgoing("ethereum", ADDRESS, 1900)
    assert rows[0]["detector"] == "bitquery_realtime"
    assert rows[0]["transaction_hash"] == TX


@pytest.mark.asyncio
async def test_hybrid_uses_alchemy_for_old_cursor_and_rpc_verifies():
    class Historical:
        async def find_next(self, chain, address, after_block):
            return [{"transaction_hash": TX, "block_number": 1500, "kind": "indexed", "direction": "out", "detector": "alchemy_historical"}]

    rpc = RpcStub(latest=5000)
    provider = HybridMovementProvider(rpc, historical=Historical(), realtime=None, realtime_lag_blocks=256)
    cursor, moves = await provider.get_address_movements("ethereum", ADDRESS, 100)
    assert cursor == 1500
    assert moves[0]["verified_by"] == "json_rpc"
    assert rpc.fallback_calls == 0


@pytest.mark.asyncio
async def test_hybrid_uses_bitquery_near_head_and_rpc_rejects_false_signal():
    class Realtime:
        async def find_outgoing(self, chain, address, after_block):
            return [{"transaction_hash": TX, "block_number": 1995, "kind": "indexed", "direction": "out", "detector": "bitquery_realtime"}]

    rpc = RpcStub(tx=normalized(block=1995, outgoing=False), latest=2000)
    provider = HybridMovementProvider(rpc, historical=None, realtime=Realtime(), realtime_lag_blocks=256)
    cursor, moves = await provider.get_address_movements("ethereum", ADDRESS, 1900)
    assert cursor == 2000
    assert moves == []
    assert rpc.fallback_calls == 0
