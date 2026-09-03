"""
INTEGRATION tests for sheets — calls the real Google Sheets API.

Same as calcom-pro, gcal and slack: they do NOT run by default.
They're skipped unless:

  1. RUN_LIVE_TESTS=1
  2. GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN are
     set (the refresh token needs the spreadsheets scope, not just
     Calendar's — see this module's README.md).
  3. ALLOW_LIVE_WRITES=1 (append_row always writes, there's no
     read-only version — same as post_message in slack).
  4. SHEETS_TEST_SPREADSHEET_ID with a test sheet's ID.

How to run them:

    export RUN_LIVE_TESTS=1
    export GOOGLE_CLIENT_ID=...
    export GOOGLE_CLIENT_SECRET=...
    export GOOGLE_REFRESH_TOKEN=...
    export ALLOW_LIVE_WRITES=1
    export SHEETS_TEST_SPREADSHEET_ID=...
    export SHEETS_TEST_RANGE="Sheet1!A:D"       # optional, default below
    cd modules/sheets
    python3 -m pytest tests/test_integration.py -v -s

What to check manually afterward:
  - That the row actually appears in the sheet, at the expected
    position (at the end of the table detected in SHEETS_TEST_RANGE,
    not necessarily within that exact range — see the note in
    `actions.append_row`).
  - If it fails with 403 "The caller does not have permission" or
    similar, it's most likely that the refresh token was generated
    without the spreadsheets scope — check the OAuth consent, not the
    code.
  - Confirm the response format (`updates.updatedRange`,
    `updates.updatedRows`) against what `actions.py` assumes.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client import SheetsClient
from actions import append_row


RUN_LIVE = os.environ.get("RUN_LIVE_TESTS") == "1"
HAS_CREDS = all(
    os.environ.get(v) for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
)
ALLOW_WRITES = os.environ.get("ALLOW_LIVE_WRITES") == "1"
TEST_SPREADSHEET_ID = os.environ.get("SHEETS_TEST_SPREADSHEET_ID")
TEST_RANGE = os.environ.get("SHEETS_TEST_RANGE", "Sheet1!A:D")

skip_writes = pytest.mark.skipif(
    not (RUN_LIVE and HAS_CREDS and ALLOW_WRITES and TEST_SPREADSHEET_ID),
    reason=(
        "Set RUN_LIVE_TESTS=1, the 3 Google credentials, ALLOW_LIVE_WRITES=1 "
        "and SHEETS_TEST_SPREADSHEET_ID to run this (appends a real row)."
    ),
)


@pytest.fixture
def live_client():
    return SheetsClient.from_env()


@skip_writes
def test_live_append_row(live_client, capsys):
    result = append_row(
        live_client, TEST_SPREADSHEET_ID, TEST_RANGE,
        ["fika-sync-test", "integration-test", "ok"],
    )

    assert "updates" in result, f"Unexpected response, check the format: {result}"

    with capsys.disabled():
        print(f"\n[sheets] Row added at: {result['updates'].get('updatedRange')}")
        print(
            "[sheets] ⚠️  Manually check in the sheet that the row appeared "
            "where you expected — this test doesn't delete it."
        )
