from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChainName = Literal["ethereum", "base"]
ChainSelection = Literal["auto", "ethereum", "base"]


class CaseCreate(BaseModel):
    wallet_address: str = Field(
        min_length=42, max_length=42, pattern=r"^0x[a-fA-F0-9]{40}$"
    )
    chain: ChainSelection = "auto"
    theft_transaction_hash: str | None = Field(
        default=None, min_length=66, max_length=66, pattern=r"^0x[a-fA-F0-9]{64}$"
    )
    incident_time: datetime | None = None

    @field_validator("theft_transaction_hash", mode="before")
    @classmethod
    def blank_hash_is_missing(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ERC20Transfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    log_index: int = Field(ge=0)
    token_contract: str
    from_address: str
    to_address: str
    raw_amount: str


class NormalizedTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hash: str
    chain: ChainName
    block_number: int
    timestamp: datetime
    status: Literal["success", "failed"]
    from_address: str
    to_address: str | None
    native_value_wei: str
    input: str
    erc20_transfers: list[ERC20Transfer]


class DeterministicEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submitted_wallet: str
    transaction: NormalizedTransaction


class DiscoveryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_hash: str
    block_number: int = Field(ge=0)
    timestamp: datetime | None = None
    transaction_from: str | None = None
    transaction_to: str | None = None
    counterparty: str | None = None
    outgoing_transfer_count: int = Field(default=1, ge=1)
    amount_usd: float | None = Field(default=None, ge=0)
    score: float
    reasons: list[str] = Field(default_factory=list, max_length=12)
    goplus_flags: list[str] = Field(default_factory=list, max_length=24)
    chainabuse_report_count: int | None = Field(default=None, ge=0)


class IncidentDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["bitquery", "alchemy"]
    selected_transaction_hash: str
    selected_score: float
    candidate_count: int = Field(ge=1)
    incident_time: datetime | None = None
    candidates: list[DiscoveryCandidate] = Field(default_factory=list, max_length=5)


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Literal[
        "malicious_approval",
        "permit_or_signature_theft",
        "malicious_contract",
        "phishing_dapp",
        "suspicious_spender",
        "possible_private_key_compromise",
        "protocol_exploit",
        "unknown",
    ]
    summary: str = Field(max_length=1200)
    confidence: float = Field(ge=0, le=1)
    evidence_references: list[str] = Field(default_factory=list, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("summary")
    @classmethod
    def summary_must_not_embed_onchain_identifiers(cls, value: str) -> str:
        import re

        if re.search(r"0x[a-fA-F0-9]{8,}", value):
            raise ValueError("summary must not contain blockchain identifiers")
        return value


class InvestigationCase(BaseModel):
    id: str
    state: Literal["INVESTIGATING", "COMPLETE", "FAILED"]
    created_at: datetime
    updated_at: datetime
    wallet_address: str
    chain: ChainSelection
    theft_transaction_hash: str | None = None
    discovery: IncidentDiscovery | None = None
    evidence: DeterministicEvidence | None = None
    finding: AgentFinding | None = None
    error: str | None = None


class CaseResponse(BaseModel):
    case: InvestigationCase
    factual_source: Literal["json_rpc"]
    agent_runtime: Literal["google_adk_gemini", "unavailable"]
