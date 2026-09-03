# meeting-debt

When a higher-priority meeting overrides someone's protected focus
time (moves or cancels it), this workflow records that "debt" and
looks for a way to give it back — instead of the lost block simply
disappearing without a trace.

## Status: from "concept" to a complete workflow, with tested logic

The original repo analysis listed `meeting-debt` alongside the other
two level-3 workflows as "concepts, not features ready to install".
This session brought it to:

- `workflow.csv`: a **13-node** DAG, verified programmatically against
  the real modules (0 broken dependencies, 0 orphan actions).
- **`modules/meeting-debt-tracker/`**: the workflow's logic core
  (recording debt, repaying it FIFO, classifying severity, generating
  the report) — **11/11 tests passing**, pure logic, no network
  calls, the easiest part of the whole workflow to trust.
- Reuses `gcal`, `calcom-pro` and `slack`, already built and tested in
  earlier sessions — no new external integration had to be written
  for this workflow.

## ⚠️ What's still unconfirmed

**`webhook_calendar_change`** (the trigger that fires the workflow
when a specific Google Calendar event changes) is an **unconfirmed**
RailCall capability. Everything else in this repo that uses RailCall
as a trigger uses `cron_weekly`/`cron_daily` (which does seem
reasonable to exist, given that `fika-sync` already assumes it), but a
per-specific-event webhook is a more specific capability that could
not be found documented.

**Plan B if `webhook_calendar_change` doesn't exist:** the workflow
still works with the other two triggers (`trigger_weekly_debt_check`,
`trigger_debt_slash_command`) — it simply doesn't react the moment
focus time is lost, but rather at the weekly check or when someone
runs `/meeting-debt-check` by hand. It's an acceptable degradation,
not a total blocker.

## How a lost block is detected

`fetch_event_details` (gcal.list_events) queries the event again. If
it no longer appears on the calendar (or its time/duration changed),
that's the signal for `record_debt`. The "is this event still the
same as when we created it?" comparison isn't implemented as a
separate action in this version — it's logic the RailCall node would
have to handle by comparing `list_events`'s result against the
state saved the previous time. It remains as pending work if this is
decided to be built for real.

## Tests

```bash
cd modules/meeting-debt-tracker
python3 -m pytest tests/ -v
```

Status: **11/11 tests passing** (verified on 2026-08-30).
