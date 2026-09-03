import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import (
    record_spend,
    get_total_spend,
    get_spend_by_workflow,
    should_pause_workflows,
    build_budget_report,
)


def test_record_spend_appends_without_mutating_original():
    ledger = []
    new_ledger = record_spend(ledger, "fika-sync", 150, "2026-09-01T10:00:00Z")

    assert ledger == []
    assert len(new_ledger) == 1
    assert new_ledger[0]["workflow_id"] == "fika-sync"
    assert new_ledger[0]["amount_cents"] == 150


def test_record_spend_rejects_non_positive_amount():
    with pytest.raises(ValueError):
        record_spend([], "fika-sync", 0, "2026-09-01T10:00:00Z")
    with pytest.raises(ValueError):
        record_spend([], "fika-sync", -10, "2026-09-01T10:00:00Z")


def test_get_total_spend_sums_across_workflows():
    ledger = record_spend([], "fika-sync", 100, "2026-09-01T10:00:00Z")
    ledger = record_spend(ledger, "meeting-debt", 200, "2026-09-01T11:00:00Z")

    assert get_total_spend(ledger) == 300


def test_get_total_spend_respects_since_filter():
    ledger = record_spend([], "fika-sync", 100, "2026-09-01T10:00:00Z")
    ledger = record_spend(ledger, "fika-sync", 200, "2026-09-02T10:00:00Z")

    assert get_total_spend(ledger, since="2026-09-02T00:00:00Z") == 200


def test_get_spend_by_workflow_groups_correctly():
    ledger = record_spend([], "fika-sync", 100, "2026-09-01T10:00:00Z")
    ledger = record_spend(ledger, "fika-sync", 50, "2026-09-01T11:00:00Z")
    ledger = record_spend(ledger, "meeting-debt", 30, "2026-09-01T12:00:00Z")

    result = get_spend_by_workflow(ledger)

    assert result == {"fika-sync": 150, "meeting-debt": 30}


def test_should_pause_workflows_false_when_under_budget():
    ledger = record_spend([], "fika-sync", 100, "2026-09-01T10:00:00Z")

    decision = should_pause_workflows(ledger, max_spend_cents=500)

    assert decision["should_pause"] is False
    assert decision["remaining_cents"] == 400
    assert decision["workflows_to_pause"] == []


def test_should_pause_workflows_true_at_or_over_budget():
    ledger = record_spend([], "fika-sync", 300, "2026-09-01T10:00:00Z")
    ledger = record_spend(ledger, "meeting-debt", 250, "2026-09-01T11:00:00Z")

    decision = should_pause_workflows(ledger, max_spend_cents=500)

    assert decision["should_pause"] is True
    assert decision["remaining_cents"] == -50
    # sorted from highest to lowest spend
    assert decision["workflows_to_pause"] == ["fika-sync", "meeting-debt"]


def test_should_pause_workflows_never_pauses_protected_workflows():
    ledger = record_spend([], "budget-guardian", 400, "2026-09-01T10:00:00Z")
    ledger = record_spend(ledger, "fika-sync", 200, "2026-09-01T11:00:00Z")

    decision = should_pause_workflows(ledger, max_spend_cents=500)

    assert decision["should_pause"] is True
    assert "budget-guardian" not in decision["workflows_to_pause"]
    assert decision["workflows_to_pause"] == ["fika-sync"]


def test_should_pause_workflows_accepts_custom_protected_set():
    ledger = record_spend([], "fika-sync", 600, "2026-09-01T10:00:00Z")

    decision = should_pause_workflows(
        ledger, max_spend_cents=500, protected_workflow_ids={"budget-guardian", "fika-sync"}
    )

    assert decision["should_pause"] is True
    assert decision["workflows_to_pause"] == []


def test_build_budget_report_under_budget():
    ledger = record_spend([], "fika-sync", 100, "2026-09-01T10:00:00Z")
    report = build_budget_report(ledger, max_spend_cents=500)

    assert "Within budget" in report
    assert "fika-sync: $1.00" in report


def test_build_budget_report_over_budget_lists_workflows_to_pause():
    ledger = record_spend([], "fika-sync", 600, "2026-09-01T10:00:00Z")
    report = build_budget_report(ledger, max_spend_cents=500)

    assert "Budget exceeded" in report
    assert "fika-sync" in report.split("Workflows to pause:")[1]
