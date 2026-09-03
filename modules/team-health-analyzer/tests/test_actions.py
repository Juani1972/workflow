import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import (
    calculate_meeting_load,
    classify_team_health,
    rebalance_queue,
    summarize_team_report,
    update_threshold,
    STATUS_GREEN,
    STATUS_YELLOW,
    STATUS_RED,
)


def test_calculate_meeting_load_combines_calcom_and_adhoc():
    calcom_bookings = [
        {"person": "ana", "duration_minutes": 60},
        {"person": "ana", "duration_minutes": 30},
        {"person": "beto", "duration_minutes": 120},
    ]
    gcal_adhoc_events = [
        {"person": "ana", "duration_minutes": 30},
    ]

    result = calculate_meeting_load(calcom_bookings, gcal_adhoc_events)

    assert result == {"ana": 2.0, "beto": 2.0}


def test_calculate_meeting_load_rejects_negative_duration():
    with pytest.raises(ValueError):
        calculate_meeting_load([{"person": "ana", "duration_minutes": -10}])


def test_classify_team_health_boundaries():
    hours = {"ana": 25.0, "beto": 15.0, "caro": 14.99, "dani": 20.0}

    result = classify_team_health(hours)

    assert result["ana"] == STATUS_RED
    assert result["beto"] == STATUS_YELLOW
    assert result["caro"] == STATUS_GREEN
    assert result["dani"] == STATUS_RED  # inclusive limit


def test_rebalance_queue_moves_red_to_back_without_dropping_anyone():
    queue = ["ana", "beto", "caro", "dani"]
    health_status = {
        "ana": STATUS_RED,
        "beto": STATUS_GREEN,
        "caro": STATUS_RED,
        "dani": STATUS_YELLOW,
    }

    result = rebalance_queue(queue, health_status)

    assert result == ["beto", "dani", "ana", "caro"]
    assert sorted(result) == sorted(queue)  # nadie se pierde


def test_summarize_team_report_contains_key_sections():
    hours = {"ana": 22.0, "beto": 10.0}
    health_status = {"ana": STATUS_RED, "beto": STATUS_GREEN}
    threshold_changes = [{"person": "beto", "new_threshold": 18}]

    report = summarize_team_report(hours, health_status, threshold_changes)

    assert "Weekly meeting load summary" in report
    assert "🔴 *ana*" in report
    assert "🟢 *beto*" in report
    assert "Thresholds adjusted" in report
    assert "assignment queue was rebalanced" in report


def test_update_threshold_creates_override_from_default_when_none_existed():
    current = {"default": {"yellow_hours": 15.0, "red_hours": 20.0}, "per_person_overrides": {}}

    result = update_threshold(current, "ana", "red_hours", 18.0)

    assert result["per_person_overrides"]["ana"] == {"yellow_hours": 15.0, "red_hours": 18.0}
    # el default global no se toca
    assert result["default"] == {"yellow_hours": 15.0, "red_hours": 20.0}
    # el input original no se muta
    assert current["per_person_overrides"] == {}


def test_update_threshold_updates_existing_override_without_touching_other_field():
    current = {
        "default": {"yellow_hours": 15.0, "red_hours": 20.0},
        "per_person_overrides": {"caro": {"yellow_hours": 12.0, "red_hours": 18.0}},
    }

    result = update_threshold(current, "caro", "yellow_hours", 10.0)

    assert result["per_person_overrides"]["caro"] == {"yellow_hours": 10.0, "red_hours": 18.0}


def test_update_threshold_rejects_unknown_field():
    current = {"default": {"yellow_hours": 15.0, "red_hours": 20.0}, "per_person_overrides": {}}

    with pytest.raises(ValueError):
        update_threshold(current, "ana", "purple_hours", 5.0)
