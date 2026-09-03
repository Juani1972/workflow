"""
budget-guardian-core
======================

Pure logic for the `budget-guardian` workflow: keeps track of how
much RailCall workflows spent against `engine_spec.json`'s
`max_spend_cents`, and decides when workflows need to be paused to
avoid going over budget.

**What this module does NOT do:** actually call RailCall to pause a
workflow. That capability — "pause a workflow via API" — is the same
one the original repo analysis flagged as unconfirmed
(`workflows/budget-guardian/README.md` has the detail). This module
is limited to the decision ("X, Y, Z need to be paused"), which is
100% pure, testable logic that doesn't depend on that RailCall
capability actually existing.

Exposed actions (5):
    1. record_spend
    2. get_total_spend
    3. get_spend_by_workflow
    4. should_pause_workflows
    5. build_budget_report
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. record_spend
# ---------------------------------------------------------------------------

def record_spend(ledger, workflow_id, amount_cents, timestamp, entry_id=None):
    """Records a workflow's spend.

    Args:
        ledger: existing list of entries (not mutated).
        workflow_id: which workflow spent (e.g. "fika-sync", "meeting-debt").
        amount_cents: how much it spent, in cents. Must be positive.
        timestamp: ISO 8601 of when the spend was recorded.
        entry_id: optional explicit id.

    Returns:
        New list of entries.

    Raises:
        ValueError: if amount_cents isn't positive.
    """
    if amount_cents <= 0:
        raise ValueError(f"amount_cents must be positive, got: {amount_cents!r}")

    entry_id = entry_id or f"spend-{len(ledger) + 1}"
    new_entry = {
        "id": entry_id,
        "workflow_id": workflow_id,
        "amount_cents": amount_cents,
        "timestamp": timestamp,
    }
    return list(ledger) + [new_entry]


# ---------------------------------------------------------------------------
# 2. get_total_spend
# ---------------------------------------------------------------------------

def get_total_spend(ledger, since=None):
    """Sums the ledger's total spend.

    Args:
        ledger: list of entries.
        since: optional ISO 8601 timestamp; if passed, only sums
            entries with timestamp >= since (lexicographic string
            comparison of ISO 8601 strings, valid since they're all
            UTC in the same format).

    Returns:
        int, total cents.
    """
    return sum(
        entry["amount_cents"] for entry in ledger
        if since is None or entry["timestamp"] >= since
    )


# ---------------------------------------------------------------------------
# 3. get_spend_by_workflow
# ---------------------------------------------------------------------------

def get_spend_by_workflow(ledger, since=None):
    """Groups spend by workflow_id.

    Returns:
        dict {workflow_id: total_cents}.
    """
    totals = {}
    for entry in ledger:
        if since is not None and entry["timestamp"] < since:
            continue
        totals[entry["workflow_id"]] = totals.get(entry["workflow_id"], 0) + entry["amount_cents"]
    return totals


# ---------------------------------------------------------------------------
# 4. should_pause_workflows
# ---------------------------------------------------------------------------

def should_pause_workflows(ledger, max_spend_cents, protected_workflow_ids=None, since=None):
    """Decides whether workflows need to be paused for overspending.

    When total spend reaches or exceeds max_spend_cents, the
    recommendation is to pause EVERY workflow with recorded spend
    except the protected ones (by default, "budget-guardian" — it
    wouldn't make sense for it to pause itself, or nobody would lift
    the pause).

    Args:
        ledger: list of entries.
        max_spend_cents: spend cap, same field as
            engine_spec.json → spend_limits.max_spend_cents.
        protected_workflow_ids: iterable of workflow_ids that should
            never be paused. Default: {"budget-guardian"}.
        since: see get_total_spend.

    Returns:
        dict:
            "should_pause": bool
            "total_spend_cents": int
            "remaining_cents": int (can be negative if already over)
            "workflows_to_pause": list[str], sorted from highest to lowest spend
    """
    protected = set(protected_workflow_ids) if protected_workflow_ids else {"budget-guardian"}

    total = get_total_spend(ledger, since=since)
    by_workflow = get_spend_by_workflow(ledger, since=since)

    should_pause = total >= max_spend_cents
    workflows_to_pause = []
    if should_pause:
        candidates = [wf for wf in by_workflow if wf not in protected]
        workflows_to_pause = sorted(candidates, key=lambda wf: -by_workflow[wf])

    return {
        "should_pause": should_pause,
        "total_spend_cents": total,
        "remaining_cents": max_spend_cents - total,
        "workflows_to_pause": workflows_to_pause,
    }


# ---------------------------------------------------------------------------
# 5. build_budget_report
# ---------------------------------------------------------------------------

def build_budget_report(ledger, max_spend_cents, protected_workflow_ids=None, since=None):
    """Generates the text published to Slack with the budget status.

    Returns:
        str in simple markdown format.
    """
    decision = should_pause_workflows(
        ledger, max_spend_cents, protected_workflow_ids=protected_workflow_ids, since=since
    )
    by_workflow = get_spend_by_workflow(ledger, since=since)

    total_dollars = decision["total_spend_cents"] / 100.0
    max_dollars = max_spend_cents / 100.0
    pct = (decision["total_spend_cents"] / max_spend_cents * 100.0) if max_spend_cents > 0 else 0.0

    lines = [
        "*Budget status*",
        "",
        f"Spend: ${total_dollars:.2f} / ${max_dollars:.2f} ({pct:.0f}%)",
        "",
    ]

    for workflow_id in sorted(by_workflow, key=lambda wf: -by_workflow[wf]):
        lines.append(f"• {workflow_id}: ${by_workflow[workflow_id] / 100.0:.2f}")

    if decision["should_pause"]:
        lines.append("")
        if decision["workflows_to_pause"]:
            lines.append(
                "🔴 Budget exceeded. Workflows to pause: "
                + ", ".join(decision["workflows_to_pause"])
            )
        else:
            lines.append(
                "🔴 Budget exceeded, but there are no pausable workflows "
                "(all the spend belongs to protected workflows)."
            )
    else:
        lines.append("")
        lines.append(f"🟢 Within budget. ${decision['remaining_cents'] / 100.0:.2f} remaining.")

    return "\n".join(lines)
