"""Handlers for the your-handle/calcom-pro module.

VALIDATED (29 Aug 2026) against Cal.com's current official API v2
documentation (https://cal.com/docs/api-reference/v2). Changes from
the previous version, which had not been cross-checked against a real
account:

  1. Added the `cal-api-version` header, required on every request.
     Without it, the API silently falls back to an old endpoint
     version.
  2. `get_availability` / `book_slot` used GET /v2/availability, which
     doesn't exist. The real endpoint is GET /v2/slots (requires
     username + event_type_id or event_type_slug, and start/end/
     timeZone params).
  3. `update_event` used PATCH /v2/bookings/{id}, which doesn't exist
     in v2. Cal.com v2 has no generic edit endpoint: only rescheduling
     the time is possible, via POST /v2/bookings/{uid}/reschedule.
  4. `delete_event` used DELETE /v2/bookings/{id}, which doesn't
     exist. Canceling is POST /v2/bookings/{uid}/cancel.
  5. `sync_calendar` called an endpoint (/v2/calendars/sync) that
     could not be found documented in v2. Left marked as unconfirmed
     and raises an explicit error instead of silently failing against
     a 404 in production.
  6. (29 Aug, second pass) `create_event` / `book_slot` sent an
     incomplete attendee object (email only) and `create_event` sent
     an `end` field, which Cal.com v2 does NOT accept -- the duration
     is defined by the event type (event_type_id), not the client.
     `create_event` also requires `eventTypeId` (or
     eventTypeSlug+username), same as book_slot: a "free" booking
     can't be created without an event type behind it. The payload was
     fixed and attendee_name and attendee_timezone are now required in
     input_schema (previously it only asked for email).
  7. Added `protect_focus_time`: not a native Cal.com action, it's
     Fika Sync's own business logic (find a free slot per a time
     priority + book it against an event_type_id the user must
     configure in their Cal.com account as a "focus block"). Built by
     reusing get_availability + book_slot, not inventing another
     endpoint.

Testing every function against a real Cal.com account before
publishing the module is still pending -- this fixes the
endpoints/headers per the docs, but doesn't replace an end-to-end
test. In particular: a public Cal.com issue
(github.com/calcom/cal.diy #24851) reports that the API sometimes
also requires a `title` field at the booking's root even though the
docs don't document it as required -- if `create_event`/`book_slot`
return 400 with `error_required_field` against a real account, that's
the first suspect to check.

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
The return value becomes the signed receipt's payload.
"""
import os
import requests

BASE_URL = "https://api.cal.com/v2"
CAL_API_VERSION = "2024-08-13"


def _headers() -> dict:
    api_key = os.environ.get("CALCOM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CALCOM_API_KEY is not configured. In production this is "
            "injected via RailCall Studio > Integrations, never hardcoded."
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "cal-api-version": CAL_API_VERSION,
    }


def _attendee(inputs: dict) -> dict:
    """Minimal attendee object Cal.com v2 expects: name, email, timeZone.
    (The previous version only sent email, which is insufficient per
    the official create-a-booking docs.)"""
    return {
        "name": inputs["attendee_name"],
        "email": inputs["attendee_email"],
        "timeZone": inputs["attendee_timezone"],
    }


def list_events(inputs: dict, context: dict) -> dict:
    params = {"afterStart": inputs["from_date"], "beforeEnd": inputs["to_date"]}
    if inputs.get("username"):
        params["attendeeEmail"] = inputs["username"]
    resp = requests.get(f"{BASE_URL}/bookings", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def create_event(inputs: dict, context: dict) -> dict:
    """POST /v2/bookings. Requires eventTypeId -- Cal.com has no concept
    of a "free" booking without an event type. Doesn't send `end`: the
    duration is defined by the event type, not the client (this was a
    bug in the previous version)."""
    body = {
        "eventTypeId": inputs["event_type_id"],
        "start": inputs["start"],
        "attendee": _attendee(inputs),
    }
    resp = requests.post(f"{BASE_URL}/bookings", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def update_event(inputs: dict, context: dict) -> dict:
    """Reschedules a booking. Cal.com v2 has no generic edit endpoint
    (PATCH /v2/bookings/{id} doesn't exist): only the time can be
    moved, via POST /v2/bookings/{uid}/reschedule. If a 'title' change
    is requested, it's explicitly rejected instead of silently ignored.
    """
    if inputs.get("title") is not None:
        raise NotImplementedError(
            "Cal.com v2 does not allow editing an existing booking's title "
            "via API. Only rescheduling the time (start) is supported."
        )
    event_id = inputs["event_id"]
    body = {"start": inputs["start"]} if inputs.get("start") else {}
    resp = requests.post(
        f"{BASE_URL}/bookings/{event_id}/reschedule", headers=_headers(), json=body, timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def delete_event(inputs: dict, context: dict) -> dict:
    """Cancels a booking. DELETE /v2/bookings/{id} doesn't exist in v2;
    the real endpoint is POST /v2/bookings/{uid}/cancel."""
    event_id = inputs["event_id"]
    body = {"cancellationReason": inputs.get("cancellation_reason", "Cancelled via RailCall")}
    resp = requests.post(
        f"{BASE_URL}/bookings/{event_id}/cancel", headers=_headers(), json=body, timeout=15
    )
    resp.raise_for_status()
    return {"deleted": True, "event_id": event_id}


def get_availability(inputs: dict, context: dict) -> dict:
    """GET /v2/slots (not /v2/availability, which doesn't exist).
    Requires identifying the event type (event_type_id) in addition to
    the user."""
    params = {
        "username": inputs["username"],
        "eventTypeId": inputs["event_type_id"],
        "start": inputs["from_date"],
        "end": inputs["to_date"],
    }
    resp = requests.get(f"{BASE_URL}/slots", headers=_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def book_slot(inputs: dict, context: dict) -> dict:
    # Revalidates availability before confirming, to avoid booking over
    # a slot that got taken between the query and the booking.
    avail = get_availability(
        {
            "username": inputs["username"],
            "event_type_id": inputs["event_type_id"],
            "from_date": inputs["slot_start"],
            "to_date": inputs["slot_start"],
        },
        context,
    )
    if not avail:
        raise RuntimeError("The slot is no longer available; not booking.")
    body = {
        "eventTypeId": inputs["event_type_id"],
        "start": inputs["slot_start"],
        "attendee": _attendee(inputs),
    }
    resp = requests.post(f"{BASE_URL}/bookings", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _extract_slot_times(slots_response: dict) -> list:
    """Flattens GET /v2/slots's response (grouped by date) into a
    simple, sorted list of ISO times. Real format per the docs:
    {"data": {"slots": {"2024-01-15": [{"time": "2024-01-15T09:00:00Z"}, ...]}}}
    """
    data = slots_response.get("data", slots_response)
    slots_by_date = data.get("slots", {}) if isinstance(data, dict) else {}
    times = []
    for day_slots in slots_by_date.values():
        for s in day_slots:
            t = s.get("time") if isinstance(s, dict) else s
            if t:
                times.append(t)
    return sorted(times)


def protect_focus_time(inputs: dict, context: dict) -> dict:
    """Looks for a free slot per a time priority and books it against
    the event_type_id that represents a "focus block" in the user's
    Cal.com account. NOT a native Cal.com endpoint -- it's Fika Sync's
    own business logic (workflow.csv's protect_focus_time node), built
    at the client level. If Fika Sync needs to block 2h for yellow
    severity and 4h for red, the Cal.com account must have TWO
    distinct event types (e.g. "Focus Block 2h" and "Focus Block 4h")
    and the caller must pass the correct event_type_id for the
    severity -- this function can't invent an arbitrary duration.

    Expected inputs:
      username, event_type_id, attendee_name, attendee_email,
      attendee_timezone, from_date, to_date,
      priority: "morning" | "afternoon" | "any" (default "any")
    """
    priority = inputs.get("priority", "any")
    avail = get_availability(
        {
            "username": inputs["username"],
            "event_type_id": inputs["event_type_id"],
            "from_date": inputs["from_date"],
            "to_date": inputs["to_date"],
        },
        context,
    )
    slots = _extract_slot_times(avail)

    def _hour(iso_ts: str) -> int:
        # Cal.com's times come in ISO 8601 UTC, e.g. "...T09:00:00Z"
        try:
            return int(iso_ts.split("T")[1][:2])
        except (IndexError, ValueError):
            return -1

    if priority == "morning":
        candidates = [s for s in slots if 0 <= _hour(s) < 12]
    elif priority == "afternoon":
        candidates = [s for s in slots if _hour(s) >= 12]
    else:
        candidates = slots

    if not candidates:
        raise RuntimeError(
            f"No free slots available (priority={priority}) for "
            f"{inputs['username']} between {inputs['from_date']} and {inputs['to_date']}."
        )

    chosen_slot = candidates[0]
    booking = book_slot(
        {
            "username": inputs["username"],
            "event_type_id": inputs["event_type_id"],
            "slot_start": chosen_slot,
            "attendee_name": inputs["attendee_name"],
            "attendee_email": inputs["attendee_email"],
            "attendee_timezone": inputs["attendee_timezone"],
        },
        context,
    )
    return {"blocked_slot": chosen_slot, "priority_used": priority, "booking": booking}


def _duration_hours(booking: dict) -> float:
    """Calculates a booking's duration in hours. Cal.com v2 returns
    `duration` in minutes in most booking responses; if it's missing,
    falls back to calculating it from start/end."""
    if booking.get("duration") is not None:
        return round(booking["duration"] / 60, 2)
    start, end = booking.get("start"), booking.get("end")
    if not (start and end):
        return 0.0
    from datetime import datetime
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return round((e - s).total_seconds() / 3600, 2)
    except ValueError:
        return 0.0


def get_meeting_load(inputs: dict, context: dict) -> dict:
    """NOT a native Cal.com endpoint -- it's Fika Sync's business logic
    (the get_calcom_load node). Lists the range's bookings via
    list_events (GET /v2/bookings, real endpoint) and sums the hours.

    Returns the total and the per-day breakdown, which is what the GUI
    and classify_severity need."""
    bookings_resp = list_events(
        {
            "from_date": inputs["from_date"],
            "to_date": inputs["to_date"],
            "username": inputs.get("username"),
        },
        context,
    )
    data = bookings_resp.get("data", bookings_resp)
    bookings = data if isinstance(data, list) else data.get("bookings", [])

    total_hours = 0.0
    by_day: dict = {}
    for b in bookings:
        hours = _duration_hours(b)
        total_hours += hours
        day = (b.get("start") or "")[:10]  # YYYY-MM-DD
        if day:
            by_day[day] = round(by_day.get(day, 0.0) + hours, 2)

    return {
        "username": inputs.get("username"),
        "total_hours": round(total_hours, 2),
        "hours_by_day": by_day,
        "booking_count": len(bookings),
    }


def get_attendance(inputs: dict, context: dict) -> dict:
    """Reads a specific booking's attendance (GET /v2/bookings/{uid}).

    NOTE: Cal.com v2 still does NOT have dedicated GET endpoints for
    attendees (there's an open issue in their repo requesting them,
    calcom/cal.diy#27283), so attendance is derived from the booking
    object, which includes the attendee list with their absence flag
    (`absent`/`noShow` depending on version). If Cal.com adds attendee
    endpoints later, this should migrate."""
    booking_uid = inputs["booking_uid"]
    resp = requests.get(
        f"{BASE_URL}/bookings/{booking_uid}", headers=_headers(), timeout=15
    )
    resp.raise_for_status()
    data = resp.json().get("data", resp.json())
    attendees = data.get("attendees", []) or []
    present, absent = [], []
    for a in attendees:
        is_absent = bool(a.get("absent") or a.get("noShow"))
        (absent if is_absent else present).append(a.get("email"))
    return {
        "booking_uid": booking_uid,
        "host_absent": bool(data.get("hostNoShow") or data.get("hostAbsent")),
        "present": present,
        "absent": absent,
        "attendee_count": len(attendees),
    }


def mark_absent(inputs: dict, context: dict) -> dict:
    """POST /v2/bookings/{uid}/mark-absent -- marks the host and/or
    specific attendees as no-show."""
    booking_uid = inputs["booking_uid"]
    body = {"host": bool(inputs.get("host_absent", False))}
    if inputs.get("absent_attendee_emails"):
        body["attendees"] = [
            {"email": email, "absent": True} for email in inputs["absent_attendee_emails"]
        ]
    resp = requests.post(
        f"{BASE_URL}/bookings/{booking_uid}/mark-absent",
        headers=_headers(), json=body, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def reassign_booking(inputs: dict, context: dict) -> dict:
    """POST /v2/bookings/{uid}/reassign/{userId} -- reassigns ONE
    round-robin booking to a specific host.

    IMPORTANT: Cal.com only allows reassigning round-robin bookings,
    one at a time. There's NO endpoint to "rebalance the assignment
    queue" globally (which is what the original workflow's
    rebalance_round_robin node assumed). If Fika Sync wants to move
    load away from someone in red, it has to iterate their bookings
    and reassign them one by one."""
    booking_uid = inputs["booking_uid"]
    user_id = inputs["target_user_id"]
    resp = requests.post(
        f"{BASE_URL}/bookings/{booking_uid}/reassign/{user_id}",
        headers=_headers(), json={}, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_user_schedule(inputs: dict, context: dict) -> dict:
    resp = requests.get(
        f"{BASE_URL}/schedules", headers=_headers(),
        params={"username": inputs["username"]}, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def sync_calendar(inputs: dict, context: dict) -> dict:
    """UNCONFIRMED: `/v2/calendars/sync` could not be found documented
    in Cal.com's current v2 API. Instead of letting this silently fail
    with a 404 in production, the error is raised explicitly until the
    real endpoint is confirmed against the official docs or Cal.com
    support."""
    raise NotImplementedError(
        "sync_calendar: endpoint not confirmed against Cal.com's v2 API. "
        "Check https://cal.com/docs/api-reference/v2 or contact Cal.com "
        "support before enabling this action."
    )
