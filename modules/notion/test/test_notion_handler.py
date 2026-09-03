"""Contract tests for modules/notion/handlers/handler.py."""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["NOTION_API_KEY"] = "secret_test"

_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("notion_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["notion_handler"] = handler


def _resp(json_data=None):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = json_data or {}
    return r


@patch("notion_handler.requests.post")
def test_create_page_hits_pages_endpoint_with_database_parent(mock_post):
    mock_post.return_value = _resp({"id": "page_1"})
    props = {"Name": {"title": [{"text": {"content": "Alex Ruiz"}}]}}
    handler.create_page({"database_id": "db_1", "properties": props}, {})
    assert mock_post.call_args.args[0] == "https://api.notion.com/v1/pages"
    body = mock_post.call_args.kwargs["json"]
    assert body["parent"] == {"database_id": "db_1"}
    assert body["properties"] == props
    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Notion-Version"] == "2022-06-28"


@patch("notion_handler.requests.patch")
def test_update_page_hits_pages_id_endpoint(mock_patch):
    mock_patch.return_value = _resp({"id": "page_1"})
    props = {"Status": {"select": {"name": "Complete"}}}
    handler.update_page({"page_id": "page_1", "properties": props}, {})
    assert mock_patch.call_args.args[0] == "https://api.notion.com/v1/pages/page_1"
    assert mock_patch.call_args.kwargs["json"] == {"properties": props}


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    try:
        handler.create_page({"database_id": "db_1", "properties": {}}, {})
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "NOTION_API_KEY" in str(e)
