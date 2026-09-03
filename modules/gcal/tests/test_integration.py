"""
INTEGRATION tests for gcal — call the real Google Calendar API.

Same as calcom-pro: they do NOT run by default. They're skipped
unless:

  1. RUN_LIVE_TESTS=1
  2. GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN are
     set (from a TEST account/calendar).

Tests that create or modify events also require ALLOW_LIVE_WRITES=1.

How to run them:

    export RUN_LIVE_TESTS=1
    export GOOGLE_CLIENT_ID=...
    export GOOGLE_CLIENT_SECRET=...
    export GOOGLE_REFRESH_TOKEN=...
    export GCAL_TEST_CALENDAR_ID=your-test-account@gmail.com   # or "primary"
    export ALLOW_LIVE_WRITES=1                                     # only for the write ones
    cd modules/gcal
    python3 -m pytest tests/test_integration.py -v -s

What to check manually afterward:
  - That list_events returns real events from the test calendar.
  - That find_next_free_slot proposes a slot that's actually free
    when looking at the calendar in the UI.
  - That create_event created a visible event (the test deletes it
    itself at the end with delete_event, but it's worth looking at it
    in the UI while the test runs if you want to confirm it visually).
  - Confirm how long the access token actually lasts in practice (the
    documentation says ~1 hour) to decide whether it needs to be
    cached between real workflow runs.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import GCalClient
from actions import list_events, create_event, update_event, delete_event, find_next_free_slot


RUN_LIVE = os.environ.get("RUN_LIVE_TESTS") == "1"
HAS_CREDS = all(
    os.environ.get(v) for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
)
ALLOW_WRITES = os.environ.get("ALLOW_LIVE_WRITES") == "1"
TEST_CALENDAR_ID = os.environ.get("GCAL_TEST_CALENDAR_ID", "primary")

skip_readonly = pytest.mark.skipif(
    not (RUN_LIVE and HAS_CREDS),
    reason="Set RUN_LIVE_TESTS=1 and the 3 Google credentials to run this against the real API.",
)

skip_writes = pytest.mark.skipif(
    not (RUN_LIVE and HAS_CREDS and ALLOW_WRITES),
    reason="Also set ALLOW_LIVE_WRITES=1 to run this (creates/edits real data).",
)


@pytest.fixture
def live_client():
    return GCalClient.from_env()


@skip_readonly
def test_live_list_events_returns_a_list(live_client, capsys):
    events = list_events(
        live_client, TEST_CALENDAR_ID,
        time_min_iso="2026-01-01T00:00:00Z",
        time_max_iso="2026-12-31T23:59:59Z",
    )

    assert isinstance(events, list)
    with capsys.disabled():
        print(f"\n[gcal] list_events returned {len(events)} events on {TEST_CALENDAR_ID}.")
        if events:
            print(f"[gcal] First event (check fields by hand): {events[0]}")


@skip_readonly
def test_live_find_next_free_slot_returns_plausible_result(live_client, capsys):
    slot = find_next_free_slot(
        live_client, TEST_CALENDAR_ID, duration_minutes=30,
        search_start_iso="2026-12-01T09:00:00+00:00",
        search_end_iso="2026-12-01T18:00:00+00:00",
    )

    with capsys.disabled():
        print(f"\n[gcal] find_next_free_slot proposed: {slot}")
        print(
            "[gcal] ⚠️  Manually confirm in the Google Calendar UI that "
            "that time is actually free on the test calendar."
        )


@skip_writes
def test_live_create_and_update_event(live_client, capsys):
    created = create_event(
        live_client, TEST_CALENDAR_ID,
        summary="Fika Sync Test",
        start_iso="2026-12-01T09:00:00",
        end_iso="2026-12-01T09:15:00",
        timezone="UTC",
        description="Test event created by gcal's integration tests.",
    )
    assert "id" in created, f"Unexpected response, check the format: {created}"

    try:
        updated = update_event(
            live_client, TEST_CALENDAR_ID, created["id"], {"summary": "Fika Sync Test (edited)"}
        )
        with capsys.disabled():
            print(f"\n[gcal] Test event created: id={created['id']}")
            print(f"[gcal] Event updated: {updated}")
    finally:
        # Automatic cleanup: don't leave clutter on the test calendar
        # even if the assert above fails.
        delete_event(live_client, TEST_CALENDAR_ID, created["id"])
        with capsys.disabled():
            print(f"[gcal] Test event {created['id']} deleted automatically.")
