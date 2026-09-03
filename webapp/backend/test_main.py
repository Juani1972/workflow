"""
Real backend tests. Run against a temporary SQLite DB (never against
app.db), following the same spirit as
fika-sync/test/test_fika_logic.py: business logic and API contract,
without calling external services.

Run:
    pytest test_main.py -v
"""
import importlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Cuts off any real HTTP egress across the whole suite.

    Concrete reason (real bug found 29 Aug 2026): a test mocked
    `load_calcom_handler` while the code already called
    `load_module_handler`. The mock didn't apply, the real handler
    loaded, and the tests made REAL requests to api.cal.com (it
    responded with 403). A green/red test for network reasons is
    worse than useless. With this, any real call blows up with an
    explicit message instead of depending on credentials or on the
    external service being up.
    """
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError(
            f"A REAL HTTP request was attempted in a test: {args[:1]}. "
            "Mock the corresponding handler (the mock's name probably "
            "went stale relative to the code)."
        )

    for verb in ("get", "post", "put", "patch", "delete", "request"):
        monkeypatch.setattr(requests, verb, _blocked)


@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / "test_app.db"
    import main as main_module
    importlib.reload(main_module)
    main_module.DB_PATH = db_file
    main_module.init_db()
    with TestClient(main_module.app) as c:
        yield c


def test_get_team_seed_data(client):
    resp = client.get("/api/team")
    assert resp.status_code == 200
    people = resp.json()
    assert len(people) == 3
    names = {p["name"] for p in people}
    assert names == {"Alex", "Sam", "Noa"}


def test_severity_matches_known_logic(client):
    # Sam is a manager (18h threshold), hours: 5+6+6+4+2=23 -> 127.7% -> red
    resp = client.get("/api/team")
    sam = next(p for p in resp.json() if p["name"] == "Sam")
    assert sam["weekly_hours"] == 23
    assert sam["severity"] == "red"


def test_add_person(client):
    resp = client.post("/api/team", json={"name": "New", "role": "ic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New"
    assert body["weekly_hours"] == 0
    assert body["severity"] == "green"


def test_add_person_invalid_role_rejected(client):
    resp = client.post("/api/team", json={"name": "X", "role": "ceo"})
    assert resp.status_code == 400


def test_update_hours_recalculates_severity(client):
    people = client.get("/api/team").json()
    noa = next(p for p in people if p["name"] == "Noa")
    resp = client.patch(f"/api/team/{noa['id']}/hours", json={"day": "mon", "hours": 12})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["hours"]["mon"] == 12
    assert updated["weekly_hours"] == 12 + 2 + 1 + 0 + 1  # rest of the days unchanged


def test_update_hours_invalid_day_rejected(client):
    people = client.get("/api/team").json()
    pid = people[0]["id"]
    resp = client.patch(f"/api/team/{pid}/hours", json={"day": "sat", "hours": 1})
    assert resp.status_code == 400


def test_remove_person(client):
    people = client.get("/api/team").json()
    pid = people[0]["id"]
    resp = client.delete(f"/api/team/{pid}")
    assert resp.status_code == 200
    remaining = client.get("/api/team").json()
    assert all(p["id"] != pid for p in remaining)


def test_remove_nonexistent_person_404(client):
    resp = client.delete("/api/team/99999")
    assert resp.status_code == 404


def test_metrics_thermometer(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "thermo_pct" in body
    assert body["team_size"] == 3


def test_thresholds_update(client):
    resp = client.put("/api/thresholds/ic", json={"weekly_hours": 20, "daily_hours": 5})
    assert resp.status_code == 200
    assert resp.json()["weekly_hours"] == 20
    # confirms it affects the classification of people with that role
    people = client.get("/api/team").json()
    alex = next(p for p in people if p["name"] == "Alex")
    assert alex["weekly_threshold"] == 20


def test_thresholds_unknown_role_404(client):
    resp = client.put("/api/thresholds/ceo", json={"weekly_hours": 10, "daily_hours": 2})
    assert resp.status_code == 404


def test_approve_action_rejected_does_not_attempt_execution(client):
    resp = client.post("/api/approve-action", json={
        "person_id": 1, "action": "protect_focus_time", "decision": "rejected",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["executed"] is False
    log = client.get("/api/audit-log").json()
    assert log[0]["status"] == "rejected"


def test_approve_action_fails_when_calcom_config_missing(client, monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "would-not-matter")
    resp = client.post("/api/approve-action", json={
        "person_id": 1, "action": "protect_focus_time", "decision": "approved",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["executed"] is False
    assert "calcom_username" in body["note"] or "attendee_email" in body["note"] or "focus_event_type_id" in body["note"]


def test_approve_action_fails_when_api_key_missing(client, monkeypatch):
    monkeypatch.delenv("CALCOM_API_KEY", raising=False)
    client.patch("/api/team/1/calcom-config", json={
        "calcom_username": "alex-ruiz", "attendee_email": "alex@example.com",
        "attendee_timezone": "Europe/Madrid",
        "focus_event_type_id_short": "42", "focus_event_type_id_long": "43",
    })
    resp = client.post("/api/approve-action", json={
        "person_id": 1, "action": "protect_focus_time", "decision": "approved",
    })
    body = resp.json()
    assert body["status"] == "failed"
    assert "CALCOM_API_KEY" in body["note"]


def test_approve_action_executes_for_real_when_configured(client, monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "test_key")
    client.patch("/api/team/1/calcom-config", json={
        "calcom_username": "alex-ruiz", "attendee_email": "alex@example.com",
        "attendee_timezone": "Europe/Madrid",
        "focus_event_type_id_short": "42", "focus_event_type_id_long": "43",
    })
    fake_handler = SimpleNamespace(
        protect_focus_time=lambda inputs, ctx: {
            "blocked_slot": "2026-03-02T08:00:00Z", "priority_used": "morning",
            "booking": {"id": "bk_test"},
        }
    )
    with patch("main.calcom_client.load_module_handler", return_value=fake_handler):
        resp = client.post("/api/approve-action", json={
            "person_id": 1, "action": "protect_focus_time", "decision": "approved",
        })
    body = resp.json()
    assert body["status"] == "executed"
    assert body["executed"] is True
    assert body["result"]["blocked_slot"] == "2026-03-02T08:00:00Z"

    log = client.get("/api/audit-log").json()
    assert log[0]["status"] == "executed"
    cal_step = log[0]["result"]["steps"]["calcom"]
    assert cal_step["status"] == "executed"
    assert cal_step["result"]["booking"]["id"] == "bk_test"
    # without gcal/slack tokens in the environment, those steps are
    # explicitly skipped instead of failing or pretending to be done
    assert log[0]["result"]["steps"]["gcal"]["status"] == "skipped"
    assert log[0]["result"]["steps"]["slack"]["status"] == "skipped"


def test_execution_chain_mirrors_to_gcal_and_notifies_slack(client, monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "test_key")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "gcal_token")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    client.patch("/api/team/1/calcom-config", json={
        "calcom_username": "alex-ruiz", "attendee_email": "alex@example.com",
        "attendee_timezone": "Europe/Madrid",
        "focus_event_type_id_short": "42", "focus_event_type_id_long": "43",
        "gcal_calendar_id": "alex@example.com", "slack_user_id": "U0999",
    })
    calls = {}

    def _fake_loader(module_dir):
        if module_dir == "calcom-pro":
            return SimpleNamespace(protect_focus_time=lambda i, c: {
                "blocked_slot": "2026-03-02T08:00:00Z", "booking": {"id": "bk_1"}})
        if module_dir == "gcal":
            def _create(i, c):
                calls["gcal"] = i
                return {"id": "gcal_evt_1"}
            return SimpleNamespace(create_event=_create)
        if module_dir == "slack":
            def _dm(i, c):
                calls["slack"] = i
                return {"ok": True}
            return SimpleNamespace(post_dm=_dm)
        raise AssertionError(f"unexpected module: {module_dir}")

    with patch("main.calcom_client.load_module_handler", side_effect=_fake_loader):
        resp = client.post("/api/approve-action", json={
            "person_id": 1, "action": "protect_focus_time", "decision": "approved",
        })
    body = resp.json()
    assert body["status"] == "executed"
    steps = body["result"]["steps"]
    assert steps["gcal"]["status"] == "executed"
    assert steps["slack"]["status"] == "executed"
    assert calls["gcal"]["start"] == "2026-03-02T08:00:00Z"
    assert calls["gcal"]["title"] == "Focus Time (auto)"
    assert calls["slack"]["user_id"] == "U0999"


def test_optional_step_failure_does_not_invalidate_calcom_block(client, monkeypatch):
    """If Google Calendar fails, the Cal.com block ALREADY happened and
    is still valid -- it's reported as executed_with_warnings, not as
    failed."""
    monkeypatch.setenv("CALCOM_API_KEY", "test_key")
    monkeypatch.setenv("GOOGLE_CALENDAR_ACCESS_TOKEN", "gcal_token")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    client.patch("/api/team/1/calcom-config", json={
        "calcom_username": "alex-ruiz", "attendee_email": "alex@example.com",
        "attendee_timezone": "Europe/Madrid",
        "focus_event_type_id_short": "42", "focus_event_type_id_long": "43",
        "gcal_calendar_id": "alex@example.com",
    })

    def _fake_loader(module_dir):
        if module_dir == "calcom-pro":
            return SimpleNamespace(protect_focus_time=lambda i, c: {
                "blocked_slot": "2026-03-02T08:00:00Z", "booking": {"id": "bk_1"}})
        if module_dir == "gcal":
            def _boom(i, c):
                raise RuntimeError("calendar not found")
            return SimpleNamespace(create_event=_boom)
        raise AssertionError(f"unexpected module: {module_dir}")

    with patch("main.calcom_client.load_module_handler", side_effect=_fake_loader):
        resp = client.post("/api/approve-action", json={
            "person_id": 1, "action": "protect_focus_time", "decision": "approved",
        })
    body = resp.json()
    assert body["status"] == "executed_with_warnings"
    assert body["result"]["steps"]["calcom"]["status"] == "executed"
    assert body["result"]["steps"]["gcal"]["status"] == "failed"
    assert "calendar not found" in body["result"]["steps"]["gcal"]["reason"]


def test_approve_action_reports_failure_when_calcom_raises(client, monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "test_key")
    client.patch("/api/team/1/calcom-config", json={
        "calcom_username": "alex-ruiz", "attendee_email": "alex@example.com",
        "attendee_timezone": "Europe/Madrid",
        "focus_event_type_id_short": "42", "focus_event_type_id_long": "43",
    })

    def _raise(inputs, ctx):
        raise RuntimeError("No free slots available")

    fake_handler = SimpleNamespace(protect_focus_time=_raise)
    with patch("main.calcom_client.load_module_handler", return_value=fake_handler):
        resp = client.post("/api/approve-action", json={
            "person_id": 1, "action": "protect_focus_time", "decision": "approved",
        })
    body = resp.json()
    assert body["status"] == "failed"
    assert "No free slots" in body["note"]


def test_approve_action_unsupported_action_marks_approved_not_executed(client, monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "test_key")
    resp = client.post("/api/approve-action", json={
        "person_id": 1, "action": "rebalance", "decision": "approved",
    })
    body = resp.json()
    assert body["status"] == "approved"
    assert body["executed"] is False


def test_approve_action_unknown_person_fails(client, monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "test_key")
    resp = client.post("/api/approve-action", json={
        "person_id": 99999, "action": "protect_focus_time", "decision": "approved",
    })
    body = resp.json()
    assert body["status"] == "failed"


def test_calcom_config_updates_and_reflects_in_team(client):
    resp = client.patch("/api/team/2/calcom-config", json={
        "calcom_username": "sam-torres", "attendee_email": "sam@example.com",
        "attendee_timezone": "Europe/Madrid",
        "focus_event_type_id_short": "10", "focus_event_type_id_long": "11",
    })
    assert resp.status_code == 200
    sam = resp.json()
    assert sam["calcom_config"]["calcom_username"] == "sam-torres"
    # Sam is in red (23h/18h) -> needs focus_event_type_id_long
    assert sam["suggested_focus_hours"] == 4
    assert sam["calcom_ready"] is True


def test_calcom_config_unknown_person_404(client):
    resp = client.patch("/api/team/99999/calcom-config", json={"attendee_timezone": "UTC"})
    assert resp.status_code == 404


def test_approve_action_rejects_invalid_action(client):
    resp = client.post("/api/approve-action", json={
        "person_id": 1, "action": "delete_everything", "decision": "approved",
    })
    assert resp.status_code == 422


def test_approve_action_rejects_invalid_decision(client):
    resp = client.post("/api/approve-action", json={
        "person_id": 1, "action": "protect_focus_time", "decision": "maybe",
    })
    assert resp.status_code == 422
