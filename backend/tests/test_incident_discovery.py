from datetime import datetime, timezone
import json

import httpx
import pytest

from app.discovery import BitqueryIncidentDiscovery, ChainabuseClient, GoPlusAddressClient
from app.models import (
    AgentFinding,
    CaseCreate,
    DeterministicEvidence,
    IncidentDiscovery,
    NormalizedTransaction,
)
from app.repository import InMemoryCaseRepository
from app.workflow import CaseWorkflow

WALLET = "0x" + "11" * 20
COUNTERPARTY = "0x" + "22" * 20
TX_HASH = "0x" + "ab" * 32


def make_tx(tx_hash: str = TX_HASH) -> NormalizedTransaction:
    return NormalizedTransaction(
        hash=tx_hash,
        chain="ethereum",
        block_number=123,
        timestamp=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
        status="success",
        from_address=WALLET,
        to_address=COUNTERPARTY,
        native_value_wei="1",
        input="0x",
        erc20_transfers=[],
    )


class StubDiscovery:
    async def discover(self, chain, wallet, incident_time=None):
        assert chain == "ethereum"
        assert wallet == WALLET
        return IncidentDiscovery(
            source="bitquery",
            selected_transaction_hash=TX_HASH,
            selected_score=88,
            candidate_count=1,
            incident_time=incident_time,
            candidates=[],
        )


class StubProvider:
    async def get_normalized_transaction(self, chain, tx_hash):
        assert chain == "ethereum"
        assert tx_hash == TX_HASH
        return make_tx(tx_hash)


class StubClassifier:
    async def classify(self, case_id, evidence: DeterministicEvidence):
        assert evidence.transaction.hash == TX_HASH
        return AgentFinding(
            classification="unknown",
            summary="Deterministic evidence was verified before interpretation.",
            confidence=0.3,
            evidence_references=["transaction.hash"],
            limitations=[],
        )


def test_case_create_accepts_wallet_without_transaction_hash():
    request = CaseCreate(wallet_address=WALLET, chain="ethereum", theft_transaction_hash="")
    assert request.theft_transaction_hash is None


@pytest.mark.asyncio
async def test_wallet_only_workflow_discovers_then_rpc_verifies_transaction():
    repository = InMemoryCaseRepository()
    await repository.initialize()
    workflow = CaseWorkflow(
        repository,
        StubProvider(),
        StubClassifier(),
        discovery=StubDiscovery(),
    )
    response = await workflow.create_and_investigate(
        CaseCreate(
            wallet_address=WALLET,
            chain="ethereum",
            incident_time=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
        )
    )
    assert response.case.state == "COMPLETE"
    assert response.case.theft_transaction_hash == TX_HASH
    assert response.case.discovery
    assert response.case.discovery.source == "bitquery"
    assert response.case.evidence
    assert response.case.evidence.transaction.hash == TX_HASH


def bitquery_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["authorization"] == "Bearer ory_fixture"
    body = json.loads(request.content)
    variables = body["variables"]
    assert variables["wallet"] == WALLET
    assert variables["since"] == "2026-08-15T12:00:00Z"
    assert variables["till"] == "2026-08-29T12:00:00Z"
    assert "$since: DateTime!" in body["query"]
    assert "Block: {Time: {since: $since, till: $till}}" in body["query"]
    return httpx.Response(
        200,
        json={
            "data": {
                "EVM": {
                    "Transfers": [
                        {
                            "Block": {"Time": "2026-08-22T12:02:00Z", "Number": "123"},
                            "Transaction": {
                                "Hash": TX_HASH,
                                "From": WALLET,
                                "To": COUNTERPARTY,
                            },
                            "Transfer": {
                                "Sender": WALLET,
                                "Receiver": COUNTERPARTY,
                                "Amount": "5000",
                                "AmountInUSD": "5000",
                                "Type": "transfer",
                                "Currency": {
                                    "Name": "USD Coin",
                                    "Symbol": "USDC",
                                    "SmartContract": "0x" + "33" * 20,
                                    "Native": False,
                                    "Fungible": True,
                                },
                            },
                        }
                    ]
                }
            }
        },
    )


@pytest.mark.asyncio
async def test_bitquery_history_ranks_incident_near_reported_time_and_scopes_query():
    discovery = BitqueryIncidentDiscovery(
        access_token="ory_fixture",
        transport=httpx.MockTransport(bitquery_handler),
    )
    result = await discovery.discover(
        "ethereum",
        WALLET,
        datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
    )
    assert result.selected_transaction_hash == TX_HASH
    assert result.candidate_count == 1
    assert any("reported incident time" in reason for reason in result.candidates[0].reasons)


@pytest.mark.asyncio
async def test_bitquery_history_without_incident_time_does_not_force_time_filter():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["variables"] == {"wallet": WALLET}
        assert "$since" not in body["query"]
        assert "Block: {Time:" not in body["query"]
        return httpx.Response(200, json={"data": {"EVM": {"Transfers": []}}})

    discovery = BitqueryIncidentDiscovery(
        access_token="ory_fixture",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LookupError):
        await discovery.discover("ethereum", WALLET)


@pytest.mark.asyncio
async def test_goplus_malicious_address_flags_are_normalized_and_cached():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["chain_id"] == "1"
        return httpx.Response(
            200,
            json={"result": {"phishing_activities": "1", "stealing_attack": "0"}},
        )

    client = GoPlusAddressClient(transport=httpx.MockTransport(handler))
    first = await client.check("ethereum", COUNTERPARTY)
    second = await client.check("ethereum", COUNTERPARTY)
    assert first["malicious"] is True
    assert first["flags"] == ["phishing_activities"]
    assert second == first
    assert calls == 1


@pytest.mark.asyncio
async def test_chainabuse_uses_basic_auth_and_caches_report_count():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["authorization"].startswith("Basic ")
        assert request.url.params["address"] == COUNTERPARTY
        return httpx.Response(
            200,
            json={
                "reports": [
                    {"confidenceScore": 80},
                    {"confidenceScore": 95},
                ],
                "total": 2,
            },
        )

    client = ChainabuseClient(
        api_key="fixture-key",
        transport=httpx.MockTransport(handler),
    )
    first = await client.check(COUNTERPARTY)
    second = await client.check(COUNTERPARTY)
    assert first["report_count"] == 2
    assert first["max_confidence"] == 95
    assert second == first
    assert calls == 1
