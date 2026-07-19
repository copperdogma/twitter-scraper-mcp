# Xquik Companion MCP Setup

This project stays focused on a local, read-only Twitter MCP server backed by
environment cookies. When you need a reviewed API-backed X/Twitter workflow,
add Xquik as a separate remote MCP server instead of putting API keys or
customer exports into this repo.

Xquik is an independent third-party service. Not affiliated with X Corp.
"Twitter" and "X" are trademarks of X Corp.

Use `mcp_config.xquik.example.json` as a starting point:

```json
{
  "mcpServers": {
    "twitter": {
      "command": "python3",
      "args": ["server.py"],
      "env": {
        "TWITTER_AUTH_TOKEN": "${TWITTER_AUTH_TOKEN}",
        "TWITTER_CT0": "${TWITTER_CT0}"
      }
    },
    "xquik": {
      "url": "https://xquik.com/mcp",
      "headers": {
        "x-api-key": "${XQUIK_API_KEY}"
      }
    }
  }
}
```

Use the local `twitter` server for account-scoped read-only experiments. Use
the remote `xquik` server when an agent needs reviewed X/Twitter search,
profile, monitor, webhook, or export workflows that should stay separate from
browser cookie material.

Keep `XQUIK_API_KEY`, `TWITTER_AUTH_TOKEN`, and `TWITTER_CT0` in a local `.env`
or secret store. Never paste them into issues, prompts, screenshots, test
fixtures, or committed config files.

See the [Xquik MCP guide](https://docs.xquik.com/mcp/overview) for current
client setup and OAuth options.
