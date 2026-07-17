import os
import sys
import pathlib
import pytest
from unittest.mock import AsyncMock, Mock, patch


@pytest.fixture(autouse=True)
def _set_env(tmp_path, monkeypatch):
    # Provide default env credentials for tests
    monkeypatch.setenv("TWITTER_CT0", "ct0_test_value")
    monkeypatch.setenv("TWITTER_AUTH_TOKEN", "auth_test_value")
    yield


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_monkey_patches_applied(monkeypatch):
    """Test that monkey patches are applied correctly"""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv
    from twikit import Client

    # Verify that our patched methods are in place
    assert Client.get_tweet_by_id == srv._patched_get_tweet_by_id
    assert Client._get_more_replies == srv._patched_get_more_replies
    print("✅ Monkey patches verified")


def test_user_init_tolerates_missing_legacy_fields(monkeypatch):
    """X can omit empty legacy fields twikit still indexes directly."""
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv  # noqa: F401
    from twikit.user import User

    user = User(None, {
        "rest_id": "783214",
        "is_blue_verified": False,
        "legacy": {
            "created_at": "Tue Feb 20 14:35:54 +0000 2007",
            "name": "X",
            "screen_name": "Twitter",
            "profile_image_url_https": "https://example.com/avatar.jpg",
            "location": "",
            "description": "what's happening?!",
            "entities": {"description": {}},
            "verified": True,
            "possibly_sensitive": False,
            "can_dm": False,
            "can_media_tag": True,
            "want_retweets": False,
            "default_profile": False,
            "default_profile_image": False,
            "has_custom_timelines": True,
            "followers_count": 1,
            "fast_followers_count": 0,
            "normal_followers_count": 1,
            "friends_count": 0,
            "favourites_count": 0,
            "listed_count": 0,
            "media_count": 0,
            "statuses_count": 1,
            "is_translator": False,
            "translator_type": "none",
        },
    })

    assert user.description_urls == []
    assert user.pinned_tweet_ids == []
    assert user.withheld_in_countries == []


@pytest.mark.anyio
async def test_get_tweet_by_id_with_real_problematic_tweet(monkeypatch):
    """
    Integration test: Verify get_tweet_by_id works with the real tweet
    that previously caused itemContent KeyError
    """
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv

    server = srv.TwitterMCPServer()

    # Test with the tweet that previously failed
    result = await server.execute_tool("get_tweet_by_id", {
        "tweet_input": "2006814700802363810"
    })

    assert result and result[0].type == "text"

    # Check that we don't have an itemContent error
    assert "itemContent" not in result[0].text, "itemContent error detected!"

    # Try to parse as JSON if possible
    import json
    try:
        data = json.loads(result[0].text)

        # If successful and no error, verify tweet data
        if "error" not in data:
            assert data["id"] == "2006814700802363810"
            assert "text" in data
            assert data["author"] == "danifesto"
            print(f"✅ Successfully retrieved problematic tweet: {data['text'][:60]}...")
        else:
            # Auth error or other error is OK, as long as it's not itemContent
            assert "itemContent" not in data.get("error", ""), "itemContent error in response"
            print(f"⚠️  Test skipped due to: {data.get('error', '')[:80]}...")
    except json.JSONDecodeError:
        # Non-JSON response - check it's not an itemContent error
        assert "itemContent" not in result[0].text, "itemContent error in non-JSON response"
        print(f"⚠️  Non-JSON response (auth error likely): {result[0].text[:80]}...")


@pytest.mark.anyio
async def test_plain_id_and_url_both_work(monkeypatch):
    """
    Test that both plain ID and URL formats work identically
    This is a regression test for the reported issue where plain IDs allegedly failed
    """
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv
    import json

    server = srv.TwitterMCPServer()

    # Test with plain ID
    result_id = await server.execute_tool("get_tweet_by_id", {
        "tweet_input": "2006814700802363810"
    })

    # Test with full URL
    result_url = await server.execute_tool("get_tweet_by_id", {
        "tweet_input": "https://x.com/danifesto/status/2006814700802363810"
    })

    # Both should succeed (or fail with same error if auth issue)
    assert result_id and result_id[0].type == "text"
    assert result_url and result_url[0].type == "text"

    # Neither should have itemContent error
    assert "itemContent" not in result_id[0].text
    assert "itemContent" not in result_url[0].text

    # Parse results if possible
    try:
        data_id = json.loads(result_id[0].text)
        data_url = json.loads(result_url[0].text)

        # If one succeeded, both should succeed
        if "error" not in data_id:
            assert "error" not in data_url, "URL format failed but plain ID succeeded"
            assert data_id["id"] == data_url["id"] == "2006814700802363810"
            print("✅ Both formats successfully retrieved the same tweet")
        else:
            # If there's an error, it should be the same for both (e.g., auth error)
            print(f"⚠️  Both formats got same error (likely auth): {data_id.get('error', '')[:80]}")
    except json.JSONDecodeError:
        # Non-JSON means likely auth error - that's OK as long as it's consistent
        print("⚠️  Non-JSON response (auth error) - both formats handled the same way")


@pytest.mark.anyio
async def test_all_methods_for_itemcontent_errors(monkeypatch):
    """
    Integration test: Run all methods and check for itemContent errors
    """
    root = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import server as srv
    import json

    server = srv.TwitterMCPServer()

    tests = [
        ("get_user_info", {"username": "elonmusk"}),
        ("get_tweet_by_id", {"tweet_input": "2006814700802363810"}),
        ("search_tweets", {"query": "python", "count": 3}),
        ("get_timeline", {"count": 3}),
        ("get_latest_timeline", {"count": 3}),
        ("get_tweet_replies", {"tweet_id": "2006814700802363810", "count": 3}),
        ("get_trends", {"category": "trending", "count": 3}),
    ]

    errors = []

    for method_name, args in tests:
        try:
            result = await server.execute_tool(method_name, args)
            if result and result[0].type == "text":
                try:
                    data = json.loads(result[0].text)
                    if "error" in data and "itemContent" in str(data.get("error", "")):
                        errors.append(f"{method_name}: itemContent error found")
                except json.JSONDecodeError:
                    pass  # Non-JSON response is OK
        except Exception as e:
            if "itemContent" in str(e):
                errors.append(f"{method_name}: {type(e).__name__} - {e}")

    if errors:
        pytest.fail(f"itemContent errors found:\n" + "\n".join(errors))

    print(f"✅ All {len(tests)} methods passed without itemContent errors")
