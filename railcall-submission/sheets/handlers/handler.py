"""Handlers for the juani1972/sheets module.

Same pattern as the other three modules in this submission: commands
are `_h_<name>` functions — the confirmed RailCall loader requirement
per the Publisher FAQ (https://railcall.ai/docs/marketplace-developer/faq/,
"Why did my module get rejected on install?") — with bare-name
aliases kept only for readability, and credentials read via
`__rc_helpers__["vault_get"]("sheets")` (confirmed shape
`{"api_key": "..."}`, Station v0.29+). See juani1972/gcal's handler
docstring for why this module also ships with a static
(non-refreshing) access-token credential instead of guessing at
OAuth2 refresh support for a custom provider.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

SHEETS_BASE_URL = "https://sheets.googleapis.com/v4"


class SheetsError(Exception):
    """Raised for any non-2xx response from the Google Sheets API."""


def _vault_access_token() -> str:
    result = __rc_helpers__["vault_get"]("sheets")  # noqa: F821 — injected by the RailCall loader
    if isinstance(result, dict):
        token = result.get("access_token") or result.get("api_key")
    else:
        token = result
    if not token:
        raise SheetsError(
            "No Google access token found in the vault. Set it up in "
            "Studio → Integrations → sheets before running this command."
        )
    return token


def _request(method: str, path: str, params: dict = None, body: dict = None) -> dict:
    url = f"{SHEETS_BASE_URL}{path}"
    if params:
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v is not None)
        if query:
            url = f"{url}?{query}"

    headers = {
        "Authorization": f"Bearer {_vault_access_token()}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise SheetsError(f"Google Sheets API returned {exc.code}: {error_body}") from exc


# ---------------------------------------------------------------------------
# Commands (must match module.json exactly)
# ---------------------------------------------------------------------------

def _h_read_values(inputs: dict, context: dict) -> dict:
    """Read a range of cells from a spreadsheet.

    inputs: {"spreadsheet_id": str, "range": str}
    Returns: {"values": list[list]}
    """
    for field in ("spreadsheet_id", "range"):
        if not inputs.get(field):
            raise SheetsError(f"Missing required input: {field}")

    path = f"/spreadsheets/{urllib.parse.quote(inputs['spreadsheet_id'])}/values/{urllib.parse.quote(inputs['range'], safe='')}"
    response = _request("GET", path)
    return {"values": response.get("values", [])}


def _h_append_row(inputs: dict, context: dict) -> dict:
    """Append a row after the last row of a detected table.

    inputs: {"spreadsheet_id": str, "range": str, "values": list}
    Returns: {"updated_range": str, "updated_rows": int}
    """
    for field in ("spreadsheet_id", "range", "values"):
        if not inputs.get(field):
            raise SheetsError(f"Missing required input: {field}")
    if not isinstance(inputs["values"], list):
        raise SheetsError("'values' must be a list of cell values for the new row.")

    path = f"/spreadsheets/{urllib.parse.quote(inputs['spreadsheet_id'])}/values/{urllib.parse.quote(inputs['range'], safe='')}:append"
    response = _request(
        "POST", path,
        params={"valueInputOption": "USER_ENTERED"},
        body={"majorDimension": "ROWS", "values": [inputs["values"]]},
    )
    updates = response.get("updates", {})
    return {"updated_range": updates.get("updatedRange"), "updated_rows": updates.get("updatedRows", 0)}


# ---------------------------------------------------------------------------
# Bare-name aliases — readability only, not required by the loader
# (which calls the `_h_`-prefixed functions above directly).
# ---------------------------------------------------------------------------

read_values = _h_read_values
append_row = _h_append_row
