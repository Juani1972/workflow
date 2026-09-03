import os

import pytest

import models


def test_init_db_seeds_team_from_config():
    models.init_db()
    team = models.get_team()

    assert len(team) == 4
    names = {m["person"] for m in team}
    assert names == {"ana", "beto", "caro", "dani"}


def test_init_db_applies_per_person_threshold_overrides():
    models.init_db()
    team = {m["person"]: m for m in models.get_team()}

    # caro tiene overrides en config/thresholds.example.json (12/18)
    assert team["caro"]["yellow_hours"] == 12.0
    assert team["caro"]["red_hours"] == 18.0
    # ana usa el default (15/20)
    assert team["ana"]["yellow_hours"] == 15.0
    assert team["ana"]["red_hours"] == 20.0


def test_init_db_is_idempotent_does_not_duplicate_on_second_call():
    models.init_db()
    models.init_db()
    assert len(models.get_team()) == 4


def test_set_threshold_updates_existing_person():
    models.init_db()
    updated = models.set_threshold("ana", "red_hours", 22.0)

    assert updated is True
    assert models.get_thresholds("ana")["red_hours"] == 22.0


def test_set_threshold_returns_false_for_unknown_person():
    models.init_db()
    assert models.set_threshold("nadie", "red_hours", 22.0) is False


def test_set_threshold_rejects_unknown_field():
    models.init_db()
    try:
        models.set_threshold("ana", "purple_hours", 1)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_record_and_get_hours_for_week():
    models.init_db()
    models.record_meeting_hours("ana", "2026-08-31", 18.5, "demo")
    models.record_meeting_hours("beto", "2026-08-31", 5.0, "demo")

    hours = models.get_hours_for_week("2026-08-31")
    assert hours == {"ana": 18.5, "beto": 5.0}


def test_record_meeting_hours_upserts_same_week():
    models.init_db()
    models.record_meeting_hours("ana", "2026-08-31", 18.5, "demo")
    models.record_meeting_hours("ana", "2026-08-31", 20.0, "calcom+gcal")

    hours = models.get_hours_for_week("2026-08-31")
    assert hours == {"ana": 20.0}


def test_get_history_returns_ascending_order():
    models.init_db()
    models.record_meeting_hours("ana", "2026-08-17", 10.0, "demo")
    models.record_meeting_hours("ana", "2026-08-24", 15.0, "demo")
    models.record_meeting_hours("ana", "2026-08-31", 20.0, "demo")

    history = models.get_history("ana", limit_weeks=8)

    assert [h["week_start"] for h in history] == ["2026-08-17", "2026-08-24", "2026-08-31"]


def test_get_history_respects_limit():
    models.init_db()
    for i in range(10):
        models.record_meeting_hours("ana", f"2026-01-{i+1:02d}", float(i), "demo")

    history = models.get_history("ana", limit_weeks=3)
    assert len(history) == 3


def test_log_sync_and_get_recent_syncs():
    models.init_db()
    models.log_sync("2026-08-30T10:00:00Z", "demo", "ok", "4 personas")
    models.log_sync("2026-08-30T11:00:00Z", "calcom+gcal", "error", "X failed")

    recent = models.get_recent_syncs(limit=10)
    assert len(recent) == 2
    # most recent first
    assert recent[0]["source"] == "calcom+gcal"
    assert recent[0]["status"] == "error"


def test_reset_db_clears_everything_and_can_reinit():
    models.init_db()
    models.record_meeting_hours("ana", "2026-08-31", 18.5, "demo")

    models.reset_db()
    models.init_db()

    assert models.get_hours_for_week("2026-08-31") == {}
    assert len(models.get_team()) == 4


# ---------------------------------------------------------------------------
# oauth_states — CSRF protection for the "Connect with one click" flow
# ---------------------------------------------------------------------------

def test_create_and_consume_oauth_state_roundtrip():
    models.init_db()
    state = models.create_oauth_state("google")

    result = models.consume_oauth_state(state)

    assert result == {"provider": "google", "person": None}


def test_consume_oauth_state_is_single_use():
    models.init_db()
    state = models.create_oauth_state("slack")

    first = models.consume_oauth_state(state)
    second = models.consume_oauth_state(state)  # retry with the same state

    assert first == {"provider": "slack", "person": None}
    assert second is None


def test_consume_oauth_state_unknown_returns_none():
    models.init_db()
    assert models.consume_oauth_state("made-up-state-that-never-existed") is None


def test_create_oauth_state_with_person_roundtrip():
    models.init_db()
    state = models.create_oauth_state("google", person="ana")

    result = models.consume_oauth_state(state)

    assert result == {"provider": "google", "person": "ana"}


def test_oauth_state_without_person_is_none_not_empty_string():
    """Distinguish an 'app-level connection' (person=None) from a
    personal one — that's exactly what separates Sheets/Slack from an
    individual calendar."""
    models.init_db()
    state = models.create_oauth_state("slack")

    result = models.consume_oauth_state(state)

    assert result["person"] is None


# ---------------------------------------------------------------------------
# oauth_connections
# ---------------------------------------------------------------------------

def test_save_and_get_oauth_connection():
    models.init_db()
    models.save_oauth_connection(
        "google", access_token="ya29.abc", refresh_token="1//xyz",
        token_type="Bearer", scope="calendar spreadsheets",
    )

    connection = models.get_oauth_connection("google")

    assert connection["access_token"] == "ya29.abc"
    assert connection["refresh_token"] == "1//xyz"


def test_get_oauth_connection_returns_none_when_not_connected():
    models.init_db()
    assert models.get_oauth_connection("google") is None


def test_save_oauth_connection_preserves_refresh_token_when_not_resent():
    """Google doesn't always resend the refresh_token on updates —
    the one already saved must not be lost."""
    models.init_db()
    models.save_oauth_connection("google", access_token="ya29.first", refresh_token="1//original")
    models.save_oauth_connection("google", access_token="ya29.second", refresh_token=None)

    connection = models.get_oauth_connection("google")

    assert connection["access_token"] == "ya29.second"
    assert connection["refresh_token"] == "1//original"  # wasn't lost


def test_save_oauth_connection_stores_extra_as_json():
    models.init_db()
    models.save_oauth_connection(
        "slack", access_token="xoxb-fake", token_type="bot",
        extra={"team_id": "T123", "team_name": "Equipo de prueba"},
    )

    connection = models.get_oauth_connection("slack")

    assert connection["extra"] == {"team_id": "T123", "team_name": "Equipo de prueba"}


def test_delete_oauth_connection():
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake")

    models.delete_oauth_connection("slack")

    assert models.get_oauth_connection("slack") is None


def test_delete_oauth_connection_when_nothing_connected_does_not_raise():
    models.init_db()
    models.delete_oauth_connection("google")  # should not blow up


def test_list_oauth_connections():
    models.init_db()
    models.save_oauth_connection("google", access_token="ya29.abc", refresh_token="1//xyz")
    models.save_oauth_connection("slack", access_token="xoxb-fake")

    connections = models.list_oauth_connections()

    assert {c["provider"] for c in connections} == {"google", "slack"}


# ---------------------------------------------------------------------------
# Team management: add / edit / remove
# ---------------------------------------------------------------------------

def test_add_team_member_creates_new_person():
    models.init_db()
    added = models.add_team_member(
        "flor", calcom_username="flor.dev", gcal_email="flor@example.com",
        slack_user_id="U0000099", yellow_hours=14.0, red_hours=19.0,
    )

    assert added is True
    team = {m["person"]: m for m in models.get_team()}
    assert team["flor"]["gcal_email"] == "flor@example.com"
    assert team["flor"]["yellow_hours"] == 14.0
    assert team["flor"]["red_hours"] == 19.0


def test_add_team_member_rejects_duplicate_without_overwriting():
    models.init_db()
    models.add_team_member("flor", gcal_email="flor@example.com")

    added_again = models.add_team_member("flor", gcal_email="otra-flor@example.com")

    assert added_again is False
    team = {m["person"]: m for m in models.get_team()}
    assert team["flor"]["gcal_email"] == "flor@example.com"  # wasn't overwritten


def test_add_team_member_rejects_empty_name():
    models.init_db()
    with pytest.raises(ValueError):
        models.add_team_member("   ")


def test_add_team_member_rejects_red_hours_not_greater_than_yellow():
    models.init_db()
    with pytest.raises(ValueError):
        models.add_team_member("flor", yellow_hours=20.0, red_hours=15.0)
    with pytest.raises(ValueError):
        models.add_team_member("flor", yellow_hours=15.0, red_hours=15.0)


def test_update_team_member_only_changes_passed_fields():
    models.init_db()
    models.add_team_member("flor", calcom_username="flor.old", gcal_email="flor@example.com")

    updated = models.update_team_member("flor", slack_user_id="U0000099")

    assert updated is True
    team = {m["person"]: m for m in models.get_team()}
    assert team["flor"]["calcom_username"] == "flor.old"  # untouched
    assert team["flor"]["slack_user_id"] == "U0000099"    # was updated


def test_update_team_member_returns_false_for_unknown_person():
    models.init_db()
    assert models.update_team_member("nadie", gcal_email="x@example.com") is False


def test_update_team_member_with_no_fields_reports_existence():
    models.init_db()
    assert models.update_team_member("ana") is True
    assert models.update_team_member("nadie-de-verdad") is False


def test_delete_team_member_removes_person_and_history():
    models.init_db()
    models.record_meeting_hours("ana", "2026-08-31", 18.5, "demo")

    removed = models.delete_team_member("ana")

    assert removed is True
    assert "ana" not in {m["person"] for m in models.get_team()}
    assert models.get_hours_for_week("2026-08-31").get("ana") is None


def test_delete_team_member_returns_false_for_unknown_person():
    models.init_db()
    assert models.delete_team_member("nadie") is False


# ---------------------------------------------------------------------------
# Workflow settings
# ---------------------------------------------------------------------------

def test_get_workflow_settings_seeds_four_known_workflows():
    models.init_db()
    settings = {s["workflow_id"]: s for s in models.get_workflow_settings()}

    assert set(settings.keys()) == {"fika-sync", "meeting-debt", "onboarding-automator", "budget-guardian"}
    assert settings["fika-sync"]["enabled"] is True
    assert settings["fika-sync"]["live_controlled"] is True
    assert settings["meeting-debt"]["enabled"] is False
    assert settings["meeting-debt"]["live_controlled"] is False


def test_set_workflow_enabled_updates_state():
    models.init_db()
    ok = models.set_workflow_enabled("budget-guardian", True)

    assert ok is True
    settings = {s["workflow_id"]: s for s in models.get_workflow_settings()}
    assert settings["budget-guardian"]["enabled"] is True


def test_set_workflow_enabled_rejects_unknown_workflow():
    models.init_db()
    assert models.set_workflow_enabled("workflow-fantasma", True) is False


# ---------------------------------------------------------------------------
# app_oauth_credentials — configurable application Client ID/Secret
# from the GUI, instead of only via environment variable.
# ---------------------------------------------------------------------------

def test_get_app_oauth_credentials_returns_none_when_not_configured():
    models.init_db()
    assert models.get_app_oauth_credentials("google") is None


def test_save_and_get_app_oauth_credentials():
    models.init_db()
    models.save_app_oauth_credentials("google", "client-123", "secret-abc")

    creds = models.get_app_oauth_credentials("google")

    assert creds["client_id"] == "client-123"
    assert creds["client_secret"] == "secret-abc"


def test_save_app_oauth_credentials_overwrites_on_reconfigure():
    models.init_db()
    models.save_app_oauth_credentials("google", "old-id", "old-secret")
    models.save_app_oauth_credentials("google", "new-id", "new-secret")

    creds = models.get_app_oauth_credentials("google")
    assert creds["client_id"] == "new-id"
    assert creds["client_secret"] == "new-secret"


def test_google_and_slack_app_credentials_are_independent():
    models.init_db()
    models.save_app_oauth_credentials("google", "google-id", "google-secret")
    models.save_app_oauth_credentials("slack", "slack-id", "slack-secret")

    assert models.get_app_oauth_credentials("google")["client_id"] == "google-id"
    assert models.get_app_oauth_credentials("slack")["client_id"] == "slack-id"


def test_delete_app_oauth_credentials():
    models.init_db()
    models.save_app_oauth_credentials("google", "client-123", "secret-abc")

    models.delete_app_oauth_credentials("google")

    assert models.get_app_oauth_credentials("google") is None


def test_delete_app_oauth_credentials_when_not_configured_does_not_raise():
    models.init_db()
    models.delete_app_oauth_credentials("google")  # should not blow up


def test_delete_app_oauth_credentials_does_not_affect_other_provider():
    models.init_db()
    models.save_app_oauth_credentials("google", "google-id", "google-secret")
    models.save_app_oauth_credentials("slack", "slack-id", "slack-secret")

    models.delete_app_oauth_credentials("google")

    assert models.get_app_oauth_credentials("google") is None
    assert models.get_app_oauth_credentials("slack") is not None


def test_get_app_oauth_credentials_tolerates_uninitialized_db(tmp_path, monkeypatch):
    """If called before init_db() has run (shouldn't happen in the
    real app, but it's a safeguard), it should not raise
    sqlite3.OperationalError — it's treated as 'not configured'."""
    fresh_db_path = tmp_path / "never_initialized.db"
    monkeypatch.setenv("FIKA_SYNC_DB_PATH", str(fresh_db_path))
    assert models.get_app_oauth_credentials("google") is None


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------

def test_get_notification_settings_defaults():
    models.init_db()
    settings = models.get_notification_settings()

    assert settings == {
        "slack_channel": None, "sync_frequency_minutes": 0,
        "auto_publish_on_sync": False, "personal_dms_enabled": False,
        "last_auto_sync_at": None,
    }


def test_save_notification_settings_partial_update_preserves_other_fields():
    models.init_db()
    models.save_notification_settings(slack_channel="#fika-sync", sync_frequency_minutes=60)

    models.save_notification_settings(auto_publish_on_sync=True)  # no toca slack_channel/frequency

    settings = models.get_notification_settings()
    assert settings["slack_channel"] == "#fika-sync"
    assert settings["sync_frequency_minutes"] == 60
    assert settings["auto_publish_on_sync"] is True


def test_save_notification_settings_personal_dms_enabled():
    models.init_db()
    assert models.get_notification_settings()["personal_dms_enabled"] is False

    models.save_notification_settings(personal_dms_enabled=True)

    assert models.get_notification_settings()["personal_dms_enabled"] is True


def test_save_notification_settings_personal_dms_does_not_affect_other_fields():
    models.init_db()
    models.save_notification_settings(slack_channel="#fika-sync", auto_publish_on_sync=True)

    models.save_notification_settings(personal_dms_enabled=True)

    settings = models.get_notification_settings()
    assert settings["slack_channel"] == "#fika-sync"
    assert settings["auto_publish_on_sync"] is True
    assert settings["personal_dms_enabled"] is True


def test_init_db_migration_for_personal_dms_column_is_idempotent():
    """The personal_dms_enabled ALTER TABLE migration should not
    break if init_db() is called more than once (happens in every test
    via the temp_db fixture, and in the real app every time it starts)."""
    models.init_db()
    models.init_db()
    models.init_db()
    assert models.get_notification_settings()["personal_dms_enabled"] is False


def test_init_db_migrates_old_oauth_states_table_missing_person_column():
    """Reproduces a real bug reported by a user: a
    fika_sync.db predating the per-person calendar connection
    doesn't have the oauth_states.person column, and
    create_oauth_state() always needs it — without the migration, the
    first click on "Connect my calendar" raises sqlite3.OperationalError:
    table oauth_states has no column named person."""
    import sqlite3

    db_path = os.environ["FIKA_SYNC_DB_PATH"]
    # oauth_states schema from BEFORE "person" was added — same
    # old schema that left create_oauth_state() broken for anyone
    # who already had a fika_sync.db from a previous run.
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE oauth_states (
            state TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    models.init_db()  # should not break, and should add the column
    state = models.create_oauth_state("google", person="ana")  # this used to break before the fix

    assert state
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    row = connection.execute("SELECT person FROM oauth_states WHERE state = ?", (state,)).fetchone()
    connection.close()
    assert row["person"] == "ana"


def test_init_db_migration_for_oauth_states_person_column_is_idempotent():
    models.init_db()
    models.init_db()
    models.init_db()
    state = models.create_oauth_state("google", person="beto")
    assert state


def test_mark_auto_sync_ran_persists_timestamp():
    models.init_db()
    models.mark_auto_sync_ran("2026-08-30T12:00:00Z")

    assert models.get_notification_settings()["last_auto_sync_at"] == "2026-08-30T12:00:00Z"


# ---------------------------------------------------------------------------
# Conexiones de calendario POR PERSONA
# ---------------------------------------------------------------------------

def test_save_and_get_person_oauth_connection():
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana", refresh_token="1//ana-refresh")

    connection = models.get_person_oauth_connection("ana", "google")

    assert connection["access_token"] == "ya29.ana"
    assert connection["refresh_token"] == "1//ana-refresh"


def test_get_person_oauth_connection_returns_none_when_not_connected():
    models.init_db()
    assert models.get_person_oauth_connection("ana", "google") is None


def test_two_people_have_independent_connections():
    """The central case for this whole change: ana's token doesn't
    mix with or overwrite beto's."""
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")
    models.save_person_oauth_connection("beto", "google", access_token="ya29.beto")

    assert models.get_person_oauth_connection("ana", "google")["access_token"] == "ya29.ana"
    assert models.get_person_oauth_connection("beto", "google")["access_token"] == "ya29.beto"


def test_save_person_oauth_connection_preserves_refresh_token_when_not_resent():
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.first", refresh_token="1//original")
    models.save_person_oauth_connection("ana", "google", access_token="ya29.second", refresh_token=None)

    connection = models.get_person_oauth_connection("ana", "google")

    assert connection["access_token"] == "ya29.second"
    assert connection["refresh_token"] == "1//original"  # wasn't lost


def test_delete_person_oauth_connection():
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")

    models.delete_person_oauth_connection("ana", "google")

    assert models.get_person_oauth_connection("ana", "google") is None


def test_delete_person_oauth_connection_when_not_connected_does_not_raise():
    models.init_db()
    models.delete_person_oauth_connection("ana", "google")  # should not blow up


def test_delete_person_oauth_connection_does_not_affect_other_people():
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")
    models.save_person_oauth_connection("beto", "google", access_token="ya29.beto")

    models.delete_person_oauth_connection("ana", "google")

    assert models.get_person_oauth_connection("ana", "google") is None
    assert models.get_person_oauth_connection("beto", "google") is not None


def test_list_connected_people():
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")
    models.save_person_oauth_connection("beto", "google", access_token="ya29.beto")

    assert set(models.list_connected_people("google")) == {"ana", "beto"}


def test_list_connected_people_empty_when_nobody_connected():
    models.init_db()
    assert models.list_connected_people("google") == []


def test_delete_team_member_also_removes_their_calendar_connection():
    models.init_db()
    models.add_team_member("flor", gcal_email="flor@example.com")
    models.save_person_oauth_connection("flor", "google", access_token="ya29.flor")

    models.delete_team_member("flor")

    assert models.get_person_oauth_connection("flor", "google") is None


# ---------------------------------------------------------------------------
# person_api_keys — same pattern as person_oauth_connections above,
# for Cal.com (a simple API key, not OAuth, but still personal
# per person — see the big note in models.py).
# ---------------------------------------------------------------------------

def test_save_and_get_person_api_key():
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")

    key_row = models.get_person_api_key("ana", "calcom")

    assert key_row["api_key"] == "cal_ana_key"


def test_get_person_api_key_returns_none_when_not_connected():
    models.init_db()
    assert models.get_person_api_key("ana", "calcom") is None


def test_two_people_have_independent_calcom_keys():
    """The central case for this function: ana's key doesn't clash
    with beto's — each of them sees only their own bookings."""
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    models.save_person_api_key("beto", "calcom", "cal_beto_key")

    assert models.get_person_api_key("ana", "calcom")["api_key"] == "cal_ana_key"
    assert models.get_person_api_key("beto", "calcom")["api_key"] == "cal_beto_key"


def test_save_person_api_key_overwrites_on_reconnect():
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_first")
    models.save_person_api_key("ana", "calcom", "cal_second")

    assert models.get_person_api_key("ana", "calcom")["api_key"] == "cal_second"


def test_delete_person_api_key():
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")

    models.delete_person_api_key("ana", "calcom")

    assert models.get_person_api_key("ana", "calcom") is None


def test_delete_person_api_key_when_not_connected_does_not_raise():
    models.init_db()
    models.delete_person_api_key("ana", "calcom")  # should not blow up


def test_delete_person_api_key_does_not_affect_other_people():
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    models.save_person_api_key("beto", "calcom", "cal_beto_key")

    models.delete_person_api_key("ana", "calcom")

    assert models.get_person_api_key("ana", "calcom") is None
    assert models.get_person_api_key("beto", "calcom") is not None


def test_list_people_with_api_key():
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    models.save_person_api_key("beto", "calcom", "cal_beto_key")

    assert set(models.list_people_with_api_key("calcom")) == {"ana", "beto"}


def test_list_people_with_api_key_empty_when_nobody_connected():
    models.init_db()
    assert models.list_people_with_api_key("calcom") == []


def test_delete_team_member_also_removes_their_calcom_key():
    models.init_db()
    models.add_team_member("flor", calcom_username="flor.dev")
    models.save_person_api_key("flor", "calcom", "cal_flor_key")

    models.delete_team_member("flor")

    assert models.get_person_api_key("flor", "calcom") is None
