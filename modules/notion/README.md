# your-handle/notion

Creates and updates pages in Notion, used by `onboarding-automator`
(`create_notion_profile`, `mark_onboarding_complete`).

## Status

✅ Real endpoints (`POST /pages`, `PATCH /pages/{id}`).

⚠️ **Real versioning risk, not a bug**: this handler pins
`Notion-Version: 2022-06-28` and uses `parent: {database_id: ...}`
deliberately, because it's what most active integrations still
follow. Notion split "databases" into "data sources" on 2025-09-03;
if the target workspace uses the new model, it may be necessary to
switch to `data_source_id` and bump the version. See the detailed
comment in `handler.py`.

⚠️ Not tested against a real workspace. The `properties` format
depends 100% on the target database's column schema -- there's no way
to guess it without connecting to the real account first.

## Auth

API key (Internal Integration Token), `NOTION_API_KEY` environment
variable.
