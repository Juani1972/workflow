# slack

Integrates Fika Sync with [Slack's Web API](https://docs.slack.dev/)
to publish the weekly/daily summary with interactive buttons, and to
verify and parse incoming `/fika-check` requests and clicks on
"Adjust my threshold".

## ⚠️ Status: mostly pure logic, a single real call not yet validated

Unlike `calcom-pro` and `gcal`, most of this module **makes no
network calls**:

| Function | Type | Status |
|---|---|---|
| `post_message` | Calls the real API | Written, **not tested against a real workspace** |
| `build_summary_blocks` | Pure logic | Tested without mocks, trustworthy |
| `verify_slack_signature` | Pure logic | Tested without mocks, trustworthy |
| `parse_slash_command` | Pure logic | Tested without mocks, trustworthy |
| `parse_interactive_payload` | Pure logic | Tested without mocks, trustworthy |

**16/16 tests passing**: 3 mock `post_message`, the other 13 test
pure logic directly. `verify_slack_signature` is the whole module's
most important function — it's the only barrier against someone
forging a click on "Adjust my threshold" or triggering `/fika-check`
without actually being Slack.

## Installation

```bash
cd modules/slack
pip install -r requirements.txt --break-system-packages   # or in your venv
```

## Configuration

- `SLACK_BOT_TOKEN` — to publish messages (`chat.postMessage`).
- `SLACK_SIGNING_SECRET` — to verify incoming requests
  (`/fika-check`, button clicks) genuinely come from Slack.

See `fika-sync/.env.example`. Both are obtained by creating an app at
`https://api.slack.com/apps` — **use a test workspace**.

## Actions

| Action | Used in workflow.csv by |
|---|---|
| `post_message(client, channel, text, blocks=None)` | `publish_slack_summary` |
| `build_summary_blocks(report_text, people)` | Builds `post_message`'s input from `team_health_analyzer.summarize_team_report`'s text |
| `verify_slack_signature(signing_secret, timestamp, raw_body, signature, current_time=None)` | `update_threshold` (verifies the click before applying the threshold change) |
| `parse_slash_command(raw_body)` | `trigger_slack_command` |
| `parse_interactive_payload(raw_body)` | `update_threshold` (extracts which person and which button) |

## Usage example

```python
from client import SlackClient
from actions import post_message, build_summary_blocks, verify_slack_signature

client = SlackClient.from_env()

report_text = "*Weekly summary*\n🔴 *ana* — 22.00h..."
blocks = build_summary_blocks(report_text, people=["ana", "beto"])

post_message(client, "#fika-sync", text="Fika Sync weekly summary", blocks=blocks)
```

Verify a click on "Adjust my threshold" (this is what RailCall would
do when receiving Slack's interactivity webhook, before calling
`update_threshold`):

```python
import os
from actions import verify_slack_signature, parse_interactive_payload

is_valid = verify_slack_signature(
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
    timestamp=request.headers["X-Slack-Request-Timestamp"],
    raw_body=request.raw_body,
    signature=request.headers["X-Slack-Signature"],
)

if not is_valid:
    raise PermissionError("Invalid Slack signature — possible forged request.")

interaction = parse_interactive_payload(request.raw_body)
# interaction = {"action_id": "adjust_threshold", "person": "ana", "clicked_by_user_id": "U123"}
```

## Before using this in a real demo

1. Create a Slack app in a test workspace, with `chat:write`
   permissions and the signing secret enabled.
2. Run `post_message` against a real channel in that workspace and
   confirm the `blocks` format (with the "Adjust my threshold"
   button) looks right in the Slack client.
3. Configure the app's interactivity endpoint to point wherever
   RailCall runs, and confirm live that `verify_slack_signature`
   accepts Slack's real requests (the current tests use hand-built
   signatures, not real Slack signatures — they should match per the
   documentation, but it's worth confirming).
4. Test the full `/fika-check` flow: Slack → RailCall →
   `parse_slash_command` → triggers the workflow.
5. Update this README with the findings.

## Tests

```bash
cd modules/slack
python3 -m pytest tests/test_actions.py -v      # unit tests, with mocks, always run
python3 -m pytest tests/test_integration.py -v  # against a real workspace, see VALIDATION.md at the root
```

Current status: **16/16 unit tests passing** (verified on 2026-08-29;
3 with `post_message` mocks, 13 pure logic without mocks).
Integration tests are written but not run — see `VALIDATION.md` at
the repo root.
