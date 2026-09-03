# Fika Sync — build status (2026-08-30)

**Just want to install and open the app?** See `INSTALL_README.md`
— no need to read the rest of this document for that.

This README summarizes what was built in this session and what's
still pending, following the same "technical honesty note" as the
repo's main README.

## 🔧 Most recent pass: personal Slack DMs + configuring Google/Slack from the GUI

- **Personal Slack DMs**: each person in 🟡/🔴 status can now receive
  a private alert (not just the shared-channel summary), using the
  `slack_user_id` that was already loaded in their Team row but
  previously wasn't used for anything. "Send a private DM..." toggle
  in Notifications + a "Send personal DMs now" button with a
  per-person result. 17 new tests.
- **Configure Google/Slack from the GUI, without editing `.env`**:
  whoever administers the installation can now paste the Client
  ID/Secret directly into the Connections tab (amber "App
  configuration" card), without touching any file or restarting the
  server. `.env` still works the same way as an alternative; whatever
  is saved from the GUI takes priority if both are present. 27 new
  tests, and along the way a bug was fixed where `/api/status` did
  not reflect credentials saved from the GUI, only the environment
  variable ones.
- See `fika-sync/gui/README.md`, sections "Personal Slack DMs" and
  "Configure Google/Slack from the GUI, without touching .env", for
  the full detail of both.

## 🔗 Previous pass: every user can connect (Cal.com + Google, per person)

- **Cal.com is now also a per-person connection**, not just Google
  Calendar. Previously, a single app-level API key tried to cover the
  whole team — only correct with a paid Cal.com Team plan; with a
  free account, that key only saw the bookings of whoever generated
  it. Now each person connects their own from their row on the
  **Team** tab, and `sync_service._sync_real()` uses each person's own
  key to fetch their own bookings. Anyone who hasn't connected their
  own is still covered by the shared key (backward compatibility) —
  see `fika-sync/gui/README.md`, section "Why Cal.com is also a
  per-person connection".
- **26 new tests** (`tests/test_models.py`, `test_app.py`,
  `test_sync_service.py`) cover this: independent per-person keys,
  cascading delete when someone is removed from the team, and the
  fallback to the shared key when someone hasn't connected their own.
  All 187 GUI tests pass.
- The fixes from `railcall-submission/` were merged in here
  (`_h_<command>` functions, sandbox `requires` block, Cal.com
  version bug, 39 tests with `urlopen` mocked) along with the GUI
  reorganized into tabs, from a previous session that worked on a
  copy of the repo that didn't yet have per-person connections — it's
  all together here now.
- The workflow validator (`tools/validate_workflows.py`) had a silent
  bug: it looked for `module.json` but this build's modules use
  `module_spec.json` — it reported "0 modules, OK" without actually
  validating anything. Fixed to read both formats; it now actually
  validates the 7 real modules.

## ✅ Built and verified in this session

### The 3 level-3 workflows (`workflows/`)

The original diagnosis marked these as "concepts, not features ready
to install". Each one now has `workflow.csv` + `engine_spec.json` +
`README.md`, verified programmatically (0 broken dependencies, 0
orphan actions across the 3 DAGs), and they reuse the provider
modules already built instead of assuming new, unwritten
integrations.

- **`workflows/meeting-debt/`** (13 nodes) — new pure-logic module
  `modules/meeting-debt-tracker/` (**11/11 tests**) that keeps track
  of how much focus time is owed to each person when a protected
  block gets overridden. One unconfirmed gap:
  `webhook_calendar_change` (RailCall reacting to a specific Google
  Calendar event, not just cron).
- **`workflows/onboarding-automator/`** (9 nodes) — the original
  diagnosis marked this as "the least mature: 5 chained integrations,
  none tested individually". It chains `slack`,
  `team-health-analyzer` (reuses `rebalance_queue` to pick a buddy,
  no new code written), `gcal`, `calcom-pro` and `sheets` — all 5
  already have their own unit tests, though none has been validated
  against a real account nor has the full chain been run end to end.
- **`workflows/budget-guardian/`** (9 nodes) — new pure-logic module
  `modules/budget-guardian-core/` (**11/11 tests**) that decides which
  workflows to pause due to overspending. The original diagnosis
  already flagged one unconfirmed RailCall capability
  (`pause_workflow`); this session found there are actually **two**
  (`get_spend_log` as well, to be able to read spend).
  `budget-guardian-core` is reliable regardless of whether those
  capabilities exist.

### `modules/sheets/` (new, needed for onboarding-automator)
- 1 action on the Google Sheets v4 API: `append_row`, on a
  `SheetsClient` that reuses `gcal`'s OAuth mechanism (same
  environment variables, but a **different scope** — documented in
  the module's README, an easy detail to miss if not read).
- **5/5 tests passing**, with the HTTP layer mocked.
- **No real call has been tested yet.**

### `modules/team-health-analyzer/`
- 5 pure-logic actions: `calculate_meeting_load`,
  `classify_team_health`, `rebalance_queue`, `summarize_team_report`,
  and `update_threshold` (added while building `slack/`, see note
  below).
- **No external dependencies, no network calls.**
- **8/8 tests passing** (`python3 -m pytest tests/ -v`).
- `module_spec.json` reconstructed following the same technical
  honesty convention as the rest of the repo (marked as a
  reconstruction, to be validated with `railcall module validate`).

### `fika-sync/` (core)
- `workflow.csv`: a **20-node** DAG (3 triggers, 12 transforms,
  5 effects) that integrates `team-health-analyzer`, `calcom-pro`,
  `gcal`, `slack`, `sheets` and `zoom`. Verified programmatically: 0
  broken dependencies, and the referenced `team-health-analyzer`
  actions match 1:1 with the ones that actually exist.
- `engine_spec.json`: providers, spend limit (`max_spend_cents`),
  retry policy. Each provider is explicitly marked with
  `"validated_against_real_account": false` because **no external
  integration has been tested against a real account** — that's
  still pending.
- `config/team.example.csv` and `config/thresholds.example.json`.
- `.env.example`.

### `modules/calcom-pro/`
- 3 actions that call the Cal.com v2 API: `list_bookings`,
  `create_booking`, `update_booking`, on a thin `CalComClient` that
  centralizes auth and error handling (`CalComAPIError`).
- **7/7 tests passing**, but with the HTTP layer mocked
  (`unittest.mock`) — **no call has been tested against a real
  Cal.com account yet**. `module_spec.json` marks this explicitly
  (`"external_calls_validated_against_real_account": false`).
- Endpoints and payload format taken from Cal.com's public v2 API
  documentation, not from Claude's own testing.
- `engine_spec.json` in `fika-sync/` still marks
  `"validated_against_real_account": false` for the `calcom`
  provider — no changes there until it's actually validated.

### `modules/gcal/`
- 5 actions on the Google Calendar v3 API: `list_events`,
  `create_event`, `update_event`, `delete_event`,
  `find_next_free_slot`, on a `GCalClient` that handles exchanging a
  refresh token for an access token (OAuth 2.0). `delete_event` was
  added later, to be able to automatically clean up
  `test_integration.py`'s test events without relying on manual
  deletion.
- **13/13 tests passing**: 8 with the HTTP layer mocked, and **5 for
  `_first_free_slot` that are pure logic, with no mocks or network**
  — that part can be trusted as much as `team-health-analyzer`.
- **No real call to the Google API has been tested yet**, explicitly
  marked in `module_spec.json`.

### `modules/slack/`
- 5 functions: `post_message` (calls the real API), and
  `build_summary_blocks`, `verify_slack_signature`,
  `parse_slash_command`, `parse_interactive_payload` (the other 4,
  pure logic, no network).
- **16/16 tests passing**: 3 with `post_message` mocked, 13 pure
  logic with no mocks.
- `verify_slack_signature` implements the HMAC-SHA256 verification +
  replay protection described in Slack's documentation — it's the
  module's most important security piece, and since it's pure logic,
  it can be trusted without needing a real workspace.
- **`post_message` has not been tested against a real workspace
  yet**, explicitly marked in `module_spec.json`.

## 🖥️ Real GUI (replaces the static mockups)

`fika-sync/gui/` — Flask dashboard with real SQLite persistence:

- The 3 underlying problems flagged by the original GUI analysis (no
  connection to real data, no persistence, static mockup) no longer
  apply: `/api/metrics` uses the real `team-health-analyzer`
  functions (via `provider_modules.py`, which resolves the `import
  actions` clash between the 3 provider modules), thresholds are
  actually edited and persisted, and there's real weekly history in
  SQLite.
- **Dual mode, never silently mixed**: without credentials, it runs
  in demo mode (`source: "demo"`, deterministic data); with Cal.com +
  Google credentials, it tries to sync for real and falls back to
  demo only on failure — each response explicitly states where the
  data came from.
- Its own visual identity ("coffee-break card", consistent with the
  Fika name) instead of a generic dashboard — linen/pine/amber/brick
  palette, Fraunces + IBM Plex typography.
- **Real bug found and fixed while building it**:
  `team-health-analyzer`, `calcom-pro` and `gcal` share file names
  (`actions.py`, `client.py`); having them all on `sys.path` at once
  caused `import actions` to resolve to the wrong module. Solved with
  `provider_modules.py`, a loader that isolates each import — with
  its own regression tests (`test_provider_modules.py`) that load the
  3 modules in sequence and confirm none of them steps on another.
- **42/42 tests passing**, all against a temporary SQLite, no network
  or credentials.
- Tested end to end in this session: it starts, serves the page,
  syncs in demo mode, classifies with the real logic, persists a
  threshold change, and recalculates status correctly.
- See `fika-sync/gui/README.md` for endpoint detail, demo vs.
  connected mode, and visual design.

**Note on the process:** at the start of this part, Claude didn't see
that it already existed — it fell outside the visible context due to
a history trim — and started building a second GUI from scratch in
parallel (`gui/backend/` + `gui/frontend/`, with its own Flask +
SQLite + design). Before continuing, Claude found it, compared both
implementations, and the existing one turned out to be more complete
(weekly model instead of a single snapshot, real sync with automatic
fallback, historical sparklines, more granular tests). Claude deleted
its own and continued from the existing one, instead of keeping two
competing GUIs in the same repo.

### 🔑 "Connect with one click" (Google + Slack) and guided flow (Cal.com) — new

Until now, the only way to give the GUI real credentials was for a
developer to generate a refresh token or bot token by hand (via OAuth
Playground or the Slack console) and paste it into an environment
variable — a developer flow, not an end-user one. This session added
the real flow:

- **`oauth_service.py`** (new) builds the authorization URLs for
  Google (`prompt=consent` to guarantee `refresh_token` always comes
  back) and Slack, and exchanges the code for tokens.
- **4 new endpoints in `app.py`**: `/oauth/<provider>/start`
  (redirects to the consent screen), `/oauth/<provider>/callback`
  (receives the code, exchanges it, saves it),
  `/oauth/<provider>/disconnect`, and an enriched `/api/status` that
  reports whether each provider is connected via OAuth or via a
  manual environment variable.
- **`models.py`**: two new tables — `oauth_connections` (with logic
  to avoid losing Google's refresh_token if a refresh doesn't resend
  it) and `oauth_states` (single-use CSRF protection, persisted in
  SQLite instead of a Flask session — survives a server restart).
- **`sync_service.py`**: `real_credentials_available()` and a new
  `_build_gcal_client()` helper now prioritize the saved OAuth
  connection over the environment-variable refresh token — both
  paths keep working, without one breaking the other.
- Real "Connect"/"Disconnect" buttons in the GUI (Connections
  section), visually verified with Playwright screenshots: connect,
  see the status reflected in the badges and in `/api/status`,
  disconnect and go back to demo mode.
- **38 new tests** (a full `test_oauth_service.py`, plus additions to
  `test_models.py`, `test_app.py`, `test_sync_service.py`) — the GUI
  suite went from **42 to 80/80** passing.
- **Not tested against real Google/Slack**, same reason as the rest
  of the repo (no network egress to those domains). What is confirmed
  with mocks is all the mechanics — URLs, exchange, CSRF protection,
  credential prioritization. `fika-sync/gui/README.md` has the list
  of what's left to validate (authorized redirect URIs, confirming
  Google actually sends `refresh_token`, `oauth_states` expiration).

**Cal.com was left out of "one click" — and not for lack of time.**
Claude investigated whether Cal.com offers something equivalent to
OAuth ("Platform OAuth Clients" + "Managed Users") and **decided not
to implement it**, for three concrete reasons:

1. It requires being a **paying "Platform" customer** of Cal.com — not
   a free signup like Google Cloud Console or api.slack.com.
2. It doesn't connect the Cal.com account the person already has: it
   creates a *new* identity ("managed user") under the app's OAuth
   Client — it doesn't solve the problem it was trying to solve.
3. The admin documentation for those OAuth Clients is marked
   *"Deprecated"* as of this writing.

Instead, a **guided flow** was built (`POST /api/calcom/connect`):
the GUI opens Cal.com's real API-key generation page in a new tab,
and provides a field to paste it right there — reusing the same
`oauth_connections` table and the same "Connected ✓ / Disconnect" UI
as Google and Slack. It's not one click, it's two steps, but nobody
has to go hunting for an environment variable.
`sync_service._build_calcom_client()` prioritizes that saved key over
the environment `CALCOM_API_KEY`, the same pattern as Google. **8 new
tests** (`test_calcom_connect_*` in `test_app.py`,
`test_build_calcom_client_*` in `test_sync_service.py`).

### ⚙️ Real configuration: team, notifications, workflows — new

The GUI went from "read-only with two threshold inputs" to having
real configuration on 3 fronts, at explicit request after showing it
— the feedback was "too simple, doesn't offer much configuration":

- **Team management** (`POST/PUT/DELETE /api/team/<person>`): add,
  edit and remove people from the "Team" section. Removing someone
  also deletes their hours history. Adding someone triggers an
  automatic sync so the person shows up on the dashboard right away —
  found and fixed during this session (without it, they'd stay in
  "Team" but invisible on the cards until the next sync).
- **Publish to Slack, with a real effect** (`POST /api/publish-now` →
  `sync_service.publish_summary_now()`): builds the report with
  `team_health_analyzer.summarize_team_report` and actually publishes
  it with `slack.post_message`, using the bot token from the OAuth
  connection — not a decorative button.
- **Background auto-sync** (`start_background_scheduler`): a daemon
  thread runs `sync_now()` according to the configured frequency
  (and publishes only if explicitly checked). The "should this run
  now?" decision is pure logic and is 100% tested
  (`_should_auto_sync`); the thread itself is the one piece in this
  whole session without an automatic test — testing real thread
  timing isn't practical in pytest. It only starts from `python3
  app.py` directly (confirmed that importing the module doesn't
  trigger it by accident, not even under Flask's reloader with
  `debug=True`, which runs `__main__` twice if unprotected).
- **Workflows: enabling/disabling is declarative, it doesn't control
  anything live.** This is important and is called out in 3 places
  (code, GUI README, the UI itself with "runs here" vs. "declarative"
  badges): the toggles for `meeting-debt`, `onboarding-automator` and
  `budget-guardian` save a preference in SQLite, but there's no
  RailCall integration in this repo yet that reads that preference.
  Pretending the toggle "activates" the workflow would have been
  exactly the kind of thing this project has been avoiding since the
  original diagnosis.
- **Bug found and fixed along the way**: the "Add person" form was
  visible by default instead of hidden — the CSS (`display: flex` on
  the class) overrode the HTML `hidden` attribute. Fixed with
  `.team-manager__form[hidden] { display: none; }`.
- **48 new tests** across `test_models.py`, `test_app.py` and
  `test_sync_service.py` — the GUI suite ended at **136/136**. Also
  verified visually with Playwright: adding a person, toggling a
  workflow, saving notifications, and trying to publish without Slack
  connected (correct 409 error, not a silent failure).

### 📅 Google Calendar was a fake connection — fixed to per-person

Direct feedback: *"the GUI doesn't interact with Google Calendar or
allow for as simple a configuration as possible for the end user"*.
Investigated before assuming anything: the code DID call
`gcal.list_events` for real, but with a real architecture bug — the
"Connect Google" button authenticated **a single account**, and
`_sync_real()` tried to use that same token to read the calendar of
**every person on the team**. That doesn't work with the real Google
API: one person's token can't read another person's calendar.

Fixed with a **per-person** connection:

- New `person_oauth_connections` table — each person has their own
  `refresh_token`.
- "Connect my calendar" button on each row in "Team"
  (`GET /oauth/google/start/<person>`), reusing the same fixed
  `redirect_uri` as always — the person travels in the `state`, not
  in the URL, because Google requires pre-registering redirect URIs
  and it's not possible to pre-register one for every future team
  member.
- `_sync_real()` no longer depends on a global connection: whoever
  hasn't connected their calendar is skipped without breaking the
  rest of the sync, and it's recorded explicitly
  (`skipped_calendar_connection`), not hidden.
- `sync_now()` no longer requires the calendar to be resolved to
  enter real mode — Cal.com alone is enough as a base; Google
  Calendar is an optional per-person enrichment.
- Sheets and Slack were left as they were (app-level connection) on
  purpose — for those, a single account for the whole team does make
  sense; the problem was specific to reading individual calendars.
- **Found and fixed two of Claude's own bugs along the way** before
  they reached the tests: Claude nearly put a list inside a dict that
  was supposed to only hold numeric hours (which would have broken
  `record_meeting_hours`), and the gate deciding "should we enter
  real mode?" still required the old global connection that no
  longer made sense with the new model.
- **25 new tests** — the GUI suite went from 136 to **161/161**. Also
  verified visually with Playwright: connecting one person's
  calendar, seeing the status reflected in their row, disconnecting
  it, and confirming the other people aren't affected.

## 🎉 Milestone: the workflow's 3 external providers are written and tested

`calcom-pro`, `gcal` and `slack` — the three providers listed in
`engine_spec.json` — now have code and tests. None has been validated
against a real account/workspace yet, but the full `workflow.csv` no
longer has any "phantom" node: every referenced action really exists
in some module. This was verified programmatically, not by eye (see
the script in this session's history).

## 🐛 Bug found and fixed during this session

While building `slack/`, the full DAG's programmatic validation
detected that the `update_threshold` node in `workflow.csv` pointed
to `team-health-analyzer.classify_team_health` — an action that has
nothing to do with persisting a threshold. It was a reference error
introduced when `workflow.csv` was originally written. Fixed by:

- Adding the real `update_threshold` action to
  `team-health-analyzer/actions.py` (with 3 new tests).
- Adding a `verify_and_parse_threshold_click` node (`slack` provider,
  uses `verify_slack_signature` + `parse_interactive_payload`) that
  `update_threshold` now depends on, so the flow is explicit: first
  the click is validated as authentic, only then is the change
  persisted.

This is documented rather than hidden — it's exactly the kind of
error that the DAG's automatic validation exists to catch.

## 🧪 Validation infrastructure (without being able to run it directly)

This environment has no network egress to `api.cal.com`,
`googleapis.com` or `slack.com` (confirmed with `curl`, which return
a 403 from the egress proxy) — only to package domains (PyPI, npm)
and GitHub. That's why real validation couldn't be run directly.

Instead, what was built makes it trivial for you to run validation
yourself:

- **`tests/test_integration.py`** in `calcom-pro`, `gcal`, `slack`
  and `sheets` — call the real APIs, but **don't run by default**:
  they require explicit environment variables (`RUN_LIVE_TESTS=1` +
  credentials, and `ALLOW_LIVE_WRITES=1` for the ones that
  create/modify data). Verified that they skip cleanly without those
  variables (7 `SKIPPED`, the 71 unit tests still pass).
- **`VALIDATION.md`** — a step-by-step checklist for the 4
  integrations: which account to create, which variables to set,
  what to check by hand afterward, and which files to update when
  everything works. Updated in this session to add the `sheets`
  section (the module existed but not its `test_integration.py` nor
  its checklist section — this was found and fixed).
- **`CONTRIBUTING.md`** (new in this session) — documents the pattern
  followed by the 7 modules and 4 workflows, so adding a new one
  means copying the structure instead of reinventing it. Includes the
  `client.py`/`actions.py` name collision between provider modules,
  so the same bug doesn't get rediscovered.

## 🔬 Validation against live official documentation (2026-08-30)

Beyond the integration-test infrastructure, Claude did what it can do
without access to those APIs: cross-checked every endpoint/payload
against the live official documentation (not against memory), and
fixed what was found to be wrong.

**Real bugs found and fixed:**

- `calcom-pro`: `cal-api-version` was outdated (`2024-08-13`) and, on
  top of that, **used a single value for all endpoints**, when in
  reality Cal.com versions each endpoint separately —
  `GET /bookings` needs `2026-05-01`, `POST /bookings` needs
  `2026-02-25`. The client was fixed to accept a version per request,
  and `actions.py` now passes the correct one on each call.
- `calcom-pro`: `update_booking` assumed a generic
  `PATCH /v2/bookings/{uid}` that **could not be found documented**.
  What does exist are specific sub-endpoints (e.g.
  `/bookings/{uid}/location`). It was left with an explicit warning
  in the code — don't use that function as-is without checking the
  booking-editing documentation first.
- `gcal` and `slack`: endpoints, field names and payload format match
  the verified official documentation — no discrepancies found.

**What documentation review CANNOT confirm** (a real account is
needed for this, see `VALIDATION.md`): exact behavior on undocumented
errors, real rate limits, whether the "Focus Time" `event_type_id`
behaves as expected, how long a Google access token actually lasts in
practice, and what a Slack message with buttons looks like in a real
client.

## ❌ Doesn't exist yet (pending, in priority order)

1. **Run `VALIDATION.md` with real accounts/workspaces** — this can't
   be advanced further without real access; the infrastructure is
   ready (all 4 integrations, including `sheets`), what's missing is
   for someone with network access to those APIs to run it.
2. **`calcom-pro`'s `update_booking`** — review Cal.com v2's
   booking-editing documentation and fix the endpoint (see the
   warning in the code). Independent of point 1.
3. **Validate the "Connect with one click" OAuth flow** against real
   Google and Slack — needs a "Web application" type OAuth Client
   with the correct redirect URI authorized (different from
   `VALIDATION.md`'s manual flow, which uses "Desktop app").
   **For Slack specifically, "Public Distribution" also needs to be
   activated** in the app dashboard (Manage Distribution → Activate
   Public Distribution) — without this, the app can only be installed
   in the workspace where it was created, and any user from another
   workspace using the "Connect Slack" button will fail (not a code
   bug). No Slack review required, it's self-service. See section 5
   of `VALIDATION.md` for the full detail.
4. **Validate Cal.com's guided flow** (`/api/calcom/connect`) against
   a real account — confirm that an API key generated from Cal.com's
   real page is saved and used correctly end to end (this is simpler
   to validate than the OAuth flow, since it doesn't depend on a
   pre-configured redirect URI).
5. **Publishing to Slack is still the workflow's responsibility, not
   the GUI's** — the GUI can now *connect* Slack (save the bot
   token), but doesn't use it to post messages. This is a deliberate
   design decision, not a limitation to fix.
6. **Confirm the unvalidated RailCall capabilities**:
   `webhook_calendar_change` (meeting-debt), `get_spend_log` and
   `pause_workflow` (budget-guardian). Without these, those two
   workflows can't run autonomously — see each one's README for the
   fallback plan.
7. **Test the 3 level-3 workflows end to end** — each module they
   chain together already has individual tests, but no full DAG has
   been run against real RailCall.
8. Validate the 4 `workflow.csv` and `engine_spec.json` files against
   the real RailCall compiler (`railcall audit workflow.csv`) —
   recommended only after point 1.

## How to run the tests

```bash
pip install pytest requests flask --break-system-packages   # if needed

# Module unit tests (mocks, always run)
for m in team-health-analyzer calcom-pro gcal slack sheets meeting-debt-tracker budget-guardian-core; do
  echo "== $m =="
  (cd modules/$m && python3 -m pytest tests/test_actions.py -q 2>/dev/null || python3 -m pytest tests/ -q)
done

# GUI tests, including the OAuth flow (temporary SQLite, no network)
(cd fika-sync/gui && python3 -m pytest tests/ -q)

# Integration tests (require real credentials; see VALIDATION.md)
# these skip automatically if the environment variables aren't set
```

Current status: **71/71 module unit tests + 161/161 GUI tests
passing** (232 total), verified on 2026-08-30. The 6 integration
tests (`test_integration.py` in calcom-pro, gcal and slack) are
written but not run — see `VALIDATION.md`.

## Recommendation for the next step

Code is no longer the bottleneck: the 7 modules, the GUI (with the
real "Connect with one click" flow), and the 4 workflows (`fika-sync`
plus the 3 level-3 ones) are all written and tested. The only thing
left to move this from "written" to "operational" is running
`VALIDATION.md` with real test credentials (now including setting up
"Web application" type OAuth Clients for the GUI flow, not just the
manual developer flow), and confirming the 3 unvalidated RailCall
capabilities (`webhook_calendar_change`, `get_spend_log`,
`pause_workflow`) — that's exactly what the original analysis
identified as the project's main blocker, and it's now reduced to
"follow a checklist" instead of "write new code".
