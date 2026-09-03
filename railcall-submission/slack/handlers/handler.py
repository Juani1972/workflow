"""Handlers for the juani1972/slack module.

Same pattern as juani1972/calcom-pro and juani1972/gcal: commands are
`_h_<name>` functions (the actual RailCall loader requirement, per
the Publisher FAQ — https://railcall.ai/docs/marketplace-developer/faq/,
"Why did my module get rejected on install?"), credentials come from
`__rc_helpers__["vault_get"]("slack")` returning `{"api_key": "..."}`
(confirmed by the same FAQ, Station v0.29+), bare names below are
aliases for readability only.

Slack bot tokens (`xoxb-...`) don't expire by default, so — unlike
gcal/sheets — there's no refresh-token caveat here.

**A Slack-specific detail worth flagging:** the Web API almost always
responds HTTP 200 even when the call failed — the real result is in
the `"ok"` field of the JSON body. `_request()` below checks that
explicitly; a naive "status == 200 means success" implementation
would silently swallow real failures (wrong channel, missing scope,
revoked token) as if they'd succeeded.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

SLACK_BASE_URL = "https://slack.com/api"


class SlackError(Exception):
    """Raised for any Slack API failure — both HTTP-level errors and
    the "ok": false pattern Slack uses for in-band failures."""


def _vault_bot_token() -> str:
    result = __rc_helpers__["vault_get"]("slack")  # noqa: F821 — injected by the RailCall loader
    if isinstance(result, dict):
        token = result.get("bot_token") or result.get("api_key")
    else:
        token = result
    if not token:
        raise SlackError(
            "No Slack bot token found in the vault. Set it up in "
            "Studio → Integrations → slack before running this command."
        )
    return token


def _request(method: str, path: str, body: dict = None) -> dict:
    url = f"{SLACK_BASE_URL}/{path}"
    headers = {
        "Authorization": f"Bearer {_vault_bot_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise SlackError(f"Slack API returned HTTP {exc.code}: {error_body}") from exc

    # Slack's Web API responds HTTP 200 even on failure — the real
    # result is "ok". Checking status alone would silently treat a
    # failed post as a success.
    if not parsed.get("ok", False):
        raise SlackError(f"Slack API rejected the request: {parsed.get('error', 'unknown_error')}")
    return parsed


# ---------------------------------------------------------------------------
# Commands (must match module.json exactly)
# ---------------------------------------------------------------------------

def _h_list_channels(inputs: dict, context: dict) -> dict:
    """List channels the bot can see.

    inputs: {"limit": int?}
    Returns: {"count": int, "channels": list}
    """
    limit = inputs.get("limit", 100)
    response = _request("GET", f"conversations.list?limit={int(limit)}")
    channels = response.get("channels", [])
    return {"count": len(channels), "channels": channels}


def _h_post_message(inputs: dict, context: dict) -> dict:
    """Post a message to a channel.

    inputs: {"channel": str, "text": str}
    Returns: {"channel": str, "ts": str}
    """
    for field in ("channel", "text"):
        if not inputs.get(field):
            raise SlackError(f"Missing required input: {field}")

    response = _request("POST", "chat.postMessage", body={
        "channel": inputs["channel"],
        "text": inputs["text"],
    })
    return {"channel": response.get("channel"), "ts": response.get("ts")}


# ---------------------------------------------------------------------------
# Bare-name aliases — readability only, not required by the loader
# (which calls the `_h_`-prefixed functions above directly).
# ---------------------------------------------------------------------------

list_channels = _h_list_channels
post_message = _h_post_message
