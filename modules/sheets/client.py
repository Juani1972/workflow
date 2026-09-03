"""
Thin HTTP client for the Google Sheets v4 API.

**Technical honesty note:** same as in `gcal`, endpoint and payload
format is taken from Google Sheets API v4's public documentation
(https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append),
but **no call from this module has been tested against a real
spreadsheet yet**.

Reuses the same refresh-token OAuth mechanism as `gcal` (same
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_REFRESH_TOKEN`
variables), but **the required consent scope is different**: Calendar
needs `https://www.googleapis.com/auth/calendar`, Sheets needs
`https://www.googleapis.com/auth/spreadsheets`. If the refresh token
was generated with only the Calendar scope, this module's calls will
fail with 403 — the consent needs to be redone with both scopes, or a
separate OAuth client needs to be used. Also documented in the
README.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

DEFAULT_BASE_URL = "https://sheets.googleapis.com/v4"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class SheetsAPIError(Exception):
    """Generic error calling the Google Sheets API (status >= 400)."""

    def __init__(self, status_code: int, message: str, response_body=None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Google Sheets API error {status_code}: {message}")


@dataclass
class SheetsClient:
    access_token: str
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: int = 15

    @classmethod
    def from_refresh_token(cls, client_id: str, client_secret: str,
                            refresh_token: str, base_url: Optional[str] = None,
                            token_url: str = TOKEN_URL):
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
            raise SheetsAPIError(response.status_code, response.text)

        access_token = response.json()["access_token"]
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        return cls(access_token=access_token, **kwargs)

    @classmethod
    def from_env(cls, base_url: Optional[str] = None):
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
                "Missing environment variables for Google Sheets: "
                + ", ".join(missing)
                + ". Copy fika-sync/.env.example to .env and fill in the values. "
                "Careful: the refresh token needs the "
                "https://www.googleapis.com/auth/spreadsheets scope, not just Calendar's."
            )
        return cls.from_refresh_token(client_id, client_secret, refresh_token, base_url=base_url)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def post(self, path: str, params: Optional[dict] = None, json_body: Optional[dict] = None):
        return self._request("POST", path, params=params, json_body=json_body)

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
            raise SheetsAPIError(response.status_code, message, response_body=body)
        return response.json()
