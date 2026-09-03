"""Handlers for the your-handle/notion module.

VALIDATED (29 Aug 2026) against Notion API's current official
documentation (developers.notion.com/reference):

  - Base URL: https://api.notion.com/v1
  - POST  /pages          -- creates a page (create_notion_profile)
  - PATCH /pages/{id}      -- updates properties (mark_onboarding_complete)
  - Auth: Bearer token + required `Notion-Version` header.

REAL VERSIONING RISK (not a bug, an explicit decision): on 2025-09-03
Notion split "databases" into "data sources", and the current docs
show `parent: {"data_source_id": "..."}` instead of
`parent: {"database_id": "..."}` for creating pages. This handler
deliberately pins `Notion-Version: 2022-06-28` and keeps using
`database_id`, because:
  (a) it's the pattern still followed by the vast majority of
      tutorials, SDKs and active integrations today,
  (b) pinning an old version is still valid in Notion's API (they
      version by date, they don't break old versions).
If the target workspace was created/migrated after that date and uses
new data sources, it may be necessary to switch to data_source_id and
bump the Notion-Version -- flagged here explicitly so it isn't
discovered in production with a hard-to-diagnose error.

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
"""
import os
import requests

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"  # see versioning risk note above


def _headers() -> dict:
    token = os.environ.get("NOTION_API_KEY")
    if not token:
        raise RuntimeError(
            "NOTION_API_KEY is not configured. In production this is "
            "injected via RailCall Studio > Integrations, never hardcoded."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def create_page(inputs: dict, context: dict) -> dict:
    """POST /pages. `properties` already arrives built in the format
    Notion requires (see the example in README) since it depends on
    the target database's column schema -- this handler can't invent
    it."""
    body = {
        "parent": {"database_id": inputs["database_id"]},
        "properties": inputs["properties"],
    }
    resp = requests.post(f"{BASE_URL}/pages", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def update_page(inputs: dict, context: dict) -> dict:
    """PATCH /pages/{id}. Only updates `properties` -- doesn't touch
    content (blocks), which is a separate endpoint in Notion's API."""
    page_id = inputs["page_id"]
    resp = requests.patch(
        f"{BASE_URL}/pages/{page_id}", headers=_headers(),
        json={"properties": inputs["properties"]}, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
