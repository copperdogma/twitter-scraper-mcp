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

# Load environment variables
load_dotenv()

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
                result = await self._get_tweet_replies(client, arguments["tweet_id"], count)
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
                description="Search for tweets with a specific query",
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
                description="Get replies to a specific tweet",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "tweet_id": {"type": "string", "description": "The ID of the tweet to get replies for"},
                        "count": {"type": "integer", "description": "Number of replies to retrieve (default: 20)", "default": 20}
                    },
                    "required": ["tweet_id"]
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
        """Ensure a single authenticated client using env credentials; reuse if unchanged."""
        async with self._client_lock:
            creds: Tuple[str, str] = (ct0, auth_token)
            if self.client is not None and self._last_credentials == creds:
                return self.client
            client = Client('en-US')
            cookies = {'ct0': ct0, 'auth_token': auth_token}
            client.set_cookies(cookies)
            try:
                # Validate authentication by attempting to fetch the current user id
                _ = await client.user_id()
            except Exception as e:
                raise ValueError(f"Authentication failed with provided cookies: {str(e)}")
            self.client = client
            self._last_credentials = creds
            return client

    async def _get_authenticated_client(self, ct0: str, auth_token: str) -> Client:
        """Compatibility wrapper to ensure a client; uses env creds path."""
        return await self._ensure_client(ct0, auth_token)

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

    async def _search_tweets(self, client: Client, query: str, count: int = 20, product: str = "Latest") -> List[Dict[str, Any]]:
        """Search for tweets"""
        tweets = await client.search_tweet(query, product=product, count=count)
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

    async def _get_tweet_replies(self, client: Client, tweet_id: str, count: int = 20) -> List[Dict[str, Any]]:
        """Get replies to a specific tweet"""
        try:
            # Get the tweet by ID, which should include replies
            tweet = await client.get_tweet_by_id(tweet_id)
            
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
