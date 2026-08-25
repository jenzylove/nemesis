"""Indexed continuation past the point a receipt stops being informative.

A contract forwarding native value produces an internal call. Receipts carry
logs, not internal calls, so tracing that relied on the receipt alone stopped at
the first contract hop and reported the branch dormant. These tests pin the
behaviour that fixes it, and guard the double-counting failure a previous
multi-path attempt introduced.
"""
from datetime import datetime, timezone

import pytest

from app.models import DeterministicEvidence, NativeTransfer, NormalizedTransaction
from app.movement import MovementDetectionError
from app.providers import JsonRpcProvider
from app.taskmaster import InMemoryMonitoringRepository, Taskmaster

WALLET = "0x" + "aa" * 20
A = "0x" + "b1" * 20
B = "0x" + "b2" * 20
C = "0x" + "c3" * 20


def h(byte):
    return "0x" + byte * 64


def make_tx(hash_value, block, source, destination, native=0):
    return NormalizedTransaction(
        hash=hash_value, chain="ethereum", block_number=block,
        timestamp=datetime.now(timezone.utc), status="success",
        from_address=source, to_address=destination,
        native_value_wei=str(native), input="0x", erc20_transfers=[],
    )


class Publisher:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)
        return "id"


class Rpc(JsonRpcProvider):
    """RPC that sees only what a receipt encodes, plus an optional index."""

    def __init__(self, transactions, movements, indexed=None, indexed_error=False):
        super().__init__({"ethereum": "fixture", "base": "fixture"})
        self.transactions = transactions
        self.movements = movements
        self.indexed = indexed or {}
        self.indexed_error = indexed_error
        self.indexed_calls = 0

    async def get_normalized_transaction(self, chain, tx_hash):
        return self.transactions[chain, tx_hash].model_copy(deep=True)

    async def get_address_movements(self, chain, address, after_block, max_blocks=20):
        rows = [m for m in self.movements.get((chain, address.lower()), []) if m["block_number"] > after_block]
        return (max([after_block + 1, *[m["block_number"] for m in rows]]), rows)

    async def get_indexed_native_transfers(self, chain, transaction, source):
        self.indexed_calls += 1
        if self.indexed_error:
            raise MovementDetectionError("Alchemy indexed transfer request failed")
        return [NativeTransfer(**row) for row in self.indexed.get((transaction.hash, source.lower()), [])]


async def native_trace(rpc, max_depth=8):
    """Seed a case whose stolen asset is native value sent to a contract."""
    repo = InMemoryMonitoringRepository()
    taskmaster = Taskmaster(repo, rpc, Publisher(), max_blocks=20, max_depth=max_depth)
    theft = make_tx(h("1"), 1, WALLET, A, native=100)
    await taskmaster.trace_initial("NMS-C", DeterministicEvidence(submitted_wallet=WALLET, transaction=theft))
    return taskmaster, repo


@pytest.mark.asyncio
async def test_internal_transfer_continues_a_branch_the_receipt_hides():
    """Before this, the branch stopped at A and was reported dormant."""
    rpc = Rpc(
        transactions={("ethereum", h("2")): make_tx(h("2"), 2, C, A)},
        movements={("ethereum", A): [{"transaction_hash": h("2"), "block_number": 2, "direction": "out"}]},
        indexed={(h("2"), A): [{"from_address": A, "to_address": B, "raw_amount": "100",
                                "provenance": ["alchemy_getAssetTransfers", "category:internal", h("2")]}]},
    )
    _, repo = await native_trace(rpc)
    branches = await repo.list_branches(case_id="NMS-C")
    landed = [b for b in branches if b.current_address == B]
    assert landed, [(b.current_address, b.status) for b in branches]
    assert landed[0].amount == "100"
    assert landed[0].depth >= 2
    assert any("alchemy_getAssetTransfers" in p for p in landed[0].evidence_provenance)


@pytest.mark.asyncio
async def test_retrieval_failure_is_not_reported_as_no_movement():
    rpc = Rpc(
        transactions={("ethereum", h("2")): make_tx(h("2"), 2, C, A)},
        movements={("ethereum", A): [{"transaction_hash": h("2"), "block_number": 2, "direction": "out"}]},
        indexed_error=True,
    )
    _, repo = await native_trace(rpc)
    branch = [b for b in await repo.list_branches(case_id="NMS-C") if b.current_address == A][0]
    assert branch.terminal_reason == "CONTINUATION_EVIDENCE_UNAVAILABLE"
    assert branch.status == "OBSCURED"


@pytest.mark.asyncio
async def test_genuine_absence_is_still_dormant():
    """An empty index is evidence of no movement, unlike a failed lookup."""
    rpc = Rpc(
        transactions={("ethereum", h("2")): make_tx(h("2"), 2, C, A)},
        movements={("ethereum", A): [{"transaction_hash": h("2"), "block_number": 2, "direction": "out"}]},
        indexed={},
    )
    _, repo = await native_trace(rpc)
    branch = [b for b in await repo.list_branches(case_id="NMS-C") if b.current_address == A][0]
    assert branch.status == "DORMANT"
    assert branch.terminal_reason == "NO_DETERMINISTIC_OUTGOING_PATH"


@pytest.mark.asyncio
async def test_indexed_split_does_not_double_count_value():
    """The regression a previous multi-path attempt introduced.

    A forwards 60 to B and 40 to C inside one transaction. Exactly 100 may be
    accounted for; the same funds must not appear down two paths.
    """
    rpc = Rpc(
        transactions={("ethereum", h("2")): make_tx(h("2"), 2, C, A)},
        movements={("ethereum", A): [{"transaction_hash": h("2"), "block_number": 2, "direction": "out"}]},
        indexed={(h("2"), A): [
            {"from_address": A, "to_address": B, "raw_amount": "60", "provenance": ["alchemy_getAssetTransfers"]},
            {"from_address": A, "to_address": C, "raw_amount": "40", "provenance": ["alchemy_getAssetTransfers"]},
        ]},
    )
    _, repo = await native_trace(rpc)
    branches = await repo.list_branches(case_id="NMS-C")
    landed = {b.current_address: int(b.amount) for b in branches if b.current_address in (B, C)}
    assert landed == {B: 60, C: 40}, landed
    assert sum(landed.values()) == 100


@pytest.mark.asyncio
async def test_index_not_consulted_when_receipt_already_shows_the_path():
    rpc = Rpc(
        transactions={("ethereum", h("2")): make_tx(h("2"), 2, A, B, native=100)},
        movements={("ethereum", A): [{"transaction_hash": h("2"), "block_number": 2, "direction": "out"}]},
        indexed={(h("2"), A): [{"from_address": A, "to_address": B, "raw_amount": "100",
                                "provenance": ["alchemy_getAssetTransfers"]}]},
    )
    _, repo = await native_trace(rpc)
    landed = [b for b in await repo.list_branches(case_id="NMS-C") if b.current_address == B]
    assert len(landed) == 1, landed
    assert int(landed[0].amount) == 100
    assert rpc.indexed_calls == 0


@pytest.mark.asyncio
async def test_forwarding_chain_stops_at_configured_depth():
    """A long forwarding chain must terminate, not run unbounded."""
    path = [A] + ["0x" + format(i, "02x") * 20 for i in range(0x20, 0x2c)]
    transactions, movements, indexed = {}, {}, {}
    for i in range(len(path) - 1):
        key = "0x" + format(i + 2, "02x") * 32
        transactions[("ethereum", key)] = make_tx(key, i + 2, C, path[i])
        movements[("ethereum", path[i].lower())] = [
            {"transaction_hash": key, "block_number": i + 2, "direction": "out"}]
        indexed[(key, path[i].lower())] = [{"from_address": path[i], "to_address": path[i + 1],
                                            "raw_amount": "100", "provenance": ["alchemy_getAssetTransfers"]}]
    rpc = Rpc(transactions=transactions, movements=movements, indexed=indexed)
    _, repo = await native_trace(rpc, max_depth=4)
    branches = await repo.list_branches(case_id="NMS-C")
    assert max(b.depth for b in branches) <= 4
    assert any(b.terminal_reason == "MAX_DEPTH" for b in branches)


@pytest.mark.asyncio
async def test_branch_advances_past_an_unrelated_outgoing_transaction():
    """An address often emits transfers that do not touch the tracked asset.

    Reading only the first outgoing transaction made the branch look dormant
    whenever an unrelated transfer happened to come first.
    """
    unrelated = make_tx(h("2"), 2, A, C)          # no native value leaves A
    relevant = make_tx(h("3"), 3, A, B, native=100)  # the tracked native does
    rpc = Rpc(
        transactions={("ethereum", h("2")): unrelated, ("ethereum", h("3")): relevant},
        movements={("ethereum", A): [
            {"transaction_hash": h("2"), "block_number": 2, "direction": "out"},
            {"transaction_hash": h("3"), "block_number": 3, "direction": "out"},
        ]},
    )
    _, repo = await native_trace(rpc)
    branches = await repo.list_branches(case_id="NMS-C")
    landed = [b for b in branches if b.current_address == B]
    assert landed, [(b.current_address, b.status, b.terminal_reason) for b in branches]
    assert int(landed[0].amount) == 100


@pytest.mark.asyncio
async def test_advancing_stops_once_value_is_accounted_for():
    """Guards the double-counting failure directly.

    The first candidate moves the whole tracked amount. No later candidate may
    be followed, or the same funds would appear twice.
    """
    first = make_tx(h("2"), 2, A, B, native=100)
    second = make_tx(h("3"), 3, A, C, native=100)
    rpc = Rpc(
        transactions={("ethereum", h("2")): first, ("ethereum", h("3")): second},
        movements={("ethereum", A): [
            {"transaction_hash": h("2"), "block_number": 2, "direction": "out"},
            {"transaction_hash": h("3"), "block_number": 3, "direction": "out"},
        ]},
    )
    _, repo = await native_trace(rpc)
    branches = await repo.list_branches(case_id="NMS-C")
    reached = {b.current_address for b in branches}
    assert B in reached
    assert C not in reached, "followed a second path for funds already accounted for"
    total = sum(int(b.amount) for b in branches if b.current_address == B)
    assert total == 100


@pytest.mark.asyncio
async def test_candidate_advancement_is_bounded():
    """Never walk an unbounded number of candidates for one hop."""
    movements, transactions = [], {}
    for i in range(12):
        key = "0x" + format(i + 2, "02x") * 32
        transactions[("ethereum", key)] = make_tx(key, i + 2, A, C)  # none move native
        movements.append({"transaction_hash": key, "block_number": i + 2, "direction": "out"})
    rpc = Rpc(transactions=transactions, movements={("ethereum", A): movements})
    taskmaster, repo = await native_trace(rpc)
    assert rpc.indexed_calls <= taskmaster.max_candidates_per_hop
    branch = [b for b in await repo.list_branches(case_id="NMS-C") if b.current_address == A][0]
    assert branch.status == "DORMANT"
