# gcal — Google Calendar for RailCall

## What it does

Five commands against the real [Google Calendar API v3](https://developers.google.com/workspace/calendar/api/v3/reference):

- **`list_events`** — events on a calendar within a time range.
- **`find_next_free_slot`** — the next free slot of a given duration in a search window (Google has no such endpoint; this combines `freeBusy.query` with local gap-finding logic).
- **`create_event`** — create an event.
- **`update_event`** — edit fields of an existing event (move it, rename it).
- **`delete_event`** — delete an event.

## Who it's for

Small teams whose AI agent or RailCall workflow needs to read and act on calendars — protecting focus time, moving a meeting, checking whether someone's free before proposing a slot — under RailCall's preview → approve → execute → signed-receipt discipline instead of a bespoke Google integration.

Concrete use case: a workflow that finds a person's next free 30-minute slot this week and books a protected "Focus Time" block there, with a human approving the actual write before it lands on the calendar (`create_event` is `side_effects: "external"`; `list_events` and `find_next_free_slot` are read-only, `"none"`).

## Install

```bash
railcall market install juani1972/gcal
```

Set a valid Google OAuth access token in Studio → Integrations. See "Known limitations" — this module expects the token to already be valid; it does not refresh it.

## Example

```bash
railcall airlock stage find_next_free_slot --inputs '{
  "calendar_id": "ana@example.com", "duration_minutes": 30,
  "search_start_iso": "2026-09-01T09:00:00Z", "search_end_iso": "2026-09-01T18:00:00Z"
}'
railcall airlock approve <staging_id>
```

Expected output:

```json
{"slot": {"start": "2026-09-01T10:00:00+00:00", "end": "2026-09-01T10:30:00+00:00"}}
```

## Credentials needed

- A Google OAuth 2.0 access token with Calendar scope
  (`https://www.googleapis.com/auth/calendar`), set via Studio →
  Integrations.

## Known limitations

- **Access tokens expire in ~1 hour and this module does not refresh
  them.** `module.json` has no `auth` field (that's not part of the
  confirmed manifest schema — see `credentials_note` instead) and
  ships a static access-token credential on purpose: whether
  RailCall's provider-catalogue OAuth refresh (documented for the
  ~110 built-in providers like Salesforce/HubSpot) covers a *custom*
  provider like this one isn't documented anywhere public. Shipped
  honest-but-limited rather than guessing — confirm with RailCall
  support before relying on this in production.
- **Not yet run against a real Station install** — no network route
  to `railcall.ai` from this environment. Verified instead: 13 unit
  tests with `urllib.urlopen` mocked (`tests/test_handler.py`),
  covering all 5 commands' request-building, response-parsing, input
  validation, error propagation, and `find_next_free_slot`'s pure
  gap-finding logic (no network for that part). Function naming is
  `_h_<name>`, confirmed by the [Publisher
  FAQ](https://railcall.ai/docs/marketplace-developer/faq/)
  rejection-reason list — not a guess.
- `find_next_free_slot` only checks one calendar per call — no
  multi-attendee "find a slot that works for everyone" yet.
- `module.json` declares a sandbox `requires` block
  (`network: ["www.googleapis.com"]`, no subprocess, no filesystem
  writes) — opt-in since Station v0.33+, not yet tested against a
  real Station's enforcement.

## Source

Standard library only (`urllib.request`, `json`, `datetime`) — no
external dependencies. ~200 lines across `module.json` +
`handlers/handler.py`.
