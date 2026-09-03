# team-health-analyzer

Pure-logic module for Fika Sync. Receives data already fetched by
other workflow nodes (Cal.com bookings, ad-hoc Google Calendar
events) and returns simple data structures the rest of the workflow
uses to decide which effects to run (block focus time, rebalance
queues, publish to Slack).

**Has no external dependencies and makes no network calls.** This is
intentional: it's the easiest piece of the project to verify, because
it can be tested 100% without mocking any API.

## Actions

| Action | What it does |
|---|---|
| `calculate_meeting_load(calcom_bookings, gcal_adhoc_events)` | Sums meeting hours per person, combining Cal.com + ad-hoc Google Calendar events. |
| `classify_team_health(hours_by_person, thresholds=None)` | Classifies each person as 🟢 / 🟡 / 🔴 based on configurable thresholds. |
| `rebalance_queue(queue, health_status)` | Reorders a round-robin queue away from anyone in 🔴, without removing anyone. |
| `summarize_team_report(hours_by_person, health_status, threshold_changes=None)` | Generates the text published to Slack. |
| `update_threshold(current_thresholds, person, new_threshold_field, new_value)` | Persists a person's new threshold after the "Adjust my threshold" button — should only be called after `slack.verify_slack_signature` confirms the click is authentic. |

## Default thresholds

```python
DEFAULT_THRESHOLDS = {
    "yellow_hours": 15.0,
    "red_hours": 20.0,
}
```

Can be overridden by passing a dict to `classify_team_health`, or via
`config/thresholds.example.json` in `fika-sync/` (Slack's "Adjust my
threshold" button modifies this per person in production).

## Tests

```
cd modules/team-health-analyzer
python3 -m pytest tests/ -v
```

Current status: **8/8 tests passing** (verified on 2026-08-29).

## Technical honesty note

This module's `module_spec.json` (manifest format for RailCall's
Module Marketplace) is a reasoned reconstruction, same as
`workflow.csv` and `engine_spec.json` in `fika-sync/`. Before
publishing it, validate with `railcall module validate
module_spec.json`.
