"""
INTEGRATION tests for slack — calls Slack's real Web API.

Same as calcom-pro and gcal: they do NOT run by default. They're
skipped unless:

  1. RUN_LIVE_TESTS=1
  2. SLACK_BOT_TOKEN is set (bot installed on a TEST workspace).
  3. ALLOW_LIVE_WRITES=1 (posting a message is always a write, so this
     module has no "read-only" integration tests).
  4. SLACK_TEST_CHANNEL with the test channel's ID or name.

How to run them:

    export RUN_LIVE_TESTS=1
    export SLACK_BOT_TOKEN=xoxb-...          # bot on a TEST workspace
    export ALLOW_LIVE_WRITES=1
    export SLACK_TEST_CHANNEL=#fika-sync-test
    cd modules/slack
    python3 -m pytest tests/test_integration.py -v -s

What to check manually afterward:
  - That the message actually appears in the test channel.
  - That the "Adjust my threshold" buttons (Block Kit) look right in
    the Slack client, not just that the API accepted the payload.
  - Click a button manually and confirm in the Slack app's logs that
    the interactivity payload has the shape parse_interactive_payload
    expects.
  - Confirm the real signature: copy the X-Slack-Signature and
    X-Slack-Request-Timestamp headers from a real request (from the
    app's request log at api.slack.com) and run
    verify_slack_signature with those real values — test_actions.py's
    mock-based tests build the signature by hand, they don't verify
    against a signature Slack genuinely generated.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import SlackClient
from actions import post_message, build_summary_blocks


RUN_LIVE = os.environ.get("RUN_LIVE_TESTS") == "1"
HAS_TOKEN = bool(os.environ.get("SLACK_BOT_TOKEN"))
ALLOW_WRITES = os.environ.get("ALLOW_LIVE_WRITES") == "1"
TEST_CHANNEL = os.environ.get("SLACK_TEST_CHANNEL")

skip_writes = pytest.mark.skipif(
    not (RUN_LIVE and HAS_TOKEN and ALLOW_WRITES and TEST_CHANNEL),
    reason=(
        "Set RUN_LIVE_TESTS=1, SLACK_BOT_TOKEN, ALLOW_LIVE_WRITES=1 and "
        "SLACK_TEST_CHANNEL to run this (posts a real message)."
    ),
)


@pytest.fixture
def live_client():
    return SlackClient.from_env()


@skip_writes
def test_live_post_message_with_buttons(live_client, capsys):
    report_text = (
        "*Test weekly summary — Fika Sync*\n"
        "🔴 *ana* — 22.00h of meetings this week\n"
        "🟢 *beto* — 8.00h of meetings this week"
    )
    blocks = build_summary_blocks(report_text, people=["ana", "beto"])

    result = post_message(
        live_client, TEST_CHANNEL,
        text="Fika Sync test weekly summary",
        blocks=blocks,
    )

    assert result["ok"] is True
    with capsys.disabled():
        print(f"\n[slack] Message posted to {TEST_CHANNEL}, ts={result.get('ts')}")
        print(
            "[slack] ⚠️  Manually check in the Slack client that the message and "
            "the buttons look right, and that clicking a button generates an "
            "interactivity payload with the shape parse_interactive_payload expects."
        )
