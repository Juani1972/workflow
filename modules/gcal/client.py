"""
Thin HTTP client for the Google Calendar v3 API.

**Technical honesty note:** same as in `calcom-pro`, endpoint,
header and payload format is taken from Google Calendar API v3's
public documentation
(https://developers.google.com/workspace/calendar/api/v3/reference),
but **no call from this module has been tested against a real
Google Calendar account yet**.

Key difference from Cal.com: Google uses OAuth 2.0 with a refresh
token, not a simple API key. This client exchanges
`GOOGLE_REFRESH_TOKEN` for a new access token every time it's
instantiated via `from_env()` — it doesn't cache the token between
workflow runs. If Fika Sync ends up running very frequently, this is
a point worth optimizing (caching the access token until it expires,
instead of requesting a new one on every run).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

DEFAULT_BASE_URL = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GCalAPIError(Exception):
    """Generic error calling the Google Calendar API (status >= 400)."""

    def __init__(self, status_code: int, message: str, response_body=None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Google Calendar API error {status_code}: {message}")


@dataclass
class GCalClient:
    access_token: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = 15

    @classmethod
    def from_refresh_token(cls, client_id: str, client_secret: str,
                            refresh_token: str, base_url: Optional[str] = None,
                            token_url: str = TOKEN_URL):
        """Exchanges a refresh token for a new access token.

        See https://developers.google.com/identity/protocols/oauth2/web-server#offline
        """
        response = requests.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if response.status_code >= 400:
            raise GCalAPIError(response.status_code, response.text)

        access_token = response.json()["access_token"]
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        return cls(access_token=access_token, **kwargs)

    @classmethod
    def from_env(cls, base_url: Optional[str] = None):
        """Creates a client reading GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN from the environment."""
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

        missing = [
            name for name, value in [
                ("GOOGLE_CLIENT_ID", client_id),
                ("GOOGLE_CLIENT_SECRET", client_secret),
                ("GOOGLE_REFRESH_TOKEN", refresh_token),
            ] if not value
        ]
        if missing:
            raise ValueError(
                "Missing environment variables for Google Calendar: "
                + ", ".join(missing)
                + ". Copy fika-sync/.env.example to .env and fill in the values "
                "with credentials from a TEST account."
            )
        return cls.from_refresh_token(client_id, client_secret, refresh_token, base_url=base_url)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: Optional[dict] = None):
        return self._request("GET", path, params=params)

    def post(self, path: str, json_body: Optional[dict] = None):
        return self._request("POST", path, json_body=json_body)

    def patch(self, path: str, json_body: Optional[dict] = None):
        return self._request("PATCH", path, json_body=json_body)

    def delete(self, path: str):
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, params=None, json_body=None):
        url = f"{self.base_url}{path}"
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("error", {}).get("message", str(body))
            except ValueError:
                body = response.text
                message = body
            raise GCalAPIError(response.status_code, message, response_body=body)

        if not response.text:
            return {}
        return response.json()
