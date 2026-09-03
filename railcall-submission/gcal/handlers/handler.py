"""Handlers for the juani1972/gcal module.

Same pattern as juani1972/calcom-pro: stdlib-only HTTP, credentials
via `__rc_helpers__["vault_get"]`, every command matches an entry in
module.json through a `_h_<name>` function — confirmed as the actual
loader requirement by the Publisher FAQ
(https://railcall.ai/docs/marketplace-developer/faq/, "Why did my
module get rejected on install?"). Bare-name aliases at the bottom
are for readability only; the loader calls `_h_*` directly. The
`vault_get()` shape (`{"api_key": "..."}`) is likewise confirmed by
the same FAQ page, resolved by Station v0.29+.

**One open question remains, specific to this module:** Google access
tokens expire in ~1 hour. This module declares no `auth` block in
module.json at all (that field isn't part of the confirmed manifest
schema — see modules/docs — credentials are just read from the vault
by provider name), so it ships as a static access-token credential
with no refresh. Whether Google Calendar has automatic OAuth2 refresh
support as one of RailCall's built-in catalogue providers (~110 ids,
per docs/marketplace-developer/modules) is not documented anywhere
public — Google Calendar's presence in that catalogue is unconfirmed.
This limitation is stated plainly in README.md rather than guessed at.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

GCAL_BASE_URL = "https://www.googleapis.com/calendar/v3"


class GCalError(Exception):
    """Raised for any non-2xx response from the Google Calendar API."""


def _vault_access_token() -> str:
    result = __rc_helpers__["vault_get"]("gcal")  # noqa: F821 — injected by the RailCall loader
    if isinstance(result, dict):
        token = result.get("access_token") or result.get("api_key")
    else:
        token = result
    if not token:
        raise GCalError(
            "No Google access token found in the vault. Set it up in "
            "Studio → Integrations → gcal before running this command."
        )
    return token


def _request(method: str, path: str, params: dict = None, body: dict = None) -> dict:
    url = f"{GCAL_BASE_URL}{path}"
    if params:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
        if query:
            url = f"{url}?{query}"

    headers = {
        "Authorization": f"Bearer {_vault_access_token()}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise GCalError(f"Google Calendar API returned {exc.code}: {error_body}") from exc


# ---------------------------------------------------------------------------
# Commands (must match module.json exactly)
# ---------------------------------------------------------------------------

def _h_list_events(inputs: dict, context: dict) -> dict:
    """List events on a calendar in a time range.

    inputs: {"calendar_id": str, "time_min_iso": str, "time_max_iso": str}
    Returns: {"count": int, "events": list}
    """
    for field in ("calendar_id", "time_min_iso", "time_max_iso"):
        if not inputs.get(field):
            raise GCalError(f"Missing required input: {field}")

    params = {
        "timeMin": inputs["time_min_iso"],
        "timeMax": inputs["time_max_iso"],
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    response = _request("GET", f"/calendars/{urllib.parse.quote(inputs['calendar_id'])}/events", params=params)
    events = response.get("items", [])
    return {"count": len(events), "events": events}


def _h_find_next_free_slot(inputs: dict, context: dict) -> dict:
    """Find the next free slot of the requested duration in a search window.

    Combines POST /freeBusy (real network call) with pure local logic
    (`_first_free_slot`) that calculates the actual gap — Google has no
    "next free slot" endpoint of its own.

    inputs: {"calendar_id": str, "duration_minutes": int,
             "search_start_iso": str, "search_end_iso": str, "timezone": str?}
    Returns: {"slot": {"start": str, "end": str}} or {"slot": null}
    """
    for field in ("calendar_id", "duration_minutes", "search_start_iso", "search_end_iso"):
        if not inputs.get(field):
            raise GCalError(f"Missing required input: {field}")

    body = {
        "timeMin": inputs["search_start_iso"],
        "timeMax": inputs["search_end_iso"],
        "timeZone": inputs.get("timezone", "UTC"),
        "items": [{"id": inputs["calendar_id"]}],
    }
    response = _request("POST", "/freeBusy", body=body)
    busy_periods = response.get("calendars", {}).get(inputs["calendar_id"], {}).get("busy", [])

    slot = _first_free_slot(
        busy_periods, inputs["search_start_iso"], inputs["search_end_iso"], inputs["duration_minutes"]
    )
    return {"slot": slot}


def _h_create_event(inputs: dict, context: dict) -> dict:
    """Create a calendar event.

    inputs: {"calendar_id": str, "summary": str, "start_iso": str,
             "end_iso": str, "timezone": str, "description": str?}
    Returns: {"event": dict}
    """
    for field in ("calendar_id", "summary", "start_iso", "end_iso", "timezone"):
        if not inputs.get(field):
            raise GCalError(f"Missing required input: {field}")

    body = {
        "summary": inputs["summary"],
        "start": {"dateTime": inputs["start_iso"], "timeZone": inputs["timezone"]},
        "end": {"dateTime": inputs["end_iso"], "timeZone": inputs["timezone"]},
    }
    if inputs.get("description"):
        body["description"] = inputs["description"]

    event = _request("POST", f"/calendars/{urllib.parse.quote(inputs['calendar_id'])}/events", body=body)
    return {"event": event}


def _h_update_event(inputs: dict, context: dict) -> dict:
    """Edit fields of an existing event.

    inputs: {"calendar_id": str, "event_id": str, "updates": dict}
    Returns: {"event": dict}
    """
    for field in ("calendar_id", "event_id", "updates"):
        if not inputs.get(field):
            raise GCalError(f"Missing required input: {field}")

    path = f"/calendars/{urllib.parse.quote(inputs['calendar_id'])}/events/{urllib.parse.quote(inputs['event_id'])}"
    event = _request("PATCH", path, body=inputs["updates"])
    return {"event": event}


def _h_delete_event(inputs: dict, context: dict) -> dict:
    """Delete an event.

    inputs: {"calendar_id": str, "event_id": str}
    Returns: {"deleted": true}
    """
    for field in ("calendar_id", "event_id"):
        if not inputs.get(field):
            raise GCalError(f"Missing required input: {field}")

    path = f"/calendars/{urllib.parse.quote(inputs['calendar_id'])}/events/{urllib.parse.quote(inputs['event_id'])}"
    _request("DELETE", path)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Pure logic — no network, ported verbatim from modules/gcal/actions.py
# where it already had its own test coverage.
# ---------------------------------------------------------------------------

def _first_free_slot(busy_periods: list, search_start_iso: str, search_end_iso: str, duration_minutes: int):
    """Given busy intervals, finds the first free slot of at least
    duration_minutes within [search_start_iso, search_end_iso]."""

    def parse(iso_str: str) -> datetime:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))

    search_start = parse(search_start_iso)
    search_end = parse(search_end_iso)
    duration = timedelta(minutes=duration_minutes)

    busy_sorted = sorted(
        ({"start": parse(b["start"]), "end": parse(b["end"])} for b in busy_periods),
        key=lambda b: b["start"],
    )

    cursor = search_start
    for busy in busy_sorted:
        if busy["start"] > search_end:
            break
        if busy["start"] - cursor >= duration:
            return {"start": cursor.isoformat(), "end": (cursor + duration).isoformat()}
        if busy["end"] > cursor:
            cursor = busy["end"]

    if search_end - cursor >= duration:
        return {"start": cursor.isoformat(), "end": (cursor + duration).isoformat()}

    return None


# ---------------------------------------------------------------------------
# Bare-name aliases — readability only, not required by the loader
# (which calls the `_h_`-prefixed functions above directly).
# ---------------------------------------------------------------------------

list_events = _h_list_events
find_next_free_slot = _h_find_next_free_slot
create_event = _h_create_event
update_event = _h_update_event
delete_event = _h_delete_event
