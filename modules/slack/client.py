"""
Thin HTTP client for Slack's Web API.

**Technical honesty note:** same as in `calcom-pro` and `gcal`,
endpoint and payload format is taken from Slack's public
documentation (https://docs.slack.dev/), but **no call from this
module has been tested against a real workspace yet**.

Slack quirk to keep in mind: the Web API almost always responds with
HTTP 200 even when the operation failed — real success is indicated
by the `"ok": true/false` field in the response body, not the status
code. This client translates that into an exception
(`SlackAPIError`) so the rest of the code doesn't have to remember to
check `"ok"` by hand everywhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

DEFAULT_BASE_URL = "https://slack.com/api"


class SlackAPIError(Exception):
    """Generic error calling Slack's Web API.

    Raised both for HTTP errors (status >= 400) and for HTTP 200
    responses with `"ok": false` in the body — both cases mean the
    operation didn't complete.
    """

    def __init__(self, error_code: str, response_body=None):
        self.error_code = error_code
        self.response_body = response_body
        super().__init__(f"Slack API error: {error_code}")


@dataclass
class SlackClient:
    bot_token: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = 15

    @classmethod
    def from_env(cls, base_url: Optional[str] = None):
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            raise ValueError(
                "SLACK_BOT_TOKEN is not set in the environment. "
                "Copy fika-sync/.env.example to .env and fill in the value "
                "with the bot token from a TEST Slack app."
            )
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        return cls(bot_token=bot_token, **kwargs)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def post(self, method: str, json_body: Optional[dict] = None) -> dict:
        """Calls a Web API method (e.g. 'chat.postMessage').

        Args:
            method: name of the Slack method, without a leading slash.
            json_body: payload to send.

        Returns:
            The already-parsed response body, if "ok" is True.

        Raises:
            SlackAPIError: if the HTTP status is >= 400, or if the
                body has `"ok": false`.
        """
        url = f"{self.base_url}/{method}"
        response = requests.post(
            url, headers=self._headers(), json=json_body, timeout=self.timeout_seconds
        )
        if response.status_code >= 400:
            raise SlackAPIError(f"http_{response.status_code}", response.text)

        body = response.json()
        if not body.get("ok", False):
            raise SlackAPIError(body.get("error", "unknown_error"), response_body=body)

        return body
