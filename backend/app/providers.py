import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx

from .models import ChainName, ERC20Transfer, NativeTransfer, NFTTransfer, NormalizedTransaction

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
BASE_L1_STANDARD_BRIDGE = "0x3154cf16ccdb4c6d922629664174b904d80f2c35"
BASE_OPTIMISM_PORTAL = "0x49048044d57e1c92a77f79988d21fa8faf74e97e"
BASE_L2_STANDARD_BRIDGE = "0x4200000000000000000000000000000000000010"


class BlockchainProvider(ABC):
    @abstractmethod
    async def get_normalized_transaction(self, chain: ChainName, tx_hash: str) -> NormalizedTransaction:
        raise NotImplementedError

    @abstractmethod
    async def get_address_movements(
        self, chain: ChainName, address: str, after_block: int, max_blocks: int = 20,
        asset: str | None = None,
    ) -> tuple[int, list[dict]]:
        raise NotImplementedError

    async def get_bridge_evidence(
        self,
        chain: ChainName,
        transaction: NormalizedTransaction,
        tracked_address: str,
        asset: str,
        amount: str,
    ) -> dict | None:
        return None

    async def resolve_bridge_destination(self, bridge_evidence: dict) -> dict | None:
        return None

    async def get_indexed_native_transfers(
        self, chain: ChainName, transaction: NormalizedTransaction, source: str
    ) -> list[NativeTransfer]:
        """Indexed native transfers a receipt cannot encode. Empty when unavailable."""
        return []


def _hex_int(value: str | None) -> int:
    return int(value or "0x0", 16)


def _topic_address(topic: str) -> str:
    if not isinstance(topic, str) or len(topic) != 66:
        raise ValueError("invalid indexed address topic")
    return "0x" + topic[-40:].lower()


def decode_erc20_transfer_logs(logs: list[dict]) -> list[ERC20Transfer]:
    transfers = []
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) != 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
            continue
        address = log.get("address")
        data = log.get("data")
        if not isinstance(address, str) or len(address) != 42 or not isinstance(data, str):
            continue
        transfers.append(
            ERC20Transfer(
                log_index=_hex_int(log.get("logIndex")),
                token_contract=address.lower(),
                from_address=_topic_address(topics[1]),
                to_address=_topic_address(topics[2]),
                raw_amount=str(_hex_int(data)),
            )
        )
    return transfers



def decode_erc721_transfer_logs(logs: list[dict]) -> list[NFTTransfer]:
    transfers = []
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) != 4 or str(topics[0]).lower() != TRANSFER_TOPIC:
            continue
        address = log.get("address")
        if not isinstance(address, str) or len(address) != 42:
            continue
        transfers.append(
            NFTTransfer(
                log_index=_hex_int(log.get("logIndex")),
                token_contract=address.lower(),
                from_address=_topic_address(topics[1]),
                to_address=_topic_address(topics[2]),
                token_id=str(_hex_int(topics[3])),
            )
        )
    return transfers

class RpcProviderError(RuntimeError):
    pass


class JsonRpcProvider(BlockchainProvider):
    def __init__(self, rpc_urls: dict[ChainName, str], timeout_seconds: float = 20, transport: httpx.AsyncBaseTransport | None = None):
        self.rpc_urls = rpc_urls
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def _call(self, chain: ChainName, method: str, params: list) -> dict | list | str | None:
        url = self.rpc_urls.get(chain)
        if not url:
            raise RpcProviderError(f"RPC URL is not configured for {chain}")
        last_error = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        retry_after = response.headers.get("retry-after")
                        delay = min(2.0, float(retry_after)) if retry_after and retry_after.replace(".", "", 1).isdigit() else 0.25 * (2 ** attempt)
                        last_error = RpcProviderError(f"RPC {method} provider throttled or unavailable ({response.status_code})")
                        if attempt < 2:
                            await asyncio.sleep(delay)
                            continue
                        raise last_error
                    response.raise_for_status()
                    payload = response.json()
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt < 2:
                        await asyncio.sleep(0.25 * (2 ** attempt))
                        continue
                    raise RpcProviderError(f"RPC {method} request failed after bounded retries") from exc
        if payload.get("jsonrpc") != "2.0" or payload.get("id") != 1:
            raise RpcProviderError(f"RPC {method} returned an invalid response")
        if payload.get("error"):
            raise RpcProviderError(
                f"RPC {method} failed: {payload['error'].get('message', 'provider error')}"
            )
        return payload.get("result")
    async def get_normalized_transaction(self, chain: ChainName, tx_hash: str) -> NormalizedTransaction:
        transaction = await self._call(chain, "eth_getTransactionByHash", [tx_hash])
        if not transaction:
            raise LookupError("transaction not found")
        receipt = await self._call(chain, "eth_getTransactionReceipt", [tx_hash])
        if not receipt:
            raise LookupError("transaction receipt not found")
        block_hex = transaction.get("blockNumber") or receipt.get("blockNumber")
        if not block_hex:
            raise LookupError("transaction is pending and has no confirmed block")
        block = await self._call(chain, "eth_getBlockByNumber", [block_hex, False])
        if not block:
            raise LookupError("transaction block not found")
        if str(receipt.get("transactionHash", transaction["hash"])).lower() != str(
            transaction["hash"]
        ).lower():
            raise RpcProviderError("transaction and receipt hashes do not match")
        if receipt.get("blockNumber") and receipt["blockNumber"] != block_hex:
            raise RpcProviderError("transaction and receipt block numbers do not match")
        return NormalizedTransaction(
            hash=str(transaction["hash"]).lower(),
            chain=chain,
            block_number=_hex_int(block_hex),
            timestamp=datetime.fromtimestamp(_hex_int(block.get("timestamp")), tz=timezone.utc),
            status="success" if _hex_int(receipt.get("status")) == 1 else "failed",
            from_address=str(transaction["from"]).lower(),
            to_address=str(transaction["to"]).lower() if transaction.get("to") else None,
            native_value_wei=str(_hex_int(transaction.get("value"))),
            input=transaction.get("input") or "0x",
            erc20_transfers=decode_erc20_transfer_logs(receipt.get("logs") or []),
            nft_transfers=decode_erc721_transfer_logs(receipt.get("logs") or []),
        )

    async def get_address_movements(
        self, chain: ChainName, address: str, after_block: int, max_blocks: int = 20,
        asset: str | None = None,
    ) -> tuple[int, list[dict]]:
        latest = _hex_int(await self._call(chain, "eth_blockNumber", []))
        end = min(latest, after_block + max_blocks)
        if end <= after_block:
            return latest, []
        target = address.lower()
        found = {}
        for number in range(after_block + 1, end + 1):
            block = await self._call(chain, "eth_getBlockByNumber", [hex(number), True]) or {}
            for tx in block.get("transactions") or []:
                if str(tx.get("from", "")).lower() == target or str(tx.get("to", "")).lower() == target:
                    tx_hash = str(tx["hash"]).lower()
                    found[tx_hash] = {
                        "transaction_hash": tx_hash,
                        "block_number": number,
                        "kind": "native_or_contract",
                        "direction": "out" if str(tx.get("from", "")).lower() == target else "in",
                    }
        padded = "0x" + "0" * 24 + target[2:]
        for direction, topics in (
            ("out", [TRANSFER_TOPIC, padded]),
            ("in", [TRANSFER_TOPIC, None, padded]),
        ):
            for start in range(after_block + 1, end + 1, 10):
                logs = await self._call(
                    chain,
                    "eth_getLogs",
                    [
                        {
                            "fromBlock": hex(start),
                            "toBlock": hex(min(end, start + 9)),
                            "topics": topics,
                        }
                    ],
                ) or []
                for log in logs:
                    tx_hash = str(log["transactionHash"]).lower()
                    movement = {
                        "transaction_hash": tx_hash,
                        "block_number": _hex_int(log.get("blockNumber")),
                        "kind": "erc20",
                        "direction": direction,
                    }
                    if tx_hash not in found or direction == "out":
                        found[tx_hash] = movement
        return end, sorted(found.values(), key=lambda item: (item["block_number"], item["transaction_hash"]))

    async def get_bridge_evidence(
        self,
        chain: ChainName,
        transaction: NormalizedTransaction,
        tracked_address: str,
        asset: str,
        amount: str,
    ) -> dict | None:
        destination = (transaction.to_address or "").lower()
        if chain == "ethereum" and destination in {BASE_L1_STANDARD_BRIDGE, BASE_OPTIMISM_PORTAL}:
            destination_chain = "base"
            name = "Base L1 Standard Bridge" if destination == BASE_L1_STANDARD_BRIDGE else "Base Optimism Portal"
        elif chain == "base" and destination == BASE_L2_STANDARD_BRIDGE:
            destination_chain = "ethereum"
            name = "Base L2 Standard Bridge"
        else:
            return None

        tracked_address = tracked_address.lower()
        tracked_amount = max(0, int(amount))
        movement_amount = 0
        movement_refs = []
        if asset == "native":
            if transaction.from_address == tracked_address and int(transaction.native_value_wei) > 0:
                movement_amount = min(int(transaction.native_value_wei), tracked_amount)
                movement_refs = ["transaction.native_value_wei"]
        else:
            for index, transfer in enumerate(transaction.erc20_transfers):
                if (
                    transfer.from_address == tracked_address
                    and transfer.to_address == destination
                    and transfer.token_contract == asset
                    and int(transfer.raw_amount) > 0
                ):
                    available = max(0, tracked_amount - movement_amount)
                    if available <= 0:
                        break
                    movement_amount += min(int(transfer.raw_amount), available)
                    movement_refs.append(f"transaction.erc20_transfers[{index}]")
        if movement_amount <= 0:
            return None

        return {
            "bridge_name": name,
            "source_chain": chain,
            "source_transaction": transaction.hash,
            "bridge_contract": destination,
            "asset": asset,
            "amount": str(movement_amount),
            "destination_chain": destination_chain,
            "destination_address": None,
            "destination_transaction_hash": None,
            "source": "Base official contract registry + JSON RPC transaction evidence",
            "evidence_type": "official_contract_exact_match_and_tracked_asset_transfer",
            "evidence_references": movement_refs,
            "provenance": ["json_rpc", transaction.hash, *movement_refs, "base_official_contract_registry"],
        }
