from datetime import datetime, timezone

import pytest

from app.models import AgentFinding, CaseCreate, DeterministicEvidence, IncidentDiscovery, NormalizedTransaction
from app.repository import InMemoryCaseRepository
from app.workflow import CaseWorkflow

WALLET="0x"+"11"*20
TX_HASH="0x"+"ab"*32
COUNTERPARTY="0x"+"22"*20


def make_tx(chain: str):
    return NormalizedTransaction(
        hash=TX_HASH,
        chain=chain,
        block_number=321,
        timestamp=datetime(2026,8,22,12,0,tzinfo=timezone.utc),
        status="success",
        from_address=WALLET,
        to_address=COUNTERPARTY,
        native_value_wei="1",
        input="0x",
        erc20_transfers=[],
    )


class AutoDiscovery:
    async def discover(self, chain, wallet, incident_time=None):
        assert wallet==WALLET
        if chain=="ethereum":
            raise LookupError("no qualifying ethereum incident")
        return IncidentDiscovery(
            source="alchemy",
            selected_transaction_hash=TX_HASH,
            selected_score=77,
            candidate_count=1,
            incident_time=incident_time,
            candidates=[],
        )


class AutoProvider:
    async def get_normalized_transaction(self, chain, tx_hash):
        assert tx_hash==TX_HASH
        if chain=="ethereum":
            raise LookupError("transaction not on ethereum")
        assert chain=="base"
        return make_tx("base")


class StubClassifier:
    async def classify(self, case_id, evidence: DeterministicEvidence):
        return AgentFinding(
            classification="unknown",
            summary="Verified evidence identifies the incident while the compromise mechanism remains unknown.",
            confidence=.2,
            evidence_references=["transaction.hash"],
            limitations=[],
        )


@pytest.mark.asyncio
async def test_wallet_only_auto_detects_base_and_persists_resolved_chain():
    repository=InMemoryCaseRepository()
    await repository.initialize()
    workflow=CaseWorkflow(repository,AutoProvider(),StubClassifier(),discovery=AutoDiscovery())
    response=await workflow.create_and_investigate(CaseCreate(wallet_address=WALLET))
    assert response.case.state=="COMPLETE"
    assert response.case.chain=="base"
    assert response.case.theft_transaction_hash==TX_HASH
    assert response.case.evidence.transaction.chain=="base"


@pytest.mark.asyncio
async def test_known_hash_auto_probes_supported_chains():
    repository=InMemoryCaseRepository()
    await repository.initialize()
    workflow=CaseWorkflow(repository,AutoProvider(),StubClassifier())
    response=await workflow.create_and_investigate(
        CaseCreate(wallet_address=WALLET,theft_transaction_hash=TX_HASH)
    )
    assert response.case.chain=="base"
    assert response.case.evidence.transaction.hash==TX_HASH
