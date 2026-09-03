"""Contract tests for modules/slack/handlers/handler.py."""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"

_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("slack_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["slack_handler"] = handler


def _ok_response(extra=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    data = {"ok": True}
    if extra:
        data.update(extra)
    resp.json.return_value = data
    return resp


def _error_response(error="channel_not_found"):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"ok": False, "error": error}
    return resp


@patch("slack_handler.requests.post")
def test_post_message_hits_chat_post_message(mock_post):
    mock_post.return_value = _ok_response()
    handler.post_message({"channel": "#team-wellbeing", "text": "hi"}, {})
    assert mock_post.call_args.args[0] == "https://slack.com/api/chat.postMessage"
    body = mock_post.call_args.kwargs["json"]
    assert body == {"channel": "#team-wellbeing", "text": "hi"}
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer xoxb-test"


@patch("slack_handler.requests.post")
def test_post_message_raises_on_ok_false_despite_http_200(mock_post):
    # Slack returns 200 OK even on logical errors -- this is the
    # classic bug of only trusting raise_for_status()
    mock_post.return_value = _error_response("channel_not_found")
    try:
        handler.post_message({"channel": "#does-not-exist", "text": "hi"}, {})
        assert False, "should have raised RuntimeError for ok=false"
    except RuntimeError as e:
        assert "channel_not_found" in str(e)


@patch("slack_handler.requests.post")
def test_post_message_with_buttons_builds_block_kit_actions(mock_post):
    mock_post.return_value = _ok_response()
    handler.post_message_with_buttons(
        {
            "channel": "#team-wellbeing",
            "text": "Approve protecting 4h of focus time for Sam?",
            "buttons": [
                {"label": "Approve", "action_id": "approve", "style": "primary"},
                {"label": "Reject", "action_id": "reject", "style": "danger"},
            ],
        },
        {},
    )
    body = mock_post.call_args.kwargs["json"]
    assert body["blocks"][1]["type"] == "actions"
    assert body["blocks"][1]["elements"][0]["action_id"] == "approve"
    assert body["blocks"][1]["elements"][0]["style"] == "primary"
    assert body["blocks"][1]["elements"][1]["action_id"] == "reject"


@patch("slack_handler.requests.post")
def test_post_dm_opens_conversation_then_posts(mock_post):
    mock_post.side_effect = [
        _ok_response({"channel": {"id": "D0123456"}}),  # conversations.open
        _ok_response(),  # chat.postMessage
    ]
    handler.post_dm({"user_id": "U0999", "text": "You exceeded your daily threshold"}, {})
    first_call_url = mock_post.call_args_list[0].args[0]
    second_call_url = mock_post.call_args_list[1].args[0]
    assert first_call_url == "https://slack.com/api/conversations.open"
    assert mock_post.call_args_list[0].kwargs["json"] == {"users": "U0999"}
    assert second_call_url == "https://slack.com/api/chat.postMessage"
    assert mock_post.call_args_list[1].kwargs["json"]["channel"] == "D0123456"


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    try:
        handler.post_message({"channel": "#x", "text": "y"}, {})
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "SLACK_BOT_TOKEN" in str(e)
