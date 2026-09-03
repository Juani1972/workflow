"""
Fika Sync / War Room -- real backend.

Serves the endpoints the GUI needs, with SQLite persistence (data is
NO LONGER lost on reload, unlike the original prototype in
war-room-prototype.html). The classification logic is the same one
already tested in the repo (see logic.py).

WHAT THIS BACKEND DOES DO:
  - Persists team, hours per day, thresholds and per-person Cal.com
    config in SQLite (app.db).
  - Calculates severity / focus thermometer with the already-validated
    logic.
  - When a focus-time-protection action is approved, it ATTEMPTS to
    actually execute it against Cal.com (protect_focus_time from
    modules/calcom-pro, already fixed against the real v2 API) -- not
    just record it. The result (executed/failed and why) is kept in
    the audit log with states PROPOSED -> APPROVED -> EXECUTING ->
    EXECUTED|FAILED.

WHAT THIS BACKEND DOES NOT DO (a real limitation, not hidden):
  - Doesn't call Google Calendar or Slack yet -- only Cal.com.
  - Real execution against Cal.com requires: (a) CALCOM_API_KEY as an
    environment variable for the process -- NEVER paste it in a chat
    or hardcode it; (b) that the person has calcom_username,
    attendee_email and a "focus block" event_type_id configured on
    their real Cal.com account (see PATCH
    /api/team/{id}/calcom-config). Without that, execution fails with
    an explicit reason instead of faking success.

Run:
    pip install -r requirements.txt
    export CALCOM_API_KEY=...   # optional; without this, approve-action
                                  # fails explicitly when trying to execute
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import logic
import calcom_client

DB_PATH = Path(__file__).parent / "app.db"
DAYS = ["mon", "tue", "wed", "thu", "fri"]

app = FastAPI(title="Fika Sync API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                mon REAL NOT NULL DEFAULT 0,
                tue REAL NOT NULL DEFAULT 0,
                wed REAL NOT NULL DEFAULT 0,
                thu REAL NOT NULL DEFAULT 0,
                fri REAL NOT NULL DEFAULT 0,
                calcom_username TEXT,
                attendee_email TEXT,
                attendee_timezone TEXT NOT NULL DEFAULT 'UTC',
                focus_event_type_id_short TEXT,
                focus_event_type_id_long TEXT,
                gcal_calendar_id TEXT,
                slack_user_id TEXT
            )
        """)
        # light migration for DBs created before these columns existed
        existing_cols = {r["name"] for r in db.execute("PRAGMA table_info(people)")}
        for col, ddl in [
            ("calcom_username", "TEXT"),
            ("attendee_email", "TEXT"),
            ("attendee_timezone", "TEXT NOT NULL DEFAULT 'UTC'"),
            ("focus_event_type_id_short", "TEXT"),
            ("focus_event_type_id_long", "TEXT"),
            ("gcal_calendar_id", "TEXT"),
            ("slack_user_id", "TEXT"),
        ]:
            if col not in existing_cols:
                db.execute(f"ALTER TABLE people ADD COLUMN {col} {ddl}")

        db.execute("""
            CREATE TABLE IF NOT EXISTS thresholds (
                role TEXT PRIMARY KEY,
                weekly_hours REAL NOT NULL,
                daily_hours REAL NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                person_id INTEGER,
                action TEXT NOT NULL,
                decision TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                result TEXT,
                note TEXT
            )
        """)
        # initial seed, same as the prototype's, only if empty
        if db.execute("SELECT COUNT(*) c FROM people").fetchone()["c"] == 0:
            db.executemany(
                "INSERT INTO people (name, role, mon, tue, wed, thu, fri) VALUES (?,?,?,?,?,?,?)",
                [
                    ("Alex", "ic", 2, 1, 4, 2, 0),
                    ("Sam", "manager", 5, 6, 6, 4, 2),
                    ("Noa", "ic", 1, 2, 1, 0, 1),
                ],
            )
        if db.execute("SELECT COUNT(*) c FROM thresholds").fetchone()["c"] == 0:
            # default values taken from fika-sync/config/thresholds.json
            db.executemany(
                "INSERT INTO thresholds (role, weekly_hours, daily_hours) VALUES (?,?,?)",
                [("ic", 15, 4), ("manager", 18, 5), ("lead", 20, 6)],
            )


init_db()


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str


class HoursUpdate(BaseModel):
    day: str  # mon|tue|wed|thu|fri
    hours: float = Field(ge=0, le=24)


class ThresholdUpdate(BaseModel):
    weekly_hours: float = Field(gt=0)
    daily_hours: float = Field(gt=0)


class CalcomConfig(BaseModel):
    calcom_username: Optional[str] = None
    attendee_email: Optional[str] = None
    attendee_timezone: str = "UTC"
    focus_event_type_id_short: Optional[str] = None  # Cal.com's 2h event
    focus_event_type_id_long: Optional[str] = None   # Cal.com's 4h event
    gcal_calendar_id: Optional[str] = None           # Google Calendar mirror
    slack_user_id: Optional[str] = None              # Slack DM notification


class ApproveAction(BaseModel):
    person_id: Optional[int] = None
    action: Literal["protect_focus_time", "rebalance", "reject"]
    decision: Literal["approved", "modified", "rejected"]
    note: Optional[str] = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _thresholds_map(db) -> dict:
    return {r["role"]: dict(r) for r in db.execute("SELECT * FROM thresholds")}


def _person_with_metrics(row: sqlite3.Row, thresholds: dict) -> dict:
    p = dict(row)
    weekly = round(sum(p[d] for d in DAYS), 2)
    th = thresholds.get(p["role"], {"weekly_hours": 0, "daily_hours": 0})
    severity = logic.classify_severity(weekly, th["weekly_hours"])
    focus_hours = logic.suggested_focus_hours(severity)
    event_type_id = p["focus_event_type_id_short"] if focus_hours == 2 else p["focus_event_type_id_long"]
    calcom_ready = bool(p["calcom_username"] and p["attendee_email"] and (event_type_id or focus_hours == 0))
    return {
        "id": p["id"],
        "name": p["name"],
        "role": p["role"],
        "hours": {d: p[d] for d in DAYS},
        "weekly_hours": weekly,
        "weekly_threshold": th["weekly_hours"],
        "daily_threshold": th["daily_hours"],
        "pct_of_threshold": logic.pct_of_threshold(weekly, th["weekly_hours"]),
        "severity": severity,
        "suggested_focus_hours": focus_hours,
        "daily_overrun": [
            d for d in DAYS if logic.check_daily_threshold(p[d], th["daily_hours"])
        ],
        "calcom_config": {
            "calcom_username": p["calcom_username"],
            "attendee_email": p["attendee_email"],
            "attendee_timezone": p["attendee_timezone"],
            "focus_event_type_id_short": p["focus_event_type_id_short"],
            "focus_event_type_id_long": p["focus_event_type_id_long"],
            "gcal_calendar_id": p["gcal_calendar_id"],
            "slack_user_id": p["slack_user_id"],
        },
        "calcom_ready": calcom_ready,
    }


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@app.get("/api/team")
def get_team():
    with get_db() as db:
        thresholds = _thresholds_map(db)
        people = db.execute("SELECT * FROM people ORDER BY id").fetchall()
        return [_person_with_metrics(p, thresholds) for p in people]


@app.post("/api/team")
def add_person(person: PersonIn):
    with get_db() as db:
        valid_roles = {r["role"] for r in db.execute("SELECT role FROM thresholds")}
        if person.role not in valid_roles:
            raise HTTPException(400, f"role must be one of {sorted(valid_roles)}")
        cur = db.execute(
            "INSERT INTO people (name, role, mon, tue, wed, thu, fri) VALUES (?,?,0,0,0,0,0)",
            (person.name, person.role),
        )
        thresholds = _thresholds_map(db)
        row = db.execute("SELECT * FROM people WHERE id=?", (cur.lastrowid,)).fetchone()
        return _person_with_metrics(row, thresholds)


@app.delete("/api/team/{person_id}")
def remove_person(person_id: int):
    with get_db() as db:
        cur = db.execute("DELETE FROM people WHERE id=?", (person_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "person not found")
        return {"deleted": True, "person_id": person_id}


@app.patch("/api/team/{person_id}/hours")
def update_hours(person_id: int, update: HoursUpdate):
    if update.day not in DAYS:
        raise HTTPException(400, f"day must be one of {DAYS}")
    with get_db() as db:
        cur = db.execute(
            f"UPDATE people SET {update.day} = ? WHERE id = ?",
            (update.hours, person_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "person not found")
        thresholds = _thresholds_map(db)
        row = db.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        return _person_with_metrics(row, thresholds)


@app.patch("/api/team/{person_id}/calcom-config")
def update_calcom_config(person_id: int, config: CalcomConfig):
    """Data Cal.com actually needs to execute protect_focus_time for
    real: the person's Cal.com username, the attendee's email/timezone,
    and the "focus block" event_type_id the user must create
    themselves on their Cal.com account (one for 2h, one for 4h --
    Cal.com defines the duration at the event-type level, this
    backend can't make it up)."""
    with get_db() as db:
        cur = db.execute(
            "UPDATE people SET calcom_username=?, attendee_email=?, attendee_timezone=?, "
            "focus_event_type_id_short=?, focus_event_type_id_long=?, "
            "gcal_calendar_id=?, slack_user_id=? WHERE id=?",
            (
                config.calcom_username, config.attendee_email, config.attendee_timezone,
                config.focus_event_type_id_short, config.focus_event_type_id_long,
                config.gcal_calendar_id, config.slack_user_id, person_id,
            ),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "person not found")
        thresholds = _thresholds_map(db)
        row = db.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        return _person_with_metrics(row, thresholds)


@app.get("/api/metrics")
def get_metrics():
    with get_db() as db:
        thresholds = _thresholds_map(db)
        people = [_person_with_metrics(p, thresholds) for p in db.execute("SELECT * FROM people")]
    total_hours = sum(p["weekly_hours"] for p in people)
    total_focus = sum(p["suggested_focus_hours"] for p in people)
    thermo_pct = min(100, round((total_focus / total_hours) * 100)) if total_hours > 0 else 0
    return {
        "thermo_pct": thermo_pct,
        "total_hours": round(total_hours, 2),
        "total_focus_hours": total_focus,
        "team_summary": logic.team_summary(people),
        "team_size": len(people),
    }


@app.get("/api/thresholds")
def get_thresholds():
    with get_db() as db:
        return _thresholds_map(db)


@app.put("/api/thresholds/{role}")
def update_threshold(role: str, update: ThresholdUpdate):
    with get_db() as db:
        cur = db.execute(
            "UPDATE thresholds SET weekly_hours=?, daily_hours=? WHERE role=?",
            (update.weekly_hours, update.daily_hours, role),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, f"role '{role}' does not exist")
        return _thresholds_map(db)[role]


@app.get("/api/audit-log")
def get_audit_log():
    with get_db() as db:
        rows = db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 50").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("result"):
                try:
                    d["result"] = json.loads(d["result"])
                except (TypeError, ValueError):
                    pass
            out.append(d)
        return out


def _add_hours_iso(iso_ts: str, hours: float) -> str:
    """Adds hours to an ISO 8601 timestamp. Cal.com returns slots in
    UTC with a 'Z' suffix, which datetime.fromisoformat() doesn't
    accept in some Python versions, so it's normalized to '+00:00'
    first."""
    normalized = iso_ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    return (dt + timedelta(hours=hours)).isoformat()


def _execute_protect_focus_time(person: dict) -> dict:
    """Attempts to actually execute protect_focus_time against
    Cal.com. Returns {"status": "executed"|"failed", "result"|"reason": ...}.
    Never raises -- any failure is caught and reported, not
    propagated as a 500 to the client, and success is never faked."""
    cfg = person["calcom_config"]
    focus_hours = person["suggested_focus_hours"]
    event_type_id = (
        cfg["focus_event_type_id_short"] if focus_hours == 2 else cfg["focus_event_type_id_long"]
    )

    missing = [
        field for field, val in [
            ("calcom_username", cfg["calcom_username"]),
            ("attendee_email", cfg["attendee_email"]),
            (f"focus_event_type_id_{'short' if focus_hours == 2 else 'long'}", event_type_id),
        ] if not val
    ]
    if missing:
        return {
            "status": "failed",
            "reason": f"Missing Cal.com configuration fields for {person['name']}: "
                      f"{', '.join(missing)}. Configure them with PATCH /api/team/{person['id']}/calcom-config.",
        }

    if not os.environ.get("CALCOM_API_KEY"):
        return {
            "status": "failed",
            "reason": "CALCOM_API_KEY is not configured as an environment variable "
                      "for the backend process. Never paste it in chat or hardcode it: "
                      "export it before starting uvicorn (see README).",
        }

    steps = {}

    # --- Step 1: block focus time in Cal.com (required) -------------------
    try:
        handler = calcom_client.load_module_handler("calcom-pro")
        today = time.strftime("%Y-%m-%d", time.gmtime())
        in_a_week = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 86400))
        result = handler.protect_focus_time(
            {
                "username": cfg["calcom_username"],
                "event_type_id": event_type_id,
                "attendee_name": person["name"],
                "attendee_email": cfg["attendee_email"],
                "attendee_timezone": cfg["attendee_timezone"] or "UTC",
                "from_date": today,
                "to_date": in_a_week,
                "priority": "morning",
            },
            {},
        )
        steps["calcom"] = {"status": "executed", "result": result}
    except Exception as e:  # noqa: BLE001 -- external boundary: reported, not propagated
        return {
            "status": "failed",
            "reason": f"Cal.com failed: {type(e).__name__}: {e}",
            "steps": {"calcom": {"status": "failed", "reason": f"{type(e).__name__}: {e}"}},
        }

    blocked_slot = (steps["calcom"]["result"] or {}).get("blocked_slot")

    # --- Step 2: Google Calendar mirror (optional) -------------------------
    # workflow.csv's mirror_gcal_block node. It's OPTIONAL on purpose:
    # if it fails, the Cal.com block is still valid -- nothing gets
    # rolled back or marked entirely as failed. The partial state stays
    # visible.
    if not os.environ.get("GOOGLE_CALENDAR_ACCESS_TOKEN"):
        steps["gcal"] = {"status": "skipped", "reason": "GOOGLE_CALENDAR_ACCESS_TOKEN not configured."}
    elif not cfg.get("gcal_calendar_id"):
        steps["gcal"] = {"status": "skipped", "reason": "gcal_calendar_id not configured for this person."}
    elif not blocked_slot:
        steps["gcal"] = {"status": "skipped", "reason": "Cal.com didn't return blocked_slot; nothing to mirror."}
    else:
        try:
            gcal = calcom_client.load_module_handler("gcal")
            end_iso = _add_hours_iso(blocked_slot, focus_hours or 2)
            steps["gcal"] = {
                "status": "executed",
                "result": gcal.create_event(
                    {
                        "calendar_id": cfg["gcal_calendar_id"],
                        "title": "Focus Time (auto)",
                        "description": f"Blocked by Fika Sync -- {person['pct_of_threshold']}% of the weekly threshold.",
                        "start": blocked_slot,
                        "end": end_iso,
                        "timezone": cfg["attendee_timezone"] or "UTC",
                    },
                    {},
                ),
            }
        except Exception as e:  # noqa: BLE001
            steps["gcal"] = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}

    # --- Step 3: Slack notification (optional) ------------------------------
    if not os.environ.get("SLACK_BOT_TOKEN"):
        steps["slack"] = {"status": "skipped", "reason": "SLACK_BOT_TOKEN not configured."}
    elif not cfg.get("slack_user_id"):
        steps["slack"] = {"status": "skipped", "reason": "slack_user_id not configured for this person."}
    else:
        try:
            slack = calcom_client.load_module_handler("slack")
            steps["slack"] = {
                "status": "executed",
                "result": slack.post_dm(
                    {
                        "user_id": cfg["slack_user_id"],
                        "text": (
                            f"I protected {focus_hours}h of focus time for you on {blocked_slot}. "
                            f"You're at {person['pct_of_threshold']}% of your weekly threshold "
                            f"({person['weekly_hours']}h of {person['weekly_threshold']}h)."
                        ),
                    },
                    {},
                ),
            }
        except Exception as e:  # noqa: BLE001
            steps["slack"] = {"status": "failed", "reason": f"{type(e).__name__}: {e}"}

    failed_optional = [k for k, v in steps.items() if v["status"] == "failed"]
    status = "executed_with_warnings" if failed_optional else "executed"
    return {"status": status, "result": {"blocked_slot": blocked_slot, "steps": steps}}


@app.post("/api/approve-action")
def approve_action(action: ApproveAction):
    """PROPOSED -> APPROVED -> EXECUTING -> EXECUTED|FAILED. If the
    decision is 'approved' and the action is 'protect_focus_time', it
    ATTEMPTS to actually execute it against Cal.com (see
    _execute_protect_focus_time). If configuration or CALCOM_API_KEY
    is missing, or if Cal.com returns an error, it's recorded as
    FAILED with the reason -- success is never faked."""
    with get_db() as db:
        person = None
        if action.person_id is not None:
            thresholds = _thresholds_map(db)
            row = db.execute("SELECT * FROM people WHERE id=?", (action.person_id,)).fetchone()
            if row:
                person = _person_with_metrics(row, thresholds)

        if action.decision != "approved":
            status = "rejected" if action.decision == "rejected" else "modified"
            note = action.note or f"Decision recorded: {action.decision}. Nothing is executed."
            db.execute(
                "INSERT INTO audit_log (ts, person_id, action, decision, status, result, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), action.person_id, action.action, action.decision, status, None, note),
            )
            return {"recorded": True, "status": status, "executed": False, "note": note}

        if action.action != "protect_focus_time":
            note = f"Action '{action.action}' recorded as approved, but only " \
                   f"protect_focus_time has real execution implemented for now."
            db.execute(
                "INSERT INTO audit_log (ts, person_id, action, decision, status, result, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), action.person_id, action.action, action.decision, "approved", None, note),
            )
            return {"recorded": True, "status": "approved", "executed": False, "note": note}

        if person is None:
            note = "person_id not found -- can't execute protect_focus_time without knowing who."
            db.execute(
                "INSERT INTO audit_log (ts, person_id, action, decision, status, result, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (time.time(), action.person_id, action.action, action.decision, "failed", None, note),
            )
            return {"recorded": True, "status": "failed", "executed": False, "note": note}

        outcome = _execute_protect_focus_time(person)
        status = outcome["status"]
        result_json = json.dumps(outcome.get("result")) if outcome.get("result") is not None else None
        note = outcome.get("reason") or "Executed successfully against Cal.com."
        db.execute(
            "INSERT INTO audit_log (ts, person_id, action, decision, status, result, note) "
            "VALUES (?,?,?,?,?,?,?)",
            (time.time(), action.person_id, action.action, action.decision, status, result_json, note),
        )
        return {
            "recorded": True,
            "status": status,
            "executed": status == "executed",
            "note": note,
            "result": outcome.get("result"),
        }


@app.get("/api/health")
def health():
    return {"status": "ok"}
