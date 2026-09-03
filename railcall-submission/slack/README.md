# slack — Slack messaging for RailCall

## What it does

Two commands against the real [Slack Web API](https://docs.slack.dev/):

- **`list_channels`** — channels the bot can see, so a workflow (or a person configuring one) can find a `channel_id` by name.
- **`post_message`** — post a message to a channel.

## Who it's for

Small teams whose AI agent or RailCall workflow needs to notify a channel — a team-health summary, an alert, a status update — under RailCall's preview → approve → execute → signed-receipt discipline, instead of a bare `chat.postMessage` call with no audit trail.

Concrete use case: a scheduled workflow computes a weekly team-load summary and posts it to `#team-health` — a human sees the exact message text in the airlock preview before it goes out, because `post_message` is `side_effects: "external"`.

## Install

```bash
railcall market install juani1972/slack
```

Set a Slack bot token in Studio → Integrations. Create one at [api.slack.com/apps](https://api.slack.com/apps) → OAuth & Permissions → add the `chat:write` scope → Install to Workspace → copy the Bot User OAuth Token (`xoxb-...`).

## Example

```bash
railcall airlock stage post_message --inputs '{"channel": "#fika-sync", "text": "Weekly summary: 2 people overloaded this week."}'
railcall airlock approve <staging_id>
```

Expected output:

```json
{"channel": "C0123ABCD", "ts": "1735689600.123456"}
```

## Credentials needed

- A Slack bot token (`xoxb-...`) with the `chat:write` scope, set via
  Studio → Integrations. Slack bot tokens don't expire by default, so
  — unlike the OAuth-based `juani1972/gcal` and `juani1972/sheets`
  modules — there's no token-refresh caveat here.

## Known limitations

- **`list_channels` doesn't paginate.** Slack caps a single call at
  ~1000 channels; workspaces with more than that need a follow-up
  call using the `cursor` Slack returns, which this first version
  doesn't implement.
- **No support for Block Kit** — `post_message` only sends plain
  `text`, not the richer `blocks` format. Kept intentionally simple
  for this first version; Block Kit support (buttons, formatted
  sections) is the natural next command to add.
- **HTTP 200 with `"ok": false` is handled explicitly** — Slack's Web
  API returns success-looking HTTP status codes even when the call
  failed (wrong channel, missing scope, revoked token). `_request()`
  checks the `"ok"` field and raises `SlackError` either way, so a
  failed post never gets reported as a success in the receipt.
- **Not yet run against a real Station install** — no network route
  to `railcall.ai` from this environment. Verified instead: 8 unit
  tests with `urllib.urlopen` mocked (`tests/test_handler.py`),
  including the `ok:false`-despite-HTTP-200 case specifically.
  Function naming is `_h_<name>`, confirmed by the [Publisher
  FAQ](https://railcall.ai/docs/marketplace-developer/faq/)
  rejection-reason list — not a guess. `vault_get("slack")` returns
  `{"bot_token": "..."}` (falls back to `"api_key"`), also confirmed
  there.
- `module.json` declares a sandbox `requires` block
  (`network: ["slack.com"]`, no subprocess, no filesystem writes) —
  opt-in since Station v0.33+, not yet tested against a real
  Station's enforcement.

## Source

Standard library only (`urllib.request`, `json`) — no external
dependencies. ~110 lines across `module.json` + `handlers/handler.py`.
