"""Handlers for the your-handle/sheets module.

VALIDATED (29 Aug 2026) against Google Sheets API v4's current
official documentation
(developers.google.com/workspace/sheets/api/reference/rest):

  - Base URL: https://sheets.googleapis.com/v4
  - POST /spreadsheets/{spreadsheetId}/values/{range}:append
  - PUT  /spreadsheets/{spreadsheetId}/values/{range}
  - GET  /spreadsheets/{spreadsheetId}/values/{range}
  - Auth: OAuth2 Bearer token.

IMPORTANT -- "upsert_row" (used by fika-sync/export_digest_sheet and
budget-guardian/log_budget_snapshot) is NOT a native Sheets endpoint:
Sheets API v4 has no upsert. It's implemented here as business logic:
  1. Read the key column (values.get)
  2. If the key already exists in some row, do a values.update on that
     specific row (PUT to an exact range, e.g. "Sheet1!A5:D5")
  3. If it doesn't exist, do a values.append

This means upsert_row makes 2-3 HTTP calls, not 1 -- it's slower than
a plain append but there's no way around it with this API.

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
"""
import os
import requests

BASE_URL = "https://sheets.googleapis.com/v4"


def _headers() -> dict:
    token = os.environ.get("GOOGLE_SHEETS_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "GOOGLE_SHEETS_ACCESS_TOKEN is not configured. In production "
            "this is injected via RailCall Studio > Integrations (OAuth2), "
            "never hardcoded."
        )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def append_row(inputs: dict, context: dict) -> dict:
    """POST /spreadsheets/{id}/values/{range}:append. `range` is
    usually the sheet name, e.g. 'fika_audit_log' -- Sheets finds the
    table and appends after the last row with data."""
    sheet_range = inputs.get("range", inputs["sheet"])
    params = {"valueInputOption": "USER_ENTERED"}
    body = {"values": [inputs["row"]]}
    resp = requests.post(
        f"{BASE_URL}/spreadsheets/{inputs['spreadsheet_id']}/values/{sheet_range}:append",
        headers=_headers(), params=params, json=body, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _get_values(spreadsheet_id: str, sheet_range: str) -> list:
    resp = requests.get(
        f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{sheet_range}",
        headers=_headers(), timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("values", [])


def update_row(inputs: dict, context: dict) -> dict:
    """PUT /spreadsheets/{id}/values/{range} (values.update). Overwrites
    a specific row. `row_number` is 1-based and includes the header
    row if the sheet has one."""
    sheet_name = inputs["sheet"]
    row_number = inputs["row_number"]
    update_range = f"{sheet_name}!A{row_number}"
    resp = requests.put(
        f"{BASE_URL}/spreadsheets/{inputs['spreadsheet_id']}/values/{update_range}",
        headers=_headers(),
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": [inputs["row"]]},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def upsert_row(inputs: dict, context: dict) -> dict:
    """Not a native Sheets endpoint (see the module docstring): reads
    the key column, and if `key_value` already exists in some row does
    an UPDATE (PUT) on that exact row; if not, does an APPEND.
    `key_column_index` is 0-based (0 = column A)."""
    spreadsheet_id = inputs["spreadsheet_id"]
    sheet_name = inputs["sheet"]
    key_value = str(inputs["key_value"])
    key_column_index = inputs.get("key_column_index", 0)

    existing = _get_values(spreadsheet_id, sheet_name)
    match_row_number = None  # 1-based, includes headers if present
    for i, row in enumerate(existing, start=1):
        if len(row) > key_column_index and str(row[key_column_index]) == key_value:
            match_row_number = i
            break

    if match_row_number is not None:
        update_range = f"{sheet_name}!A{match_row_number}"
        resp = requests.put(
            f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{update_range}",
            headers=_headers(),
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": [inputs["row"]]},
            timeout=15,
        )
        resp.raise_for_status()
        return {"action": "updated", "row_number": match_row_number, "result": resp.json()}

    params = {"valueInputOption": "USER_ENTERED"}
    resp = requests.post(
        f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{sheet_name}:append",
        headers=_headers(), params=params, json={"values": [inputs["row"]]}, timeout=15,
    )
    resp.raise_for_status()
    return {"action": "appended", "result": resp.json()}
