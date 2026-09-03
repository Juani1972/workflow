# Fika Sync

Protects the team's focus time and balances meeting load, cross-referencing
data from **Cal.com** and **Google Calendar**, with an automatic weekly
summary in **Slack**.

Every week (or on demand with `/fika-check` in Slack), Fika Sync:

1. Calculates how many meeting hours each person has (Cal.com + ad-hoc
   Google Calendar events that Cal.com doesn't see).
2. Classifies the team as 🟢 healthy / 🟡 at the limit / 🔴 overloaded.
3. Automatically blocks "focus time" hours for 🟡 and 🔴, and mirrors them
   onto Google Calendar.
4. Rebalances automatic assignment queues (round-robin) away from whoever
   is 🔴.
5. Publishes a human, actionable summary to Slack — with a button so each
   person can adjust their own threshold.
6. Leaves an audit record of every action taken.

Every action that writes or modifies something (blocking a calendar, moving
meetings, publishing to Slack) goes through RailCall's **airlock**:
`preview → approve → execute → signed receipt`. Nothing runs without your
approval.

---

## ⚠️ Before installing — read this first

This project was built for a RailCall developer contest.
If you got here through that contest, two basic security recommendations
before installing anything:

- **Don't run the installer (`curl ... | bash`) on your main machine.**
  Use a disposable VM or container the first time.
- **Use test/sandbox accounts** for Cal.com, Google and Slack to try this
  out — never your production accounts or a real team's real data,
  until you trust the workflow's behavior.

None of these precautions are specific to Fika Sync — they apply to any
tool that asks you to install a script and connect real accounts.

---

## Installation (≈10 min)

### 1. Install the RailCall CLI

```bash
curl -fsSL https://railcall.ai/install.sh | bash
railcall version
```

### 2. Create an account and publisher key (one time only)

```bash
railcall market login your@email.com
railcall market publisher init your-handle
railcall market publisher register
```

### 3. Clone/copy this project

```bash
git clone <your-repo>/fika-sync
cd fika-sync
cp .env.example .env   # fill in with TEST credentials, not production
cp config/team.example.csv config/team.csv   # adjust with your team (or a test one)
```

### 4. Audit before compiling (doesn't run anything, read-only)

```bash
railcall audit workflow.csv
```

### 5. Compile and verify locally

```bash
railcall build workflow.csv
railcall workflow run workflow.csv        # dry-run by default, sends nothing real
```

Review the preview shown by the airlock. Only once you're satisfied,
add `--live` to actually run it:

```bash
railcall workflow run workflow.csv --live
```

### 6. Connect the real (or test) accounts in Studio

```bash
railcall studio
```

Go to **Integrations** and connect Cal.com, Google Calendar and Slack.
Credentials are stored locally — never in this repo, never in the
marketplace listing.

### 7. Publish (optional, for the marketplace)

```bash
railcall market claim your-handle/fika-sync
railcall market publish
```

---

## Project structure

```
fika-sync/
├── workflow.csv          # node DAG (trigger, transforms, effects)
├── engine_spec.json       # capabilities, providers, spend cap
├── config/
│   ├── team.example.csv   # team template (copy to team.csv)
│   └── thresholds.json    # per-role thresholds, editable without touching code
├── test/
│   └── test_fika_logic.py # classification logic tests (10/10 passing)
├── demo/
│   └── run_demo.sh        # dry-run demo script
├── gui/
│   ├── mockup-4-screens.html   # static mockup: War Room, Cockpit, Pulse, Retrospective
│   └── war-room-prototype.html   # functional War Room prototype (editable data, live calculation)
├── .env.example            # example environment variables (never the real .env)
└── README.md
```

### GUI (work in progress)

`gui/mockup-4-screens.html` is a static design of the 4 screens proposed
for a future visual interface (no real data, no functionality).
`gui/war-room-prototype.html` goes a step further: a War Room with data
editable in the browser, reusing the same classification logic (80%/100%
bands) that's tested in `test/test_fika_logic.py`. Neither one connects
yet to Cal.com, Google Calendar or Slack — open them directly in the
browser to see them.

## Technical honesty note

The exact column format of `workflow.csv` and of `engine_spec.json` was
reconstructed from the prose description in RailCall's official
documentation (`/docs/marketplace-developer/workflows`), not from a
published complete file example. **Before relying on this in a real
demo, validate the exact syntax with `railcall build --help` and with
`railcall audit workflow.csv`**, and adjust column names if the
compiler expects something different. This is explicitly flagged in
`engine_spec.json` (`_readme`) so it's clear what's official
documentation and what's a reasoned reconstruction.

## Security

- No token, secret, or webhook is written in `workflow.csv` or in
  `engine_spec.json` — they're configured in Studio → Integrations,
  against the real account of the user installing the workflow.
- `protect_focus_time` and `mirror_gcal_block` never overwrite an
  already-accepted meeting: if there's a conflict, `resolve_conflicts`
  looks for the next free slot before blocking.
- The "Adjust my threshold" button in Slack never modifies a calendar
  directly — it only triggers an explicit confirmation from that
  schedule's owner.
- `max_spend_cents` in `engine_spec.json` caps the maximum spend per
  run, enforced at runtime, not just in the plan.

## What's new in v0.2.0 (Level 1 and 4 improvements)

- **Export to Sheets** (`export_to_sheet`, `log_history`) — the weekly
  summary is no longer just published to Slack, it's also kept in a
  shared sheet with history.
- **Configurable thresholds** (`config/thresholds.example.json`) — the
  hours threshold is no longer hardcoded, it's read from an editable
  JSON file, and the Slack "Adjust my threshold" button now persists
  the change (`update_threshold`), not just confirms it.
- **Proactive notifications** (`trigger_daily_check`,
  `check_daily_threshold`) — besides the weekly summary, it warns the
  same day if someone exceeds their daily threshold.
- **Real duration via Zoom/Meet** (`get_actual_duration`,
  `adjust_focus_time`) — corrects the calculation when a meeting ran
  longer than scheduled.
- **Tests and demo** (`test/test_plan.md`, `demo/run_dry_run.sh`) — a
  case plan with mock fixtures, and a script ready to record the
  contest video in dry-run mode.

See `engine_spec.json` v0.2.0 for the added Zoom provider and the retry
policy.

## License / IP

This workflow is your own creation — you publish it under your own
handle and keep the IP and any marketplace revenue it generates.
