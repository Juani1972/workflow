import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import (
    record_debt,
    repay_debt,
    get_balance,
    classify_debt_severity,
    summarize_debt_report,
    SEVERITY_OK,
    SEVERITY_WATCH,
    SEVERITY_CRITICAL,
)


def test_record_debt_appends_entry_without_mutating_original():
    ledger = []
    new_ledger = record_debt(ledger, "ana", 30, "Meeting with ACME rescheduled", "2026-09-01T10:00:00Z")

    assert ledger == []  # el original no se toca
    assert len(new_ledger) == 1
    assert new_ledger[0]["person"] == "ana"
    assert new_ledger[0]["minutes"] == 30
    assert new_ledger[0]["repaid_minutes"] == 0.0


def test_record_debt_rejects_non_positive_minutes():
    with pytest.raises(ValueError):
        record_debt([], "ana", 0, "motivo", "2026-09-01T10:00:00Z")
    with pytest.raises(ValueError):
        record_debt([], "ana", -5, "motivo", "2026-09-01T10:00:00Z")


def test_get_balance_sums_multiple_entries_for_same_person():
    ledger = record_debt([], "ana", 30, "motivo 1", "2026-09-01T10:00:00Z")
    ledger = record_debt(ledger, "ana", 45, "motivo 2", "2026-09-02T10:00:00Z")
    ledger = record_debt(ledger, "beto", 15, "motivo 3", "2026-09-02T10:00:00Z")

    assert get_balance(ledger, "ana") == 75
    assert get_balance(ledger, "beto") == 15
    assert get_balance(ledger, "nadie") == 0


def test_repay_debt_applies_fifo_across_multiple_entries():
    ledger = record_debt([], "ana", 30, "motivo 1", "2026-09-01T10:00:00Z")
    ledger = record_debt(ledger, "ana", 45, "motivo 2", "2026-09-02T10:00:00Z")

    repaid_ledger = repay_debt(ledger, "ana", 40)  # cubre toda la primera + parte de la segunda

    assert repaid_ledger[0]["repaid_minutes"] == 30  # first entry fully settled
    assert repaid_ledger[1]["repaid_minutes"] == 10  # segunda entry parcialmente saldada
    assert get_balance(repaid_ledger, "ana") == 35


def test_repay_debt_never_overpays():
    ledger = record_debt([], "ana", 20, "motivo", "2026-09-01T10:00:00Z")
    repaid_ledger = repay_debt(ledger, "ana", 100)  # too much, on purpose

    assert get_balance(repaid_ledger, "ana") == 0
    assert repaid_ledger[0]["repaid_minutes"] == 20  # never more than what's owed


def test_repay_debt_does_not_affect_other_people():
    ledger = record_debt([], "ana", 30, "motivo", "2026-09-01T10:00:00Z")
    ledger = record_debt(ledger, "beto", 30, "motivo", "2026-09-01T10:00:00Z")

    repaid_ledger = repay_debt(ledger, "ana", 30)

    assert get_balance(repaid_ledger, "ana") == 0
    assert get_balance(repaid_ledger, "beto") == 30


def test_repay_debt_rejects_non_positive_minutes():
    with pytest.raises(ValueError):
        repay_debt([], "ana", 0)


def test_classify_debt_severity_boundaries():
    assert classify_debt_severity(0) == SEVERITY_OK
    assert classify_debt_severity(59.9) == SEVERITY_OK
    assert classify_debt_severity(60) == SEVERITY_WATCH
    assert classify_debt_severity(179.9) == SEVERITY_WATCH
    assert classify_debt_severity(180) == SEVERITY_CRITICAL


def test_summarize_debt_report_when_everyone_is_clear():
    report = summarize_debt_report([])
    assert "Nobody has focus time pending" in report


def test_summarize_debt_report_sorts_critical_first_and_flags_it():
    ledger = record_debt([], "ana", 200, "motivo grave", "2026-09-01T10:00:00Z")
    ledger = record_debt(ledger, "beto", 20, "motivo leve", "2026-09-01T10:00:00Z")

    report = summarize_debt_report(ledger)

    assert report.index("ana") < report.index("beto")
    assert "🔴 *ana*" in report
    assert "Critical accumulated debt for: ana" in report
    assert "beto" not in report.split("Critical")[0].split("\n")[-2]  # beto isn't 🔴


def test_summarize_debt_report_excludes_people_with_zero_balance():
    ledger = record_debt([], "ana", 30, "motivo", "2026-09-01T10:00:00Z")
    ledger = repay_debt(ledger, "ana", 30)  # ana queda en 0

    report = summarize_debt_report(ledger)

    assert "ana" not in report
    assert "Nobody has focus time pending" in report
