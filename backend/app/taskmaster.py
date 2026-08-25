import asyncio,base64,hashlib,json
from copy import deepcopy
from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,Field
from .attribution import CuratedAttributionProvider,EntityAttribution
from .models import ChainName,DeterministicEvidence,NormalizedTransaction
BranchStatus=Literal["MOVING","DORMANT","OBSCURED","ACTIONABLE"]

class TraceBranch(BaseModel):
    id:str;case_id:str;current_address:str;chain:ChainName;asset:str;amount:str;status:BranchStatus;last_transaction:str
    cursor_block:int=Field(ge=0);last_checked:datetime;evidence_provenance:list[str]=Field(default_factory=list)
    parent_branch_id:str|None=None;depth:int=Field(default=1,ge=1);terminal_reason:str|None=None;attribution:EntityAttribution|None=None
class GraphNode(BaseModel):
    id:str;case_id:str;branch_id:str|None=None;kind:Literal["address","transaction","swap","bridge","entity"];label:str;chain:ChainName
    address:str|None=None;transaction_hash:str|None=None;created_at:datetime;provenance:list[str]=Field(default_factory=list);data:dict=Field(default_factory=dict)
class GraphEdge(BaseModel):
    id:str;case_id:str;branch_id:str;source:str;target:str;asset:str;amount:str;transaction_hash:str;chain:ChainName;created_at:datetime
    provenance:list[str]=Field(default_factory=list);kind:Literal["transfer","split","swap","bridge"]="transfer";destination_chain:ChainName|None=None;data:dict=Field(default_factory=dict)
class TimelineEvent(BaseModel):
    id:str;case_id:str;type:str;message:str;created_at:datetime;data:dict=Field(default_factory=dict)
def stable_id(prefix,*parts):return prefix+"-"+hashlib.sha256(":".join(str(x).lower() for x in parts).encode()).hexdigest()[:20].upper()

class MonitoringRepository:
    async def save_branch(self,b):raise NotImplementedError
    async def get_branch(self,i):raise NotImplementedError
    async def list_branches(self,case_id=None,status=None):raise NotImplementedError
    async def claim_event(self,i):raise NotImplementedError
    async def complete_event(self,i):raise NotImplementedError
    async def release_event(self,i):raise NotImplementedError
    async def append_timeline(self,e):raise NotImplementedError
    async def get_timeline(self,c):raise NotImplementedError
    async def save_node(self,n):raise NotImplementedError
    async def save_edge(self,e):raise NotImplementedError
    async def get_graph(self,c):raise NotImplementedError
class InMemoryMonitoringRepository(MonitoringRepository):
    def __init__(self):self.branches={};self.claims=set();self.timeline={};self.nodes={};self.edges={}
    async def save_branch(self,b):self.branches[b.id]=deepcopy(b);return b
    async def get_branch(self,i):return deepcopy(self.branches.get(i))
    async def list_branches(self,case_id=None,status=None):return [deepcopy(x) for x in self.branches.values() if (not case_id or x.case_id==case_id) and (not status or x.status==status)]
    async def claim_event(self,i):
        if i in self.claims:return False
        self.claims.add(i);return True
    async def complete_event(self,i):return None
    async def release_event(self,i):self.claims.discard(i)
    async def append_timeline(self,e):self.timeline[e.id]=deepcopy(e);return e
    async def get_timeline(self,c):return sorted([deepcopy(x) for x in self.timeline.values() if x.case_id==c],key=lambda x:x.created_at)
    async def save_node(self,n):self.nodes[n.id]=deepcopy(n);return n
    async def save_edge(self,e):self.edges[e.id]=deepcopy(e);return e
    async def get_graph(self,c):return {"nodes":[deepcopy(x) for x in self.nodes.values() if x.case_id==c],"edges":[deepcopy(x) for x in self.edges.values() if x.case_id==c]}
class FirestoreMonitoringRepository(MonitoringRepository):
    def __init__(self,client):self.client=client
    async def save_branch(self,b):await self.client.collection("trace_branches").document(b.id).set(b.model_dump(mode="python"));return b
    async def get_branch(self,i):
        s=await self.client.collection("trace_branches").document(i).get();return TraceBranch.model_validate(s.to_dict()) if s.exists else None
    async def list_branches(self,case_id=None,status=None):
        q=self.client.collection("trace_branches")
        if case_id:q=q.where("case_id","==",case_id)
        if status:q=q.where("status","==",status)
        return [TraceBranch.model_validate(d.to_dict()) async for d in q.stream()]
    async def claim_event(self,i):
        from google.api_core.exceptions import AlreadyExists
        try:await self.client.collection("processed_events").document(i).create({"processed_at":datetime.now(timezone.utc)});return True
        except AlreadyExists:return False
    async def complete_event(self,i):await self.client.collection("processed_events").document(i).set({"status":"COMPLETED","processed_at":datetime.now(timezone.utc)})
    async def release_event(self,i):await self.client.collection("processed_events").document(i).delete()
    async def append_timeline(self,e):await self.client.collection("case_timeline").document(e.id).set(e.model_dump(mode="python"));return e
    async def get_timeline(self,c):
        docs=self.client.collection("case_timeline").where("case_id","==",c).stream();items=[TimelineEvent.model_validate(d.to_dict()) async for d in docs];return sorted(items,key=lambda x:x.created_at)
    async def save_node(self,n):await self.client.collection("case_graph_nodes").document(n.id).set(n.model_dump(mode="python"));return n
    async def save_edge(self,e):await self.client.collection("case_graph_edges").document(e.id).set(e.model_dump(mode="python"));return e
    async def get_graph(self,c):
        ns=self.client.collection("case_graph_nodes").where("case_id","==",c).stream();es=self.client.collection("case_graph_edges").where("case_id","==",c).stream()
        return {"nodes":[GraphNode.model_validate(d.to_dict()) async for d in ns],"edges":[GraphEdge.model_validate(d.to_dict()) async for d in es]}
class EventPublisher:
    async def publish(self,e):raise NotImplementedError
class GooglePubSubPublisher(EventPublisher):
    def __init__(self,project,topic):self.project,self.topic,self.client=project,topic,None
    async def publish(self,e):
        from google.cloud import pubsub_v1
        if self.client is None:self.client=pubsub_v1.PublisherClient()
        return self.client.publish(self.client.topic_path(self.project,self.topic),json.dumps(e).encode()).result(timeout=20)

class Taskmaster:
    def __init__(self,repo,provider,publisher,max_blocks=20,max_depth=8,attribution_provider=None,max_candidates_per_hop=8):
        self.repo,self.provider,self.publisher,self.max_blocks,self.max_depth=repo,provider,publisher,max_blocks,max_depth;self.max_candidates_per_hop=max(1,max_candidates_per_hop);self.attribution_provider=attribution_provider or CuratedAttributionProvider();self.monitoring_gate=asyncio.Semaphore(2)
    async def trace_initial(self,case_id,evidence:DeterministicEvidence):
        tx=evidence.transaction;wallet=evidence.submitted_wallet.lower();await self._timeline(case_id,"TRACING_FUNDS","Tracing funds",{"transaction_hash":tx.hash});branches=[];now=datetime.now(timezone.utc)
        for i,p in enumerate(self._paths(tx,wallet,None,None)):
            b=TraceBranch(id=stable_id("BR",case_id,tx.hash,i,p["asset"],p["destination"]),case_id=case_id,current_address=p["destination"],chain=tx.chain,asset=p["asset"],amount=p["amount"],status="MOVING",last_transaction=tx.hash,cursor_block=tx.block_number,last_checked=now,evidence_provenance=list(dict.fromkeys(["json_rpc",p["ref"],tx.hash,*p.get("provenance",[])])))
            await self.repo.save_branch(b);await self._transfer_graph(b,wallet,p["destination"],tx,p["ref"],"transfer");await self._timeline(case_id,"BRANCH_CREATED","Branch created",{"branch_id":b.id,"address":b.current_address,"asset":b.asset,"amount":b.amount,"depth":b.depth});branches.append(b)
        await self._drain(branches);return [await self.repo.get_branch(b.id) for b in branches]
    async def schedule(self):
        bs=await self.repo.list_branches(status="DORMANT")
        for b in bs:await self.publisher.publish({"id":stable_id("EV","recheck",b.id,b.cursor_block),"type":"RECHECK_REQUESTED","branch_id":b.id})
        return len(bs)
    async def consume(self,e):
        if not await self.repo.claim_event(e["id"]):return {"duplicate":True}
        try:
            async with self.monitoring_gate:
                if e["type"]=="RECHECK_REQUESTED":result=await self.recheck(e["branch_id"])
                elif e["type"]=="TRACE_REQUESTED":result=await self.resume(e["branch_id"],e["transaction_hash"])
                else:raise ValueError("unsupported event type")
        except Exception:
            await self.repo.release_event(e["id"])
            raise
        await self.repo.complete_event(e["id"])
        return result
    async def recheck(self,bid):
        b=await self.repo.get_branch(bid)
        if not b or b.status!="DORMANT":return {"ignored":True}
        cursor,moves=await self.provider.get_address_movements(b.chain,b.current_address,b.cursor_block,self.max_blocks,asset=b.asset);b.cursor_block=cursor;b.last_checked=datetime.now(timezone.utc);out=[m for m in moves if m.get("direction")=="out"]
        if not out:await self.repo.save_branch(b);return {"movement":False}
        m=out[0];b.status="MOVING";b.terminal_reason=None;b.last_transaction=m["transaction_hash"];await self.repo.save_branch(b);await self._timeline(b.case_id,"MOVEMENT_DETECTED","Movement detected",{"branch_id":b.id,**m});await self.publisher.publish({"id":stable_id("EV","trace",b.id,m["transaction_hash"]),"type":"TRACE_REQUESTED","branch_id":b.id,"transaction_hash":m["transaction_hash"]});return {"movement":True,"transaction_hash":m["transaction_hash"]}
    async def resume(self,bid,tx_hash):
        b=await self.repo.get_branch(bid)
        if not b or b.status!="MOVING":return {"ignored":True}
        await self._timeline(b.case_id,"TRACING_RESUMED","Tracing resumed",{"branch_id":b.id,"transaction_hash":tx_hash});r=await self._process(b,tx_hash);await self._drain(r["branches"]);return {"resumed":True,"extended":r["extended"],"branches":r["path_count"],"terminal":not r["extended"]}
    async def case_trace(self,c):
        g=await self.repo.get_graph(c);return {"branches":[b.model_dump(mode="json") for b in await self.repo.list_branches(case_id=c)],"graph":{"nodes":[n.model_dump(mode="json") for n in g["nodes"]],"edges":[e.model_dump(mode="json") for e in g["edges"]]},"timeline":[e.model_dump(mode="json") for e in await self.repo.get_timeline(c)]}
    async def _drain(self,branches):
        q=[b for b in branches if b]
        while q:
            b=await self.repo.get_branch(q.pop(0).id)
            if not b or b.status!="MOVING":continue
            a=await self._attribute(b)
            if a and a.actionable:await self._actionable(b,a);continue
            if b.depth>=self.max_depth:
                b.status="OBSCURED";b.terminal_reason="MAX_DEPTH";await self.repo.save_branch(b);await self._timeline(b.case_id,"MAX_DEPTH_REACHED","Configured trace depth reached",{"branch_id":b.id,"depth":b.depth,"max_depth":self.max_depth});continue
            try:
                cursor,moves=await self.provider.get_address_movements(b.chain,b.current_address,b.cursor_block,self.max_blocks,asset=b.asset)
            except Exception:
                # The chain could not be reached. That is not evidence the funds
                # stopped moving, so the branch is not reported dormant, and the
                # rest of the case still completes on its own evidence.
                await self._unavailable(b);continue
            b.cursor_block=cursor;b.last_checked=datetime.now(timezone.utc);out=[m for m in moves if m.get("direction")=="out"]
            if not out:await self._dormant(b);continue
            q.extend(await self._follow(b,out))
    def _prioritise(self,b,out,hashes):
        """Order candidates so those able to carry the tracked asset come first.

        A drained address emits a lot of traffic that cannot possibly move the
        asset being followed, including address-poisoning spam that mimics real
        token symbols. Walking candidates in pure block order let that noise
        consume the per-hop budget before the real transfer was ever examined,
        and the branch was then recorded as dormant while the funds had moved.

        Ordering is a preference, not a filter: a candidate whose category is
        unknown is still examined, and every candidate is still verified against
        deterministic evidence before it can extend the branch.
        """
        native=b.asset=="native"
        wanted={"external","internal"} if native else {"erc20","erc721","erc1155"}
        categories={}
        for m in out:
            h=m.get("transaction_hash")
            if h:categories.setdefault(h,set()).update(m.get("categories") or [])
        def rank(h):
            known=categories.get(h) or set()
            if not known:return 1          # unclassified, still worth examining
            return 0 if known & wanted else 2
        return sorted(hashes,key=lambda h:(rank(h),hashes.index(h)))
    async def _follow(self,b,out):
        """Advance the branch on the first outgoing transaction that moves it.

        An address commonly emits several outgoing transactions, and only some
        of them touch the asset this branch is tracking. Reading just the first
        one made a branch look dormant whenever an unrelated transfer happened
        to come first. Candidates are therefore tried in order until one
        actually accounts for tracked value.

        Advancing is only permitted when the previous candidate consumed
        nothing, so the same funds can never be followed down two paths. That
        is the double-counting failure an earlier parallel-path attempt
        introduced, and it stays impossible here by construction.
        """
        seen=[h for h in dict.fromkeys(m.get("transaction_hash") for m in out) if h]
        seen=self._prioritise(b,out,seen)[:self.max_candidates_per_hop]
        for index,tx_hash in enumerate(seen):
            b.last_transaction=tx_hash
            await self.repo.save_branch(b)
            await self._timeline(b.case_id,"MOVEMENT_DETECTED","Movement detected",{"branch_id":b.id,**next((x for x in out if x.get("transaction_hash")==tx_hash),{"transaction_hash":tx_hash})})
            last=index==len(seen)-1
            r=await self._process(b,tx_hash,terminal=last)
            if r["extended"] or int(r.get("consumed") or 0)>0:
                return r["branches"]
            if r.get("halted"):
                return r["branches"]
        return []
    async def _process(self,b,tx_hash,terminal=True):
        tx=await self.provider.get_normalized_transaction(b.chain,tx_hash);source=b.current_address.lower();b.cursor_block=max(b.cursor_block,tx.block_number);b.last_transaction=tx.hash;b.last_checked=datetime.now(timezone.utc)
        bridge=await self.provider.get_bridge_evidence(b.chain,tx,source,b.asset,b.amount)
        if bridge:return await self._bridge(b,tx,bridge)
        swap=self._swap(tx,b)
        if swap:return await self._handle_swap(b,tx,swap)
        ps=self._paths(tx,source,b.asset,b.amount)
        if not ps and b.asset=="native":
            # A receipt cannot encode a contract-forwarded internal transfer, so
            # an absent path here is ambiguous: the funds may have moved in a way
            # RPC does not expose. Consult the index before concluding anything.
            try:
                indexed=await self.provider.get_indexed_native_transfers(b.chain,tx,source)
            except Exception:
                # Retrieval failed. This is not evidence that funds stopped moving.
                b.status="OBSCURED";b.terminal_reason="CONTINUATION_EVIDENCE_UNAVAILABLE";b.last_checked=datetime.now(timezone.utc)
                await self.repo.save_branch(b)
                await self._timeline(b.case_id,"CONTINUATION_EVIDENCE_UNAVAILABLE","Continuation evidence could not be retrieved",{"branch_id":b.id,"address":source,"transaction_hash":tx.hash})
                return {"extended":False,"path_count":0,"branches":[],"consumed":0,"halted":True}
            fresh=[t for t in indexed if not any(
                e.from_address==t.from_address and e.to_address==t.to_address and e.raw_amount==t.raw_amount
                for e in tx.native_transfers)]
            if fresh:
                tx.native_transfers.extend(fresh)
                await self._timeline(b.case_id,"INDEXED_CONTINUATION_RESOLVED","Indexed evidence revealed native movement the receipt does not encode",{"branch_id":b.id,"transaction_hash":tx.hash,"transfer_count":len(fresh),"evidence_provenance":sorted({p for t in fresh for p in t.provenance})})
                ps=self._paths(tx,source,b.asset,b.amount)
        if not ps:
            if terminal:await self._dormant(b,"NO_DETERMINISTIC_OUTGOING_PATH")
            return {"extended":False,"path_count":0,"branches":[],"consumed":0}
        targets=await self._apply(b,tx,ps);return {"extended":True,"path_count":len(targets),"branches":targets,"consumed":sum(int(p["amount"]) for p in ps)}
    def _paths(self,tx,source,asset,amount):
        source=source.lower();c=[]
        if asset in (None,"native") and tx.from_address==source and tx.to_address and int(tx.native_value_wei)>0:c.append({"destination":tx.to_address.lower(),"asset":"native","amount":tx.native_value_wei,"ref":"transaction.native_value_wei","order":-1})
        if asset in (None,"native"):
            for i,t in enumerate(tx.native_transfers):
                if t.from_address==source:c.append({"destination":t.to_address.lower(),"asset":"native","amount":t.raw_amount,"ref":f"transaction.native_transfers[{i}]","order":i,"provenance":list(t.provenance)})
        for i,t in enumerate(tx.erc20_transfers):
            if t.from_address==source and (asset is None or asset==t.token_contract):c.append({"destination":t.to_address,"asset":t.token_contract,"amount":t.raw_amount,"ref":f"transaction.erc20_transfers[{i}]","order":t.log_index})
        c.sort(key=lambda x:x["order"])
        if amount is None:return c
        left=int(amount);out=[]
        for p in c:
            if left<=0:break
            n=min(int(p["amount"]),left)
            if n>0:out.append({**p,"amount":str(n)});left-=n
        return out
    def _swap(self,tx,b):
        wallet=b.current_address.lower();total=int(b.amount);spent=0;refs=[]
        if b.asset=="native":
            if tx.from_address==wallet and int(tx.native_value_wei)>0:spent=min(int(tx.native_value_wei),total);refs=["transaction.native_value_wei"]
        else:
            for i,t in enumerate(tx.erc20_transfers):
                if t.from_address!=wallet or t.token_contract!=b.asset:continue
                n=min(int(t.raw_amount),max(0,total-spent));spent+=n
                if n:refs.append(f"transaction.erc20_transfers[{i}]")
        if not spent or not tx.to_address:return None
        outs=[{"asset":t.token_contract,"amount":t.raw_amount,"ref":f"transaction.erc20_transfers[{i}]","order":t.log_index} for i,t in enumerate(tx.erc20_transfers) if t.to_address==wallet and t.token_contract!=b.asset]
        return {"outputs":sorted(outs,key=lambda x:x["order"]),"spent_amount":str(spent),"remaining_amount":str(max(0,total-spent)),"spent_refs":refs} if outs else None
    async def _apply(self,b,tx,ps):
        source=b.current_address;parent=b.id;depth=b.depth+1;moved=sum(int(p["amount"]) for p in ps);res=max(0,int(b.amount)-moved);keep=res>0;split=len(ps)>1 or keep
        if split:await self._timeline(b.case_id,"FUND_SPLIT_DETECTED","Fund split detected",{"branch_id":parent,"transaction_hash":tx.hash,"path_count":len(ps)+(1 if keep else 0),"asset":b.asset,"residual_amount":str(res) if keep else "0"})
        out=[]
        for i,p in enumerate(ps):
            t=b if i==0 else b.model_copy(deep=True,update={"id":stable_id("BR",b.case_id,tx.hash,i,p["asset"],p["destination"]),"parent_branch_id":parent})
            t.current_address,t.asset,t.amount=p["destination"],p["asset"],p["amount"];t.last_transaction=tx.hash;t.cursor_block=tx.block_number;t.last_checked=datetime.now(timezone.utc);t.status="MOVING";t.depth=depth;t.terminal_reason=None;t.attribution=None;t.evidence_provenance=list(dict.fromkeys(["json_rpc",p["ref"],tx.hash,*p.get("provenance",[])]));await self.repo.save_branch(t);await self._transfer_graph(t,source,p["destination"],tx,p["ref"],"split" if split else "transfer")
            if i:await self._timeline(b.case_id,"BRANCH_CREATED","Branch created",{"branch_id":t.id,"parent_branch_id":parent,"address":t.current_address,"asset":t.asset,"amount":t.amount,"depth":t.depth})
            out.append(t)
        if keep:
            r=b.model_copy(deep=True,update={"id":stable_id("BR",b.case_id,tx.hash,"residual",b.asset,source),"parent_branch_id":parent});r.current_address=source;r.asset=b.asset;r.amount=str(res);r.last_transaction=tx.hash;r.cursor_block=tx.block_number;r.last_checked=datetime.now(timezone.utc);r.status="MOVING";r.depth=depth;r.terminal_reason=None;r.attribution=None;r.evidence_provenance=["json_rpc",tx.hash,"tracked_asset_residual"];await self.repo.save_branch(r);await self._timeline(b.case_id,"BRANCH_CREATED","Branch created",{"branch_id":r.id,"parent_branch_id":parent,"address":source,"asset":r.asset,"amount":r.amount,"depth":r.depth,"residual":True});out.append(r)
        return out
    async def _handle_swap(self,b,tx,s):
        source=b.current_address;parent=b.id;depth=b.depth+1;before_asset=b.asset;before_amount=b.amount;outs=s["outputs"];spent=s["spent_amount"];remain=s["remaining_amount"];prov=["json_rpc",tx.hash,*s["spent_refs"],"erc20_transfer_logs"]
        await self._timeline(b.case_id,"SWAP_DETECTED","Swap detected from deterministic asset movements",{"branch_id":parent,"transaction_hash":tx.hash,"wallet":source,"asset_before":before_asset,"amount_before":before_amount,"tracked_amount_spent":spent,"tracked_amount_remaining":remain,"assets_after":[{"asset":x["asset"],"amount":x["amount"]} for x in outs],"evidence_provenance":prov})
        now=datetime.now(timezone.utc);swap_node=stable_id("NODE",b.case_id,"swap",tx.hash,parent);wallet_node=stable_id("NODE",b.case_id,b.chain,source);await self.repo.save_node(GraphNode(id=swap_node,case_id=b.case_id,branch_id=parent,kind="swap",label="Swap",chain=b.chain,transaction_hash=tx.hash,created_at=now,provenance=prov,data={"asset_before":before_asset,"amount_before":before_amount,"tracked_amount_spent":spent,"tracked_amount_remaining":remain}));await self.repo.save_node(GraphNode(id=wallet_node,case_id=b.case_id,branch_id=parent,kind="address",label="Wallet",chain=b.chain,address=source,created_at=now,provenance=["json_rpc",tx.hash]));await self.repo.save_edge(GraphEdge(id=stable_id("EDGE",parent,tx.hash,"swap-input",before_asset),case_id=b.case_id,branch_id=parent,source=wallet_node,target=swap_node,asset=before_asset,amount=spent,transaction_hash=tx.hash,chain=b.chain,created_at=now,provenance=["json_rpc",*s["spent_refs"],"swap_pattern"],kind="swap",data={"role":"asset_before"}))
        targets=[]
        for i,o in enumerate(outs):
            t=b if i==0 else b.model_copy(deep=True,update={"id":stable_id("BR",b.case_id,tx.hash,"swap",i,o["asset"]),"parent_branch_id":parent});t.asset=o["asset"];t.amount=o["amount"];t.current_address=source;t.last_transaction=tx.hash;t.cursor_block=tx.block_number;t.last_checked=now;t.status="MOVING";t.depth=depth;t.terminal_reason=None;t.attribution=None;t.evidence_provenance=["json_rpc",o["ref"],tx.hash,"swap_pattern"];await self.repo.save_branch(t);await self.repo.save_edge(GraphEdge(id=stable_id("EDGE",t.id,tx.hash,"swap",o["asset"],i),case_id=t.case_id,branch_id=t.id,source=swap_node,target=wallet_node,asset=o["asset"],amount=o["amount"],transaction_hash=tx.hash,chain=t.chain,created_at=now,provenance=["json_rpc",o["ref"],"swap_pattern"],kind="swap",data={"asset_before":before_asset,"tracked_amount_spent":spent}));targets.append(t)
        if int(remain)>0:
            r=b.model_copy(deep=True,update={"id":stable_id("BR",b.case_id,tx.hash,"swap-residual",before_asset),"parent_branch_id":parent});r.asset=before_asset;r.amount=remain;r.current_address=source;r.last_transaction=tx.hash;r.cursor_block=tx.block_number;r.last_checked=now;r.status="MOVING";r.depth=depth;r.terminal_reason=None;r.attribution=None;r.evidence_provenance=["json_rpc",tx.hash,*s["spent_refs"],"tracked_swap_residual"];await self.repo.save_branch(r);await self._timeline(b.case_id,"FUND_SPLIT_DETECTED","Tracked funds split between swapped and residual assets",{"branch_id":parent,"transaction_hash":tx.hash,"asset":before_asset,"swapped_amount":spent,"residual_amount":remain,"residual_branch_id":r.id});targets.append(r)
        return {"extended":True,"path_count":len(targets),"branches":targets}
    async def _bridge(self,b,tx,e):
        source=b.current_address.lower();b.amount=str(e["amount"]);now=datetime.now(timezone.utc);prov=list(e.get("provenance") or ["json_rpc",tx.hash]);await self._timeline(b.case_id,"BRIDGE_DETECTED","Bridge transfer detected",{"branch_id":b.id,**e});src=stable_id("NODE",b.case_id,b.chain,source);bridge=stable_id("NODE",b.case_id,"bridge",tx.hash,e["bridge_contract"]);txn=stable_id("NODE",b.case_id,"tx",b.chain,tx.hash);await self.repo.save_node(GraphNode(id=src,case_id=b.case_id,branch_id=b.id,kind="address",label="Wallet",chain=b.chain,address=source,created_at=now,provenance=["json_rpc",tx.hash]));await self.repo.save_node(GraphNode(id=txn,case_id=b.case_id,branch_id=b.id,kind="transaction",label="Transaction",chain=b.chain,transaction_hash=tx.hash,created_at=now,provenance=["json_rpc",tx.hash]));await self.repo.save_node(GraphNode(id=bridge,case_id=b.case_id,branch_id=b.id,kind="bridge",label=e["bridge_name"],chain=b.chain,address=e["bridge_contract"],transaction_hash=tx.hash,created_at=now,provenance=prov,data={k:v for k,v in e.items() if k!="provenance"}));await self.repo.save_edge(GraphEdge(id=stable_id("EDGE",b.id,tx.hash,"bridge-source",e["bridge_contract"]),case_id=b.case_id,branch_id=b.id,source=src,target=bridge,asset=e["asset"],amount=b.amount,transaction_hash=tx.hash,chain=b.chain,created_at=now,provenance=prov,kind="bridge",data={"transaction_node_id":txn,"role":"source_bridge_transfer"}))
        r=await self.provider.resolve_bridge_destination(e)
        if not r:
            b.current_address=e["bridge_contract"];b.last_transaction=tx.hash;b.cursor_block=tx.block_number;b.last_checked=now;b.status="OBSCURED";b.terminal_reason="BRIDGE_DESTINATION_UNRESOLVED";b.depth+=1;b.evidence_provenance=prov;await self.repo.save_branch(b);return {"extended":False,"path_count":0,"branches":[],"consumed":int(b.amount),"halted":True}
        req={"destination_chain","destination_address","destination_transaction_hash","destination_block_number"}
        if not req<=r.keys() or not r["destination_transaction_hash"]:
            b.status="OBSCURED";b.terminal_reason="BRIDGE_DESTINATION_EVIDENCE_INCOMPLETE";await self.repo.save_branch(b);return {"extended":False,"path_count":0,"branches":[],"consumed":int(b.amount),"halted":True}
        if r["destination_chain"]!=e["destination_chain"]:raise ValueError("bridge destination resolution contradicts deterministic bridge evidence")
        old=b.chain;dest_chain=r["destination_chain"];dest=r["destination_address"].lower();dst=stable_id("NODE",b.case_id,dest_chain,dest);rprov=list(r.get("provenance") or []);await self.repo.save_node(GraphNode(id=dst,case_id=b.case_id,branch_id=b.id,kind="address",label="Wallet",chain=dest_chain,address=dest,created_at=now,provenance=rprov));await self.repo.save_edge(GraphEdge(id=stable_id("EDGE",b.id,tx.hash,"bridge-destination",dest_chain,dest),case_id=b.case_id,branch_id=b.id,source=bridge,target=dst,asset=r.get("destination_asset") or b.asset,amount=str(r.get("destination_amount") or b.amount),transaction_hash=tx.hash,chain=old,destination_chain=dest_chain,created_at=now,provenance=prov+rprov,kind="bridge",data={"destination_transaction_hash":r["destination_transaction_hash"],"role":"cross_chain_continuation"}));b.chain=dest_chain;b.current_address=dest;b.asset=r.get("destination_asset") or b.asset;b.amount=str(r.get("destination_amount") or b.amount);b.last_transaction=r["destination_transaction_hash"].lower();b.cursor_block=int(r["destination_block_number"]);b.last_checked=now;b.status="MOVING";b.depth+=1;b.terminal_reason=None;b.attribution=None;b.evidence_provenance=rprov;await self.repo.save_branch(b);await self._timeline(b.case_id,"CROSS_CHAIN_TRACE_CONTINUED","Cross chain trace continued",{"branch_id":b.id,"source_chain":old,"destination_chain":dest_chain,"destination_address":dest,"destination_transaction_hash":b.last_transaction,"evidence_provenance":rprov});return {"extended":True,"path_count":1,"branches":[b]}
    async def _attribute(self,b):
        a=await self.attribution_provider.lookup(b.chain,b.current_address)
        if not a:return None
        if a.address.lower()!=b.current_address.lower() or a.chain!=b.chain:raise ValueError("attribution source returned mismatched deterministic identity")
        b.attribution=a;await self.repo.save_branch(b);await self._timeline(b.case_id,"ENTITY_ATTRIBUTION_DETECTED","Deterministic entity attribution detected",{"branch_id":b.id,**a.model_dump(mode="json")});node=stable_id("NODE",b.case_id,a.chain,a.address);await self.repo.save_node(GraphNode(id=node,case_id=b.case_id,branch_id=b.id,kind="entity",label=a.entity_name,chain=a.chain,address=a.address,created_at=datetime.now(timezone.utc),provenance=[a.source,a.evidence_type],data=a.model_dump(mode="json")));return a
    async def _actionable(self,b,a):
        b.status="ACTIONABLE";b.terminal_reason="DETERMINISTIC_ACTIONABLE_ENTITY";b.attribution=a;await self.repo.save_branch(b);await self._timeline(b.case_id,"ACTIONABLE_DESTINATION_DETECTED","Actionable destination detected",{"branch_id":b.id,"address":b.current_address,"chain":b.chain,"entity_name":a.entity_name,"entity_type":a.entity_type,"source":a.source,"confidence":a.confidence,"evidence_type":a.evidence_type})
    async def _unavailable(self,b):
        """Record that evidence retrieval failed, which is not a finding."""
        b.status="OBSCURED";b.terminal_reason="CONTINUATION_EVIDENCE_UNAVAILABLE";b.last_checked=datetime.now(timezone.utc)
        await self.repo.save_branch(b)
        await self._timeline(b.case_id,"CONTINUATION_EVIDENCE_UNAVAILABLE","Continuation evidence could not be retrieved",{"branch_id":b.id,"address":b.current_address})
    async def _dormant(self,b,reason="NO_OUTGOING_MOVEMENT_IN_SCAN_WINDOW"):
        b.status="DORMANT";b.terminal_reason=reason;b.last_checked=datetime.now(timezone.utc);await self.repo.save_branch(b);await self._timeline(b.case_id,"BRANCH_DORMANT","Dormant wallet detected",{"branch_id":b.id,"address":b.current_address,"reason":reason});await self._timeline(b.case_id,"MONITORING_ACTIVE","Monitoring active",{"branch_id":b.id})
    async def _transfer_graph(self,b,source,dest,tx,ref,kind):
        now=datetime.now(timezone.utc);src=stable_id("NODE",b.case_id,b.chain,source);dst=stable_id("NODE",b.case_id,b.chain,dest);txn=stable_id("NODE",b.case_id,"tx",b.chain,tx.hash);await self.repo.save_node(GraphNode(id=src,case_id=b.case_id,branch_id=b.id,kind="address",label="Wallet",chain=b.chain,address=source,created_at=now,provenance=["json_rpc",tx.hash]));await self.repo.save_node(GraphNode(id=dst,case_id=b.case_id,branch_id=b.id,kind="address",label="Wallet",chain=b.chain,address=dest,created_at=now,provenance=["json_rpc",tx.hash]));await self.repo.save_node(GraphNode(id=txn,case_id=b.case_id,branch_id=b.id,kind="transaction",label="Transaction",chain=b.chain,transaction_hash=tx.hash,created_at=now,provenance=["json_rpc",tx.hash]));await self.repo.save_edge(GraphEdge(id=stable_id("EDGE",b.id,tx.hash,source,dest,b.asset),case_id=b.case_id,branch_id=b.id,source=src,target=dst,asset=b.asset,amount=b.amount,transaction_hash=tx.hash,chain=b.chain,created_at=now,provenance=["json_rpc",ref,tx.hash],kind=kind,data={"transaction_node_id":txn}))
    async def _timeline(self,c,t,m,data):
        e=TimelineEvent(id=stable_id("EVT",c,t,json.dumps(data,sort_keys=True,default=str)),case_id=c,type=t,message=m,created_at=datetime.now(timezone.utc),data=data);return await self.repo.append_timeline(e)

def decode_pubsub(body):
    raw=(body.get("message") or {}).get("data")
    if not raw:raise ValueError("Pub/Sub message data is missing")
    return json.loads(base64.b64decode(raw).decode())
