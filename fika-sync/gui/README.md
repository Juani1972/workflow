# fika-sync/gui

Fika Sync's real dashboard. Replaces the two static HTML files the
original repo analysis described (mockups with no data connection,
that lost everything on page reload) with a Flask app with real
persistence.

## What's real here

- **Real SQLite persistence** (`models.py`). The data —team,
  thresholds, weekly meeting hours, sync log— survives a page reload
  and a server restart. This was one of the three underlying problems
  from the original analysis; it no longer applies to this GUI.
- **Real health classification**: `/api/metrics` uses
  `team_health_analyzer.classify_team_health` and
  `.summarize_team_report` — the same tested functions
  `fika-sync/workflow.csv` would use in production, not a JavaScript
  reimplementation.
- **Genuinely editable thresholds**: each card's "Save threshold"
  button persists to SQLite via `POST /api/thresholds`, and the
  classification is recalculated with the new value the next time
  `/api/metrics` is requested.
- **Real history**: every sync appends a row to `meeting_hours`,
  doesn't overwrite it — that's why each card's sparkline can show
  previous weeks.
- **Connect Slack, and Google (for Sheets), with one click**
  (`oauth_service.py`). Previously, the only way for `sheets`/`slack`
  to have credentials was for someone to generate a refresh token or
  bot token by hand (via OAuth Playground or the Slack console) and
  paste it into an environment variable — a developer flow, not an
  end-user one. Now there's a real button: `GET /oauth/<provider>/start`
  redirects to the consent screen, `GET /oauth/<provider>/callback`
  receives the code, exchanges it for a token, and saves it in SQLite
  (`oauth_connections`) — the user never touches any environment
  variable. *Application*-level credentials (`GOOGLE_CLIENT_ID`/`SECRET`,
  `SLACK_CLIENT_ID`/`SECRET`) are still environment variables, but
  those are configured once by whoever deploys the app, not by each
  user. The manual environment-variable flow (`GOOGLE_REFRESH_TOKEN`,
  `SLACK_BOT_TOKEN`) is still supported in parallel.
- **Slack also has a pasted-token path** (`POST /api/slack/connect-token`,
  `oauth_service.validate_slack_bot_token`) alongside the one-click
  redirect. This exists because Slack requires PKCE for a redirect_uri
  on `127.0.0.1`/`localhost` without HTTPS, which the redirect flow
  can hit on a purely local install — pasting a Bot User OAuth Token
  generated from "Install to workspace" in api.slack.com/apps skips
  redirect_uri entirely. The token is validated against Slack's real
  `auth.test` before saving, same as the OAuth exchange.
- **Google Calendar connects PER PERSON, not with this same global
  button** — see "Why the calendar is a per-person connection" below.
  This is this session's most important fix: previously, a single
  global Google connection tried to read the calendar of the *entire
  team*, and that's not how the real Google API works — one person's
  token can't read another person's calendar. Now each row in the
  "Team" section has its own "Connect my calendar" button
  (`GET /oauth/google/start/<person>`).
- **Cal.com: a *guided* flow, not OAuth** (`POST /api/calcom/connect`).
  Cal.com doesn't offer OAuth for personal/free accounts — see "Why
  Cal.com doesn't have OAuth" below. Instead, the GUI opens Cal.com's
  real API-key generation page (in a new tab) and gives a field to
  paste it right there — saved in the same `oauth_connections` table
  (with `token_type="api_key"`), reusing all the connect/disconnect
  infrastructure that already existed for Slack. It's not "one
  click", it's two steps, but the person never touches an environment
  variable or has to go hunting for where the settings page is.
- **Real team management**: add, edit and remove people from the
  "Team" section — `POST/PUT/DELETE /api/team/<person>`. Removing
  someone also deletes their hours history (`meeting_hours`), no
  orphan rows are left. When someone is added, the GUI triggers a
  sync automatically so they show up as a card on the dashboard
  without having to press "Sync now" by hand.
- **Genuinely publish to Slack**: the "Publish summary now" button
  (in the "Notifications" section) calls
  `sync_service.publish_summary_now()`, which builds the report with
  `team_health_analyzer.summarize_team_report` and publishes it with
  `slack.post_message` to the configured channel, using the bot token
  from the saved OAuth connection. This **does have a real effect** —
  unlike the workflow toggles (see below), this genuinely sends a
  Slack message if Slack is connected.
- **Background auto-sync** (`sync_service.start_background_scheduler`):
  if a frequency other than "manual only" is configured, a daemon
  thread runs `sync_now()` (and `publish_summary_now()` if
  "auto_publish_on_sync" is checked) whenever it's due according to
  that frequency. The "is it due now?" decision is pure logic
  (`_should_auto_sync`, 100% tested); the thread itself is "best
  effort" — it has no automatic tests because testing real timing
  with a background thread isn't practical in a pytest suite, and **it
  only starts from `python3 app.py` directly**, never when the module
  is imported (confirmed: importing `app.py` doesn't create new
  threads).

## Configuration: what's real and what's declarative

With this session's expansion, the GUI went from "just a read-only
dashboard with two threshold inputs" — but not everything new has the
same level of "reality", and it's important not to confuse them:

| Section | Effect |
|---|---|
| **Team** (add/edit/remove people) | 100% real — persists to SQLite, affects the dashboard and future syncs. |
| **Notifications → Slack channel + "Publish now"** | 100% real — actually publishes if Slack is connected. |
| **Notifications → auto-sync frequency** | Real, with the background scheduler described above. |
| **Workflows (enable/disable)** | **Declarative, doesn't control anything live.** See the next section. |

### Workflows: why the toggles don't "do" anything yet

`meeting-debt`, `onboarding-automator` and `budget-guardian` are
`workflow.csv` definitions meant to run on **RailCall**, which isn't
part of this app. Enabling the "Onboarding Automator" toggle in the
GUI saves `enabled=true` in the `workflow_settings` table — it
doesn't trigger anything, doesn't call RailCall (that integration
doesn't exist in this repo), doesn't change `fika-sync/gui/`'s
behavior. It's a declared preference for the day a real RailCall
integration exists, and so the UI is honest about which workflows are
"meant to be active" without pretending they already are. The "Fika
Sync" toggle is disabled on purpose (always on, can't be turned off)
because that one literally IS the code that renders this dashboard.

## Why the calendar is a per-person connection

**The architecture bug fixed in this session.** The original "Connect
Google" flow (the same button that today only covers Sheets)
authenticated a single account, and `sync_service._sync_real()` tried
to use THAT token to read the calendar of *every team member* by
calling `gcal.list_events(client, person.gcal_email, ...)`. That
doesn't work with the real Google Calendar API: one person's token
can't read another person's calendar, unless that other person shared
it explicitly, or there's a service account with domain-wide
delegation (requires being a Google Workspace admin — not a
reasonable option for "as simple as possible for the end user").

**The fix:**

- New `person_oauth_connections` table (`person`, `provider` as
  composite key) — each person has their own `refresh_token`,
  independent of everyone else.
- `GET /oauth/google/start/<person>` — the "Connect my calendar"
  button on each row in "Team". Uses the **same** fixed `redirect_uri`
  as the app-level connection (`/oauth/google/callback`) — which
  person it is travels in the `state` (saved in `oauth_states`,
  `person` column), not in the callback URL, because Google requires
  the redirect_uri to be pre-registered exactly as-is in Cloud
  Console, and a different one can't be pre-registered for every
  future team member.
- `sync_service._build_gcal_client_for_person(gcal_actions, person)`
  replaces the old global `_build_gcal_client()` — if that person
  hasn't connected their calendar, it returns `None` and
  `_sync_real()` skips them (without breaking the rest of the team's
  sync), recording it explicitly in `sync_log` and in
  `/api/metrics`'s response (`skipped_calendar_connection`) — never
  hidden.
- `real_credentials_available()["google_calendar"]` now means "at
  least one person connected their calendar", not "there's an
  app-level connection" — and `sync_now()` no longer requires the
  calendar to be resolved to enter real mode: Cal.com alone is enough
  as a base (gives data for the whole team), Google Calendar is an
  optional per-person enrichment.

**What stays the same**: Sheets and Slack do make sense with a single
app-level connection — anyone with that token can export/publish for
the whole team, no need for each person to authorize their own.
That's why those two still use `oauth_connections` (the app-level
table), and only the calendar uses `person_oauth_connections`.

## Why Cal.com is also a per-person connection

**The same architecture bug, in the other provider.** Before this
fix, Cal.com only had an app-level connection (a key pasted into
"Connections"), and `_sync_real()` fetched *all* bookings with that
single key (`list_bookings`) and distributed them among people by
filtering client-side on `attendee.email == gcal_email`. That works
well if that key belongs to a paying Cal.com **Team** plan (with
visibility over the whole team's bookings), but a personal, free
Cal.com account's API key **only sees that account's bookings** — not
their teammates', no matter that they're on the same team here.

**The fix — same pattern as the calendar, adapted to the fact that
Cal.com doesn't offer OAuth for free accounts (see the section
below):**

- New `person_api_keys` table (`person`, `provider` as composite key)
  — each person has their own API key, independent of everyone else.
  No `refresh_token` because a Cal.com key doesn't expire or renew
  itself, unlike a Google access token.
- `POST /api/calcom/connect/<person>` — the "Connect" button on each
  person's row in "Team", next to "Connect my calendar". Same
  validation as the app-level flow (the key has to start with
  `cal_`), but saved in `person_api_keys` instead of
  `oauth_connections`.
- `sync_service._build_calcom_client_for_person(calcom_actions,
  person)` — if that person connected their own key, `_sync_real()`
  makes **its own call** to `list_bookings` with that key (without
  filtering by email — everything that account returns belongs to
  them). If they didn't connect one, it falls back to the app-level
  fallback client (previous behavior, without breaking teams already
  using a Team-plan key), and only if there's no fallback available
  either does it get recorded in `skipped_calcom_connection` — never
  hidden, same spirit as `skipped_calendar_connection`.
- `real_credentials_available()["calcom"]` now also counts "at least
  one person connected their own key", not just the app-level
  connection or `CALCOM_API_KEY`.

**Cost of this**: if the team has 4 people and all 4 connect their
own key, `_sync_real()` makes 4 calls to `list_bookings` instead of
1 — more traffic to the Cal.com API, but the data each call returns
is correct (that person's bookings, not a guess by email over a
shared list).

## Configuring Google/Slack from the GUI, without touching .env

**What this simplifies.** Previously, configuring Google or Slack's
Client ID/Secret (the *application's* credentials, not each person's)
required editing `fika-sync/gui/.env` by hand and restarting the
server — a terminal step, even if only once. Now whoever administers
the installation can paste them directly into the **Connections**
tab, in the amber "App configuration" card that appears at the very
top: a direct link to where each credential is generated, two fields
to paste it, a "Save" button — and it just works, without restarting
anything.

- New `app_oauth_credentials` table (`provider`, `client_id`,
  `client_secret`) — separate from `oauth_connections` (which stores
  *user* tokens, not *app* credentials) and from
  `person_oauth_connections`/`person_api_keys` (*personal*
  connections). Three distinct levels, three distinct tables, on
  purpose — mixing "who am I to Google" with "who is this team
  member" would have been confusing to read later.
- `oauth_service._resolve_app_credentials(provider)` prioritizes
  what's saved here over the corresponding environment variable —
  same priority order `sync_service._build_calcom_client` already
  used (guided > env var). `.env` keeps working exactly the same for
  whoever prefers that path; nothing breaks if it was already
  configured that way.
- `client_secret` is **never returned** in any API response
  (`GET /api/admin/app-credentials` only reports whether it's
  configured, where it came from, and a preview of the `client_id`,
  which isn't secret) — pasting it in again is the only way to "see"
  it again, on purpose.
- Same as the rest of this repo's credentials (see
  `oauth_connections`, `person_api_keys`), `client_secret` is stored
  in plain text in `fika_sync.db` — this tool never claimed to
  encrypt secrets at rest, it's meant to run locally, not as an
  exposed service. See "What's still demo" below.
- "Remove" button next to each already-configured provider — deletes
  what was saved from the GUI; if an environment variable is set, the
  app falls back to that (it doesn't just stop working).

**What doesn't change**: this is still *application*-level
configuration (the same for the whole team), not per-person — there's
no concept of an "admin user" or login in this app. Anyone with
access to the GUI can see and touch this section, exactly the same
trust model the rest of the tabs already had.

## Personal Slack DMs — "per person" without duplicating credentials

Unlike the calendar and Cal.com, **Slack doesn't need each person to
connect anything of their own** — it's still a single shared bot
token, configured once by whoever administers the app (see "Why
Cal.com doesn't have OAuth" below for the same reasoning applied to
app vs. person credentials). What IS per-person here is **who the
message reaches**, not which credential sends it.

- `notification_settings.personal_dms_enabled` (new column, migrated
  with `ALTER TABLE` in `init_db()` for anyone who already had the
  database created from before) — toggle in the Notifications tab:
  "Send a private DM to each person in 🟡/🔴 after every sync".
- `sync_service.send_personal_dm_notifications()` — goes through the
  team, and sends a `chat.postMessage` with
  `channel=<their slack_user_id>` instead of a channel to anyone in
  🟡/🔴 (nothing is sent to 🟢, to avoid "everything's fine" noise on
  every sync) — Slack opens the DM automatically if it didn't already
  exist. Uses the `slack_user_id` field that already existed on every
  "Team" row before this fix, but wasn't used for anything until now.
- Best-effort per person: if a DM fails (no `slack_user_id` set,
  network error, permissions), it's recorded in the result
  (`skipped_no_slack_id` / `error: ...`) and the rest continue — one
  individual failure never stops the whole team. The "Send personal
  DMs now" button in the Notifications tab shows the full result,
  person by person.
- `run_auto_sync_if_due()` triggers it automatically after every sync
  if the toggle is on, same pattern as `auto_publish_on_sync` — and
  the same way, a `PublishError` (Slack not connected) doesn't take
  down the auto-sync, it just skips that step.

**Not confirmed against a real workspace** (same caveat as
`post_message` in general, see `modules/slack/actions.py`): whether
`chat.postMessage` with a `user_id` as `channel` opens the DM without
needing the `im:write` scope separately. The currently connected
scope is only `chat:write` — if Slack rejects it,
`send_personal_dm_notifications` catches it as `error: ...` for that
person, it doesn't break the rest.

## Why Cal.com doesn't have OAuth (and what was evaluated)

Cal.com does have an OAuth-like mechanism — "Platform OAuth Clients" +
"Managed Users" — but it **doesn't solve the same problem** as the
Google/Slack flow:

- Requires being a **paying "Platform" customer** of Cal.com (a
  commercial relationship, not a free signup like Google Cloud
  Console or api.slack.com).
- Doesn't connect the Cal.com account the person already has: it
  creates a *new* identity ("managed user") under the app's OAuth
  Client. If someone already has meetings and availability set up on
  their real Cal.com account, this mechanism doesn't use them.
- Cal.com's "Update an OAuth client" documentation is marked
  *"Deprecated: Platform OAuth Clients"* as of this writing — a sign
  the mechanism might be changing.

For these three reasons, building that was ruled out in favor of the
guided flow — see the session thread where this was compared against
the alternative if more context is needed.

## What's still demo (and why, honestly)

- **Without Cal.com + Google credentials configured** (the default
  case in this environment, which has no network egress to those
  APIs), `/api/sync` generates deterministic meeting hours per
  person+week and saves them with `source="demo"` — never silently
  mixed with real data. The `source` field in `/api/metrics` and
  `/api/sync`'s responses always reflects where the data came from.
- **With credentials configured**, `/api/sync` attempts connected
  mode (`sync_service._sync_real`): fetches Google Calendar events
  (confirmed format) and Cal.com bookings (**best-effort, unconfirmed
  format** — see the warning in `_calcom_bookings_to_records`), and
  combines them with the same real `calculate_meeting_load` function.
  If something fails (invalid credentials, Cal.com format different
  from assumed), the error is logged to `sync_log` and the GUI falls
  back to demo mode for that run instead of breaking — it never makes
  up real-looking numbers when the real sync failed.
- **Slack can be *connected* from the GUI, but isn't used to publish
  here.** The "Connect Slack" button saves a real bot token in
  `oauth_connections` — that's genuine. But publishing the summary
  (`chat.postMessage`) is still the workflow's responsibility
  (`publish_slack_summary` in `workflow.csv`), not something this GUI
  triggers. Connecting Slack here serves to have the token ready for
  when the real workflow needs it, not for this GUI itself to post
  messages.

## ⚠️ About the OAuth flow: what's left to validate

**Update:** since `validated_at`/`mark_connection_validated` was
added (see `models.py` and `/api/status`), the app itself now
distinguishes "connected (not validated)" from "connected ✓" — Cal.com
is tested with a real call to `list_bookings` before saving the key
(app-level and per-person), and Google/Slack are marked validated the
moment `oauth_callback` confirms a successful code-for-token exchange.
This replaces the old fixed `"validated_against_real_account": false`
that `/api/status` used to have. It's still true that this development
environment has no network egress to Google/Slack to test it in an
automated test — the real validation is done by the person using the
GUI against their own account, and the app confirms it right then.

**Not tested against real Google/Slack** — same reason as the rest of
the repo: this environment has no network egress to those domains.
What IS tested (with mocks) is all the mechanics: building
authorization URLs, exchanging code for token, CSRF protection via
`oauth_states` (single-use), and that `sync_service.py` actually
prioritizes the saved connection over the environment refresh token.
Before using this with real users, the following is needed:

1. Create an OAuth Client in Google Cloud Console ("Web application"
   type, not "Desktop app" like in `VALIDATION.md`'s manual flow)
   with the redirect URI `http://YOUR_DOMAIN/oauth/google/callback`
   authorized.
2. Create an app at `api.slack.com/apps` with the redirect URL
   `http://YOUR_DOMAIN/oauth/slack/callback` configured under "OAuth &
   Permissions".
3. **Activate "Public Distribution" on the Slack app** (dashboard →
   "Manage Distribution" → complete the checklist → "Activate Public
   Distribution"). Without this, the Slack app can only be installed
   in the workspace where it was created — any user from another
   workspace using the GUI's "Connect Slack" button will fail, not
   due to a code bug but because Slack doesn't allow it yet. Doesn't
   require Slack review; that's a separate, optional step
   ("Submit to App Directory").
4. Run the full flow once by hand and confirm Google actually sends
   `refresh_token` (it should, thanks to `prompt=consent`, but this
   isn't confirmed against a real consent).
5. `oauth_states` don't have an expiration yet — if someone starts the
   flow and abandons it, that state stays in the database forever
   (harmless, but it's clutter accumulating). Add periodic cleanup or
   a TTL if this ever goes to real production.

## Installation and use

```bash
cd fika-sync/gui
pip install -r requirements.txt --break-system-packages   # or in your venv
python3 app.py
```

Open `http://127.0.0.1:5000`. The first time the team's status is
requested, the GUI syncs automatically (in demo mode if there are no
credentials) so it doesn't show an empty dashboard.

### Connecting real accounts from the GUI (step by step)

**Cal.com — each person connects their own, no prior setup:**

1. The person generates their own API key at
   [app.cal.com/settings/developer/api-keys](https://app.cal.com/settings/developer/api-keys).
2. On the **Team** tab, in their own row, paste the key into the
   "Paste key (cal_...)" field → "Connect". No need to touch any file
   or ask whoever administers the app for anything.

Alternative (not recommended for more than one person, see "Why
Cal.com is also a per-person connection" above): paste ONE key at the
app level on the **Connections** tab — this only gives real data for
the whole team if it's a key from a paying Cal.com **Team** plan; with
a free account, that key only sees the bookings of whoever generated
it.

**Google Calendar — each person connects their own, with a one-time
app setup:**

Google requires registering an "application" (Client ID/Secret)
before anyone can authorize anything — that's a one-time step for
whoever administers this GUI, not something each person repeats. Two
ways to do it, with the same result:

- **From the GUI (recommended)**: **Connections** tab → amber "App
  configuration" card → follow the link to Google Cloud Console to
  create the Client ID/Secret → paste it right there → "Save". Works
  right away, without restarting the server.
- **Via file** (the path that existed before, still works):
  `cp fika-sync/gui/.env.example fika-sync/gui/.env`, fill in
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` following the file's own
  instructions, restart `python3 app.py`.

Either path leaves the same thing ready:

1. Each person goes to their row on **Team** → "Connect my calendar"
   → authorizes on Google's consent screen → comes back connected.

**Slack — a single app-level connection** (makes sense shared: anyone
with the bot token can publish to the team channel, no need for each
person to authorize their own):

1. Same place as Google: the "App configuration" card in
   **Connections** (or `SLACK_CLIENT_ID`/`SLACK_CLIENT_SECRET` in
   `.env`, if you prefer that path).
2. **Connections** tab → "Connect Slack".

Without either credential configured (neither from the GUI nor via
`.env`), the **Connections** tab doesn't even show the "Connect
Google"/"Connect Slack" buttons — the amber card above explicitly
says "Not configured" for that provider.

### Alternative: manual environment variables (without using the GUI)

Developer path, without going through the "Connect" buttons: set the
full credentials from `fika-sync/.env.example`
(`GOOGLE_REFRESH_TOKEN`, `SLACK_BOT_TOKEN`, `CALCOM_API_KEY`) before
running `python3 app.py` — see `VALIDATION.md` at the repo root for
how to get them from a test account. These still act as an app-level
fallback, with the same limitation as the Cal.com key pasted from the
GUI: they work for the whole team only if they're from a plan that
provides that visibility (Cal.com Team, or a Google service account
with domain-wide delegation).

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/` | Serves the dashboard |
| GET | `/api/status` | Credentials configured per provider (doesn't confirm they're valid) |
| GET | `/api/admin/app-credentials` | Status per provider: `{"configured", "source": "guided"\|"env_manual"\|null, "client_id_preview"}` — never returns the `client_secret` |
| POST | `/api/admin/app-credentials/<provider>` | `{"client_id", "client_secret"}` — `provider` = `google` \| `slack`. Saves the app credentials from the GUI, without touching `.env` |
| POST | `/api/admin/app-credentials/<provider>/reset` | Deletes what's saved from the GUI for that provider; falls back to the environment variable if set |
| GET | `/api/team` | Team with their current thresholds + `gcal_connected` and `calcom_connected` per person |
| POST | `/api/team` | `{"person", "calcom_username"?, "gcal_email"?, "slack_user_id"?, "yellow_hours"?, "red_hours"?}` — adds a person |
| PUT | `/api/team/<person>` | `{"calcom_username"?, "gcal_email"?, "slack_user_id"?}` — edits identity (not thresholds) |
| DELETE | `/api/team/<person>` | Removes the person, deletes their hours history and personal connections (calendar + Cal.com) |
| POST | `/api/calcom/connect/<person>` | `{"api_key"}` — connects that specific person's Cal.com key |
| POST | `/api/calcom/disconnect/<person>` | Disconnects that person's Cal.com key |
| GET | `/api/metrics` | Hours + health + report for the current week (syncs if there's no data yet; includes `skipped_calendar_connection` and `skipped_calcom_connection` if someone was missing a connection) |
| GET | `/api/history/<person>` | A person's last 8 weeks |
| POST | `/api/sync` | Forces a sync |
| POST | `/api/thresholds` | `{"person", "field", "value"}` — persists a threshold |
| GET | `/api/sync-log` | Last 10 syncs |
| POST | `/api/reset-demo` | `{"confirm": true}` — wipes everything and reseeds from `config/*.example` |
| GET | `/api/workflow-settings` | Status of the 4 workflow toggles (declarative, see above) |
| POST | `/api/workflow-settings/<workflow_id>` | `{"enabled": bool}` |
| GET | `/api/notification-settings` | Slack channel, auto-sync frequency, auto-publish, personal DMs |
| POST | `/api/notification-settings` | `{"slack_channel"?, "sync_frequency_minutes"?, "auto_publish_on_sync"?, "personal_dms_enabled"?}` |
| POST | `/api/publish-now` | Publishes the summary to Slack right now (409 if Slack isn't connected or there's no channel) |
| POST | `/api/notifications/send-personal-dms` | Sends a private DM to each person in 🟡/🔴 with a `slack_user_id` set (409 if Slack isn't connected); returns `{"results": {person: "sent"\|"skipped_green"\|"skipped_no_slack_id"\|"error: ..."}}` |
| GET | `/oauth/<provider>/start` | `provider` = `google` \| `slack`. App-level connection (Sheets/Slack). Redirects to the consent screen |
| GET | `/oauth/google/start/<person>` | Connects THAT specific person's calendar — same fixed redirect_uri, the person travels in the `state` |
| GET | `/oauth/<provider>/callback` | Receives the code, exchanges it for a token; if the `state` had a person associated, saves it per-person, otherwise at the app level |
| POST | `/oauth/<provider>/disconnect` | Deletes that provider's saved app-level connection |
| POST | `/oauth/google/disconnect/<person>` | Deletes that specific person's calendar connection |
| POST | `/api/calcom/connect` | `{"api_key": "cal_..."}` — guided flow, not OAuth (see above) |
| POST | `/api/calcom/disconnect` | Deletes the saved Cal.com connection |
| POST | `/api/slack/connect-token` | `{"bot_token": "xoxb-..."}` — alternative to `/oauth/slack/start` for pasting a Bot User OAuth Token by hand; validated against Slack's `auth.test` before saving |

## Visual design

Its own identity ("coffee-break card"): each person is a card with a
status stamp (🟢/🟡/🔴) and a ticket perforation, instead of a generic
traffic light. Linen/pine/amber/brick palette — see tokens in
`static/style.css`. Typography: Fraunces (display), IBM Plex
Sans (body), IBM Plex Mono (data and hours).

## Tests

```bash
cd fika-sync/gui
python3 -m pytest tests/ -v
```

All of them run against a temporary SQLite database
(`FIKA_SYNC_DB_PATH`, see `tests/conftest.py`) — never touching the
real `fika_sync.db`. None require network or credentials; the
fallback to demo when the real sync fails is tested by simulating the
error, not by calling a real API.

Current status: **161/161 tests passing** (verified on 2026-08-30):
`test_models.py`, `test_sync_service.py`, `test_app.py`,
`test_provider_modules.py` (added to directly test the loader that
avoids the `import actions` clash between modules), and
`test_oauth_service.py` (for the "Connect with one click" flow —
building authorization URLs and exchanging code for token, both
mocked, no real network calls). Cal.com's guided flow doesn't have its
own test file — its tests live alongside the rest of each layer's
(`test_app.py` for the endpoints, `test_sync_service.py` for
`_build_calcom_client`). Same for team management, workflow settings,
notification settings, `publish_summary_now`, and the per-person
calendar flow (25 new tests across `test_models.py`, `test_app.py`
and `test_sync_service.py` — no dedicated file, added to each layer's
existing ones).

**The auto-sync scheduler thread (`start_background_scheduler`) is
this session's only piece without an automatic test** — testing real
timing with a background thread isn't practical in a pytest suite.
What IS 100% tested is the pure decision logic that thread calls in a
loop (`_should_auto_sync`, `run_auto_sync_if_due`) and that the thread
never starts by accident when the module is imported (confirmed
manually, see the session's history).

## Technical note: why `provider_modules.py` exists

`team-health-analyzer`, `calcom-pro` and `gcal` each define an
`actions.py`. Having all three on `sys.path` at once breaks things:
`import actions` always resolves to the last one inserted, not the
one needed on each call (this caused a real `ImportError` during
development — it remains as an implicit regression test in that the
full suite passes). `provider_modules.py` isolates each load,
avoiding that name clash.
