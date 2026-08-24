import asyncio
from datetime import datetime, timezone

import pytest

from app.incident_selection import RPC_CONCURRENCY, rank_verified_candidates
from app.models import DiscoveryCandidate, ERC20Transfer, IncidentDiscovery, NormalizedTransaction

WALLET = "0x" + "11" * 20
CALLER = "0x" + "22" * 20
DEST = "0x" + "33" * 20
TOKEN = "0x" + "44" * 20


def transaction(tx_hash, caller=CALLER, token=TOKEN):
    return NormalizedTransaction(
        hash=tx_hash, chain="ethereum", block_number=1,
        timestamp=datetime.now(timezone.utc), status="success",
        from_address=caller, to_address=DEST, native_value_wei="0", input="0x23b872dd",
        erc20_transfers=[ERC20Transfer(log_index=0, token_contract=token, from_address=WALLET, to_address=DEST, raw_amount="1")],
    )


def discovery(scores):
    candidates = [DiscoveryCandidate(transaction_hash="0x" + f"{i:064x}", block_number=i, score=score) for i, score in enumerate(scores, 1)]
    return IncidentDiscovery(source="alchemy", candidate_count=len(candidates), candidates=candidates)


class Provider:
    def __init__(self, failing=None):
        self.active = 0
        self.peak = 0
        self.failing = failing

    async def get_normalized_transaction(self, chain, tx_hash):
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        if tx_hash == self.failing:
            raise RuntimeError("provider failure")
        return transaction(tx_hash)


@pytest.mark.asyncio
async def test_near_tie_is_ambiguous_and_does_not_select():
    item = discovery([70, 69])
    result = await rank_verified_candidates(Provider(), "ethereum", WALLET, item)
    assert result is None
    assert item.status == "AMBIGUOUS_INCIDENT"
    assert item.selected_transaction_hash is None
    assert len(item.candidates) == 2


@pytest.mark.asyncio
async def test_clear_winner_has_selection_confidence_separate_from_mechanism():
    item = discovery([100, 40])
    result = await rank_verified_candidates(Provider(), "ethereum", WALLET, item)
    assert result is not None
    assert item.status == "SELECTED"
    assert item.incident_selection_confidence >= 0.70


@pytest.mark.asyncio
async def test_rpc_verification_is_bounded_and_provider_failure_isolated():
    item = discovery([100 - i for i in range(12)])
    provider = Provider(failing=item.candidates[-1].transaction_hash)
    await rank_verified_candidates(provider, "ethereum", WALLET, item)
    assert provider.peak <= RPC_CONCURRENCY
    assert provider.peak > 1
    assert all(c.transaction_hash != provider.failing for c in item.candidates)