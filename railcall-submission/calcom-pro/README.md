# calcom-pro — Cal.com scheduling for RailCall

## What it does

Eight commands against the real [Cal.com v2 API](https://cal.com/docs/api-reference/v2):

- **`list_bookings`** — list bookings, optionally filtered by status.
- **`get_booking`** — fetch a single booking by uid.
- **`get_availability`** — open slots for an event type in a date range.
- **`create_booking`** — book a slot (e.g. block focus time as a real meeting).
- **`reschedule_booking`** — move an existing booking to a new time.
- **`cancel_booking`** — cancel a booking.
- **`protect_focus_time`** — not a native Cal.com endpoint: finds the earliest open slot for a "Focus Time" event type and books it for real, so deep work shows up on the calendar as an actual meeting other bookings have to route around, not a suggestion someone can ignore.
- **`get_meeting_load`** — pure calculation on already-fetched booking data (no extra API call): total hours and meeting count for the week.

## Who it's for

Small teams that already use Cal.com and want their AI agent (or a RailCall workflow) to read and manage bookings under the same preview → approve → execute → signed-receipt discipline as everything else in RailCall — instead of a bespoke, unaudited integration.

Concrete use case: a team-health workflow chains `list_bookings` → `get_meeting_load` to spot who's overloaded, then calls `protect_focus_time` to book them a real deep-work block — with a human approving it before it lands on the calendar, since every write command here is `side_effects: "external"`.

## Install

```bash
railcall market install juani1972/calcom-pro
```

Set your Cal.com API key in Studio → Integrations (generate one at [app.cal.com/settings/developer/api-keys](https://app.cal.com/settings/developer/api-keys)). The handler reads it via `__rc_helpers__["vault_get"]("calcom")` — never from an environment variable; `os.environ` credential reads fail RailCall's review, per the [Publisher FAQ](https://railcall.ai/docs/marketplace-developer/faq/).

## Example

```bash
railcall airlock stage protect_focus_time --inputs '{
  "event_type_id": 55, "start_date": "2026-09-01", "end_date": "2026-09-05",
  "attendee_name": "Ana", "attendee_email": "ana@example.com",
  "attendee_timezone": "America/Argentina/Buenos_Aires"
}'
railcall airlock approve <staging_id>
```

Expected output:

```json
{"booked": true, "booking": {"uid": "...", "start": "2026-09-01T09:00:00Z", ...}}
```

## Credentials needed

A Cal.com API key (personal or team), stored in the RailCall vault under `calcom`. `list_bookings`/`get_booking`/`get_availability` need no other scope; `create_booking` and `protect_focus_time` need an existing event type ID in your Cal.com account to book against.

## Known limitations

- **Not yet run against a real Station install** — no network route to `railcall.ai` from this environment. Verified instead: 23 unit tests with `urllib.urlopen` mocked (`tests/test_handler.py`), covering request-building, response-parsing, validation, and error propagation for all eight commands, plus the `_h_<name>` naming the loader requires.
- Every `cal-api-version` (`2026-05-01` list, `2026-02-25` get/create/reschedule/cancel, `2024-09-04` slots) is confirmed against Cal.com's live docs as of 2026-08-31, not guessed.
- `reschedule_booking` only changes the start time — no duration override.
- `protect_focus_time` books the single earliest slot found; no fallback event types.
- Standard library only (`urllib`, `json`) — RailCall docs don't describe a pip-dependency mechanism for modules.
- `module.json` declares a sandbox `requires` block (network limited to `api.cal.com`, no subprocess, no filesystem writes) — opt-in since Station v0.33+, not yet tested against real enforcement.

## Source

Standard library only — no external dependencies. ~330 lines across `module.json` + `handlers/handler.py`.
