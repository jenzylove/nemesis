import base64, hashlib, json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

BranchStatus = Literal["MOVING", "DORMANT", "OBSCURED", "ACTIONABLE"]

class TraceBranch(BaseModel):
    id: str; case_id: str; current_address: str; chain: Literal["ethereum", "base"]
    asset: str; amount: str; status: BranchStatus; last_transaction: str
    cursor_block: int = Field(ge=0); last_checked: datetime
    evidence_provenance: list[str] = Field(default_factory=list)

class GraphNode(BaseModel):
    id: str; case_id: str; branch_id: str | None = None; kind: Literal["address", "transaction"]
    label: str; chain: Literal["ethereum", "base"]; address: str | None = None
    transaction_hash: str | None = None; created_at: datetime; provenance: list[str] = Field(default_factory=list)

class GraphEdge(BaseModel):
    id: str; case_id: str; branch_id: str; source: str; target: str; asset: str
    amount: str; transaction_hash: str; chain: Literal["ethereum", "base"]
    created_at: datetime; provenance: list[str] = Field(default_factory=list)

class TimelineEvent(BaseModel):
    id: str; case_id: str; type: str; message: str; created_at: datetime; data: dict = Field(default_factory=dict)

def stable_id(prefix, *parts):
    return prefix + "-" + hashlib.sha256(":".join(str(x).lower() for x in parts).encode()).hexdigest()[:20].upper()

class MonitoringRepository:
    async def save_branch(self, branch): raise NotImplementedError
    async def get_branch(self, branch_id): raise NotImplementedError
    async def list_branches(self, case_id=None, status=None): raise NotImplementedError
    async def claim_event(self, event_id): raise NotImplementedError
    async def append_timeline(self, event): raise NotImplementedError
    async def get_timeline(self, case_id): raise NotImplementedError
    async def save_node(self, node): raise NotImplementedError
    async def save_edge(self, edge): raise NotImplementedError
    async def get_graph(self, case_id): raise NotImplementedError

class InMemoryMonitoringRepository(MonitoringRepository):
    def __init__(self): self.branches={}; self.claims=set(); self.timeline={}; self.nodes={}; self.edges={}
    async def save_branch(self,b): self.branches[b.id]=deepcopy(b); return b
    async def get_branch(self,i): return deepcopy(self.branches.get(i))
    async def list_branches(self,case_id=None,status=None): return [deepcopy(x) for x in self.branches.values() if (not case_id or x.case_id==case_id) and (not status or x.status==status)]
    async def claim_event(self,i):
        if i in self.claims: return False
        self.claims.add(i); return True
    async def append_timeline(self,e): self.timeline[e.id]=deepcopy(e); return e
    async def get_timeline(self,c): return sorted([deepcopy(x) for x in self.timeline.values() if x.case_id==c], key=lambda x:x.created_at)
    async def save_node(self,n): self.nodes[n.id]=deepcopy(n); return n
    async def save_edge(self,e): self.edges[e.id]=deepcopy(e); return e
    async def get_graph(self,c): return {"nodes":[deepcopy(x) for x in self.nodes.values() if x.case_id==c], "edges":[deepcopy(x) for x in self.edges.values() if x.case_id==c]}

class FirestoreMonitoringRepository(MonitoringRepository):
    def __init__(self,client): self.client=client
    async def save_branch(self,b): await self.client.collection("trace_branches").document(b.id).set(b.model_dump(mode="python")); return b
    async def get_branch(self,i):
        s=await self.client.collection("trace_branches").document(i).get(); return TraceBranch.model_validate(s.to_dict()) if s.exists else None
    async def list_branches(self,case_id=None,status=None):
        q=self.client.collection("trace_branches")
        if case_id: q=q.where("case_id","==",case_id)
        if status: q=q.where("status","==",status)
        return [TraceBranch.model_validate(d.to_dict()) async for d in q.stream()]
    async def claim_event(self,i):
        from google.api_core.exceptions import AlreadyExists
        try: await self.client.collection("processed_events").document(i).create({"processed_at":datetime.now(timezone.utc)}); return True
        except AlreadyExists: return False
    async def append_timeline(self,e): await self.client.collection("case_timeline").document(e.id).set(e.model_dump(mode="python")); return e
    async def get_timeline(self,c):
        docs=self.client.collection("case_timeline").where("case_id","==",c).stream(); items=[TimelineEvent.model_validate(d.to_dict()) async for d in docs]; return sorted(items,key=lambda x:x.created_at)
    async def save_node(self,n): await self.client.collection("case_graph_nodes").document(n.id).set(n.model_dump(mode="python")); return n
    async def save_edge(self,e): await self.client.collection("case_graph_edges").document(e.id).set(e.model_dump(mode="python")); return e
    async def get_graph(self,c):
        ns=self.client.collection("case_graph_nodes").where("case_id","==",c).stream(); es=self.client.collection("case_graph_edges").where("case_id","==",c).stream()
        return {"nodes":[GraphNode.model_validate(d.to_dict()) async for d in ns], "edges":[GraphEdge.model_validate(d.to_dict()) async for d in es]}

class EventPublisher:
    async def publish(self,event): raise NotImplementedError

class GooglePubSubPublisher(EventPublisher):
    def __init__(self,project,topic): self.project,self.topic,self.client=project,topic,None
    async def publish(self,event):
        from google.cloud import pubsub_v1
        if self.client is None: self.client=pubsub_v1.PublisherClient()
        return self.client.publish(self.client.topic_path(self.project,self.topic),json.dumps(event).encode()).result(timeout=20)

class Taskmaster:
    def __init__(self,repo,provider,publisher,max_blocks=20): self.repo,self.provider,self.publisher,self.max_blocks=repo,provider,publisher,max_blocks

    async def trace_initial(self,case_id,evidence):
        tx=evidence.transaction; wallet=evidence.submitted_wallet.lower(); now=datetime.now(timezone.utc)
        await self._timeline(case_id,"TRACING_FUNDS","Tracing funds",{"transaction_hash":tx.hash})
        paths=[(t.from_address,t.to_address,t.token_contract,t.raw_amount,f"transaction.erc20_transfers[{i}]") for i,t in enumerate(tx.erc20_transfers) if t.from_address==wallet]
        if tx.from_address==wallet and tx.to_address and int(tx.native_value_wei)>0: paths.append((wallet,tx.to_address,"native",tx.native_value_wei,"transaction.native_value_wei"))
        branches=[]
        for index,(source,destination,asset,amount,ref) in enumerate(paths):
            bid=stable_id("BR",case_id,tx.hash,index,asset,destination)
            branch=TraceBranch(id=bid,case_id=case_id,current_address=destination,chain=tx.chain,asset=asset,amount=amount,status="MOVING",last_transaction=tx.hash,cursor_block=tx.block_number,last_checked=now,evidence_provenance=["json_rpc",ref,tx.hash])
            await self.repo.save_branch(branch); await self._extend_graph(branch,source,destination,tx,ref)
            await self._timeline(case_id,"BRANCH_CREATED","Branch created",{"branch_id":bid,"address":destination,"asset":asset,"amount":amount})
            cursor,moves=await self.provider.get_address_movements(tx.chain,destination,tx.block_number,self.max_blocks); branch.cursor_block=cursor; branch.last_checked=datetime.now(timezone.utc)
            outgoing=[m for m in moves if m.get("direction")=="out"]
            if outgoing:
                await self.repo.save_branch(branch)
                await self.publisher.publish({"id":stable_id("EV",bid,outgoing[0]["transaction_hash"]),"type":"TRACE_REQUESTED","branch_id":bid,"transaction_hash":outgoing[0]["transaction_hash"]})
            else:
                branch.status="DORMANT"; await self.repo.save_branch(branch)
                await self._timeline(case_id,"BRANCH_DORMANT","Dormant wallet detected",{"branch_id":bid,"address":destination})
                await self._timeline(case_id,"MONITORING_ACTIVE","Monitoring active",{"branch_id":bid})
            branches.append(branch)
        return branches

    async def schedule(self):
        branches=await self.repo.list_branches(status="DORMANT")
        for b in branches: await self.publisher.publish({"id":stable_id("EV","recheck",b.id,b.cursor_block),"type":"RECHECK_REQUESTED","branch_id":b.id})
        return len(branches)

    async def consume(self,event):
        if not await self.repo.claim_event(event["id"]): return {"duplicate":True}
        if event["type"]=="RECHECK_REQUESTED": return await self.recheck(event["branch_id"])
        if event["type"]=="TRACE_REQUESTED": return await self.resume(event["branch_id"],event["transaction_hash"])
        raise ValueError("unsupported event type")

    async def recheck(self,branch_id):
        b=await self.repo.get_branch(branch_id)
        if not b or b.status!="DORMANT": return {"ignored":True}
        cursor,moves=await self.provider.get_address_movements(b.chain,b.current_address,b.cursor_block,self.max_blocks); b.cursor_block=cursor; b.last_checked=datetime.now(timezone.utc)
        outgoing=[m for m in moves if m.get("direction")=="out"]
        if not outgoing: await self.repo.save_branch(b); return {"movement":False}
        movement=outgoing[0]; b.status="MOVING"; b.last_transaction=movement["transaction_hash"]; await self.repo.save_branch(b)
        await self._timeline(b.case_id,"MOVEMENT_DETECTED","Movement detected",{"branch_id":b.id,**movement})
        await self.publisher.publish({"id":stable_id("EV","trace",b.id,movement["transaction_hash"]),"type":"TRACE_REQUESTED","branch_id":b.id,"transaction_hash":movement["transaction_hash"]})
        return {"movement":True,"transaction_hash":movement["transaction_hash"]}

    async def resume(self,branch_id,tx_hash):
        b=await self.repo.get_branch(branch_id)
        if not b or b.status!="MOVING": return {"ignored":True}
        tx=await self.provider.get_normalized_transaction(b.chain,tx_hash)
        await self._timeline(b.case_id,"TRACING_RESUMED","Tracing resumed",{"branch_id":b.id,"transaction_hash":tx.hash})
        paths=[(t.to_address,t.token_contract,t.raw_amount,f"transaction.erc20_transfers[{i}]") for i,t in enumerate(tx.erc20_transfers) if t.from_address==b.current_address]
        if tx.from_address==b.current_address and tx.to_address and int(tx.native_value_wei)>0: paths.append((tx.to_address,"native",tx.native_value_wei,"transaction.native_value_wei"))
        if not paths:
            b.status="DORMANT"; b.cursor_block=tx.block_number; b.last_transaction=tx.hash; b.last_checked=datetime.now(timezone.utc); await self.repo.save_branch(b)
            await self._timeline(b.case_id,"BRANCH_DORMANT","Dormant wallet detected",{"branch_id":b.id,"address":b.current_address}); return {"resumed":True,"extended":False}
        for index,(destination,asset,amount,ref) in enumerate(paths):
            target=b if index==0 else b.model_copy(update={"id":stable_id("BR",b.case_id,tx.hash,index,asset,destination)})
            source=b.current_address; target.current_address=destination; target.asset=asset; target.amount=amount; target.last_transaction=tx.hash; target.cursor_block=tx.block_number; target.last_checked=datetime.now(timezone.utc); target.status="DORMANT"; target.evidence_provenance=["json_rpc",ref,tx.hash]
            await self.repo.save_branch(target); await self._extend_graph(target,source,destination,tx,ref)
            if index>0: await self._timeline(b.case_id,"BRANCH_CREATED","Branch created",{"branch_id":target.id,"address":destination,"asset":asset,"amount":amount})
            await self._timeline(b.case_id,"BRANCH_DORMANT","Dormant wallet detected",{"branch_id":target.id,"address":destination})
        return {"resumed":True,"extended":True,"branches":len(paths)}

    async def case_trace(self,case_id):
        graph=await self.repo.get_graph(case_id)
        return {"branches":[b.model_dump(mode="json") for b in await self.repo.list_branches(case_id=case_id)],"graph":{"nodes":[n.model_dump(mode="json") for n in graph["nodes"]],"edges":[e.model_dump(mode="json") for e in graph["edges"]]},"timeline":[e.model_dump(mode="json") for e in await self.repo.get_timeline(case_id)]}

    async def _extend_graph(self,b,source,destination,tx,ref):
        now=datetime.now(timezone.utc); src=stable_id("NODE",b.case_id,b.chain,source); dst=stable_id("NODE",b.case_id,b.chain,destination)
        await self.repo.save_node(GraphNode(id=src,case_id=b.case_id,branch_id=b.id,kind="address",label="Wallet",chain=b.chain,address=source,created_at=now,provenance=["json_rpc",tx.hash]))
        await self.repo.save_node(GraphNode(id=dst,case_id=b.case_id,branch_id=b.id,kind="address",label="Wallet",chain=b.chain,address=destination,created_at=now,provenance=["json_rpc",tx.hash]))
        await self.repo.save_edge(GraphEdge(id=stable_id("EDGE",b.id,tx.hash,source,destination,b.asset),case_id=b.case_id,branch_id=b.id,source=src,target=dst,asset=b.asset,amount=b.amount,transaction_hash=tx.hash,chain=b.chain,created_at=now,provenance=["json_rpc",ref]))

    async def _timeline(self,case_id,event_type,message,data):
        key=data.get("branch_id","")+data.get("transaction_hash","")+message
        e=TimelineEvent(id=stable_id("EVT",case_id,event_type,key),case_id=case_id,type=event_type,message=message,created_at=datetime.now(timezone.utc),data=data)
        return await self.repo.append_timeline(e)

def decode_pubsub(body):
    msg=body.get("message") or {}; raw=msg.get("data")
    if not raw: raise ValueError("Pub/Sub message data is missing")
    return json.loads(base64.b64decode(raw).decode())
