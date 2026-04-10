import os
import sys
import asyncio
import types
import pathlib
import pytest


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    # Provide default env credentials for tests
    monkeypatch.setenv("TWITTER_CT0", "ct0_test_value")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "auth_test_value")
    yield


@pytest.fixture(scope="session")
def anyio_backend():
    # Limit to asyncio to avoid needing trio dependency in tests
    return "asyncio"


@pytest.mark.anyio
async def test_parse_tweet_id_plain_id(monkeypatch):
    """Test parsing plain tweet ID"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._parse_tweet_id("2006814700802363810")
    assert result == "2006814700802363810"


@pytest.mark.anyio
async def test_parse_tweet_id_x_url(monkeypatch):
    """Test parsing x.com URL"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._parse_tweet_id("https://x.com/danifesto/status/2006814700802363810")
    assert result == "2006814700802363810"


@pytest.mark.anyio
async def test_parse_tweet_id_twitter_url(monkeypatch):
    """Test parsing twitter.com URL"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._parse_tweet_id("https://twitter.com/user/status/1234567890123456789")
    assert result == "1234567890123456789"


@pytest.mark.anyio
async def test_parse_tweet_id_url_with_query_string(monkeypatch):
    """Test parsing URL with query string parameters"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._parse_tweet_id("https://x.com/danifesto/status/2006814700802363810?s=46&t=uFZE-MuhgWdh1YErEZzLtQ")
    assert result == "2006814700802363810"


@pytest.mark.anyio
async def test_parse_tweet_id_various_domains(monkeypatch):
    """Test parsing works for both x.com and twitter.com"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()

    # x.com domain
    result1 = server._parse_tweet_id("https://x.com/user/status/1111111111111111111")
    assert result1 == "1111111111111111111"

    # twitter.com domain
    result2 = server._parse_tweet_id("https://twitter.com/user/status/2222222222222222222")
    assert result2 == "2222222222222222222"


@pytest.mark.anyio
async def test_extract_exact_tweet_lookup_id_plain_id(monkeypatch):
    """search_tweets should recognize a plain tweet ID as a direct lookup."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._extract_exact_tweet_lookup_id("2006814700802363810")
    assert result == "2006814700802363810"


@pytest.mark.anyio
async def test_extract_exact_tweet_lookup_id_url(monkeypatch):
    """search_tweets should recognize a tweet URL as a direct lookup."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._extract_exact_tweet_lookup_id(
        "https://x.com/danifesto/status/2006814700802363810?s=46"
    )
    assert result == "2006814700802363810"


@pytest.mark.anyio
async def test_extract_exact_tweet_lookup_id_ignores_free_text(monkeypatch):
    """Free text that merely contains digits should not be treated as a tweet lookup."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    result = server._extract_exact_tweet_lookup_id(
        "greg status 2006814700802363810 please"
    )
    assert result is None


@pytest.mark.anyio
async def test_get_tweet_by_id_tool_exists(monkeypatch):
    """Test that get_tweet_by_id tool is registered"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    tools = server.get_tools()
    tool_names = {t.name for t in tools}

    assert "get_tweet_by_id" in tool_names


@pytest.mark.anyio
async def test_get_tweet_by_id_tool_schema(monkeypatch):
    """Test that get_tweet_by_id tool has correct schema"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    server = srv.TwitterMCPServer()
    tools = server.get_tools()
    tool = next((t for t in tools if t.name == "get_tweet_by_id"), None)

    assert tool is not None
    assert "tweet_input" in tool.inputSchema["properties"]
    assert "tweet_input" in tool.inputSchema["required"]


@pytest.mark.anyio
async def test_get_tweet_by_id_executes_with_plain_id(monkeypatch):
    """Test executing get_tweet_by_id with plain ID"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    # Fake client
    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            return "123"

        async def get_tweet_by_id(self, tweet_id):
            class FakeTweet:
                id = tweet_id
                text = "Test tweet content"
                created_at = "2025-01-01"
                favorite_count = 42
                retweet_count = 10
                reply_count = 5
                view_count = 1000
                lang = "en"
                is_quote_status = False
                possibly_sensitive = False

                class user:
                    id = "999"
                    screen_name = "testuser"
                    name = "Test User"

            return FakeTweet()

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("get_tweet_by_id", {"tweet_input": "1234567890123456789"})

    assert res and res[0].type == "text"
    import json
    data = json.loads(res[0].text)
    assert data["id"] == "1234567890123456789"
    assert data["text"] == "Test tweet content"
    assert data["author"] == "testuser"


@pytest.mark.anyio
async def test_get_tweet_by_id_executes_with_url(monkeypatch):
    """Test executing get_tweet_by_id with URL"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    # Fake client
    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            return "123"

        async def get_tweet_by_id(self, tweet_id):
            class FakeTweet:
                id = tweet_id
                text = "Test tweet from URL"
                created_at = "2025-01-01"
                favorite_count = 100
                retweet_count = 20
                reply_count = 8
                view_count = 5000
                lang = "en"
                is_quote_status = False
                possibly_sensitive = False

                class user:
                    id = "888"
                    screen_name = "urluser"
                    name = "URL User"

            return FakeTweet()

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("get_tweet_by_id", {
        "tweet_input": "https://x.com/urluser/status/2006814700802363810?s=46"
    })

    assert res and res[0].type == "text"
    import json
    data = json.loads(res[0].text)
    # Should have extracted the ID from the URL
    assert data["id"] == "2006814700802363810"
    assert data["text"] == "Test tweet from URL"
    assert data["author"] == "urluser"


@pytest.mark.anyio
async def test_search_tweets_uses_tweet_lookup_for_url_query(monkeypatch):
    """URL queries should bypass twikit search and reuse the working tweet detail path."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    class FakeClient:
        search_called = False
        looked_up_id = None

        async def search_tweet(self, query, product="Latest", count=20):
            self.search_called = True
            raise AssertionError("search_tweet should not be called for direct tweet URLs")

        async def get_tweet_by_id(self, tweet_id):
            self.looked_up_id = tweet_id

            class FakeTweet:
                id = tweet_id
                text = "Tweet fetched via direct lookup"
                created_at = "2025-01-01"
                favorite_count = 7
                retweet_count = 2
                reply_count = 1

                class user:
                    screen_name = "lookupuser"
                    name = "Lookup User"

            return FakeTweet()

    server = srv.TwitterMCPServer()
    client = FakeClient()
    result = await server._search_tweets(
        client,
        "https://x.com/lookupuser/status/2006814700802363810?s=46",
        count=5,
        product="Latest",
    )

    assert client.looked_up_id == "2006814700802363810"
    assert client.search_called is False
    assert result == [
        {
            "id": "2006814700802363810",
            "text": "Tweet fetched via direct lookup",
            "author": "lookupuser",
            "author_name": "Lookup User",
            "created_at": "2025-01-01",
            "like_count": 7,
            "retweet_count": 2,
            "reply_count": 1,
        }
    ]


@pytest.mark.anyio
async def test_search_tweets_uses_tweet_lookup_for_plain_id_query(monkeypatch):
    """Plain tweet IDs should also bypass the stale search endpoint."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    class FakeClient:
        search_called = False
        looked_up_id = None

        async def search_tweet(self, query, product="Latest", count=20):
            self.search_called = True
            raise AssertionError("search_tweet should not be called for plain tweet IDs")

        async def get_tweet_by_id(self, tweet_id):
            self.looked_up_id = tweet_id

            class FakeTweet:
                id = tweet_id
                text = "Tweet fetched via ID"
                created_at = "2025-01-01"
                favorite_count = 3
                retweet_count = 1
                reply_count = 0

                class user:
                    screen_name = "plainid"
                    name = "Plain ID"

            return FakeTweet()

    server = srv.TwitterMCPServer()
    client = FakeClient()
    result = await server._search_tweets(client, "2006814700802363810", count=5, product="Latest")

    assert client.looked_up_id == "2006814700802363810"
    assert client.search_called is False
    assert result == [
        {
            "id": "2006814700802363810",
            "text": "Tweet fetched via ID",
            "author": "plainid",
            "author_name": "Plain ID",
            "created_at": "2025-01-01",
            "like_count": 3,
            "retweet_count": 1,
            "reply_count": 0,
        }
    ]


@pytest.mark.anyio
async def test_search_tweets_parses_generic_search_results(monkeypatch):
    """Generic text search should use the POST-based SearchTimeline response shape."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    async def fake_request_search_timeline(client, query, product, count, cursor=None):
        assert query == "openai"
        assert product == "Latest"
        assert count == 3
        return {
            "data": {
                "search_by_raw_query": {
                    "search_timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "entryId": "tweet-123",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "123",
                                                            "legacy": {
                                                                "id_str": "123",
                                                                "full_text": "OpenAI generic search result",
                                                                "created_at": "Fri Apr 10 12:00:00 +0000 2026",
                                                                "favorite_count": 11,
                                                                "retweet_count": 4,
                                                                "reply_count": 2,
                                                            },
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "core": {
                                                                            "screen_name": "openai",
                                                                            "name": "OpenAI",
                                                                        }
                                                                    }
                                                                }
                                                            },
                                                        }
                                                    }
                                                }
                                            },
                                        },
                                        {
                                            "entryId": "cursor-bottom-1",
                                            "content": {"value": "cursor"},
                                        },
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }

    monkeypatch.setattr(srv, "_request_search_timeline", fake_request_search_timeline)

    server = srv.TwitterMCPServer()
    result = await server._search_tweets(object(), "openai", count=3, product="Latest")

    assert result == [
        {
            "id": "123",
            "text": "OpenAI generic search result",
            "author": "openai",
            "author_name": "OpenAI",
            "created_at": "Fri Apr 10 12:00:00 +0000 2026",
            "like_count": 11,
            "retweet_count": 4,
            "reply_count": 2,
        }
    ]


@pytest.mark.anyio
async def test_get_tweet_by_id_returns_complete_data(monkeypatch):
    """Test that get_tweet_by_id returns all expected fields"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    # Fake client
    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            return "123"

        async def get_tweet_by_id(self, tweet_id):
            class FakeTweet:
                id = "9999999999999999999"
                text = "Complete data test"
                created_at = "2025-01-03"
                favorite_count = 250
                retweet_count = 50
                reply_count = 15
                view_count = 10000
                lang = "en"
                is_quote_status = True
                possibly_sensitive = False

                class user:
                    id = "555"
                    screen_name = "completeuser"
                    name = "Complete User"

            return FakeTweet()

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("get_tweet_by_id", {"tweet_input": "9999999999999999999"})

    assert res and res[0].type == "text"
    import json
    data = json.loads(res[0].text)

    # Verify all expected fields are present
    expected_fields = [
        "id", "text", "author", "author_name", "author_id",
        "created_at", "like_count", "retweet_count", "reply_count",
        "view_count", "lang", "is_quote_status", "possibly_sensitive"
    ]
    for field in expected_fields:
        assert field in data, f"Expected field '{field}' not found in response"

    # Verify field values
    assert data["id"] == "9999999999999999999"
    assert data["text"] == "Complete data test"
    assert data["author"] == "completeuser"
    assert data["author_name"] == "Complete User"
    assert data["author_id"] == "555"
    assert data["like_count"] == 250
    assert data["retweet_count"] == 50
    assert data["reply_count"] == 15
    assert data["view_count"] == 10000
    assert data["is_quote_status"] is True


@pytest.mark.anyio
async def test_get_tweet_replies_accepts_url(monkeypatch):
    """Test that get_tweet_replies now accepts URLs"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    called_with_id = None

    # Fake client
    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            return "123"

        async def get_tweet_by_id(self, tweet_id):
            nonlocal called_with_id
            called_with_id = tweet_id

            class FakeTweet:
                id = tweet_id
                text = "Original tweet"
                created_at = "2025-01-01"
                reply_count = 2
                retweet_count = 0
                favorite_count = 0
                replies = None

                class user:
                    id = "777"
                    screen_name = "original"
                    name = "Original User"

            return FakeTweet()

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("get_tweet_replies", {
        "tweet_id": "https://x.com/original/status/9876543210987654321"
    })

    assert res and res[0].type == "text"
    # Verify it extracted the ID correctly
    assert called_with_id == "9876543210987654321"


@pytest.mark.anyio
async def test_get_tweet_replies_backward_compatible(monkeypatch):
    """Test that get_tweet_replies still works with plain IDs for backward compatibility"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # type: ignore

    called_with_id = None

    # Fake client
    class FakeClient:
        def __init__(self, lang):
            self.lang = lang
            self.cookies = None

        def set_cookies(self, cookies):
            self.cookies = dict(cookies)

        async def user_id(self):
            return "123"

        async def get_tweet_by_id(self, tweet_id):
            nonlocal called_with_id
            called_with_id = tweet_id

            class FakeTweet:
                id = tweet_id
                text = "Tweet with replies"
                created_at = "2025-01-01"
                reply_count = 1
                retweet_count = 0
                favorite_count = 0
                replies = None

                class user:
                    id = "666"
                    screen_name = "replier"
                    name = "Replier"

            return FakeTweet()

    monkeypatch.setattr(srv, "Client", FakeClient)

    server = srv.TwitterMCPServer()
    res = await server.execute_tool("get_tweet_replies", {
        "tweet_id": "5555555555555555555"
    })

    assert res and res[0].type == "text"
    assert called_with_id == "5555555555555555555"
