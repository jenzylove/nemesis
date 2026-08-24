from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.agent_runtime import InvestigationClassifier, UnavailableClassifier, ensure_facts_unchanged, evidence_consistent_fallback, validate_agent_finding
from app.attribution import CuratedAttributionProvider, EntityAttribution, EntityAttributionProvider
from app.config import Settings
from app.models import AgentFinding, CaseCreate, DeterministicEvidence, NormalizedTransaction
from app.providers import JsonRpcProvider, TRANSFER_TOPIC, decode_erc20_transfer_logs, decode_erc721_transfer_logs
from app.repository import InMemoryCaseRepository
from app.taskmaster import EventPublisher, InMemoryMonitoringRepository, Taskmaster
from app.workflow import CaseWorkflow
TX_HASH = '0x' + 'ab' * 32
WALLET = '0x' + '11' * 20
FROM = '0x' + '22' * 20
TO = '0x' + '33' * 20
TOKEN = '0x' + '44' * 20
TOKEN2 = '0x' + '99' * 20
A = '0x' + 'a1' * 20
B = '0x' + 'b2' * 20
C = '0x' + 'c3' * 20
D = '0x' + 'd4' * 20
E = '0x' + 'e5' * 20
ROUTER = '0x' + '12' * 20
POOL = '0x' + '13' * 20
BASE_L1_BRIDGE = '0x3154cf16ccdb4c6d922629664174b904d80f2c35'

def h(byte: str) -> str:
    return '0x' + byte * 64

def topic(address):
    return '0x' + '0' * 24 + address[2:]

def transfer_log(amount=100):
    return {'logIndex': '0x2', 'address': TOKEN, 'topics': [TRANSFER_TOPIC, topic(FROM), topic(TO)], 'data': hex(amount)}

def make_tx(hash_value, chain, block, source, destination, transfers=None, native=0):
    return NormalizedTransaction(hash=hash_value, chain=chain, block_number=block, timestamp=datetime.now(timezone.utc), status='success', from_address=source, to_address=destination, native_value_wei=str(native), input='0x', erc20_transfers=transfers or [])

def token_transfer(index, token, source, destination, amount):
    return {'log_index': index, 'token_contract': token, 'from_address': source, 'to_address': destination, 'raw_amount': str(amount)}

class FixtureRpc(JsonRpcProvider):

    def __init__(self, status='0x1'):
        super().__init__({'ethereum': 'fixture'})
        self.status = status
        self.calls = []

    async def _call(self, chain, method, params):
        self.calls.append(method)
        if method == 'eth_getTransactionByHash':
            return {'hash': TX_HASH, 'blockNumber': '0x10', 'from': FROM, 'to': TO, 'value': '0x5', 'input': '0x1234'}
        if method == 'eth_getTransactionReceipt':
            return {'status': self.status, 'blockNumber': '0x10', 'logs': [transfer_log(255)]}
        if method == 'eth_getBlockByNumber':
            return {'timestamp': '0x65a0bc00'}

    async def get_address_movements(self, chain, address, after_block, max_blocks=20):
        return (after_block, [])

class FixtureClassifier(InvestigationClassifier):

    async def classify(self, case_id, evidence):
        return AgentFinding(classification='unknown', summary='The supplied transaction is verified, but this evidence is insufficient to determine the compromise mechanism.', confidence=0.2, evidence_references=['transaction.hash', 'transaction.status'], limitations=['Only the supplied transaction was examined.'])

@pytest.mark.asyncio
async def test_transaction_normalization_uses_transaction_receipt_and_block():
    provider = FixtureRpc()
    tx = await provider.get_normalized_transaction('ethereum', TX_HASH)
    assert provider.calls == ['eth_getTransactionByHash', 'eth_getTransactionReceipt', 'eth_getBlockByNumber']
    assert tx.hash == TX_HASH and tx.block_number == 16 and (tx.native_value_wei == '5')
    assert tx.timestamp == datetime.fromtimestamp(int('65a0bc00', 16), tz=timezone.utc)
    assert tx.status == 'success'

@pytest.mark.asyncio
async def test_failed_receipt_is_normalized_as_failed():
    tx = await FixtureRpc(status='0x0').get_normalized_transaction('ethereum', TX_HASH)
    assert tx.status == 'failed'

def test_erc20_transfer_log_decoding():
    transfers = decode_erc20_transfer_logs([transfer_log(987654321), {'topics': [], 'address': TOKEN}])
    assert len(transfers) == 1
    assert transfers[0].from_address == FROM and transfers[0].to_address == TO
    assert transfers[0].token_contract == TOKEN and transfers[0].raw_amount == '987654321'

def test_erc721_transfer_log_decoding():
    nft_log = {
        "logIndex": "0x3",
        "address": TOKEN,
        "topics": [TRANSFER_TOPIC, topic(FROM), topic(TO), hex(42)],
        "data": "0x",
    }
    transfers = decode_erc721_transfer_logs([nft_log])
    assert len(transfers) == 1
    assert transfers[0].token_id == "42"
    assert transfers[0].from_address == FROM
    assert transfers[0].to_address == TO

def test_fallback_matches_native_only_evidence():
    evidence = DeterministicEvidence(
        submitted_wallet=FROM,
        transaction=make_tx(TX_HASH, "ethereum", 1, FROM, TO, native=5),
    )
    finding = evidence_consistent_fallback(evidence)
    assert "native value movement" in finding.summary
    assert "token transfer activity" not in finding.summary
    assert finding.evidence_references == [
        "submitted_wallet",
        "transaction.native_value_wei",
    ]

def test_agent_cannot_overwrite_deterministic_facts():
    tx = make_tx(TX_HASH, 'ethereum', 1, FROM, TO)
    original = DeterministicEvidence(submitted_wallet=WALLET, transaction=tx)
    changed = original.model_copy(deep=True)
    changed.transaction.hash = '0x' + 'ff' * 32
    with pytest.raises(ValueError, match='alter deterministic evidence'):
        ensure_facts_unchanged(original, changed)

def test_agent_cannot_reference_unsupported_facts():
    evidence = DeterministicEvidence(submitted_wallet=WALLET, transaction=make_tx(TX_HASH, 'ethereum', 1, FROM, TO))
    finding = AgentFinding(classification='unknown', summary='The evidence is insufficient.', confidence=0.1, evidence_references=['transaction.exchange'], limitations=[])
    with pytest.raises(ValueError, match='unsupported evidence references'):
        validate_agent_finding(finding, evidence)

def test_unsupported_gemini_entity_attribution_is_rejected():
    evidence = DeterministicEvidence(submitted_wallet=WALLET, transaction=make_tx(TX_HASH, 'ethereum', 1, FROM, TO))
    finding = AgentFinding(classification='unknown', summary='The funds reached an exchange.', confidence=0.1, evidence_references=['transaction.to_address'], limitations=[])
    with pytest.raises(ValueError, match='unsupported semantic attribution'):
        validate_agent_finding(finding, evidence)

def test_unsupported_named_protocol_attribution_is_rejected():
    evidence = DeterministicEvidence(submitted_wallet=WALLET, transaction=make_tx(TX_HASH, 'ethereum', 1, FROM, TO))
    finding = AgentFinding(classification='unknown', summary='The transaction interacted with a UniswapX reactor contract using Permit2.', confidence=0.1, evidence_references=['transaction.to_address'], limitations=[])
    with pytest.raises(ValueError, match='unsupported named entity attribution'):
        validate_agent_finding(finding, evidence)

def test_production_settings_require_real_integrations():
    with pytest.raises(ValueError, match='production configuration is incomplete'):
        Settings(app_env='production', _env_file=None)

def test_production_settings_accept_vertex_firestore_and_rpc_configuration():
    settings = Settings(app_env='production', google_genai_use_vertexai=True, google_cloud_project='nemesis', firestore_project_id='nemesis', ethereum_rpc_url='https://ethereum.example', base_rpc_url='https://base.example', _env_file=None)
    assert settings.google_genai_use_vertexai and settings.firestore_project_id == 'nemesis'
    assert settings.trace_max_depth == 8

@pytest.mark.asyncio
async def test_case_creation_persistence_and_api_response_structure():
    repository = InMemoryCaseRepository()
    await repository.initialize()
    workflow = CaseWorkflow(repository, FixtureRpc(), FixtureClassifier())
    request = CaseCreate(wallet_address=FROM, chain='ethereum', theft_transaction_hash=TX_HASH)
    first = await workflow.create_and_investigate(request, "test-user")
    second = await workflow.create_and_investigate(request, "test-user")
    assert first.case.id != second.case.id
    stored = await repository.get(first.case.id)
    assert stored and stored.state == 'EVIDENCE_READY' and stored.evidence
    payload = first.model_dump(mode='json')
    assert payload['factual_source'] == 'json_rpc' and payload['agent_runtime'] == 'google_adk_gemini'
    assert payload['case']['evidence']['transaction']['erc20_transfers'][0]['raw_amount'] == '255'
    assert payload['case']['finding']['classification'] == 'unknown'

@pytest.mark.asyncio
async def test_rpc_evidence_is_persisted_when_gemini_credentials_are_missing():
    repository = InMemoryCaseRepository()
    await repository.initialize()
    workflow = CaseWorkflow(repository, FixtureRpc(), UnavailableClassifier())
    response = await workflow.create_and_investigate(CaseCreate(wallet_address=FROM, chain='ethereum', theft_transaction_hash=TX_HASH), "test-user")
    assert response.agent_runtime == 'unavailable' and response.case.state == 'EVIDENCE_READY'
    stored = await repository.get(response.case.id)
    assert stored and stored.evidence and (stored.evidence.transaction.hash == TX_HASH) and (stored.finding is None)

def test_api_schema_rejects_invalid_wallet_and_hash():
    from app.main import app
    with TestClient(app) as client:
        response = client.post('/v1/cases', json={'wallet_address': 'bad', 'chain': 'ethereum', 'theft_transaction_hash': 'bad'})
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], list) and len(response.json()['detail']) >= 2

class QueuePublisher(EventPublisher):

    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)
        return str(len(self.events))

class MovementRpc(FixtureRpc):

    async def get_address_movements(self, chain, address, after_block, max_blocks=20):
        return (after_block + 1, [{'transaction_hash': TX_HASH, 'block_number': after_block + 1, 'kind': 'erc20', 'direction': 'out'}])

class AutonomousRpc(FixtureRpc):

    def __init__(self):
        super().__init__()
        self.movement = False
        self.resume_hash = '0x' + 'cd' * 32

    async def get_address_movements(self, chain, address, after_block, max_blocks=20):
        return (after_block + 1, [{'transaction_hash': self.resume_hash, 'block_number': after_block + 1, 'kind': 'erc20', 'direction': 'out'}]) if self.movement else (after_block + 1, [])

    async def get_normalized_transaction(self, chain, tx_hash):
        if tx_hash == self.resume_hash:
            return make_tx(tx_hash, chain, 18, TO, '0x' + '55' * 20, [token_transfer(1, TOKEN, TO, '0x' + '66' * 20, 60), token_transfer(2, TOKEN, TO, '0x' + '77' * 20, 40)])
        return await super().get_normalized_transaction(chain, tx_hash)

class AddressScanRpc(JsonRpcProvider):

    def __init__(self):
        super().__init__({'ethereum': 'fixture'})

    async def _call(self, chain, method, params):
        if method == 'eth_blockNumber':
            return '0x11'
        if method == 'eth_getBlockByNumber':
            number = int(params[0], 16)
            return {'transactions': [{'hash': TX_HASH, 'from': WALLET if number == 17 else FROM, 'to': TO}]}
        if method == 'eth_getLogs':
            return []

class MixedDirectionRpc(JsonRpcProvider):

    def __init__(self):
        super().__init__({'ethereum': 'fixture'})

    async def _call(self, chain, method, params):
        if method == 'eth_blockNumber':
            return '0x11'
        if method == 'eth_getBlockByNumber':
            return {'transactions': [{'hash': TX_HASH, 'from': FROM, 'to': WALLET}]}
        if method == 'eth_getLogs' and params[0]['topics'][1] is not None:
            return [{'transactionHash': TX_HASH, 'blockNumber': '0x11'}]
        if method == 'eth_getLogs':
            return []

@pytest.mark.asyncio
async def test_real_rpc_address_recheck_scans_confirmed_blocks():
    cursor, movements = await AddressScanRpc().get_address_movements('ethereum', WALLET, 16, 20)
    assert cursor == 17 and movements == [{'transaction_hash': TX_HASH, 'block_number': 17, 'kind': 'native_or_contract', 'direction': 'out'}]

@pytest.mark.asyncio
async def test_outgoing_token_log_overrides_same_transaction_inbound_call():
    _, movements = await MixedDirectionRpc().get_address_movements('ethereum', WALLET, 16, 20)
    assert movements == [{'transaction_hash': TX_HASH, 'block_number': 17, 'kind': 'erc20', 'direction': 'out'}]

@pytest.mark.asyncio
async def test_automatic_split_dormant_monitor_resume_graph_and_idempotency():
    repo = InMemoryMonitoringRepository()
    publisher = QueuePublisher()
    rpc = AutonomousRpc()
    agent = Taskmaster(repo, rpc, publisher)
    tx = make_tx(TX_HASH, 'ethereum', 16, WALLET, TO, [token_transfer(1, TOKEN, WALLET, TO, 75), token_transfer(2, TOKEN, WALLET, '0x' + '88' * 20, 25)])
    branches = await agent.trace_initial('NMS-TEST', DeterministicEvidence(submitted_wallet=WALLET, transaction=tx))
    assert len(branches) == 2 and all((b.status == 'DORMANT' for b in branches))
    assert await agent.schedule() == 2
    rpc.movement = True
    recheck = publisher.events.pop(0)
    result = await agent.consume(recheck)
    assert result['movement'] and (await agent.consume(recheck))['duplicate'] is True
    trace_event = publisher.events[-1]
    resumed = await agent.consume(trace_event)
    assert resumed['resumed'] and resumed['extended'] and (resumed['branches'] == 2)
    all_branches = await repo.list_branches(case_id='NMS-TEST')
    assert len(all_branches) == 3 and all((b.status == 'DORMANT' for b in all_branches))
    graph = await repo.get_graph('NMS-TEST')
    assert len(graph['edges']) == 4
    types = [event.type for event in await repo.get_timeline('NMS-TEST')]
    assert {'TRACING_FUNDS', 'BRANCH_CREATED', 'BRANCH_DORMANT', 'MONITORING_ACTIVE', 'MOVEMENT_DETECTED', 'TRACING_RESUMED', 'FUND_SPLIT_DETECTED'} <= set(types)

class TableRpc(JsonRpcProvider):

    def __init__(self, transactions=None, movements=None, bridge_resolutions=None):
        super().__init__({'ethereum': 'fixture', 'base': 'fixture'})
        self.transactions = transactions or {}
        self.movements = movements or {}
        self.bridge_resolutions = bridge_resolutions or {}

    async def get_normalized_transaction(self, chain, tx_hash):
        return self.transactions[chain, tx_hash]

    async def get_address_movements(self, chain, address, after_block, max_blocks=20):
        candidates = [m for m in self.movements.get((chain, address.lower()), []) if m['block_number'] > after_block]
        cursor = max([after_block + 1, *[m['block_number'] for m in candidates]])
        return (cursor, candidates)

    async def resolve_bridge_destination(self, bridge_evidence):
        return self.bridge_resolutions.get(bridge_evidence['source_transaction'])

async def trace_fixture(rpc, *, max_depth=8, attribution_provider=None, case_id='NMS-TRACE'):
    repo = InMemoryMonitoringRepository()
    publisher = QueuePublisher()
    taskmaster = Taskmaster(repo, rpc, publisher, max_blocks=20, max_depth=max_depth, attribution_provider=attribution_provider)
    theft = make_tx(h('1'), 'ethereum', 1, WALLET, A, [token_transfer(1, TOKEN, WALLET, A, 100)])
    await taskmaster.trace_initial(case_id, DeterministicEvidence(submitted_wallet=WALLET, transaction=theft))
    return (taskmaster, repo, publisher)

@pytest.mark.asyncio
async def test_multi_hop_tracing_persists_every_hop_until_dormant():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, B, [token_transfer(1, TOKEN, A, B, 100)])
    tx3 = make_tx(h('3'), 'ethereum', 3, B, C, [token_transfer(1, TOKEN, B, C, 100)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2, ('ethereum', h('3')): tx3}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}], ('ethereum', B): [{'transaction_hash': h('3'), 'block_number': 3, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branches = await repo.list_branches(case_id='NMS-TRACE')
    assert len(branches) == 1
    branch = branches[0]
    assert branch.current_address == C and branch.depth == 3 and (branch.status == 'DORMANT')
    graph = await repo.get_graph('NMS-TRACE')
    assert len(graph['edges']) == 3
    assert {edge.transaction_hash for edge in graph['edges']} == {h('1'), h('2'), h('3')}

@pytest.mark.asyncio
async def test_configured_maximum_depth_stops_trace_deterministically():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, B, [token_transfer(1, TOKEN, A, B, 100)])
    tx3 = make_tx(h('3'), 'ethereum', 3, B, C, [token_transfer(1, TOKEN, B, C, 100)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2, ('ethereum', h('3')): tx3}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}], ('ethereum', B): [{'transaction_hash': h('3'), 'block_number': 3, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc, max_depth=2)
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.current_address == B and branch.status == 'OBSCURED' and (branch.terminal_reason == 'MAX_DEPTH')
    assert 'MAX_DEPTH_REACHED' in [e.type for e in await repo.get_timeline('NMS-TRACE')]

@pytest.mark.asyncio
async def test_fund_split_creates_independent_branches_with_parent_relationship():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, ROUTER, [token_transfer(1, TOKEN, A, B, 60), token_transfer(2, TOKEN, A, C, 40)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branches = await repo.list_branches(case_id='NMS-TRACE')
    assert sorted(((b.current_address, b.amount) for b in branches)) == [(B, '60'), (C, '40')]
    child = next((b for b in branches if b.parent_branch_id))
    parent = next((b for b in branches if b.id == child.parent_branch_id))
    assert parent.current_address == B and child.current_address == C
    assert all((b.status == 'DORMANT' for b in branches))
    assert 'FUND_SPLIT_DETECTED' in [e.type for e in await repo.get_timeline('NMS-TRACE')]

@pytest.mark.asyncio
async def test_swap_detection_changes_asset_without_claiming_protocol():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, ROUTER, [token_transfer(1, TOKEN, A, ROUTER, 100), token_transfer(2, TOKEN2, POOL, A, 50)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.current_address == A and branch.asset == TOKEN2 and (branch.amount == '50') and (branch.status == 'DORMANT')
    event = next((e for e in await repo.get_timeline('NMS-TRACE') if e.type == 'SWAP_DETECTED'))
    assert event.data['asset_before'] == TOKEN and event.data['assets_after'] == [{'asset': TOKEN2, 'amount': '50'}]
    assert 'protocol' not in event.data

@pytest.mark.asyncio
async def test_swap_resulting_asset_continues_on_subsequent_hop():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, ROUTER, [token_transfer(1, TOKEN, A, ROUTER, 100), token_transfer(2, TOKEN2, POOL, A, 50)])
    tx3 = make_tx(h('3'), 'ethereum', 3, A, B, [token_transfer(1, TOKEN2, A, B, 50)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2, ('ethereum', h('3')): tx3}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}, {'transaction_hash': h('3'), 'block_number': 3, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.current_address == B and branch.asset == TOKEN2 and (branch.amount == '50') and (branch.depth == 3)

@pytest.mark.asyncio
async def test_supported_base_bridge_is_detected_and_unresolved_destination_is_not_invented():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, BASE_L1_BRIDGE, [token_transfer(1, TOKEN, A, BASE_L1_BRIDGE, 100)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.status == 'OBSCURED' and branch.terminal_reason == 'BRIDGE_DESTINATION_UNRESOLVED'
    event = next((e for e in await repo.get_timeline('NMS-TRACE') if e.type == 'BRIDGE_DETECTED'))
    assert event.data['source_chain'] == 'ethereum' and event.data['destination_chain'] == 'base'
    assert event.data['destination_transaction_hash'] is None

@pytest.mark.asyncio
async def test_unsupported_bridge_attribution_is_rejected_by_exact_match_rule():
    unknown_contract = '0x' + '77' * 20
    tx2 = make_tx(h('2'), 'ethereum', 2, A, unknown_contract, [token_transfer(1, TOKEN, A, unknown_contract, 100)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    assert 'BRIDGE_DETECTED' not in [e.type for e in await repo.get_timeline('NMS-TRACE')]
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.current_address == unknown_contract and branch.status == 'DORMANT'

@pytest.mark.asyncio
async def test_cross_chain_continuation_occurs_only_with_destination_evidence():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, BASE_L1_BRIDGE, [token_transfer(1, TOKEN, A, BASE_L1_BRIDGE, 100)])
    tx3 = make_tx(h('4'), 'base', 101, D, E, [token_transfer(1, TOKEN, D, E, 100)])
    resolution = {'destination_chain': 'base', 'destination_address': D, 'destination_transaction_hash': h('3'), 'destination_block_number': 100, 'destination_asset': TOKEN, 'destination_amount': '100', 'source': 'fixture deterministic bridge resolver', 'evidence_type': 'destination_receipt_match', 'provenance': ['fixture_bridge_receipt', h('3')]}
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2, ('base', h('4')): tx3}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}], ('base', D): [{'transaction_hash': h('4'), 'block_number': 101, 'kind': 'erc20', 'direction': 'out'}]}, bridge_resolutions={h('2'): resolution})
    _, repo, _ = await trace_fixture(rpc)
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.chain == 'base' and branch.current_address == E and (branch.status == 'DORMANT')
    types = [e.type for e in await repo.get_timeline('NMS-TRACE')]
    assert 'BRIDGE_DETECTED' in types and 'CROSS_CHAIN_TRACE_CONTINUED' in types
    graph = await repo.get_graph('NMS-TRACE')
    assert any((edge.kind == 'bridge' and edge.destination_chain == 'base' for edge in graph['edges']))

def test_entity_attribution_schema_rejects_invalid_type_and_requires_evidence_source():
    with pytest.raises(ValidationError):
        EntityAttribution(entity_name='Bad', entity_type='wallet', address=A, chain='ethereum', source='fixture', confidence=1, evidence_type='curated')
    with pytest.raises(ValidationError):
        EntityAttribution(entity_name='Bad', entity_type='exchange', address=A, chain='ethereum', source='', confidence=1, evidence_type='curated')

class MismatchedAttributionProvider(EntityAttributionProvider):

    async def lookup(self, chain, address):
        return EntityAttribution(entity_name='Mismatch', entity_type='exchange', address=B, chain=chain, source='fixture', confidence=1, evidence_type='curated')

@pytest.mark.asyncio
async def test_entity_attribution_provider_must_match_exact_chain_and_address():
    rpc = TableRpc()
    with pytest.raises(ValueError, match='mismatched deterministic identity'):
        await trace_fixture(rpc, attribution_provider=MismatchedAttributionProvider())

@pytest.mark.asyncio
async def test_actionable_branch_transition_requires_deterministic_exchange_or_service_attribution():
    attribution = EntityAttribution(entity_name='Fixture Exchange', entity_type='exchange', address=A, chain='ethereum', source='fixture curated attribution', confidence=1.0, evidence_type='exact_address_match')
    provider = CuratedAttributionProvider([attribution])
    _, repo, _ = await trace_fixture(TableRpc(), attribution_provider=provider)
    branch = (await repo.list_branches(case_id='NMS-TRACE'))[0]
    assert branch.status == 'ACTIONABLE' and branch.attribution == attribution
    event = next((e for e in await repo.get_timeline('NMS-TRACE') if e.type == 'ACTIONABLE_DESTINATION_DETECTED'))
    assert event.data['entity_name'] == 'Fixture Exchange' and event.data['source'] == 'fixture curated attribution'

@pytest.mark.asyncio
async def test_autonomous_monitoring_resume_follows_multiple_hops_before_returning_to_monitoring():
    rpc = TableRpc()
    taskmaster, repo, publisher = await trace_fixture(rpc, case_id='NMS-AUTO')
    initial = (await repo.list_branches(case_id='NMS-AUTO'))[0]
    assert initial.status == 'DORMANT' and initial.current_address == A
    block2 = initial.cursor_block + 1
    block3 = block2 + 1
    tx2 = make_tx(h('2'), 'ethereum', block2, A, B, [token_transfer(1, TOKEN, A, B, 100)])
    tx3 = make_tx(h('3'), 'ethereum', block3, B, C, [token_transfer(1, TOKEN, B, C, 100)])
    rpc.transactions = {('ethereum', h('2')): tx2, ('ethereum', h('3')): tx3}
    rpc.movements = {('ethereum', A): [{'transaction_hash': h('2'), 'block_number': block2, 'kind': 'erc20', 'direction': 'out'}], ('ethereum', B): [{'transaction_hash': h('3'), 'block_number': block3, 'kind': 'erc20', 'direction': 'out'}]}
    assert await taskmaster.schedule() == 1
    recheck_event = publisher.events.pop(0)
    assert (await taskmaster.consume(recheck_event))['movement']
    trace_event = publisher.events.pop(0)
    result = await taskmaster.consume(trace_event)
    assert result['resumed'] and result['extended']
    final = (await repo.list_branches(case_id='NMS-AUTO'))[0]
    assert final.current_address == C and final.depth == 3 and (final.status == 'DORMANT')
    types = [e.type for e in await repo.get_timeline('NMS-AUTO')]
    assert types.count('TRACING_RESUMED') == 1 and 'MONITORING_ACTIVE' in types

@pytest.mark.asyncio
async def test_duplicate_pubsub_event_does_not_duplicate_trace_or_timeline_events():
    rpc = TableRpc()
    taskmaster, repo, publisher = await trace_fixture(rpc, case_id='NMS-DUPE')
    initial = (await repo.list_branches(case_id='NMS-DUPE'))[0]
    block2 = initial.cursor_block + 1
    tx2 = make_tx(h('2'), 'ethereum', block2, A, B, [token_transfer(1, TOKEN, A, B, 100)])
    rpc.transactions = {('ethereum', h('2')): tx2}
    rpc.movements = {('ethereum', A): [{'transaction_hash': h('2'), 'block_number': block2, 'kind': 'erc20', 'direction': 'out'}]}
    await taskmaster.schedule()
    event = publisher.events.pop(0)
    first = await taskmaster.consume(event)
    count_after_first = len(await repo.get_timeline('NMS-DUPE'))
    second = await taskmaster.consume(event)
    count_after_second = len(await repo.get_timeline('NMS-DUPE'))
    assert first['movement'] and second == {'duplicate': True}
    assert count_after_first == count_after_second

@pytest.mark.asyncio
async def test_split_children_keep_same_hop_depth():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, ROUTER, [token_transfer(1, TOKEN, A, B, 60), token_transfer(2, TOKEN, A, C, 40)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branches = await repo.list_branches(case_id='NMS-TRACE')
    assert {branch.depth for branch in branches} == {2}

@pytest.mark.asyncio
async def test_partial_token_transfer_preserves_residual_branch_and_traces_it_independently():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, B, [token_transfer(1, TOKEN, A, B, 60)])
    tx3 = make_tx(h('3'), 'ethereum', 3, A, C, [token_transfer(1, TOKEN, A, C, 40)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2, ('ethereum', h('3')): tx3}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}, {'transaction_hash': h('3'), 'block_number': 3, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branches = await repo.list_branches(case_id='NMS-TRACE')
    assert sorted(((branch.current_address, branch.amount) for branch in branches)) == [(B, '60'), (C, '40')]
    assert all((branch.status == 'DORMANT' for branch in branches))

@pytest.mark.asyncio
async def test_known_bridge_call_without_tracked_asset_transfer_is_not_attributed_as_bridge():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, BASE_L1_BRIDGE, [token_transfer(1, TOKEN2, A, BASE_L1_BRIDGE, 10)])
    provider = JsonRpcProvider({'ethereum': 'fixture', 'base': 'fixture'})
    evidence = await provider.get_bridge_evidence('ethereum', tx2, A, TOKEN, '100')
    assert evidence is None

@pytest.mark.asyncio
async def test_bridge_graph_contains_source_and_cross_chain_bridge_edges_when_resolved():
    destination_hash = h('9')
    tx2 = make_tx(h('2'), 'ethereum', 2, A, BASE_L1_BRIDGE, [token_transfer(1, TOKEN, A, BASE_L1_BRIDGE, 100)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]}, bridge_resolutions={h('2'): {'destination_chain': 'base', 'destination_address': B, 'destination_transaction_hash': destination_hash, 'destination_block_number': 20, 'destination_asset': TOKEN, 'destination_amount': '100', 'provenance': ['fixture_bridge_message_match', destination_hash]}})
    _, repo, _ = await trace_fixture(rpc)
    graph = await repo.get_graph('NMS-TRACE')
    bridge_edges = [edge for edge in graph['edges'] if edge.kind == 'bridge']
    assert len(bridge_edges) == 2
    assert any((edge.destination_chain == 'base' for edge in bridge_edges))

@pytest.mark.asyncio
async def test_partial_swap_preserves_unswapped_tracked_asset_as_residual_branch():
    tx2 = make_tx(h('2'), 'ethereum', 2, A, ROUTER, [token_transfer(1, TOKEN, A, ROUTER, 60), token_transfer(2, TOKEN2, POOL, A, 30)])
    rpc = TableRpc(transactions={('ethereum', h('2')): tx2}, movements={('ethereum', A): [{'transaction_hash': h('2'), 'block_number': 2, 'kind': 'erc20', 'direction': 'out'}]})
    _, repo, _ = await trace_fixture(rpc)
    branches = await repo.list_branches(case_id='NMS-TRACE')
    assert sorted(((branch.asset, branch.amount, branch.current_address) for branch in branches)) == [(TOKEN, '40', A), (TOKEN2, '30', A)]
    event = next((event for event in await repo.get_timeline('NMS-TRACE') if event.type == 'SWAP_DETECTED'))
    assert event.data['tracked_amount_spent'] == '60'
    assert event.data['tracked_amount_remaining'] == '40'
