"""
Tests for gcal.

- The actions that call the API (list_events, create_event,
  update_event, find_next_free_slot) are tested with the HTTP layer
  mocked — no real network call, no real credentials.
- `_first_free_slot` is pure logic and is tested directly, without
  mocks, with several edge cases. It's the easiest part of this
  module to trust without external validation.

**None of these tests replace testing against a real Google Calendar
account** (see README.md).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import GCalClient, GCalAPIError
from actions import (
    list_events,
    create_event,
    update_event,
    delete_event,
    find_next_free_slot,
    _first_free_slot,
)


def make_client():
    return GCalClient(access_token="ya29.test-dummy-token")


def mock_response(status_code=200, json_data=None, text_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    # The client now checks `response.text` to detect bodyless
    # responses (e.g. DELETE's 204) before calling .json(). If
    # text_data isn't passed explicitly, a non-empty body needs to be
    # simulated when json_data IS present, so as not to break tests
    # that don't care about this detail.
    if text_data is not None:
        resp.text = text_data
    else:
        resp.text = "" if json_data is None else "non-empty-body"
    return resp


# ---------------------------------------------------------------------------
# Actions that call the API (mocked)
# ---------------------------------------------------------------------------

@patch("client.requests.request")
def test_list_events_calls_correct_endpoint(mock_request):
    mock_request.return_value = mock_response(
        json_data={"items": [{"id": "evt1", "summary": "Standup"}]}
    )

    client = make_client()
    result = list_events(
        client, "ana@example.com", "2026-09-01T00:00:00Z", "2026-09-07T23:59:59Z"
    )

    assert result == [{"id": "evt1", "summary": "Standup"}]
    _, called_url = mock_request.call_args.args
    assert called_url == "https://www.googleapis.com/calendar/v3/calendars/ana@example.com/events"
    params = mock_request.call_args.kwargs["params"]
    assert params["singleEvents"] == "true"
    assert params["orderBy"] == "startTime"


@patch("client.requests.request")
def test_create_event_sends_expected_payload(mock_request):
    mock_request.return_value = mock_response(
        json_data={"id": "evt-new", "summary": "Focus Time"}
    )

    client = make_client()
    result = create_event(
        client,
        "ana@example.com",
        summary="Focus Time",
        start_iso="2026-09-01T09:00:00",
        end_iso="2026-09-01T10:00:00",
        timezone="America/Argentina/Buenos_Aires",
        description="Blocked by Fika Sync",
    )

    assert result["id"] == "evt-new"
    sent_json = mock_request.call_args.kwargs["json"]
    assert sent_json["summary"] == "Focus Time"
    assert sent_json["start"]["dateTime"] == "2026-09-01T09:00:00"
    assert sent_json["description"] == "Blocked by Fika Sync"


@patch("client.requests.request")
def test_update_event_hits_correct_path(mock_request):
    mock_request.return_value = mock_response(json_data={"id": "evt1"})

    client = make_client()
    update_event(client, "ana@example.com", "evt1", {"summary": "Focus Time (extendido)"})

    _, called_url = mock_request.call_args.args
    assert called_url == "https://www.googleapis.com/calendar/v3/calendars/ana@example.com/events/evt1"


@patch("client.requests.request")
def test_delete_event_handles_empty_204_response(mock_request):
    mock_request.return_value = mock_response(status_code=204, text_data="")

    client = make_client()
    result = delete_event(client, "ana@example.com", "evt1")

    assert result == {}
    _, called_url = mock_request.call_args.args
    assert called_url == "https://www.googleapis.com/calendar/v3/calendars/ana@example.com/events/evt1"
    assert mock_request.call_args.args[0] == "DELETE"


@patch("client.requests.request")
def test_find_next_free_slot_uses_freebusy_and_parses_result(mock_request):
    mock_request.return_value = mock_response(
        json_data={
            "calendars": {
                "ana@example.com": {
                    "busy": [
                        {"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T10:00:00+00:00"}
                    ]
                }
            }
        }
    )

    client = make_client()
    result = find_next_free_slot(
        client, "ana@example.com", duration_minutes=30,
        search_start_iso="2026-09-01T09:00:00+00:00",
        search_end_iso="2026-09-01T12:00:00+00:00",
    )

    assert result == {
        "start": "2026-09-01T10:00:00+00:00",
        "end": "2026-09-01T10:30:00+00:00",
    }
    _, called_url = mock_request.call_args.args
    assert called_url == "https://www.googleapis.com/calendar/v3/freeBusy"


@patch("client.requests.request")
def test_api_error_raises_gcal_api_error(mock_request):
    mock_request.return_value = mock_response(
        status_code=403,
        json_data={"error": {"message": "rateLimitExceeded"}},
    )

    client = make_client()
    with pytest.raises(GCalAPIError) as exc_info:
        list_events(client, "ana@example.com", "2026-09-01T00:00:00Z", "2026-09-07T23:59:59Z")

    assert exc_info.value.status_code == 403


def test_from_env_requires_all_three_vars(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)

    with pytest.raises(ValueError) as exc_info:
        GCalClient.from_env()

    assert "GOOGLE_CLIENT_ID" in str(exc_info.value)


@patch("client.requests.post")
def test_from_refresh_token_exchanges_for_access_token(mock_post):
    mock_post.return_value = mock_response(json_data={"access_token": "ya29.new-token"})

    client = GCalClient.from_refresh_token("client-id", "client-secret", "refresh-token")

    assert client.access_token == "ya29.new-token"
    sent_data = mock_post.call_args.kwargs["data"]
    assert sent_data["grant_type"] == "refresh_token"
    assert sent_data["refresh_token"] == "refresh-token"


# ---------------------------------------------------------------------------
# _first_free_slot: pure logic, no mocks
# ---------------------------------------------------------------------------

def test_first_free_slot_no_busy_periods_returns_search_start():
    result = _first_free_slot(
        busy_periods=[],
        search_start_iso="2026-09-01T09:00:00+00:00",
        search_end_iso="2026-09-01T17:00:00+00:00",
        duration_minutes=60,
    )
    assert result == {
        "start": "2026-09-01T09:00:00+00:00",
        "end": "2026-09-01T10:00:00+00:00",
    }


def test_first_free_slot_skips_over_busy_period():
    result = _first_free_slot(
        busy_periods=[
            {"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T11:00:00+00:00"}
        ],
        search_start_iso="2026-09-01T09:00:00+00:00",
        search_end_iso="2026-09-01T17:00:00+00:00",
        duration_minutes=30,
    )
    assert result == {
        "start": "2026-09-01T11:00:00+00:00",
        "end": "2026-09-01T11:30:00+00:00",
    }


def test_first_free_slot_finds_gap_between_two_busy_periods():
    result = _first_free_slot(
        busy_periods=[
            {"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T10:00:00+00:00"},
            {"start": "2026-09-01T10:15:00+00:00", "end": "2026-09-01T11:00:00+00:00"},
        ],
        search_start_iso="2026-09-01T09:00:00+00:00",
        search_end_iso="2026-09-01T17:00:00+00:00",
        duration_minutes=15,
    )
    assert result == {
        "start": "2026-09-01T10:00:00+00:00",
        "end": "2026-09-01T10:15:00+00:00",
    }


def test_first_free_slot_returns_none_when_fully_booked():
    result = _first_free_slot(
        busy_periods=[
            {"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T17:00:00+00:00"}
        ],
        search_start_iso="2026-09-01T09:00:00+00:00",
        search_end_iso="2026-09-01T17:00:00+00:00",
        duration_minutes=30,
    )
    assert result is None


def test_first_free_slot_ignores_unsorted_and_overlapping_periods():
    result = _first_free_slot(
        busy_periods=[
            {"start": "2026-09-01T12:00:00+00:00", "end": "2026-09-01T13:00:00+00:00"},
            {"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T12:30:00+00:00"},
        ],
        search_start_iso="2026-09-01T09:00:00+00:00",
        search_end_iso="2026-09-01T17:00:00+00:00",
        duration_minutes=30,
    )
    assert result == {
        "start": "2026-09-01T13:00:00+00:00",
        "end": "2026-09-01T13:30:00+00:00",
    }
