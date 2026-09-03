# meeting-debt-tracker

Pure-logic module for the `meeting-debt` workflow. Keeps track of how
much protected focus time is owed to each person when a
higher-priority meeting overrides it (bumps or cancels it), and
decides when that debt is serious enough to escalate.

**No external dependencies or network calls** — just like
`team-health-analyzer`, it can be tested 100% without mocking
anything.

## Actions

| Action | What it does |
|---|---|
| `record_debt(ledger, person, minutes, reason, created_at, entry_id=None)` | Records a new debt. |
| `repay_debt(ledger, person, minutes)` | Marks debt as paid, FIFO (oldest to newest), never over-repays. |
| `get_balance(ledger, person)` | A person's outstanding minutes. |
| `classify_debt_severity(balance_minutes, thresholds=None)` | 🟢 ok / 🟡 watch / 🔴 critical. |
| `summarize_debt_report(ledger, thresholds=None)` | Text to publish to Slack. |

## Default thresholds

```python
DEFAULT_SEVERITY_THRESHOLDS = {
    "watch_minutes": 60.0,
    "critical_minutes": 180.0,
}
```

## Tests

```bash
cd modules/meeting-debt-tracker
python3 -m pytest tests/ -v
```

Current status: **11/11 tests passing** (verified on 2026-08-30).
