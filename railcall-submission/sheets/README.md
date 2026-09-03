# sheets — Google Sheets for RailCall

## What it does

Two commands against the real [Google Sheets API v4](https://developers.google.com/workspace/sheets/api/reference/rest):

- **`read_values`** — read a range of cells (A1 notation).
- **`append_row`** — append a row after the last row of a detected table.

## Who it's for

Small teams whose AI agent or RailCall workflow needs a simple, human-readable audit log or export target — a running list of what a workflow did, a weekly export of computed numbers — without standing up a database, and with every write going through RailCall's preview → approve → execute → signed-receipt discipline instead of a silent script writing to a shared sheet.

Concrete use case: a weekly team-health workflow appends one row per person (date, name, hours, status) to a shared spreadsheet HR already looks at — a human sees the exact row before it's written, because `append_row` is `side_effects: "external"`.

## Install

```bash
railcall market install juani1972/sheets
```

Set a valid Google OAuth access token in Studio → Integrations. See "Known limitations" — this module expects the token to already be valid; it does not refresh it. The token needs the `https://www.googleapis.com/auth/spreadsheets` scope specifically — the Calendar scope used by `juani1972/gcal` is a different one, so a token that only works for that module won't work for this one.

## Example

```bash
railcall airlock stage append_row --inputs '{
  "spreadsheet_id": "1AbC...xyz", "range": "Historial!A:D",
  "values": ["2026-09-01", "ana", "22.0", "red"]
}'
railcall airlock approve <staging_id>
```

Expected output:

```json
{"updated_range": "Historial!A5:D5", "updated_rows": 1}
```

## Credentials needed

- A Google OAuth 2.0 access token with the Sheets scope
  (`https://www.googleapis.com/auth/spreadsheets`), set via Studio →
  Integrations.

## Known limitations

- **Access tokens expire in ~1 hour and this module does not refresh
  them** — same caveat as `juani1972/gcal`, and for the same reason:
  whether RailCall's `oauth2` auth type auto-refreshes for a *custom*
  (non-catalogue) provider isn't documented anywhere I could find.
  Shipped as a static credential, limitation stated plainly, rather
  than assuming a refresh mechanism that might not exist.
- **`append_row` always appends** — there's no `update_cell` or
  `write_range` command yet for overwriting specific cells rather than
  adding a new row.
- **Not yet run against a real Station install** — no network route
  to `railcall.ai` from this environment. Verified instead: 9 unit
  tests with `urllib.urlopen` mocked (`tests/test_handler.py`).
  Function naming is `_h_<name>`, confirmed by the [Publisher
  FAQ](https://railcall.ai/docs/marketplace-developer/faq/)
  rejection-reason list — not a guess. `vault_get("sheets")` returns
  `{"access_token": "..."}` (falls back to `"api_key"`), also
  confirmed there.
- `module.json` declares a sandbox `requires` block
  (`network: ["sheets.googleapis.com"]`, no subprocess, no filesystem
  writes) — opt-in since Station v0.33+, not yet tested against a
  real Station's enforcement.

## Source

Standard library only (`urllib.request`, `json`) — no external
dependencies. ~100 lines across `module.json` + `handlers/handler.py`.
