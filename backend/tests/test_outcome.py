from app.outcome import build_outcome, derive_case_state


def branch(status, attribution=None):
    return {"id": status, "status": status, "attribution": attribution}


def test_case_state_is_derived_from_real_branch_semantics():
    assert derive_case_state([branch("DORMANT")], "EVIDENCE_READY") == "MONITORING"
    assert derive_case_state([branch("MOVING"), branch("DORMANT")], "MONITORING") == "INVESTIGATING"
    assert derive_case_state([branch("ACTIONABLE"), branch("DORMANT")], "MONITORING") == "ACTIONABLE"
    assert derive_case_state([branch("OBSCURED")], "INVESTIGATING") == "LIMITED"


def test_outcome_is_truthful_and_actionable_without_usd_invention():
    attribution = {"entity_name": "Verified Service", "entity_type": "exchange", "address": "0x1", "chain": "ethereum", "confidence": 0.9, "source": "curated", "evidence_type": "published_address", "actionable": True}
    totals = [{"asset": "0xtoken", "stolen": 10, "located": 10, "unresolved": 4, "unit": "raw"}]
    result = build_outcome(totals, {"branches": [branch("ACTIONABLE", attribution), branch("DORMANT")]})
    assert result["asset_totals"] == totals
    assert result["branch_counts"]["actionable"] == 1
    assert result["branch_counts"]["dormant"] == 1
    assert result["identified_services"][0]["entity_name"] == "Verified Service"
    assert any("Contact" in action for action in result["next_actions"])
    assert "$" not in result["summary"]