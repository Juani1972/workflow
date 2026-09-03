"""
High-level actions for the sheets module.

Used by fika-sync/workflow.csv (export_to_sheet, log_history) and by
workflows/onboarding-automator/workflow.csv (log_onboarding_checklist).

**Not tested against a real spreadsheet.**
"""

from __future__ import annotations

from typing import Optional

from client import SheetsClient


def append_row(client: SheetsClient, spreadsheet_id: str, sheet_range: str,
                row_values: list, value_input_option: str = "USER_ENTERED") -> dict:
    """Appends a row to the end of a table (POST .../values/{range}:append).

    Args:
        client: an already-authenticated SheetsClient instance.
        spreadsheet_id: the sheet's ID (appears in the Google Sheets URL).
        sheet_range: range in A1 notation where the table should be
            looked for, e.g. "History!A:D". Google appends after that
            table's last row, not necessarily within that exact range.
        row_values: list of values for the new row, e.g.
            ["2026-09-01", "ana", "22.0", "red"].
        value_input_option: "USER_ENTERED" (default, interprets dates
            and formulas as if a person had typed them) or "RAW"
            (stores the values as-is, without interpretation).

    Returns:
        dict with Google's response (includes "updates" with the
        actual range where it was written).
    """
    return client.post(
        f"/spreadsheets/{spreadsheet_id}/values/{sheet_range}:append",
        params={"valueInputOption": value_input_option},
        json_body={"majorDimension": "ROWS", "values": [row_values]},
    )
