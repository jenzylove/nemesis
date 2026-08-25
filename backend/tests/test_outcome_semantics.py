"""Terminal reasons carry different meaning and must not be collapsed."""
from app.outcome import build_outcome, derive_case_state


def branch(reason, amount, status="OBSCURED", address="0x" + "11" * 20):
    return {"id": "BR-" + reason[:4] + str(amount), "status": status, "asset": "native",
            "amount": str(amount), "terminal_reason": reason, "current_address": address,
            "chain": "ethereum", "depth": 4}


def test_depth_limited_funds_are_located_not_unresolved():
    """Stopping by choice is not the same as losing the trail."""
    trace = {"branches": [branch("MAX_DEPTH", 100)]}
    outcome = build_outcome([], trace)
    reasons = {r["reason"]: r for r in outcome["terminal_breakdown"]}
    assert "MAX_DEPTH" in reasons
    assert "identifiable" in reasons["MAX_DEPTH"]["meaning"]
    assert any("configured trace depth" in a for a in outcome["next_actions"])


def test_retrieval_failure_is_described_as_a_limit_not_a_finding():
    trace = {"branches": [branch("CONTINUATION_EVIDENCE_UNAVAILABLE", 50)]}
    outcome = build_outcome([], trace)
    reasons = {r["reason"]: r for r in outcome["terminal_breakdown"]}
    assert "could not be retrieved" in reasons["CONTINUATION_EVIDENCE_UNAVAILABLE"]["meaning"]
    assert any("not evidence that those funds stopped moving" in l for l in outcome["limitations"])


def test_current_holdings_answer_where_the_money_is():
    trace = {"branches": [
        branch("MAX_DEPTH", 5, address="0x" + "aa" * 20),
        branch("MAX_DEPTH", 900, address="0x" + "bb" * 20),
    ]}
    outcome = build_outcome([], trace)
    holdings = outcome["current_holdings"]
    assert holdings[0]["amount"] == "900", "largest holding must lead"
    assert holdings[0]["address"] == "0x" + "bb" * 20


def test_outcome_never_claims_recovery_or_contact():
    trace = {"branches": [branch("MAX_DEPTH", 1)]}
    outcome = build_outcome([], trace)
    text = " ".join(outcome["next_actions"] + outcome["limitations"] + [outcome["summary"]]).lower()
    for forbidden in ("froze", "frozen", "recovered your", "we contacted", "kyc obtained"):
        assert forbidden not in text
    assert "cannot freeze funds" in text


def test_case_state_never_reports_complete():
    assert derive_case_state([{"status": "OBSCURED"}], "INVESTIGATING") == "LIMITED"
    assert derive_case_state([{"status": "DORMANT"}], "INVESTIGATING") == "MONITORING"
    assert derive_case_state([{"status": "ACTIONABLE"}], "INVESTIGATING") == "ACTIONABLE"
