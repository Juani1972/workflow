"""Handlers for the juani1972/calcom-pro module.

Every command declared in module.json has a matching `_h_<name>`
function here — confirmed as the loader's actual requirement by the
Publisher FAQ (https://railcall.ai/docs/marketplace-developer/faq/,
"Why did my module get rejected on install?": *"Command `<cid>`: no
callable `_h_<name>` in handler.py"*). Bare-name aliases are kept
below purely for readability when this module is imported elsewhere
(e.g. tests) — the loader itself only ever calls the `_h_`-prefixed
names.

Two things this module previously flagged as unconfirmed are resolved,
both per the same FAQ page:

1. `__rc_helpers__["vault_get"]` — confirmed shape is
   `{"api_key": "..."}`, resolved by Station's credential store as of
   v0.29+.
2. Handler functions **must** be named `_h_<command_name>`.

Only the Python standard library is used here (`urllib`, `json`) —
the RailCall docs don't describe a pip-dependency declaration
mechanism for modules, so `requests` was avoided.

**v0.2.0 — five new commands, verified against Cal.com's live API
docs (cal.com/docs/api-reference/v2) on 2026-08-31:**

- `get_booking` — GET /bookings/{uid}, cal-api-version 2026-02-25.
- `get_availability` — GET /slots, cal-api-version 2024-09-04.
  Confirmed params: eventTypeId, start, end, timeZone, format=range.
- `cancel_booking` — POST /bookings/{uid}/cancel, cal-api-version
  2026-02-25. Body: {cancellationReason, cancelSubsequentBookings}.
- `protect_focus_time` — not a native Cal.com endpoint. Business
  logic that composes get_availability + create_booking: finds the
  earliest open slot for a "Focus Time" event type and books it for
  real, so it shows up on the calendar as an actual meeting other
  bookings have to route around instead of a suggestion someone can
  ignore.
- `get_meeting_load` — pure logic, no network call. Sums booking
  duration from data already fetched via list_bookings, so a
  workflow can chain list_bookings -> get_meeting_load without a
  second API round trip.

This also lets `reschedule_booking`'s cal-api-version move from
"assumed" to confirmed: GET /bookings/{uid} and POST
/bookings/{uid}/cancel both independently confirm 2026-02-25 as the
current version for the whole booking-mutation family, and
cal.com/docs/api-reference/v2/bookings/reschedule-a-booking
confirms POST /bookings/{uid}/reschedule uses the same value.

Still not run against a real Station install — this environment has
no network route to railcall.ai. See README.md for what's confirmed
by reading the docs vs. what still needs a first real run.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

CALCOM_BASE_URL = "https://api.cal.com/v2"

# Cal.com versions its v2 API per-endpoint via the cal-api-version
# header, not with one global value. Every constant below is
# confirmed against Cal.com's own live documentation (2026-08-31):
API_VERSION_LIST_BOOKINGS = "2026-05-01"      # GET  /bookings
API_VERSION_GET_BOOKING = "2026-02-25"        # GET  /bookings/{uid}
API_VERSION_CREATE_BOOKING = "2026-02-25"     # POST /bookings
API_VERSION_RESCHEDULE_BOOKING = "2026-02-25"  # POST /bookings/{uid}/reschedule
API_VERSION_CANCEL_BOOKING = "2026-02-25"     # POST /bookings/{uid}/cancel
API_VERSION_SLOTS = "2024-09-04"              # GET  /slots


class CalComError(Exception):
    """Raised for any non-2xx response from the Cal.com API. Never
    swallowed — every command below lets this propagate so the airlock
    surfaces the real failure instead of a silent no-op."""


def _vault_api_key() -> str:
    """Reads the Cal.com API key from the RailCall vault.

    NOT `os.environ` on purpose — the Publisher FAQ is explicit that
    "os.environ credential reads fail review."
    """
    result = __rc_helpers__["vault_get"]("calcom")  # noqa: F821 — injected by the RailCall loader
    if isinstance(result, dict):
        api_key = result.get("api_key")
    else:
        api_key = result
    if not api_key:
        raise CalComError(
            "No Cal.com API key found in the vault. Set it up in "
            "Studio → Integrations → calcom before running this command."
        )
    return api_key


def _request(method: str, path: str, params: dict = None, body: dict = None, api_version: str = None) -> dict:
    """Thin wrapper around urllib for the Cal.com v2 API. Raises
    CalComError with the response body on any non-2xx status — never
    returns a partial/guessed result on failure.

    `api_version` is required per-call, not a module-wide default —
    Cal.com versions each endpoint separately (see the constants
    above)."""
    url = f"{CALCOM_BASE_URL}{path}"
    if params:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
        if query:
            url = f"{url}?{query}"

    headers = {
        "Authorization": f"Bearer {_vault_api_key()}",
        "Content-Type": "application/json",
        "cal-api-version": api_version,
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise CalComError(f"Cal.com API returned {exc.code}: {error_body}") from exc


# ---------------------------------------------------------------------------
# Commands (must match module.json exactly)
# ---------------------------------------------------------------------------

def _h_list_bookings(inputs: dict, context: dict) -> dict:
    """List bookings from Cal.com, optionally filtered by status.

    inputs: {"status": str?, "cursor": str?}
    Returns: {"count": int, "bookings": list}
    """
    params = {}
    if inputs.get("status"):
        params["status"] = inputs["status"]
    if inputs.get("cursor"):
        params["cursor"] = inputs["cursor"]

    response = _request("GET", "/bookings", params=params, api_version=API_VERSION_LIST_BOOKINGS)
    bookings = response.get("data", [])
    return {"count": len(bookings), "bookings": bookings}


def _h_get_booking(inputs: dict, context: dict) -> dict:
    """Fetch a single booking by its uid.

    inputs: {"booking_uid": str}
    Returns: {"booking": dict}
    """
    if not inputs.get("booking_uid"):
        raise CalComError("Missing required input: booking_uid")

    response = _request(
        "GET", f"/bookings/{urllib.parse.quote(inputs['booking_uid'])}",
        api_version=API_VERSION_GET_BOOKING,
    )
    return {"booking": response.get("data", {})}


def _h_get_availability(inputs: dict, context: dict) -> dict:
    """Get available time slots for an event type in a date range.

    Uses GET /slots with format=range so each slot carries both start
    and end — confirmed param set against Cal.com's live docs:
    eventTypeId, start, end, timeZone (optional), format.

    inputs: {"event_type_id": int, "start_date": str, "end_date": str,
             "timezone": str?}
    Returns: {"slots": {date: [{"start": str, "end": str}, ...]}}
    """
    for field in ("event_type_id", "start_date", "end_date"):
        if not inputs.get(field):
            raise CalComError(f"Missing required input: {field}")

    params = {
        "eventTypeId": inputs["event_type_id"],
        "start": inputs["start_date"],
        "end": inputs["end_date"],
        "format": "range",
    }
    if inputs.get("timezone"):
        params["timeZone"] = inputs["timezone"]

    response = _request("GET", "/slots", params=params, api_version=API_VERSION_SLOTS)
    return {"slots": response.get("data", {})}


def _h_create_booking(inputs: dict, context: dict) -> dict:
    """Create a booking in Cal.com.

    inputs: {"event_type_id": int, "start_iso": str, "attendee_name": str,
             "attendee_email": str, "attendee_timezone": str,
             "length_in_minutes": int?}
    Returns: {"booking": dict}
    """
    for required_field in ("event_type_id", "start_iso", "attendee_name", "attendee_email", "attendee_timezone"):
        if not inputs.get(required_field):
            raise CalComError(f"Missing required input: {required_field}")

    body = {
        "eventTypeId": inputs["event_type_id"],
        "start": inputs["start_iso"],
        "attendee": {
            "name": inputs["attendee_name"],
            "email": inputs["attendee_email"],
            "timeZone": inputs["attendee_timezone"],
        },
    }
    if inputs.get("length_in_minutes"):
        body["lengthInMinutes"] = inputs["length_in_minutes"]

    response = _request("POST", "/bookings", body=body, api_version=API_VERSION_CREATE_BOOKING)
    return {"booking": response.get("data", {})}


def _h_reschedule_booking(inputs: dict, context: dict) -> dict:
    """Reschedule an existing Cal.com booking to a new start time.

    Uses POST /bookings/{uid}/reschedule — confirmed against Cal.com's
    own documentation.

    inputs: {"booking_uid": str, "new_start_iso": str, "reason": str?}
    Returns: {"booking": dict}
    """
    if not inputs.get("booking_uid"):
        raise CalComError("Missing required input: booking_uid")
    if not inputs.get("new_start_iso"):
        raise CalComError("Missing required input: new_start_iso")

    body = {"start": inputs["new_start_iso"]}
    if inputs.get("reason"):
        body["reschedulingReason"] = inputs["reason"]

    response = _request(
        "POST", f"/bookings/{inputs['booking_uid']}/reschedule", body=body,
        api_version=API_VERSION_RESCHEDULE_BOOKING,
    )
    return {"booking": response.get("data", {})}


def _h_cancel_booking(inputs: dict, context: dict) -> dict:
    """Cancel an existing booking.

    inputs: {"booking_uid": str, "reason": str?}
    Returns: {"booking": dict}
    """
    if not inputs.get("booking_uid"):
        raise CalComError("Missing required input: booking_uid")

    body = {}
    if inputs.get("reason"):
        body["cancellationReason"] = inputs["reason"]

    response = _request(
        "POST", f"/bookings/{urllib.parse.quote(inputs['booking_uid'])}/cancel", body=body,
        api_version=API_VERSION_CANCEL_BOOKING,
    )
    return {"booking": response.get("data", {})}


def _h_protect_focus_time(inputs: dict, context: dict) -> dict:
    """Find the earliest free slot for a focus-time event type and
    book it for real.

    Not a native Cal.com endpoint — this is business logic that
    composes get_availability + create_booking. Deliberately books a
    real meeting rather than just returning a suggestion, so the
    block actually shows up on the calendar and other bookings have
    to route around it.

    inputs: {"event_type_id": int, "start_date": str, "end_date": str,
             "attendee_name": str, "attendee_email": str,
             "attendee_timezone": str}
    Returns: {"booked": bool, "booking": dict?, "reason": str?}
    """
    for field in ("event_type_id", "start_date", "end_date", "attendee_name", "attendee_email", "attendee_timezone"):
        if not inputs.get(field):
            raise CalComError(f"Missing required input: {field}")

    availability = _h_get_availability(
        {
            "event_type_id": inputs["event_type_id"],
            "start_date": inputs["start_date"],
            "end_date": inputs["end_date"],
            "timezone": inputs["attendee_timezone"],
        },
        context,
    )
    earliest_slot = _earliest_slot(availability["slots"])
    if earliest_slot is None:
        return {"booked": False, "reason": "No open slots in the requested window."}

    booking_result = _h_create_booking(
        {
            "event_type_id": inputs["event_type_id"],
            "start_iso": earliest_slot["start"],
            "attendee_name": inputs["attendee_name"],
            "attendee_email": inputs["attendee_email"],
            "attendee_timezone": inputs["attendee_timezone"],
        },
        context,
    )
    return {"booked": True, "booking": booking_result["booking"]}


def _h_get_meeting_load(inputs: dict, context: dict) -> dict:
    """Summarize booked hours from already-fetched booking data.

    Pure calculation, no network call — lets a workflow chain
    list_bookings -> get_meeting_load without a second round trip.

    inputs: {"bookings": list}
    Returns: {"total_hours": float, "meeting_count": int}
    """
    if inputs.get("bookings") is None:
        raise CalComError("Missing required input: bookings")

    total_minutes = 0.0
    for booking in inputs["bookings"]:
        total_minutes += _booking_duration_minutes(booking)

    return {
        "total_hours": round(total_minutes / 60, 2),
        "meeting_count": len(inputs["bookings"]),
    }


# ---------------------------------------------------------------------------
# Pure logic — no network calls, unit-testable in isolation.
# ---------------------------------------------------------------------------

def _earliest_slot(slots_by_date: dict):
    """Given the {date: [{"start", "end"}, ...]} shape returned by
    get_availability, returns the single earliest slot across all
    dates, or None if there are none."""
    all_slots = [slot for day_slots in slots_by_date.values() for slot in day_slots]
    if not all_slots:
        return None
    return min(all_slots, key=lambda s: s["start"])


def _booking_duration_minutes(booking: dict) -> float:
    """Duration of a single booking in minutes. Prefers the explicit
    `duration` field Cal.com returns; falls back to computing it from
    start/end if that field is absent."""
    if booking.get("duration") is not None:
        return float(booking["duration"])

    start = booking.get("start")
    end = booking.get("end")
    if not start or not end:
        return 0.0

    def parse(iso_str: str) -> datetime:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))

    return (parse(end) - parse(start)).total_seconds() / 60


# ---------------------------------------------------------------------------
# Bare-name aliases — readability only. The RailCall loader calls the
# `_h_`-prefixed functions above directly.
# ---------------------------------------------------------------------------

list_bookings = _h_list_bookings
get_booking = _h_get_booking
get_availability = _h_get_availability
create_booking = _h_create_booking
reschedule_booking = _h_reschedule_booking
cancel_booking = _h_cancel_booking
protect_focus_time = _h_protect_focus_time
get_meeting_load = _h_get_meeting_load
