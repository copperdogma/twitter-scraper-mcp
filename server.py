#!/usr/bin/env python3
"""
Twitter MCP Server using twikit

This server provides Twitter functionality through the Model Context Protocol (MCP).
It uses twikit for Twitter API interactions and supports authentication via ct0 and auth_token
cookies provided by the LLM model or environment variables.
"""

import asyncio
import os
import json
import sys
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.types as types

from twikit import Client
from twikit.tweet import Tweet
from twikit.utils import find_dict, Result
from functools import partial

# Load environment variables
load_dotenv()

_SEARCH_BUNDLE_RE = re.compile(
    r'https://abs\.twimg\.com/responsive-web/client-web/main\.[^"\']+\.js'
)
_SEARCH_TIMELINE_QUERY_ID_RE = re.compile(
    r'queryId:"([A-Za-z0-9_-]+)",operationName:"SearchTimeline"'
)
_SEARCH_TIMELINE_QUERY_ID_CACHE: tuple[str, float] | None = None
_SEARCH_TIMELINE_QUERY_ID_TTL_SECONDS = 900

# Monkey-patch twikit's get_tweet_by_id to handle missing itemContent
_original_get_tweet_by_id = Client.get_tweet_by_id


async def _request_tweet_detail(client: Client, tweet_id: str, cursor: str | None = None) -> dict:
    from twikit.client.gql import Endpoint
    from twikit.constants import FEATURES
    from twikit.utils import flatten_params

    variables = {
        'focalTweetId': tweet_id,
        'with_rux_injections': False,
        'includePromotedContent': True,
        'withCommunity': True,
        'withQuickPromoteEligibilityTweetFields': True,
        'withBirdwatchNotes': True,
        'withVoice': True,
        'withV2Timeline': True
    }
    if cursor is not None:
        variables['cursor'] = cursor

    params = {
        'variables': variables,
        'features': FEATURES,
        'fieldToggles': {'withAuxiliaryUserLabels': False}
    }

    response = await client.http.request(
        'GET',
        Endpoint.TWEET_DETAIL,
        params=flatten_params(params),
        headers=client._base_headers,
    )

    try:
        payload = response.json()
    except json.decoder.JSONDecodeError as e:
        raise ValueError(
            f"Tweet detail request returned invalid JSON (status {response.status_code})"
        ) from e

    if response.status_code >= 400:
        if isinstance(payload, dict) and payload.get('errors'):
            first_error = payload['errors'][0]
            message = first_error.get('message') or json.dumps(first_error)
        else:
            message = response.text or f"HTTP {response.status_code}"
        raise ValueError(f"Tweet detail request failed: {message}")

    return payload


async def _get_search_timeline_query_id(client: Client) -> str:
    global _SEARCH_TIMELINE_QUERY_ID_CACHE

    now = time.monotonic()
    if _SEARCH_TIMELINE_QUERY_ID_CACHE is not None:
        query_id, cached_at = _SEARCH_TIMELINE_QUERY_ID_CACHE
        if now - cached_at < _SEARCH_TIMELINE_QUERY_ID_TTL_SECONDS:
            return query_id

    import httpx

    headers = {
        'User-Agent': client._user_agent,
        'Accept-Language': f'{client.language},{client.language.split("-")[0]};q=0.9',
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as http:
        search_page = await http.get(
            'https://x.com/search?q=openai&src=typed_query&f=live',
            headers=headers,
        )
        search_page.raise_for_status()

        bundle_match = _SEARCH_BUNDLE_RE.search(search_page.text)
        if bundle_match is None:
            raise ValueError('Could not locate X search bundle URL')

        bundle_response = await http.get(bundle_match.group(0), headers=headers)
        bundle_response.raise_for_status()

    query_id_match = _SEARCH_TIMELINE_QUERY_ID_RE.search(bundle_response.text)
    if query_id_match is None:
        raise ValueError('Could not locate SearchTimeline query id in X bundle')

    query_id = query_id_match.group(1)
    _SEARCH_TIMELINE_QUERY_ID_CACHE = (query_id, now)
    return query_id


async def _request_search_timeline(
    client: Client,
    query: str,
    product: str,
    count: int,
    cursor: str | None = None,
) -> dict:
    from twikit.constants import FEATURES

    query_id = await _get_search_timeline_query_id(client)
    variables = {
        'rawQuery': query,
        'count': count,
        'querySource': 'typed_query',
        'product': product,
    }
    if cursor is not None:
        variables['cursor'] = cursor

    payload = {
        'variables': variables,
        'features': FEATURES,
        'queryId': query_id,
    }

    response = await client.http.request(
        'POST',
        f'https://x.com/i/api/graphql/{query_id}/SearchTimeline',
        json=payload,
        headers=client._base_headers,
    )

    try:
        response_payload = response.json()
    except json.decoder.JSONDecodeError as e:
        raise ValueError(
            f"Search timeline request returned invalid JSON (status {response.status_code})"
        ) from e

    if response.status_code >= 400:
        if isinstance(response_payload, dict) and response_payload.get('errors'):
            first_error = response_payload['errors'][0]
            message = first_error.get('message') or json.dumps(first_error)
        else:
            message = response.text or f"HTTP {response.status_code}"
        raise ValueError(f"Search timeline request failed: {message}")

    return response_payload


def _is_retryable_twitter_error(error: Exception) -> bool:
    message = str(error)
    return any(marker in message for marker in (
        'OverCapacity',
        'HTTP 502',
        'HTTP 503',
        'status: 502',
        'status: 503',
    ))


async def _retry_twitter_call(operation, attempts: int = 3, base_delay: float = 0.5):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as error:
            last_error = error
            if attempt >= attempts or not _is_retryable_twitter_error(error):
                raise
            await asyncio.sleep(base_delay * attempt)
    raise last_error

async def _patched_get_tweet_by_id(self, tweet_id: str, cursor: str | None = None) -> Tweet:
    """Patched version that handles missing itemContent in cursor entries"""
    from twikit.errors import TweetNotAvailable
    from twikit.tweet import tweet_from_data

    response = await _request_tweet_detail(self, tweet_id, cursor)

    if 'errors' in response:
        first_error = response['errors'][0]
        raise TweetNotAvailable(first_error.get('message') or json.dumps(first_error))

    entries_match = find_dict(response, 'entries', find_one=True)
    if not entries_match:
        raise TweetNotAvailable('Tweet detail response did not include timeline entries')
    entries = entries_match[0]
    reply_to = []
    replies_list = []
    related_tweets = []
    tweet = None

    for entry in entries:
        if entry['entryId'].startswith('cursor'):
            continue
        tweet_object = tweet_from_data(self, entry)
        if tweet_object is None:
            continue

        if entry['entryId'].startswith('tweetdetailrelatedtweets'):
            related_tweets.append(tweet_object)
            continue

        if entry['entryId'] == f'tweet-{tweet_id}':
            tweet = tweet_object
        else:
            if tweet is None:
                reply_to.append(tweet_object)
            else:
                replies = []
                sr_cursor = None
                show_replies = None

                for reply in entry['content']['items'][1:]:
                    if 'tweetcomposer' in reply['entryId']:
                        continue
                    if 'tweet' in reply.get('entryId'):
                        rpl = tweet_from_data(self, reply)
                        if rpl is None:
                            continue
                        replies.append(rpl)
                    if 'cursor' in reply.get('entryId'):
                        sr_cursor = reply['item']['itemContent']['value']
                        show_replies = partial(
                            self._show_more_replies,
                            tweet_id,
                            sr_cursor
                        )
                tweet_object.replies = Result(
                    replies,
                    show_replies,
                    sr_cursor
                )
                replies_list.append(tweet_object)

                display_type = find_dict(entry, 'tweetDisplayType', True)
                if display_type and display_type[0] == 'SelfThread':
                    tweet.thread = [tweet_object, *replies]

    if tweet is None:
        raise TweetNotAvailable(f'Tweet not found for id {tweet_id}')

    # FIX: Safely handle cursor entry that may not have itemContent
    if entries[-1]['entryId'].startswith('cursor'):
        try:
            reply_next_cursor = entries[-1]['content']['itemContent']['value']
            _fetch_more_replies = partial(self._get_more_replies,
                                          tweet_id, reply_next_cursor)
        except (KeyError, TypeError):
            # Cursor exists but doesn't have expected structure
            reply_next_cursor = None
            _fetch_more_replies = None
    else:
        reply_next_cursor = None
        _fetch_more_replies = None

    tweet.replies = Result(
        replies_list,
        _fetch_more_replies,
        reply_next_cursor
    )
    tweet.reply_to = reply_to
    tweet.related_tweets = related_tweets

    return tweet

# Apply the monkey patch
Client.get_tweet_by_id = _patched_get_tweet_by_id

# Monkey-patch _get_more_replies which has the same itemContent issue
_original_get_more_replies = Client._get_more_replies

async def _patched_get_more_replies(self, tweet_id: str, cursor: str) -> Result:
    """Patched version that handles missing itemContent in cursor entries"""
    from twikit.tweet import tweet_from_data

    response = await _request_tweet_detail(self, tweet_id, cursor)
    entries_match = find_dict(response, 'entries', find_one=True)
    if not entries_match:
        return Result([])
    entries = entries_match[0]

    results = []
    for entry in entries:
        if entry['entryId'].startswith(('cursor', 'label')):
            continue
        tweet = tweet_from_data(self, entry)
        if tweet is not None:
            results.append(tweet)

    # FIX: Safely handle cursor entry that may not have itemContent
    if entries[-1]['entryId'].startswith('cursor'):
        try:
            next_cursor = entries[-1]['content']['itemContent']['value']
            _fetch_next_result = partial(self._get_more_replies, tweet_id, next_cursor)
        except (KeyError, TypeError):
            # Cursor exists but doesn't have expected structure
            next_cursor = None
            _fetch_next_result = None
    else:
        next_cursor = None
        _fetch_next_result = None

    return Result(
        results,
        _fetch_next_result,
        next_cursor
    )

# Apply the monkey patch
Client._get_more_replies = _patched_get_more_replies

# Monkey-patch twikit's request flow to tolerate X transaction header breakage.
# twikit 2.3.3 can fail while deriving KEY_BYTE indices for X-Client-Transaction-Id,
# which makes every authenticated request fail before cookies are even exercised.
_original_client_request = Client.request

async def _patched_client_request(self, method: str, url: str, auto_unlock: bool = True,
                                  raise_exception: bool = True, **kwargs):
    from urllib.parse import urlparse
    from twikit.errors import (
        AccountLocked,
        AccountSuspended,
        BadRequest,
        Forbidden,
        NotFound,
        RequestTimeout,
        ServerError,
        TooManyRequests,
        TwitterException,
        Unauthorized,
    )
    from twikit.constants import DOMAIN

    headers = kwargs.pop('headers', {})

    if not getattr(self, '_disable_client_transaction', False):
        transaction_error = None
        if not self.client_transaction.home_page_response:
            cookies_backup = self.get_cookies().copy()
            ct_headers = {
                'Accept-Language': f'{self.language},{self.language.split("-")[0]};q=0.9',
                'Cache-Control': 'no-cache',
                'Referer': f'https://{DOMAIN}',
                'User-Agent': self._user_agent,
            }
            try:
                await self.client_transaction.init(self.http, ct_headers)
            except Exception as e:
                transaction_error = e
                self._disable_client_transaction = True
            finally:
                self.set_cookies(cookies_backup, clear_cookies=True)

        if transaction_error is None:
            try:
                tid = self.client_transaction.generate_transaction_id(
                    method=method,
                    path=urlparse(url).path,
                )
                headers['X-Client-Transaction-Id'] = tid
            except Exception as e:
                transaction_error = e
                self._disable_client_transaction = True

        if transaction_error is not None and not getattr(self, '_transaction_bypass_warned', False):
            print(
                f"[WARN] twikit transaction header disabled after bootstrap failure: {transaction_error}",
                file=sys.stderr,
            )
            self._transaction_bypass_warned = True

    cookies_backup = self.get_cookies().copy()
    response = await self.http.request(method, url, headers=headers, **kwargs)
    self._remove_duplicate_ct0_cookie()

    try:
        response_data = response.json()
    except json.decoder.JSONDecodeError:
        response_data = response.text

    if isinstance(response_data, dict) and 'errors' in response_data:
        first_error = response_data['errors'][0]
        error_code = first_error.get('code')
        error_message = first_error.get('message') or json.dumps(first_error)
        if error_code in (37, 64):
            raise AccountSuspended(error_message)

        if error_code == 326:
            if self.captcha_solver is None:
                raise AccountLocked(
                    'Your account is locked. Visit '
                    f'https://{DOMAIN}/account/access to unlock it.'
                )
            if auto_unlock:
                await self.unlock()
                self.set_cookies(cookies_backup, clear_cookies=True)
                response = await self.http.request(method, url, **kwargs)
                self._remove_duplicate_ct0_cookie()
                try:
                    response_data = response.json()
                except json.decoder.JSONDecodeError:
                    response_data = response.text
        elif raise_exception and error_code is None:
            raise TwitterException(error_message, headers=response.headers)

    status_code = response.status_code

    if status_code >= 400 and raise_exception:
        message = f'status: {status_code}, message: "{response.text}"'
        if status_code == 400:
            raise BadRequest(message, headers=response.headers)
        elif status_code == 401:
            raise Unauthorized(message, headers=response.headers)
        elif status_code == 403:
            raise Forbidden(message, headers=response.headers)
        elif status_code == 404:
            raise NotFound(message, headers=response.headers)
        elif status_code == 408:
            raise RequestTimeout(message, headers=response.headers)
        elif status_code == 429:
            if await self._get_user_state() == 'suspended':
                raise AccountSuspended(message, headers=response.headers)
            raise TooManyRequests(message, headers=response.headers)
        elif 500 <= status_code < 600:
            raise ServerError(message, headers=response.headers)
        else:
            raise TwitterException(message, headers=response.headers)

    if status_code == 200:
        return response_data, response

    return response_data, response

# Apply the monkey patch
Client.request = _patched_client_request

class TwitterMCPServer:
    def __init__(self):
        self.client = None
        self.server = Server("twitter-mcp")
        self.authenticated_clients = {}  # Cache for authenticated clients (legacy)
        self._client_lock = asyncio.Lock()
        self._last_credentials: Optional[Tuple[str, str]] = None
        self.setup_handlers()

    def setup_handlers(self):
        """Set up MCP server handlers"""
        
        @self.server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            """List available Twitter resources"""
            return [
                Resource(
                    uri="twitter://timeline",
                    name="Twitter Timeline",
                    description="Get tweets from your timeline (requires ct0 and auth_token)",
                    mimeType="application/json"
                ),
                Resource(
                    uri="twitter://user-tweets",
                    name="User Tweets",
                    description="Get tweets from a specific user (requires ct0 and auth_token)",
                    mimeType="application/json"
                ),
                Resource(
                    uri="twitter://search",
                    name="Search Tweets",
                    description="Search for tweets (requires ct0 and auth_token)",
                    mimeType="application/json"
                )
            ]

        @self.server.read_resource()
        async def handle_read_resource(uri: types.AnyUrl) -> str:
            """Read a specific Twitter resource"""
            # For resources, we'll use environment variables as fallback
            auth_token = os.getenv("TWITTER_AUTH_TOKEN")
            ct0 = os.getenv("TWITTER_CT0")
            if not auth_token or not ct0:
                return json.dumps({
                    "error": "Authentication required. Please provide TWITTER_AUTH_TOKEN and TWITTER_CT0 environment variables or use tools with ct0 and auth_token parameters."
                }, indent=2)
            
            client = await self._get_authenticated_client(ct0, auth_token)
            
            if uri.scheme != "twitter":
                raise ValueError(f"Unsupported URI scheme: {uri.scheme}")
            
            path = uri.path.lstrip("/")
            
            if path == "timeline":
                tweets = await self._get_timeline(client)
                return json.dumps(tweets, indent=2)
            elif path == "user-tweets":
                # Extract username from query parameters if provided
                username = getattr(uri, 'fragment', None) or "twitter"
                tweets = await self._get_user_tweets(client, username)
                return json.dumps(tweets, indent=2)
            elif path == "search":
                # Extract query from fragment if provided, use 'Latest' product by default
                query = getattr(uri, 'fragment', None) or "python"
                tweets = await self._search_tweets(client, query, product="Latest")
                return json.dumps(tweets, indent=2)
            else:
                raise ValueError(f"Unknown resource path: {path}")

        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """List available Twitter tools"""
            return self.get_tools()

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            return await self.execute_tool(name, arguments)

    async def execute_tool(self, name: str, arguments: dict) -> list[types.TextContent]:
        """Execute a tool with implicit env-based auth (no cookie args)."""
        try:
            # Do not override already-set env vars; allow process env to win over .env
            load_dotenv(override=False)
            if name == "authenticate":
                # Return guidance without attempting network auth
                return [types.TextContent(type="text", text=(
                    "Authentication is automatic using .env. The authenticate tool is deprecated."
                ))]
            # Explicitly disable write/DM tools for safety
            disabled = {
                "tweet",
                "like_tweet",
                "retweet",
                "send_dm",
                "add_reaction_to_message",
                "delete_dm",
                "get_dm_history",  # reading DMs is sensitive; disable by default
            }
            if name in disabled:
                return [types.TextContent(type="text", text=f"Tool '{name}' is disabled on this server for safety.")]
            ct0 = os.getenv("TWITTER_CT0")
            auth_token = os.getenv("TWITTER_AUTH_TOKEN")
            if not ct0 or not auth_token:
                return [
                    types.TextContent(
                        type="text",
                        text=(
                            "Error: Missing Twitter credentials. Set TWITTER_CT0 and TWITTER_AUTH_TOKEN in twitter-scraper-mcp/.env."
                        ),
                    )
                ]

            client = await self._ensure_client(ct0, auth_token)

            if name == "get_user_info":
                result = await self._get_user_info(client, arguments["username"])
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "get_tweet_by_id":
                result = await self._get_tweet_by_id(client, arguments["tweet_input"])
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "search_tweets":
                count = arguments.get("count", 20)
                product = arguments.get("product", "Latest")
                if product not in ("Top", "Latest"):
                    product = "Latest"
                result = await self._search_tweets(client, arguments["query"], count, product)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "get_timeline":
                count = arguments.get("count", 20)
                result = await self._get_timeline(client, count)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "get_latest_timeline":
                count = arguments.get("count", 20)
                result = await self._get_latest_timeline(client, count)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            # write/DM tools are disabled; fall through to unknown if somehow reached

            if name == "get_tweet_replies":
                count = arguments.get("count", 20)
                # Support both old 'tweet_id' and new 'tweet_input' parameter names for backwards compatibility
                tweet_input = arguments.get("tweet_input") or arguments.get("tweet_id")
                result = await self._get_tweet_replies(client, tweet_input, count)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if name == "get_trends":
                category = arguments.get("category", "trending")
                count = arguments.get("count", 20)
                result = await self._get_trends(client, category, count)
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            return [types.TextContent(type="text", text=f"Error: Unknown tool: {name}")]
        except Exception as e:
            return [types.TextContent(type="text", text=f"Error: {str(e)}")]

    def get_tools(self) -> list[Tool]:
        """Return Tool definitions without cookie parameters (implicit auth)."""
        return [
            Tool(
                name="get_user_info",
                description="Get information about a Twitter user",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "username": {"type": "string", "description": "The username (without @) to get info for"}
                    },
                    "required": ["username"]
                }
            ),
            Tool(
                name="get_tweet_by_id",
                description="Get a specific tweet by ID. Accepts both plain tweet IDs (e.g., '2006814700802363810') and full URLs (e.g., 'https://x.com/user/status/2006814700802363810'). Both formats work identically.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tweet_input": {
                            "type": "string",
                            "description": "Tweet ID (plain digits) or full URL. Examples: '2006814700802363810' or 'https://x.com/user/status/2006814700802363810' - both work the same way"
                        }
                    },
                    "required": ["tweet_input"]
                }
            ),
            Tool(
                name="get_timeline",
                description="Get tweets from your timeline",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of tweets to return (default: 20)", "default": 20, "minimum": 1, "maximum": 100}
                    }
                }
            ),
            Tool(
                name="get_latest_timeline",
                description="Get latest tweets from your timeline",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "count": {"type": "integer", "description": "Number of tweets to return (default: 20)", "default": 20, "minimum": 1, "maximum": 100}
                    }
                }
            ),
            Tool(
                name="search_tweets",
                description="Search for tweets with a specific query. Full tweet URLs and plain tweet IDs are also supported and will resolve the exact tweet directly.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"},
                        "count": {"type": "integer", "description": "Number of tweets to return (default: 20)", "default": 20, "minimum": 1, "maximum": 100},
                        "product": {"type": "string", "description": "Type of results to return (e.g., 'Top' or 'Latest')", "enum": ["Top", "Latest"], "default": "Latest"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="get_tweet_replies",
                description="Get replies to a specific tweet. Accepts tweet IDs or URLs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tweet_id": {"type": "string", "description": "Tweet ID or URL (e.g., '2006814700802363810' or 'https://x.com/user/status/2006814700802363810')"},
                        "tweet_input": {"type": "string", "description": "Tweet ID or URL (alternate parameter name)"},
                        "count": {"type": "integer", "description": "Number of replies to retrieve (default: 20)", "default": 20}
                    },
                    "required": []
                }
            ),
            Tool(
                name="get_trends",
                description="Get trending topics on Twitter",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "The category of trends to retrieve", "enum": ["trending", "for-you", "news", "sports", "entertainment"], "default": "trending"},
                        "count": {"type": "integer", "description": "Number of trends to retrieve (default: 20)", "default": 20, "minimum": 1, "maximum": 50}
                    }
                }
            )
        ]

    async def _ensure_client(self, ct0: str, auth_token: str) -> Client:
        """Ensure a single client using env credentials; reuse if unchanged."""
        async with self._client_lock:
            creds: Tuple[str, str] = (ct0, auth_token)
            if self.client is not None and self._last_credentials == creds:
                return self.client
            client = Client('en-US')
            cookies = {'ct0': ct0, 'auth_token': auth_token}
            client.set_cookies(cookies)
            self.client = client
            self._last_credentials = creds
            return client

    async def _get_authenticated_client(self, ct0: str, auth_token: str) -> Client:
        """Compatibility wrapper to ensure a client; uses env creds path."""
        return await self._ensure_client(ct0, auth_token)

    def _parse_tweet_id(self, tweet_input: str) -> str:
        """Parse tweet ID from various input formats.

        Supports:
        - Plain ID: "2006814700802363810"
        - Twitter URL: "https://twitter.com/user/status/2006814700802363810"
        - X URL: "https://x.com/user/status/2006814700802363810"
        - URLs with query strings: "https://x.com/user/status/2006814700802363810?s=46&t=..."
        """
        # If it's already just digits, return as-is
        if tweet_input.isdigit():
            return tweet_input

        # Try to extract tweet ID from URL patterns
        # Matches: twitter.com/*/status/ID or x.com/*/status/ID
        url_pattern = r'(?:twitter\.com|x\.com)/[^/]+/status/(\d+)'
        match = re.search(url_pattern, tweet_input)
        if match:
            return match.group(1)

        # If no pattern matched but it contains only digits and maybe some non-alphanumeric chars
        # extract just the digits
        digits_only = re.sub(r'\D', '', tweet_input)
        if digits_only and len(digits_only) >= 15:  # Tweet IDs are typically 18-19 digits
            return digits_only

        # If nothing worked, return the original input and let the API handle the error
        return tweet_input

    def _extract_exact_tweet_lookup_id(self, query: str) -> Optional[str]:
        """Return a tweet ID when the query is exactly a tweet URL or tweet ID."""
        normalized = query.strip()
        if re.fullmatch(r"\d{15,25}", normalized):
            return normalized

        url_match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?(?:mobile\.)?(?:twitter\.com|x\.com)/[^/]+/status/(\d+)(?:[/?].*)?",
            normalized,
            re.IGNORECASE,
        )
        if url_match:
            return url_match.group(1)

        return None

    def _search_entry_to_result(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract a search result tweet from the current SearchTimeline response shape."""
        try:
            tweet_result = entry['content']['itemContent']['tweet_results']['result']
            if 'tweet' in tweet_result:
                tweet_result = tweet_result['tweet']

            legacy = tweet_result['legacy']
            user_result = tweet_result['core']['user_results']['result']
            user_core = user_result['core']
        except (KeyError, TypeError):
            return None

        return {
            "id": tweet_result.get('rest_id') or legacy.get('id_str'),
            "text": legacy.get('full_text'),
            "author": user_core.get('screen_name'),
            "author_name": user_core.get('name'),
            "created_at": legacy.get('created_at'),
            "like_count": legacy.get('favorite_count'),
            "retweet_count": legacy.get('retweet_count'),
            "reply_count": legacy.get('reply_count'),
        }

    async def _test_authentication(self, client: Client) -> Dict[str, Any]:
        """Test authentication and return user info"""
        # Fetch current user info (no id argument)
        user = await client.user()
        return {
            "authenticated": True,
            "user": {
                "id": user.id,
                "username": user.screen_name,
                "name": user.name,
                "followers_count": user.followers_count,
                "following_count": user.following_count,
                "tweet_count": user.statuses_count,
                "verified": user.verified
            }
        }

    async def _post_tweet(self, client: Client, text: str) -> Dict[str, Any]:
        """Post a tweet"""
        tweet = await client.create_tweet(text=text)
        return {
            "id": tweet.id,
            "text": tweet.text,
            "created_at": str(tweet.created_at),
            "author": tweet.user.screen_name
        }

    async def _get_user_info(self, client: Client, username: str) -> Dict[str, Any]:
        """Get user information"""
        user = await client.get_user_by_screen_name(username)
        return {
            "id": user.id,
            "username": user.screen_name,
            "name": user.name,
            "description": user.description,
            "followers_count": user.followers_count,
            "following_count": user.following_count,
            "tweet_count": user.statuses_count,
            "verified": user.verified,
            "created_at": str(user.created_at)
        }

    async def _get_tweet_by_id(self, client: Client, tweet_input: str) -> Dict[str, Any]:
        """Get a specific tweet by ID (accepts URLs or plain IDs)"""
        try:
            # Parse the input to extract the tweet ID
            tweet_id = self._parse_tweet_id(tweet_input)

            # Log for debugging (will appear in error log)
            import sys
            print(f"[DEBUG] get_tweet_by_id: input='{tweet_input}' -> extracted_id='{tweet_id}'", file=sys.stderr)

            # Fetch the tweet using the patched get_tweet_by_id
            tweet = await _retry_twitter_call(lambda: client.get_tweet_by_id(tweet_id))

            if not tweet:
                return {
                    "error": f"Tweet not found with ID: {tweet_id}",
                    "original_input": tweet_input,
                    "extracted_id": tweet_id,
                    "note": "Tweet may be deleted, private, or the ID may be invalid"
                }

            return {
                "id": tweet.id,
                "text": tweet.text,
                "author": tweet.user.screen_name,
                "author_name": tweet.user.name,
                "author_id": tweet.user.id,
                "created_at": str(tweet.created_at),
                "like_count": tweet.favorite_count,
                "retweet_count": tweet.retweet_count,
                "reply_count": tweet.reply_count,
                "view_count": getattr(tweet, 'view_count', None),
                "lang": getattr(tweet, 'lang', None),
                "is_quote_status": getattr(tweet, 'is_quote_status', False),
                "possibly_sensitive": getattr(tweet, 'possibly_sensitive', False)
            }
        except Exception as e:
            return {
                "error": f"Failed to retrieve tweet: {str(e)}",
                "tweet_id": tweet_id,
                "error_type": type(e).__name__
            }

    async def _search_tweets(self, client: Client, query: str, count: int = 20, product: str = "Latest") -> List[Dict[str, Any]]:
        """Search for tweets"""
        tweet_id = self._extract_exact_tweet_lookup_id(query)
        if tweet_id is not None:
            tweet = await _retry_twitter_call(lambda: client.get_tweet_by_id(tweet_id))
            if tweet is None:
                return []
            return [
                {
                    "id": tweet.id,
                    "text": tweet.text,
                    "author": tweet.user.screen_name,
                    "author_name": tweet.user.name,
                    "created_at": str(tweet.created_at),
                    "like_count": tweet.favorite_count,
                    "retweet_count": tweet.retweet_count,
                    "reply_count": tweet.reply_count,
                }
            ]

        response = await _retry_twitter_call(
            lambda: _request_search_timeline(client, query, product, count)
        )
        instructions = find_dict(response, 'instructions', find_one=True)
        if not instructions:
            return []

        entries = find_dict(instructions[0], 'entries', find_one=True)
        if not entries:
            return []

        results = []
        for entry in entries[0]:
            tweet_result = self._search_entry_to_result(entry)
            if tweet_result is not None:
                results.append(tweet_result)
        return results

    async def _get_timeline(self, client: Client, count: int = 20) -> List[Dict[str, Any]]:
        """Get timeline tweets"""
        # Use get_timeline() instead of get_home_timeline()
        tweets = await client.get_timeline(count=count)
        return [
            {
                "id": tweet.id,
                "text": tweet.text,
                "author": tweet.user.screen_name,
                "author_name": tweet.user.name,
                "created_at": str(tweet.created_at),
                "like_count": tweet.favorite_count,
                "retweet_count": tweet.retweet_count,
                "reply_count": tweet.reply_count
            }
            for tweet in tweets
        ]

    async def _get_user_tweets(self, client: Client, username: str, count: int = 20) -> List[Dict[str, Any]]:
        """Get tweets from a specific user"""
        user = await client.get_user_by_screen_name(username)
        tweets = await client.get_user_tweets(user.id, tweet_type='Tweets', count=count)
        return [
            {
                "id": tweet.id,
                "text": tweet.text,
                "author": tweet.user.screen_name,
                "author_name": tweet.user.name,
                "created_at": str(tweet.created_at),
                "like_count": tweet.favorite_count,
                "retweet_count": tweet.retweet_count,
                "reply_count": tweet.reply_count
            }
            for tweet in tweets
        ]

    async def _like_tweet(self, client: Client, tweet_id: str) -> Dict[str, Any]:
        """Like a tweet"""
        result = await client.favorite_tweet(tweet_id)
        return {"success": True, "tweet_id": tweet_id}

    async def _retweet(self, client: Client, tweet_id: str) -> Dict[str, Any]:
        """Retweet a tweet"""
        result = await client.retweet(tweet_id)
        return {"success": True, "tweet_id": tweet_id}

    async def _get_latest_timeline(self, client: Client, count: int = 20) -> List[Dict[str, Any]]:
        """Get latest timeline tweets"""
        # Use get_latest_timeline() instead of get_home_timeline()
        tweets = await client.get_latest_timeline(count=count)
        return [
            {
                "id": tweet.id,
                "text": tweet.text,
                "author": tweet.user.screen_name,
                "author_name": tweet.user.name,
                "created_at": str(tweet.created_at),
                "like_count": tweet.favorite_count,
                "retweet_count": tweet.retweet_count,
                "reply_count": tweet.reply_count
            }
            for tweet in tweets
        ]

    async def _send_dm(self, client: Client, recipient_username: str, text: str) -> Dict[str, Any]:
        """Send a direct message to a user"""
        # First get the user_id from the username
        user = await client.get_user_by_screen_name(recipient_username)
        user_id = user.id
        
        result = await client.send_dm(user_id, text)
        return {
            "success": True,
            "recipient_username": recipient_username,
            "recipient_user_id": user_id,
            "text": text,
            "message_id": result.id,
            "created_at": str(result.time)
        }

    async def _get_dm_history(self, client: Client, recipient_username: str, count: int = 20) -> List[Dict[str, Any]]:
        """Get direct message history with a user"""
        # First get the user_id from the username
        user = await client.get_user_by_screen_name(recipient_username)
        user_id = user.id
        
        result = await client.get_dm_history(user_id)
        messages = []
        for i, message in enumerate(result):
            if i >= count:  # Limit to requested count
                break
            messages.append({
                "id": message.id,
                "text": message.text,
                "time": str(message.time),
                "sender_id": getattr(message, 'sender_id', None),
                "recipient_id": getattr(message, 'recipient_id', None),
                "attachment": getattr(message, 'attachment', None)
            })
        return messages

    async def _add_reaction_to_message(self, client: Client, message_id: str, emoji: str, conversation_id: str) -> Dict[str, Any]:
        """Add a reaction (emoji) to a direct message"""
        result = await client.add_reaction_to_message(message_id, conversation_id, emoji)
        return {
            "success": True,
            "message_id": message_id,
            "emoji": emoji,
            "conversation_id": conversation_id
        }

    async def _delete_dm(self, client: Client, message_id: str) -> Dict[str, Any]:
        """Delete a direct message"""
        result = await client.delete_dm(message_id)
        return {
            "success": True,
            "message_id": message_id
        }

    async def _get_tweet_replies(self, client: Client, tweet_input: str, count: int = 20) -> List[Dict[str, Any]]:
        """Get replies to a specific tweet (accepts URLs or plain IDs)"""
        try:
            # Parse the input to extract the tweet ID
            tweet_id = self._parse_tweet_id(tweet_input)

            # Get the tweet by ID, which should include replies
            tweet = await _retry_twitter_call(lambda: client.get_tweet_by_id(tweet_id))
            
            if not tweet:
                return {"error": "Tweet not found"}
            
            replies_data = []
            
            # Check if tweet has replies attribute and it's not None
            if hasattr(tweet, 'replies') and tweet.replies is not None:
                # The replies attribute should be a Result object that we can iterate over
                reply_count = 0
                for reply in tweet.replies:
                    if reply_count >= count:
                        break
                    
                    replies_data.append({
                        "id": reply.id,
                        "text": reply.text,
                        "author_id": reply.user.id,
                        "author_username": reply.user.screen_name,
                        "author_name": reply.user.name,
                        "created_at": reply.created_at,
                        "reply_count": reply.reply_count,
                        "retweet_count": reply.retweet_count,
                        "favorite_count": reply.favorite_count,
                        "in_reply_to": reply.in_reply_to
                    })
                    reply_count += 1
            
            return {
                "original_tweet": {
                    "id": tweet.id,
                    "text": tweet.text,
                    "author": tweet.user.screen_name,
                    "reply_count": tweet.reply_count
                },
                "replies": replies_data,
                "total_replies_retrieved": len(replies_data)
            }
            
        except Exception as e:
            return {"error": f"Failed to get tweet replies: {str(e)}"}

    async def _get_trends(self, client: Client, category: str, count: int) -> List[Dict[str, Any]]:
        """Get trending topics on Twitter"""
        trends = await client.get_trends(category, count)
        return [
            {
                "name": trend.name,
                "tweets_count": trend.tweets_count,
                "domain_context": trend.domain_context,
                "grouped_trends": trend.grouped_trends
            }
            for trend in trends
        ]

    async def run(self):
        """Run the MCP server using stdio or SSE based on environment.

        ENV:
        - TRANSPORT: 'stdio' (default) or 'sse'
        - HOST: interface for SSE (default 127.0.0.1)
        - PORT: port for SSE (default 7781)
        - SSE_ENDPOINT: path for SSE (default /sse)
        """
        transport = os.environ.get("TRANSPORT", os.environ.get("MCP_TRANSPORT", "stdio")).lower()

        init_opts = InitializationOptions(
            server_name="twitter-mcp",
            server_version="1.0.0",
            capabilities=self.server.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={}
            )
        )

        if transport == "sse":
            host = os.environ.get("HOST", "127.0.0.1")
            port = int(os.environ.get("PORT", "7781"))
            sse_endpoint = os.environ.get("SSE_ENDPOINT", "/sse")  # GET path for SSE stream

            # Use the built-in Starlette-based SSE transport provided by mcp
            from starlette.applications import Starlette
            from starlette.routing import Route, Mount
            from starlette.responses import Response
            from mcp.server.sse import SseServerTransport
            import uvicorn

            # POST target for client messages (relative path)
            messages_path = "/messages"
            sse_transport = SseServerTransport(messages_path)

            async def handle_sse(request):
                # Establish SSE connection and run MCP server over the streams
                async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
                    await self.server.run(read_stream, write_stream, init_opts)
                # After connection closes, return an empty response to complete request
                return Response()

            routes = [
                Route(sse_endpoint, endpoint=handle_sse, methods=["GET"]),
                Mount(messages_path, app=sse_transport.handle_post_message),
            ]

            app = Starlette(routes=routes)
            print(f"Twitter MCP server starting (SSE) at http://{host}:{port}{sse_endpoint}")
            # Run the ASGI server; this call does not return until shutdown
            config = uvicorn.Config(app, host=host, port=port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        else:
            # stdio (default)
            from mcp.server.stdio import stdio_server
            print("Twitter MCP server starting (stdio)")
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(read_stream, write_stream, init_opts)

async def main():
    """Main entry point"""
    server = TwitterMCPServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())
