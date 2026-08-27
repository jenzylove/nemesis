"""Publishing a case must not weaken owner-only access to every other case."""
from datetime import datetime, timezone

import pytest

from app.main import PRIVATE_CASE_FIELDS, published_case, redact
from app.models import InvestigationCase
from fastapi import HTTPException


def case(case_id, public):
    return InvestigationCase(
        id=case_id, state="MONITORING",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wallet_address="0x" + "ab" * 20, chain="ethereum",
        owner_user_id="owner-1", owner_email="victim@example.com",
        is_public_case=public,
    )


class Repo:
    def __init__(self, cases): self.cases = {c.id: c for c in cases}
    async def get(self, case_id): return self.cases.get(case_id)


@pytest.fixture
def repo(monkeypatch):
    store = Repo([case("NMS-PUBLIC", True), case("NMS-PRIVATE", False)])
    monkeypatch.setattr("app.main.repository", store)
    return store


@pytest.mark.asyncio
async def test_published_case_is_readable(repo):
    assert (await published_case("NMS-PUBLIC")).id == "NMS-PUBLIC"


@pytest.mark.asyncio
async def test_private_case_is_not_readable_publicly(repo):
    with pytest.raises(HTTPException) as raised:
        await published_case("NMS-PRIVATE")
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_a_private_case_looks_exactly_like_a_missing_one(repo):
    """Otherwise the endpoint becomes a probe for which case ids exist."""
    private, missing = None, None
    try:
        await published_case("NMS-PRIVATE")
    except HTTPException as exc:
        private = (exc.status_code, exc.detail)
    try:
        await published_case("NMS-DOES-NOT-EXIST")
    except HTTPException as exc:
        missing = (exc.status_code, exc.detail)
    assert private == missing


def test_publishing_never_exposes_the_account_behind_the_case():
    payload = redact(case("NMS-PUBLIC", True))
    for field in PRIVATE_CASE_FIELDS:
        assert field not in payload
    assert "victim@example.com" not in str(payload)
    assert "owner-1" not in str(payload)
    # the evidence itself must survive redaction
    assert payload["wallet_address"] == "0x" + "ab" * 20
    assert payload["state"] == "MONITORING"


def test_cases_are_private_unless_someone_publishes_them():
    fresh = InvestigationCase(
        id="NMS-NEW", state="INVESTIGATING",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        wallet_address="0x" + "cd" * 20, chain="ethereum", owner_user_id="owner-2",
    )
    assert fresh.is_public_case is False
