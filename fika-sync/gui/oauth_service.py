"""
oauth_service.py — OAuth flow so an end user can connect Google
(Calendar + Sheets) and Slack with one click, instead of generating
credentials by hand and pasting them into environment variables.

**App credentials, now configurable from the GUI.** The app still
needs a Client ID/Secret per provider
(`GOOGLE_CLIENT_ID`/`SECRET`, `SLACK_CLIENT_ID`/`SECRET`) — they
identify Fika Sync to Google/Slack, are the same for every user, and
are configured by whoever administers the installation, not each
team member. This used to require editing `.env` and restarting the
server; now `_resolve_app_credentials` prioritizes what's saved in
`models.app_oauth_credentials` (pasted from the Connections tab →
"App configuration") over environment variables — `.env` still works
as a fallback for whoever prefers that route.

What this module adds on top is the flow for **each user** to
authorize access to **their own** account with one click, without
generating a refresh token by hand via the OAuth Playground (which
was the only path that existed before this session).

**Not tested against real Google/Slack** — same reason as the rest of
the repo: this environment has no network egress to those domains.
See `VALIDATION.md` at the repo root.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlencode

import requests

import models

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
# A single combined scope for Calendar + Sheets — one consent click
# covers both modules (gcal and sheets).
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/spreadsheets"

SLACK_AUTH_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_BOT_SCOPES = "chat:write"

# provider -> (client_id env var name, client_secret env var name)
_ENV_VAR_NAMES = {
    "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "slack": ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"),
}


class OAuthConfigError(Exception):
    """The app's server-side credentials (Client ID/Secret) are missing."""


def _resolve_app_credentials(provider: str, require_secret: bool = True) -> dict:
    """Resolves a provider's Client ID/Secret, prioritizing what's
    saved from the GUI (`app_oauth_credentials`) over environment
    variables — same priority order as
    `sync_service._build_calcom_client` (guided > env var).

    Args:
        provider: "google" | "slack".
        require_secret: False for authorization URLs (they only need
            the client_id, not the secret) — so the secret isn't
            required just to build a link.

    Returns:
        dict {"client_id": str, "client_secret": str|None}.

    Raises:
        OAuthConfigError: if there's no client_id (or client_secret,
            if require_secret) available through either path.
    """
    env_id_name, env_secret_name = _ENV_VAR_NAMES[provider]
    saved = models.get_app_oauth_credentials(provider)

    if saved:
        client_id = saved["client_id"]
        client_secret = saved["client_secret"]
    else:
        client_id = os.environ.get(env_id_name)
        client_secret = os.environ.get(env_secret_name)

    missing = []
    if not client_id:
        missing.append(f"{provider} client_id (guided in Connections, or {env_id_name})")
    if require_secret and not client_secret:
        missing.append(f"{provider} client_secret (guided in Connections, or {env_secret_name})")

    if missing:
        raise OAuthConfigError(
            "Missing app credentials (configured by whoever administers "
            "this installation, not each user, from the Connections tab → "
            "\"App configuration\"): " + "; ".join(missing)
        )

    return {"client_id": client_id, "client_secret": client_secret}


# ---------------------------------------------------------------------------
# Google (Calendar + Sheets)
# ---------------------------------------------------------------------------

def build_google_authorize_url(redirect_uri: str, state: str) -> str:
    """Builds the URL to redirect the user to so they can authorize.

    `prompt=consent` forces Google to ALWAYS send a refresh_token, not
    just the first time the person consents — without this, if
    someone had already connected before (even with a different app),
    Google may omit the refresh_token from the exchange and we'd have
    no way to renew the access_token afterward.
    """
    creds = _resolve_app_credentials("google", require_secret=False)
    params = {
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Exchanges the authorization code for tokens.

    Args:
        code: the "code" parameter Google sent to redirect_uri.
        redirect_uri: has to be EXACTLY the same one used in
            build_google_authorize_url, or Google rejects the exchange.

    Returns:
        dict with at least "access_token"; "refresh_token" should
        always come back thanks to prompt=consent, but it's not
        guaranteed by the documentation — the caller has to handle it
        being missing.

    Raises:
        OAuthConfigError: if the app credentials are missing.
        requests.HTTPError: if Google returns an error (invalid/
            expired code, redirect_uri mismatch, etc.).
    """
    creds = _resolve_app_credentials("google")
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def build_slack_authorize_url(redirect_uri: str, state: str) -> str:
    creds = _resolve_app_credentials("slack", require_secret=False)
    params = {
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "scope": SLACK_BOT_SCOPES,
        "state": state,
    }
    return f"{SLACK_AUTH_URL}?{urlencode(params)}"


def exchange_slack_code(code: str, redirect_uri: str) -> dict:
    """Exchanges the code for a bot token (xoxb-...).

    Unlike Google, Slack's bot token doesn't expire by default (no
    refresh_token needed) — that's why `save_oauth_connection` for
    "slack" doesn't save a refresh_token.

    Returns:
        dict with "ok", "access_token" (the bot token), "team"
        ({"id", "name"}), "bot_user_id", etc.

    Raises:
        OAuthConfigError: if app credentials are missing, or if Slack
            returns `"ok": false` (for example, invalid/expired code
            — Slack responds 200 with ok:false, not an HTTP error
            status, so the body has to be checked).
    """
    creds = _resolve_app_credentials("slack")
    response = requests.post(
        SLACK_TOKEN_URL,
        data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok", False):
        raise OAuthConfigError(f"Slack rejected the exchange: {body.get('error', 'unknown_error')}")
    return body


SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"


def validate_slack_bot_token(bot_token: str) -> dict:
    """Confirms a hand-pasted Bot User OAuth Token (xoxb-...) is
    valid, by calling auth.test — the same method Slack's "Install
    to workspace" uses, without going through the redirect/PKCE
    flow.

    Used for the alternative admin path: generating the token from
    api.slack.com/apps -> OAuth & Permissions -> "Install to
    workspace" (no redirect_uri, no HTTPS) and pasting it here,
    instead of connecting with one click from the browser.

    Returns:
        dict with "team_id", "team_name", "bot_user_id" — the same
        thing exchange_slack_code() extracts from the normal OAuth
        exchange, so save_oauth_connection() can save the same
        "extra" for both paths.

    Raises:
        OAuthConfigError: if the token doesn't have the expected
            format or Slack rejects it (revoked, wrong token type,
            etc.).
    """
    bot_token = (bot_token or "").strip()
    if not bot_token.startswith("xoxb-"):
        raise OAuthConfigError(
            "That doesn't look like a Slack Bot User OAuth Token — it has to start with 'xoxb-'. "
            "You get one at api.slack.com/apps -> your app -> OAuth & Permissions -> 'Install to workspace'."
        )
    response = requests.post(
        SLACK_AUTH_TEST_URL,
        headers={"Authorization": f"Bearer {bot_token}"},
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok", False):
        raise OAuthConfigError(f"Slack rejected the token: {body.get('error', 'unknown_error')}")
    return {
        "team_id": body.get("team_id"),
        "team_name": body.get("team"),
        "bot_user_id": body.get("bot_id") or body.get("user_id"),
    }
