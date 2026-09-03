"""
Tests for provider_modules.py.

Until now this loader was only tested indirectly (through
sync_service.py, which uses it internally). These tests exercise it
directly: that each load_*() brings back the correct functions, and
above all that loading the three modules in any order doesn't make
one overwrite another's functions — which is exactly the bug that
motivated writing this file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import provider_modules


def test_load_team_health_analyzer_exposes_expected_functions():
    th = provider_modules.load_team_health_analyzer()

    assert callable(th.calculate_meeting_load)
    assert callable(th.classify_team_health)
    assert callable(th.rebalance_queue)
    assert callable(th.summarize_team_report)
    assert callable(th.update_threshold)


def test_load_calcom_pro_exposes_expected_functions_and_client():
    calcom = provider_modules.load_calcom_pro()

    assert callable(calcom.list_bookings)
    assert callable(calcom.create_booking)
    assert callable(calcom.update_booking)
    assert hasattr(calcom, "CalComClient")


def test_load_gcal_exposes_expected_functions_and_client():
    gcal = provider_modules.load_gcal()

    assert callable(gcal.list_events)
    assert callable(gcal.create_event)
    assert callable(gcal.update_event)
    assert callable(gcal.delete_event)
    assert callable(gcal.find_next_free_slot)
    assert hasattr(gcal, "GCalClient")


def test_load_slack_exposes_expected_functions_and_client():
    slack = provider_modules.load_slack()

    assert callable(slack.post_message)
    assert callable(slack.build_summary_blocks)
    assert callable(slack.verify_slack_signature)
    assert callable(slack.parse_slash_command)
    assert callable(slack.parse_interactive_payload)
    assert hasattr(slack, "SlackClient")


def test_loading_all_four_in_sequence_does_not_cross_contaminate():
    """Direct regression test for the real bug: loading all 4 in any
    order must not make one bring back another's functions."""
    th = provider_modules.load_team_health_analyzer()
    calcom = provider_modules.load_calcom_pro()
    gcal = provider_modules.load_gcal()
    slack = provider_modules.load_slack()
    th_again = provider_modules.load_team_health_analyzer()

    # team-health-analyzer should never bring back anything from the other three.
    assert not hasattr(th, "CalComClient")
    assert not hasattr(th, "GCalClient")
    assert not hasattr(th, "SlackClient")
    assert not hasattr(th_again, "list_bookings")
    assert not hasattr(th_again, "list_events")
    assert not hasattr(th_again, "post_message")

    # The three providers shouldn't mix with each other either.
    assert not hasattr(calcom, "GCalClient")
    assert not hasattr(calcom, "SlackClient")
    assert not hasattr(gcal, "CalComClient")
    assert not hasattr(gcal, "SlackClient")
    assert not hasattr(slack, "CalComClient")
    assert not hasattr(slack, "GCalClient")

    # And team-health-analyzer still works after loading the other three.
    assert th_again.calculate_meeting_load([{"person": "ana", "duration_minutes": 60}], []) == {"ana": 1.0}


def test_reloading_same_module_twice_returns_working_module():
    """Loading the same module twice in a row (e.g. two consecutive
    HTTP requests to the GUI) must not break anything."""
    first = provider_modules.load_calcom_pro()
    second = provider_modules.load_calcom_pro()

    assert callable(first.list_bookings)
    assert callable(second.list_bookings)
