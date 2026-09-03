# calcom-pro

Integrates Fika Sync with the [Cal.com v2 API](https://cal.com/docs/api-reference/v2/introduction)
to read meetings (`list_bookings`) and create/edit focus-time blocks
(`create_booking`, `update_booking`).

## ⚠️ Status: written, validated against official documentation, not against a real account

This module went through two rounds of validation:

1. **Cross-check against Cal.com's live official documentation**
   (2026-08-30) — found and fixed 2 real problems:
   - `cal-api-version` differs per endpoint: `list_bookings` uses
     `2026-05-01`, `create_booking` uses `2026-02-25`. The client now
     accepts a version per request instead of a fixed value.
   - `update_booking` assumed a generic `PATCH /v2/bookings/{uid}`
     that **isn't documented**. It's left with an explicit warning in
     the code — don't use it without checking the booking-editing
     documentation first.
2. **Mock-based tests** — 7/7 passing, verify the functions' signature
   builds correct requests according to the documentation.

**What's still missing is validation against a real account** — that's
what `tests/test_integration.py` exists for, which doesn't run by
default (see `VALIDATION.md` at the repo root for the full checklist).

## Installation

```bash
cd modules/calcom-pro
pip install -r requirements.txt --break-system-packages   # or in your venv
```

## Configuration

Needs the `CALCOM_API_KEY` environment variable (see
`fika-sync/.env.example`). Obtained by creating an API key at
`https://app.cal.com/settings/developer/api-keys` — **use a test
account, not production**, until the module is validated.

## Actions

| Action | Cal.com endpoint | Used in workflow.csv by |
|---|---|---|
| `list_bookings(client, status=None, cursor=None)` | `GET /v2/bookings` | `fetch_calcom_bookings` |
| `create_booking(client, event_type_id, start_iso, attendee_name, attendee_email, attendee_timezone, length_in_minutes=None)` | `POST /v2/bookings` | `protect_focus_time` |
| `update_booking(client, booking_uid, updates)` | `PATCH /v2/bookings/{uid}` | (available, not yet used in the workflow) |

## Usage example

```python
from client import CalComClient
from actions import list_bookings, create_booking

client = CalComClient.from_env()  # reads CALCOM_API_KEY

bookings = list_bookings(client, status="upcoming")

new_block = create_booking(
    client,
    event_type_id=123,               # ID of Cal.com's "Focus Time" event type
    start_iso="2026-09-01T09:00:00Z",
    attendee_name="Ana",
    attendee_email="ana@example.com",
    attendee_timezone="America/Argentina/Buenos_Aires",
    length_in_minutes=60,
)
```

## Before using this in a real demo

1. Create a Cal.com sandbox account and an event type dedicated to
   "Focus Time" (protects against `create_booking` accidentally
   creating meetings of another type).
2. Run `list_bookings` and `create_booking` against that account and
   compare the real response with what `actions.py` assumes
   (especially the shape of `response["data"]`).
3. Confirm whether `status` accepts multiple comma-separated values or
   whether a call per status is really needed (the public
   documentation suggests the latter — see the comment in
   `list_bookings`).
4. Update this README with the findings and, if something doesn't
   match, fix `actions.py` and its tests.

## Tests

```bash
cd modules/calcom-pro
python3 -m pytest tests/test_actions.py -v      # unit tests, with mocks, always run
python3 -m pytest tests/test_integration.py -v  # against the real API, see VALIDATION.md at the root
```

Current status: **7/7 unit tests passing** (verified on 2026-08-29,
with mocks — doesn't replace validation against a real account).
Integration tests are written but not run — see `VALIDATION.md` at
the repo root for the full checklist.
