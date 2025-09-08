import os
import sys
import asyncio
import types
import pathlib
import pytest


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    # Provide default env credentials for tests; individual tests may override/unset
    monkeypatch.setenv("TWITTER_CT0", "ct0_test_value")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "auth_test_value")
    yield


@pytest.fixture(scope="session")
def anyio_backend():
    # Limit to asyncio to avoid needing trio dependency in tests
    return "asyncio"


@pytest.mark.anyio
async def test_tools_schema_has_no_cookie_fields(monkeypatch):
    # Import server module by path since folder name has a hyphen
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    # Instantiate server
    server = srv.TwitterMCPServer()

    # Ensure we can list tools via helper
    tools = server.get_tools()
    names = {t.name for t in tools}
    assert "authenticate" not in names, "authenticate should be removed from tools list"

    # None of the tools should require cookie parameters
    for t in tools:
        schema = t.inputSchema or {}
        props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
        required = (schema.get("required") or []) if isinstance(schema, dict) else []
        assert "ct0" not in props
        assert "auth_token" not in props
        assert "ct0" not in required
        assert "auth_token" not in required


@pytest.mark.anyio
async def test_execute_tool_uses_env_credentials(monkeypatch):
    # Import after env set
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    # Fake client to capture cookies
    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            return "123"

        async def user(self):
            class U:  # minimal shape for _test_authentication if called
                id = "123"
                screen_name = "tester"
                name = "Tester"
                followers_count = 0
                following_count = 0
                statuses_count = 0
                verified = False
            return U()

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()

    called = {}

    async def fake_search(self, client, query, count=20, product="Latest"):
        called["cookies"] = getattr(client, "cookies", {})
        called["query"] = query
        return [{"id": "1", "text": "ok", "author": "tester", "author_name": "Tester", "created_at": "now", "like_count": 0, "retweet_count": 0, "reply_count": 0}]

    monkeypatch.setattr(srv.TwitterMCPServer, "_search_tweets", fake_search)

    # No cookie args provided; should still work via env
    res_list = await server.execute_tool("search_tweets", {"query": "python"})
    assert res_list and res_list[0].type == "text"
    assert called["query"] == "python"
    assert called["cookies"] == {"ct0": "ct0_test_value", "auth_token": "auth_test_value"}


@pytest.mark.anyio
async def test_missing_env_returns_clear_error(monkeypatch):
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    # Unset env to simulate missing creds
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    # Explicitly set to empty to ensure falsy read
    monkeypatch.setenv("TWITTER_CT0", "")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "")
    # Also chdir to a clean temp dir so no .env is auto-loaded
    tmp = pathlib.Path.cwd() / ".pytest-tmp-no-env"
    tmp.mkdir(exist_ok=True)
    monkeypatch.chdir(tmp)

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("search_tweets", {"query": "x"})
    assert res and res[0].type == "text"
    msg = res[0].text.lower()
    assert "missing" in msg and "twitter_ct0" in msg and "twitter_auth_token" in msg


@pytest.mark.anyio
async def test_authenticate_tool_deprecated_message(monkeypatch):
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("authenticate", {})
    assert res and res[0].type == "text"
    msg = res[0].text.lower()
    assert "deprecated" in msg or "automatic" in msg
