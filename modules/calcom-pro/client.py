"""
Thin HTTP client for the Cal.com v2 API.

**Important — technical honesty note:** the endpoint format, headers
and payload structure in this file are taken from Cal.com's public
API v2 documentation (https://cal.com/docs/api-reference/v2/), but
**no call from this module has been tested against a real Cal.com
account**. Before using it in production:

  1. Create a Cal.com sandbox account.
  2. Run every `actions.py` action against that account (not just this
     repo's mock-based tests).
  3. Update this module's `README.md` with the confirmed endpoints,
     their real responses, and any necessary adjustments.

Also see `_readme` in `module_spec.json`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import requests

DEFAULT_BASE_URL = "https://api.cal.com/v2"
# Cal.com versions its API by date via the cal-api-version header, and
# **the required version differs per endpoint** (confirmed against
# the live official documentation on 2026-08-30):
#   - GET  /bookings         -> cal-api-version: 2026-05-01
#   - POST /bookings         -> cal-api-version: 2026-02-25
# This default value is only used if the caller doesn't specify one;
# `actions.py` passes the correct value in each function. If Cal.com
# publishes a newer version, update it here and in actions.py.
DEFAULT_API_VERSION = "2026-05-01"


class CalComAPIError(Exception):
    """Generic error calling the Cal.com API (status >= 400)."""

    def __init__(self, status_code: int, message: str, response_body=None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Cal.com API error {status_code}: {message}")


@dataclass
class CalComClient:
    """Minimal client: only knows how to authenticate and build requests.

    Business logic (which endpoint to call, which payload to build)
    lives in `actions.py`, not here — so the client can be reused for
    any future endpoint without touching it.
    """

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    api_version: str = DEFAULT_API_VERSION
    timeout_seconds: int = 15

    @classmethod
    def from_env(cls, base_url: Optional[str] = None, api_version: Optional[str] = None):
        """Creates a client by reading CALCOM_API_KEY from the environment (.env)."""
        api_key = os.environ.get("CALCOM_API_KEY")
        if not api_key:
            raise ValueError(
                "CALCOM_API_KEY is not set in the environment. "
                "Copy fika-sync/.env.example to .env and fill in the value "
                "with an API key from a TEST Cal.com account."
            )
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_version:
            kwargs["api_version"] = api_version
        return cls(api_key=api_key, **kwargs)

    def _headers(self, api_version: Optional[str] = None):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "cal-api-version": api_version or self.api_version,
        }

    def get(self, path: str, params: Optional[dict] = None, api_version: Optional[str] = None):
        return self._request("GET", path, params=params, api_version=api_version)

    def post(self, path: str, json_body: Optional[dict] = None, api_version: Optional[str] = None):
        return self._request("POST", path, json_body=json_body, api_version=api_version)

    def patch(self, path: str, json_body: Optional[dict] = None, api_version: Optional[str] = None):
        return self._request("PATCH", path, json_body=json_body, api_version=api_version)

    def _request(self, method: str, path: str, params=None, json_body=None, api_version=None):
        url = f"{self.base_url}{path}"
        response = requests.request(
            method,
            url,
            headers=self._headers(api_version=api_version),
            params=params,
            json=json_body,
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            try:
                body = response.json()
                message = body.get("message", str(body))
            except ValueError:
                body = response.text
                message = body
            raise CalComAPIError(response.status_code, message, response_body=body)
        return response.json()
