"""
High-level actions for the gcal module.

Used by fika-sync/workflow.csv:
  - fetch_gcal_events   -> list_events
  - mirror_gcal_block   -> create_event
  - adjust_focus_time   -> update_event
  - resolve_conflicts   -> find_next_free_slot

**None of these actions have been tested against a real Google
Calendar account.** Payload format follows the v3 API's public
documentation.

The exception is `_first_free_slot`, which is pure logic (no network
calls) and can be trusted with the same confidence as
`team-health-analyzer` — it's deliberately separated from
`find_next_free_slot` (which does call the API) so it can be tested
without mocks.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from client import GCalClient


def list_events(client: GCalClient, calendar_id: str, time_min_iso: str,
                 time_max_iso: str, single_events: bool = True) -> list:
    """Lists a calendar's events (GET /calendars/{id}/events).

    Args:
        client: an already-authenticated GCalClient instance.
        calendar_id: usually the person's email (Google uses the
            email as the primary calendar's calendar_id).
        time_min_iso / time_max_iso: search range in RFC3339.
        single_events: if True, expands recurring events into
            individual instances (needed to sum real hours).

    Returns:
        list of dicts, one per event (see "items" in Google's
        response; exact shape to be confirmed against a real account).
    """
    params = {
        "timeMin": time_min_iso,
        "timeMax": time_max_iso,
        "singleEvents": str(single_events).lower(),
    }
    if single_events:
        params["orderBy"] = "startTime"

    response = client.get(f"/calendars/{calendar_id}/events", params=params)
    return response.get("items", [])


def create_event(client: GCalClient, calendar_id: str, summary: str,
                  start_iso: str, end_iso: str, timezone: str,
                  description: Optional[str] = None) -> dict:
    """Creates an event (POST /calendars/{id}/events).

    Used by mirror_gcal_block to mirror onto Google Calendar the
    focus time protect_focus_time blocked in Cal.com.
    """
    payload = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
    }
    if description:
        payload["description"] = description

    return client.post(f"/calendars/{calendar_id}/events", json_body=payload)


def update_event(client: GCalClient, calendar_id: str, event_id: str,
                  updates: dict) -> dict:
    """Edits an existing event (PATCH /calendars/{id}/events/{eventId}).

    Used by adjust_focus_time when get_actual_duration (calcom-pro /
    zoom) detects a meeting ran longer and the focus-time block needs
    to be shifted.
    """
    return client.patch(f"/calendars/{calendar_id}/events/{event_id}", json_body=updates)


def delete_event(client: GCalClient, calendar_id: str, event_id: str) -> dict:
    """Deletes an event (DELETE /calendars/{id}/events/{eventId}).

    Not referenced by any workflow.csv node yet — added so
    validate_live.py's test events can be cleaned up automatically,
    without leaving clutter on the real calendar used for validation.
    A candidate for future use if Fika Sync ever needs to cancel a
    focus-time block instead of just moving it.
    """
    return client.delete(f"/calendars/{calendar_id}/events/{event_id}")


def find_next_free_slot(client: GCalClient, calendar_id: str, duration_minutes: int,
                         search_start_iso: str, search_end_iso: str,
                         timezone: str = "UTC") -> Optional[dict]:
    """Finds the next free slot of at least duration_minutes.

    Google doesn't expose a direct "next free slot" endpoint, so this
    function combines POST /freeBusy (fetches the busy intervals)
    with client-side calculation logic (`_first_free_slot`, see
    below).

    Used by resolve_conflicts: if protect_focus_time detects the
    proposed time collides with an already-accepted meeting, this
    looks for the next free slot before blocking.

    Returns:
        dict {"start": iso, "end": iso} for the first slot found, or
        None if there's no slot of that size in the searched range.
    """
    payload = {
        "timeMin": search_start_iso,
        "timeMax": search_end_iso,
        "timeZone": timezone,
        "items": [{"id": calendar_id}],
    }
    response = client.post("/freeBusy", json_body=payload)
    busy_periods = response.get("calendars", {}).get(calendar_id, {}).get("busy", [])

    return _first_free_slot(busy_periods, search_start_iso, search_end_iso, duration_minutes)


def _first_free_slot(busy_periods: list, search_start_iso: str,
                      search_end_iso: str, duration_minutes: int) -> Optional[dict]:
    """Pure logic: given the busy intervals, finds the first free
    slot of at least duration_minutes within the searched range.

    No network calls — can be tested directly with hand-built data,
    just like team-health-analyzer's actions.

    Args:
        busy_periods: list of dicts {"start": iso, "end": iso}, not
            necessarily sorted or free of overlaps.
        search_start_iso / search_end_iso: bounds of the search
            range, in ISO 8601.
        duration_minutes: minimum duration of the slot being searched
            for.

    Returns:
        dict {"start": iso, "end": iso} or None if there's no slot.
    """

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
