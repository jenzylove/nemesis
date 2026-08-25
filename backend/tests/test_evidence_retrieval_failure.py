"""A provider outage must never be reported as an investigative conclusion."""
import pytest

from app.attribution import CuratedAttributionProvider, default_curated_attributions
from app.discovery import DiscoveryProviderError, IncidentNotFoundError
from app.models import CaseCreate
from app.providers import RpcProviderError
from app.workflow import EVIDENCE_RETRIEVAL_MESSAGE, CaseWorkflow


class Repo:
    def __init__(self): self.saved = []
    async def save(self, case): self.saved.append(case.model_copy(deep=True)); return case


class BrokenDiscovery:
    def __init__(self, error): self.error = error
    async def discover(self, chain, wallet, incident_time): raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    RpcProviderError("upstream throttled or unavailable"),
    DiscoveryProviderError("Alchemy wallet history request failed"),
])
async def test_provider_outage_is_reported_as_retrieval_failure(error):
    repo = Repo()
    workflow = CaseWorkflow(repo, provider=None, classifier=None, discovery=BrokenDiscovery(error))
    request = CaseCreate(wallet_address="0x" + "ab" * 20, chain="auto")

    with pytest.raises(DiscoveryProviderError) as raised:
        await workflow.create_and_investigate(request, owner_user_id="user-1")

    # The victim is told retrieval failed, not that nothing was found.
    assert str(raised.value) == EVIDENCE_RETRIEVAL_MESSAGE
    assert "Alchemy" not in str(raised.value)
    assert "throttled" not in str(raised.value)


@pytest.mark.asyncio
async def test_genuine_absence_stays_a_normal_investigative_result():
    repo = Repo()
    workflow = CaseWorkflow(
        repo, provider=None, classifier=None,
        discovery=BrokenDiscovery(IncidentNotFoundError("no candidate qualified")),
    )
    request = CaseCreate(wallet_address="0x" + "cd" * 20, chain="auto")

    with pytest.raises(ValueError) as raised:
        await workflow.create_and_investigate(request, owner_user_id="user-1")

    assert not isinstance(raised.value, DiscoveryProviderError)
    assert "No verified incident was found" in str(raised.value)


@pytest.mark.asyncio
async def test_sanctioned_destination_is_actionable():
    """ACTIONABLE was previously unreachable: the registry held only bridges."""
    entries = default_curated_attributions()
    sanctioned = [entry for entry in entries if entry.entity_type == "sanctioned"]
    assert sanctioned, "sanctions registry is empty"
    assert all(entry.actionable for entry in sanctioned)
    assert not any(entry.actionable for entry in entries if entry.entity_type == "bridge")

    provider = CuratedAttributionProvider()
    hit = await provider.lookup(sanctioned[0].chain, sanctioned[0].address.upper())
    assert hit is not None and hit.actionable
    assert hit.evidence_type == "ofac_sdn_sanctions_list"
    # NEMESIS must not name an operator the source list does not evidence.
    assert hit.entity_name == "OFAC sanctioned address"
