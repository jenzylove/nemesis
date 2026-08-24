from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .discovery import (
    ChainabuseClient,
    DiscoveryProviderError,
    DiscoveryUnavailableError,
    GoPlusAddressClient,
    IncidentNotFoundError,
    _as_utc,
)
from .models import ChainName, DiscoveryCandidate, IncidentDiscovery

ALCHEMY_HOSTS: dict[ChainName, str] = {
    "ethereum": "https://eth-mainnet.g.alchemy.com/v2",
    "base": "https://base-mainnet.g.alchemy.com/v2",
}
TRANSFER_CATEGORIES = ["external", "internal", "erc20", "erc721", "erc1155"]
ENRICHMENT_CANDIDATE_LIMIT = 5
RPC_SHORTLIST_LIMIT = 12


class AlchemyIncidentDiscovery:
    """Historical wallet discovery via Alchemy Transfers API.

    Alchemy is only used to discover candidate transaction hashes. The selected
    transaction is still independently verified by NEMESIS through its normal
    chain RPC provider before tracing or model interpretation.
    """

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_pages: int = 20,
        goplus: GoPlusAddressClient | None = None,
        chainabuse: ChainabuseClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, min(max_pages, 100))
        self.goplus = goplus
        self.chainabuse = chainabuse
        self.transport = transport

    async def _history(self, chain: ChainName, wallet: str) -> list[dict[str, Any]]:
        if not self.api_key:
            raise DiscoveryUnavailableError(
                "Wallet-only discovery requires ALCHEMY_API_KEY. Add a theft transaction hash or configure Alchemy."
            )

        endpoint = f"{ALCHEMY_HOSTS[chain]}/{self.api_key}"
        transfers: list[dict[str, Any]] = []
        page_key: str | None = None

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        ) as client:
            for _ in range(self.max_pages):
                params: dict[str, Any] = {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "fromAddress": wallet,
                    "category": TRANSFER_CATEGORIES,
                    "withMetadata": True,
                    "excludeZeroValue": True,
                    "order": "desc",
                    "maxCount": "0x3e8",
                }
                if page_key:
                    params["pageKey"] = page_key
                try:
                    response = await client.post(
                        endpoint,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "alchemy_getAssetTransfers",
                            "params": [params],
                        },
                        headers={"content-type": "application/json"},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except httpx.HTTPError as exc:
                    raise DiscoveryProviderError(
                        "Alchemy wallet history request failed"
                    ) from exc
                except ValueError as exc:
                    raise DiscoveryProviderError(
                        "Alchemy returned an invalid response"
                    ) from exc

                if payload.get("error"):
                    message = payload["error"].get("message", "Alchemy JSON-RPC error")
                    raise DiscoveryProviderError(
                        f"Alchemy wallet history failed: {message}"
                    )
                result = payload.get("result") or {}
                rows = result.get("transfers") or []
                if not isinstance(rows, list):
                    raise DiscoveryProviderError(
                        "Alchemy wallet history response had no transfer list"
                    )
                transfers.extend(row for row in rows if isinstance(row, dict))
                page_key = result.get("pageKey")
                if not page_key:
                    break

        return transfers

    @staticmethod
    def _timestamp(row: dict[str, Any]) -> datetime | None:
        metadata = row.get("metadata") or {}
        raw = metadata.get("blockTimestamp")
        if not raw:
            return None
        try:
            return _as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sort(candidates: list[DiscoveryCandidate]) -> None:
        candidates.sort(
            key=lambda candidate: (
                candidate.score,
                candidate.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

    def _build_candidates(
        self,
        rows: list[dict[str, Any]],
        wallet: str,
        incident_time: datetime | None,
    ) -> list[DiscoveryCandidate]:
        wallet = wallet.lower()
        incident_time = _as_utc(incident_time)
        grouped: dict[str, dict[str, Any]] = {}

        for row in rows:
            tx_hash = str(row.get("hash") or "").lower()
            sender = str(row.get("from") or "").lower()
            if len(tx_hash) != 66 or sender != wallet:
                continue
            receiver = str(row.get("to") or "").lower() or None
            block_hex = row.get("blockNum")
            try:
                block_number = int(str(block_hex), 16) if block_hex else 0
            except (TypeError, ValueError):
                block_number = 0
            timestamp = self._timestamp(row)

            item = grouped.setdefault(
                tx_hash,
                {
                    "transaction_hash": tx_hash,
                    "block_number": block_number,
                    "timestamp": timestamp,
                    "counterparty": receiver,
                    "outgoing_transfer_count": 0,
                    "categories": set(),
                },
            )
            item["outgoing_transfer_count"] += 1
            category = str(row.get("category") or "").lower()
            if category:
                item["categories"].add(category)
            if not item.get("counterparty") and receiver:
                item["counterparty"] = receiver
            if not item.get("timestamp") and timestamp:
                item["timestamp"] = timestamp

        candidates: list[DiscoveryCandidate] = []
        for item in grouped.values():
            count = item["outgoing_transfer_count"]
            score = 30.0
            reasons = ["wallet is the indexed outgoing transfer sender"]

            if count > 1:
                score += min(36.0, 6.0 * (count - 1))
                reasons.append("multiple outgoing transfers share one transaction")
            if len(item["categories"]) > 1:
                score += min(12.0, 4.0 * (len(item["categories"]) - 1))
                reasons.append("transaction moves multiple asset categories")

            timestamp = item.get("timestamp")
            if incident_time and timestamp:
                hours = abs((timestamp - incident_time).total_seconds()) / 3600
                if hours <= 6:
                    score += 40
                    reasons.append("within six hours of reported incident time")
                elif hours <= 24:
                    score += 30
                    reasons.append("within one day of reported incident time")
                elif hours <= 24 * 7:
                    score += 16
                    reasons.append("within one week of reported incident time")
                else:
                    score -= min(24.0, hours / (24 * 30))

            candidates.append(
                DiscoveryCandidate(
                    transaction_hash=item["transaction_hash"],
                    block_number=item["block_number"],
                    timestamp=timestamp,
                    transaction_from=None,
                    transaction_to=None,
                    counterparty=item.get("counterparty"),
                    outgoing_transfer_count=count,
                    amount_usd=None,
                    score=round(score, 2),
                    reasons=reasons,
                )
            )

        self._sort(candidates)
        return candidates

    async def _enrich_shortlist(
        self, chain: ChainName, candidates: list[DiscoveryCandidate]
    ) -> None:
        """Enrich the serious deterministic shortlist before final selection.

        Provider reputation can influence ranking, but it never substitutes for
        the RPC verification that happens after a transaction is selected.
        """
        shortlist = candidates[:ENRICHMENT_CANDIDATE_LIMIT]

        if self.goplus:
            for candidate in shortlist:
                check = await self.goplus.check(chain, candidate.counterparty)
                if not check.get("available"):
                    continue
                candidate.goplus_flags = list(check.get("flags") or [])
                if check.get("malicious"):
                    candidate.score += 24
                    candidate.reasons.append("GoPlus flags the outgoing counterparty")

        if self.chainabuse:
            # The client caches by address, so repeated counterparties cost one API call.
            for candidate in shortlist:
                check = await self.chainabuse.check(candidate.counterparty)
                if not check.get("available"):
                    continue
                candidate.chainabuse_report_count = check.get("report_count")
                report_count = int(check.get("report_count") or 0)
                if report_count > 0:
                    candidate.score += min(30, 10 + 2 * report_count)
                    candidate.reasons.append("Chainabuse has reports for the outgoing counterparty")

        self._sort(candidates)

    async def discover(
        self, chain: ChainName, wallet: str, incident_time: datetime | None = None
    ) -> IncidentDiscovery:
        candidates = self._build_candidates(
            await self._history(chain, wallet), wallet, incident_time
        )
        if not candidates:
            raise IncidentNotFoundError(
                "No deterministic outgoing transfer candidate was found for this wallet. Add an approximate incident time or a known theft transaction hash."
            )

        await self._enrich_shortlist(chain, candidates)
        top = candidates[0]
        return IncidentDiscovery(
            source="alchemy",
            selected_transaction_hash=top.transaction_hash,
            selected_score=top.score,
            candidate_count=len(candidates),
            incident_time=_as_utc(incident_time),
            candidates=candidates[:RPC_SHORTLIST_LIMIT],
        )
