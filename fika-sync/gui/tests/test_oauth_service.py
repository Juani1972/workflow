import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse, parse_qs

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
import oauth_service


def mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# build_*_authorize_url — pure logic, no network
# ---------------------------------------------------------------------------

def test_build_google_authorize_url_includes_required_params(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-client-id")

    url = oauth_service.build_google_authorize_url("https://app.example.com/oauth/google/callback", "state123")

    parsed = urlparse(url)
    assert parsed.netloc == "accounts.google.com"
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["my-client-id"]
    assert params["redirect_uri"] == ["https://app.example.com/oauth/google/callback"]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["state"] == ["state123"]
    assert "calendar" in params["scope"][0]
    assert "spreadsheets" in params["scope"][0]


def test_build_google_authorize_url_requires_client_id(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)

    with pytest.raises(oauth_service.OAuthConfigError):
        oauth_service.build_google_authorize_url("https://example.com/callback", "state123")


def test_build_slack_authorize_url_includes_required_params(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "my-slack-id")

    url = oauth_service.build_slack_authorize_url("https://app.example.com/oauth/slack/callback", "state456")

    parsed = urlparse(url)
    assert parsed.netloc == "slack.com"
    params = parse_qs(parsed.query)
    assert params["client_id"] == ["my-slack-id"]
    assert params["redirect_uri"] == ["https://app.example.com/oauth/slack/callback"]
    assert params["scope"] == ["chat:write"]
    assert params["state"] == ["state456"]


def test_build_slack_authorize_url_requires_client_id(monkeypatch):
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)

    with pytest.raises(oauth_service.OAuthConfigError):
        oauth_service.build_slack_authorize_url("https://example.com/callback", "state456")


# ---------------------------------------------------------------------------
# exchange_*_code — mockea la llamada de red
# ---------------------------------------------------------------------------

@patch("oauth_service.requests.post")
def test_exchange_google_code_returns_tokens(mock_post, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "my-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "my-secret")
    mock_post.return_value = mock_response(json_data={
        "access_token": "ya29.abc", "refresh_token": "1//xyz",
        "token_type": "Bearer", "scope": "calendar spreadsheets", "expires_in": 3599,
    })

    result = oauth_service.exchange_google_code("auth-code-123", "https://app.example.com/callback")

    assert result["access_token"] == "ya29.abc"
    assert result["refresh_token"] == "1//xyz"
    sent_data = mock_post.call_args.kwargs["data"]
    assert sent_data["code"] == "auth-code-123"
    assert sent_data["grant_type"] == "authorization_code"
    assert sent_data["redirect_uri"] == "https://app.example.com/callback"


def test_exchange_google_code_requires_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    with pytest.raises(oauth_service.OAuthConfigError):
        oauth_service.exchange_google_code("code", "https://example.com/callback")


@patch("oauth_service.requests.post")
def test_exchange_slack_code_returns_bot_token(mock_post, monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "my-slack-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "my-slack-secret")
    mock_post.return_value = mock_response(json_data={
        "ok": True, "access_token": "xoxb-fake",
        "team": {"id": "T123", "name": "Equipo de prueba"}, "bot_user_id": "U999",
    })

    result = oauth_service.exchange_slack_code("auth-code-456", "https://app.example.com/oauth/slack/callback")

    assert result["access_token"] == "xoxb-fake"
    assert result["team"]["id"] == "T123"


@patch("oauth_service.requests.post")
def test_exchange_slack_code_raises_on_ok_false(mock_post, monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "my-slack-id")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "my-slack-secret")
    mock_post.return_value = mock_response(json_data={"ok": False, "error": "invalid_code"})

    with pytest.raises(oauth_service.OAuthConfigError) as exc_info:
        oauth_service.exchange_slack_code("bad-code", "https://example.com/callback")

    assert "invalid_code" in str(exc_info.value)


def test_exchange_slack_code_requires_credentials(monkeypatch):
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
    monkeypatch.delenv("SLACK_CLIENT_SECRET", raising=False)

    with pytest.raises(oauth_service.OAuthConfigError):
        oauth_service.exchange_slack_code("code", "https://example.com/callback")


# ---------------------------------------------------------------------------
# _resolve_app_credentials — app credentials configured from the GUI
# (models.app_oauth_credentials) take priority over environment
# variables, same pattern as sync_service._build_calcom_client.
# ---------------------------------------------------------------------------

def test_resolve_app_credentials_uses_env_var_when_nothing_saved(monkeypatch):
    models.init_db()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")

    creds = oauth_service._resolve_app_credentials("google")

    assert creds == {"client_id": "env-client-id", "client_secret": "env-secret"}


def test_resolve_app_credentials_prefers_guided_over_env_var(monkeypatch):
    models.init_db()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    models.save_app_oauth_credentials("google", "guided-client-id", "guided-secret")

    creds = oauth_service._resolve_app_credentials("google")

    assert creds == {"client_id": "guided-client-id", "client_secret": "guided-secret"}


def test_resolve_app_credentials_works_with_only_guided_no_env_at_all(monkeypatch):
    models.init_db()
    monkeypatch.delenv("SLACK_CLIENT_ID", raising=False)
    monkeypatch.delenv("SLACK_CLIENT_SECRET", raising=False)
    models.save_app_oauth_credentials("slack", "guided-slack-id", "guided-slack-secret")

    creds = oauth_service._resolve_app_credentials("slack")

    assert creds == {"client_id": "guided-slack-id", "client_secret": "guided-slack-secret"}


def test_resolve_app_credentials_raises_when_neither_source_available(monkeypatch):
    models.init_db()
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    with pytest.raises(oauth_service.OAuthConfigError):
        oauth_service._resolve_app_credentials("google")


def test_resolve_app_credentials_require_secret_false_only_needs_client_id(monkeypatch):
    models.init_db()
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client-id")

    creds = oauth_service._resolve_app_credentials("google", require_secret=False)

    assert creds["client_id"] == "env-client-id"


def test_build_google_authorize_url_uses_guided_credentials(monkeypatch):
    """The authorization link uses the client_id saved from the GUI,
    not the one from the environment variable, when both exist."""
    models.init_db()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client-id")
    models.save_app_oauth_credentials("google", "guided-client-id", "guided-secret")

    url = oauth_service.build_google_authorize_url("https://app.example.com/oauth/google/callback", "state123")

    params = parse_qs(urlparse(url).query)
    assert params["client_id"] == ["guided-client-id"]


@patch("oauth_service.requests.post")
def test_exchange_google_code_uses_guided_credentials(mock_post, monkeypatch):
    models.init_db()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    models.save_app_oauth_credentials("google", "guided-client-id", "guided-secret")
    mock_post.return_value = mock_response(json_data={"access_token": "ya29.fake", "refresh_token": "1//fake"})

    oauth_service.exchange_google_code("code", "https://app.example.com/oauth/google/callback")

    sent_data = mock_post.call_args.kwargs["data"]
    assert sent_data["client_id"] == "guided-client-id"
    assert sent_data["client_secret"] == "guided-secret"

