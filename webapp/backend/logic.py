"""
Fika Sync / Team Health business logic, reused as-is from the
original repo's already-validated pieces:

  - classify_severity(): identical to the logic tested in
    fika-sync/test/test_fika_logic.py (10/10 passing) and to
    _classify() in modules/team-health-analyzer/handlers/handler.py
    (5/5 passing).
  - check_daily_threshold(): identical to
    fika-sync/test/test_fika_logic.py.

Nothing is reinvented here -- it's the same already-tested business
logic, now served behind a real API instead of only living in tests.
"""
from __future__ import annotations


def classify_severity(hours: float, weekly_threshold: float) -> str:
    """Green <=80%, yellow <=100%, red >100%. Threshold 0/not
    configured: any booked hour is already overload (explicit rule
    from the original test_zero_threshold_does_not_break)."""
    if not weekly_threshold:
        return "red" if hours > 0 else "green"
    pct = (hours / weekly_threshold) * 100
    if pct <= 80:
        return "green"
    if pct <= 100:
        return "yellow"
    return "red"


def pct_of_threshold(hours: float, weekly_threshold: float) -> float:
    if not weekly_threshold:
        return 0.0 if hours == 0 else 999.0
    return round((hours / weekly_threshold) * 100, 1)


def check_daily_threshold(hours_today: float, daily_threshold: float) -> bool:
    """The threshold must be strictly exceeded, not just met (business
    rule confirmed by test_exactly_at_limit_does_not_trigger)."""
    return hours_today > daily_threshold


def suggested_focus_hours(severity: str) -> int:
    if severity == "yellow":
        return 2
    if severity == "red":
        return 4
    return 0


def team_summary(members: list[dict]) -> dict:
    """Replicates team-health-analyzer/handler.py's
    analyze_team_health(): counts how many people fall into each
    severity band."""
    counts = {"green": 0, "yellow": 0, "red": 0}
    for m in members:
        counts[m["severity"]] += 1
    return counts
