"""The anti-hallucination guard must block entity attribution, not vocabulary."""
from datetime import datetime, timezone

import pytest

from app.agent_runtime import validate_agent_finding
from app.models import AgentFinding, DeterministicEvidence, NormalizedTransaction

WALLET = "0x" + "11" * 20
SPENDER = "0x" + "22" * 20


def _evidence():
    return DeterministicEvidence(
        submitted_wallet=WALLET,
        transaction=NormalizedTransaction(
            hash="0x" + "ab" * 32, chain="ethereum", block_number=1,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            from_address=SPENDER, to_address=WALLET, status="success",
            native_value_wei="0", input="0x", erc20_transfers=[], nft_transfers=[],
            native_transfers=[],
        ),
    )


def _finding(summary):
    return AgentFinding(
        classification="unknown", summary=summary, confidence=0.1,
        evidence_references=["submitted_wallet", "transaction.status"],
        limitations=["Only the supplied transaction was examined."],
    )


@pytest.mark.parametrize("summary", [
    "A third-party caller invoked a contract that moved value from the wallet.",
    "The transaction interacted with a protocol contract in a single call.",
])
def test_generic_onchain_vocabulary_is_allowed(summary):
    """Previously this rejected every Gemini finding, leaving cases unclassified."""
    assert validate_agent_finding(_finding(summary), _evidence()) is not None


@pytest.mark.parametrize("summary,term", [
    ("The funds were forwarded to an exchange deposit address.", "exchange"),
    ("The destination is a mixer used to obscure the trail.", "mixer"),
    ("A bridge carried the value to another chain.", "bridge"),
])
def test_entity_attribution_is_still_blocked(summary, term):
    with pytest.raises(ValueError, match="unsupported semantic attribution"):
        validate_agent_finding(_finding(summary), _evidence())


def test_named_entity_attribution_is_still_blocked():
    with pytest.raises(ValueError, match="unsupported named entity attribution"):
        validate_agent_finding(_finding("The funds reached Tornado shortly after."), _evidence())
