"""Handlers for the your-handle/zoom module.

VALIDATED (29 Aug 2026) against Zoom API's current official
documentation (developers.zoom.us/docs/api/meetings/):

  - Base URL: https://api.zoom.us/v2
  - GET /past_meetings/{meetingUUID}  -- returns details of an already
    finished meeting, including the `duration` field (in minutes).
  - Auth: OAuth2 Bearer token (Server-to-Server OAuth or app OAuth,
    depending on how the integration is installed).

REAL GOTCHA documented on Zoom's official developer forum: if the
meeting UUID contains the '/' character or starts with '//' (happens
fairly often because Zoom generates base64 UUIDs that can include
those characters), it needs to be URL-encoded TWICE before being put
in the URL, or the API returns 404 "Meeting does not exist" with a
UUID that does exist. This handler already does this (double
quote()).

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
"""
import os
from urllib.parse import quote

import requests

BASE_URL = "https://api.zoom.us/v2"


def _headers() -> dict:
    token = os.environ.get("ZOOM_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "ZOOM_ACCESS_TOKEN is not configured. In production this is "
            "injected via RailCall Studio > Integrations (OAuth2), never "
            "hardcoded."
        )
    return {"Authorization": f"Bearer {token}"}


def get_meeting_actual_duration(inputs: dict, context: dict) -> dict:
    """GET /past_meetings/{meetingUUID}. The UUID is URL-encoded twice
    -- see the module note about Zoom's real gotcha with UUIDs
    containing '/' or starting with '//'."""
    uuid = inputs["meeting_uuid"]
    encoded_uuid = quote(quote(uuid, safe=""), safe="")
    resp = requests.get(f"{BASE_URL}/past_meetings/{encoded_uuid}", headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {
        "meeting_uuid": uuid,
        "actual_duration_minutes": data.get("duration"),
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "raw": data,
    }
