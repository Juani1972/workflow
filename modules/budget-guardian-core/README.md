# budget-guardian-core

Pure-logic module for the `budget-guardian` workflow. Keeps track of
how much RailCall workflows spent against a cap (`max_spend_cents`),
and decides when and who to pause.

**No external dependencies or network calls.**

## ⚠️ Important limit: this decides, it doesn't execute

This module answers "X, Y, Z need to be paused" — but **it doesn't
call any RailCall API to actually pause anything**. That capability
("pause a workflow via API") is the same one the original repo
analysis flagged as unconfirmed. See
`workflows/budget-guardian/README.md` for the detail of what's left
to confirm before this workflow is operational end to end.

## Actions

| Action | What it does |
|---|---|
| `record_spend(ledger, workflow_id, amount_cents, timestamp, entry_id=None)` | Records a spend. |
| `get_total_spend(ledger, since=None)` | Total spend (optionally filtered by date). |
| `get_spend_by_workflow(ledger, since=None)` | Spend grouped by workflow. |
| `should_pause_workflows(ledger, max_spend_cents, protected_workflow_ids=None, since=None)` | Decides whether to pause and who (never the protected ones — itself, by default). |
| `build_budget_report(ledger, max_spend_cents, protected_workflow_ids=None, since=None)` | Text for Slack. |

## Tests

```bash
cd modules/budget-guardian-core
python3 -m pytest tests/ -v
```

Current status: **11/11 tests passing** (verified on 2026-08-30).
