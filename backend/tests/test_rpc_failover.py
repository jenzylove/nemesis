"""Verification must not share fate with the indexer it is meant to check."""
import httpx
import pytest

from app.providers import JsonRpcProvider, RpcProviderError

PRIMARY = "https://primary.test"
BACKUP = "https://backup.test"
EXHAUSTED = {"jsonrpc": "2.0", "id": 1,
             "error": {"code": 429, "message": "Monthly capacity limit exceeded."}}


def provider(handler, urls=f"{PRIMARY},{BACKUP}"):
    return JsonRpcProvider({"ethereum": urls, "base": urls}, timeout_seconds=1,
                           transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_): return None
    monkeypatch.setattr("app.providers.asyncio.sleep", instant)


@pytest.mark.asyncio
async def test_a_dead_primary_falls_through_to_the_backup():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if str(request.url).startswith(PRIMARY):
            return httpx.Response(429, json=EXHAUSTED)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x2a"})

    assert await provider(handler)._call("ethereum", "eth_blockNumber", []) == "0x2a"
    assert any(u.startswith(PRIMARY) for u in seen)
    assert any(u.startswith(BACKUP) for u in seen)


@pytest.mark.asyncio
async def test_the_backup_is_untouched_while_the_primary_answers():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    await provider(handler)._call("ethereum", "eth_blockNumber", [])
    assert all(u.startswith(PRIMARY) for u in seen), "fallbacks must stay idle"


@pytest.mark.asyncio
async def test_every_endpoint_down_still_reports_a_provider_failure():
    """It must stay an RpcProviderError, which the workflow treats as retrieval."""
    def handler(request):
        return httpx.Response(429, json=EXHAUSTED)

    with pytest.raises(RpcProviderError):
        await provider(handler)._call("ethereum", "eth_blockNumber", [])


@pytest.mark.asyncio
async def test_a_single_endpoint_still_works():
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x7"})

    single = provider(handler, urls=PRIMARY)
    assert await single._call("ethereum", "eth_blockNumber", []) == "0x7"


@pytest.mark.asyncio
async def test_an_unconfigured_chain_is_still_an_error():
    def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})

    empty = JsonRpcProvider({"ethereum": "", "base": ""}, transport=httpx.MockTransport(handler))
    with pytest.raises(RpcProviderError, match="not configured"):
        await empty._call("ethereum", "eth_blockNumber", [])
