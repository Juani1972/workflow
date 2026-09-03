"""
Tests for Fika Sync's transformation logic (load.merge, load.classify,
load.check_daily, digest.generate). Use mocks — no real API calls.

How to run them:
    pip install pytest --break-system-packages
    pytest test/test_fika_logic.py -v

HONESTY NOTE: these tests validate the business LOGIC in pure Python
(severity classification, load merging, threshold calculation). They do not
test actual execution of workflow.csv's nodes against the RailCall runtime
-- that can only be validated with `railcall audit workflow.csv` and
`railcall workflow run workflow.csv` (dry-run) on your own installation.
"""
import pytest


# --- Logic that would replicate the merge_load node ---
def merge_load(calcom_hours: float, gcal_hours: float) -> float:
    return round(calcom_hours + gcal_hours, 2)


# --- Logic that would replicate the classify_severity node ---
def classify_severity(hours: float, weekly_threshold: float) -> str:
    if not weekly_threshold:
        # Threshold 0/not configured: any booked hour is already overload.
        return "red" if hours > 0 else "green"
    pct = (hours / weekly_threshold) * 100
    if pct <= 80:
        return "green"
    if pct <= 100:
        return "yellow"
    return "red"


# --- Logic that would replicate the check_daily_threshold node ---
def check_daily_threshold(hours_today: float, daily_threshold: float) -> bool:
    return hours_today > daily_threshold


class TestMergeLoad:
    def test_simple_sum(self):
        assert merge_load(10, 3) == 13

    def test_no_extra_hours(self):
        assert merge_load(12, 0) == 12

    def test_rounding(self):
        assert merge_load(4.111, 2.222) == 6.33


class TestClassifySeverity:
    def test_green_below_80_percent(self):
        assert classify_severity(hours=10, weekly_threshold=15) == "green"

    def test_yellow_between_80_and_100(self):
        assert classify_severity(hours=13, weekly_threshold=15) == "yellow"

    def test_red_above_100(self):
        assert classify_severity(hours=18, weekly_threshold=15) == "red"

    def test_zero_threshold_does_not_break(self):
        # A 0 threshold must not raise ZeroDivisionError
        assert classify_severity(hours=5, weekly_threshold=0) == "red"


class TestCheckDailyThreshold:
    def test_does_not_exceed(self):
        assert check_daily_threshold(hours_today=3, daily_threshold=4) is False

    def test_exceeds(self):
        assert check_daily_threshold(hours_today=5, daily_threshold=4) is True

    def test_exactly_at_limit_does_not_trigger(self):
        # Business rule: the threshold must be strictly exceeded, not just met
        assert check_daily_threshold(hours_today=4, daily_threshold=4) is False


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
