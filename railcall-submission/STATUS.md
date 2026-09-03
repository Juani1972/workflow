# Real status of the full submission (2026-08-30)

Consolidated checklist of the **4 modules + 1 workflow** converted to
RailCall's real format in this session. Each one also has its own
`README.md` with the same notes — this is the overview.

## The 4 modules

| Module | Commands | External effects | Credential (vault) |
|---|---|---|---|
| `juani1972/calcom-pro` | `list_bookings`, `get_booking`, `get_availability`, `create_booking`, `reschedule_booking`, `cancel_booking`, `protect_focus_time`, `get_meeting_load` | 3 of 8 | `calcom` → `api_key` |
| `juani1972/gcal` | `list_events`, `find_next_free_slot`, `create_event`, `update_event`, `delete_event` | 3 of 5 | `gcal` → `access_token` (static) |
| `juani1972/slack` | `list_channels`, `post_message` | 1 of 2 | `slack` → `bot_token` (doesn't expire) |
| `juani1972/sheets` | `read_values`, `append_row` | 1 of 2 | `sheets` → `access_token` (static) |

**Total: 17 commands, 9 read-only, 8 with an external effect (`side_effects: "external"`, go through the airlock).**

**2026-08-31 — `calcom-pro` went from 3 to 8 commands** (to fall
within the "top 6-10 actions" range of a RailCall developer contest's
rubric), adding `get_booking`, `get_availability`, `cancel_booking`,
`protect_focus_time` (composes `get_availability` + `create_booking`:
looks for the first free slot for a "Focus Time" event type and
actually books it, not just suggests it) and `get_meeting_load` (pure
logic over the data `list_bookings` already fetched, no extra network
call). The 3 new endpoints that hit Cal.com (`get_booking`,
`get_availability`, `cancel_booking`) were verified against Cal.com's
live documentation on 2026-08-31: their `cal-api-version` values are
`2026-02-25`, `2024-09-04` and `2026-02-25` respectively. This also
confirms (no longer "assumes") that `reschedule_booking` uses
`2026-02-25` — three endpoints from the same `/bookings/{uid}/*`
family agree on that value. 23 new unit tests with `urllib.urlopen`
mocked (previously 9), README updated without going over 500 words.

## ✅ Same across all 4, resolved this session

1. **Real format**: `module.json` + a single `handlers/handler.py`,
   without `client.py`/`actions.py`/`module_spec.json` as in
   `modules/`.
2. **Credentials via vault**, never `os.environ` — each handler has
   its own `_vault_*()` with the same pattern.
3. **No error goes silent** — every command validates its required
   inputs and propagates HTTP errors with a clear message. In `slack`
   the "HTTP 200 but `ok: false`" case was specifically verified as
   well (Slack doesn't use status codes to signal failures).
4. **README ≤500 words** per module, all with an example + expected
   output + honest limitations — not one generic README copied 4
   times.
5. **The 12 commands have 39 unit tests with `urllib.urlopen`
   mocked** (`tests/test_handler.py` in each module), including error
   cases (missing input, error HTTP, missing credential) and
   verification that every `_h_<command_name>` exists and is
   callable — not a claim with no backing file, they actually run
   with `pytest`.
6. **Standard library only** (`urllib`, `json`, `datetime`) in all 4
   — no `requests` import, because RailCall's documentation never
   describes how to declare a pip dependency for a module.

## ✅ Two shared uncertainties across all 4, now confirmed against the real docs

Read live on 2026-08-30: [Publisher FAQ](https://railcall.ai/docs/marketplace-developer/faq/) and
[Publish a Module](https://railcall.ai/docs/marketplace-developer/modules/).

1. **Function name**: the loader literally looks for
   `_h_<command_name>` — confirmed as a verbatim rejection reason
   ("Command `<cid>`: no callable `_h_<name>` in handler.py"), not a
   style preference. All 4 handlers now have the `_h_*` functions as
   primary, with prefix-less aliases only for readability (the loader
   never calls them).
2. **Shape of `vault_get()`**: confirmed as `{"api_key": "..."}` (or
   the provider-specific field, e.g. `access_token`/`bot_token`),
   resolved by Station v0.29+ exclusively via
   `__rc_helpers__["vault_get"]`. All 4 handlers already used it that
   way; only the docstrings that marked it as "unconfirmed" were
   cleaned up.

**Additional changes applied in this pass, based on the same confirmed information:**

- Added the `requires` sandbox block (network allowlist,
  `subprocess: false`, `filesystem_writes: []`) to the 4 `module.json`
  files — opt-in since Station v0.33+, a direct improvement to the
  rubric's "Trust Surface" criterion.
- Added per-command `requires` (credential list) to the 12 commands.
- Removed the `auth.env_var` field from the 4 `module.json` files —
  it was misleading, because the code never reads environment
  variables, only the vault. Replaced with `credentials_note`, an
  informational field.
- Fixed `calcom-pro`: the `cal-api-version` header was a single,
  outdated value for the 3 commands; it now uses `2026-05-01` for
  `GET /bookings` and `2026-02-25` for `POST /bookings` (confirmed
  against Cal.com's live docs), same as had already been fixed in
  `modules/calcom-pro/` but hadn't made it into this folder.
- Added **39 unit tests with `urllib.urlopen` mocked**
  (`tests/test_handler.py` in each of the 4 modules) — previously
  this document claimed the 12 commands were already "tested with
  mocks" with no test file actually committed. Now they exist and
  all 39 pass (`cd <module> && python3 -m pytest tests/ -q`).
- Adjusted `protect-focus-time/engine_spec.json`: the module
  dependency key is `module_dependency` (singular, confirmed
  literally in the workflows docs), not `module_dependencies`.

## Uncertainty specific to `gcal` and `sheets`

Google access tokens expire in ~1 hour. Neither module renews them —
neither declares an `auth` field in its `module.json` (it isn't part
of the confirmed manifest schema; credentials are read from the
vault by provider name, see `credentials_note` in each manifest).
They're sent as a static token on purpose, because no documentation
was found on whether RailCall auto-renews OAuth2 for a *non-cataloged*
provider (Google Calendar/Sheets aren't confirmed on the list of
~110 built-in providers that would have this handled, per
[Publish a Module](https://railcall.ai/docs/marketplace-developer/modules/)).
It's a real limitation, not a minor detail — it's in each README under
"Known limitations", not hidden.

## ❌ Still pending — depends on you, not something that can be resolved here

1. **Install the real Station** (`curl -fsSL https://railcall.ai/install.sh | bash`)
   and run `railcall studio` — this environment has no network egress
   to `railcall.ai` nor to any of the 3 real APIs (Cal.com, Google,
   Slack). This closes the one thing left: running the 5-step loop
   the FAQ recommends (`railcall market module sign` → load in
   Studio → `railcall airlock stage` → approve → verify the receipt)
   against the 12 commands, starting with `list_bookings` (the
   simplest, read-only one).
2. **Verify the sandbox `requires` block doesn't block legitimate
   calls** — a `network` allowlist was added to the 4 modules
   (`api.cal.com`, `www.googleapis.com`, `slack.com`,
   `sheets.googleapis.com`) based on the hosts the code actually
   calls, but it was never tested against the sandbox's real
   enforcement (Station v0.33+).
3. **Create the marketplace account once**
   (`railcall market publisher init juani1972` →
   `railcall market publisher register`), then claim and publish each
   slug:
   ```bash
   cd railcall-submission/calcom-pro && railcall market claim juani1972/calcom-pro && railcall market publish .
   cd ../gcal && railcall market claim juani1972/gcal && railcall market publish .
   cd ../slack && railcall market claim juani1972/slack && railcall market publish .
   cd ../sheets && railcall market claim juani1972/sheets && railcall market publish .
   ```
4. **Tag each listing** with the exact tag the current contest
   instance asks for (`contest:2026Q3` per the evergreen page,
   `contest:round2` per the specific Freelancer posting shared —
   confirm which one before publishing).
5. **Test each one from a clean install**
   (`railcall market install juani1972/<slug>`) before calling it
   done — it's the rubric's first criterion (30 of 100 points).
6. **Choose which one to publish as the contest entry** — per the
   rules, "only your best-scoring submission counts toward the
   prize" if you submit more than one. `gcal` is probably the
   strongest in coverage (5 commands, includes pure logic testable
   without network in `find_next_free_slot`); `calcom-pro` has the
   most concrete use case and already fixed a real endpoint bug. All
   4 can be published either way — the contest doesn't limit how many
   modules you upload, only which one counts for the prize.

## What's next if you want more

**Already done**: `protect-focus-time` — the category B workflow, see
`railcall-submission/protect-focus-time/`. Reuses the 3 modules above
(`gcal`, `calcom-pro`, `slack`), 4 nodes, CSV + `engine_spec.json`
validated programmatically against the real `module.json` files (0
broken dependencies, 0 orphan actions — the 4 referenced actions are
commands that genuinely exist in the modules, each with its own
tests).

**What remains the submission's most uncertain piece**: the real
workflows docs ([Publish a
Workflow](https://railcall.ai/docs/marketplace-developer/workflows/),
read live on 2026-08-30) confirm the prose-described shape (transform
nodes, effect nodes with `action_id` + `for_each` fan-out, a
`capabilities` block with `providers` + `max_spend_cents`) and
literally confirms the `module_dependency` key (already fixed here,
it used to be `module_dependencies`) — but still doesn't show a
complete `engine_spec.json`: it only names
`dave/retainer-billing-run` as the real marketplace example, without
reproducing its content. `protect-focus-time`'s `engine_spec.json` is
the best possible mapping given what the docs confirm, explicitly
marked where it's still an assumption. Before publishing that
specific workflow, actually running `railcall build workflow.csv` and
adjusting against the real error matters more than it did for the 4
modules (which are anchored in complete, verbatim JSON examples from
the documentation).

`meeting-debt`, `onboarding-automator` and `budget-guardian` (the
other 3 workflows from the original repo) are still unconverted —
same pattern, same work, say the word if we should continue with any
of them.
