import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import SheetsClient, SheetsAPIError
from actions import append_row


def make_client():
    return SheetsClient(access_token="ya29.test-dummy-token")


def mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.text = "non-empty-body"
    return resp


@patch("client.requests.request")
def test_append_row_calls_correct_endpoint_and_payload(mock_request):
    mock_request.return_value = mock_response(json_data={
        "spreadsheetId": "abc123",
        "updates": {"updatedRange": "Historial!A5:D5", "updatedRows": 1},
    })

    client = make_client()
    result = append_row(client, "abc123", "Historial!A:D", ["2026-09-01", "ana", "22.0", "red"])

    assert result["updates"]["updatedRows"] == 1
    _, called_url = mock_request.call_args.args
    assert called_url == "https://sheets.googleapis.com/v4/spreadsheets/abc123/values/Historial!A:D:append"
    assert mock_request.call_args.kwargs["params"] == {"valueInputOption": "USER_ENTERED"}
    sent_json = mock_request.call_args.kwargs["json"]
    assert sent_json["values"] == [["2026-09-01", "ana", "22.0", "red"]]


@patch("client.requests.request")
def test_append_row_supports_raw_value_input_option(mock_request):
    mock_request.return_value = mock_response(json_data={"updates": {"updatedRows": 1}})

    client = make_client()
    append_row(client, "abc123", "Sheet1!A:A", ["=SUM(1,2)"], value_input_option="RAW")

    assert mock_request.call_args.kwargs["params"]["valueInputOption"] == "RAW"


@patch("client.requests.request")
def test_api_error_raises_sheets_api_error(mock_request):
    mock_request.return_value = mock_response(
        status_code=403, json_data={"error": {"message": "The caller does not have permission"}}
    )

    client = make_client()
    with pytest.raises(SheetsAPIError) as exc_info:
        append_row(client, "abc123", "Sheet1!A:A", ["x"])

    assert exc_info.value.status_code == 403


def test_from_env_requires_all_three_vars(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)

    with pytest.raises(ValueError) as exc_info:
        SheetsClient.from_env()

    assert "GOOGLE_CLIENT_ID" in str(exc_info.value)


@patch("client.requests.post")
def test_from_refresh_token_exchanges_for_access_token(mock_post):
    mock_post.return_value = mock_response(json_data={"access_token": "ya29.new-token"})

    client = SheetsClient.from_refresh_token("client-id", "client-secret", "refresh-token")

    assert client.access_token == "ya29.new-token"
