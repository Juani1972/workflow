"""Contract tests for modules/asana/handlers/handler.py."""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["ASANA_ACCESS_TOKEN"] = "test_token"

_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("asana_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["asana_handler"] = handler


def _resp(json_data=None):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = json_data or {}
    return r


@patch("asana_handler.requests.post")
def test_create_tasks_from_template_calls_instantiate_per_template(mock_post):
    mock_post.side_effect = [
        _resp({"data": {"gid": "job_1"}}),
        _resp({"data": {"gid": "job_2"}}),
    ]
    result = handler.create_tasks_from_template({"template_gids": ["tpl_1", "tpl_2"]}, {})
    assert result["template_count"] == 2
    assert len(result["jobs"]) == 2
    first_url = mock_post.call_args_list[0].args[0]
    second_url = mock_post.call_args_list[1].args[0]
    assert first_url == "https://app.asana.com/api/1.0/task_templates/tpl_1/instantiateTask"
    assert second_url == "https://app.asana.com/api/1.0/task_templates/tpl_2/instantiateTask"


@patch("asana_handler.requests.post")
def test_create_tasks_from_template_applies_name_override(mock_post):
    mock_post.return_value = _resp({"data": {"gid": "job_1"}})
    handler.create_tasks_from_template({"template_gids": ["tpl_1"], "name": "Onboarding Alex"}, {})
    body = mock_post.call_args.kwargs["json"]
    assert body == {"data": {"name": "Onboarding Alex"}}


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ASANA_ACCESS_TOKEN", raising=False)
    try:
        handler.create_tasks_from_template({"template_gids": ["tpl_1"]}, {})
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "ASANA_ACCESS_TOKEN" in str(e)
