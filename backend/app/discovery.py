from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

import httpx

from .models import ChainName, DiscoveryCandidate, IncidentDiscovery


BITQUERY_NETWORKS: dict[ChainName, str] = {"ethereum": "eth", "base": "base"}
GOPLUS_CHAIN_IDS: dict[ChainName, str] = {"ethereum": "1", "base": "8453"}
DISCOVERY_TIME_WINDOW = timedelta(days=7)

GOPLUS_RISK_KEYS = {
    "blackmail_activities",
    "cybercrime",
    "darkweb_transactions",
    "fake_kyc",
    "financial_crime",
    "gas_abuse",
    "honeypot_related_address",
    "malicious_mining_activities",
    "mixer",
    "money_laundering",
    "phishing_activities",
    "sanctioned",
    "stealing_attack",
}


class DiscoveryUnavailableError(RuntimeError):
    pass


class DiscoveryProviderError(RuntimeError):
    pass


class IncidentNotFoundError(LookupError):
    pass


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bitquery_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


class GoPlusAddressClient:
    """Best-effort malicious-address enrichment. It never supplies chain facts."""

    def __init__(
        self,
        base_url: str = "https://api.gopluslabs.io/api/v1",
        access_token: str = "",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._cache: dict[tuple[str, str], dict] = {}

    async def check(self, chain: ChainName, address: str | None) -> dict:
        if not address:
            return {"available": False, "malicious": False, "flags": []}
        key = (chain, address.lower())
        if key in self._cache:
            return self._cache[key]
        headers = {"accept": "application/json"}
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}/address_security/{address}",
                    params={"chain_id": GOPLUS_CHAIN_IDS[chain]},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            result = {"available": False, "malicious": False, "flags": []}
            self._cache[key] = result
            return result

        raw = payload.get("result") if isinstance(payload, dict) else None
        raw = raw if isinstance(raw, dict) else {}
        flags = sorted(
            name
            for name in GOPLUS_RISK_KEYS
            if name in raw and _truthy_flag(raw.get(name))
        )
        result = {
            "available": True,
            "malicious": bool(flags),
            "flags": flags,
        }
        self._cache[key] = result
        return result


class ChainabuseClient:
    """Very small cached Chainabuse screening client to conserve free-tier calls."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.chainabuse.com/v0",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._cache: dict[str, dict] = {}

    async def check(self, address: str | None) -> dict:
        if not self.api_key or not address:
            return {"available": False, "report_count": None, "max_confidence": None}
        address = address.lower()
        if address in self._cache:
            return self._cache[address]
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}/reports",
                    params={"address": address, "page": 1, "perPage": 10},
                    auth=httpx.BasicAuth(self.api_key, self.api_key),
                    headers={"accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            result = {"available": False, "report_count": None, "max_confidence": None}
            self._cache[address] = result
            return result

        if isinstance(payload, list):
            reports = payload
            total = len(reports)
        elif isinstance(payload, dict):
            reports = payload.get("reports") or payload.get("data") or payload.get("items") or []
            reports = reports if isinstance(reports, list) else []
            total_value = payload.get("total") or payload.get("count") or payload.get("totalCount")
            try:
                total = int(total_value) if total_value is not None else len(reports)
            except (TypeError, ValueError):
                total = len(reports)
        else:
            reports, total = [], 0

        confidences = []
        for report in reports:
            if not isinstance(report, dict):
                continue
            value = report.get("confidenceScore", report.get("confidence"))
            try:
                if value is not None:
                    confidences.append(float(value))
            except (TypeError, ValueError):
                pass
        result = {
            "available": True,
            "report_count": total,
            "max_confidence": max(confidences) if confidences else None,
        }
        self._cache[address] = result
        return result


class BitqueryIncidentDiscovery:
    """Find likely theft transactions from deterministic indexed wallet history."""

    def __init__(
        self,
        access_token: str,
        endpoint: str = "https://streaming.bitquery.io/graphql",
        timeout_seconds: float = 20.0,
        candidate_limit: int = 100,
        goplus: GoPlusAddressClient | None = None,
        chainabuse: ChainabuseClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.access_token = access_token
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.candidate_limit = max(10, min(candidate_limit, 500))
        self.goplus = goplus
        self.chainabuse = chainabuse
        self.transport = transport

    def _query(self, network: str, time_scoped: bool = False) -> str:
        variables = "$wallet: String!"
        block_filter = ""
        if time_scoped:
            variables += ", $since: DateTime!, $till: DateTime!"
            block_filter = "\n        Block: {Time: {since: $since, till: $till}}"
        return f"""
query WalletIncidentHistory({variables}) {{
  EVM(dataset: archive, network: {network}) {{
    Transfers(
      limit: {{count: {self.candidate_limit}}}
      orderBy: {{descending: Block_Time}}
      where: {{
        any: [
          {{Transfer: {{Sender: {{is: $wallet}}}}}},
          {{Transfer: {{Receiver: {{is: $wallet}}}}}}
        ]{block_filter}
      }}
    ) {{
      Block {{ Time Number }}
      Transaction {{ Hash From To }}
      Transfer {{
        Sender
        Receiver
        Amount
        AmountInUSD
        Type
        Currency {{ Name Symbol SmartContract Native Fungible }}
      }}
    }}
  }}
}}
""".strip()

    async def _history(
        self,
        chain: ChainName,
        wallet: str,
        incident_time: datetime | None = None,
    ) -> list[dict]:
        if not self.access_token:
            raise DiscoveryUnavailableError(
                "Wallet-only discovery requires BITQUERY_ACCESS_TOKEN. Add a theft transaction hash or configure Bitquery."
            )

        incident_time = _as_utc(incident_time)
        variables: dict[str, str] = {"wallet": wallet.lower()}
        if incident_time:
            variables["since"] = _bitquery_time(incident_time - DISCOVERY_TIME_WINDOW)
            variables["till"] = _bitquery_time(incident_time + DISCOVERY_TIME_WINDOW)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.post(
                    self.endpoint,
                    json={
                        "query": self._query(
                            BITQUERY_NETWORKS[chain], time_scoped=incident_time is not None
                        ),
                        "variables": variables,
                    },
                    headers={
                        "authorization": f"Bearer {self.access_token}",
                        "content-type": "application/json",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise DiscoveryProviderError("Bitquery wallet history request failed") from exc
        except ValueError as exc:
            raise DiscoveryProviderError("Bitquery returned an invalid response") from exc
        if payload.get("errors"):
            message = payload["errors"][0].get("message", "Bitquery GraphQL error")
            raise DiscoveryProviderError(f"Bitquery wallet history failed: {message}")
        rows = (((payload.get("data") or {}).get("EVM") or {}).get("Transfers") or [])
        if not isinstance(rows, list):
            raise DiscoveryProviderError("Bitquery wallet history response had no transfer list")
        return rows

    def _build_candidates(
        self, rows: list[dict], wallet: str, incident_time: datetime | None
    ) -> list[DiscoveryCandidate]:
        wallet = wallet.lower()
        incident_time = _as_utc(incident_time)
        grouped: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            tx = row.get("Transaction") or {}
            transfer = row.get("Transfer") or {}
            block = row.get("Block") or {}
            tx_hash = str(tx.get("Hash") or "").lower()
            sender = str(transfer.get("Sender") or "").lower()
            if len(tx_hash) != 66 or sender != wallet:
                continue
            receiver = str(transfer.get("Receiver") or "").lower() or None
            timestamp_raw = block.get("Time")
            try:
                timestamp = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
                timestamp = _as_utc(timestamp)
            except (TypeError, ValueError):
                timestamp = None
            try:
                block_number = int(block.get("Number"))
            except (TypeError, ValueError):
                block_number = 0
            try:
                amount_usd = float(transfer.get("AmountInUSD") or 0)
            except (TypeError, ValueError):
                amount_usd = 0.0
            item = grouped.setdefault(
                tx_hash,
                {
                    "transaction_hash": tx_hash,
                    "block_number": block_number,
                    "timestamp": timestamp,
                    "transaction_from": str(tx.get("From") or "").lower() or None,
                    "transaction_to": str(tx.get("To") or "").lower() or None,
                    "counterparty": receiver,
                    "outgoing_transfer_count": 0,
                    "amount_usd": 0.0,
                },
            )
            item["outgoing_transfer_count"] += 1
            item["amount_usd"] += max(0.0, amount_usd)
            if not item.get("counterparty") and receiver:
                item["counterparty"] = receiver

        candidates: list[DiscoveryCandidate] = []
        for item in grouped.values():
            score = 30.0
            reasons = ["wallet is the deterministic transfer sender"]
            if item["transaction_from"] and item["transaction_from"] != wallet:
                score += 25
                reasons.append("transaction caller differs from wallet while value leaves wallet")
            amount_usd = item["amount_usd"]
            if amount_usd >= 10_000:
                score += 18
                reasons.append("large indexed USD outflow")
            elif amount_usd >= 1_000:
                score += 14
                reasons.append("material indexed USD outflow")
            elif amount_usd >= 100:
                score += 8
                reasons.append("indexed USD outflow")
            if item["outgoing_transfer_count"] > 1:
                score += min(12, 4 * (item["outgoing_transfer_count"] - 1))
                reasons.append("multiple outgoing transfers in one transaction")
            if incident_time and item["timestamp"]:
                hours = abs((item["timestamp"] - incident_time).total_seconds()) / 3600
                if hours <= 6:
                    score += 30
                    reasons.append("within six hours of reported incident time")
                elif hours <= 24:
                    score += 22
                    reasons.append("within one day of reported incident time")
                elif hours <= 24 * 7:
                    score += 10
                    reasons.append("within one week of reported incident time")
                else:
                    score -= min(20, math.log10(max(hours, 1)) * 4)
            candidates.append(
                DiscoveryCandidate(
                    transaction_hash=item["transaction_hash"],
                    block_number=item["block_number"],
                    timestamp=item["timestamp"],
                    transaction_from=item["transaction_from"],
                    transaction_to=item["transaction_to"],
                    counterparty=item["counterparty"],
                    outgoing_transfer_count=item["outgoing_transfer_count"],
                    amount_usd=round(amount_usd, 2) if amount_usd else None,
                    score=round(score, 2),
                    reasons=reasons,
                )
            )
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.score,
                candidate.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

    async def discover(
        self, chain: ChainName, wallet: str, incident_time: datetime | None = None
    ) -> IncidentDiscovery:
        candidates = self._build_candidates(
            await self._history(chain, wallet, incident_time), wallet, incident_time
        )
        if not candidates:
            raise IncidentNotFoundError(
                "No deterministic outgoing transfer candidate was found for this wallet. Add an approximate incident time or a known theft transaction hash."
            )

        # GoPlus is cheap enough to enrich a few leading deterministic candidates.
        if self.goplus:
            for candidate in candidates[:3]:
                check = await self.goplus.check(chain, candidate.counterparty)
                if check.get("available"):
                    candidate.goplus_flags = list(check.get("flags") or [])
                    if check.get("malicious"):
                        candidate.score += 24
                        candidate.reasons.append("GoPlus flags the outgoing counterparty")

        candidates.sort(
            key=lambda candidate: (
                candidate.score,
                candidate.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

        # Chainabuse free keys are tightly limited. Screen only the leading counterparty and cache it.
        top = candidates[0]
        if self.chainabuse:
            check = await self.chainabuse.check(top.counterparty)
            if check.get("available"):
                top.chainabuse_report_count = check.get("report_count")
                if (check.get("report_count") or 0) > 0:
                    top.score += 28
                    top.reasons.append("Chainabuse has public reports for the outgoing counterparty")

        candidates.sort(
            key=lambda candidate: (
                candidate.score,
                candidate.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        selected = candidates[0]
        return IncidentDiscovery(
            source="bitquery",
            selected_transaction_hash=selected.transaction_hash,
            selected_score=round(selected.score, 2),
            candidate_count=len(candidates),
            incident_time=_as_utc(incident_time),
            candidates=candidates[:5],
        )
