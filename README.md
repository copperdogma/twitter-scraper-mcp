# Twitter MCP Server

A Model Context Protocol (MCP) server that provides Twitter functionality using the `twikit` library. This server now uses implicit, environment-based authentication: credentials are read from a local `.env` file and applied automatically to every tool call.

## Features

- **Implicit Auth (via .env)**: Set `TWITTER_CT0` and `TWITTER_AUTH_TOKEN` in `.env` and all tools will authenticate automatically. Do not pass cookies in tool calls.
- **Session Caching**: Automatically caches authenticated sessions for efficiency  
- **Timeline Access**: Get tweets from your timeline
- **User Information**: Retrieve user profiles and statistics
- **Tweet Search**: Search for tweets with specific queries
- **Tweet Management**: Post, like, and retweet tweets
- **User Tweets**: Get tweets from specific users
- **Direct Messaging**: Send DMs, get DM history, react to messages, and delete messages
- **Authentication Testing**: Deprecated explicit tool; see below for current behavior
- **Tweet Operations**: Post tweets, like/unlike tweets, retweet/delete retweets, bookmark tweets
- **Tweet Retrieval**: Get tweets by ID, search tweets, get user timelines, get tweet replies
- **User Operations**: Follow/unfollow users, get user information, search users
- **Trending Topics**: Get trending topics across different categories (trending, news, sports, entertainment, for-you)

## Disclaimer

**This project utilizes an unofficial API to interact with X (formerly Twitter) through the `twikit` library. The methods employed for authentication and data retrieval are not officially endorsed by X/Twitter and may be subject to change or discontinuation without notice.**

**This tool is intended for educational and experimental purposes only. Users should be aware of the potential risks associated with using unofficial APIs, including but not limited to account restrictions or suspension. The developers of this project are not responsible for any misuse or consequences arising from the use of this tool.**

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd twitter-mcp
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the server:
```bash
python server.py
```

## Authentication

This server authenticates using environment variables only. Set them in `twitter-scraper-mcp/.env`:

Environment variable names:

```
TWITTER_CT0=your_ct0_cookie
TWITTER_AUTH_TOKEN=your_auth_token_cookie
```

### Getting Twitter Cookies

To obtain your cookies:

1. Open your browser and go to Twitter/X
2. Log in to your account
3. Open Developer Tools (F12)
4. Go to Application/Storage → Cookies → twitter.com (or x.com)
5. Find and copy these cookie values:
   - `ct0` - CSRF token cookie
   - `auth_token` - Authentication token cookie

Both cookies are required for all operations.

## Usage

### Available Tools

Note: Do not pass `ct0` or `auth_token` in any tool arguments. Credentials are applied automatically from the `.env` file.

Authentication tool deprecation: Calling `authenticate` returns a deprecation message since auth is implicit.

#### 2. Tweet
Post a new tweet:
```json
{
  "tool": "tweet",
  "arguments": {
    "text": "Hello from MCP! 🚀"
  }
}
```

#### 3. Get User Info
Get information about a Twitter user:
```json
{
  "tool": "get_user_info",
  "arguments": {
    "username": "elonmusk"
  }
}
```

#### 4. Search Tweets
Search for tweets:
```json
{
  "tool": "search_tweets",
  "arguments": {
    "query": "artificial intelligence",
    "count": 10
  }
}
```

#### 5. Get Timeline
Get tweets from your timeline:
```json
{
  "tool": "get_timeline",
  "arguments": {
    "count": 20
  }
}
```

#### 6. Like Tweet
Like a tweet by ID:
```json
{
  "tool": "like_tweet",
  "arguments": {
    "tweet_id": "1234567890123456789"
  }
}
```

#### 7. Retweet
Retweet a tweet by ID:
```json
{
  "tool": "retweet",
  "arguments": {
    "tweet_id": "1234567890123456789"
  }
}
```

#### 8. Send Direct Message
Send a direct message to a user.

**Parameters:**
- `recipient_username` (string): The username (without @) to send the message to (automatically converted to user_id internally)
- `text` (string): The message content

```json
{
  "name": "send_dm",
  "arguments": {
    "recipient_username": "username",
    "text": "Hello from MCP!"
  }
}
```

#### 9. Get DM History
Get direct message history with a specific user.

**Parameters:**
- `recipient_username` (string): The username (without @) to get DM history with (automatically converted to user_id internally)
- `count` (integer, optional): Number of messages to retrieve (default: 20, max: 100)

```json
{
  "name": "get_dm_history", 
  "arguments": {
    "recipient_username": "username",
    "count": 50
  }
}
```

#### 10. React to Direct Message
Add an emoji reaction to a direct message.

**Parameters:**
- `message_id` (string): The ID of the message to react to
- `emoji` (string): The emoji to add (e.g., "👍", "❤️", "😀")
- `conversation_id` (string): The conversation ID containing the message

```json
{
  "name": "add_reaction_to_message",
  "arguments": {
    "message_id": "message_id_here", 
    "emoji": "👍",
    "conversation_id": "conversation_id_here"
  }
}
```

#### 11. Delete Direct Message
Delete a direct message:
```json
{
  "tool": "delete_dm",
  "arguments": {
    "message_id": "1234567890123456789"
  }
}
```

#### **get_tweet_replies**
Get replies to a specific tweet.

**Parameters:**
- `tweet_id` (string): The ID of the tweet to get replies for
- `count` (integer, optional): Number of replies to retrieve (default: 20)

```json
{
  "name": "get_tweet_replies",
  "arguments": {
    "tweet_id": "1234567890",
    "count": 10
  }
}
```

#### **get_trends**
Get trending topics on Twitter.

**Parameters:**
- `category` (string, optional): The category of trends to retrieve (default: "trending")
  - Options: `"trending"`, `"for-you"`, `"news"`, `"sports"`, `"entertainment"`
- `count` (integer, optional): Number of trends to retrieve (default: 20, max: 50)

```json
{
  "name": "get_trends",
  "arguments": {
    "category": "trending",
    "count": 20
  }
}
```

**Examples:**
```json
// Get general trending topics
{
  "name": "get_trends",
  "arguments": {}
}

// Get sports trends
{
  "name": "get_trends", 
  "arguments": {
    "category": "sports",
    "count": 10
  }
}

// Get personalized trends
{
  "name": "get_trends",
  "arguments": {
    "category": "for-you"
  }
}
```

### Available Resources

Resources remain available and use the same implicit authentication from `.env`.

## Notes

- Do not include cookies in tool calls; they are ignored.
- The `authenticate` tool is deprecated and returns a guidance message.
- Credentials are applied automatically on each call; updates to `.env` are detected at runtime.
