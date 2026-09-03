"""Handlers for the your-handle/gcal module.

VALIDATED (29 Aug 2026) against Google Calendar API v3's current
official documentation
(developers.google.com/workspace/calendar/api/v3/reference). Unlike
Cal.com, this API is old and stable -- no discrepancies were found
between what the documentation says and what one would expect:

  - Base URL: https://www.googleapis.com/calendar/v3
  - GET    /calendars/{calendarId}/events              (events.list)
  - POST   /calendars/{calendarId}/events              (events.insert)
  - PATCH  /calendars/{calendarId}/events/{eventId}     (events.patch)
  - DELETE /calendars/{calendarId}/events/{eventId}     (events.delete)
  - Auth: OAuth2 Bearer token (no API key). RailCall injects it via
    Studio > Integrations (see engine_spec.json: auth type oauth2,
    provider google) -- here it's read from the
    GOOGLE_CALENDAR_ACCESS_TOKEN environment variable only as a
    development/test mechanism.
  - calendarId accepts the literal "primary" for the authenticated
    user's calendar -- that's what fika-sync uses (gcal_calendar_id
    in team.csv will normally be a specific calendar email, not
    always "primary").

Even with a stable API, an OAuth access token expires (usually 1h)
and RailCall handles refreshing it -- this module does NOT implement
refresh, it assumes the token it receives is already valid. That's
the responsibility of the runtime orchestrating the module, not this
handler.

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
"""
import os
import requests

BASE_URL = "https://www.googleapis.com/calendar/v3"


def _headers() -> dict:
    token = os.environ.get("GOOGLE_CALENDAR_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "GOOGLE_CALENDAR_ACCESS_TOKEN is not configured. In production "
            "this is injected via RailCall Studio > Integrations (OAuth2), "
            "never hardcoded. The token expires -- RailCall is responsible "
            "for refreshing it before invoking this module."
        )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_events(inputs: dict, context: dict) -> dict:
    """GET /calendars/{calendarId}/events. from_date/to_date must be in
    RFC3339 (e.g. '2026-01-01T00:00:00Z') -- they're the timeMin/timeMax
    parameters."""
    calendar_id = inputs.get("calendar_id", "primary")
    params = {
        "timeMin": inputs["from_date"],
        "timeMax": inputs["to_date"],
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    resp = requests.get(
        f"{BASE_URL}/calendars/{calendar_id}/events", headers=_headers(), params=params, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def create_event(inputs: dict, context: dict) -> dict:
    """POST /calendars/{calendarId}/events (events.insert)."""
    calendar_id = inputs.get("calendar_id", "primary")
    body = {
        "summary": inputs["title"],
        "start": {"dateTime": inputs["start"], "timeZone": inputs["timezone"]},
        "end": {"dateTime": inputs["end"], "timeZone": inputs["timezone"]},
    }
    if inputs.get("description"):
        body["description"] = inputs["description"]
    resp = requests.post(
        f"{BASE_URL}/calendars/{calendar_id}/events", headers=_headers(), json=body, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def update_event(inputs: dict, context: dict) -> dict:
    """PATCH /calendars/{calendarId}/events/{eventId} (events.patch --
    partial-patch semantics, unlike Cal.com, here ANY field CAN be
    edited, including the title)."""
    calendar_id = inputs.get("calendar_id", "primary")
    event_id = inputs["event_id"]
    body = {}
    if inputs.get("title") is not None:
        body["summary"] = inputs["title"]
    if inputs.get("start") is not None:
        body["start"] = {"dateTime": inputs["start"], "timeZone": inputs.get("timezone", "UTC")}
    if inputs.get("end") is not None:
        body["end"] = {"dateTime": inputs["end"], "timeZone": inputs.get("timezone", "UTC")}
    resp = requests.patch(
        f"{BASE_URL}/calendars/{calendar_id}/events/{event_id}",
        headers=_headers(), json=body, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def delete_event(inputs: dict, context: dict) -> dict:
    """DELETE /calendars/{calendarId}/events/{eventId}. Returns 204 with
    no body on success -- there's no resp.json() to parse."""
    calendar_id = inputs.get("calendar_id", "primary")
    event_id = inputs["event_id"]
    resp = requests.delete(
        f"{BASE_URL}/calendars/{calendar_id}/events/{event_id}", headers=_headers(), timeout=15
    )
    resp.raise_for_status()
    return {"deleted": True, "event_id": event_id}
