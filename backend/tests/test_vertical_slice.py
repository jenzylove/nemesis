from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from app.agent_runtime import InvestigationClassifier,UnavailableClassifier,ensure_facts_unchanged,validate_agent_finding
from app.config import Settings
from app.models import AgentFinding,CaseCreate,DeterministicEvidence,NormalizedTransaction
from app.providers import JsonRpcProvider,TRANSFER_TOPIC,decode_erc20_transfer_logs
from app.repository import InMemoryCaseRepository
from app.workflow import CaseWorkflow
from app.taskmaster import EventPublisher,InMemoryMonitoringRepository,Taskmaster

TX_HASH="0x"+"ab"*32
WALLET="0x"+"11"*20
FROM="0x"+"22"*20
TO="0x"+"33"*20
TOKEN="0x"+"44"*20

def topic(address):return "0x"+"0"*24+address[2:]
def transfer_log(amount=100):
    return {"logIndex":"0x2","address":TOKEN,"topics":[TRANSFER_TOPIC,topic(FROM),topic(TO)],"data":hex(amount)}

class FixtureRpc(JsonRpcProvider):
    def __init__(self,status="0x1"):super().__init__({"ethereum":"fixture"});self.status=status;self.calls=[]
    async def _call(self,chain,method,params):
        self.calls.append(method)
        if method=="eth_getTransactionByHash":return {"hash":TX_HASH,"blockNumber":"0x10","from":FROM,"to":TO,"value":"0x5","input":"0x1234"}
        if method=="eth_getTransactionReceipt":return {"status":self.status,"blockNumber":"0x10","logs":[transfer_log(255)]}
        if method=="eth_getBlockByNumber":return {"timestamp":"0x65a0bc00"}
    async def get_address_movements(self,chain,address,after_block,max_blocks=20):return after_block,[]

class FixtureClassifier(InvestigationClassifier):
    async def classify(self,case_id,evidence):
        return AgentFinding(classification="unknown",summary="The supplied transaction is verified, but this evidence is insufficient to determine the compromise mechanism.",confidence=.2,evidence_references=["transaction.hash","transaction.status"],limitations=["Only the supplied transaction was examined."])

@pytest.mark.asyncio
async def test_transaction_normalization_uses_transaction_receipt_and_block():
    provider=FixtureRpc();tx=await provider.get_normalized_transaction("ethereum",TX_HASH)
    assert provider.calls==["eth_getTransactionByHash","eth_getTransactionReceipt","eth_getBlockByNumber"]
    assert tx.hash==TX_HASH and tx.block_number==16 and tx.native_value_wei=="5"
    assert tx.timestamp==datetime.fromtimestamp(int("65a0bc00",16),tz=timezone.utc)
    assert tx.status=="success"

@pytest.mark.asyncio
async def test_failed_receipt_is_normalized_as_failed():
    tx=await FixtureRpc(status="0x0").get_normalized_transaction("ethereum",TX_HASH)
    assert tx.status=="failed"

def test_erc20_transfer_log_decoding():
    transfers=decode_erc20_transfer_logs([transfer_log(987654321),{"topics":[],"address":TOKEN}])
    assert len(transfers)==1
    assert transfers[0].from_address==FROM and transfers[0].to_address==TO
    assert transfers[0].token_contract==TOKEN and transfers[0].raw_amount=="987654321"

def test_agent_cannot_overwrite_deterministic_facts():
    tx=NormalizedTransaction(hash=TX_HASH,chain="ethereum",block_number=1,timestamp=datetime.now(timezone.utc),status="success",from_address=FROM,to_address=TO,native_value_wei="0",input="0x",erc20_transfers=[])
    original=DeterministicEvidence(submitted_wallet=WALLET,transaction=tx)
    changed=original.model_copy(deep=True);changed.transaction.hash="0x"+"ff"*32
    with pytest.raises(ValueError,match="alter deterministic evidence"):ensure_facts_unchanged(original,changed)

def test_agent_cannot_reference_unsupported_facts():
    tx=NormalizedTransaction(hash=TX_HASH,chain="ethereum",block_number=1,timestamp=datetime.now(timezone.utc),status="success",from_address=FROM,to_address=TO,native_value_wei="0",input="0x",erc20_transfers=[])
    evidence=DeterministicEvidence(submitted_wallet=WALLET,transaction=tx)
    finding=AgentFinding(classification="unknown",summary="The evidence is insufficient.",confidence=.1,evidence_references=["transaction.exchange"],limitations=[])
    with pytest.raises(ValueError,match="unsupported evidence references"):validate_agent_finding(finding,evidence)

def test_unsupported_gemini_entity_attribution_is_rejected():
    tx=NormalizedTransaction(hash=TX_HASH,chain="ethereum",block_number=1,timestamp=datetime.now(timezone.utc),status="success",from_address=FROM,to_address=TO,native_value_wei="0",input="0x",erc20_transfers=[])
    evidence=DeterministicEvidence(submitted_wallet=WALLET,transaction=tx)
    finding=AgentFinding(classification="unknown",summary="The funds reached an exchange.",confidence=.1,evidence_references=["transaction.to_address"],limitations=[])
    with pytest.raises(ValueError,match="unsupported semantic attribution"):validate_agent_finding(finding,evidence)

def test_production_settings_require_real_integrations():
    with pytest.raises(ValueError,match="production configuration is incomplete"):
        Settings(app_env="production",_env_file=None)

def test_production_settings_accept_vertex_firestore_and_rpc_configuration():
    settings=Settings(app_env="production",google_genai_use_vertexai=True,google_cloud_project="nemesis",firestore_project_id="nemesis",ethereum_rpc_url="https://ethereum.example",base_rpc_url="https://base.example",_env_file=None)
    assert settings.google_genai_use_vertexai and settings.firestore_project_id=="nemesis"

@pytest.mark.asyncio
async def test_case_creation_persistence_and_api_response_structure():
    repository=InMemoryCaseRepository();await repository.initialize()
    workflow=CaseWorkflow(repository,FixtureRpc(),FixtureClassifier())
    request=CaseCreate(wallet_address=WALLET,chain="ethereum",theft_transaction_hash=TX_HASH)
    first=await workflow.create_and_investigate(request);second=await workflow.create_and_investigate(request)
    assert first.case.id!=second.case.id
    stored=await repository.get(first.case.id)
    assert stored and stored.state=="COMPLETE" and stored.evidence
    payload=first.model_dump(mode="json")
    assert payload["factual_source"]=="json_rpc"
    assert payload["agent_runtime"]=="google_adk_gemini"
    assert payload["case"]["evidence"]["transaction"]["erc20_transfers"][0]["raw_amount"]=="255"
    assert payload["case"]["finding"]["classification"]=="unknown"

@pytest.mark.asyncio
async def test_rpc_evidence_is_persisted_when_gemini_credentials_are_missing():
    repository=InMemoryCaseRepository();await repository.initialize()
    workflow=CaseWorkflow(repository,FixtureRpc(),UnavailableClassifier())
    response=await workflow.create_and_investigate(CaseCreate(wallet_address=WALLET,chain="ethereum",theft_transaction_hash=TX_HASH))
    assert response.agent_runtime=="unavailable" and response.case.state=="FAILED"
    stored=await repository.get(response.case.id)
    assert stored and stored.evidence and stored.evidence.transaction.hash==TX_HASH
    assert stored.finding is None

def test_api_schema_rejects_invalid_wallet_and_hash():
    from app.main import app
    with TestClient(app) as client:
        response=client.post("/v1/cases",json={"wallet_address":"bad","chain":"ethereum","theft_transaction_hash":"bad"})
    assert response.status_code==422
    detail=response.json()["detail"]
    assert isinstance(detail,list) and len(detail)>=2

class QueuePublisher(EventPublisher):
    def __init__(self):self.events=[]
    async def publish(self,event):self.events.append(event);return str(len(self.events))
class MovementRpc(FixtureRpc):
    async def get_address_movements(self,chain,address,after_block,max_blocks=20):
        return after_block+1,[{"transaction_hash":TX_HASH,"block_number":after_block+1,"kind":"erc20","direction":"out"}]

class AutonomousRpc(FixtureRpc):
    def __init__(self):super().__init__();self.movement=False;self.resume_hash="0x"+"cd"*32
    async def get_address_movements(self,chain,address,after_block,max_blocks=20):
        return (after_block+1,[{"transaction_hash":self.resume_hash,"block_number":after_block+1,"kind":"erc20","direction":"out"}]) if self.movement else (after_block+1,[])
    async def get_normalized_transaction(self,chain,tx_hash):
        if tx_hash==self.resume_hash:
            return NormalizedTransaction(hash=tx_hash,chain=chain,block_number=18,timestamp=datetime.now(timezone.utc),status="success",from_address=TO,to_address="0x"+"55"*20,native_value_wei="0",input="0x",erc20_transfers=[{"log_index":1,"token_contract":TOKEN,"from_address":TO,"to_address":"0x"+"66"*20,"raw_amount":"60"},{"log_index":2,"token_contract":TOKEN,"from_address":TO,"to_address":"0x"+"77"*20,"raw_amount":"40"}])
        return await super().get_normalized_transaction(chain,tx_hash)

class AddressScanRpc(JsonRpcProvider):
    def __init__(self):super().__init__({"ethereum":"fixture"})
    async def _call(self,chain,method,params):
        if method=="eth_blockNumber":return "0x11"
        if method=="eth_getBlockByNumber":
            number=int(params[0],16)
            return {"transactions":[{"hash":TX_HASH,"from":WALLET if number==17 else FROM,"to":TO}]}
        if method=="eth_getLogs":return []

@pytest.mark.asyncio
async def test_real_rpc_address_recheck_scans_confirmed_blocks():
    cursor,movements=await AddressScanRpc().get_address_movements("ethereum",WALLET,16,20)
    assert cursor==17 and movements==[{"transaction_hash":TX_HASH,"block_number":17,"kind":"native_or_contract","direction":"out"}]

@pytest.mark.asyncio
async def test_automatic_split_dormant_monitor_resume_graph_and_idempotency():
    repo=InMemoryMonitoringRepository();publisher=QueuePublisher();rpc=AutonomousRpc();agent=Taskmaster(repo,rpc,publisher)
    tx=NormalizedTransaction(hash=TX_HASH,chain="ethereum",block_number=16,timestamp=datetime.now(timezone.utc),status="success",from_address=WALLET,to_address=TO,native_value_wei="0",input="0x",erc20_transfers=[{"log_index":1,"token_contract":TOKEN,"from_address":WALLET,"to_address":TO,"raw_amount":"75"},{"log_index":2,"token_contract":TOKEN,"from_address":WALLET,"to_address":"0x"+"88"*20,"raw_amount":"25"}])
    branches=await agent.trace_initial("NMS-TEST",DeterministicEvidence(submitted_wallet=WALLET,transaction=tx))
    assert len(branches)==2 and all(b.status=="DORMANT" for b in branches)
    assert (await agent.schedule())==2
    rpc.movement=True;recheck=publisher.events.pop(0);result=await agent.consume(recheck)
    assert result["movement"] and (await agent.consume(recheck))["duplicate"] is True
    trace_event=publisher.events[-1];resumed=await agent.consume(trace_event)
    assert resumed=={"resumed":True,"extended":True,"branches":2}
    all_branches=await repo.list_branches(case_id="NMS-TEST")
    assert len(all_branches)==3 and all(b.status=="DORMANT" for b in all_branches)
    graph=await repo.get_graph("NMS-TEST");assert len(graph["edges"])==4
    types=[event.type for event in await repo.get_timeline("NMS-TEST")]
    assert {"TRACING_FUNDS","BRANCH_CREATED","BRANCH_DORMANT","MONITORING_ACTIVE","MOVEMENT_DETECTED","TRACING_RESUMED"}<=set(types)
