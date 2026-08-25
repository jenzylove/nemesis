from datetime import datetime, timezone

import pytest

from app.taskmaster import InMemoryMonitoringRepository, Taskmaster, TraceBranch


class NoopPublisher:
    async def publish(self, event):
        return event["id"]


class FailOnceProvider:
    def __init__(self):
        self.calls = 0

    async def get_address_movements(self, chain, address, after_block, max_blocks, asset=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary provider failure")
        return after_block + 1, []


@pytest.mark.asyncio
async def test_failed_event_is_retryable_then_duplicate_after_success():
    repository = InMemoryMonitoringRepository()
    provider = FailOnceProvider()
    taskmaster = Taskmaster(repository, provider, NoopPublisher())
    branch = TraceBranch(
        id="BR-RETRY",
        case_id="NMS-RETRY",
        current_address="0x" + "11" * 20,
        chain="ethereum",
        asset="native",
        amount="1",
        status="DORMANT",
        last_transaction="0x" + "ab" * 32,
        cursor_block=1,
        last_checked=datetime.now(timezone.utc),
    )
    await repository.save_branch(branch)
    event = {
        "id": "EV-RETRY",
        "type": "RECHECK_REQUESTED",
        "branch_id": branch.id,
    }

    with pytest.raises(RuntimeError, match="temporary provider failure"):
        await taskmaster.consume(event)
    assert event["id"] not in repository.claims

    result = await taskmaster.consume(event)
    assert result == {"movement": False}
    assert event["id"] in repository.claims
    assert await taskmaster.consume(event) == {"duplicate": True}
