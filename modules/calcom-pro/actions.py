"""
High-level actions for the calcom-pro module.

Used by fika-sync/workflow.csv:
  - fetch_calcom_bookings -> list_bookings
  - protect_focus_time    -> create_booking

**None of these actions has been tested against a real Cal.com
account.** The functions' signatures and payload format follow the
public v2 API documentation, but that doesn't replace a real test.
See README.md before using this in a demo with data that matters.
"""

from __future__ import annotations

from typing import Optional

from client import CalComClient


def list_bookings(client: CalComClient, status: Optional[str] = None,
                   cursor: Optional[str] = None) -> list:
    """Lists meetings from Cal.com (GET /v2/bookings).

    Note: according to the public documentation, `status` filters to a
    single value per call (for example "upcoming", "cancelled",
    "past"). To fetch several statuses at once, one call per status is
    needed with client-side merging — fetch_calcom_bookings in the
    workflow should iterate over the statuses Fika Sync cares about
    (probably "upcoming" and "past" for the current week).

    Args:
        client: an already-authenticated CalComClient instance.
        status: optional status filter.
        cursor: pagination cursor returned by a previous call.

    Returns:
        list of dicts, one per meeting (exact shape to be confirmed
        against a real account).
    """
    params = {}
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor

    # Confirmed against the live official documentation (2026-08-30):
    # GET /v2/bookings requires cal-api-version: 2026-05-01.
    response = client.get("/bookings", params=params or None, api_version="2026-05-01")
    return response.get("data", [])


def create_booking(client: CalComClient, event_type_id: int, start_iso: str,
                    attendee_name: str, attendee_email: str,
                    attendee_timezone: str,
                    length_in_minutes: Optional[int] = None) -> dict:
    """Creates a meeting on Cal.com (POST /v2/bookings).

    Fika Sync uses this in protect_focus_time to block focus time by
    creating a "meeting with yourself" on the overloaded person's
    calendar. Requires an event_type_id already configured in Cal.com
    for that purpose (to be created manually in Studio → Integrations,
    this module doesn't create it).

    Args:
        client: an already-authenticated CalComClient instance.
        event_type_id: ID of Cal.com's "focus time" event type.
        start_iso: start of the block, in ISO 8601 format (e.g.
            "2026-09-01T09:00:00Z").
        attendee_name: name of the person the block is for.
        attendee_email: that person's email (identifies the calendar).
        attendee_timezone: IANA timezone (e.g. "America/Argentina/Buenos_Aires").
        length_in_minutes: block duration; if not passed, Cal.com uses
            the event type's default duration.

    Returns:
        dict with the created meeting's data (exact shape to be
        confirmed against a real account).
    """
    payload = {
        "eventTypeId": event_type_id,
        "start": start_iso,
        "attendee": {
            "name": attendee_name,
            "email": attendee_email,
            "timeZone": attendee_timezone,
        },
    }
    if length_in_minutes is not None:
        payload["lengthInMinutes"] = length_in_minutes

    # Confirmed against the live official documentation (2026-08-30):
    # POST /v2/bookings requires cal-api-version: 2026-02-25 (different
    # from what GET /v2/bookings requires — Cal.com versions each
    # endpoint separately, not the whole API at once).
    response = client.post("/bookings", json_body=payload, api_version="2026-02-25")
    return response.get("data", {})


def update_booking(client: CalComClient, booking_uid: str, updates: dict) -> dict:
    """Edits an existing meeting.

    ⚠️ **UNCONFIRMED ENDPOINT — review before using.** When
    cross-checking this action against Cal.com's live official
    documentation (2026-08-30), no generic `PATCH /v2/bookings/{uid}`
    accepting arbitrary fields was found, as originally assumed. What
    IS documented are specific sub-endpoints, for example
    `PATCH /v2/bookings/{uid}/location` (only for changing the
    location). Moving or modifying other fields of a meeting (time,
    duration) likely requires a different "reschedule" endpoint, not
    this generic PATCH.

    **Do not use this function as-is without first reviewing Cal.com
    v2's complete booking-editing documentation** (the "Bookings"
    section at https://cal.com/docs/api-reference/v2/) and adjusting
    the path/payload accordingly.

    Potentially used by resolve_conflicts / adjust_focus_time if an
    already-created focus-time block needs to be moved, instead of
    cancelling it and creating a new one.

    Args:
        client: an already-authenticated CalComClient instance.
        booking_uid: the meeting's unique identifier (uid, not a
            numeric id).
        updates: fields to update — unconfirmed format, see the
            warning above.

    Returns:
        dict with the updated meeting's data.
    """
    response = client.patch(f"/bookings/{booking_uid}", json_body=updates)
    return response.get("data", {})
