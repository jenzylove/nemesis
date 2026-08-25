from __future__ import annotations

from typing import Any

import httpx

from .alchemy_discovery import ALCHEMY_HOSTS, TRANSFER_CATEGORIES
from .discovery import BITQUERY_NETWORKS
from .models import ChainName, NativeTransfer, NormalizedTransaction
from .providers import JsonRpcProvider, RpcProviderError


# How many indexed candidates may be RPC-verified for a single hop. Bounded so a
# noisy address cannot consume provider budget.
MOVEMENT_CANDIDATE_LIMIT = 25


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
        categories: dict[str, set[str]] = {}
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
                category = str(row.get("category") or "").lower()
                if category:
                    categories.setdefault(tx_hash, set()).add(category)
        return [
            {
                "transaction_hash": tx_hash,
                "block_number": block,
                "kind": "indexed",
                "direction": "out",
                "detector": "alchemy_historical",
                # Which asset class moved. A drained address emits a great deal of
                # unrelated traffic, including address-poisoning spam, so the
                # trace engine uses this to reach for the transactions that can
                # actually carry the asset it is following.
                "categories": sorted(categories.get(tx_hash, set())),
            }
            for tx_hash, block in sorted(grouped.items(), key=lambda item: (item[1], item[0]))
        ]


class AlchemyIndexedTransferResolver:
    """Reveal native movement that a transaction receipt cannot encode.

    A contract forwarding native value produces an internal call. Receipts carry
    logs, not internal calls, so `eth_getTransactionReceipt` cannot expose it and
    a branch whose funds moved that way looks motionless. Alchemy indexes those
    calls, so it is used to make the movement visible.

    This never replaces deterministic evidence. RPC still proves the transaction
    exists, succeeded, and belongs to the chain; the index only reveals a
    transfer inside it that RPC does not encode, and every transfer produced here
    is tagged with its provenance.
    """

    def __init__(self, api_key: str, timeout_seconds: float = 20.0, transport=None):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def internal_native_transfers(
        self, chain: ChainName, transaction_hash: str, block_number: int, source: str
    ) -> list[NativeTransfer]:
        if not self.api_key:
            return []
        source = source.lower()
        transaction_hash = transaction_hash.lower()
        endpoint = f"{ALCHEMY_HOSTS[chain]}/{self.api_key}"
        params: dict[str, Any] = {
            "fromBlock": hex(int(block_number)),
            "toBlock": hex(int(block_number)),
            "fromAddress": source,
            "category": ["internal", "external"],
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
            raise MovementDetectionError("Alchemy indexed transfer request failed") from exc
        if payload.get("error"):
            raise MovementDetectionError(
                f"Alchemy indexed transfer lookup failed: {payload['error'].get('message', 'provider error')}"
            )
        transfers: list[NativeTransfer] = []
        for row in (payload.get("result") or {}).get("transfers") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("hash") or "").lower() != transaction_hash:
                continue
            if str(row.get("from") or "").lower() != source:
                continue
            destination = str(row.get("to") or "").lower()
            if len(destination) != 42 or not destination.startswith("0x"):
                continue
            if destination == source:
                continue
            raw = (row.get("rawContract") or {}).get("value")
            try:
                amount = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            transfers.append(NativeTransfer(
                from_address=source,
                to_address=destination,
                raw_amount=str(amount),
                provenance=[
                    "alchemy_getAssetTransfers",
                    f"category:{row.get('category') or 'internal'}",
                    transaction_hash,
                ],
            ))
        return transfers


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
        indexed_transfers: AlchemyIndexedTransferResolver | None = None,
    ):
        self.rpc = rpc
        self.historical = historical
        self.realtime = realtime
        self.realtime_lag_blocks = max(20, realtime_lag_blocks)
        self.indexed_transfers = indexed_transfers

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
            verified_by = "json_rpc"
            if not self._is_verified_outgoing(tx, address):
                # The receipt shows no outgoing value, which is also what a
                # contract-forwarded internal transfer looks like. Consult the
                # index before concluding the address did not move funds.
                try:
                    internal = await self.get_indexed_native_transfers(chain, tx, address)
                except MovementDetectionError:
                    continue
                if not internal:
                    continue
                verified_by = "json_rpc+alchemy_internal"
            verified.append({**candidate, "block_number": tx.block_number, "verified_by": verified_by})
        return sorted(verified, key=lambda item: (item["block_number"], item["transaction_hash"]))

    async def get_address_movements(
        self, chain: ChainName, address: str, after_block: int, max_blocks: int = 20
    ) -> tuple[int, list[dict]]:
        latest = await self._latest(chain)
        lag = max(0, latest - after_block)

        # Several verified candidates are returned, not just the earliest. Only
        # some of an address's outgoing transactions carry the asset a branch is
        # following, so the trace engine needs the choice. The cursor still
        # advances to the earliest of them, so nothing is skipped.
        if lag > self.realtime_lag_blocks and self.historical:
            try:
                historical = await self.historical.find_next(chain, address, after_block)
                verified = await self._verify(chain, address, historical[:MOVEMENT_CANDIDATE_LIMIT])
                if verified:
                    return verified[0]["block_number"], verified
                return latest, []
            except MovementDetectionError:
                pass

        if self.realtime:
            try:
                realtime = await self.realtime.find_outgoing(chain, address, after_block)
                verified = await self._verify(chain, address, realtime[:MOVEMENT_CANDIDATE_LIMIT])
                if verified:
                    return verified[0]["block_number"], verified
                return latest, []
            except MovementDetectionError:
                pass

        return await self.rpc.get_address_movements(chain, address, after_block, max_blocks)

    async def get_normalized_transaction(self, chain: ChainName, tx_hash: str):
        return await self.rpc.get_normalized_transaction(chain, tx_hash)

    async def get_indexed_native_transfers(
        self, chain: ChainName, transaction: NormalizedTransaction, source: str
    ) -> list[NativeTransfer]:
        """Native transfers inside a verified transaction that its receipt omits.

        Raises MovementDetectionError when the index cannot be reached, so the
        caller can tell "the evidence says nothing moved" apart from "NEMESIS
        could not retrieve the evidence".
        """
        if not self.indexed_transfers:
            return []
        return await self.indexed_transfers.internal_native_transfers(
            chain, transaction.hash, transaction.block_number, source
        )

    async def get_bridge_evidence(self, *args, **kwargs):
        return await self.rpc.get_bridge_evidence(*args, **kwargs)

    async def resolve_bridge_destination(self, *args, **kwargs):
        return await self.rpc.resolve_bridge_destination(*args, **kwargs)
