"""Contract tests: verify handler.py calls the correct HTTP method, URL
and headers per Cal.com API v2's official documentation. They don't
test Cal.com's real response (a real account is needed for that) --
they verify we no longer call made-up endpoints.
"""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["CALCOM_API_KEY"] = "test_key"

# Loaded by path with a unique name -- see the identical comment in
# modules/team-health-analyzer/test/test_handler.py about why a
# normal `import handler` collides between the two "handler.py" modules.
_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("calcom_pro_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["calcom_pro_handler"] = handler  # needed so @patch("calcom_pro_handler....") can resolve it


def _mock_response(json_data=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data or {"status": "success"}
    return resp


@patch("calcom_pro_handler.requests.get")
def test_list_events_hits_bookings_get(mock_get):
    mock_get.return_value = _mock_response()
    handler.list_events({"from_date": "2026-01-01", "to_date": "2026-01-07"}, {})
    url = mock_get.call_args.args[0]
    headers = mock_get.call_args.kwargs["headers"]
    assert url == "https://api.cal.com/v2/bookings"
    assert headers["cal-api-version"] == "2024-08-13"


@patch("calcom_pro_handler.requests.post")
def test_create_event_hits_bookings_post_with_event_type_and_full_attendee(mock_post):
    mock_post.return_value = _mock_response()
    handler.create_event(
        {
            "event_type_id": "42",
            "start": "2026-02-01T10:00:00Z",
            "attendee_name": "Ana",
            "attendee_email": "a@b.com",
            "attendee_timezone": "Europe/Madrid",
        },
        {},
    )
    assert mock_post.call_args.args[0] == "https://api.cal.com/v2/bookings"
    body = mock_post.call_args.kwargs["json"]
    assert body["eventTypeId"] == "42"
    assert "end" not in body  # Cal.com v2 no acepta 'end': lo define el event type
    assert body["attendee"] == {"name": "Ana", "email": "a@b.com", "timeZone": "Europe/Madrid"}


@patch("calcom_pro_handler.requests.post")
def test_update_event_hits_reschedule_not_patch(mock_post):
    mock_post.return_value = _mock_response()
    handler.update_event({"event_id": "abc123", "start": "2026-02-01T10:00:00Z"}, {})
    assert mock_post.call_args.args[0] == "https://api.cal.com/v2/bookings/abc123/reschedule"


def test_update_event_rejects_title_change():
    try:
        handler.update_event({"event_id": "abc123", "title": "nuevo titulo"}, {})
        assert False, "should have raised NotImplementedError"
    except NotImplementedError:
        pass


@patch("calcom_pro_handler.requests.post")
def test_delete_event_hits_cancel_not_delete(mock_post):
    mock_post.return_value = _mock_response()
    handler.delete_event({"event_id": "abc123"}, {})
    assert mock_post.call_args.args[0] == "https://api.cal.com/v2/bookings/abc123/cancel"


@patch("calcom_pro_handler.requests.get")
def test_get_availability_hits_slots_not_availability(mock_get):
    mock_get.return_value = _mock_response()
    handler.get_availability(
        {"username": "u", "event_type_id": "10", "from_date": "2026-01-01", "to_date": "2026-01-07"},
        {},
    )
    url = mock_get.call_args.args[0]
    params = mock_get.call_args.kwargs["params"]
    assert url == "https://api.cal.com/v2/slots"
    assert params["eventTypeId"] == "10"


def test_sync_calendar_raises_instead_of_silent_404():
    try:
        handler.sync_calendar({"username": "u"}, {})
        assert False, "should have raised NotImplementedError"
    except NotImplementedError:
        pass


@patch("calcom_pro_handler.requests.get")
def test_all_requests_include_cal_api_version_header(mock_get):
    mock_get.return_value = _mock_response()
    handler.list_events({"from_date": "2026-01-01", "to_date": "2026-01-07"}, {})
    headers = mock_get.call_args.kwargs["headers"]
    assert "cal-api-version" in headers


ATTENDEE = {
    "attendee_name": "Ana",
    "attendee_email": "a@b.com",
    "attendee_timezone": "Europe/Madrid",
}

SLOTS_RESPONSE = {
    "data": {
        "slots": {
            "2026-03-02": [
                {"time": "2026-03-02T08:00:00Z"},
                {"time": "2026-03-02T14:00:00Z"},
            ],
            "2026-03-03": [
                {"time": "2026-03-03T09:30:00Z"},
            ],
        }
    }
}


@patch("calcom_pro_handler.requests.post")
@patch("calcom_pro_handler.requests.get")
def test_book_slot_sends_full_attendee_object(mock_get, mock_post):
    mock_get.return_value = _mock_response(SLOTS_RESPONSE)
    mock_post.return_value = _mock_response({"id": "bk_1"})
    handler.book_slot(
        {"username": "u", "event_type_id": "10", "slot_start": "2026-03-02T08:00:00Z", **ATTENDEE},
        {},
    )
    body = mock_post.call_args.kwargs["json"]
    assert body["attendee"] == {"name": "Ana", "email": "a@b.com", "timeZone": "Europe/Madrid"}


@patch("calcom_pro_handler.requests.post")
@patch("calcom_pro_handler.requests.get")
def test_protect_focus_time_picks_earliest_morning_slot(mock_get, mock_post):
    mock_get.return_value = _mock_response(SLOTS_RESPONSE)
    mock_post.return_value = _mock_response({"id": "bk_2"})
    result = handler.protect_focus_time(
        {
            "username": "u", "event_type_id": "focus_2h",
            "from_date": "2026-03-02", "to_date": "2026-03-03",
            "priority": "morning", **ATTENDEE,
        },
        {},
    )
    # of the 3 slots, only 08:00 and 09:30 are morning (<12h UTC); the earliest is 08:00
    assert result["blocked_slot"] == "2026-03-02T08:00:00Z"
    assert mock_post.call_args.kwargs["json"]["start"] == "2026-03-02T08:00:00Z"


@patch("calcom_pro_handler.requests.post")
@patch("calcom_pro_handler.requests.get")
def test_protect_focus_time_picks_afternoon_slot(mock_get, mock_post):
    mock_get.return_value = _mock_response(SLOTS_RESPONSE)
    mock_post.return_value = _mock_response({"id": "bk_3"})
    result = handler.protect_focus_time(
        {
            "username": "u", "event_type_id": "focus_2h",
            "from_date": "2026-03-02", "to_date": "2026-03-03",
            "priority": "afternoon", **ATTENDEE,
        },
        {},
    )
    assert result["blocked_slot"] == "2026-03-02T14:00:00Z"


@patch("calcom_pro_handler.requests.get")
def test_protect_focus_time_raises_when_no_matching_slots(mock_get):
    # all slots are AM/PM depending on the case -- requesting "afternoon" over an
    # empty response must fail explicitly, not return a fake booking
    mock_get.return_value = _mock_response({"data": {"slots": {}}})
    try:
        handler.protect_focus_time(
            {
                "username": "u", "event_type_id": "focus_2h",
                "from_date": "2026-03-02", "to_date": "2026-03-03",
                "priority": "any", **ATTENDEE,
            },
            {},
        )
        assert False, "should have raised RuntimeError"
    except RuntimeError:
        pass
