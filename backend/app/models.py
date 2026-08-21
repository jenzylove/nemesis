from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
ChainName=Literal["ethereum","base"]
class CaseCreate(BaseModel):
    wallet_address:str=Field(min_length=42,max_length=42,pattern=r"^0x[a-fA-F0-9]{40}$")
    chain:ChainName
    theft_transaction_hash:str=Field(min_length=66,max_length=66,pattern=r"^0x[a-fA-F0-9]{64}$")
class ERC20Transfer(BaseModel):
    model_config=ConfigDict(extra="forbid")
    log_index:int=Field(ge=0);token_contract:str;from_address:str;to_address:str;raw_amount:str
class NormalizedTransaction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    hash:str;chain:ChainName;block_number:int;timestamp:datetime;status:Literal["success","failed"];from_address:str;to_address:str|None;native_value_wei:str;input:str;erc20_transfers:list[ERC20Transfer]
class DeterministicEvidence(BaseModel):
    model_config=ConfigDict(extra="forbid")
    submitted_wallet:str;transaction:NormalizedTransaction
class AgentFinding(BaseModel):
    model_config=ConfigDict(extra="forbid")
    classification:Literal["malicious_approval","permit_or_signature_theft","malicious_contract","phishing_dapp","suspicious_spender","possible_private_key_compromise","protocol_exploit","unknown"]
    summary:str=Field(max_length=1200);confidence:float=Field(ge=0,le=1);evidence_references:list[str]=Field(default_factory=list,max_length=12);limitations:list[str]=Field(default_factory=list,max_length=12)
    @field_validator("summary")
    @classmethod
    def summary_must_not_embed_onchain_identifiers(cls,value:str)->str:
        import re
        if re.search(r"0x[a-fA-F0-9]{8,}",value):
            raise ValueError("summary must not contain blockchain identifiers")
        return value
class InvestigationCase(BaseModel):
    id:str;state:Literal["INVESTIGATING","COMPLETE","FAILED"];created_at:datetime;updated_at:datetime;wallet_address:str;chain:ChainName;theft_transaction_hash:str;evidence:DeterministicEvidence|None=None;finding:AgentFinding|None=None;error:str|None=None
class CaseResponse(BaseModel):
    case:InvestigationCase;factual_source:Literal["json_rpc"];agent_runtime:Literal["google_adk_gemini","unavailable"]
