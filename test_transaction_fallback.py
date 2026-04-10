import pathlib
import sys

import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_twikit_request_skips_transaction_header_when_bootstrap_breaks(monkeypatch):
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    client = srv.Client("en-US")

    class DummyResponse:
        status_code = 200
        headers = {}
        text = "{}"

        def json(self):
            return {}

    calls = {"init": 0, "headers": []}

    async def fake_init(http, headers):
        calls["init"] += 1
        raise Exception("Couldn't get KEY_BYTE indices")

    async def fake_request(method, url, headers=None, **kwargs):
        calls["headers"].append(dict(headers or {}))
        return DummyResponse()

    monkeypatch.setattr(client.client_transaction, "init", fake_init)
    monkeypatch.setattr(client.http, "request", fake_request)

    await client.request("GET", "https://example.com/test")
    await client.request("GET", "https://example.com/test")

    assert calls["init"] == 1
    assert getattr(client, "_disable_client_transaction") is True
    assert all("X-Client-Transaction-Id" not in headers for headers in calls["headers"])


@pytest.mark.anyio
async def test_ensure_client_does_not_eagerly_probe_user_id(monkeypatch):
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    calls = {"user_id": 0}

    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            calls["user_id"] += 1
            return "should-not-be-called"

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()
    client = await server._ensure_client("ct0", "auth")

    assert client.cookies == {"ct0": "ct0", "auth_token": "auth"}
    assert calls["user_id"] == 0


@pytest.mark.anyio
async def test_retry_twitter_call_retries_overcapacity(monkeypatch):
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    calls = {"count": 0}

    async def flaky_operation():
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("OverCapacity: Unspecified")
        return "ok"

    result = await srv._retry_twitter_call(flaky_operation, attempts=3, base_delay=0)

    assert result == "ok"
    assert calls["count"] == 2
