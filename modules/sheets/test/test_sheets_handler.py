"""Contract tests for modules/sheets/handlers/handler.py."""
import importlib.util
import os
from unittest.mock import patch, MagicMock

os.environ["GOOGLE_SHEETS_ACCESS_TOKEN"] = "test_token"

_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("sheets_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)
import sys  # noqa: E402
sys.modules["sheets_handler"] = handler


def _resp(json_data=None):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = json_data or {}
    return r


@patch("sheets_handler.requests.post")
def test_append_row_hits_values_append(mock_post):
    mock_post.return_value = _resp({"updates": {"updatedRows": 1}})
    handler.append_row({"spreadsheet_id": "SS1", "sheet": "fika_audit_log", "row": ["a", "b"]}, {})
    url = mock_post.call_args.args[0]
    assert url == "https://sheets.googleapis.com/v4/spreadsheets/SS1/values/fika_audit_log:append"
    assert mock_post.call_args.kwargs["json"] == {"values": [["a", "b"]]}
    assert mock_post.call_args.kwargs["params"]["valueInputOption"] == "USER_ENTERED"


@patch("sheets_handler.requests.put")
@patch("sheets_handler.requests.get")
def test_upsert_row_updates_when_key_found(mock_get, mock_put):
    # fila 1 = header, fila 2 = p1 (no matchea), fila 3 = p2 (matchea)
    mock_get.return_value = _resp({"values": [["person_id", "hours"], ["p1", "10"], ["p2", "20"]]})
    mock_put.return_value = _resp({"updatedRows": 1})
    result = handler.upsert_row(
        {"spreadsheet_id": "SS1", "sheet": "fika_weekly_digest", "key_value": "p2", "row": ["p2", "23"]},
        {},
    )
    assert result["action"] == "updated"
    assert result["row_number"] == 3
    put_url = mock_put.call_args.args[0]
    assert put_url == "https://sheets.googleapis.com/v4/spreadsheets/SS1/values/fika_weekly_digest!A3"
    assert mock_put.call_args.kwargs["json"] == {"values": [["p2", "23"]]}


@patch("sheets_handler.requests.post")
@patch("sheets_handler.requests.get")
def test_upsert_row_appends_when_key_not_found(mock_get, mock_post):
    mock_get.return_value = _resp({"values": [["person_id", "hours"], ["p1", "10"]]})
    mock_post.return_value = _resp({"updates": {"updatedRows": 1}})
    result = handler.upsert_row(
        {"spreadsheet_id": "SS1", "sheet": "fika_weekly_digest", "key_value": "p3", "row": ["p3", "5"]},
        {},
    )
    assert result["action"] == "appended"
    mock_post.assert_called_once()


@patch("sheets_handler.requests.get")
def test_upsert_row_handles_empty_sheet(mock_get):
    mock_get.return_value = _resp({})  # no "values" -- empty sheet
    with patch("sheets_handler.requests.post") as mock_post:
        mock_post.return_value = _resp({})
        result = handler.upsert_row(
            {"spreadsheet_id": "SS1", "sheet": "vacia", "key_value": "p1", "row": ["p1", "1"]}, {}
        )
    assert result["action"] == "appended"


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEETS_ACCESS_TOKEN", raising=False)
    try:
        handler.append_row({"spreadsheet_id": "SS1", "sheet": "x", "row": ["a"]}, {})
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "GOOGLE_SHEETS_ACCESS_TOKEN" in str(e)


@patch("sheets_handler.requests.put")
def test_update_row_hits_values_update_at_exact_row(mock_put):
    mock_put.return_value = _resp({"updatedRows": 1})
    handler.update_row(
        {"spreadsheet_id": "SS1", "sheet": "meeting_debt_ledger", "row_number": 7, "row": ["p1", "paid"]},
        {},
    )
    url = mock_put.call_args.args[0]
    assert url == "https://sheets.googleapis.com/v4/spreadsheets/SS1/values/meeting_debt_ledger!A7"
    assert mock_put.call_args.kwargs["json"] == {"values": [["p1", "paid"]]}
