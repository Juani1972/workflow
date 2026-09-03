"""
Data layer for the Fika Sync GUI.

Uses SQLite (a file on disk, not in-memory) so data **survives a page
reload** — which was one of the three underlying problems identified
in the repo's original analysis.

Everything this layer stores is real and persistent: team, per-person
thresholds, weekly meeting hours (with history, not just the current
number), and a sync log. What is NOT real is the origin of that data
when no credentials are configured — that's explicitly marked as
"demo" on every row, never silently mixed with real data (see
seed_demo_week in app.py).
"""

from __future__ import annotations

import csv
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import os

DB_PATH_DEFAULT = Path(__file__).resolve().parent / "fika_sync.db"
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def get_db_path() -> Path:
    """Path to the SQLite file. Resolved on every call (not just once
    when the module is imported) so tests can override
    FIKA_SYNC_DB_PATH with a temporary database."""
    override = os.environ.get("FIKA_SYNC_DB_PATH")
    return Path(override) if override else DB_PATH_DEFAULT

SCHEMA = """
CREATE TABLE IF NOT EXISTS team (
    person TEXT PRIMARY KEY,
    calcom_username TEXT,
    gcal_email TEXT,
    slack_user_id TEXT,
    yellow_hours REAL NOT NULL,
    red_hours REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meeting_hours (
    person TEXT NOT NULL,
    week_start TEXT NOT NULL,  -- ISO date of that week's Monday
    hours REAL NOT NULL,
    source TEXT NOT NULL,      -- 'demo' | 'calcom+gcal'
    PRIMARY KEY (person, week_start)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,      -- 'demo' | 'calcom+gcal'
    status TEXT NOT NULL,      -- 'ok' | 'error'
    detail TEXT
);

CREATE TABLE IF NOT EXISTS app_oauth_credentials (
    provider TEXT PRIMARY KEY,    -- 'google' | 'slack'
    client_id TEXT NOT NULL,
    client_secret TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_connections (
    provider TEXT PRIMARY KEY,    -- 'google' | 'slack'
    access_token TEXT,
    refresh_token TEXT,           -- Google has one, Slack (bot token) doesn't
    token_type TEXT,
    scope TEXT,
    extra_json TEXT,              -- team_id/team_name/bot_user_id for slack, etc.
    connected_at TEXT NOT NULL,
    validated_at TEXT              -- NULL until the first successful real
                                    -- call to that API (see mark_connection_validated)
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,       -- random token, CSRF protection for the OAuth flow
    provider TEXT NOT NULL,
    person TEXT,                  -- NULL = app-level connection (slack, sheets); set = personal connection (that person's calendar)
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_oauth_connections (
    person TEXT NOT NULL,
    provider TEXT NOT NULL,       -- 'google' for now (that person's calendar)
    access_token TEXT,
    refresh_token TEXT,
    token_type TEXT,
    scope TEXT,
    connected_at TEXT NOT NULL,
    PRIMARY KEY (person, provider)
);

CREATE TABLE IF NOT EXISTS person_api_keys (
    person TEXT NOT NULL,
    provider TEXT NOT NULL,       -- 'calcom' for now — any provider
                                   -- that connects with a simple API
                                   -- key instead of OAuth, but on a
                                   -- per-person basis (not a key
                                   -- shared by the whole team, see
                                   -- oauth_connections for that).
    api_key TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    PRIMARY KEY (person, provider)
);

CREATE TABLE IF NOT EXISTS workflow_settings (
    workflow_id TEXT PRIMARY KEY,  -- 'fika-sync' | 'meeting-debt' | 'onboarding-automator' | 'budget-guardian'
    enabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notification_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- single row (singleton)
    slack_channel TEXT,
    sync_frequency_minutes INTEGER NOT NULL DEFAULT 0,  -- 0 = manual only
    auto_publish_on_sync INTEGER NOT NULL DEFAULT 0,
    personal_dms_enabled INTEGER NOT NULL DEFAULT 0,
    last_auto_sync_at TEXT
);
"""

# The 4 workflows that exist in the repo (see workflows/*/README.md
# and fika-sync/workflow.csv). Only fika-sync actually runs in this
# GUI — the other 3 are workflow.csv definitions for RailCall, which
# isn't part of this app. See WORKFLOW_DISPLAY_NAMES and the note in
# get_workflow_settings().
KNOWN_WORKFLOW_IDS = ("fika-sync", "meeting-debt", "onboarding-automator", "budget-guardian")
WORKFLOW_DISPLAY_NAMES = {
    "fika-sync": "Fika Sync (this dashboard)",
    "meeting-debt": "Meeting Debt",
    "onboarding-automator": "Onboarding Automator",
    "budget-guardian": "Budget Guardian",
}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Creates the tables if they don't exist, and seeds the team from
    config/team.example.csv + config/thresholds.example.json if the
    `team` table is empty (first run). Also seeds workflow_settings
    (the 4 known workflows) and notification_settings (the singleton
    row) if they're empty."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()

        # Light migration: CREATE TABLE IF NOT EXISTS doesn't add new
        # columns to a table that already existed from a previous run
        # of the app (there's no migration tool here, it's a single
        # singleton table). If the column already exists, SQLite
        # raises "duplicate column name" — deliberately ignored.
        try:
            conn.execute(
                "ALTER TABLE notification_settings ADD COLUMN personal_dms_enabled INTEGER NOT NULL DEFAULT 0"
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

        # Same light migration, for oauth_states.person: databases
        # created before per-person calendar connection
        # (oauth_start_for_person) don't have this column, and
        # create_oauth_state() always needs it — without this, anyone
        # who already had a fika_sync.db from a previous run would
        # hit "table oauth_states has no column named person" when
        # clicking "Connect my calendar".
        try:
            conn.execute("ALTER TABLE oauth_states ADD COLUMN person TEXT")
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

        # Same light migration, for oauth_connections.validated_at
        # (see mark_connection_validated): databases from before the
        # "connected ✓" badge existed don't have this column.
        try:
            conn.execute("ALTER TABLE oauth_connections ADD COLUMN validated_at TEXT")
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise

        existing = conn.execute("SELECT COUNT(*) AS n FROM team").fetchone()["n"]
        if existing == 0:
            _seed_team_from_config(conn)

        wf_count = conn.execute("SELECT COUNT(*) AS n FROM workflow_settings").fetchone()["n"]
        if wf_count == 0:
            for workflow_id in KNOWN_WORKFLOW_IDS:
                # fika-sync is the only one that actually runs in this
                # GUI — it starts enabled. The other 3 are
                # workflow.csv definitions for RailCall (they don't
                # execute here), so they start disabled to avoid
                # suggesting they're active when nothing is running
                # them yet.
                default_enabled = 1 if workflow_id == "fika-sync" else 0
                conn.execute(
                    "INSERT INTO workflow_settings (workflow_id, enabled) VALUES (?, ?)",
                    (workflow_id, default_enabled),
                )
            conn.commit()

        notif_count = conn.execute("SELECT COUNT(*) AS n FROM notification_settings").fetchone()["n"]
        if notif_count == 0:
            conn.execute(
                "INSERT INTO notification_settings (id, slack_channel, sync_frequency_minutes, auto_publish_on_sync) "
                "VALUES (1, NULL, 0, 0)"
            )
            conn.commit()
    finally:
        conn.close()


def _seed_team_from_config(conn: sqlite3.Connection) -> None:
    team_csv = CONFIG_DIR / "team.example.csv"
    thresholds_json = CONFIG_DIR / "thresholds.example.json"

    overrides = {}
    if thresholds_json.exists():
        data = json.loads(thresholds_json.read_text())
        default = data.get("default", {"yellow_hours": 15.0, "red_hours": 20.0})
        overrides = data.get("per_person_overrides", {})
    else:
        default = {"yellow_hours": 15.0, "red_hours": 20.0}

    if not team_csv.exists():
        return

    with open(team_csv) as f:
        for row in csv.DictReader(f):
            person = row["person"]
            person_thresholds = overrides.get(person, default)
            conn.execute(
                """INSERT OR IGNORE INTO team
                   (person, calcom_username, gcal_email, slack_user_id, yellow_hours, red_hours)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    person,
                    row.get("calcom_username", ""),
                    row.get("gcal_email", ""),
                    row.get("slack_user_id", ""),
                    float(person_thresholds.get("yellow_hours", default["yellow_hours"])),
                    float(person_thresholds.get("red_hours", default["red_hours"])),
                ),
            )
    conn.commit()


def get_team() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM team ORDER BY person").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_thresholds(person: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT yellow_hours, red_hours FROM team WHERE person = ?", (person,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_threshold(person: str, field: str, value: float) -> bool:
    """Persists a new threshold. Returns False if the person doesn't exist."""
    if field not in ("yellow_hours", "red_hours"):
        raise ValueError(f"field must be 'yellow_hours' or 'red_hours', got: {field!r}")

    conn = get_connection()
    try:
        cursor = conn.execute(
            f"UPDATE team SET {field} = ? WHERE person = ?", (value, person)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Team management: add, edit, remove people
# ---------------------------------------------------------------------------
# Before this, the team could only be loaded by seeding
# config/team.example.csv on startup — there was no way to add or
# remove people without editing that file by hand and restarting.
# This adds real management from the GUI.

def add_team_member(person: str, calcom_username: str = "", gcal_email: str = "",
                     slack_user_id: str = "", yellow_hours: float = 15.0,
                     red_hours: float = 20.0) -> bool:
    """Adds a new person to the team.

    Returns:
        True if added, False if a person with that name already
        existed (it doesn't overwrite — use update_team_member to edit).

    Raises:
        ValueError: if red_hours isn't greater than yellow_hours, or
            if person is empty.
    """
    person = person.strip()
    if not person:
        raise ValueError("The person's name cannot be empty.")
    if red_hours <= yellow_hours:
        raise ValueError(
            f"red_hours ({red_hours}) must be greater than yellow_hours ({yellow_hours})."
        )

    conn = get_connection()
    try:
        existing = conn.execute("SELECT 1 FROM team WHERE person = ?", (person,)).fetchone()
        if existing:
            return False

        conn.execute(
            """INSERT INTO team
               (person, calcom_username, gcal_email, slack_user_id, yellow_hours, red_hours)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (person, calcom_username, gcal_email, slack_user_id, yellow_hours, red_hours),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def update_team_member(person: str, calcom_username: Optional[str] = None,
                        gcal_email: Optional[str] = None,
                        slack_user_id: Optional[str] = None) -> bool:
    """Edits a person's identity data (not the thresholds — for that,
    use set_threshold). Only updates fields that are passed (not
    None); passing "" does clear the field, on purpose.

    Returns:
        True if the person existed and was updated, False if they
        didn't exist.
    """
    fields = {
        "calcom_username": calcom_username,
        "gcal_email": gcal_email,
        "slack_user_id": slack_user_id,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return person in {m["person"] for m in get_team()}

    conn = get_connection()
    try:
        set_clause = ", ".join(f"{field} = ?" for field in fields)
        cursor = conn.execute(
            f"UPDATE team SET {set_clause} WHERE person = ?",
            (*fields.values(), person),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_team_member(person: str) -> bool:
    """Removes a person from the team, and cleans up their hours
    history (meeting_hours), their personal calendar connection
    (person_oauth_connections) and their personal Cal.com key
    (person_api_keys) so no orphan rows or credentials are left for
    someone no longer on the team.

    Returns:
        True if the person existed and was deleted, False if they
        didn't exist.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM team WHERE person = ?", (person,))
        conn.execute("DELETE FROM meeting_hours WHERE person = ?", (person,))
        conn.execute("DELETE FROM person_oauth_connections WHERE person = ?", (person,))
        conn.execute("DELETE FROM person_api_keys WHERE person = ?", (person,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def record_meeting_hours(person: str, week_start: str, hours: float, source: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO meeting_hours (person, week_start, hours, source)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(person, week_start) DO UPDATE SET hours=excluded.hours, source=excluded.source""",
            (person, week_start, hours, source),
        )
        conn.commit()
    finally:
        conn.close()


def get_hours_for_week(week_start: str) -> dict:
    """dict {person: hours} for a given week. Doesn't include people
    with no data for that week."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT person, hours FROM meeting_hours WHERE week_start = ?", (week_start,)
        ).fetchall()
        return {r["person"]: r["hours"] for r in rows}
    finally:
        conn.close()


def get_history(person: str, limit_weeks: int = 8) -> list[dict]:
    """A person's last `limit_weeks` weeks, ordered by ascending date."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT week_start, hours, source FROM meeting_hours
               WHERE person = ? ORDER BY week_start DESC LIMIT ?""",
            (person, limit_weeks),
        ).fetchall()
        return list(reversed([dict(r) for r in rows]))
    finally:
        conn.close()


def log_sync(timestamp: str, source: str, status: str, detail: str = "") -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sync_log (timestamp, source, status, detail) VALUES (?, ?, ?, ?)",
            (timestamp, source, status, detail),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_syncs(limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def reset_db() -> None:
    """Deletes the database file. Used by the tests and by the GUI's
    reset endpoint."""
    conn = get_connection()
    conn.close()
    db_path = get_db_path()
    if db_path.exists():
        db_path.unlink()


# ---------------------------------------------------------------------------
# OAuth connections ("Connect Google" / "Connect Slack" with one click)
# ---------------------------------------------------------------------------
#
# Before this, the only way for gcal/sheets/slack to have credentials
# was for a developer to generate a refresh token / bot token by hand
# (via OAuth Playground or the Slack console) and paste it into
# environment variables. This adds the flow for an end USER to
# authorize access with one click, without touching any environment
# variable — the token is saved here, not in the .env.
#
# Environment variables are still needed, but for something else:
# GOOGLE_CLIENT_ID/SECRET and SLACK_CLIENT_ID/SECRET identify the
# Fika Sync APPLICATION to Google/Slack (they're the same for every
# user) — that's still configured by whoever deploys the app, not
# each end user.
#
# **Why there are TWO kinds of connection (app-level vs. per-person):**
# Slack (posting to a channel) and Sheets (exporting to a shared
# sheet) make sense with a SINGLE account connected at the app level
# — anyone with that token can publish/export for the whole team.
# Google Calendar does NOT work that way: one person's token can't
# read another person's calendar (Google doesn't allow it, unless
# it's explicitly shared or there's a service account with
# domain-wide delegation). That's why the calendar connects via
# `person_oauth_connections` — one row per person, each authorizing
# their own — instead of sharing the `oauth_connections` table
# (which still exists, at the app level, for Slack/Sheets/Cal.com).

def create_oauth_state(provider: str, person: Optional[str] = None) -> str:
    """Generates a single-use token to protect the OAuth flow against
    CSRF, and saves it so it can be validated in the callback.

    Args:
        provider: 'google' | 'slack' | 'calcom'.
        person: if passed, this state is for a personal connection
            (that specific person's calendar) — None means an
            app-level connection.
    """
    state = secrets.token_urlsafe(24)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO oauth_states (state, provider, person, created_at) VALUES (?, ?, ?, ?)",
            (state, provider, person, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return state


def consume_oauth_state(state: str) -> Optional[dict]:
    """Returns {provider, person} associated with that state and
    deletes it (single use — if someone retries the same state, it no
    longer exists).

    Returns:
        dict {"provider": str, "person": str|None} if the state was
        valid, None if it didn't exist (made-up state, reused, or
        from a previous server run).
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT provider, person FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        conn.commit()
        return {"provider": row["provider"], "person": row["person"]}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# app_oauth_credentials — APPLICATION-level Client ID/Secret (Google,
# Slack), configurable from the GUI instead of only via environment
# variable. Whoever administers the installation pastes them here
# once; from then on, any team member uses the "Connect" buttons
# without touching this again. `oauth_service._resolve_app_credentials`
# prioritizes what's saved here over environment variables — same
# pattern already used by `_build_calcom_client` (guided > env var).
#
# The client_secret IS stored in plain text in fika_sync.db, just like
# the tokens in `oauth_connections` — this repo never claimed to
# encrypt secrets at rest (see README, "What's still demo"), it's a
# tool meant to run locally, not an exposed service.
# ---------------------------------------------------------------------------

def save_app_oauth_credentials(provider: str, client_id: str, client_secret: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO app_oauth_credentials (provider, client_id, client_secret, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(provider) DO UPDATE SET
                 client_id = excluded.client_id,
                 client_secret = excluded.client_secret,
                 updated_at = excluded.updated_at
            """,
            (provider, client_id, client_secret, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_app_oauth_credentials(provider: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM app_oauth_credentials WHERE provider = ?", (provider,)
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError as exc:
        # DB not initialized yet (init_db() hasn't run) — treated the
        # same as "nobody has configured anything here yet", not as
        # an error: oauth_service falls back to the environment
        # variable. This shouldn't happen in the real app
        # (create_app() always calls init_db() before serving
        # requests), but it's a reasonable safeguard anyway.
        if "no such table" not in str(exc).lower():
            raise
        return None
    finally:
        conn.close()


def delete_app_oauth_credentials(provider: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM app_oauth_credentials WHERE provider = ?", (provider,))
        conn.commit()
    finally:
        conn.close()


def save_oauth_connection(provider: str, access_token: Optional[str] = None,
                           refresh_token: Optional[str] = None,
                           token_type: Optional[str] = None,
                           scope: Optional[str] = None,
                           extra: Optional[dict] = None) -> None:
    """Saves (or updates) a provider's connection.

    If `refresh_token` is None on an update (Google doesn't always
    resend it), the previously saved one is kept — a valid
    refresh_token is never overwritten with an empty one.
    """
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO oauth_connections
               (provider, access_token, refresh_token, token_type, scope, extra_json, connected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider) DO UPDATE SET
                 access_token = excluded.access_token,
                 refresh_token = COALESCE(excluded.refresh_token, oauth_connections.refresh_token),
                 token_type = excluded.token_type,
                 scope = excluded.scope,
                 extra_json = excluded.extra_json,
                 connected_at = excluded.connected_at
            """,
            (
                provider, access_token, refresh_token, token_type, scope,
                json.dumps(extra) if extra else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_oauth_connection(provider: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM oauth_connections WHERE provider = ?", (provider,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["extra"] = json.loads(result["extra_json"]) if result.get("extra_json") else {}
        return result
    finally:
        conn.close()


def mark_connection_validated(provider: str, validated_at: str) -> None:
    """Marks that `provider`'s APP-LEVEL credentials (Cal.com, Google
    or Slack) have already been tested against the real API and work
    — not just that they're saved in the correct format.

    Who calls this and when, per provider (see app.py):
    - calcom: when saving the key, with a real test call to
      list_bookings at that moment — before this, calcom_connect()
      only checked the "cal_" prefix, never actually tested it.
    - google / slack: when the code-for-token exchange in
      oauth_callback() succeeds — Google/Slack only hand back a token
      if the app's Client ID/Secret are correct, so that success IS
      the proof, no separate call is needed.

    If an oauth_connections row doesn't exist yet for that provider
    (shouldn't happen, this is called after saving it), it does
    nothing — silently, so as not to break the flow over a minor
    timing issue."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE oauth_connections SET validated_at = ? WHERE provider = ?",
            (validated_at, provider),
        )
        conn.commit()
    finally:
        conn.close()


def delete_oauth_connection(provider: str) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM oauth_connections WHERE provider = ?", (provider,))
        conn.commit()
    finally:
        conn.close()


def list_oauth_connections() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT provider, token_type, scope, connected_at FROM oauth_connections"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Workflow settings (enable/disable)
# ---------------------------------------------------------------------------
#
# **Important — honest limit of this:** this table saves a declared
# preference, it doesn't control anything live. `fika-sync` is the
# only workflow that actually runs in this GUI (it's literally what
# renders the dashboard). `meeting-debt`, `onboarding-automator` and
# `budget-guardian` are `workflow.csv` definitions meant to run in
# RailCall, which isn't part of this app — enabling them here does
# NOT make them execute. It exists to keep the preference saved for
# when a real RailCall integration exists, and so the UI is honest
# about which ones are "meant to be active" without pretending they
# already are.

def get_workflow_settings() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT workflow_id, enabled FROM workflow_settings ORDER BY workflow_id"
        ).fetchall()
        return [
            {
                "workflow_id": r["workflow_id"],
                "display_name": WORKFLOW_DISPLAY_NAMES.get(r["workflow_id"], r["workflow_id"]),
                "enabled": bool(r["enabled"]),
                "live_controlled": r["workflow_id"] == "fika-sync",
            }
            for r in rows
        ]
    finally:
        conn.close()


def set_workflow_enabled(workflow_id: str, enabled: bool) -> bool:
    """Returns:
        True if the workflow_id existed and was updated, False if
        it's not a known workflow_id.
    """
    if workflow_id not in KNOWN_WORKFLOW_IDS:
        return False

    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE workflow_settings SET enabled = ? WHERE workflow_id = ?",
            (1 if enabled else 0, workflow_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------

def get_notification_settings() -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT slack_channel, sync_frequency_minutes, auto_publish_on_sync, "
            "personal_dms_enabled, last_auto_sync_at "
            "FROM notification_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            return {
                "slack_channel": None, "sync_frequency_minutes": 0,
                "auto_publish_on_sync": False, "personal_dms_enabled": False,
                "last_auto_sync_at": None,
            }
        result = dict(row)
        result["auto_publish_on_sync"] = bool(result["auto_publish_on_sync"])
        result["personal_dms_enabled"] = bool(result["personal_dms_enabled"])
        return result
    finally:
        conn.close()


def save_notification_settings(slack_channel: Optional[str] = None,
                                sync_frequency_minutes: Optional[int] = None,
                                auto_publish_on_sync: Optional[bool] = None,
                                personal_dms_enabled: Optional[bool] = None) -> None:
    """Updates only the fields that are passed (not None). Passing ""
    for slack_channel does clear it, on purpose."""
    current = get_notification_settings()
    new_channel = slack_channel if slack_channel is not None else current["slack_channel"]
    new_frequency = sync_frequency_minutes if sync_frequency_minutes is not None else current["sync_frequency_minutes"]
    new_auto_publish = auto_publish_on_sync if auto_publish_on_sync is not None else current["auto_publish_on_sync"]
    new_personal_dms = personal_dms_enabled if personal_dms_enabled is not None else current["personal_dms_enabled"]

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notification_settings SET slack_channel = ?, sync_frequency_minutes = ?, "
            "auto_publish_on_sync = ?, personal_dms_enabled = ? WHERE id = 1",
            (new_channel, new_frequency, 1 if new_auto_publish else 0, 1 if new_personal_dms else 0),
        )
        conn.commit()
    finally:
        conn.close()


def mark_auto_sync_ran(timestamp_iso: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE notification_settings SET last_auto_sync_at = ? WHERE id = 1",
            (timestamp_iso,),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PER-PERSON calendar connections
# ---------------------------------------------------------------------------
# See the big note in the "OAuth connections" section above for why:
# each person's calendar needs THEIR OWN token, a single app-level one
# isn't enough to read another person's calendar.

def save_person_oauth_connection(person: str, provider: str,
                                  access_token: Optional[str] = None,
                                  refresh_token: Optional[str] = None,
                                  token_type: Optional[str] = None,
                                  scope: Optional[str] = None) -> None:
    """Same as save_oauth_connection, but tied to a specific person.
    If refresh_token is None on an update (Google doesn't always
    resend it), the existing one is kept — same care as in
    save_oauth_connection."""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO person_oauth_connections
               (person, provider, access_token, refresh_token, token_type, scope, connected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(person, provider) DO UPDATE SET
                 access_token = excluded.access_token,
                 refresh_token = COALESCE(excluded.refresh_token, person_oauth_connections.refresh_token),
                 token_type = excluded.token_type,
                 scope = excluded.scope,
                 connected_at = excluded.connected_at
            """,
            (
                person, provider, access_token, refresh_token, token_type, scope,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_person_oauth_connection(person: str, provider: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM person_oauth_connections WHERE person = ? AND provider = ?",
            (person, provider),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_person_oauth_connection(person: str, provider: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM person_oauth_connections WHERE person = ? AND provider = ?",
            (person, provider),
        )
        conn.commit()
    finally:
        conn.close()


def list_connected_people(provider: str) -> list[str]:
    """Names of the people who have already connected their calendar
    for that provider — used by the GUI to show per-row status
    without having to run N queries."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT person FROM person_oauth_connections WHERE provider = ?", (provider,)
        ).fetchall()
        return [r["person"] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# person_api_keys — same idea as person_oauth_connections, but for
# providers that connect with a simple API key instead of OAuth
# (today: Cal.com). No refresh_token because a Cal.com API key doesn't
# expire or renew itself — unlike a Google access_token, the special
# "don't overwrite if None" handling isn't needed.
# ---------------------------------------------------------------------------

def save_person_api_key(person: str, provider: str, api_key: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO person_api_keys (person, provider, api_key, connected_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(person, provider) DO UPDATE SET
                 api_key = excluded.api_key,
                 connected_at = excluded.connected_at
            """,
            (person, provider, api_key, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_person_api_key(person: str, provider: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM person_api_keys WHERE person = ? AND provider = ?",
            (person, provider),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_person_api_key(person: str, provider: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM person_api_keys WHERE person = ? AND provider = ?",
            (person, provider),
        )
        conn.commit()
    finally:
        conn.close()


def list_people_with_api_key(provider: str) -> list[str]:
    """Same as list_connected_people but for person_api_keys — used by
    the GUI to mark which rows in the Team table already have their
    own Cal.com key connected."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT person FROM person_api_keys WHERE provider = ?", (provider,)
        ).fetchall()
        return [r["person"] for r in rows]
    finally:
        conn.close()
