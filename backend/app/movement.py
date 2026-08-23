from __future__ import annotations

from typing import Any

import httpx

from .alchemy_discovery import ALCHEMY_HOSTS, TRANSFER_CATEGORIES
from .discovery import BITQUERY_NETWORKS
from .models import ChainName, NormalizedTransaction
from .providers import JsonRpcProvider, RpcProviderError


class MovementDetectionError(RuntimeError):
    pass


class AlchemyHistoricalMovementDetector:
    """Find the earliest outgoing historical transaction after a branch cursor."""

    def __init__(self, api_key: str, timeout_seconds: float = 20.0, transport=None):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def find_next(self, chain: ChainName, address: str, after_block: int) -> list[dict]:
        if not self.api_key:
            return []
        endpoint = f"{ALCHEMY_HOSTS[chain]}/{self.api_key}"
        params: dict[str, Any] = {
            "fromBlock": hex(after_block + 1),
            "toBlock": "latest",
            "fromAddress": address.lower(),
            "category": TRANSFER_CATEGORIES,
            "withMetadata": False,
            "excludeZeroValue": True,
            "order": "asc",
            "maxCount": "0x64",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.post(
                    endpoint,
                    json={"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [params]},
                    headers={"content-type": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MovementDetectionError("Alchemy historical movement request failed") from exc
        if payload.get("error"):
            raise MovementDetectionError(
                f"Alchemy historical movement failed: {payload['error'].get('message', 'provider error')}"
            )
        rows = (payload.get("result") or {}).get("transfers") or []
        grouped: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            tx_hash = str(row.get("hash") or "").lower()
            try:
                block = int(str(row.get("blockNum")), 16)
            except (TypeError, ValueError):
                continue
            if len(tx_hash) == 66 and block > after_block:
                grouped[tx_hash] = min(block, grouped.get(tx_hash, block))
        return [
            {"transaction_hash": tx_hash, "block_number": block, "kind": "indexed", "direction": "out", "detector": "alchemy_historical"}
            for tx_hash, block in sorted(grouped.items(), key=lambda item: (item[1], item[0]))
        ]


class BitqueryRealtimeMovementDetector:
    """Query Bitquery's realtime dataset for fresh outgoing transfers."""

    def __init__(
        self,
        access_token: str,
        endpoint: str = "https://streaming.bitquery.io/graphql",
        timeout_seconds: float = 20.0,
        transport=None,
    ):
        self.access_token = access_token
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def find_outgoing(self, chain: ChainName, address: str, after_block: int) -> list[dict]:
        if not self.access_token:
            return []
        cursor = max(0, int(after_block))
        query = f"""
query RealtimeOutgoing($wallet: String!) {{
  EVM(dataset: realtime, network: {BITQUERY_NETWORKS[chain]}) {{
    Transfers(
      limit: {{count: 100}}
      orderBy: {{ascending: Block_Number}}
      where: {{
        Transfer: {{Sender: {{is: $wallet}}}}
        Block: {{Number: {{gt: \"{cursor}\"}}}}
      }}
    ) {{
      Block {{ Number }}
      Transaction {{ Hash }}
      Transfer {{ Sender Receiver Currency {{ SmartContract Native }} }}
    }}
  }}
}}
""".strip()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = await client.post(
                    self.endpoint,
                    json={"query": query, "variables": {"wallet": address.lower()}},
                    headers={"authorization": f"Bearer {self.access_token}", "content-type": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MovementDetectionError("Bitquery realtime movement request failed") from exc
        if payload.get("errors"):
            raise MovementDetectionError(
                f"Bitquery realtime movement failed: {payload['errors'][0].get('message', 'GraphQL error')}"
            )
        rows = (((payload.get("data") or {}).get("EVM") or {}).get("Transfers") or [])
        grouped: dict[str, int] = {}
        for row in rows:
            tx = row.get("Transaction") or {}
            block = row.get("Block") or {}
            tx_hash = str(tx.get("Hash") or "").lower()
            try:
                block_number = int(block.get("Number"))
            except (TypeError, ValueError):
                continue
            if len(tx_hash) == 66 and block_number > cursor:
                grouped[tx_hash] = min(block_number, grouped.get(tx_hash, block_number))
        return [
            {"transaction_hash": tx_hash, "block_number": block, "kind": "indexed", "direction": "out", "detector": "bitquery_realtime"}
            for tx_hash, block in sorted(grouped.items(), key=lambda item: (item[1], item[0]))
        ]


class HybridMovementProvider:
    """Historical catch-up + realtime detection, with RPC as the verifier and fallback."""

    def __init__(
        self,
        rpc: JsonRpcProvider,
        historical: AlchemyHistoricalMovementDetector | None = None,
        realtime: BitqueryRealtimeMovementDetector | None = None,
        realtime_lag_blocks: int = 256,
    ):
        self.rpc = rpc
        self.historical = historical
        self.realtime = realtime
        self.realtime_lag_blocks = max(20, realtime_lag_blocks)

    async def _latest(self, chain: ChainName) -> int:
        value = await self.rpc._call(chain, "eth_blockNumber", [])
        return int(str(value), 16)

    @staticmethod
    def _is_verified_outgoing(tx: NormalizedTransaction, address: str) -> bool:
        address = address.lower()
        if tx.from_address == address and int(tx.native_value_wei) > 0:
            return True
        return any(transfer.from_address == address for transfer in tx.erc20_transfers)

    async def _verify(self, chain: ChainName, address: str, candidates: list[dict]) -> list[dict]:
        verified = []
        for candidate in candidates:
            try:
                tx = await self.rpc.get_normalized_transaction(chain, candidate["transaction_hash"])
            except (LookupError, RpcProviderError):
                continue
            if not self._is_verified_outgoing(tx, address):
                continue
            verified.append({**candidate, "block_number": tx.block_number, "verified_by": "json_rpc"})
        return sorted(verified, key=lambda item: (item["block_number"], item["transaction_hash"]))

    async def get_address_movements(
        self, chain: ChainName, address: str, after_block: int, max_blocks: int = 20
    ) -> tuple[int, list[dict]]:
        latest = await self._latest(chain)
        lag = max(0, latest - after_block)

        if lag > self.realtime_lag_blocks and self.historical:
            try:
                historical = await self.historical.find_next(chain, address, after_block)
                verified = await self._verify(chain, address, historical[:10])
                if verified:
                    return verified[0]["block_number"], [verified[0]]
                return latest, []
            except MovementDetectionError:
                pass

        if self.realtime:
            try:
                realtime = await self.realtime.find_outgoing(chain, address, after_block)
                verified = await self._verify(chain, address, realtime[:10])
                if verified:
                    return verified[0]["block_number"], [verified[0]]
                return latest, []
            except MovementDetectionError:
                pass

        return await self.rpc.get_address_movements(chain, address, after_block, max_blocks)

    async def get_normalized_transaction(self, chain: ChainName, tx_hash: str):
        return await self.rpc.get_normalized_transaction(chain, tx_hash)

    async def get_bridge_evidence(self, *args, **kwargs):
        return await self.rpc.get_bridge_evidence(*args, **kwargs)

    async def resolve_bridge_destination(self, *args, **kwargs):
        return await self.rpc.resolve_bridge_destination(*args, **kwargs)
