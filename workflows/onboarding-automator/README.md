# onboarding-automator

When someone new joins the team, this workflow assigns them a buddy,
schedules the welcome meeting, mirrors it onto the calendar, posts a
notice on Slack, and logs it in a shared checklist sheet.

## Status: from "the least mature" to 5 integrations with individual tests

The original analysis marked this as **"the least mature: 5 chained
integrations, none tested individually"**. This session can't resolve
the "test against real accounts" part (still pending, see
`VALIDATION.md` at the repo root), but it did solve the other half of
the problem — that no individual integration had even mock-based
tests:

- `workflow.csv`: a **9-node** DAG, verified programmatically (0
  broken dependencies, 0 orphan actions).
- The 5 integrations it chains together — `slack`,
  `team-health-analyzer`, `google_calendar`, `calcom`, `sheets` —
  **each has its own module with unit tests that pass in isolation**
  (see the table below). Previously, "5 integrations, none tested
  individually" meant an error in any one of the five could hide
  errors in the other four. Now, if something fails in the full
  workflow, it can be isolated quickly: each piece is already known to
  work on its own.

| System | Module | Tests |
|---|---|---|
| Slack (command + message) | `modules/slack/` | 16/16 |
| Buddy selection | `modules/team-health-analyzer/` | 8/8 |
| Google Calendar | `modules/gcal/` | 13/13 |
| Cal.com | `modules/calcom-pro/` | 7/7 |
| Google Sheets | `modules/sheets/` | 5/5 |

## Design decision: reuse `rebalance_queue` to pick a buddy

`assign_buddy` uses `team_health_analyzer.rebalance_queue` — the same
function `fika-sync` uses to reorder the meeting-assignment queue away
from whoever is in 🔴. Here it's reused for a different purpose:
given a candidate buddy queue and its current health status, it
returns whoever isn't overloaded first. It's the same logic ("don't
keep piling work on someone already at the limit"), applied to a
different decision. No new function had to be written for this.

## ⚠️ What's still unconfirmed

- **The trigger is manual** (`/onboard-new-hire` via Slack), not
  automatic from an HR system. The original diagnosis didn't specify
  how this workflow would start; assuming a webhook from a specific
  HRIS (Gusto, Rippling, BambooHR, etc.) would mean inventing an
  integration nobody asked for anywhere — the simplest, most
  verifiable trigger was chosen instead.
- **None of the 5 integrations has been tested against a real
  account** — that's still pending in `VALIDATION.md`.
- **The full chain (the 9 nodes in sequence) hasn't been tested end
  to end either** — the current tests validate each module
  separately, not the assembled workflow genuinely running against
  RailCall.

## Tests

```bash
for m in slack team-health-analyzer gcal calcom-pro sheets; do
  (cd ../../modules/$m && python3 -m pytest tests/test_actions.py -q)
done
```
