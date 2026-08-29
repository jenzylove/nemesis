"""A failure to look must never be reported as having looked and seen nothing.

The retry path in Alchemy discovery called asyncio.sleep without importing
asyncio, so every throttled or failed provider request raised NameError. Because
NameError was not a recognised retrieval failure, the workflow reported it as
"no verified incident was found" -- a provider outage presented to a victim as a
forensic conclusion about their wallet.
"""
import inspect

import pytest

from app import alchemy_discovery
from app.discovery import DiscoveryProviderError, IncidentNotFoundError, WalletInactiveError
from app.models import CaseCreate
from app.workflow import CaseWorkflow, EVIDENCE_RETRIEVAL_MESSAGE, is_evidence_retrieval_failure


class Repo:
    def __init__(self): self.saved = []
    async def save(self, case): self.saved.append(case); return case


class Failing:
    def __init__(self, error): self.error = error
    async def discover(self, chain, wallet, incident_time): raise self.error


def test_every_name_used_in_the_retry_path_is_importable():
    """The bug was a missing import on a path only reached when a provider failed."""
    source = inspect.getsource(alchemy_discovery)
    if "asyncio." in source:
        assert hasattr(alchemy_discovery, "asyncio"), "asyncio is used but not imported"


@pytest.mark.parametrize("error", [
    NameError("name 'asyncio' is not defined"),   # the exact production failure
    AttributeError("unexpected provider payload"),
    KeyError("transfers"),
    RuntimeError("something unforeseen"),
])
def test_unexpected_failures_count_as_retrieval_failures(error):
    assert is_evidence_retrieval_failure(error) is True


@pytest.mark.parametrize("error", [
    IncidentNotFoundError("nothing qualified"),
    WalletInactiveError("no history"),
    ValueError("candidates too close to call"),
])
def test_real_investigative_answers_are_not_retrieval_failures(error):
    assert is_evidence_retrieval_failure(error) is False


@pytest.mark.asyncio
async def test_a_bug_during_discovery_does_not_become_no_incident_found():
    workflow = CaseWorkflow(Repo(), provider=None, classifier=None,
                            discovery=Failing(NameError("name 'asyncio' is not defined")))
    request = CaseCreate(wallet_address="0x" + "ab" * 20, chain="auto")

    with pytest.raises(DiscoveryProviderError) as raised:
        await workflow.create_and_investigate(request, owner_user_id="user-1")

    message = str(raised.value)
    assert message == EVIDENCE_RETRIEVAL_MESSAGE
    # the two phrasings a victim must never see for an outage
    assert "No verified incident was found" not in message
    assert "never sent a transaction" not in message
    # and nothing internal leaks
    assert "asyncio" not in message and "NameError" not in message


@pytest.mark.asyncio
async def test_the_case_records_retrieval_failure_rather_than_a_conclusion():
    repo = Repo()
    workflow = CaseWorkflow(repo, provider=None, classifier=None,
                            discovery=Failing(NameError("boom")))
    request = CaseCreate(wallet_address="0x" + "cd" * 20, chain="auto")

    with pytest.raises(DiscoveryProviderError):
        await workflow.create_and_investigate(request, owner_user_id="user-1")
