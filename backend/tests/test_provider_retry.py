import httpx
import pytest

from app.providers import JsonRpcProvider, RpcProviderError


@pytest.mark.asyncio
async def test_rpc_retries_429_then_succeeds(monkeypatch):
    calls = 0
    async def no_sleep(_): return None
    monkeypatch.setattr("app.providers.asyncio.sleep", no_sleep)
    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x1"})
    provider = JsonRpcProvider({"ethereum": "https://rpc.test", "base": "https://rpc.test"}, transport=httpx.MockTransport(handler))
    assert await provider._call("ethereum", "eth_blockNumber", []) == "0x1"
    assert calls == 3


@pytest.mark.asyncio
async def test_rpc_provider_failure_stays_explicit_after_bounded_retries(monkeypatch):
    calls = 0
    async def no_sleep(_): return None
    monkeypatch.setattr("app.providers.asyncio.sleep", no_sleep)
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)
    provider = JsonRpcProvider({"ethereum": "https://rpc.test", "base": "https://rpc.test"}, transport=httpx.MockTransport(handler))
    with pytest.raises(RpcProviderError, match="throttled or unavailable"):
        await provider._call("ethereum", "eth_blockNumber", [])
    assert calls == 3