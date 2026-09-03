"""
INTEGRATION tests for calcom-pro — call the real Cal.com API.

Unlike tests/test_actions.py (which mocks everything), these tests do
NOT run by default. They're skipped automatically unless:

  1. The RUN_LIVE_TESTS=1 environment variable is set, AND
  2. CALCOM_API_KEY is set with a TEST account's key.

Tests that create or modify data (marked below) also require
ALLOW_LIVE_WRITES=1, so it's impossible to run them by accident.

How to run them:

    export RUN_LIVE_TESTS=1
    export CALCOM_API_KEY=cal_test_xxxxx          # TEST account
    export CALCOM_TEST_EVENT_TYPE_ID=123            # test "Focus Time" event type
    export ALLOW_LIVE_WRITES=1                      # only if you want to run the write ones
    cd modules/calcom-pro
    python3 -m pytest tests/test_integration.py -v -s

What to check manually after running them (an automatic assert can't
verify this):
  - That list_bookings returns meetings you recognize as real.
  - That create_booking actually created an event visible on the test
    account's Cal.com calendar.
  - That the response format (field names inside response["data"])
    matches what actions.py assumes — if it doesn't, actions.py and
    its mock-based tests need to be adjusted.

**This module doesn't have a "delete/cancel booking" action yet.**
If you run the write tests, you'll have to cancel the test
booking/event by hand from the Cal.com UI.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import CalComClient
from actions import list_bookings, create_booking, update_booking


RUN_LIVE = os.environ.get("RUN_LIVE_TESTS") == "1"
HAS_API_KEY = bool(os.environ.get("CALCOM_API_KEY"))
ALLOW_WRITES = os.environ.get("ALLOW_LIVE_WRITES") == "1"
TEST_EVENT_TYPE_ID = os.environ.get("CALCOM_TEST_EVENT_TYPE_ID")

skip_readonly = pytest.mark.skipif(
    not (RUN_LIVE and HAS_API_KEY),
    reason="Set RUN_LIVE_TESTS=1 and CALCOM_API_KEY to run this against real Cal.com.",
)

skip_writes = pytest.mark.skipif(
    not (RUN_LIVE and HAS_API_KEY and ALLOW_WRITES and TEST_EVENT_TYPE_ID),
    reason=(
        "Set RUN_LIVE_TESTS=1, CALCOM_API_KEY, ALLOW_LIVE_WRITES=1 and "
        "CALCOM_TEST_EVENT_TYPE_ID to run this (creates real data)."
    ),
)


@pytest.fixture
def live_client():
    return CalComClient.from_env()


@skip_readonly
def test_live_list_bookings_returns_a_list(live_client, capsys):
    """Only verifies the call doesn't blow up and returns a list.

    We can't assert specific content because it depends on the test
    account's real data — so it prints the result for manual
    inspection (run with -s to see it).
    """
    bookings = list_bookings(live_client, status="upcoming")

    assert isinstance(bookings, list)
    with capsys.disabled():
        print(f"\n[calcom-pro] list_bookings returned {len(bookings)} meetings.")
        if bookings:
            print(f"[calcom-pro] First record (check fields by hand): {bookings[0]}")


@skip_writes
def test_live_create_and_update_booking(live_client, capsys):
    """Creates a test booking and edits it. Requires manual cleanup."""
    created = create_booking(
        live_client,
        event_type_id=int(TEST_EVENT_TYPE_ID),
        start_iso="2026-12-01T09:00:00Z",
        attendee_name="Fika Sync Test",
        attendee_email="fika-sync-test@example.com",
        attendee_timezone="UTC",
        length_in_minutes=15,
    )
    assert "uid" in created, f"Unexpected response, check the format: {created}"

    updated = update_booking(live_client, created["uid"], {"title": "Fika Sync Test (edited)"})

    with capsys.disabled():
        print(f"\n[calcom-pro] Test booking created: uid={created['uid']}")
        print(f"[calcom-pro] Booking updated: {updated}")
        print(
            "[calcom-pro] ⚠️  Cancel this booking by hand from the Cal.com UI "
            "— this module doesn't have a cancel action yet."
        )
