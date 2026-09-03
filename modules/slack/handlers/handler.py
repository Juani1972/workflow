"""Handlers for the your-handle/slack module.

VALIDATED (29 Aug 2026) against Slack's current official Web API
documentation (docs.slack.dev/reference/methods, api.slack.com/methods):

  - Base URL: https://slack.com/api
  - POST /chat.postMessage        -- message to a channel or conversation
  - POST /conversations.open      -- opens/gets the DM channel with a user
                                      (necessary before sending a real DM;
                                      chat.postMessage with a user's channel
                                      isn't the recommended pattern)
  - Auth: Bearer token (bot token, xoxb-...) in the Authorization header,
    NOT as a query parameter (that was the legacy pattern).
  - Responses: Slack returns HTTP 200 even on logical errors, with
    {"ok": false, "error": "..."} in the body -- do NOT rely only on
    resp.raise_for_status(), the "ok" field must be checked explicitly.
    This is different from Cal.com/Google, which use HTTP codes for errors.

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
"""
import os
import requests

BASE_URL = "https://slack.com/api"


def _headers() -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "SLACK_BOT_TOKEN is not configured. In production this is "
            "injected via RailCall Studio > Integrations (OAuth2), never "
            "hardcoded."
        )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}


def _call(method: str, body: dict) -> dict:
    """Slack returns 200 OK even when the call failed logically
    (invalid channel, token without scope, etc.) -- the "ok" field is
    the only source of truth, not the HTTP status code."""
    resp = requests.post(f"{BASE_URL}/{method}", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()  # this only catches genuine HTTP errors (5xx, etc.)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error on {method}: {data.get('error', 'unknown_error')}")
    return data


def post_message(inputs: dict, context: dict) -> dict:
    """POST /chat.postMessage to a public/private channel."""
    body = {"channel": inputs["channel"], "text": inputs["text"]}
    if inputs.get("blocks"):
        body["blocks"] = inputs["blocks"]
    return _call("chat.postMessage", body)


def post_message_with_buttons(inputs: dict, context: dict) -> dict:
    """Builds a Block Kit message with action buttons (e.g. Approve/
    Modify/Reject) and publishes it via chat.postMessage. `buttons` is a
    list of {label, action_id, style?}; style can be 'primary'|'danger'
    or absent (neutral)."""
    elements = []
    for b in inputs["buttons"]:
        btn = {
            "type": "button",
            "text": {"type": "plain_text", "text": b["label"]},
            "action_id": b["action_id"],
        }
        if b.get("style"):
            btn["style"] = b["style"]
        elements.append(btn)
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": inputs["text"]}},
        {"type": "actions", "elements": elements},
    ]
    body = {"channel": inputs["channel"], "text": inputs["text"], "blocks": blocks}
    return _call("chat.postMessage", body)


def post_dm(inputs: dict, context: dict) -> dict:
    """Sends a direct message. First opens/gets the DM channel via
    conversations.open (the pattern Slack recommends instead of assuming
    a user ID works directly as a channel in chat.postMessage)."""
    opened = _call("conversations.open", {"users": inputs["user_id"]})
    channel_id = opened["channel"]["id"]
    return _call("chat.postMessage", {"channel": channel_id, "text": inputs["text"]})
