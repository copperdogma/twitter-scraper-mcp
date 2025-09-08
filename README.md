# Twitter MCP Server

A Model Context Protocol (MCP) server that provides Twitter functionality using the `twikit` library. This server now uses implicit, environment-based authentication: credentials are read from a local `.env` file and applied automatically to every tool call.

## Features

- **Implicit Auth (via .env)**: Set `TWITTER_CT0` and `TWITTER_AUTH_TOKEN` in `.env`; all tools authenticate automatically. Do not pass cookies in tool calls.
- **Read-Only Tools**: get_user_info, search_tweets, get_timeline, get_latest_timeline, get_tweet_replies, get_trends
- **Session Caching**: Automatically caches authenticated sessions for efficiency.
- **Trending Topics**: Get trending topics across different categories (trending, news, sports, entertainment, for-you).

Security hardening: All write/DM capabilities (tweet, like, retweet, send_dm, reactions, delete_dm, DM history) are disabled and not exposed.

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

### Quick Install (macOS LaunchAgent)

One-liner to install and run as a per-user LaunchAgent on port 7781:

```bash
bash -lc 'PORT=7781 LABEL=com.mcp.twitter APP_DIR="$HOME/MCPs/twitter-scraper-mcp" VENV_DIR="$APP_DIR/.venv" PY_BIN="$VENV_DIR/bin/python" PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist" LOG_OUT="$HOME/Library/Logs/${LABEL}.out.log" LOG_ERR="$HOME/Library/Logs/${LABEL}.err.log"; mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"; cd "$APP_DIR"; [ -x "$PY_BIN" ] || python3 -m venv "$VENV_DIR"; "$PY_BIN" -m pip install -U pip >/dev/null; "$PY_BIN" -m pip install -U -r "$APP_DIR/requirements.txt" >/dev/null; cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>${PY_BIN}</string>
    <string>${APP_DIR}/server.py</string>
  </array>
  <key>WorkingDirectory</key><string>${APP_DIR}</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    <key>TRANSPORT</key><string>sse</string>
    <key>HOST</key><string>127.0.0.1</string>
    <key>PORT</key><string>${PORT}</string>
    <key>SSE_ENDPOINT</key><string>/sse</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOG_OUT}</string>
  <key>StandardErrorPath</key><string>${LOG_ERR}</string>
</dict></plist>
PLIST
/usr/bin/plutil -lint "$PLIST"; launchctl bootout gui/"$(id -u)" "$PLIST" 2>/dev/null || true; launchctl bootstrap gui/"$(id -u)" "$PLIST"; launchctl kickstart -kp gui/"$(id -u)"/"${LABEL}"; launchctl print gui/"$(id -u)"/"${LABEL}" | sed -n '1,40p''
```

Quick foreground run (for testing only):

```bash
cd ~/MCPs/twitter-scraper-mcp && python3 -m venv .venv && .venv/bin/python -m pip install -U -r requirements.txt && TRANSPORT=sse HOST=127.0.0.1 PORT=7781 SSE_ENDPOINT=/sse .venv/bin/python server.py
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

<!-- Write/DM tools intentionally omitted for security. -->

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
