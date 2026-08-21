from datetime import datetime,timezone
import uuid
from .models import CaseCreate,CaseResponse,DeterministicEvidence,InvestigationCase
class CaseWorkflow:
    def __init__(self,repository,provider,classifier,taskmaster=None):self.repository,self.provider,self.classifier,self.taskmaster=repository,provider,classifier,taskmaster
    async def create_and_investigate(self,request:CaseCreate)->CaseResponse:
        now=datetime.now(timezone.utc);case=InvestigationCase(id=f"NMS-{now:%y%m%d}-{uuid.uuid4().hex[:8].upper()}",state="INVESTIGATING",created_at=now,updated_at=now,wallet_address=request.wallet_address.lower(),chain=request.chain,theft_transaction_hash=request.theft_transaction_hash.lower());await self.repository.save(case)
        try:
            transaction=await self.provider.get_normalized_transaction(request.chain,request.theft_transaction_hash);evidence=DeterministicEvidence(submitted_wallet=request.wallet_address.lower(),transaction=transaction);case.evidence=evidence;case.updated_at=datetime.now(timezone.utc);await self.repository.save(case)
            if self.taskmaster:await self.taskmaster.trace_initial(case.id,evidence)
            try:
                case.finding=await self.classifier.classify(case.id,evidence);case.state="COMPLETE";runtime="google_adk_gemini"
            except (RuntimeError,ValueError) as exc:
                case.state="FAILED";case.error=str(exc);runtime="unavailable"
            case.updated_at=datetime.now(timezone.utc);await self.repository.save(case)
            return CaseResponse(case=case,factual_source="json_rpc",agent_runtime=runtime)
        except Exception as exc:
            case.state="FAILED";case.error=str(exc);case.updated_at=datetime.now(timezone.utc);await self.repository.save(case);raise
