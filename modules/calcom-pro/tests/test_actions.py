"""
Tests for calcom-pro. All HTTP calls are mocked — none of these
tests makes a real network call or requires credentials. This
verifies that the functions' signature and request building are
correct, but **does not replace testing against a real Cal.com
account** (see README.md).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import CalComClient, CalComAPIError
from actions import list_bookings, create_booking, update_booking


def make_client():
    return CalComClient(api_key="cal_test_dummy_key")


def mock_response(status_code=200, json_data=None, text_data=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = text_data
    return resp


@patch("client.requests.request")
def test_list_bookings_calls_correct_endpoint_and_parses_data(mock_request):
    mock_request.return_value = mock_response(
        json_data={"status": "success", "data": [{"uid": "abc"}]}
    )

    client = make_client()
    result = list_bookings(client, status="upcoming")

    assert result == [{"uid": "abc"}]
    _, called_url = mock_request.call_args.args
    assert called_url == "https://api.cal.com/v2/bookings"
    assert mock_request.call_args.kwargs["params"] == {"status": "upcoming"}
    assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer cal_test_dummy_key"
    assert mock_request.call_args.kwargs["headers"]["cal-api-version"] == "2026-05-01"


@patch("client.requests.request")
def test_create_booking_sends_expected_payload(mock_request):
    mock_request.return_value = mock_response(
        json_data={"status": "success", "data": {"uid": "new-uid"}}
    )

    client = make_client()
    result = create_booking(
        client,
        event_type_id=123,
        start_iso="2026-09-01T09:00:00Z",
        attendee_name="Ana",
        attendee_email="ana@example.com",
        attendee_timezone="America/Argentina/Buenos_Aires",
        length_in_minutes=30,
    )

    assert result == {"uid": "new-uid"}
    sent_json = mock_request.call_args.kwargs["json"]
    assert sent_json["eventTypeId"] == 123
    assert sent_json["attendee"]["email"] == "ana@example.com"
    assert sent_json["lengthInMinutes"] == 30
    assert mock_request.call_args.kwargs["headers"]["cal-api-version"] == "2026-02-25"


@patch("client.requests.request")
def test_create_booking_omits_length_when_not_given(mock_request):
    mock_request.return_value = mock_response(
        json_data={"status": "success", "data": {"uid": "new-uid"}}
    )

    client = make_client()
    create_booking(
        client,
        event_type_id=123,
        start_iso="2026-09-01T09:00:00Z",
        attendee_name="Ana",
        attendee_email="ana@example.com",
        attendee_timezone="America/Argentina/Buenos_Aires",
    )

    sent_json = mock_request.call_args.kwargs["json"]
    assert "lengthInMinutes" not in sent_json


@patch("client.requests.request")
def test_update_booking_hits_correct_uid_path(mock_request):
    mock_request.return_value = mock_response(
        json_data={"status": "success", "data": {"uid": "abc"}}
    )

    client = make_client()
    update_booking(client, "abc", {"start": "2026-09-01T10:00:00Z"})

    _, called_url = mock_request.call_args.args
    assert called_url == "https://api.cal.com/v2/bookings/abc"


@patch("client.requests.request")
def test_api_error_raises_calcom_api_error(mock_request):
    mock_request.return_value = mock_response(
        status_code=401, json_data={"status": "error", "message": "Invalid API key"}
    )

    client = make_client()
    with pytest.raises(CalComAPIError) as exc_info:
        list_bookings(client)

    assert exc_info.value.status_code == 401


def test_client_from_env_requires_api_key(monkeypatch):
    monkeypatch.delenv("CALCOM_API_KEY", raising=False)
    with pytest.raises(ValueError):
        CalComClient.from_env()


def test_client_from_env_reads_api_key(monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_from_env")
    client = CalComClient.from_env()
    assert client.api_key == "cal_live_from_env"
    assert client.base_url == "https://api.cal.com/v2"
