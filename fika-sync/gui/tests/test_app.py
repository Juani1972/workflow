def test_index_page_loads(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Fika" in res.data


def test_status_endpoint_reports_no_credentials_by_default(client, monkeypatch):
    monkeypatch.delenv("CALCOM_API_KEY", raising=False)
    res = client.get("/api/status")
    body = res.get_json()

    assert res.status_code == 200
    assert body["providers"]["calcom"]["credentials_configured"] is False
    assert body["providers"]["calcom"]["validated_against_real_account"] is False


def test_team_endpoint_returns_seeded_team(client):
    res = client.get("/api/team")
    body = res.get_json()

    assert res.status_code == 200
    assert len(body) == 4


def test_metrics_endpoint_triggers_sync_on_first_call(client):
    res = client.get("/api/metrics")
    body = res.get_json()

    assert res.status_code == 200
    assert body["source"] == "demo"
    assert set(body["hours_by_person"].keys()) == {"ana", "beto", "caro", "dani"}
    assert set(body["health_status"].values()) <= {"green", "yellow", "red"}
    assert "Weekly meeting load summary" in body["report_text"]


def test_metrics_endpoint_is_stable_across_calls_same_week(client):
    first = client.get("/api/metrics").get_json()
    second = client.get("/api/metrics").get_json()

    assert first["hours_by_person"] == second["hours_by_person"]


def test_metrics_uses_per_person_threshold_for_classification(client):
    # caro has a red threshold at 18h (default is 20h) — lower it to
    # force caro into red with fewer hours than everyone else.
    client.post("/api/thresholds", json={"person": "caro", "field": "red_hours", "value": 0.1})

    body = client.get("/api/metrics").get_json()

    assert body["health_status"]["caro"] == "red"


def test_thresholds_endpoint_updates_value(client):
    res = client.post("/api/thresholds", json={"person": "ana", "field": "red_hours", "value": 23.5})
    body = res.get_json()

    assert res.status_code == 200
    assert body == {"person": "ana", "field": "red_hours", "value": 23.5}

    team = {m["person"]: m for m in client.get("/api/team").get_json()}
    assert team["ana"]["red_hours"] == 23.5


def test_thresholds_endpoint_rejects_unknown_field(client):
    res = client.post("/api/thresholds", json={"person": "ana", "field": "purple_hours", "value": 1})
    assert res.status_code == 400


def test_thresholds_endpoint_rejects_non_numeric_value(client):
    res = client.post("/api/thresholds", json={"person": "ana", "field": "red_hours", "value": "mucho"})
    assert res.status_code == 400


def test_thresholds_endpoint_404_for_unknown_person(client):
    res = client.post("/api/thresholds", json={"person": "nadie", "field": "red_hours", "value": 20})
    assert res.status_code == 404


def test_history_endpoint_returns_list(client):
    client.get("/api/metrics")  # triggers a sync, leaves this week's history
    res = client.get("/api/history/ana")

    assert res.status_code == 200
    assert isinstance(res.get_json(), list)


def test_sync_endpoint_returns_source_and_persists(client):
    res = client.post("/api/sync")
    body = res.get_json()

    assert res.status_code == 200
    assert body["source"] == "demo"
    assert "week_start" in body


def test_sync_log_endpoint_reflects_syncs(client):
    client.post("/api/sync")
    res = client.get("/api/sync-log")
    body = res.get_json()

    assert res.status_code == 200
    assert len(body) >= 1


def test_reset_demo_requires_confirmation(client):
    res = client.post("/api/reset-demo", json={})
    assert res.status_code == 400


def test_reset_demo_clears_and_reseeds(client):
    client.post("/api/thresholds", json={"person": "ana", "field": "red_hours", "value": 99})
    client.post("/api/sync")

    res = client.post("/api/reset-demo", json={"confirm": True})
    assert res.status_code == 200
    assert res.get_json()["reset"] is True

    team = {m["person"]: m for m in client.get("/api/team").get_json()}
    assert team["ana"]["red_hours"] == 20.0  # vuelve al default de config


# ---------------------------------------------------------------------------
# OAuth flow: "Connect with one click"
# ---------------------------------------------------------------------------

def test_oauth_start_rejects_unknown_provider(client):
    res = client.get("/oauth/dropbox/start")
    assert res.status_code == 404


def test_oauth_start_redirects_with_error_when_app_credentials_missing(client, monkeypatch):
    """Replaces the old test_oauth_start_returns_501_when_app_credentials_missing
    — see test_oauth_start_without_app_credentials_redirects_with_friendly_error
    below for the full version of this same case."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    res = client.get("/oauth/google/start")

    assert res.status_code == 302
    assert "GOOGLE_CLIENT_ID" in res.headers["Location"]


def test_oauth_start_redirects_to_google_with_state(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    res = client.get("/oauth/google/start")

    assert res.status_code == 302
    assert "accounts.google.com" in res.headers["Location"]
    assert "state=" in res.headers["Location"]


def test_oauth_start_redirects_to_slack(client, monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "test-slack-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "test-slack-secret")

    res = client.get("/oauth/slack/start")

    assert res.status_code == 302
    assert "slack.com" in res.headers["Location"]


def test_oauth_callback_rejects_unknown_provider(client):
    res = client.get("/oauth/dropbox/callback?code=x&state=y")
    assert res.status_code == 404


def test_oauth_callback_redirects_with_error_when_provider_reports_error(client):
    res = client.get("/oauth/google/callback?error=access_denied")

    assert res.status_code == 302
    assert "oauth_error=google" in res.headers["Location"]


def test_oauth_callback_rejects_invalid_or_missing_state(client):
    res = client.get("/oauth/google/callback?code=abc&state=state-that-never-existed")

    assert res.status_code == 302
    assert "oauth_error=google:invalid_state" in res.headers["Location"]


def test_oauth_callback_rejects_state_issued_for_a_different_provider(client, monkeypatch):
    """If the state was created for 'slack' but arrives at 'google''s callback, it
    has to be rejected — this is exactly the kind of mismatch that protects against CSRF."""
    import models
    state = models.create_oauth_state("slack")

    res = client.get(f"/oauth/google/callback?code=abc&state={state}")

    assert res.status_code == 302
    assert "oauth_error=google:invalid_state" in res.headers["Location"]


def test_oauth_callback_google_happy_path_saves_connection(client, monkeypatch):
    import models
    from unittest.mock import patch

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    state = models.create_oauth_state("google")

    with patch("oauth_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {
            "access_token": "ya29.fake", "refresh_token": "1//fake",
            "token_type": "Bearer", "scope": "calendar spreadsheets",
        }
        res = client.get(f"/oauth/google/callback?code=fakecode&state={state}")

    assert res.status_code == 302
    assert "oauth_connected=google" in res.headers["Location"]

    connection = models.get_oauth_connection("google")
    assert connection["refresh_token"] == "1//fake"
    # The code-for-token exchange with Google just succeeded
    # — that IS the proof that the app's Client ID/Secret
    # work, it's marked right then, without a separate call.
    assert connection["validated_at"]

    status_body = client.get("/api/status").get_json()
    assert status_body["providers"]["google_calendar"]["validated_against_real_account"] is False
    # note: it's still False here because "google_calendar" measures PER-PERSON
    # connections (person_oauth_connections), not the app-level one above —
    # see test_oauth_callback_google_for_person_marks_validated below


def test_oauth_callback_slack_happy_path_saves_connection(client, monkeypatch):
    import models
    from unittest.mock import patch

    monkeypatch.setenv("SLACK_CLIENT_ID", "test-slack-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "test-slack-secret")
    state = models.create_oauth_state("slack")

    with patch("oauth_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {
            "ok": True, "access_token": "xoxb-fake",
            "team": {"id": "T123", "name": "Test Team"}, "bot_user_id": "U999",
        }
        res = client.get(f"/oauth/slack/callback?code=fakecode&state={state}")

    assert res.status_code == 302
    assert "oauth_connected=slack" in res.headers["Location"]

    connection = models.get_oauth_connection("slack")
    assert connection["access_token"] == "xoxb-fake"
    assert connection["extra"]["team_id"] == "T123"
    assert connection["validated_at"]

    status_body = client.get("/api/status").get_json()
    assert status_body["providers"]["slack"]["validated_against_real_account"] is True


def test_oauth_start_without_app_credentials_redirects_with_friendly_error(client, monkeypatch):
    """Before this fix, clicking 'Connect' without the admin having
    configured the Client ID/Secret yet returned raw JSON (501) that
    the browser displayed as-is, with no readable error banner —
    because this endpoint is an <a href> the browser navigates to
    directly, not a fetch the frontend can intercept. It now redirects
    to index with oauth_error, same as the rest of the OAuth failures."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    res = client.get("/oauth/google/start")

    assert res.status_code == 302  # no more 501 with raw JSON
    assert "accounts.google.com" not in res.headers["Location"]
    assert res.headers["Location"].startswith("/")
    assert "oauth_error=google:not_configured:" in res.headers["Location"]


def test_oauth_start_for_person_without_app_credentials_redirects_with_friendly_error(client, monkeypatch):
    """Same fix, for the 'Connect my calendar' link on a specific
    row in Team."""
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    res = client.get("/oauth/google/start/ana")

    assert res.status_code == 302
    assert "accounts.google.com" not in res.headers["Location"]
    assert "oauth_error=google:not_configured:" in res.headers["Location"]


def test_oauth_callback_google_for_person_marks_validated_against_real_account(client, monkeypatch):
    """The field that actually matters for the badge at the top of
    the Connections tab: when ONE person successfully completes the
    Google login, that already proves the app's credentials work —
    status() uses the existence of that row in
    person_oauth_connections as the proof, without needing a separate
    call or a per-person validated_at column."""
    import models
    from unittest.mock import patch

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    state = models.create_oauth_state("google", person="ana")

    assert client.get("/api/status").get_json()["providers"]["google_calendar"]["validated_against_real_account"] is False

    with patch("oauth_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {
            "access_token": "ya29.ana", "refresh_token": "1//ana-refresh",
            "token_type": "Bearer", "scope": "calendar",
        }
        res = client.get(f"/oauth/google/callback?code=fakecode&state={state}")

    assert res.status_code == 302
    status_body = client.get("/api/status").get_json()
    assert status_body["providers"]["google_calendar"]["validated_against_real_account"] is True


def test_oauth_callback_redirects_with_error_when_exchange_fails(client, monkeypatch):
    import models
    from unittest.mock import patch

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    state = models.create_oauth_state("google")

    with patch("oauth_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 400
        mock_post.return_value.raise_for_status.side_effect = Exception("invalid_grant")
        res = client.get(f"/oauth/google/callback?code=badcode&state={state}")

    assert res.status_code == 302
    assert "oauth_error=google" in res.headers["Location"]
    assert models.get_oauth_connection("google") is None


def test_oauth_disconnect_removes_connection(client):
    import models
    models.save_oauth_connection("google", access_token="ya29.fake", refresh_token="1//fake")

    res = client.post("/oauth/google/disconnect")

    assert res.status_code == 200
    assert models.get_oauth_connection("google") is None


def test_oauth_disconnect_rejects_unknown_provider(client):
    res = client.post("/oauth/dropbox/disconnect")
    assert res.status_code == 404


def test_status_reflects_slack_oauth_connection_over_env_vars(client, monkeypatch):
    """If there's a saved OAuth connection, status reflects it even
    if no bot token environment variables are set."""
    import models

    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")

    res = client.get("/api/status")
    body = res.get_json()

    assert body["providers"]["slack"]["credentials_configured"] is True
    assert body["providers"]["slack"]["connection_method"] == "oauth_connected"
    assert body["oauth"]["connected"]["slack"] is True


def test_status_google_calendar_reflects_at_least_one_person_connected(client, monkeypatch):
    """google_calendar is now per-person, not an app-level connection
    — an app-level Google connection alone (e.g. for Sheets) does NOT
    count as 'a calendar is available'."""
    import models

    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)

    # Just the app-level connection (Sheets) — nobody on the team connected yet.
    models.save_oauth_connection("google", access_token="ya29.fake", refresh_token="1//fake")
    res = client.get("/api/status")
    assert res.get_json()["providers"]["google_calendar"]["credentials_configured"] is False

    # Now a real person connects their calendar.
    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana", refresh_token="1//ana")
    res = client.get("/api/status")
    assert res.get_json()["providers"]["google_calendar"]["credentials_configured"] is True


# ---------------------------------------------------------------------------
# Cal.com guided flow (not real OAuth — Cal.com doesn't offer it for
# personal/free accounts, see fika-sync/gui/README.md)
# ---------------------------------------------------------------------------

def test_calcom_connect_rejects_missing_api_key(client):
    res = client.post("/api/calcom/connect", json={})
    assert res.status_code == 400


def test_calcom_connect_rejects_key_with_wrong_prefix(client):
    res = client.post("/api/calcom/connect", json={"api_key": "does-not-start-with-cal"})
    assert res.status_code == 400
    assert "cal_" in res.get_json()["error"]


def _fake_calcom_actions_ok():
    """A fake provider_modules.load_calcom_pro() that simulates a
    valid key — calcom_connect() and calcom_connect_for_person() now
    test the key with a real call before saving it (see their
    docstrings in app.py), so any test that connects a fake key
    needs this to avoid getting a 400."""
    fake = type("FakeCalcom", (), {})()
    fake.CalComClient = type("FakeClient", (), {"__init__": lambda self, api_key=None: None})
    fake.list_bookings = lambda client, status=None: []
    return fake


def test_calcom_connect_saves_key_and_reflects_in_status(client, monkeypatch):
    from unittest.mock import patch
    import models

    monkeypatch.delenv("CALCOM_API_KEY", raising=False)

    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        res = client.post("/api/calcom/connect", json={"api_key": "cal_test_abc123"})
    assert res.status_code == 200
    assert res.get_json()["connected"] == "calcom"

    connection = models.get_oauth_connection("calcom")
    assert connection["access_token"] == "cal_test_abc123"
    assert connection["token_type"] == "api_key"
    assert connection["validated_at"]  # tested with a real call before saving

    status_body = client.get("/api/status").get_json()
    assert status_body["providers"]["calcom"]["credentials_configured"] is True
    assert status_body["providers"]["calcom"]["validated_against_real_account"] is True
    assert status_body["providers"]["calcom"]["connection_method"] == "guided_api_key"
    assert status_body["oauth"]["connected"]["calcom"] is True


def test_calcom_connect_rejects_key_that_fails_the_real_test_call(client):
    """If the key has the right format (starts with 'cal_') but
    Cal.com rejects it (revoked, from another account, etc.), it
    shouldn't be saved — before this fix, any key with the right
    prefix was saved anyway, regardless of whether it worked."""
    import models
    from unittest.mock import patch

    fake = type("FakeCalcom", (), {})()
    fake.CalComClient = type("FakeClient", (), {"__init__": lambda self, api_key=None: None})

    def boom(client, status=None):
        raise RuntimeError("401 Unauthorized")
    fake.list_bookings = boom

    with patch("provider_modules.load_calcom_pro", return_value=fake):
        res = client.post("/api/calcom/connect", json={"api_key": "cal_test_but_invalid"})

    assert res.status_code == 400
    assert models.get_oauth_connection("calcom") is None


def test_calcom_connect_strips_whitespace(client):
    import models
    from unittest.mock import patch

    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        client.post("/api/calcom/connect", json={"api_key": "  cal_test_abc123  "})

    connection = models.get_oauth_connection("calcom")
    assert connection["access_token"] == "cal_test_abc123"


def test_calcom_disconnect_removes_connection(client):
    import models

    models.save_oauth_connection("calcom", access_token="cal_test_abc123", token_type="api_key")

    res = client.post("/api/calcom/disconnect")

    assert res.status_code == 200
    assert models.get_oauth_connection("calcom") is None


def test_calcom_connect_overrides_env_var(client, monkeypatch):
    """If there's a CALCOM_API_KEY environment variable AND a key
    saved via the guided flow, status should reflect the guided one as
    the active connection method — it's the one that wins in sync_service."""
    import models
    from unittest.mock import patch

    monkeypatch.setenv("CALCOM_API_KEY", "cal_env_var_key")
    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        client.post("/api/calcom/connect", json={"api_key": "cal_guided_key"})

    status_body = client.get("/api/status").get_json()
    assert status_body["providers"]["calcom"]["connection_method"] == "guided_api_key"

    connection = models.get_oauth_connection("calcom")
    assert connection["access_token"] == "cal_guided_key"


# ---------------------------------------------------------------------------
# Team management
# ---------------------------------------------------------------------------

def test_add_team_member_endpoint(client):
    res = client.post("/api/team", json={"person": "flor", "gcal_email": "flor@example.com"})

    assert res.status_code == 201
    assert res.get_json()["added"] == "flor"

    team = {m["person"]: m for m in client.get("/api/team").get_json()}
    assert team["flor"]["gcal_email"] == "flor@example.com"


def test_add_team_member_requires_person(client):
    res = client.post("/api/team", json={"gcal_email": "x@example.com"})
    assert res.status_code == 400


def test_add_team_member_rejects_duplicate(client):
    client.post("/api/team", json={"person": "flor"})
    res = client.post("/api/team", json={"person": "flor"})
    assert res.status_code == 409


def test_add_team_member_rejects_invalid_thresholds(client):
    res = client.post("/api/team", json={"person": "flor", "yellow_hours": 20, "red_hours": 10})
    assert res.status_code == 400


def test_edit_team_member_endpoint(client):
    client.post("/api/team", json={"person": "flor"})

    res = client.put("/api/team/flor", json={"slack_user_id": "U0000099"})

    assert res.status_code == 200
    team = {m["person"]: m for m in client.get("/api/team").get_json()}
    assert team["flor"]["slack_user_id"] == "U0000099"


def test_edit_team_member_unknown_person(client):
    res = client.put("/api/team/nobody", json={"slack_user_id": "U0000099"})
    assert res.status_code == 404


def test_delete_team_member_endpoint(client):
    client.post("/api/team", json={"person": "flor"})

    res = client.delete("/api/team/flor")

    assert res.status_code == 200
    team = {m["person"] for m in client.get("/api/team").get_json()}
    assert "flor" not in team


def test_delete_team_member_unknown_person(client):
    res = client.delete("/api/team/nobody")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Workflow settings
# ---------------------------------------------------------------------------

def test_get_workflow_settings_endpoint(client):
    res = client.get("/api/workflow-settings")
    body = res.get_json()

    assert res.status_code == 200
    ids = {w["workflow_id"] for w in body}
    assert ids == {"fika-sync", "meeting-debt", "onboarding-automator", "budget-guardian"}


def test_set_workflow_enabled_endpoint(client):
    res = client.post("/api/workflow-settings/meeting-debt", json={"enabled": True})

    assert res.status_code == 200
    assert res.get_json() == {"workflow_id": "meeting-debt", "enabled": True}

    settings = {w["workflow_id"]: w for w in client.get("/api/workflow-settings").get_json()}
    assert settings["meeting-debt"]["enabled"] is True


def test_set_workflow_enabled_requires_body_field(client):
    res = client.post("/api/workflow-settings/meeting-debt", json={})
    assert res.status_code == 400


def test_set_workflow_enabled_unknown_workflow(client):
    res = client.post("/api/workflow-settings/does-not-exist", json={"enabled": True})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Notification settings + publish now
# ---------------------------------------------------------------------------

def test_get_notification_settings_endpoint(client):
    res = client.get("/api/notification-settings")
    assert res.status_code == 200
    assert res.get_json()["sync_frequency_minutes"] == 0


def test_save_notification_settings_endpoint(client):
    res = client.post("/api/notification-settings", json={
        "slack_channel": "#fika-sync", "sync_frequency_minutes": 60, "auto_publish_on_sync": True,
    })

    assert res.status_code == 200
    body = res.get_json()
    assert body["slack_channel"] == "#fika-sync"
    assert body["sync_frequency_minutes"] == 60
    assert body["auto_publish_on_sync"] is True


def test_save_notification_settings_rejects_negative_frequency(client):
    res = client.post("/api/notification-settings", json={"sync_frequency_minutes": -10})
    assert res.status_code == 400


def test_publish_now_fails_without_slack_connected(client):
    res = client.post("/api/publish-now")
    assert res.status_code == 409
    assert "Slack isn't connected" in res.get_json()["error"]


def test_publish_now_fails_without_channel_configured(client):
    import models
    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")

    res = client.post("/api/publish-now")

    assert res.status_code == 409
    assert "Slack channel" in res.get_json()["error"]


def test_publish_now_succeeds_with_mocked_slack(client):
    import models
    from unittest.mock import MagicMock, patch

    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    client.post("/api/notification-settings", json={"slack_channel": "#fika-sync-test"})
    client.get("/api/metrics")  # ensures hours are calculated for the week

    fake_slack = MagicMock()
    fake_slack.SlackClient = lambda bot_token: MagicMock(bot_token=bot_token)
    fake_slack.build_summary_blocks = MagicMock(return_value=[{"type": "section"}])
    fake_slack.post_message = MagicMock(return_value={"ok": True, "ts": "12345.6789"})

    with patch("provider_modules.load_slack", return_value=fake_slack):
        res = client.post("/api/publish-now")

    assert res.status_code == 200
    body = res.get_json()
    assert body["channel"] == "#fika-sync-test"
    assert body["response"]["ok"] is True
    fake_slack.post_message.assert_called_once()


# ---------------------------------------------------------------------------
# PER-PERSON calendar — "Connect my calendar" on each Team row
# ---------------------------------------------------------------------------

def test_api_team_includes_gcal_connected_flag(client):
    import models

    team = client.get("/api/team").get_json()
    assert all(m["gcal_connected"] is False for m in team)  # nobody connected yet

    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")
    team = client.get("/api/team").get_json()
    connected = {m["person"]: m["gcal_connected"] for m in team}
    assert connected["ana"] is True
    assert connected["beto"] is False


def test_oauth_start_for_person_rejects_unknown_person(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    res = client.get("/oauth/google/start/nobody-on-the-team")

    assert res.status_code == 404


def test_oauth_start_for_person_redirects_with_state(client, monkeypatch):
    import models

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    res = client.get("/oauth/google/start/ana")

    assert res.status_code == 302
    assert "accounts.google.com" in res.headers["Location"]

    import urllib.parse
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(res.headers["Location"]).query)
    state = qs["state"][0]
    # the same fixed redirect_uri as the app-level flow, not one per person
    assert qs["redirect_uri"][0].endswith("/oauth/google/callback")

    # the state actually ended up associated with 'ana' — confirmed by
    # consuming it directly (this also deletes it, simulating the real callback)
    state_info = models.consume_oauth_state(state)
    assert state_info == {"provider": "google", "person": "ana"}


def test_oauth_callback_for_person_saves_person_connection_not_app_level(client, monkeypatch):
    import models
    from unittest.mock import patch

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    state = models.create_oauth_state("google", person="ana")

    with patch("oauth_service.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {
            "access_token": "ya29.ana", "refresh_token": "1//ana-refresh",
            "token_type": "Bearer", "scope": "calendar",
        }
        res = client.get(f"/oauth/google/callback?code=fakecode&state={state}")

    assert res.status_code == 302
    assert "oauth_connected=google_calendar:ana" in res.headers["Location"]

    # Guardado en person_oauth_connections, NO en la tabla app-level
    person_connection = models.get_person_oauth_connection("ana", "google")
    assert person_connection["refresh_token"] == "1//ana-refresh"
    assert models.get_oauth_connection("google") is None  # app-level is still empty


def test_oauth_callback_two_people_get_independent_connections(client, monkeypatch):
    import models
    from unittest.mock import patch

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")

    for person, token in [("ana", "ya29.ana"), ("beto", "ya29.beto")]:
        state = models.create_oauth_state("google", person=person)
        with patch("oauth_service.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json.return_value = {
                "access_token": token, "refresh_token": f"1//{person}-refresh", "token_type": "Bearer",
            }
            client.get(f"/oauth/google/callback?code=fake&state={state}")

    assert models.get_person_oauth_connection("ana", "google")["access_token"] == "ya29.ana"
    assert models.get_person_oauth_connection("beto", "google")["access_token"] == "ya29.beto"


def test_oauth_disconnect_for_person(client):
    import models

    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")

    res = client.post("/oauth/google/disconnect/ana")

    assert res.status_code == 200
    assert res.get_json() == {"disconnected": "google_calendar", "person": "ana"}
    assert models.get_person_oauth_connection("ana", "google") is None


def test_oauth_disconnect_for_person_does_not_affect_others(client):
    import models

    models.save_person_oauth_connection("ana", "google", access_token="ya29.ana")
    models.save_person_oauth_connection("beto", "google", access_token="ya29.beto")

    client.post("/oauth/google/disconnect/ana")

    assert models.get_person_oauth_connection("ana", "google") is None
    assert models.get_person_oauth_connection("beto", "google") is not None


# ---------------------------------------------------------------------------
# Per-person Cal.com — same spirit as the Google tests above,
# but without OAuth: the key is pasted directly instead of redirecting
# to a consent screen (Cal.com doesn't offer OAuth for personal/free
# accounts, see fika-sync/gui/README.md).
# ---------------------------------------------------------------------------

def test_calcom_connect_for_person_rejects_unknown_person(client):
    res = client.post("/api/calcom/connect/nobody-on-the-team", json={"api_key": "cal_test123"})
    assert res.status_code == 404


def test_calcom_connect_for_person_rejects_missing_api_key(client):
    res = client.post("/api/calcom/connect/ana", json={})
    assert res.status_code == 400
    assert "api_key" in res.get_json()["error"]


def test_calcom_connect_for_person_rejects_malformed_key(client):
    res = client.post("/api/calcom/connect/ana", json={"api_key": "not-a-real-key"})
    assert res.status_code == 400
    assert "cal_" in res.get_json()["error"]


def test_calcom_connect_for_person_saves_key(client):
    import models
    from unittest.mock import patch

    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        res = client.post("/api/calcom/connect/ana", json={"api_key": "cal_ana_test_key"})

    assert res.status_code == 200
    assert res.get_json() == {"connected": "calcom", "person": "ana"}
    assert models.get_person_api_key("ana", "calcom")["api_key"] == "cal_ana_test_key"


def test_calcom_connect_for_person_rejects_key_that_fails_the_real_test_call(client):
    """Mirror of the app-level test: a key with the right prefix that
    Cal.com rejects shouldn't be saved here either."""
    import models
    from unittest.mock import patch

    fake = type("FakeCalcom", (), {})()
    fake.CalComClient = type("FakeClient", (), {"__init__": lambda self, api_key=None: None})

    def boom(client, status=None):
        raise RuntimeError("401 Unauthorized")
    fake.list_bookings = boom

    with patch("provider_modules.load_calcom_pro", return_value=fake):
        res = client.post("/api/calcom/connect/ana", json={"api_key": "cal_test_but_invalid"})

    assert res.status_code == 400
    assert models.get_person_api_key("ana", "calcom") is None


def test_calcom_connect_for_person_does_not_touch_app_level_connection(client):
    """The central case: ana's personal key goes to person_api_keys,
    NEVER to the oauth_connections table shared by the whole app."""
    import models
    from unittest.mock import patch

    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        client.post("/api/calcom/connect/ana", json={"api_key": "cal_ana_test_key"})

    assert models.get_oauth_connection("calcom") is None


def test_calcom_connect_for_two_people_are_independent(client):
    import models
    from unittest.mock import patch

    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        client.post("/api/calcom/connect/ana", json={"api_key": "cal_ana_key"})
        client.post("/api/calcom/connect/beto", json={"api_key": "cal_beto_key"})

    assert models.get_person_api_key("ana", "calcom")["api_key"] == "cal_ana_key"
    assert models.get_person_api_key("beto", "calcom")["api_key"] == "cal_beto_key"


def test_calcom_connect_for_person_rejects_when_google_already_connected(client):
    """The central mutual-exclusion case: if ana already has Google
    Calendar connected, she can't also connect Cal.com — it would add
    the same meeting twice (Cal.com usually writes it to the person's
    Google Calendar too)."""
    import models

    models.save_person_oauth_connection(
        "ana", "google", access_token="ya29.ana", refresh_token="1//ana-refresh",
    )

    res = client.post("/api/calcom/connect/ana", json={"api_key": "cal_ana_key"})

    assert res.status_code == 409
    assert "Google Calendar" in res.get_json()["error"]
    # Not saved — the rejection happened before touching the database
    assert models.get_person_api_key("ana", "calcom") is None


def test_calcom_connect_for_person_allowed_after_disconnecting_google(client):
    """Confirms the exclusion is dynamic, not a permanent lock:
    once Google is disconnected, Cal.com can be connected normally."""
    import models
    from unittest.mock import patch

    models.save_person_oauth_connection(
        "ana", "google", access_token="ya29.ana", refresh_token="1//ana-refresh",
    )
    models.delete_person_oauth_connection("ana", "google")

    with patch("provider_modules.load_calcom_pro", return_value=_fake_calcom_actions_ok()):
        res = client.post("/api/calcom/connect/ana", json={"api_key": "cal_ana_key"})

    assert res.status_code == 200
    assert models.get_person_api_key("ana", "calcom")["api_key"] == "cal_ana_key"


def test_oauth_start_for_person_rejects_when_calcom_already_connected(client, monkeypatch):
    """Mirror of the previous test, from the Google side: if ana
    already has her Cal.com key connected, /oauth/google/start/ana
    should not send her to Google — it redirects back to index with
    oauth_error instead of a JSON, because this endpoint is an
    <a href>, not a fetch."""
    import models

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    models.save_person_api_key("ana", "calcom", "cal_ana_key")

    res = client.get("/oauth/google/start/ana")

    assert res.status_code == 302
    assert "accounts.google.com" not in res.headers["Location"]
    assert "oauth_error=google:already_connected_calcom:ana" in res.headers["Location"]


def test_calcom_disconnect_for_person(client):
    import models

    models.save_person_api_key("ana", "calcom", "cal_ana_key")

    res = client.post("/api/calcom/disconnect/ana")

    assert res.status_code == 200
    assert res.get_json() == {"disconnected": "calcom", "person": "ana"}
    assert models.get_person_api_key("ana", "calcom") is None


def test_calcom_disconnect_for_person_does_not_affect_others(client):
    import models

    models.save_person_api_key("ana", "calcom", "cal_ana_key")
    models.save_person_api_key("beto", "calcom", "cal_beto_key")

    client.post("/api/calcom/disconnect/ana")

    assert models.get_person_api_key("ana", "calcom") is None
    assert models.get_person_api_key("beto", "calcom") is not None


def test_get_team_reports_calcom_connected_per_person(client):
    import models

    models.save_person_api_key("ana", "calcom", "cal_ana_key")

    res = client.get("/api/team")
    team = res.get_json()

    by_person = {m["person"]: m for m in team}
    assert by_person["ana"]["calcom_connected"] is True
    assert by_person["beto"]["calcom_connected"] is False


# ---------------------------------------------------------------------------
# Personal Slack DMs — use the shared app-level bot token,
# but the RECIPIENT is per person (slack_user_id from each row in
# Team). See sync_service.send_personal_dm_notifications.
# ---------------------------------------------------------------------------

def test_send_personal_dms_fails_without_slack_connected(client):
    res = client.post("/api/notifications/send-personal-dms")
    assert res.status_code == 409
    assert "Slack isn't connected" in res.get_json()["error"]


def test_send_personal_dms_succeeds_with_mocked_slack(client):
    import models
    from unittest.mock import MagicMock, patch

    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    models.update_team_member("ana", slack_user_id="U0000001")
    models.record_meeting_hours("ana", "2026-08-31", 22.0, "demo")  # red, with the default 20h

    fake_slack = MagicMock()
    fake_slack.SlackClient = lambda bot_token: MagicMock(bot_token=bot_token)
    fake_slack.post_message = MagicMock(return_value={"ok": True})

    with patch("provider_modules.load_slack", return_value=fake_slack), \
         patch("sync_service.current_week_start", return_value="2026-08-31"):
        res = client.post("/api/notifications/send-personal-dms")

    assert res.status_code == 200
    results = res.get_json()["results"]
    assert results["ana"] == "sent"
    # the DM was sent to ana's slack_user_id, not to a channel
    call_args = fake_slack.post_message.call_args
    assert call_args[0][1] == "U0000001"


def test_send_personal_dms_skips_people_without_slack_user_id(client):
    import models
    from unittest.mock import MagicMock, patch

    models.save_oauth_connection("slack", access_token="xoxb-fake", token_type="bot")
    models.update_team_member("ana", slack_user_id="")  # the seed provides one, we clear it on purpose
    models.record_meeting_hours("ana", "2026-08-31", 22.0, "demo")

    fake_slack = MagicMock()
    fake_slack.SlackClient = lambda bot_token: MagicMock(bot_token=bot_token)
    fake_slack.post_message = MagicMock(return_value={"ok": True})

    with patch("provider_modules.load_slack", return_value=fake_slack), \
         patch("sync_service.current_week_start", return_value="2026-08-31"):
        res = client.post("/api/notifications/send-personal-dms")

    results = res.get_json()["results"]
    assert results["ana"] == "skipped_no_slack_id"
    fake_slack.post_message.assert_not_called()


def test_notification_settings_accepts_personal_dms_enabled(client):
    res = client.post("/api/notification-settings", json={"personal_dms_enabled": True})
    assert res.status_code == 200
    assert res.get_json()["personal_dms_enabled"] is True

    res = client.get("/api/notification-settings")
    assert res.get_json()["personal_dms_enabled"] is True


# ---------------------------------------------------------------------------
# App configuration (Client ID/Secret) from the GUI — the one-time
# setup done by whoever administers the installation, without editing
# .env or restarting the server.
# ---------------------------------------------------------------------------

def test_get_app_credentials_reports_not_configured_by_default(client):
    res = client.get("/api/admin/app-credentials")
    body = res.get_json()

    assert body["google"] == {"configured": False, "source": None, "client_id_preview": None}
    assert body["slack"] == {"configured": False, "source": None, "client_id_preview": None}


def test_get_app_credentials_reports_env_manual_source(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")

    body = client.get("/api/admin/app-credentials").get_json()

    assert body["google"]["configured"] is True
    assert body["google"]["source"] == "env_manual"
    assert body["google"]["client_id_preview"] == "env-id"


def test_save_app_credentials_rejects_missing_fields(client):
    res = client.post("/api/admin/app-credentials/google", json={"client_id": "only-id"})
    assert res.status_code == 400


def test_save_app_credentials_rejects_unknown_provider(client):
    res = client.post("/api/admin/app-credentials/nope", json={"client_id": "x", "client_secret": "y"})
    assert res.status_code == 404


def test_save_app_credentials_persists_and_reports_guided_source(client):
    res = client.post(
        "/api/admin/app-credentials/google",
        json={"client_id": "guided-id", "client_secret": "guided-secret"},
    )
    assert res.status_code == 200
    assert res.get_json() == {"saved": "google"}

    body = client.get("/api/admin/app-credentials").get_json()
    assert body["google"]["configured"] is True
    assert body["google"]["source"] == "guided"
    assert body["google"]["client_id_preview"] == "guided-id"


def test_save_app_credentials_never_returns_the_secret(client):
    client.post(
        "/api/admin/app-credentials/google",
        json={"client_id": "guided-id", "client_secret": "super-secret-value"},
    )

    body = client.get("/api/admin/app-credentials").get_json()

    assert "super-secret-value" not in str(body)


def test_save_app_credentials_prefers_guided_over_env_in_status(client, monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "env-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "env-secret")
    client.post("/api/admin/app-credentials/slack", json={"client_id": "guided-id", "client_secret": "guided-secret"})

    body = client.get("/api/admin/app-credentials").get_json()

    assert body["slack"]["source"] == "guided"
    assert body["slack"]["client_id_preview"] == "guided-id"


def test_reset_app_credentials(client):
    client.post("/api/admin/app-credentials/google", json={"client_id": "guided-id", "client_secret": "guided-secret"})

    res = client.post("/api/admin/app-credentials/google/reset")

    assert res.status_code == 200
    assert res.get_json() == {"reset": "google"}
    assert client.get("/api/admin/app-credentials").get_json()["google"]["configured"] is False


def test_reset_app_credentials_falls_back_to_env_var(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    client.post("/api/admin/app-credentials/google", json={"client_id": "guided-id", "client_secret": "guided-secret"})

    client.post("/api/admin/app-credentials/google/reset")

    body = client.get("/api/admin/app-credentials").get_json()
    assert body["google"]["configured"] is True
    assert body["google"]["source"] == "env_manual"


def test_reset_app_credentials_rejects_unknown_provider(client):
    res = client.post("/api/admin/app-credentials/nope/reset")
    assert res.status_code == 404


def test_api_status_reflects_guided_app_credentials(client):
    """The bug this fixes: /api/status.oauth.app_configured used to
    only look at environment variables — it didn't reflect credentials
    saved from the GUI."""
    client.post("/api/admin/app-credentials/slack", json={"client_id": "guided-id", "client_secret": "guided-secret"})

    status = client.get("/api/status").get_json()

    assert status["oauth"]["app_configured"]["slack"] is True
    assert status["oauth"]["app_configured"]["google"] is False


def test_oauth_start_uses_guided_app_credentials_when_no_env_var(client):
    """With the credentials saved from the GUI (with no environment
    variable set), the 'Connect Google' button on the Connections
    tab should work just the same."""
    client.post("/api/admin/app-credentials/google", json={"client_id": "guided-id", "client_secret": "guided-secret"})

    res = client.get("/oauth/google/start")

    assert res.status_code == 302
    assert "client_id=guided-id" in res.headers["Location"]


# ---------------------------------------------------------------------------
# Slack: pasting a Bot User OAuth Token by hand (alternative to the browser
# redirect — needed when Slack requires PKCE because the redirect_uri is
# 127.0.0.1/localhost without HTTPS, see the GUI's README).
# ---------------------------------------------------------------------------

def test_slack_connect_token_rejects_missing_token(client):
    res = client.post("/api/slack/connect-token", json={})
    assert res.status_code == 400


def test_slack_connect_token_rejects_token_with_wrong_prefix(client):
    res = client.post("/api/slack/connect-token", json={"bot_token": "does-not-start-with-xoxb"})
    assert res.status_code == 400
    assert "xoxb-" in res.get_json()["error"]


def _fake_auth_test_response(ok=True, **body):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": ok, **body}
    return FakeResponse()


def test_slack_connect_token_saves_token_and_reflects_in_status(client, monkeypatch):
    from unittest.mock import patch
    import models

    fake_response = _fake_auth_test_response(
        ok=True, team="fiction", team_id="T0BU27DJSA1", bot_id="B123", user_id="U123",
    )
    with patch("oauth_service.requests.post", return_value=fake_response) as mock_post:
        res = client.post("/api/slack/connect-token", json={"bot_token": "xoxb-fake-token-123"})

    assert res.status_code == 200
    assert res.get_json()["connected"] == "slack"
    assert res.get_json()["team_name"] == "fiction"

    # Validated against auth.test (Authorization: Bearer <token>), not
    # against the normal OAuth exchange — no redirect_uri in the call.
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer xoxb-fake-token-123"

    connection = models.get_oauth_connection("slack")
    assert connection["access_token"] == "xoxb-fake-token-123"
    assert connection["token_type"] == "bot"
    assert connection["validated_at"]

    status_body = client.get("/api/status").get_json()
    assert status_body["oauth"]["connected"]["slack"] is True


def test_slack_connect_token_rejects_token_that_slack_rejects(client):
    from unittest.mock import patch

    fake_response = _fake_auth_test_response(ok=False, error="invalid_auth")
    with patch("oauth_service.requests.post", return_value=fake_response):
        res = client.post("/api/slack/connect-token", json={"bot_token": "xoxb-revoked"})

    assert res.status_code == 400
    assert "invalid_auth" in res.get_json()["error"]

    import models
    assert models.get_oauth_connection("slack") is None


def test_slack_connect_token_strips_whitespace(client):
    from unittest.mock import patch

    fake_response = _fake_auth_test_response(ok=True, team="fiction", team_id="T1", bot_id="B1")
    with patch("oauth_service.requests.post", return_value=fake_response):
        client.post("/api/slack/connect-token", json={"bot_token": "  xoxb-with-spaces  "})

    import models
    connection = models.get_oauth_connection("slack")
    assert connection["access_token"] == "xoxb-with-spaces"

