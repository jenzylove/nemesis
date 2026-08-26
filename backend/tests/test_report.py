"""The readable report must restate the package and never exceed it."""
from app.report import render

PACKAGE = {
    "generated_at": "2026-08-26T21:45:19+00:00",
    "case_metadata": {"id": "NMS-1", "state": "ACTIONABLE", "chain": "ethereum",
                      "created_at": "2026-08-26T21:03:30+00:00"},
    "deterministic_facts": {
        "submitted_wallet": "0x" + "1a" * 20,
        "selected_theft_transaction": "0x" + "c2" * 32,
        "discovery": {"candidate_count": 19998, "incident_selection_confidence": 0.853,
                      "ambiguity_reason": None},
        "normalized_evidence": {"transaction": {"block_number": 14442835, "status": "success",
                                                "timestamp": "2022-03-23T13:29:09Z",
                                                "from_address": "0x" + "09" * 20}},
        "trace_branches": [{"depth": 1, "status": "ACTIONABLE"}],
        "current_outcome": {
            "asset_totals": [{"asset": "native", "stolen": "173600000000000000000000",
                              "located": "173600000000000000000000", "unresolved": "0"}],
            "branch_counts": {"actionable": 1, "dormant": 0},
            "terminal_breakdown": [{"reason": "DETERMINISTIC_ACTIONABLE_ENTITY", "branch_count": 1}],
            "current_holdings": [{"address": "0x" + "09" * 20, "amount": "173600000000000000000000"}],
            "identified_services": [{"entity_name": "OFAC sanctioned address", "entity_type": "sanctioned",
                                     "address": "0x" + "09" * 20, "actionable": True,
                                     "evidence_type": "ofac_sdn_sanctions_list", "source": "OFAC SDN"}],
            "next_actions": ["Download and preserve the current evidence package."],
            "limitations": ["NEMESIS cannot freeze funds, access KYC records, or guarantee recovery."],
        },
    },
    "nemesis_assessment": {"classification": "unknown", "compromise_mechanism_confidence": 0.15,
                           "summary": "A protocol vulnerability was exploited."},
    "unknowns_and_limitations": ["The calling address authorisation cannot be established."],
}


def test_report_states_the_facts_and_keeps_the_boundary():
    text = render(PACKAGE)
    # deterministic facts
    assert "NMS-1" in text and "ETHEREUM" in text
    assert "19998" in text and "85% confidence" in text
    # the human amount and the exact onchain value both survive
    assert "173,600" in text and "raw 173600000000000000000000" in text
    # assessment is labelled as an assessment, not a fact
    assert "WHAT THE CHAIN PROVES" in text
    assert "NEMESIS ASSESSMENT" in text
    assert text.index("WHAT THE CHAIN PROVES") < text.index("NEMESIS ASSESSMENT")
    # actionability and its evidence
    assert "[ACTIONABLE] OFAC sanctioned address" in text
    assert "ofac_sdn_sanctions_list" in text
    # limits, including the standing disclaimer
    assert "cannot freeze funds" in text
    assert "compel any exchange or authority to act" in text


def test_missing_assessment_does_not_invalidate_the_evidence():
    package = {**PACKAGE, "nemesis_assessment": None}
    text = render(package)
    assert "No verified assessment was produced" in text
    assert "deterministic evidence above is unaffected" in text
    assert "173,600" in text


def test_report_survives_a_sparse_package():
    """A failed or very early case must still render something coherent."""
    text = render({"case_metadata": {"id": "NMS-2", "state": "FAILED"}})
    assert "NMS-2" in text
    assert "NEMESIS INCIDENT REPORT" in text
