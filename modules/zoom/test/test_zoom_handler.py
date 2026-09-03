"""Contract tests for modules/zoom/handlers/handler.py."""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["ZOOM_ACCESS_TOKEN"] = "test_token"

_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("zoom_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["zoom_handler"] = handler


def _resp(json_data=None):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = json_data or {}
    return r


@patch("zoom_handler.requests.get")
def test_get_meeting_actual_duration_hits_past_meetings(mock_get):
    mock_get.return_value = _resp({"duration": 47, "start_time": "s", "end_time": "e"})
    result = handler.get_meeting_actual_duration({"meeting_uuid": "abc123"}, {})
    assert mock_get.call_args.args[0] == "https://api.zoom.us/v2/past_meetings/abc123"
    assert result["actual_duration_minutes"] == 47


@patch("zoom_handler.requests.get")
def test_meeting_uuid_with_slash_gets_double_encoded(mock_get):
    # real Zoom gotcha: UUIDs with '/' need double URL-encoding
    mock_get.return_value = _resp({"duration": 30})
    handler.get_meeting_actual_duration({"meeting_uuid": "ab/cd=="}, {})
    url = mock_get.call_args.args[0]
    # 'ab/cd==' -> quote() once -> 'ab%2Fcd%3D%3D' -> quote() again -> 'ab%252Fcd%253D%253D'
    assert "%252F" in url  # the '/' double-encoded


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ZOOM_ACCESS_TOKEN", raising=False)
    try:
        handler.get_meeting_actual_duration({"meeting_uuid": "x"}, {})
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "ZOOM_ACCESS_TOKEN" in str(e)
