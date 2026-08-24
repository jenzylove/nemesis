from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import main
from app.auth import verify_user_credentials
from app.models import AgentFinding, CaseCreate, InvestigationCase, NormalizedTransaction
from app.agent_runtime import InvestigationClassifier
from app.repository import InMemoryCaseRepository
from app.workflow import CaseWorkflow

WALLET = "0x" + "11" * 20
DESTINATION = "0x" + "22" * 20
TX_HASH = "0x" + "ab" * 32


class AuthProvider:
    async def get_normalized_transaction(self, chain, tx_hash):
        return NormalizedTransaction(
            hash=tx_hash,
            chain=chain,
            block_number=1,
            timestamp=datetime.now(timezone.utc),
            status="success",
            from_address=WALLET,
            to_address=DESTINATION,
            native_value_wei="1",
            input="0x",
            erc20_transfers=[],
        )


class UnknownClassifier(InvestigationClassifier):
    async def classify(self, case_id, evidence):
        return AgentFinding(
            classification="unknown",
            summary="The deterministic evidence is insufficient to determine the compromise mechanism.",
            confidence=0.1,
            evidence_references=["transaction.status"],
            limitations=["Only one transaction was examined."],
        )


def test_missing_auth_is_rejected():
    with pytest.raises(HTTPException) as exc:
        verify_user_credentials(None)
    assert exc.value.status_code == 401


def test_invalid_token_is_rejected(monkeypatch):
    from google.oauth2 import id_token

    def reject(*args, **kwargs):
        raise ValueError("bad token")

    monkeypatch.setattr(id_token, "verify_firebase_token", reject)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid")
    with pytest.raises(HTTPException) as exc:
        verify_user_credentials(credentials)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_creation_assigns_owner_on_first_save(monkeypatch):
    repository = InMemoryCaseRepository()
    await repository.initialize()
    workflow = CaseWorkflow(repository, AuthProvider(), UnknownClassifier())
    monkeypatch.setattr(main, "repository", repository)
    monkeypatch.setattr(main, "workflow", workflow)

    response = await main.create_case(
        CaseCreate(
            wallet_address=WALLET,
            chain="ethereum",
            theft_transaction_hash=TX_HASH,
        ),
        {"sub": "user-a", "email": "a@example.com"},
    )
    stored = await repository.get(response.case.id)
    assert stored.owner_user_id == "user-a"
    assert stored.owner_email == "a@example.com"
    assert [case.id for case in await repository.list_by_owner("user-a")] == [stored.id]
    assert await repository.list_by_owner("user-b") == []


@pytest.mark.asyncio
async def test_owner_can_reopen_and_non_owner_gets_same_not_found(monkeypatch):
    repository = InMemoryCaseRepository()
    await repository.initialize()
    now = datetime.now(timezone.utc)
    case = InvestigationCase(
        id="NMS-OWNER-TEST",
        state="EVIDENCE_READY",
        created_at=now,
        updated_at=now,
        wallet_address=WALLET,
        chain="ethereum",
        owner_user_id="user-a",
    )
    await repository.save(case)
    monkeypatch.setattr(main, "repository", repository)

    reopened = await main.owned_case(case.id, {"sub": "user-a"})
    assert reopened.id == case.id
    for user in ({"sub": "user-b"}, {"sub": "anonymous"}):
        with pytest.raises(HTTPException) as exc:
            await main.owned_case(case.id, user)
        assert exc.value.status_code == 404
        assert exc.value.detail == "case not found"


@pytest.mark.asyncio
async def test_unrelated_hash_creates_no_case():
    repository = InMemoryCaseRepository()
    await repository.initialize()
    workflow = CaseWorkflow(repository, AuthProvider(), UnknownClassifier())
    with pytest.raises(ValueError, match="no deterministic value"):
        await workflow.create_and_investigate(
            CaseCreate(
                wallet_address="0x" + "33" * 20,
                chain="ethereum",
                theft_transaction_hash=TX_HASH,
            ),
            "user-a",
        )
    assert await repository.list_by_owner("user-a") == []
