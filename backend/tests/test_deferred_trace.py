"""Deep tracing must not run inside the create-case request.

A real drain reaches tens of branches and runs for minutes. Holding the request
open for that long meant the investigation outlived the browser that started it:
it completed and persisted while the user saw a frozen page, and retrying
started a second full trace against the same provider quota.
"""
from datetime import datetime, timezone

import pytest

from app.models import DeterministicEvidence, NativeTransfer, NormalizedTransaction
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
    def __init__(self, transactions, movements, indexed=None):
        super().__init__({"ethereum": "fixture", "base": "fixture"})
        self.transactions = transactions
        self.movements = movements
        self.indexed = indexed or {}

    async def get_normalized_transaction(self, chain, tx_hash):
        return self.transactions[chain, tx_hash].model_copy(deep=True)

    async def get_address_movements(self, chain, address, after_block, max_blocks=20, asset=None):
        rows = [m for m in self.movements.get((chain, address.lower()), []) if m["block_number"] > after_block]
        return (max([after_block + 1, *[m["block_number"] for m in rows]]), rows)

    async def get_indexed_native_transfers(self, chain, transaction, source):
        return [NativeTransfer(**row) for row in self.indexed.get((transaction.hash, source.lower()), [])]


def onward_hop():
    """A first hop that has somewhere further to go."""
    return Rpc(
        transactions={("ethereum", h("2")): make_tx(h("2"), 2, A, B, native=100)},
        movements={("ethereum", A): [{"transaction_hash": h("2"), "block_number": 2, "direction": "out"}]},
    )


async def seed(taskmaster):
    theft = make_tx(h("1"), 1, WALLET, A, native=100)
    return await taskmaster.trace_initial("NMS-D", DeterministicEvidence(submitted_wallet=WALLET, transaction=theft))


@pytest.mark.asyncio
async def test_create_returns_the_first_hop_without_draining():
    publisher = Publisher()
    repo = InMemoryMonitoringRepository()
    taskmaster = Taskmaster(repo, onward_hop(), publisher, defer_deep_trace=True)

    branches = await seed(taskmaster)

    # The first hop is persisted, so the case can be delivered immediately.
    assert len(branches) == 1
    assert branches[0].current_address == A
    assert branches[0].status == "MOVING"
    # Nothing was followed past it inside the request.
    assert not [b for b in await repo.list_branches(case_id="NMS-D") if b.current_address == B]
    # The remaining work was handed to the event path.
    assert [e["type"] for e in publisher.events] == ["DRAIN_REQUESTED"]
    assert publisher.events[0]["branch_id"] == branches[0].id


@pytest.mark.asyncio
async def test_the_queued_event_completes_the_trace():
    publisher = Publisher()
    repo = InMemoryMonitoringRepository()
    taskmaster = Taskmaster(repo, onward_hop(), publisher, defer_deep_trace=True)
    await seed(taskmaster)

    await taskmaster.consume(publisher.events[0])

    landed = [b for b in await repo.list_branches(case_id="NMS-D") if b.current_address == B]
    assert landed, "the deferred trace did not continue past the first hop"
    assert int(landed[0].amount) == 100


@pytest.mark.asyncio
async def test_redelivery_does_not_trace_twice():
    publisher = Publisher()
    repo = InMemoryMonitoringRepository()
    taskmaster = Taskmaster(repo, onward_hop(), publisher, defer_deep_trace=True)
    await seed(taskmaster)
    event = publisher.events[0]

    first = await taskmaster.consume(event)
    second = await taskmaster.consume(event)

    assert first.get("drained") is True
    assert second == {"duplicate": True}
    assert len({b.id for b in await repo.list_branches(case_id="NMS-D")}) == len(
        await repo.list_branches(case_id="NMS-D")
    )


@pytest.mark.asyncio
async def test_inline_tracing_is_unchanged_when_not_deferred():
    """The synchronous path stays available and behaves as before."""
    repo = InMemoryMonitoringRepository()
    taskmaster = Taskmaster(repo, onward_hop(), Publisher(), defer_deep_trace=False)

    await seed(taskmaster)

    landed = [b for b in await repo.list_branches(case_id="NMS-D") if b.current_address == B]
    assert landed, "inline tracing should follow the hop within the call"
