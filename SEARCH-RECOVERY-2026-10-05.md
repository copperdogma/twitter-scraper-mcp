# Story: Restore authenticated search bundle discovery

Status: Done (deployed connector verified; parent-context verification pending)
Date: 2026-10-05

Cam authorized diagnosis, scoped repair, regression tests, push to main, deployment
of the existing connector, and public OpenAI/OpenAIDevs search/thread validation.

## Findings and work log

- Live cloud search reproduced `Could not locate X search bundle URL` with
  `isError: false`; direct tweet lookup was a separate, working path.
- Public unauthenticated search redirected to `/i/jf/onboarding/web` and served
  an `x-web` logged-out bundle. The existing authenticated client received the
  responsive-web `main` bundle containing the current SearchTimeline query id.
- Twikit's static SearchTimeline endpoint returned 404. Retained the established
  dynamic query-id/POST implementation and reused the existing authenticated HTTP
  session for discovery. No credentials, account grants, security settings,
  challenge handling, or transaction-header logic changed.
- Added tests for authenticated session reuse, cache hit/expiry, logged-out page,
  missing operation, HTTP and GraphQL errors, malformed responses, and MCP error
  flags. Existing suite plus new coverage: 40 passed (dependency deprecations).
- Source-level live Latest/count30 searches returned 3 OpenAI and 1 OpenAIDevs
  posts for `since:2026-10-04`. OpenAI post 2107164653147340988 detail and reply
  tools returned without errors. A validation script's cleanup then referenced
  an incorrect attribute; it did not affect the successful retrieval assertions.
- Existing remote only has `master`; the explicitly requested `main` is created
  for this repair without altering repository settings or the old remote branch.

## Deployment and rollback

Existing owner: `com.mcp.twitter`, Python `.venv/bin/python server.py` in this
checkout, existing SSE listener 7781. Deploy by restarting only this owner:
`launchctl kickstart -k gui/$(id -u)/com.mcp.twitter`.

Rollback baseline: `0f15f0e08565cf932abe3e7549ee89c2da27ea0d`. Revert this repair
commit and kickstart the same owner; no dependency/configuration rollback needed.

## Deletion test

Remove custom query discovery when the installed twikit SearchTimeline endpoint
passes the two targeted account searches and supported thread retrieval against
current X. A native connector with equivalent verified results can replace the
retained service through the existing Bishop migration decision process.

## Independent cloud verification

- `twitter_scraper_search_tweets(query="from:OpenAI since:2026-10-04", product="Latest", count=30)`
- `twitter_scraper_search_tweets(query="from:OpenAIDevs since:2026-10-04", product="Latest", count=30)`
- `twitter_scraper_search_tweets(query="https://x.com/OpenAI/status/2107164653147340988", product="Latest", count=1)`
- `twitter_scraper_get_tweet_replies(tweet_id="2107164653147340988", count=3)`

Require `isError: false`, parseable results, correct authors, and reply/thread
structure. Local tests/push alone do not establish connector success.

## Deployed verification

- Restarted only the existing `com.mcp.twitter` LaunchAgent successfully.
- Fresh calls through the installed cloud Twitter Scraper connector returned
  3 OpenAI and 1 OpenAIDevs posts for the original Latest/count30 queries, with
  the requested authors and `isError: false`.
- Fresh cloud reply retrieval for 2107164653147340988 returned matching
  original tweet id and 3 replies, `isError: false`.
- Parent cloud Bishop should repeat the independent calls above in its own
  conversation to verify access from that context.

## Follow-up: complete long-post text

- Parent independently verified the first deployed search/thread repair, then
  identified that legacy previews were truncated mid-sentence.
- Existing TweetDetail payloads already contain full `note_tweet` bodies:
  2107164653147340988 is 482 characters versus 275 legacy characters;
  2107164650249101695 is 639 versus 279. No additional endpoint or grant needed.
- Read-only object serializers now use twikit's existing `Tweet.full_text`
  property; raw search results prefer `note_tweet_results.result.text` and
  fall back to `legacy.full_text` for ordinary posts.
- Added regression coverage for notes, ordinary/empty-note fallbacks, exact
  ID/URL lookup, detail, original thread text, and reply text. Suite: 44 passed.
- Restarted only `com.mcp.twitter`. Fresh cloud search returned bodies of
  482, 619, and 639 characters. Exact URL lookup and thread-original retrieval
  for both targeted long posts matched search text byte-for-byte, returned
  482/639 characters, and retrieved 3 replies each with `isError: false`.
- This verifies the returned long-post bodies and bounded reply results; it
  does not claim exhaustive pagination of every reply in an X conversation.

## Branch and storage implications

- Remote HEAD/default is still `master` at the original rollback baseline.
  It was not changed. Repair branch `main` is tracked locally against
  `origin/main`; launchd executes this checkout directly. There is no branch
  switch in the LaunchAgent. A default clone still selects old `master`:
  explicitly clone/checkout `main` to recover this repair.
- Temporary helper/test/record/scan files were created only under `/tmp`;
  six small files used 28 KiB allocated and were removed after use. Scanner
  temporary snapshots were automatically removed. No dependency installation,
  build cache, service configuration, or unrelated file cleanup was performed.
- Existing Python bytecode was updated by initial tests/imports; subsequent
  tests disabled bytecode creation and pytest caching. Low free disk space
  predates the repair and remains an independent operational issue.
