# sheets

Integrates Fika Sync with the [Google Sheets v4 API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append)
to append rows to a spreadsheet — used to export the weekly summary
(`fika-sync`) and for the onboarding checklist
(`workflows/onboarding-automator`).

## ⚠️ Status: written, not validated against a real sheet

**5/5 tests passing**, all with the HTTP layer mocked. No call has
been tested against a real spreadsheet.

## Configuration

Reuses the same OAuth variables as `gcal`:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REFRESH_TOKEN`

**Important:** the refresh token needs the
`https://www.googleapis.com/auth/spreadsheets` scope. If it was
generated with only the Calendar scope
(`https://www.googleapis.com/auth/calendar`, used by `gcal`), this
module's calls will fail with 403. The consent needs to be redone
with both scopes together, or a separate OAuth Client used just for
Sheets.

`SHEETS_SPREADSHEET_ID` is also needed (the sheet's ID, visible in
its URL) — see `fika-sync/.env.example`.

## Actions

| Action | Google endpoint | Use |
|---|---|---|
| `append_row(client, spreadsheet_id, sheet_range, row_values, value_input_option="USER_ENTERED")` | `POST /spreadsheets/{id}/values/{range}:append` | `export_to_sheet`, `log_history` (fika-sync); `log_onboarding_checklist` (onboarding-automator) |

## Usage example

```python
from client import SheetsClient
from actions import append_row

client = SheetsClient.from_env()

append_row(
    client, "YOUR_SPREADSHEET_ID", "History!A:D",
    ["2026-09-01", "ana", "22.0", "red"],
)
```

## Before using this in a real demo

1. Create a test Google Sheets spreadsheet and note its ID.
2. Generate (or regenerate) Google's refresh token including the
   spreadsheets scope.
3. Run `append_row` against that sheet and confirm the row appears
   where expected.
4. Update this README with the findings.

## Tests

```bash
cd modules/sheets
python3 -m pytest tests/ -v
```

Current status: **5/5 tests passing** (verified on 2026-08-30, with
mocks — doesn't replace validation against a real sheet).
