"""
Tests for slack.

- `post_message` is tested with the HTTP layer mocked — no real call,
  no real token.
- `build_summary_blocks`, `verify_slack_signature`,
  `parse_slash_command` and `parse_interactive_payload` are pure logic
  and are tested directly, without mocks. `verify_slack_signature` in
  particular has this module's most important coverage: it's the only
  thing preventing someone from forging a click on "Adjust my
  threshold".

**`post_message` has not been tested against a real Slack workspace**
(see README.md).
"""

import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import SlackClient, SlackAPIError
from actions import (
    post_message,
    build_summary_blocks,
    verify_slack_signature,
    parse_slash_command,
    parse_interactive_payload,
)


def make_client():
    return SlackClient(bot_token="xoxb-test-dummy-token")


def mock_response(status_code=200, json_data=None, text_data=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text_data
    return resp


# ---------------------------------------------------------------------------
# post_message (mocked)
# ---------------------------------------------------------------------------

@patch("client.requests.post")
def test_post_message_sends_text_and_blocks(mock_post):
    mock_post.return_value = mock_response(json_data={"ok": True, "ts": "12345.6789"})

    client = make_client()
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
    result = post_message(client, "#fika-sync", "Weekly summary", blocks=blocks)

    assert result["ok"] is True
    sent_json = mock_post.call_args.kwargs["json"]
    assert sent_json["channel"] == "#fika-sync"
    assert sent_json["text"] == "Weekly summary"
    assert sent_json["blocks"] == blocks


@patch("client.requests.post")
def test_post_message_raises_on_ok_false_even_with_http_200(mock_post):
    """Slack returns HTTP 200 even when the operation failed."""
    mock_post.return_value = mock_response(
        status_code=200, json_data={"ok": False, "error": "channel_not_found"}
    )

    client = make_client()
    with pytest.raises(SlackAPIError) as exc_info:
        post_message(client, "#nonexistent-channel", "hi")

    assert exc_info.value.error_code == "channel_not_found"


def test_client_from_env_requires_bot_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with pytest.raises(ValueError):
        SlackClient.from_env()


# ---------------------------------------------------------------------------
# build_summary_blocks (pure logic)
# ---------------------------------------------------------------------------

def test_build_summary_blocks_includes_report_text():
    blocks = build_summary_blocks("*Weekly summary*\n🔴 ana", people=[])
    assert blocks[0]["text"]["text"] == "*Weekly summary*\n🔴 ana"


def test_build_summary_blocks_adds_one_button_per_person():
    blocks = build_summary_blocks("report", people=["ana", "beto"])
    action_block = next(b for b in blocks if b["type"] == "actions")
    values = [el["value"] for el in action_block["elements"]]
    assert values == ["ana", "beto"]
    assert all(el["action_id"] == "adjust_threshold" for el in action_block["elements"])


def test_build_summary_blocks_no_actions_block_when_no_people():
    blocks = build_summary_blocks("report", people=[])
    assert not any(b["type"] == "actions" for b in blocks)


# ---------------------------------------------------------------------------
# verify_slack_signature (pure logic, security)
# ---------------------------------------------------------------------------

def _sign(secret, timestamp, body):
    base_string = f"v0:{timestamp}:{body}"
    digest = hmac.new(secret.encode(), base_string.encode(), hashlib.sha256).hexdigest()
    return f"v0={digest}"


def test_verify_slack_signature_accepts_valid_signature():
    secret = "shh-secret"
    timestamp = "1000000000"
    body = "command=/fika-check&text=&user_id=U123"
    signature = _sign(secret, timestamp, body)

    assert verify_slack_signature(
        secret, timestamp, body, signature, current_time=1000000010
    ) is True


def test_verify_slack_signature_rejects_wrong_signature():
    secret = "shh-secret"
    timestamp = "1000000000"
    body = "command=/fika-check"

    assert verify_slack_signature(
        secret, timestamp, body, "v0=made-up-signature", current_time=1000000010
    ) is False


def test_verify_slack_signature_rejects_tampered_body():
    secret = "shh-secret"
    timestamp = "1000000000"
    original_body = "command=/fika-check"
    signature = _sign(secret, timestamp, original_body)

    tampered_body = "command=/fika-check&extra=malicious"

    assert verify_slack_signature(
        secret, timestamp, tampered_body, signature, current_time=1000000010
    ) is False


def test_verify_slack_signature_rejects_replayed_old_request():
    secret = "shh-secret"
    timestamp = "1000000000"
    body = "command=/fika-check"
    signature = _sign(secret, timestamp, body)

    # 10 minutes later: older than MAX_REQUEST_AGE_SECONDS (5 min)
    assert verify_slack_signature(
        secret, timestamp, body, signature, current_time=1000000000 + 600
    ) is False


def test_verify_slack_signature_rejects_malformed_timestamp():
    assert verify_slack_signature(
        "secret", "not-a-number", "body", "v0=whatever", current_time=1000
    ) is False


# ---------------------------------------------------------------------------
# parse_slash_command (pure logic)
# ---------------------------------------------------------------------------

def test_parse_slash_command_extracts_fields():
    raw_body = "command=%2Ffika-check&text=&user_id=U123&channel_id=C456"
    result = parse_slash_command(raw_body)

    assert result == {
        "command": "/fika-check",
        "text": "",
        "user_id": "U123",
        "channel_id": "C456",
    }


def test_parse_slash_command_missing_fields_default_to_empty_string():
    result = parse_slash_command("command=%2Ffika-check")
    assert result["user_id"] == ""
    assert result["channel_id"] == ""


# ---------------------------------------------------------------------------
# parse_interactive_payload (pure logic)
# ---------------------------------------------------------------------------

def test_parse_interactive_payload_extracts_action_and_person():
    payload = {
        "user": {"id": "U789"},
        "actions": [{"action_id": "adjust_threshold", "value": "ana"}],
    }
    raw_body = "payload=" + json.dumps(payload)

    result = parse_interactive_payload(raw_body)

    assert result == {
        "action_id": "adjust_threshold",
        "person": "ana",
        "clicked_by_user_id": "U789",
    }


def test_parse_interactive_payload_raises_without_payload_field():
    with pytest.raises(ValueError):
        parse_interactive_payload("some_other_field=1")


def test_parse_interactive_payload_handles_no_actions():
    payload = {"user": {"id": "U789"}, "actions": []}
    raw_body = "payload=" + json.dumps(payload)

    result = parse_interactive_payload(raw_body)

    assert result["action_id"] is None
    assert result["person"] is None
