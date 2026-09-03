# gcal

Integrates Fika Sync with the [Google Calendar v3 API](https://developers.google.com/workspace/calendar/api/v3/reference)
to read ad-hoc events, mirror focus-time blocks, and find the next
available free slot.

## ⚠️ Status: written, not validated against a real account

Same as `calcom-pro`: correct function signatures, **13/13 tests
passing**, but:

- 8 tests mock the HTTP layer (`unittest.mock.patch` over
  `requests.request` / `requests.post`) — **no real network call, no
  real credentials**.
- 5 tests are for `_first_free_slot`, which **is pure logic** (no
  network) and can be trusted with the same confidence as
  `team-health-analyzer`, because it doesn't depend on any
  unconfirmed Google response format.

**No call to the real Google Calendar API has been tested yet.**

## Installation

```bash
cd modules/gcal
pip install -r requirements.txt --break-system-packages   # or in your venv
```

## Configuration

Needs OAuth 2.0 with a refresh token (not a simple API key, unlike
Cal.com):

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`

See `fika-sync/.env.example`. Obtained by creating an OAuth Client ID
in Google Cloud Console and completing the consent flow once to get
the refresh token — **use a test account**.

## Actions

| Action | Google endpoint | Used in workflow.csv by |
|---|---|---|
| `list_events(client, calendar_id, time_min_iso, time_max_iso, single_events=True)` | `GET /calendars/{id}/events` | `fetch_gcal_events` |
| `create_event(client, calendar_id, summary, start_iso, end_iso, timezone, description=None)` | `POST /calendars/{id}/events` | `mirror_gcal_block` |
| `update_event(client, calendar_id, event_id, updates)` | `PATCH /calendars/{id}/events/{eventId}` | `adjust_focus_time` |
| `delete_event(client, calendar_id, event_id)` | `DELETE /calendars/{id}/events/{eventId}` | None yet — added to automatically clean up `tests/test_integration.py`'s test events |
| `find_next_free_slot(client, calendar_id, duration_minutes, search_start_iso, search_end_iso, timezone="UTC")` | `POST /freeBusy` + local calculation | `resolve_conflicts` |

`find_next_free_slot` doesn't exist as a direct endpoint in Google:
it's built by combining `freeBusy.query` (fetches the busy intervals)
with `_first_free_slot`, an internal pure-logic function that
calculates the first free slot. That function is deliberately
separated so it can be tested without mocking HTTP.

## Usage example

```python
from client import GCalClient
from actions import list_events, create_event, find_next_free_slot

client = GCalClient.from_env()  # exchanges the refresh token for an access token

events = list_events(
    client, "ana@example.com",
    time_min_iso="2026-09-01T00:00:00Z",
    time_max_iso="2026-09-07T23:59:59Z",
)

slot = find_next_free_slot(
    client, "ana@example.com", duration_minutes=60,
    search_start_iso="2026-09-01T09:00:00+00:00",
    search_end_iso="2026-09-01T18:00:00+00:00",
)

if slot:
    create_event(
        client, "ana@example.com",
        summary="Focus Time",
        start_iso=slot["start"], end_iso=slot["end"],
        timezone="America/Argentina/Buenos_Aires",
        description="Blocked by Fika Sync",
    )
```

## Before using this in a real demo

1. Create an OAuth Client in Google Cloud Console and a test account
   (or a secondary calendar in your own account you don't mind
   breaking).
2. Run `list_events` and `create_event` against that account and
   compare the real response with what `actions.py` assumes.
3. Confirm the access token obtained via `from_env()` doesn't need to
   be renewed within a single workflow run (it lasts ~1 hour
   according to Google's documentation; if Fika Sync runs longer than
   that in a single execution, the refresh needs to be handled
   mid-run).
4. Validate `find_next_free_slot` with a calendar that has real,
   overlapping meetings, not just the hand-built test cases.
5. Update this README with the findings.

## Tests

```bash
cd modules/gcal
python3 -m pytest tests/test_actions.py -v      # unit tests, with mocks, always run
python3 -m pytest tests/test_integration.py -v  # against the real API, see VALIDATION.md at the root
```

Current status: **13/13 unit tests passing** (verified on 2026-08-29;
8 with mocks, 5 pure logic without mocks). Integration tests are
written but not run — see `VALIDATION.md` at the repo root.
