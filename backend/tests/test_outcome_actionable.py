"""The outcome must agree with the branch about what is actionable."""
from app.attribution import EntityAttribution
from app.outcome import build_outcome


def branch(status, entity_type, entity_name="OFAC sanctioned address"):
    attribution = EntityAttribution(
        entity_name=entity_name,
        entity_type=entity_type,
        address="0x" + "ab" * 20,
        chain="ethereum",
        source="test registry",
        confidence=1.0,
        evidence_type="test",
    )
    return {
        "id": "BR-1",
        "status": status,
        "asset": "native",
        "amount": "100",
        "current_address": "0x" + "ab" * 20,
        # The branch is serialised before it reaches the outcome builder, and a
        # property does not survive that, which is what the bug depended on.
        "attribution": attribution.model_dump(mode="json"),
    }


def test_sanctioned_destination_is_reported_as_actionable():
    outcome = build_outcome([], {"branches": [branch("ACTIONABLE", "sanctioned")]})
    service = outcome["identified_services"][0]
    assert service["actionable"] is True, "outcome contradicted the branch status"
    assert service["entity_type"] == "sanctioned"


def test_exchange_destination_is_reported_as_actionable():
    outcome = build_outcome([], {"branches": [branch("ACTIONABLE", "exchange", "Test Exchange")]})
    assert outcome["identified_services"][0]["actionable"] is True


def test_bridge_destination_is_not_actionable():
    """A bridge is recorded, but reaching one is not a next step by itself."""
    outcome = build_outcome([], {"branches": [branch("OBSCURED", "bridge", "Test Bridge")]})
    assert outcome["identified_services"][0]["actionable"] is False
