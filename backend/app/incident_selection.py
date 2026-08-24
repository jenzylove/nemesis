from __future__ import annotations

import asyncio
from datetime import datetime, timezone

MIN_SELECTION_CONFIDENCE = 0.70
MIN_SCORE_MARGIN = 12.0
RPC_CONCURRENCY = 4
FINALIST_LIMIT = 5


def _append_reason(candidate, reason: str) -> None:
    if reason not in candidate.reasons and len(candidate.reasons) < 12:
        candidate.reasons.append(reason)


def wallet_outflow(transaction, wallet: str) -> bool:
    return (
        transaction.from_address == wallet and int(transaction.native_value_wei) > 0
    ) or any(t.from_address == wallet for t in transaction.erc20_transfers) or any(
        t.from_address == wallet for t in transaction.nft_transfers
    )


def selection_confidence(score: float, runner_up_score: float | None) -> float:
    absolute = max(0.0, min(1.0, (score - 45.0) / 85.0))
    margin = 1.0 if runner_up_score is None else max(
        0.0, min(1.0, (score - runner_up_score) / 30.0)
    )
    return round((0.6 * absolute) + (0.4 * margin), 3)


async def rank_verified_candidates(provider, chain, wallet, discovery):
    if not discovery.candidates and discovery.selected_transaction_hash:
        tx_hash = discovery.selected_transaction_hash.lower()
        transaction = await provider.get_normalized_transaction(chain, tx_hash)
        if transaction.hash.lower() != tx_hash or transaction.status != "success" or not wallet_outflow(transaction, wallet):
            raise ValueError("the discovered transaction did not contain deterministic value leaving the submitted wallet")
        discovery.status = "SELECTED"
        discovery.incident_selection_confidence = 1.0
        return transaction

    semaphore = asyncio.Semaphore(RPC_CONCURRENCY)

    async def verify(candidate):
        async with semaphore:
            tx_hash = candidate.transaction_hash.lower()
            try:
                transaction = await provider.get_normalized_transaction(chain, tx_hash)
            except Exception:
                return None
            if (
                transaction.hash.lower() != tx_hash
                or transaction.status != "success"
                or not wallet_outflow(transaction, wallet)
            ):
                return None

            tokens = [t for t in transaction.erc20_transfers if t.from_address == wallet]
            nfts = [t for t in transaction.nft_transfers if t.from_address == wallet]
            native = transaction.from_address == wallet and int(transaction.native_value_wei) > 0
            assets = {t.token_contract for t in tokens}
            assets.update(f"nft:{t.token_contract}:{t.token_id}" for t in nfts)
            if native:
                assets.add("native")
            destinations = {t.to_address for t in tokens + nfts}
            if native and transaction.to_address:
                destinations.add(transaction.to_address)

            candidate.transaction_from = transaction.from_address
            candidate.transaction_to = transaction.to_address
            candidate.caller_relationship = (
                "wallet" if transaction.from_address == wallet else "third_party"
            )
            candidate.method_id = transaction.input[:10] if len(transaction.input) >= 10 else None
            candidate.token_outflow_count = len(tokens)
            candidate.nft_outflow_count = len(nfts)
            candidate.native_outflow_wei = transaction.native_value_wei if native else "0"
            candidate.asset_count = len(assets)
            candidate.destination_count = len(destinations)
            candidate.outgoing_transfer_count = max(
                candidate.outgoing_transfer_count, len(tokens) + len(nfts) + int(native)
            )
            candidate.outflow_summary = sorted(assets)[:12]
            candidate.destination_summary = sorted(destinations)[:12]

            if (tokens or nfts) and transaction.from_address != wallet:
                candidate.score += 52
                _append_reason(candidate, "RPC shows a third-party transaction caller moved wallet assets")
            if len(assets) > 1:
                candidate.score += min(36, 10 * (len(assets) - 1))
                _append_reason(candidate, "multiple distinct assets left in one transaction")
            if candidate.outgoing_transfer_count > 2:
                candidate.score += min(30, 3 * (candidate.outgoing_transfer_count - 2))
                _append_reason(candidate, "batch-like wallet drain contains several outflows")
            if len(destinations) > 1:
                candidate.score += min(16, 4 * (len(destinations) - 1))
                _append_reason(candidate, "funds split across multiple destinations")
            if native and (tokens or nfts):
                candidate.score += 10
                _append_reason(candidate, "native and token assets left together")
            if nfts:
                candidate.score += min(10, 2 * len(nfts))
                _append_reason(candidate, "NFT assets also left the wallet")
            if candidate.method_id == "0x23b872dd":
                candidate.score += 10
                _append_reason(candidate, "transferFrom calldata is consistent with delegated movement")
            return candidate, transaction

    verified = [item for item in await asyncio.gather(
        *(verify(candidate) for candidate in discovery.candidates), return_exceptions=False
    ) if item is not None]
    verified.sort(
        key=lambda item: (
            item[0].score,
            item[0].timestamp or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    if not verified:
        raise ValueError("no discovered candidate contained deterministic value leaving the submitted wallet")

    top_score = verified[0][0].score
    second_score = verified[1][0].score if len(verified) > 1 else None
    confidence = selection_confidence(top_score, second_score)
    for candidate, _ in verified:
        candidate.selection_confidence = selection_confidence(
            candidate.score, top_score if candidate is not verified[0][0] else second_score
        )

    margin = top_score - second_score if second_score is not None else top_score
    selected = confidence >= MIN_SELECTION_CONFIDENCE and (
        second_score is None or margin >= MIN_SCORE_MARGIN
    )
    discovery.candidates = [candidate for candidate, _ in verified[:FINALIST_LIMIT]]
    discovery.selected_score = top_score
    discovery.incident_selection_confidence = confidence
    if selected:
        discovery.status = "SELECTED"
        discovery.selected_transaction_hash = verified[0][0].transaction_hash.lower()
        discovery.ambiguity_reason = None
        return verified[0][1]

    discovery.status = "AMBIGUOUS_INCIDENT"
    discovery.selected_transaction_hash = None
    discovery.ambiguity_reason = (
        f"Top candidates are separated by only {margin:.1f} points; choose a candidate or add an incident time."
    )
    return None