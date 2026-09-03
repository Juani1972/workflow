from datetime import datetime, timezone

import pytest

import models
import provider_modules
import sync_service


def test_current_week_start_returns_a_monday():
    # 2026-09-02 is a Wednesday
    wednesday = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    result = sync_service.current_week_start(wednesday)

    assert result == "2026-08-31"  # that week's Monday
    assert datetime.strptime(result, "%Y-%m-%d").weekday() == 0


def test_demo_hours_for_is_deterministic():
    a = sync_service._demo_hours_for("ana", "2026-08-31")
    b = sync_service._demo_hours_for("ana", "2026-08-31")
    assert a == b


def test_demo_hours_for_varies_by_person_and_week():
    ana_week1 = sync_service._demo_hours_for("ana", "2026-08-31")
    beto_week1 = sync_service._demo_hours_for("beto", "2026-08-31")
    ana_week2 = sync_service._demo_hours_for("ana", "2026-09-07")

    assert ana_week1 != beto_week1
    assert ana_week1 != ana_week2


def test_demo_hours_for_is_in_plausible_range():
    hours = sync_service._demo_hours_for("ana", "2026-08-31")
    assert 4 <= hours <= 26


def test_real_credentials_available_reflects_env(monkeypatch):
    monkeypatch.delenv("CALCOM_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    models.init_db()  # real_credentials_available now also checks oauth_connections

    creds = sync_service.real_credentials_available()
    assert creds == {"calcom": False, "google_calendar": False, "slack": False}

    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "x")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "x")

    creds = sync_service.real_credentials_available()
    assert creds["calcom"] is True
    assert creds["google_calendar"] is True
    assert creds["slack"] is False


def test_gcal_events_to_records_ignores_all_day_events():
    events = [
        {"start": {"dateTime": "2026-08-31T09:00:00Z"}, "end": {"dateTime": "2026-08-31T10:00:00Z"}},
        {"start": {"date": "2026-08-31"}, "end": {"date": "2026-09-01"}},  # all-day, no dateTime
    ]
    records = sync_service._gcal_events_to_records(events, "ana")

    assert len(records) == 1
    assert records[0] == {"person": "ana", "duration_minutes": 60.0}


def test_calcom_bookings_to_records_matches_by_attendee_email():
    bookings = [
        {
            "attendees": [{"email": "ana@example.com"}],
            "start": "2026-08-31T09:00:00Z",
            "end": "2026-08-31T09:30:00Z",
        },
        {
            "attendees": [{"email": "beto@example.com"}],
            "start": "2026-08-31T10:00:00Z",
            "end": "2026-08-31T11:00:00Z",
        },
    ]
    records = sync_service._calcom_bookings_to_records(bookings, "ana", "ana@example.com")

    assert len(records) == 1
    assert records[0] == {"person": "ana", "duration_minutes": 30.0}


def test_calcom_bookings_to_records_returns_empty_on_malformed_data():
    """Best-effort: if the format doesn't match, it doesn't crash, it returns []."""
    bookings = [{"unexpected": "shape"}]
    records = sync_service._calcom_bookings_to_records(bookings, "ana", "ana@example.com")
    assert records == []


def test_sync_now_demo_mode_without_credentials(monkeypatch):
    monkeypatch.delenv("CALCOM_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    models.init_db()

    result = sync_service.sync_now()

    assert result["source"] == "demo"
    assert set(result["hours_by_person"].keys()) == {"ana", "beto", "caro", "dani"}
    # actually persisted
    assert models.get_hours_for_week(result["week_start"]) == result["hours_by_person"]


def test_sync_now_falls_back_to_demo_when_real_sync_raises(monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "x")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "x")
    models.init_db()

    def boom(team, week_start):
        raise RuntimeError("Cal.com format does not match")

    monkeypatch.setattr(sync_service, "_sync_real", boom)

    result = sync_service.sync_now()

    assert result["source"] == "demo"
    assert "Cal.com format does not match" in result["fallback_reason"]

    logs = models.get_recent_syncs(limit=1)
    assert logs[0]["status"] == "error"
    assert "Cal.com format does not match" in logs[0]["detail"]


# ---------------------------------------------------------------------------
# real_credentials_available — now also looks at oauth_connections
# ---------------------------------------------------------------------------

def test_real_credentials_available_true_via_person_calendar_connection(monkeypatch):
    """google_calendar now depends on AT LEAST ONE person having
    connected their own calendar — a single app-level connection
    (the kind Sheets would use) is no longer enough, see
    test_real_credentials_available_app_level_alone_is_not_enough."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.fake", refresh_token="1//fake")

    creds = sync_service.real_credentials_available()

    assert creds["google_calendar"] is True


def test_real_credentials_available_app_level_alone_is_not_enough(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    models.init_db()
    models.save_oauth_connection("google", access_token="ya29.fake", refresh_token="1//fake")

    creds = sync_service.real_credentials_available()

    assert creds["google_calendar"] is False


def test_real_credentials_available_true_via_slack_oauth_connection(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake")

    creds = sync_service.real_credentials_available()

    assert creds["slack"] is True


def test_real_credentials_available_false_when_neither_oauth_nor_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    models.init_db()

    creds = sync_service.real_credentials_available()

    assert creds["google_calendar"] is False


# ---------------------------------------------------------------------------
# _build_gcal_client_for_person — each person uses THEIR OWN connection,
# never a shared one
# ---------------------------------------------------------------------------

def test_build_gcal_client_for_person_uses_that_persons_connection(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "app-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "app-secret")
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana", refresh_token="1//ana-token")
    models.save_person_oauth_connection("beto", "google", access_token="ya29.beto", refresh_token="1//beto-token")

    class FakeGCalClient:
        @classmethod
        def from_refresh_token(cls, client_id, client_secret, refresh_token):
            return {"client_id": client_id, "refresh_token": refresh_token}

    fake_gcal_actions = type("FakeModule", (), {"GCalClient": FakeGCalClient})

    ana_client = sync_service._build_gcal_client_for_person(fake_gcal_actions, "ana")
    beto_client = sync_service._build_gcal_client_for_person(fake_gcal_actions, "beto")

    assert ana_client["refresh_token"] == "1//ana-token"
    assert beto_client["refresh_token"] == "1//beto-token"


def test_build_gcal_client_for_person_returns_none_when_not_connected(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "app-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "app-secret")
    models.init_db()  # nobody connected their calendar

    class FakeGCalClient:
        @classmethod
        def from_refresh_token(cls, client_id, client_secret, refresh_token):
            return {"via": "from_refresh_token"}

    fake_gcal_actions = type("FakeModule", (), {"GCalClient": FakeGCalClient})

    client = sync_service._build_gcal_client_for_person(fake_gcal_actions, "ana")

    assert client is None  # no connection, doesn't fall back to any global default


def test_build_gcal_client_for_person_returns_none_without_app_credentials(monkeypatch):
    """Even if the person connected their calendar, without
    GOOGLE_CLIENT_ID/SECRET (the app itself) the client can't be
    built — those identify Fika Sync to Google, they don't change
    per person."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana", refresh_token="1//ana-token")

    fake_gcal_actions = type("FakeModule", (), {"GCalClient": type("FakeGCalClient", (), {})})

    client = sync_service._build_gcal_client_for_person(fake_gcal_actions, "ana")

    assert client is None


# ---------------------------------------------------------------------------
# _build_calcom_client — prioritizes the key saved via the guided flow
# over the CALCOM_API_KEY environment variable
# ---------------------------------------------------------------------------

def test_build_calcom_client_prefers_guided_key_over_env(monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "cal_env_key")
    models.init_db()
    models.save_oauth_connection("calcom", access_token="cal_guided_key", token_type="api_key")

    class FakeCalComClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.via = "constructor"

        @classmethod
        def from_env(cls):
            instance = cls(api_key="cal_env_key")
            instance.via = "from_env"
            return instance

    fake_calcom_actions = type("FakeModule", (), {"CalComClient": FakeCalComClient})

    client = sync_service._build_calcom_client(fake_calcom_actions)

    assert client.via == "constructor"
    assert client.api_key == "cal_guided_key"


def test_build_calcom_client_falls_back_to_env_when_no_guided_key(monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "cal_env_key")
    models.init_db()  # no guided key saved

    class FakeCalComClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.via = "constructor"

        @classmethod
        def from_env(cls):
            instance = cls(api_key="cal_env_key")
            instance.via = "from_env"
            return instance

    fake_calcom_actions = type("FakeModule", (), {"CalComClient": FakeCalComClient})

    client = sync_service._build_calcom_client(fake_calcom_actions)

    assert client.via == "from_env"


# ---------------------------------------------------------------------------
# publish_summary_now
# ---------------------------------------------------------------------------

def test_publish_summary_now_raises_when_slack_not_connected(monkeypatch):
    models.init_db()
    with pytest.raises(sync_service.PublishError, match="Slack isn.t connected"):
        sync_service.publish_summary_now()


def test_publish_summary_now_raises_when_no_channel_configured(monkeypatch):
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")

    with pytest.raises(sync_service.PublishError, match="Slack channel"):
        sync_service.publish_summary_now()


def test_publish_summary_now_posts_report_to_configured_channel(monkeypatch):
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    models.save_notification_settings(slack_channel="#fika-sync-test")
    sync_service.sync_now()  # ensures there are hours calculated for the week

    fake_slack = type("FakeSlackActions", (), {})()
    fake_slack.SlackClient = lambda bot_token: type("FakeClient", (), {"bot_token": bot_token})()
    fake_slack.build_summary_blocks = lambda report_text, people: [{"type": "section"}]

    calls = {}
    def fake_post_message(client, channel, text, blocks=None):
        calls["channel"] = channel
        calls["client_token"] = client.bot_token
        return {"ok": True, "ts": "12345.6789"}
    fake_slack.post_message = fake_post_message

    monkeypatch.setattr(provider_modules, "load_slack", lambda: fake_slack)

    result = sync_service.publish_summary_now()

    assert result["channel"] == "#fika-sync-test"
    assert result["response"]["ok"] is True
    assert calls["channel"] == "#fika-sync-test"
    assert calls["client_token"] == "xoxb-fake"


def test_publish_summary_now_triggers_sync_if_no_data_for_week(monkeypatch):
    """If nobody has synced yet this week, publish_summary_now
    has to calculate the data first (same as /api/metrics),
    not fail or publish an empty summary."""
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    models.save_notification_settings(slack_channel="#fika-sync-test")
    # Deliberately, without calling sync_now() first.

    fake_slack = type("FakeSlackActions", (), {})()
    fake_slack.SlackClient = lambda bot_token: type("FakeClient", (), {"bot_token": bot_token})()
    fake_slack.build_summary_blocks = lambda report_text, people: [{"type": "section"}]
    fake_slack.post_message = lambda client, channel, text, blocks=None: {"ok": True}

    monkeypatch.setattr(provider_modules, "load_slack", lambda: fake_slack)

    result = sync_service.publish_summary_now()

    assert result["response"]["ok"] is True
    week_start = sync_service.current_week_start()
    assert models.get_hours_for_week(week_start) != {}  # sync_now() ran on its own


# ---------------------------------------------------------------------------
# _should_auto_sync — pure scheduler logic, no threads or real timing
# ---------------------------------------------------------------------------

def test_should_auto_sync_false_when_frequency_is_zero():
    assert sync_service._should_auto_sync(None, 0) is False
    assert sync_service._should_auto_sync("2026-08-30T10:00:00Z", 0) is False


def test_should_auto_sync_true_on_first_run_ever():
    assert sync_service._should_auto_sync(None, 60) is True


def test_should_auto_sync_false_when_not_enough_time_elapsed():
    now = datetime(2026, 8, 30, 10, 30, tzinfo=timezone.utc)
    last_sync = "2026-08-30T10:00:00Z"  # 30 minutes ago

    assert sync_service._should_auto_sync(last_sync, frequency_minutes=60, now=now) is False


def test_should_auto_sync_true_when_enough_time_elapsed():
    now = datetime(2026, 8, 30, 11, 1, tzinfo=timezone.utc)
    last_sync = "2026-08-30T10:00:00Z"  # 61 minutes ago

    assert sync_service._should_auto_sync(last_sync, frequency_minutes=60, now=now) is True


def test_should_auto_sync_boundary_exactly_at_frequency():
    now = datetime(2026, 8, 30, 11, 0, tzinfo=timezone.utc)
    last_sync = "2026-08-30T10:00:00Z"  # exactly 60 minutes

    assert sync_service._should_auto_sync(last_sync, frequency_minutes=60, now=now) is True


# ---------------------------------------------------------------------------
# run_auto_sync_if_due
# ---------------------------------------------------------------------------

def test_run_auto_sync_if_due_does_nothing_when_frequency_is_zero():
    models.init_db()  # default: sync_frequency_minutes=0

    result = sync_service.run_auto_sync_if_due()

    assert result is None
    assert models.get_recent_syncs(limit=1) == []  # nothing was synced


def test_run_auto_sync_if_due_syncs_and_marks_timestamp_on_first_run():
    models.init_db()
    models.save_notification_settings(sync_frequency_minutes=60)

    result = sync_service.run_auto_sync_if_due()

    assert result is not None
    assert result["source"] == "demo"
    assert models.get_notification_settings()["last_auto_sync_at"] is not None


def test_run_auto_sync_if_due_does_not_double_sync_immediately_after():
    models.init_db()
    models.save_notification_settings(sync_frequency_minutes=60)

    first = sync_service.run_auto_sync_if_due()
    second = sync_service.run_auto_sync_if_due()  # called "again" right away

    assert first is not None
    assert second is None  # not enough time has passed yet


def test_run_auto_sync_if_due_auto_publishes_when_configured(monkeypatch):
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    models.save_notification_settings(
        sync_frequency_minutes=60, slack_channel="#fika-sync-test", auto_publish_on_sync=True,
    )

    published = {}
    monkeypatch.setattr(
        sync_service, "publish_summary_now",
        lambda: published.setdefault("called", True) or {"channel": "#fika-sync-test", "response": {"ok": True}},
    )

    sync_service.run_auto_sync_if_due()

    assert published.get("called") is True


def test_run_auto_sync_if_due_does_not_fail_if_publish_fails(monkeypatch):
    """If Slack isn't ready (channel deleted, token revoked, etc.), the
    auto-sync itself shouldn't fail because of that — only the publish step."""
    models.init_db()
    models.save_notification_settings(sync_frequency_minutes=60, auto_publish_on_sync=True)
    # Deliberately: auto_publish_on_sync=True but WITHOUT slack connected
    # or a channel configured — publish_summary_now() will raise PublishError.

    result = sync_service.run_auto_sync_if_due()

    assert result is not None  # the sync itself wasn't affected
    assert result["source"] == "demo"


# ---------------------------------------------------------------------------
# sync_now() with partial calendar connections across the team
# ---------------------------------------------------------------------------

def test_sync_now_enters_real_mode_with_only_calcom_and_no_calendars_connected(monkeypatch):
    """Previously, sync_now required an app-level Google connection to
    enter real mode. Now, with per-person calendars, Cal.com alone
    is already enough — the calendar is an optional enrichment."""
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")
    models.init_db()  # nobody connected their calendar

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type("FakeClient", (), {"from_env": classmethod(lambda cls: "fake")})
    fake_calcom_actions.list_bookings = lambda client, status=None: []

    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    result = sync_service.sync_now()

    assert result["source"] == "calcom+gcal"
    # all 4 team members had gcal_email set in the seed
    # -> all 4 end up "skipped" for not having connected their calendar
    assert set(result["skipped_calendar_connection"]) == {"ana", "beto", "caro", "dani"}


def test_sync_now_only_lists_people_who_actually_lack_a_connection(monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "app-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "app-secret")
    models.init_db()
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana", refresh_token="1//ana")

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type("FakeClient", (), {"from_env": classmethod(lambda cls: "fake")})
    fake_calcom_actions.list_bookings = lambda client, status=None: []

    fake_gcal_actions = type("FakeGcal", (), {})()
    fake_gcal_actions.GCalClient = type(
        "FakeGCalClient", (), {"from_refresh_token": classmethod(lambda cls, cid, cs, rt: "fake-client")}
    )
    fake_gcal_actions.list_events = lambda client, email, tmin, tmax: []

    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: fake_gcal_actions)

    result = sync_service.sync_now()

    assert "ana" not in result["skipped_calendar_connection"]
    assert set(result["skipped_calendar_connection"]) == {"beto", "caro", "dani"}


def test_sync_now_no_skipped_key_when_everyone_connected(monkeypatch):
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "app-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "app-secret")
    models.init_db()
    for person in ("ana", "beto", "caro", "dani"):
        models.save_person_oauth_connection(person, "google", access_token=f"ya29.{person}", refresh_token=f"1//{person}")

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type("FakeClient", (), {"from_env": classmethod(lambda cls: "fake")})
    fake_calcom_actions.list_bookings = lambda client, status=None: []

    fake_gcal_actions = type("FakeGcal", (), {})()
    fake_gcal_actions.GCalClient = type(
        "FakeGCalClient", (), {"from_refresh_token": classmethod(lambda cls, cid, cs, rt: "fake-client")}
    )
    fake_gcal_actions.list_events = lambda client, email, tmin, tmax: []

    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: fake_gcal_actions)

    result = sync_service.sync_now()

    assert "skipped_calendar_connection" not in result


# ---------------------------------------------------------------------------
# Per-person Cal.com — same spirit as the calendar tests above: each
# person with their own key sees THEIR OWN bookings, not anyone
# else's, without depending on a shared app-level key.
# ---------------------------------------------------------------------------

def test_calcom_bookings_to_records_without_email_filter_takes_everything():
    """When bookings come from the person's OWN account
    (attendee_email=None), there's no need to filter by email —
    everything that account returned belongs to them."""
    bookings = [
        {"start": "2026-09-01T10:00:00Z", "end": "2026-09-01T11:00:00Z", "attendees": [{"email": "otro@example.com"}]},
        {"start": "2026-09-02T10:00:00Z", "end": "2026-09-02T10:30:00Z"},
    ]
    records = sync_service._calcom_bookings_to_records(bookings, "ana")
    assert len(records) == 2
    assert sum(r["duration_minutes"] for r in records) == 90.0


def test_build_calcom_client_for_person_returns_none_without_key():
    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = lambda api_key: f"client-for-{api_key}"

    models.init_db()
    client = sync_service._build_calcom_client_for_person(fake_calcom_actions, "ana")
    assert client is None


def test_build_calcom_client_for_person_uses_their_own_key():
    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = lambda api_key: f"client-for-{api_key}"

    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")

    client = sync_service._build_calcom_client_for_person(fake_calcom_actions, "ana")
    assert client == "client-for-cal_ana_key"


def test_sync_now_uses_each_persons_own_calcom_key_not_a_shared_call(monkeypatch):
    """The central case for this function: if EVERY person connected
    their own key, the app-level fallback client should never be
    called — CALCOM_API_KEY doesn't even need to exist."""
    models.init_db()  # seed: ana, beto, caro, dani
    for person in ("ana", "beto", "caro", "dani"):
        models.save_person_api_key(person, "calcom", f"cal_{person}_key")

    calls = []

    def fake_list_bookings(client, status=None):
        calls.append(client)
        return [{"start": "2026-09-01T10:00:00Z", "end": "2026-09-01T11:00:00Z"}]

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = lambda api_key: f"client-{api_key}"
    fake_calcom_actions.list_bookings = fake_list_bookings

    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    result = sync_service.sync_now()

    assert result["source"] == "calcom+gcal"
    assert "skipped_calcom_connection" not in result
    # one call to list_bookings per person, each with THEIR client
    assert len(calls) == 4
    assert calls == ["client-cal_ana_key", "client-cal_beto_key", "client-cal_caro_key", "client-cal_dani_key"]
    for person, hours in result["hours_by_person"].items():
        assert hours == 1.0  # 60 minutes = 1 hour, for all 4 people


def test_sync_now_falls_back_to_shared_calcom_client_for_people_without_own_key(monkeypatch):
    """Backward compatibility: whoever didn't connect their own key is
    still covered by the shared app-level key, filtered by email —
    same behavior as before the personal key existed."""
    monkeypatch.setenv("CALCOM_API_KEY", "cal_shared_team_key")
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    # beto, caro, dani didn't connect their own — they depend on the fallback

    shared_bookings = [
        {"start": "2026-09-01T10:00:00Z", "end": "2026-09-01T11:00:00Z",
         "attendees": [{"email": "beto@example.com"}]},
    ]
    own_calls = []

    def fake_calcom_client(api_key):
        return "shared-client" if api_key == "cal_shared_team_key" else f"client-{api_key}"
    fake_calcom_client.from_env = lambda: "shared-client"

    def fake_list_bookings(client, status=None):
        if client == "shared-client":
            return shared_bookings
        own_calls.append(client)
        return []

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = fake_calcom_client
    fake_calcom_actions.list_bookings = fake_list_bookings

    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    result = sync_service.sync_now()

    assert own_calls == ["client-cal_ana_key"]  # ana used her own
    assert "skipped_calcom_connection" not in result  # beto has gcal_email set in the seed


def test_sync_now_reports_skipped_calcom_when_no_key_available_at_all(monkeypatch):
    """Without their own key AND without any fallback key configured
    (CALCOM_API_KEY missing), the person ends up in
    skipped_calcom_connection — it doesn't break the whole sync."""
    models.init_db()
    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    # nobody else connected anything, and there's no CALCOM_API_KEY set

    def fake_list_bookings(client, status=None):
        return []

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = lambda api_key: f"client-{api_key}"

    class _FromEnvRaises:
        @classmethod
        def from_env(cls):
            raise ValueError("CALCOM_API_KEY is not set")
    fake_calcom_actions.CalComClient.from_env = _FromEnvRaises.from_env
    fake_calcom_actions.list_bookings = fake_list_bookings

    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    result = sync_service.sync_now()

    assert result["source"] == "calcom+gcal"
    assert "ana" not in result["skipped_calcom_connection"]
    assert set(result["skipped_calcom_connection"]) == {"beto", "caro", "dani"}


def test_real_credentials_available_counts_any_person_calcom_key(monkeypatch):
    models.init_db()
    assert sync_service.real_credentials_available()["calcom"] is False

    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    assert sync_service.real_credentials_available()["calcom"] is True


# ---------------------------------------------------------------------------
# Personal Slack DMs — send_personal_dm_notifications and its pure
# text builder, _build_personal_dm_text.
# ---------------------------------------------------------------------------

def test_build_personal_dm_text_mentions_person_hours_and_status():
    text = sync_service._build_personal_dm_text("ana", 22.3, "red")
    assert "ana" in text
    assert "22.3" in text
    assert "red" in text


def test_build_personal_dm_text_is_pure_no_network():
    """Same spirit as team_health_analyzer: the text can be built
    without mocking anything, because it makes no network call."""
    a = sync_service._build_personal_dm_text("ana", 18.0, "yellow")
    b = sync_service._build_personal_dm_text("ana", 18.0, "yellow")
    assert a == b


def test_send_personal_dm_notifications_fails_without_slack_connected():
    models.init_db()
    with pytest.raises(sync_service.PublishError):
        sync_service.send_personal_dm_notifications({"ana": 22.0}, {"ana": "red"})


def test_send_personal_dm_notifications_sends_only_to_yellow_and_red(monkeypatch):
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")

    sent_to = []

    fake_slack_actions = type("FakeSlack", (), {})()
    fake_slack_actions.SlackClient = lambda bot_token: f"client-{bot_token}"
    fake_slack_actions.post_message = lambda client, channel, text=None, blocks=None: sent_to.append(channel) or {"ok": True}

    monkeypatch.setattr(provider_modules, "load_slack", lambda: fake_slack_actions)

    hours = {"ana": 22.0, "beto": 10.0, "caro": 17.0}
    status = {"ana": "red", "beto": "green", "caro": "yellow"}

    results = sync_service.send_personal_dm_notifications(hours, status)

    assert results["ana"] == "sent"
    assert results["beto"] == "skipped_green"
    assert results["caro"] == "sent"
    # ana and caro's slack_user_id in the seed: U0000001, U0000003
    assert set(sent_to) == {"U0000001", "U0000003"}


def test_send_personal_dm_notifications_skips_people_without_slack_user_id(monkeypatch):
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    models.update_team_member("ana", slack_user_id="")

    fake_slack_actions = type("FakeSlack", (), {})()
    fake_slack_actions.SlackClient = lambda bot_token: f"client-{bot_token}"
    calls = []
    fake_slack_actions.post_message = lambda client, channel, text=None, blocks=None: calls.append(channel) or {"ok": True}

    monkeypatch.setattr(provider_modules, "load_slack", lambda: fake_slack_actions)

    results = sync_service.send_personal_dm_notifications({"ana": 22.0}, {"ana": "red"})

    assert results["ana"] == "skipped_no_slack_id"
    assert calls == []


def test_send_personal_dm_notifications_one_failure_does_not_block_others(monkeypatch):
    """The central case for this function: a DM that fails (network
    error, permissions, whatever) shouldn't stop the rest of the team."""
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")

    def flaky_post_message(client, channel, text=None, blocks=None):
        if channel == "U0000001":  # ana
            raise RuntimeError("Slack API error: rate_limited")
        return {"ok": True}

    fake_slack_actions = type("FakeSlack", (), {})()
    fake_slack_actions.SlackClient = lambda bot_token: f"client-{bot_token}"
    fake_slack_actions.post_message = flaky_post_message

    monkeypatch.setattr(provider_modules, "load_slack", lambda: fake_slack_actions)

    hours = {"ana": 22.0, "beto": 21.0}
    status = {"ana": "red", "beto": "red"}

    results = sync_service.send_personal_dm_notifications(hours, status)

    assert "error" in results["ana"]
    assert results["beto"] == "sent"  # beto still got sent, despite ana's error


def test_send_personal_dm_notifications_computes_current_week_when_not_passed(monkeypatch):
    """Without passing hours_by_person/health_status, it calculates
    them itself (same pattern as publish_summary_now)."""
    models.init_db()
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    week_start = sync_service.current_week_start()
    models.record_meeting_hours("ana", week_start, 22.0, "demo")

    sent_to = []
    fake_slack_actions = type("FakeSlack", (), {})()
    fake_slack_actions.SlackClient = lambda bot_token: f"client-{bot_token}"
    fake_slack_actions.post_message = lambda client, channel, text=None, blocks=None: sent_to.append(channel) or {"ok": True}

    monkeypatch.setattr(provider_modules, "load_slack", lambda: fake_slack_actions)

    results = sync_service.send_personal_dm_notifications()

    assert results["ana"] == "sent"
    assert "U0000001" in sent_to


def test_run_auto_sync_if_due_sends_personal_dms_when_enabled(monkeypatch):
    models.init_db()
    models.save_notification_settings(sync_frequency_minutes=60, personal_dms_enabled=True)
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type("FakeClient", (), {"from_env": classmethod(lambda cls: "fake")})
    fake_calcom_actions.list_bookings = lambda client, status=None: []
    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    dm_calls = []
    original_send_dms = sync_service.send_personal_dm_notifications

    def spy_send_dms(*a, **k):
        dm_calls.append(True)
        return {}
    monkeypatch.setattr(sync_service, "send_personal_dm_notifications", spy_send_dms)

    sync_service.run_auto_sync_if_due()

    assert dm_calls == [True]


def test_run_auto_sync_if_due_does_not_send_dms_when_disabled(monkeypatch):
    models.init_db()
    models.save_notification_settings(sync_frequency_minutes=60, personal_dms_enabled=False)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type("FakeClient", (), {"from_env": classmethod(lambda cls: "fake")})
    fake_calcom_actions.list_bookings = lambda client, status=None: []
    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    dm_calls = []
    monkeypatch.setattr(sync_service, "send_personal_dm_notifications", lambda *a, **k: dm_calls.append(True))

    sync_service.run_auto_sync_if_due()

    assert dm_calls == []


def test_run_auto_sync_if_due_does_not_crash_when_slack_not_connected(monkeypatch):
    """personal_dms_enabled=True but Slack not connected: shouldn't
    take down the auto-sync (same behavior as auto_publish_on_sync
    with PublishError)."""
    models.init_db()
    models.save_notification_settings(sync_frequency_minutes=60, personal_dms_enabled=True)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_test_x")

    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type("FakeClient", (), {"from_env": classmethod(lambda cls: "fake")})
    fake_calcom_actions.list_bookings = lambda client, status=None: []
    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: type("FakeGcal", (), {})())

    result = sync_service.run_auto_sync_if_due()  # shouldn't raise
    assert result is not None


# ---------------------------------------------------------------------------
# _sync_real — mutual exclusion between Cal.com / Google Calendar per
# person. Safety net: even though calcom_connect_for_person and
# oauth_start_for_person already block connecting both sources from
# the GUI, this confirms that even if a row ended up with both
# connections (stale data, or edited directly in the database),
# _sync_real doesn't add them up anyway — otherwise the same meeting
# (Cal.com usually writes it into the person's Google Calendar too)
# would be counted twice.
# ---------------------------------------------------------------------------

def test_sync_real_does_not_double_count_when_person_has_both_sources(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "app-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "app-secret")
    models.init_db()
    models.add_team_member("ana", calcom_username="ana.dev", gcal_email="ana@example.com")
    # ana has BOTH connected — the scenario that shouldn't be
    # possible from the GUI anymore, but we still want to make sure
    # it doesn't break the numbers if it happened.
    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana", refresh_token="1//ana-token")

    # Cal.com: a 60-minute meeting.
    fake_calcom_actions = type("FakeCalcom", (), {})()
    fake_calcom_actions.CalComClient = type(
        "FakeCalComClient", (), {"__init__": lambda self, api_key=None: None}
    )
    fake_calcom_actions.list_bookings = lambda client, status=None: [
        {
            "attendees": [{"email": "ana@example.com"}],
            "start": "2026-01-05T09:00:00Z",
            "end": "2026-01-05T10:00:00Z",
        }
    ]
    monkeypatch.setattr(provider_modules, "load_calcom_pro", lambda: fake_calcom_actions)

    # Google Calendar: the SAME meeting, as if Cal.com had written it
    # there too — if _sync_real added it in, ana would show 2h
    # instead of 1.
    gcal_list_events_calls = []

    class FakeGCalClient:
        @classmethod
        def from_refresh_token(cls, client_id, client_secret, refresh_token):
            return {"refresh_token": refresh_token}

    def fake_list_events(client, email, time_min, time_max):
        gcal_list_events_calls.append(email)
        return [{
            "summary": "Duplicate meeting", "start": {"dateTime": "2026-01-05T09:00:00Z"},
            "end": {"dateTime": "2026-01-05T10:00:00Z"},
        }]

    fake_gcal_actions = type("FakeGcal", (), {})()
    fake_gcal_actions.GCalClient = FakeGCalClient
    fake_gcal_actions.list_events = fake_list_events
    monkeypatch.setattr(provider_modules, "load_gcal", lambda: fake_gcal_actions)

    hours_by_person, skipped = sync_service._sync_real(models.get_team(), "2026-01-05")

    # The safety net: since ana has her own Cal.com key,
    # list_events isn't even called for her — there's no way for
    # the meeting to be counted twice.
    assert gcal_list_events_calls == []
    assert hours_by_person["ana"] == 1.0  # one hour, not two


