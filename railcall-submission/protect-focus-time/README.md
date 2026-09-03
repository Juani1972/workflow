# protect-focus-time — a RailCall workflow

## What it does

For each person in `team_members`: reads their Google Calendar for the current week (`gcal.list_events`), finds their next free slot of the configured duration (`gcal.find_next_free_slot`), books it as a real Cal.com meeting called "Focus Time" (`calcom-pro.create_booking`), then posts a one-line summary to Slack (`slack.post_message`) of how many focus blocks got booked this run.

## Who it's for

Small teams where meetings eat the calendar and "protect your focus time" stays a suggestion nobody acts on. This workflow makes the block a real, calendar-visible meeting instead — and because `create_booking` is `side_effects: "external"`, a human sees and approves each specific booking in the airlock before it lands on anyone's calendar, so nobody wakes up to a surprise meeting an AI invented.

## End-to-end story (real trigger → real business value)

A team lead runs this once a week from Studio's Run button, filling in the team's emails, the Slack channel, and the Cal.com "Focus Time" event type ID. Four nodes later, everyone who had room in their week has a real, protected block on their calendar, and the team channel has a one-line receipt of what happened — not a dashboard nobody checks, a message that already landed.

## Reliability

- **Missing fields**: every module command validates its required
  inputs and raises a clear error instead of silently skipping a
  person — see each module's own tests.
- **Deduplication**: **not yet implemented** — doesn't check for an
  existing "Focus Time" block before booking another. Honest
  limitation, not hidden.
- **Rate limits**: not handled yet — one HTTP call per invocation; a
  large team could need retry/backoff added to the module handlers.

## Install

```bash
railcall market install juani1972/gcal
railcall market install juani1972/calcom-pro
railcall market install juani1972/slack
railcall market install juani1972/protect-focus-time
```

## Signed receipts

Each `book_focus_time` invocation (one per team member, `for_each: team_members`) mints its own signed receipt through the airlock — so the audit trail shows exactly which bookings were proposed, approved, and executed, per person, not one opaque "workflow ran" line.

## Known limitations — read before publishing

- **The exact `engine_spec` JSON schema is not confirmed.** RailCall's own docs describe it only in prose ("transform nodes... effect nodes with `action_id` + `for_each` fan-out... a capabilities block") with no full worked example. `engine_spec.json` here is my best mapping of that description — it has **not** been run through `railcall build workflow.csv` against a real Station. Do that first and fix against the real error output, not this file's assumptions.
- No deduplication (see above) and no rate-limit handling.
- Depends on all three `juani1972/*` modules also submitted in this contest window — each has its own "not yet run against a real Station" caveat documented in its own README.

## Source

`workflow.csv` (4 nodes) + `engine_spec.json` (~40 lines) — no code, this workflow is entirely declarative on top of the three modules.
