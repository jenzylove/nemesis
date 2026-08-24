from datetime import datetime, timezone

import pytest

from app.agent_runtime import InvestigationClassifier
from app.models import (
    AgentFinding,
    CaseCreate,
    DiscoveryCandidate,
    ERC20Transfer,
    IncidentDiscovery,
    NormalizedTransaction,
)
from app.repository import InMemoryCaseRepository
from app.workflow import CaseWorkflow

WALLET = "0x" + "11" * 20
ATTACKER = "0x" + "22" * 20
DEST_A = "0x" + "33" * 20
DEST_B = "0x" + "44" * 20
TOKEN_A = "0x" + "55" * 20
TOKEN_B = "0x" + "66" * 20
TX_A = "0x" + "aa" * 32
TX_B = "0x" + "bb" * 32


def tx(hash_value, caller, transfers):
    return NormalizedTransaction(
        hash=hash_value,
        chain="ethereum",
        block_number=100,
        timestamp=datetime(2026, 3, 22, tzinfo=timezone.utc),
        status="success",
        from_address=caller,
        to_address=DEST_A,
        native_value_wei="0",
        input="0x",
        erc20_transfers=transfers,
    )


class DiscoveryStub:
    async def discover(self, chain, wallet, incident_time=None):
        return IncidentDiscovery(
            source="alchemy",
            selected_transaction_hash=TX_A,
            selected_score=52,
            candidate_count=2,
            candidates=[
                DiscoveryCandidate(
                    transaction_hash=TX_A,
                    block_number=100,
                    score=52,
                    counterparty=DEST_A,
                    outgoing_transfer_count=1,
                ),
                DiscoveryCandidate(
                    transaction_hash=TX_B,
                    block_number=101,
                    score=40,
                    counterparty=DEST_B,
                    outgoing_transfer_count=2,
                ),
            ],
        )


class ProviderStub:
    def __init__(self):
        self.transactions = {
            TX_A: tx(
                TX_A,
                WALLET,
                [ERC20Transfer(log_index=1, token_contract=TOKEN_A, from_address=WALLET, to_address=DEST_A, raw_amount="10")],
            ),
            TX_B: tx(
                TX_B,
                ATTACKER,
                [
                    ERC20Transfer(log_index=1, token_contract=TOKEN_A, from_address=WALLET, to_address=DEST_B, raw_amount="10"),
                    ERC20Transfer(log_index=2, token_contract=TOKEN_B, from_address=WALLET, to_address=DEST_B, raw_amount="20"),
                ],
            ),
        }

    async def get_normalized_transaction(self, chain, tx_hash):
        return self.transactions[tx_hash]


class UnknownClassifier(InvestigationClassifier):
    async def classify(self, case_id, evidence):
        return AgentFinding(
            classification="unknown",
            summary="The drain is verified but the compromise mechanism cannot be determined.",
            confidence=0.1,
            evidence_references=["transaction.hash"],
            limitations=["Authorization mechanism is not proven by this transaction alone."],
        )


class TraceRecorder:
    def __init__(self):
        self.evidence = None

    async def trace_initial(self, case_id, evidence):
        self.evidence = evidence
        return []


@pytest.mark.asyncio
async def test_rpc_drain_evidence_can_rerank_and_exact_selection_is_traced():
    repository = InMemoryCaseRepository()
    await repository.initialize()
    recorder = TraceRecorder()
    workflow = CaseWorkflow(
        repository,
        ProviderStub(),
        UnknownClassifier(),
        taskmaster=recorder,
        discovery=DiscoveryStub(),
    )

    response = await workflow.create_and_investigate(
        CaseCreate(wallet_address=WALLET, chain="ethereum"),
        "test-user",
    )

    assert response.case.theft_transaction_hash == TX_B
    assert response.case.discovery.selected_transaction_hash == TX_B
    assert response.case.discovery.candidates[0].transaction_hash == TX_B
    assert any(
        "third-party transaction caller" in reason
        for reason in response.case.discovery.candidates[0].reasons
    )
    assert recorder.evidence.transaction.hash == TX_B
    assert response.case.finding.classification == "unknown"
    assert response.case.state == "LIMITED"
