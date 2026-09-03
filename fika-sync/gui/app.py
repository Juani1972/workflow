"""
Fika Sync GUI — real Flask backend.

Replaces the two original static HTML files (`fika-sync/gui/*.html`,
mockups with no data connection) with an app that has:

- Real persistence in SQLite (`models.py`) — data survives a page
  reload, unlike the original mockup.
- Team health classification using the REAL `team-health-analyzer`
  logic (`classify_team_health`, `summarize_team_report`,
  `update_threshold`), not a JavaScript reimplementation.
- Sync that tries real Cal.com + Google Calendar data if credentials
  are present, and falls back to demo data (marked as such, never
  hidden) if they aren't — see `sync_service.py`.
- **Connect Google/Slack with one click** (`/oauth/<provider>/start`,
  `oauth_service.py`) — so an end user can authorize access to their
  account without having to generate a refresh token by hand. The
  application's own credentials (Client ID/Secret) still come from
  environment variables; what changes is that the user no longer
  needs to touch them.

What this is NOT: an implementation of the 3 level-3 workflows
(`meeting-debt`, `onboarding-automator`, `budget-guardian`) — those
live in `workflows/`, not here. Publishing to Slack
(`chat.postMessage`) isn't done by the GUI either — it's still the
workflow's responsibility; here only the account gets connected, it's
not used to publish.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Loads fika-sync/gui/.env if it exists, BEFORE reading any
# os.environ.get() below (here, in oauth_service.py and in
# sync_service.py). Without this, configuring GOOGLE_CLIENT_ID/SECRET
# (needed for ANY person to be able to connect their own calendar)
# would require exporting them by hand in the terminal before
# starting `python3 app.py` — with this, pasting them into the .env
# file once is enough (see fika-sync/gui/.env.example). It doesn't
# override variables already exported in the environment
# (override=False is load_dotenv's default).
load_dotenv(Path(__file__).resolve().parent / ".env")

from flask import Flask, jsonify, redirect, render_template, request, url_for

import models
import oauth_service
import provider_modules
import sync_service

th_actions = provider_modules.load_team_health_analyzer()
classify_team_health = th_actions.classify_team_health
summarize_team_report = th_actions.summarize_team_report

OAUTH_PROVIDERS = ("google", "slack")


def create_app() -> Flask:
    app = Flask(__name__)
    models.init_db()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def status():
        creds = sync_service.real_credentials_available()
        calcom_conn = models.get_oauth_connection("calcom")
        google_conn = models.get_oauth_connection("google")
        slack_conn = models.get_oauth_connection("slack")

        google_env_configured = all(
            os.environ.get(v) for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
        )
        slack_env_configured = bool(os.environ.get("SLACK_BOT_TOKEN"))
        calcom_env_configured = bool(os.environ.get("CALCOM_API_KEY"))

        def _connection_method(env_configured, connection, connected_label):
            if connection:
                return connected_label
            if env_configured:
                return "env_manual"
            return None

        # validated_against_real_account: unlike credentials_configured
        # (which only confirms that SOMETHING is saved, in the
        # expected format), this confirms those credentials have
        # already been tested against the real API/OAuth and worked —
        # not a promise for the future.
        #
        # - calcom: the app-level row has validated_at (calcom_connect
        #   tests it with list_bookings before saving) OR at least one
        #   person has their key saved (calcom_connect_for_person also
        #   tests it before saving — its mere existence in
        #   person_api_keys is already the proof).
        # - google_calendar: at least one person connected their
        #   calendar (person_oauth_connections) — that row only exists
        #   after a successful code-for-token exchange with Google, so
        #   the calendar connection itself is its own proof, no
        #   separate call is needed.
        # - slack: the app-level row has validated_at (set in
        #   oauth_callback right when Slack confirms the token).
        #
        # Each provider's legacy environment variable (CALCOM_API_KEY,
        # GOOGLE_REFRESH_TOKEN, SLACK_BOT_TOKEN) NEVER counts here — it
        # loads when the process starts, without going through any of
        # these checks, so there's no honest way to know if it's still
        # valid.
        calcom_validated = bool(calcom_conn and calcom_conn.get("validated_at")) or \
            len(models.list_people_with_api_key("calcom")) > 0
        google_validated = len(models.list_connected_people("google")) > 0
        slack_validated = bool(slack_conn and slack_conn.get("validated_at"))

        return jsonify({
            "providers": {
                "calcom": {
                    "credentials_configured": creds["calcom"],
                    "validated_against_real_account": calcom_validated,
                    "connection_method": _connection_method(calcom_env_configured, calcom_conn, "guided_api_key"),
                },
                "google_calendar": {
                    "credentials_configured": creds["google_calendar"],
                    "validated_against_real_account": google_validated,
                    "connection_method": _connection_method(google_env_configured, google_conn, "oauth_connected"),
                },
                "slack": {
                    "credentials_configured": creds["slack"],
                    "validated_against_real_account": slack_validated,
                    "connection_method": _connection_method(slack_env_configured, slack_conn, "oauth_connected"),
                },
            },
            "oauth": {
                "app_configured": {
                    "google": _app_credentials_configured("google"),
                    "slack": _app_credentials_configured("slack"),
                },
                "connected": {
                    "calcom": calcom_conn is not None,
                    "google": google_conn is not None,
                    "slack": slack_conn is not None,
                },
            },
        })

    def _app_credentials_configured(provider: str) -> bool:
        """True if a Client ID + Secret are available for that
        provider, through EITHER of the two paths: saved from the
        GUI (app_oauth_credentials) or an environment variable — same
        priority order as oauth_service._resolve_app_credentials."""
        if models.get_app_oauth_credentials(provider):
            return True
        env_names = {
            "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
            "slack": ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"),
        }[provider]
        return all(os.environ.get(v) for v in env_names)

    @app.get("/api/admin/app-credentials")
    def get_app_credentials():
        """Status of the APPLICATION-level credentials per provider —
        NEVER returns the saved client_secret (not even masked), only
        whether something is configured and where it came from
        (guided from the GUI vs. environment variable) and a preview
        of the client_id (not a secret, useful to confirm which one
        ended up loaded without having to guess)."""
        result = {}
        for provider in OAUTH_PROVIDERS:
            saved = models.get_app_oauth_credentials(provider)
            env_id_name, env_secret_name = {
                "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
                "slack": ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"),
            }[provider]
            if saved:
                result[provider] = {
                    "configured": True, "source": "guided",
                    "client_id_preview": saved["client_id"],
                }
            elif os.environ.get(env_id_name) and os.environ.get(env_secret_name):
                result[provider] = {
                    "configured": True, "source": "env_manual",
                    "client_id_preview": os.environ.get(env_id_name),
                }
            else:
                result[provider] = {"configured": False, "source": None, "client_id_preview": None}
        return jsonify(result)

    @app.post("/api/admin/app-credentials/<provider>")
    def save_app_credentials(provider):
        """Saves a provider's app-level Client ID/Secret, pasted from
        the Connections tab → "App configuration" — the single step
        done by whoever administers the installation, replacing
        having to edit .env and restart the server.

        Body: {"client_id": str, "client_secret": str}"""
        if provider not in OAUTH_PROVIDERS:
            return jsonify({"error": f"Unknown provider: {provider}"}), 404

        body = request.get_json(force=True, silent=True) or {}
        client_id = (body.get("client_id") or "").strip()
        client_secret = (body.get("client_secret") or "").strip()

        if not client_id or not client_secret:
            return jsonify({"error": "client_id and client_secret are required."}), 400

        models.save_app_oauth_credentials(provider, client_id, client_secret)
        return jsonify({"saved": provider})

    @app.post("/api/admin/app-credentials/<provider>/reset")
    def reset_app_credentials(provider):
        """Deletes what was saved from the GUI for that provider — the
        app goes back to depending on the environment variable if
        it's set, or on nothing (the "Connect" buttons disappear) if
        not."""
        if provider not in OAUTH_PROVIDERS:
            return jsonify({"error": f"Unknown provider: {provider}"}), 404
        models.delete_app_oauth_credentials(provider)
        return jsonify({"reset": provider})

    def _validate_calcom_key(body: dict) -> tuple[str, str] | tuple[None, tuple]:
        """Validates the body of a Cal.com connection POST.

        Returns:
            (api_key, None) if valid.
            (None, (json_response, status_code)) if an error needs to
            be returned — so the caller can just do
            `key, err = _validate_calcom_key(body); if err: return err`.
        """
        api_key = (body.get("api_key") or "").strip()
        if not api_key:
            return None, (jsonify({"error": "api_key is missing from the body."}), 400)
        if not api_key.startswith("cal_"):
            # Cal.com prefixes its keys with "cal_" (test) or
            # "cal_live_" (production) — this doesn't validate that
            # the key is VALID, only that it has the expected shape,
            # to catch obvious copy-paste errors before saving it.
            return None, (jsonify({
                "error": "The Cal.com API key should start with 'cal_'. Check that you copied the full value."
            }), 400)
        return api_key, None

    @app.post("/api/calcom/connect")
    def calcom_connect():
        """'Guided' flow for Cal.com — not real OAuth (Cal.com doesn't
        offer it for personal/free accounts, see
        fika-sync/gui/README.md), but it avoids the person having to
        manually set an environment variable: paste the API key here,
        it gets saved in SQLite just like OAuth connections.

        This is the APP-LEVEL key (fallback/legacy, see
        sync_service._build_calcom_client): if nobody on the team
        connected their own personal key
        (/api/calcom/connect/<person>), the sync uses this one for the
        whole team — this only works well if it's a key from a
        "Team" Cal.com plan with visibility over everyone's bookings,
        not a free personal key.

        It's tested with a real call to list_bookings BEFORE saving —
        _validate_calcom_key only checks the "cal_" prefix, which
        caught obvious copy-paste errors but let through keys with the
        correct format that were still invalid (revoked, from another
        account, with typos in the middle). Without this, the first
        sign of a bad key would only show up on the next sync,
        silently — the user would see "connected" and trust data that
        was actually demo."""
        body = request.get_json(force=True, silent=True) or {}
        api_key, err = _validate_calcom_key(body)
        if err:
            return err

        calcom_actions = provider_modules.load_calcom_pro()
        try:
            calcom_actions.list_bookings(calcom_actions.CalComClient(api_key=api_key), status="upcoming")
        except Exception as exc:
            return jsonify({
                "error": (
                    f"The key didn't work against the real Cal.com API ({exc}). "
                    "Check that you copied it in full and that it's not revoked."
                )
            }), 400

        now = datetime.now(timezone.utc).isoformat()
        models.save_oauth_connection("calcom", access_token=api_key, token_type="api_key")
        models.mark_connection_validated("calcom", now)
        return jsonify({"connected": "calcom", "validated_at": now})

    @app.post("/api/calcom/disconnect")
    def calcom_disconnect():
        models.delete_oauth_connection("calcom")
        return jsonify({"disconnected": "calcom"})

    @app.post("/api/calcom/connect/<person>")
    def calcom_connect_for_person(person):
        """Connects the Cal.com API key of ONE specific person on the
        team — so each person sees their OWN bookings, instead of
        depending on a single account (with a paid Team plan) that can
        see the whole team's. Same spirit as
        /oauth/google/start/<person> for the calendar, but without
        OAuth: Cal.com doesn't offer it for free accounts, so this is
        also "paste the key", just in that person's row instead of the
        Connections panel.

        Mutual exclusion with Google Calendar: a person connects ONE
        of the two sources, not both. If they had both, the same
        meeting would arrive via Cal.com AND via Google Calendar
        (Cal.com usually writes its bookings into the person's Google
        Calendar) and calculate_meeting_load would count it twice — an
        incorrect data point, not just a redundant one. See the same
        validation mirrored in oauth_start_for_person.
        """
        if not any(m["person"] == person for m in models.get_team()):
            return jsonify({"error": f"'{person}' is not on the team."}), 404

        if person in models.list_connected_people("google"):
            return jsonify({
                "error": (
                    f"'{person}' already has Google Calendar connected. "
                    "Disconnect it first if you want to use Cal.com instead — "
                    "connecting both sources at once would double-count the hours."
                )
            }), 409

        body = request.get_json(force=True, silent=True) or {}
        api_key, err = _validate_calcom_key(body)
        if err:
            return err

        # Same real-call validation as the app-level calcom_connect()
        # — see that docstring. Here it's also what lets the mere
        # existence of a row in person_api_keys serve, on its own, as
        # proof that person is "validated" (same as
        # person_oauth_connections for Google): status() uses it that
        # way, without needing a per-person validated_at column.
        calcom_actions = provider_modules.load_calcom_pro()
        try:
            calcom_actions.list_bookings(calcom_actions.CalComClient(api_key=api_key), status="upcoming")
        except Exception as exc:
            return jsonify({
                "error": (
                    f"{person}'s key didn't work against the real Cal.com API ({exc}). "
                    "Check that you copied it in full and that it's not revoked."
                )
            }), 400

        models.save_person_api_key(person, "calcom", api_key)
        return jsonify({"connected": "calcom", "person": person})

    @app.post("/api/calcom/disconnect/<person>")
    def calcom_disconnect_for_person(person):
        models.delete_person_api_key(person, "calcom")
        return jsonify({"disconnected": "calcom", "person": person})

    @app.get("/oauth/<provider>/start")
    def oauth_start(provider):
        """Redirects the user to the provider's consent screen, at the
        APP level (Slack always; Google only for Sheets — for a
        person's calendar, see /oauth/google/start/<person> below).
        Cal.com has no endpoint here since it uses a simple API key,
        not OAuth."""
        if provider not in OAUTH_PROVIDERS:
            return jsonify({"error": f"Unknown provider: {provider}"}), 404

        state = models.create_oauth_state(provider)
        redirect_uri = url_for("oauth_callback", provider=provider, _external=True)

        try:
            if provider == "google":
                authorize_url = oauth_service.build_google_authorize_url(redirect_uri, state)
            else:
                authorize_url = oauth_service.build_slack_authorize_url(redirect_uri, state)
        except oauth_service.OAuthConfigError as exc:
            # Same reason as the mutual-exclusion redirect in
            # oauth_start_for_person below: this endpoint is an
            # <a href> the browser navigates directly to, not a
            # fetch/JSON call the frontend can intercept — returning
            # jsonify() here made the browser display the raw JSON on
            # screen instead of a readable error banner. Redirects to
            # index with oauth_error to reuse the same banner that
            # already handles the rest of the OAuth failures.
            return redirect(url_for("index", oauth_error=f"{provider}:not_configured:{exc}"))

        return redirect(authorize_url)

    @app.get("/oauth/google/start/<person>")
    def oauth_start_for_person(person):
        """Connects the calendar of ONE specific person on the team.

        Why this exists on top of /oauth/google/start: one person's
        Google token can't read another person's calendar — everyone
        has to authorize their own. See the big note in models.py,
        "OAuth connections" section.

        Uses the SAME fixed redirect_uri as the app-level connection
        (/oauth/google/callback) — which person it is travels in the
        `state`, not in the callback URL, because Google requires the
        redirect_uri to be pre-registered exactly as-is in Cloud
        Console, and a different one can't be pre-registered for every
        future team member.

        Mutual exclusion with Cal.com: see the long note in
        calcom_connect_for_person — prevents the same meeting from
        being counted twice if a person connected both sources. Since
        this endpoint is an <a href> link (not fetch/JSON), the
        rejection redirects back to index with oauth_error instead of
        returning a JSON 409, to reuse the same error banner the
        frontend already handles for the rest of the OAuth failures.
        """
        if not any(m["person"] == person for m in models.get_team()):
            return jsonify({"error": f"'{person}' is not on the team."}), 404

        if person in models.list_people_with_api_key("calcom"):
            return redirect(url_for(
                "index",
                oauth_error=f"google:already_connected_calcom:{person}",
            ))

        state = models.create_oauth_state("google", person=person)
        redirect_uri = url_for("oauth_callback", provider="google", _external=True)

        try:
            authorize_url = oauth_service.build_google_authorize_url(redirect_uri, state)
        except oauth_service.OAuthConfigError as exc:
            return redirect(url_for("index", oauth_error=f"google:not_configured:{exc}"))

        return redirect(authorize_url)

    @app.get("/oauth/<provider>/callback")
    def oauth_callback(provider):
        if provider not in OAUTH_PROVIDERS:
            return jsonify({"error": f"Unknown provider: {provider}"}), 404

        provider_error = request.args.get("error")
        if provider_error:
            return redirect(url_for("index", oauth_error=f"{provider}:{provider_error}"))

        state = request.args.get("state")
        code = request.args.get("code")
        state_info = models.consume_oauth_state(state) if state else None

        if not code or not state or not state_info or state_info["provider"] != provider:
            # Could be a CSRF attempt, an already-used state, or a
            # server restart between /start and this callback (states
            # are saved in SQLite, they survive a restart, but don't
            # have an expiration yet — see the GUI's README).
            return redirect(url_for("index", oauth_error=f"{provider}:invalid_state"))

        person = state_info["person"]  # None = app-level connection (Slack, or Google for Sheets)
        redirect_uri = url_for("oauth_callback", provider=provider, _external=True)

        try:
            if provider == "google":
                token_data = oauth_service.exchange_google_code(code, redirect_uri)
                if person:
                    models.save_person_oauth_connection(
                        person, "google",
                        access_token=token_data.get("access_token"),
                        refresh_token=token_data.get("refresh_token"),
                        token_type=token_data.get("token_type"),
                        scope=token_data.get("scope"),
                    )
                else:
                    models.save_oauth_connection(
                        "google",
                        access_token=token_data.get("access_token"),
                        refresh_token=token_data.get("refresh_token"),
                        token_type=token_data.get("token_type"),
                        scope=token_data.get("scope"),
                    )
                    models.mark_connection_validated("google", datetime.now(timezone.utc).isoformat())
                # With person set there's no app-level row
                # (oauth_connections) to mark here — but
                # exchange_google_code() just returned a real token,
                # so Google has ALREADY validated that the app's
                # Client ID/Secret are correct. status() uses the
                # existence of THIS row in person_oauth_connections as
                # that same proof, without needing a separate column.
            else:
                token_data = oauth_service.exchange_slack_code(code, redirect_uri)
                models.save_oauth_connection(
                    "slack",
                    access_token=token_data.get("access_token"),
                    token_type="bot",
                    scope=token_data.get("scope"),
                    extra={
                        "team_id": (token_data.get("team") or {}).get("id"),
                        "team_name": (token_data.get("team") or {}).get("name"),
                        "bot_user_id": token_data.get("bot_user_id"),
                    },
                )
                models.mark_connection_validated("slack", datetime.now(timezone.utc).isoformat())
        except Exception as exc:  # noqa: BLE001 — show the error to the user, don't crash
            return redirect(url_for("index", oauth_error=f"{provider}:{exc}"))

        connected_label = f"google_calendar:{person}" if person else provider
        return redirect(url_for("index", oauth_connected=connected_label))

    @app.post("/api/slack/connect-token")
    def slack_connect_token():
        """Alternative to '/oauth/slack/start' for when the browser
        redirect flow isn't viable (for example, Slack requires PKCE
        because the redirect_uri is 127.0.0.1/localhost without
        HTTPS, or the team simply prefers the admin path).

        A Bot User OAuth Token (xoxb-...) generated from
        api.slack.com/apps -> OAuth & Permissions -> "Install to
        workspace" is pasted here — that button doesn't use
        redirect_uri at all, so it doesn't run into the PKCE
        requirement. It's validated against the real Slack API
        (auth.test) before saving, same as the normal OAuth exchange.

        Body: {"bot_token": str}
        """
        body = request.get_json(force=True, silent=True) or {}
        bot_token = (body.get("bot_token") or "").strip()
        if not bot_token:
            return jsonify({"error": "bot_token is missing from the body."}), 400

        try:
            info = oauth_service.validate_slack_bot_token(bot_token)
        except oauth_service.OAuthConfigError as exc:
            return jsonify({"error": str(exc)}), 400

        models.save_oauth_connection(
            "slack",
            access_token=bot_token,
            token_type="bot",
            scope=None,
            extra={
                "team_id": info.get("team_id"),
                "team_name": info.get("team_name"),
                "bot_user_id": info.get("bot_user_id"),
                "connection_method": "pasted_token",
            },
        )
        models.mark_connection_validated("slack", datetime.now(timezone.utc).isoformat())
        return jsonify({"connected": "slack", "team_name": info.get("team_name")})

    @app.post("/oauth/<provider>/disconnect")
    def oauth_disconnect(provider):
        if provider not in OAUTH_PROVIDERS:
            return jsonify({"error": f"Unknown provider: {provider}"}), 404
        models.delete_oauth_connection(provider)
        return jsonify({"disconnected": provider})

    @app.post("/oauth/google/disconnect/<person>")
    def oauth_disconnect_for_person(person):
        models.delete_person_oauth_connection(person, "google")
        return jsonify({"disconnected": "google_calendar", "person": person})

    @app.get("/api/team")
    def get_team():
        team = models.get_team()
        gcal_connected = set(models.list_connected_people("google"))
        calcom_connected = set(models.list_people_with_api_key("calcom"))
        for member in team:
            member["gcal_connected"] = member["person"] in gcal_connected
            member["calcom_connected"] = member["person"] in calcom_connected
        return jsonify(team)

    @app.post("/api/team")
    def add_team_member():
        """Adds a new person to the team.

        Body: {"person": str, "calcom_username": str?, "gcal_email": str?,
               "slack_user_id": str?, "yellow_hours": float?, "red_hours": float?}
        """
        body = request.get_json(force=True, silent=True) or {}
        person = (body.get("person") or "").strip()
        if not person:
            return jsonify({"error": "'person' is missing from the body."}), 400

        yellow_hours = body.get("yellow_hours", 15.0)
        red_hours = body.get("red_hours", 20.0)

        try:
            added = models.add_team_member(
                person,
                calcom_username=body.get("calcom_username", ""),
                gcal_email=body.get("gcal_email", ""),
                slack_user_id=body.get("slack_user_id", ""),
                yellow_hours=float(yellow_hours),
                red_hours=float(red_hours),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if not added:
            return jsonify({"error": f"A person named '{person}' already exists."}), 409

        return jsonify({"added": person}), 201

    @app.put("/api/team/<person>")
    def edit_team_member(person):
        """Edits a person's identity data (not the thresholds — for
        that, use POST /api/thresholds).

        Body: {"calcom_username": str?, "gcal_email": str?, "slack_user_id": str?}
        Only the fields present in the body are updated.
        """
        body = request.get_json(force=True, silent=True) or {}
        updated = models.update_team_member(
            person,
            calcom_username=body.get("calcom_username"),
            gcal_email=body.get("gcal_email"),
            slack_user_id=body.get("slack_user_id"),
        )
        if not updated:
            return jsonify({"error": f"No person named '{person}' exists."}), 404
        return jsonify({"updated": person})

    @app.delete("/api/team/<person>")
    def remove_team_member(person):
        removed = models.delete_team_member(person)
        if not removed:
            return jsonify({"error": f"No person named '{person}' exists."}), 404
        return jsonify({"removed": person})

    @app.get("/api/metrics")
    def get_metrics():
        week_start = sync_service.current_week_start()
        hours_by_person = models.get_hours_for_week(week_start)

        if not hours_by_person:
            # First load of the week: sync automatically so we don't
            # show an empty dashboard.
            result = sync_service.sync_now()
            hours_by_person = result["hours_by_person"]
            source = result["source"]
        else:
            # There's already data for this week: where it came from
            # is the source saved the last time it was synced.
            recent = models.get_recent_syncs(limit=1)
            source = recent[0]["source"] if recent else "demo"

        team = models.get_team()
        thresholds_by_person = {
            m["person"]: {"yellow_hours": m["yellow_hours"], "red_hours": m["red_hours"]}
            for m in team
        }

        health_status = {}
        for person, hours in hours_by_person.items():
            person_thresholds = thresholds_by_person.get(person)
            health_status.update(classify_team_health({person: hours}, person_thresholds))

        report_text = summarize_team_report(hours_by_person, health_status)

        return jsonify({
            "week_start": week_start,
            "source": source,
            "hours_by_person": hours_by_person,
            "health_status": health_status,
            "thresholds_by_person": thresholds_by_person,
            "report_text": report_text,
        })

    @app.get("/api/workflow-settings")
    def get_workflow_settings():
        return jsonify(models.get_workflow_settings())

    @app.post("/api/workflow-settings/<workflow_id>")
    def set_workflow_enabled(workflow_id):
        """Body: {"enabled": bool}.

        **See the note in models.py**: this saves a preference, it
        doesn't control anything live except for 'fika-sync'. Don't
        confuse it with a real RailCall switch.
        """
        body = request.get_json(force=True, silent=True) or {}
        if "enabled" not in body:
            return jsonify({"error": "'enabled' is missing from the body."}), 400

        ok = models.set_workflow_enabled(workflow_id, bool(body["enabled"]))
        if not ok:
            return jsonify({"error": f"'{workflow_id}' is not a known workflow."}), 404
        return jsonify(
            {"workflow_id": workflow_id, "enabled": bool(body["enabled"])}
        )

    @app.get("/api/notification-settings")
    def get_notification_settings():
        return jsonify(models.get_notification_settings())

    @app.post("/api/notification-settings")
    def save_notification_settings():
        """Body: {"slack_channel": str?, "sync_frequency_minutes": int?,
                  "auto_publish_on_sync": bool?, "personal_dms_enabled": bool?}
                  — only updates what's present."""
        body = request.get_json(force=True, silent=True) or {}

        sync_frequency = body.get("sync_frequency_minutes")
        if sync_frequency is not None and sync_frequency < 0:
            return jsonify({"error": "sync_frequency_minutes cannot be negative."}), 400

        models.save_notification_settings(
            slack_channel=body.get("slack_channel"),
            sync_frequency_minutes=sync_frequency,
            auto_publish_on_sync=body.get("auto_publish_on_sync"),
            personal_dms_enabled=body.get("personal_dms_enabled"),
        )
        return jsonify(models.get_notification_settings())

    @app.post("/api/publish-now")
    def publish_now():
        """Publishes the current week's summary to the configured
        Slack channel — this DOES have a real effect (unlike the
        workflow toggles), as long as Slack is connected."""
        try:
            result = sync_service.publish_summary_now()
        except sync_service.PublishError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(result)

    @app.post("/api/notifications/send-personal-dms")
    def send_personal_dms():
        """Sends a private DM to each person in 🟡/🔴 who has a
        slack_user_id set in their "Team" row — see
        sync_service.send_personal_dm_notifications for the detail of
        why this is "per person" even though there's a single shared
        bot token. Returns the result per person, not a single global
        boolean, so the GUI can show who got one and who didn't (and
        why)."""
        try:
            results = sync_service.send_personal_dm_notifications()
        except sync_service.PublishError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"results": results})

    @app.get("/api/history/<person>")
    def get_history(person):
        history = models.get_history(person, limit_weeks=8)
        return jsonify(history)

    @app.post("/api/sync")
    def sync():
        result = sync_service.sync_now()
        return jsonify(result)

    @app.post("/api/thresholds")
    def update_thresholds():
        body = request.get_json(force=True, silent=True) or {}
        person = body.get("person")
        field = body.get("field")
        value = body.get("value")

        if not person or field not in ("yellow_hours", "red_hours"):
            return jsonify({"error": "Body must have person and field ('yellow_hours' | 'red_hours')."}), 400
        try:
            value = float(value)
        except (TypeError, ValueError):
            return jsonify({"error": "value must be numeric."}), 400

        updated = models.set_threshold(person, field, value)
        if not updated:
            return jsonify({"error": f"Person '{person}' does not exist."}), 404

        return jsonify({"person": person, "field": field, "value": value})

    @app.get("/api/sync-log")
    def sync_log():
        return jsonify(models.get_recent_syncs(limit=10))

    @app.post("/api/reset-demo")
    def reset_demo():
        """Wipes the database and reseeds it from config/*.example.
        Meant to let the GUI be shown from scratch in a demo."""
        body = request.get_json(force=True, silent=True) or {}
        if body.get("confirm") is not True:
            return jsonify({"error": "Send {\"confirm\": true} to confirm the reset."}), 400

        models.reset_db()
        models.init_db()
        models.log_sync(datetime.now(timezone.utc).isoformat(), "demo", "ok", "Database reset from the GUI.")
        return jsonify({"reset": True})

    return app


app = create_app()

if __name__ == "__main__":
    DEBUG_MODE = True

    # Flask's reloader (active when debug=True) launches a "monitor"
    # process in addition to the real worker — if we started the
    # scheduler without this guard, two auto-sync threads would end up
    # running in parallel. WERKZEUG_RUN_MAIN is only set in the real
    # worker process.
    if not DEBUG_MODE or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        sync_service.start_background_scheduler()

    app.run(debug=DEBUG_MODE, port=5000)
