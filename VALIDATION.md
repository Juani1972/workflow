# Validation checklist against real accounts/workspaces

This document is the step still missing for `calcom-pro`, `gcal`,
`slack` and `sheets` to stop being marked as
`"external_calls_validated_against_real_account": false`. An
assistant without internet access to those domains can't do it —
you need to run it yourself, with your own test accounts.

Each module has a `tests/test_integration.py` that **doesn't run by
default**: it's only activated with explicit environment variables,
so it's impossible to run it by accident and create real data
unintentionally.

## 0. Before you start

```bash
pip install pytest requests --break-system-packages
```

ALWAYS use test accounts/workspaces, never production ones — this
was already said in the repo's original README, and it still applies
here.

---

## 1. Cal.com

### Setup
1. Create a Cal.com account (or use an existing test one).
2. Create an event type dedicated to "Focus Time" — note its numeric
   ID (it appears in the URL when editing it, or via
   `GET /v2/event-types`).
3. Generate an API key at
   `https://app.cal.com/settings/developer/api-keys`.

### Run
```bash
export RUN_LIVE_TESTS=1
export CALCOM_API_KEY=cal_test_xxxxx
cd modules/calcom-pro
python3 -m pytest tests/test_integration.py -v -s   # read-only for now
```

If `test_live_list_bookings_returns_a_list` passes, manually review
the printed `bookings[0]` and compare it against what `actions.py`
assumes (`response["data"]`, the `uid` field, etc.). If something
doesn't match, flag it so `actions.py` and its mock-based tests can
be adjusted.

**Note on `cal-api-version`:** `list_bookings` uses `2026-05-01` and
`create_booking` uses `2026-02-25` — these are deliberately different
values (Cal.com versions each endpoint separately, confirmed against
the official documentation on 2026-08-30). If either test fails with
a version-related error, that's the first thing to check — Cal.com
may have published a newer version.

**Note on `update_booking`:** this action is not confirmed — no
generic `PATCH /v2/bookings/{uid}` was found documented. Before
running any test that uses it, review Cal.com v2's booking-editing
documentation and fix the endpoint if needed.

To test `create_booking` / `update_booking` (creates real data):
```bash
export CALCOM_TEST_EVENT_TYPE_ID=123   # the ID noted during setup
export ALLOW_LIVE_WRITES=1
python3 -m pytest tests/test_integration.py -v -s
```

**Manually cancel** the test booking from the Cal.com UI when done —
the module doesn't have a cancel action yet.

### What to update if everything went well
- `modules/calcom-pro/module_spec.json`:
  `"external_calls_validated_against_real_account": true`
- `fika-sync/engine_spec.json`, `calcom` provider:
  `"validated_against_real_account": true`
- Both READMEs, removing the "not tested" warnings.

---

## 2. Google Calendar

### Setup
1. Create a project in Google Cloud Console and an OAuth Client ID
   (a "Desktop app" type is the simplest to test by hand).
2. Complete the OAuth consent flow once (with Google's official
   libraries or by hand) to get a `refresh_token` — this repo doesn't
   include that flow, only the exchange of a refresh token for an
   access token.
3. Decide which calendar to use: a test account's `"primary"`, or a
   secondary calendar you don't mind breaking.

### Run
```bash
export RUN_LIVE_TESTS=1
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export GOOGLE_REFRESH_TOKEN=...
export GCAL_TEST_CALENDAR_ID=primary
cd modules/gcal
python3 -m pytest tests/test_integration.py -v -s -k "not create_and_update"
```

Manually review:
- `list_events` — are the events it fetches the ones you expect?
- `find_next_free_slot` — is the proposed slot actually free in the
  Google Calendar UI?

To test `create_event` / `update_event` (creates real data):
```bash
export ALLOW_LIVE_WRITES=1
python3 -m pytest tests/test_integration.py -v -s
```

**Automatic cleanup**: the write test deletes the test event itself
at the end with `delete_event` (added to this module specifically for
this) — you don't need to delete it by hand, but it's still worth
confirming in the UI that the event was created correctly while the
test is running, if you want to see it before it's deleted.

Also confirm how long the access token actually lasts in practice
(Google's docs say ~1h) — important for deciding whether `GCalClient`
needs to cache the token between nodes in the same workflow run.

### What to update if everything went well
- `modules/gcal/module_spec.json`:
  `"external_calls_validated_against_real_account": true`
- `fika-sync/engine_spec.json`, `google_calendar` provider:
  `"validated_against_real_account": true`
- Both READMEs.

---

## 3. Slack

### Setup
1. Create an app at `https://api.slack.com/apps` in a test workspace.
2. Add the `chat:write` scope, install the app to the workspace, and
   copy the Bot User OAuth Token (`xoxb-...`).
3. Copy the Signing Secret from "Basic Information".
4. Create (or choose) a test channel and invite the bot.

### Run
```bash
export RUN_LIVE_TESTS=1
export SLACK_BOT_TOKEN=xoxb-...
export ALLOW_LIVE_WRITES=1
export SLACK_TEST_CHANNEL=#fika-sync-test
cd modules/slack
python3 -m pytest tests/test_integration.py -v -s
```

`post_message` always writes (there's no read-only version), which
is why this is the only module where the integration test requires
`ALLOW_LIVE_WRITES=1` right from the start.

Manually review:
- That the message and the "Adjust my threshold" buttons look right
  in the Slack client (Block Kit sometimes renders differently than
  you'd imagine from reading the JSON).
- Click a real button and look at the interactivity payload that
  reaches your endpoint (or the app's request log at
  api.slack.com) — compare it against what
  `parse_interactive_payload` expects.
- **Important**: copy the `X-Slack-Signature` and
  `X-Slack-Request-Timestamp` headers from a real request and run
  `verify_slack_signature` with those real values (not the ones
  built by hand in `test_actions.py`) to confirm the algorithm
  actually validates signatures Slack genuinely generated, not just
  signatures we built ourselves following the documentation.

### What to update if everything went well
- `modules/slack/module_spec.json`:
  `"external_calls_validated_against_real_account": true`
  (and the `post_message` entry in the `actions` array)
- `fika-sync/engine_spec.json`, `slack` provider:
  `"validated_against_real_account": true`
- The module's README.

---

## 4. Google Sheets

### Setup
1. Create a test Google Sheets spreadsheet and copy its ID (the long
   string in the URL between `/d/` and `/edit`).
2. **Important:** the refresh token already generated for `gcal`
   (step 2) may not be enough. Calendar needs the
   `https://www.googleapis.com/auth/calendar` scope, Sheets needs
   `https://www.googleapis.com/auth/spreadsheets` — they're
   different. If the refresh token was generated consenting only to
   Calendar, the consent flow needs to be redone adding Sheets (both
   scopes can be requested together on the same consent screen, no
   separate Client ID is needed).
3. If the sheet is empty, add a header row in the first row (e.g.
   `date | person | hours | status`) — Sheets uses that row to detect
   where the table starts and append after it.

### Run
```bash
export RUN_LIVE_TESTS=1
export GOOGLE_CLIENT_ID=...
export GOOGLE_CLIENT_SECRET=...
export GOOGLE_REFRESH_TOKEN=...          # with the spreadsheets scope
export ALLOW_LIVE_WRITES=1                # append_row always writes
export SHEETS_TEST_SPREADSHEET_ID=...
export SHEETS_TEST_RANGE="Sheet1!A:D"     # optional, defaults to "Sheet1!A:D"
cd modules/sheets
python3 -m pytest tests/test_integration.py -v -s
```

`append_row` always writes (there's no read-only version), same as
`post_message` in Slack — which is why this is the only one of the
four modules, along with Slack, where the integration test requires
`ALLOW_LIVE_WRITES=1` from the start, with no prior read-only mode.

Manually review:
- That the row actually appears in the sheet, and in the expected
  position (Sheets appends after the last row of the table it
  detects in `SHEETS_TEST_RANGE`, not necessarily within that exact
  range — this can be surprising if the sheet has irregular data).
- If it fails with a 403 ("The caller does not have permission" or
  similar), it's almost certainly the scope issue from setup step 2,
  not a code bug — review the OAuth consent before touching
  `actions.py`.
- Compare the real response format
  (`updates.updatedRange`, `updates.updatedRows`) against what
  `actions.py` assumes.

**This test doesn't delete the row it creates** — unlike `gcal`
(which does have `delete_event` to clean up after itself), Sheets
doesn't have a delete action in this module. Delete the row by hand
if you don't want to keep it.

### What to update if everything went well
- `modules/sheets/module_spec.json`:
  `"external_calls_validated_against_real_account": true`
- `fika-sync/engine_spec.json`, `sheets` provider:
  `"validated_against_real_account": true`
- `workflows/onboarding-automator/engine_spec.json`, `sheets`
  provider: same field.
- The module's README.

---

## 5. The GUI's "Connect with one click" flow (Google + Slack)

This is **different** from sections 2 and 3 — those validate that
the `gcal`/`sheets`/`slack` modules work with credentials generated
by hand (developer flow). This validates the real flow an end user
would see: the "Connect" buttons in `fika-sync/gui/`
(`oauth_service.py`).

### Setup — Google
1. In Google Cloud Console, the OAuth Client has to be a **"Web
   application"** type, not "Desktop app" (the one used in section
   2). Add as an authorized redirect URI:
   `http://YOUR_DOMAIN/oauth/google/callback` (with `https://` in
   production).
2. Set THAT client's `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` as
   environment variables before running `python3 app.py`.

### Setup — Slack
1. Create (or reuse) an app at `api.slack.com/apps`.
2. Under **"OAuth & Permissions"**, add
   `http://YOUR_DOMAIN/oauth/slack/callback` as a Redirect URL, and
   the `chat:write` scope.
3. Copy the Client ID and Client Secret from "Basic Information" →
   set them as `SLACK_CLIENT_ID`/`SLACK_CLIENT_SECRET`.
4. **Step not in sections 2/3, and easy to miss**: by default, a
   Slack app can only be installed in the workspace where it was
   created — any other workspace trying to use the GUI's "Connect
   Slack" button will fail, not due to a code bug but because Slack
   doesn't allow it yet. To enable it:
   - Go to **"Manage Distribution"** in the app dashboard.
   - Complete the **"Share Your App with Other Workspaces"**
     checklist (confirms there are no hardcoded tokens/IDs from a
     specific workspace — there shouldn't be any, since OAuth is
     already used).
   - Click **"Activate Public Distribution"**.
   - This does NOT require Slack review or appearing in the App
     Directory — that's a separate, optional step
     ("Submit to App Directory"), only needed if you want people to
     find the app by searching inside Slack.

### Run
With the environment variables above set, start the GUI:
```bash
cd fika-sync/gui
python3 app.py
```
Open `http://YOUR_DOMAIN`, go to the "Connections" section, and click
"Connect" for Google and/or Slack. It should redirect to the real
consent screen and, on accepting, return to the GUI showing
"Connected ✓".

Manually review:
- That the saved token (`GET /api/status` → `oauth.connected`)
  actually works to call the real API — test
  `sync_service.sync_now()` after connecting and confirm that
  `source` comes back `"calcom+gcal"` (or at least that it doesn't
  fall back to demo due to a credentials error).
- If Google doesn't return `refresh_token` in the exchange (shouldn't
  happen thanks to `prompt=consent`, but this isn't confirmed against
  a real consent) — review `exchange_google_code` in
  `oauth_service.py`.
- If testing with a Slack workspace other than the one that created
  the app, and "Public Distribution" hasn't been activated yet, a
  Slack error will show up in the callback — this is expected, see
  step 4 above.

### What to update if everything went well
- `fika-sync/gui/README.md`, section "⚠️ About the OAuth flow: what's
  left to validate" — move the confirmed points from "what's
  missing" to "confirmed".

---

## 6. When everything is done

Once all four providers are validated:

1. Update the full `fika-sync/engine_spec.json` (the five providers
   it lists — `calcom`, `google_calendar`, `slack`, `sheets`, and
   `zoom` if that's also validated — with
   `"validated_against_real_account"` set to `true` where
   applicable).
2. Also update `workflows/onboarding-automator/engine_spec.json`
   (uses `slack`, `google_calendar`, `calcom` and `sheets` — the same
   four) and `workflows/meeting-debt/engine_spec.json` (uses
   `calcom`, `google_calendar` and `slack`).
3. Update this build's root README (`README.md`) moving this item
   from "pending" to "done", with the actual validation date.
4. Only then does it make sense to actually try
   `railcall audit workflow.csv` and `railcall build workflow.csv`
   for the 4 workflows — before validating the providers, any error
   from RailCall's compiler gets mixed up with possible errors from
   our own assumptions about the external APIs, making it harder to
   tell which is which.

## What this document doesn't cover

`budget-guardian` and (partially) `meeting-debt` depend on
capabilities of **RailCall itself** — not Cal.com, Google or Slack —
that remain unconfirmed (`webhook_calendar_change`, `get_spend_log`,
`pause_workflow`). Validating those isn't a "get a test account and
run this" checklist: it depends on RailCall's complete admin API
documentation, which is outside the scope of this document. See each
of those two workflows' README for the detail.
