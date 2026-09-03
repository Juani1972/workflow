# budget-guardian

Watches the aggregate spend of all RailCall workflows against a cap,
and automatically pauses whatever's needed if the budget is exceeded.

## Status: the decision logic is real; execution is still blocked

The original analysis was specific about this workflow's problem:
**"assumes a RailCall capability (pausing workflows via API) that
isn't confirmed to exist"**. This session couldn't resolve that
question — it remains unconfirmed — but it did split the problem into
two parts, and solved the one that could be solved without that
capability:

- **`modules/budget-guardian-core/`**: decides *what* to pause and
  when, from a spend ledger. **11/11 tests passing**, pure logic, no
  network calls. This part is completely trustworthy regardless of
  whether RailCall can pause workflows or not.
- **`workflow.csv`**: a **9-node** DAG, verified programmatically (0
  broken dependencies, 0 orphan actions).

## ⚠️ Two unconfirmed RailCall capabilities (not one, two)

1. **`get_spend_log`** (`fetch_workflow_spend`): whether RailCall
   exposes a way to read how much each workflow spent. Without this,
   there's no source for the data that feeds
   `budget-guardian-core`.
2. **`pause_workflow`** (`pause_workflows`): the one the original
   diagnosis already flagged — whether RailCall allows pausing a
   workflow via API.

Neither is documented in what could be found about RailCall. This
workflow depends on **both** to operate autonomously.

## Fallback plan if neither exists

`budget-guardian-core` is still useful as a manual calculator: if
someone pastes in each workflow's spend by hand (or exports it from
wherever RailCall shows it in its UI), `should_pause_workflows` and
`build_budget_report` work just the same — it's just that someone has
to "be" `fetch_workflow_spend` and `pause_workflows`, instead of
RailCall doing it automatically. It's a significant degradation (from
"autonomous workflow" to "calculator someone operates by hand"), but
it doesn't leave the work already done in `budget-guardian-core`
useless.

## Tests

```bash
cd modules/budget-guardian-core
python3 -m pytest tests/ -v
```

Status: **11/11 tests passing** (verified on 2026-08-30) — all on the
decision logic, none (nor could there be) on the unconfirmed RailCall
capabilities.
