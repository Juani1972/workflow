# Fika Sync — War Room (real backend + frontend)

Replaces `fika-sync/gui/war-room-prototype.html` (a browser prototype
with no persistence) with a real two-piece app, with **real
execution against Cal.com** when a focus-time-protection action is
approved.

```
webapp/
├── backend/
│   ├── main.py            # FastAPI + SQLite
│   ├── logic.py            # same logic already tested in the original repo
│   ├── calcom_client.py     # bridge to modules/calcom-pro/handlers/handler.py
│   ├── test_main.py         # 22/22 passing
│   └── requirements.txt
└── frontend/
    └── src/
```

## What this version DOES do

- Real SQLite persistence (team, thresholds, Cal.com config, an audit
  trail with `proposed → approved → executed|failed` states).
- Severity classification reuses the original repo's already-tested
  logic (`fika-sync/test/test_fika_logic.py`, `team-health-analyzer`).
- **When approving "protect_focus_time", the backend ATTEMPTS to
  actually execute it against Cal.com** (`modules/calcom-pro`,
  already fixed against the real v2 API: `cal-api-version`,
  `/v2/slots` instead of `/v2/availability`, `reschedule`/`cancel`
  instead of `PATCH`/`DELETE`, a complete `attendee` object,
  mandatory `eventTypeId`). If something fails, it's recorded with
  the exact reason — success is never faked.
- 49/49 tests passing across the whole repo (`pytest` from the root),
  including failure paths (no config, no API key, Cal.com returns an
  error) simulated with mocks, without needing a real account to
  verify them.

## How to enable real execution (you need your own Cal.com account)

**1. Create two event types in your Cal.com account** to represent a
"focus block": one for 2h (yellow severity) and another for 4h (red).
Cal.com defines the duration at the event-type level, this backend
can't decide it. Copy their `event_type_id` (they're in each event
type's URL at `app.cal.com`).

**2. Configure each person** from the GUI (the "Per-person Cal.com
configuration" card) or via the API:
```bash
curl -X PATCH http://127.0.0.1:8000/api/team/1/calcom-config \
  -H "Content-Type: application/json" \
  -d '{
    "calcom_username": "alex-ruiz",
    "attendee_email": "alex@example.com",
    "attendee_timezone": "Europe/Madrid",
    "focus_event_type_id_short": "12345",
    "focus_event_type_id_long": "12346"
  }'
```

**3. Export your Cal.com API key as an environment variable for the
backend process — NEVER paste it into a chat, a commit, or hardcode
it in code:**
```bash
export CALCOM_API_KEY=cal_live_xxxxxxxx   # get it at app.cal.com/settings/developer/api-keys
cd webapp/backend
uvicorn main:app --reload --port 8000
```

Without `CALCOM_API_KEY` configured, or without a complete
per-person config, `POST /api/approve-action` with `decision=approved`
returns `status: "failed"` with the exact reason — it doesn't break
the app, it doesn't fake success.

## What this doesn't do yet

- Doesn't call Google Calendar or Slack (only Cal.com).
- No user authentication in the API (out of scope for a contest
  demo).
- Only `protect_focus_time` has real execution implemented. Other
  actions (`rebalance`) are recorded as approved but not executed,
  with an explicit note.

## How to run it

### Backend
```bash
cd webapp/backend
pip install -r requirements.txt --break-system-packages   # or use a venv
export CALCOM_API_KEY=...   # optional; without this, approve-action fails explicitly
uvicorn main:app --reload --port 8000
```
Tests: `pytest test_main.py -v` (don't require a real `CALCOM_API_KEY` — they use mocks)

### Frontend
```bash
cd webapp/frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

## Reasonable next steps

1. Test `protect_focus_time` against a real Cal.com account at least
   once end-to-end (the current tests are contract/mock-based, they
   don't replace a test with real traffic — see the note in
   `modules/calcom-pro/handlers/handler.py` about the public Cal.com
   issue with the `title` field sometimes being required).
2. Connect Google Calendar and Slack the same way.
3. Basic authentication if this stops being just a contest demo.
