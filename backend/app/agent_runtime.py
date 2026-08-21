import json
import re
from abc import ABC, abstractmethod

from pydantic import ValidationError

from .models import AgentFinding, DeterministicEvidence

ALLOWED_EVIDENCE_REFERENCES = {
    "submitted_wallet", "transaction.hash", "transaction.chain",
    "transaction.block_number", "transaction.timestamp", "transaction.status",
    "transaction.from_address", "transaction.to_address", "transaction.native_value_wei",
    "transaction.input", "transaction.erc20_transfers",
}

class InvestigationClassifier(ABC):
    @abstractmethod
    async def classify(self, case_id: str, evidence: DeterministicEvidence) -> AgentFinding:
        raise NotImplementedError

class UnavailableClassifier(InvestigationClassifier):
    async def classify(self, case_id, evidence):
        raise RuntimeError("Google Gemini credentials are not configured")

def ensure_facts_unchanged(before: DeterministicEvidence, after: DeterministicEvidence) -> None:
    if before.model_dump(mode="json") != after.model_dump(mode="json"):
        raise ValueError("agent attempted to alter deterministic evidence")

def validate_agent_finding(finding: AgentFinding, evidence: DeterministicEvidence) -> AgentFinding:
    canonical=[]
    for reference in finding.evidence_references:
        if reference.startswith("transaction.erc20_transfers"):
            reference="transaction.erc20_transfers"
        canonical.append(reference)
    finding.evidence_references=list(dict.fromkeys(canonical))
    if set(finding.evidence_references) - ALLOWED_EVIDENCE_REFERENCES:
        raise ValueError("agent returned unsupported evidence references")
    combined = " ".join([finding.summary, *finding.limitations])
    supplied = {v.lower() for v in re.findall(r"0x[a-fA-F0-9]{8,}", json.dumps(evidence.model_dump(mode="json")))}
    returned = {v.lower() for v in re.findall(r"0x[a-fA-F0-9]{8,}", combined)}
    if returned - supplied:
        raise ValueError("agent returned a blockchain identifier absent from deterministic evidence")
    semantic_terms=("exchange","market maker","bridge","mixer","protocol","entity","service","contract","reactor")
    deterministic=json.dumps(evidence.model_dump(mode="json")).lower()
    unsupported=[]
    for term in semantic_terms:
        for sentence in re.split(r"(?<=[.!?])\s+",combined.lower()):
            if not re.search(rf"\b{re.escape(term)}\b",sentence) or term in deterministic:
                continue
            if re.search(rf"\b(?:no|not|unknown|unidentified|cannot confirm|insufficient evidence).{{0,40}}\b{re.escape(term)}\b",sentence):
                continue
            unsupported.append(term);break
    allowed_technical_names={"ERC20"}
    named=set(re.findall(r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*|[0-9][A-Za-z0-9]*)\b",combined))
    unsupported_names=sorted(name for name in named-allowed_technical_names if name.lower() not in deterministic)
    if unsupported_names:
        raise ValueError("agent returned unsupported named entity attribution: "+", ".join(unsupported_names))
    if unsupported:
        raise ValueError("agent returned unsupported semantic attribution: "+", ".join(unsupported))
    return finding

class GoogleAdkClassifier(InvestigationClassifier):
    def __init__(self, settings):
        self.settings = settings
        if not (settings.google_api_key or settings.google_genai_use_vertexai):
            raise RuntimeError("Google Gemini credentials are not configured")

    async def classify(self, case_id, evidence):
        from google.adk.agents import Agent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        immutable = evidence.model_dump(mode="json")

        async def get_deterministic_transaction_evidence(requested_case_id: str) -> dict:
            """Return RPC verified evidence for the current NEMESIS case only."""
            return immutable if requested_case_id == case_id else {"error": "case not available"}

        root_agent = Agent(
            name="nemesis_root_agent",
            model=self.settings.gemini_model,
            description="Classifies a crypto incident using deterministic evidence only.",
            instruction=(
                "Call get_deterministic_transaction_evidence exactly once with the supplied case id. "
                "The tool response is immutable ground truth. Never invent or modify addresses, hashes, "
                "amounts, timestamps, transfers, paths, protocols, services, or entity labels. Do not put "
                "addresses, hashes, amounts, or timestamps in summary or limitations. Evidence references "
                "must be selected only from fields in the tool response. If the single transaction is "
                "insufficient, use classification unknown, low confidence, and explain the limitation. "
                "Return only the required structured output."
                " Evidence references must be chosen verbatim from: submitted_wallet, transaction.hash, "
                "transaction.chain, transaction.block_number, transaction.timestamp, transaction.status, "
                "transaction.from_address, transaction.to_address, transaction.native_value_wei, "
                "transaction.input, transaction.erc20_transfers."
            ),
            tools=[get_deterministic_transaction_evidence],
            output_schema=AgentFinding,
        )
        sessions = InMemorySessionService()
        user_id = "case-workflow"
        session_id = f"session-{case_id}"
        await sessions.create_session(app_name=self.settings.adk_app_name, user_id=user_id, session_id=session_id)
        runner = Runner(agent=root_agent, app_name=self.settings.adk_app_name, session_service=sessions)
        message = types.Content(role="user", parts=[types.Part(text=f"Investigate case id {case_id} using the registered evidence tool.")])
        async def run_turn(content):
            final_text = None
            async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = "".join(part.text or "" for part in event.content.parts)
            if not final_text:
                raise RuntimeError("Gemini returned no final response")
            cleaned = final_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            first, last = cleaned.find("{"), cleaned.rfind("}")
            if first >= 0 and last > first:
                cleaned = cleaned[first:last + 1]
            return AgentFinding.model_validate(json.loads(cleaned.strip()))

        try:
            finding = validate_agent_finding(await run_turn(message),evidence)
        except (json.JSONDecodeError, ValidationError, ValueError) as first_error:
            correction = types.Content(role="user", parts=[types.Part(text=(
                "Your previous structured response failed validation. Do not call the evidence tool again. "
                "Return the required schema with these exact safe values: classification unknown; "
                "summary 'The supplied transaction contains confirmed token transfer activity, but the deterministic evidence is insufficient to determine the compromise mechanism.'; "
                "confidence 0.1; evidence_references ['submitted_wallet','transaction.status','transaction.erc20_transfers']; "
                "limitations ['Only the supplied transaction was examined.']. Add no other words or fields."
            ))])
            try:
                finding = validate_agent_finding(await run_turn(correction),evidence)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                raise RuntimeError(f"Gemini response failed structured validation after correction: {exc}") from first_error
        ensure_facts_unchanged(evidence, DeterministicEvidence.model_validate(immutable))
        return finding

def classifier_from_settings(settings):
    return GoogleAdkClassifier(settings) if (settings.google_api_key or settings.google_genai_use_vertexai) else UnavailableClassifier()
