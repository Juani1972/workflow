"""Contract tests for modules/gcal/handlers/handler.py: verify URL,
HTTP method and payload are correct per Google Calendar API v3's
official docs. They don't test against a real account (a real Google
OAuth2 token is needed for that)."""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["GOOGLE_CALENDAR_ACCESS_TOKEN"] = "test_token"

_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("gcal_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["gcal_handler"] = handler


def _mock_response(json_data=None, status=200):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    return resp


@patch("gcal_handler.requests.get")
def test_list_events_hits_events_list(mock_get):
    mock_get.return_value = _mock_response({"items": []})
    handler.list_events({"from_date": "2026-01-01T00:00:00Z", "to_date": "2026-01-07T00:00:00Z"}, {})
    assert mock_get.call_args.args[0] == "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    params = mock_get.call_args.kwargs["params"]
    assert params["timeMin"] == "2026-01-01T00:00:00Z"
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test_token"


@patch("gcal_handler.requests.get")
def test_list_events_respects_custom_calendar_id(mock_get):
    mock_get.return_value = _mock_response({"items": []})
    handler.list_events(
        {"calendar_id": "team@example.com", "from_date": "2026-01-01T00:00:00Z", "to_date": "2026-01-07T00:00:00Z"},
        {},
    )
    assert mock_get.call_args.args[0] == "https://www.googleapis.com/calendar/v3/calendars/team@example.com/events"


@patch("gcal_handler.requests.post")
def test_create_event_hits_events_insert_with_start_end_timezone(mock_post):
    mock_post.return_value = _mock_response({"id": "evt_1"})
    handler.create_event(
        {"title": "Focus Time (auto)", "start": "2026-01-05T09:00:00", "end": "2026-01-05T11:00:00",
         "timezone": "Europe/Madrid"},
        {},
    )
    assert mock_post.call_args.args[0] == "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    body = mock_post.call_args.kwargs["json"]
    assert body["summary"] == "Focus Time (auto)"
    assert body["start"] == {"dateTime": "2026-01-05T09:00:00", "timeZone": "Europe/Madrid"}
    assert body["end"] == {"dateTime": "2026-01-05T11:00:00", "timeZone": "Europe/Madrid"}


@patch("gcal_handler.requests.patch")
def test_update_event_hits_events_patch_partial(mock_patch):
    mock_patch.return_value = _mock_response({"id": "evt_1"})
    handler.update_event({"event_id": "evt_1", "title": "New title"}, {})
    assert mock_patch.call_args.args[0] == "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt_1"
    body = mock_patch.call_args.kwargs["json"]
    assert body == {"summary": "New title"}  # only sends what changed, not empty start/end


@patch("gcal_handler.requests.delete")
def test_delete_event_hits_events_delete(mock_delete):
    mock_delete.return_value = _mock_response(status=204)
    result = handler.delete_event({"event_id": "evt_1"}, {})
    assert mock_delete.call_args.args[0] == "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt_1"
    assert result == {"deleted": True, "event_id": "evt_1"}


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALENDAR_ACCESS_TOKEN", raising=False)
    try:
        handler.list_events({"from_date": "a", "to_date": "b"}, {})
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "GOOGLE_CALENDAR_ACCESS_TOKEN" in str(e)
