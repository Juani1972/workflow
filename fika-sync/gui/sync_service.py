"""
GUI sync service.

Two modes, chosen automatically based on whether real credentials are
available or not — never silently mixed. Credentials can come from
two paths (see `real_credentials_available`): connected with one
click from the GUI (`oauth_service.py` + `/oauth/<provider>/start`),
or set by hand as environment variables (the developer path that
already existed).

- **Connected mode** (`source="calcom+gcal"`): if `CALCOM_API_KEY`
  and Google's 3 variables are set, tries to fetch real data from
  Cal.com + Google Calendar. **Mapping Cal.com's response to "minutes
  per person" is best-effort and unconfirmed against a real account**
  (see the warning in `_extract_calcom_hours`) — if it fails or the
  format doesn't match, the error is logged and it falls back to demo
  mode for that sync, without breaking the GUI.
- **Demo mode** (`source="demo"`): generates deterministic meeting
  hours (same result if you run the sync twice in the same week) from
  a hash of person+week. Saved in SQLite just like real data — the
  difference is always marked in the `source` column, never hidden.

In both cases, the 🟢/🟡/🔴 classification and the report use the
real `team-health-analyzer` functions — that's never demo, it's the
same logic the production workflow would use.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import models
import provider_modules

th_actions = provider_modules.load_team_health_analyzer()
th_calculate_meeting_load = th_actions.calculate_meeting_load


def current_week_start(now: datetime = None) -> str:
    """Monday of the current week, in ISO format (YYYY-MM-DD)."""
    now = now or datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.strftime("%Y-%m-%d")


def real_credentials_available() -> dict:
    """Checks (without calling any API) whether there are credentials
    for each provider, through EITHER of the available paths:

    - **Cal.com**: **per person** (`person_api_keys`, connected from
      each person's row in "Team") OR at the app level (guided flow
      in "Connections", `oauth_connections`) OR the `CALCOM_API_KEY`
      environment variable — `True` here means "there's AT LEAST ONE
      Cal.com data source available for someone", not that everyone
      is covered. For per-person detail, see `/api/team`
      (`calcom_connected` on each row) and
      `skipped_calcom_connection` in the `/api/sync` response. None
      of the three is real OAuth — Cal.com doesn't offer it for
      personal/free accounts, only for paying "Platform" customers
      (see `fika-sync/gui/README.md`).
    - **Google Calendar**: **per person**, not at the app level —
      `True` here means "at least one team member connected their
      calendar" (`person_oauth_connections`), not "everything is set
      up for the whole team". For per-person detail, see `/api/team`
      (`gcal_connected` on each row). The old environment variable
      flow (`GOOGLE_REFRESH_TOKEN`) also counts here, as a legacy
      single-account fallback for the whole team — documented, not
      recommended for more than one person.
    - **Slack**: connected with one click (`models.oauth_connections`,
      see `oauth_service.py` and `/oauth/<provider>/start` in
      `app.py`) — the path meant for an end user — or the
      `SLACK_BOT_TOKEN` environment variable — the manual developer
      path that already existed, still works for whoever prefers to
      configure it that way.

    Doesn't confirm the credentials are valid, only that they exist
    through one of the available paths.
    """
    calcom_connected = models.get_oauth_connection("calcom") is not None
    any_person_calcom_connected = len(models.list_people_with_api_key("calcom")) > 0
    any_person_gcal_connected = len(models.list_connected_people("google")) > 0
    slack_connected = models.get_oauth_connection("slack") is not None

    return {
        "calcom": calcom_connected or any_person_calcom_connected or bool(os.environ.get("CALCOM_API_KEY")),
        "google_calendar": any_person_gcal_connected or all(
            os.environ.get(v)
            for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
        ),
        "slack": slack_connected or bool(os.environ.get("SLACK_BOT_TOKEN")),
    }


def _demo_hours_for(person: str, week_start: str) -> float:
    """Deterministic demo meeting hours, per person+week.

    Not actually random: uses a hash so running the sync twice in the
    same week gives the same number (it looks like real data that
    doesn't change on its own, instead of rolling a die every time
    someone opens the GUI).
    """
    seed = int(hashlib.sha256(f"{person}:{week_start}".encode()).hexdigest(), 16)
    # 4–26 hour range: crosses the default threshold (15/20) so the
    # demo shows all three health states, not just green.
    return round(4 + (seed % 2200) / 100.0, 2)


def _gcal_events_to_records(events: list, person: str) -> list:
    """Converts Google Calendar events into
    {"person", "duration_minutes"} records — the format expected by
    `team_health_analyzer.calculate_meeting_load`.

    Event format confirmed against the official documentation:
    event["start"]["dateTime"] / event["end"]["dateTime"] in RFC3339.
    Ignores all-day events (no "dateTime", only "date").
    """
    records = []
    for event in events:
        start = event.get("start", {}).get("dateTime")
        end = event.get("end", {}).get("dateTime")
        if not start or not end:
            continue
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            continue
        minutes = (end_dt - start_dt).total_seconds() / 60.0
        if minutes > 0:
            records.append({"person": person, "duration_minutes": minutes})
    return records


def _calcom_bookings_to_records(bookings: list, person: str, attendee_email: Optional[str] = None) -> list:
    """Converts Cal.com bookings into {"person", "duration_minutes"}
    records for a given person.

    If `attendee_email` is None (case: bookings came from that
    person's OWN key, see `_build_calcom_client_for_person`), it
    doesn't filter by attendee — it assumes everything that account
    returned belongs to them. If an email is passed (case: bookings
    came from the app-level fallback client, shared by the whole
    team), it filters by attendee matching that email — it's the only
    data available to separate "whose booking is this" when the
    source is a single shared account.

    ⚠️ **Best-effort, unconfirmed.** Assumes every booking has
    `attendees: [{"email": ...}]` and `start`/`end` in ISO 8601 —
    these are reasonable field names based on the rest of Cal.com v2's
    documentation, but `list_bookings` has never been run against a
    real account (see `modules/calcom-pro/README.md`). If the real
    format differs, this function returns an empty list instead of
    crashing — that's why `sync_now` treats `_sync_real`'s result as
    best-effort, not as confirmed truth.
    """
    records = []
    for booking in bookings:
        if attendee_email is not None:
            attendees = booking.get("attendees", [])
            emails = {a.get("email") for a in attendees if isinstance(a, dict)}
            if attendee_email not in emails:
                continue
        start = booking.get("start")
        end = booking.get("end")
        if not start or not end:
            continue
        try:
            start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        except ValueError:
            continue
        minutes = (end_dt - start_dt).total_seconds() / 60.0
        if minutes > 0:
            records.append({"person": person, "duration_minutes": minutes})
    return records


def sync_now(now: datetime = None) -> dict:
    """Runs a sync and persists the result to SQLite.

    Returns a dict with "source" ("demo" or "calcom+gcal"),
    "week_start", "hours_by_person" and, if something failed while
    trying connected mode, "fallback_reason".

    Never raises an exception upward: any network or format error
    while trying connected mode gets logged to `sync_log` and is
    resolved by falling back to demo mode for that run, so a
    credentials or API-format problem doesn't break the GUI.
    """
    now = now or datetime.now(timezone.utc)
    week_start = current_week_start(now)
    creds = real_credentials_available()
    team = models.get_team()

    # We used to require creds["calcom"] AND creds["google_calendar"]
    # here — now both connect per person, so "nobody connected their
    # own yet" for ONE of the two shouldn't drop the whole sync to
    # demo anymore. But if there's NO real credential at all (for any
    # provider, neither app-level nor per-person), it should still
    # fall back to demo — otherwise _sync_real would return zero hours
    # for everyone with source="calcom+gcal", which would look like
    # empty real data instead of the honest "demo" label.
    if team and (creds["calcom"] or creds["google_calendar"]):
        try:
            hours_by_person, skipped = _sync_real(team, week_start)
            skipped_calendar = skipped["calendar"]
            skipped_calcom = skipped["calcom"]
            source = "calcom+gcal"
            for person, hours in hours_by_person.items():
                models.record_meeting_hours(person, week_start, hours, source)

            detail = f"{len(hours_by_person)} people synced for week {week_start}"
            notes = []
            if skipped_calendar:
                notes.append(
                    f"{len(skipped_calendar)} haven't connected their calendar yet: "
                    f"{', '.join(skipped_calendar)}"
                )
            if skipped_calcom:
                notes.append(
                    f"{len(skipped_calcom)} with no Cal.com key available at all (neither "
                    f"their own nor a fallback): {', '.join(skipped_calcom)}"
                )
            if notes:
                detail += " (" + "; ".join(notes) + ")"
            models.log_sync(now.isoformat(), source, "ok", detail)

            result = {"source": source, "week_start": week_start, "hours_by_person": hours_by_person}
            if skipped_calendar:
                result["skipped_calendar_connection"] = skipped_calendar
            if skipped_calcom:
                result["skipped_calcom_connection"] = skipped_calcom
            return result
        except Exception as exc:  # noqa: BLE001 — best-effort, falls back to demo
            models.log_sync(
                now.isoformat(), "calcom+gcal", "error",
                f"Real sync failed, demo was used for this run: {exc}",
            )
            hours_by_person = _sync_demo(team, week_start)
            return {
                "source": "demo",
                "week_start": week_start,
                "hours_by_person": hours_by_person,
                "fallback_reason": str(exc),
            }

    hours_by_person = _sync_demo(team, week_start)
    models.log_sync(
        now.isoformat(), "demo", "ok",
        f"{len(hours_by_person)} people (demo) for week {week_start}"
        + ("" if (creds['calcom'] and creds['google_calendar']) else " — no credentials configured"),
    )
    return {"source": "demo", "week_start": week_start, "hours_by_person": hours_by_person}


def _sync_demo(team: list, week_start: str) -> dict:
    """Generates demo data and runs it through team-health-analyzer's
    REAL `calculate_meeting_load` function — the aggregation isn't
    demo, only the input data is."""
    demo_records = []
    for member in team:
        person = member["person"]
        minutes = _demo_hours_for(person, week_start) * 60.0
        demo_records.append({"person": person, "duration_minutes": minutes})

    hours_by_person = th_calculate_meeting_load(demo_records, [])

    for person, hours in hours_by_person.items():
        models.record_meeting_hours(person, week_start, hours, "demo")

    return hours_by_person


def _build_calcom_client(calcom_actions):
    """Builds the app-level FALLBACK CalComClient — prioritizes the
    API key saved via the GUI's guided flow (`/api/calcom/connect`)
    over the `CALCOM_API_KEY` environment variable.

    Only used for people who did NOT connect their own personal key
    (`/api/calcom/connect/<person>`) — see
    `_build_calcom_client_for_person` and `_sync_real`. If nobody
    connected anything personal, this is the only source and only
    works well to see the WHOLE team's bookings if it's a key from a
    Cal.com Team plan; a free personal key only sees its owner's
    bookings."""
    connection = models.get_oauth_connection("calcom")
    if connection and connection.get("access_token"):
        return calcom_actions.CalComClient(api_key=connection["access_token"])
    return calcom_actions.CalComClient.from_env()


def _build_calcom_client_for_person(calcom_actions, person: str):
    """Builds ONE specific person's CalComClient, using THEIR OWN API
    key (`/api/calcom/connect/<person>`, connected from their row in
    the "Team" section) — same pattern as
    `_build_gcal_client_for_person` for the calendar.

    Why this is needed on top of `_build_calcom_client`: a personal,
    free Cal.com API key only sees the bookings of the account it
    belongs to — it can't read another team member's bookings, not
    even with special permissions. Before this existed, `_sync_real`
    depended on a SINGLE key (at the app level) having visibility over
    the whole team, which is only true on a paid Cal.com Team plan.

    Returns:
        The client if that person connected their own key, or None if
        not — in that case, `_sync_real` falls back to the app-level
        fallback client for that person (same behavior as before this
        change)."""
    key_row = models.get_person_api_key(person, "calcom")
    if key_row and key_row.get("api_key"):
        return calcom_actions.CalComClient(api_key=key_row["api_key"])
    return None


def _build_gcal_client_for_person(gcal_actions, person: str):
    """Builds ONE specific person's GCalClient, using THEIR OWN
    connection (`/oauth/google/start/<person>`, connected from that
    person's row in the "Team" section).

    Why there's no "global" version of this: one person's Google
    token can't read another person's calendar — everyone has to have
    connected their own. See the big note in models.py.

    Returns:
        The client if that person connected their calendar, or None
        if not — in that case, _sync_real skips them (doesn't fail
        the whole sync over one unconnected person).
    """
    connection = models.get_person_oauth_connection(person, "google")
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if connection and connection.get("refresh_token") and client_id and client_secret:
        return gcal_actions.GCalClient.from_refresh_token(
            client_id, client_secret, connection["refresh_token"]
        )
    return None


def _sync_real(team: list, week_start: str) -> tuple:
    """Returns:
        (hours_by_person, skipped) — skipped is a dict
        {"calendar": [...], "calcom": [...]}:
        - "calendar": people with gcal_email configured who still
          haven't connected THEIR personal calendar (see
          _build_gcal_client_for_person).
        - "calcom": people who neither connected their own Cal.com key
          NOR have an app-level fallback key configured (see
          _build_calcom_client_for_person /
          _build_calcom_client) — for these, no Cal.com hours could be
          calculated at all, neither their own nor via the shared
          client's email filter.
        Neither one is an error: the sync keeps running with what's
        available — but it's not hidden, sync_now leaves it in the
        log and in the response.
    """
    calcom_actions = provider_modules.load_calcom_pro()
    gcal_actions = provider_modules.load_gcal()

    week_start_dt = datetime.strptime(week_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    week_end_dt = week_start_dt + timedelta(days=7)
    time_min_iso = week_start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max_iso = week_end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # App-level fallback client — built only once, LAZILY (only if at
    # least one person ends up needing it below), so as not to
    # require an app key configured when the whole team already
    # connected their own.
    fallback_client = None
    fallback_bookings = None

    def _get_fallback_bookings():
        nonlocal fallback_client, fallback_bookings
        if fallback_bookings is None:
            if fallback_client is None:
                fallback_client = _build_calcom_client(calcom_actions)
            # A single call, reused for everyone without their own
            # key — matched by attendee on the client side, see the
            # warning in _calcom_bookings_to_records.
            fallback_bookings = calcom_actions.list_bookings(fallback_client, status="past")
        return fallback_bookings

    gcal_records = []
    calcom_records = []
    skipped_calendar = []
    skipped_calcom = []

    for member in team:
        person = member["person"]
        gcal_email = member.get("gcal_email") or ""

        # --- Cal.com: first the person's own key; if they don't have
        # one, fall back to the app-level shared client filtered by
        # their email (previous behavior, to not break compatibility
        # with teams still using a single Team-plan key). ---
        own_calcom_client = _build_calcom_client_for_person(calcom_actions, person)
        if own_calcom_client is not None:
            own_bookings = calcom_actions.list_bookings(own_calcom_client, status="past")
            calcom_records.extend(_calcom_bookings_to_records(own_bookings, person))
        else:
            try:
                shared_bookings = _get_fallback_bookings()
            except Exception:  # noqa: BLE001 — no usable own or fallback key
                shared_bookings = None
            if shared_bookings is None or not gcal_email:
                skipped_calcom.append(person)
            else:
                calcom_records.extend(_calcom_bookings_to_records(shared_bookings, person, gcal_email))

        if not gcal_email:
            continue

        # Mutual exclusion: if this person already has their OWN
        # Cal.com key connected, don't also add their Google Calendar
        # here — calcom_connect_for_person and oauth_start_for_person
        # already block connecting both from the GUI, but this is a
        # safety net for data that may have been left over from before
        # that block existed (or a row edited directly in the
        # database). Without this, the same meeting would arrive via
        # Cal.com AND via Google Calendar (Cal.com usually writes it
        # there too) and calculate_meeting_load would count it twice.
        if own_calcom_client is not None:
            continue

        # Each person needs THEIR OWN calendar connection — a global
        # token can't read another person's calendar.
        gcal_client = _build_gcal_client_for_person(gcal_actions, person)
        if gcal_client is None:
            skipped_calendar.append(person)
            continue

        events = gcal_actions.list_events(gcal_client, gcal_email, time_min_iso, time_max_iso)
        gcal_records.extend(_gcal_events_to_records(events, person))

    # REAL aggregation: the same function fika-sync/workflow.csv would
    # use in production (calculate_meeting_load node). Reload
    # team-health-analyzer here in case another provider's
    # _load_actions() overwrote the sys.modules cache after it was
    # loaded when this file was imported.
    th = provider_modules.load_team_health_analyzer()
    hours_by_person = th.calculate_meeting_load(calcom_records, gcal_records)

    # People with no event/booking that week don't show up in
    # calculate_meeting_load's result — fill in with 0 so the
    # dashboard keeps showing them.
    for member in team:
        hours_by_person.setdefault(member["person"], 0.0)

    return hours_by_person, {"calendar": skipped_calendar, "calcom": skipped_calcom}


# ---------------------------------------------------------------------------
# Publish the summary to Slack — gives real effect to the notification
# settings (unlike "frequency" and the workflow toggles, which are
# saved preferences, this DOES do something).
# ---------------------------------------------------------------------------

class PublishError(Exception):
    """Slack isn't connected, or no channel is configured — never
    attempts to publish "in demo mode", it wouldn't make sense to
    simulate a message nobody is going to see."""


def publish_summary_now() -> dict:
    """Publishes the current week's summary to the configured Slack
    channel (`notification_settings.slack_channel`), using the bot
    token from the connection saved via `/oauth/slack/start`.

    If there's no data calculated yet for the current week, runs
    `sync_now()` first (same behavior as `/api/metrics`).

    Returns:
        dict {"channel": str, "response": dict} with Slack's Web API's
        raw response.

    Raises:
        PublishError: if Slack isn't connected, or if no channel is
            configured.
    """
    connection = models.get_oauth_connection("slack")
    if not connection or not connection.get("access_token"):
        raise PublishError(
            "Slack isn't connected. Go to the Connections section and connect Slack first."
        )

    settings = models.get_notification_settings()
    channel = settings.get("slack_channel")
    if not channel:
        raise PublishError(
            "No Slack channel is configured. Set it up in the Notifications section."
        )

    week_start = current_week_start()
    hours_by_person = models.get_hours_for_week(week_start)
    if not hours_by_person:
        result = sync_now()
        hours_by_person = result["hours_by_person"]

    team = models.get_team()
    thresholds_by_person = {
        m["person"]: {"yellow_hours": m["yellow_hours"], "red_hours": m["red_hours"]}
        for m in team
    }

    th = provider_modules.load_team_health_analyzer()
    health_status = {}
    for person, hours in hours_by_person.items():
        person_thresholds = thresholds_by_person.get(person)
        health_status.update(th.classify_team_health({person: hours}, person_thresholds))

    report_text = th.summarize_team_report(hours_by_person, health_status)

    slack_actions = provider_modules.load_slack()
    client = slack_actions.SlackClient(bot_token=connection["access_token"])
    blocks = slack_actions.build_summary_blocks(report_text, people=list(hours_by_person.keys()))

    response = slack_actions.post_message(client, channel, text=report_text, blocks=blocks)

    return {"channel": channel, "response": response}


# ---------------------------------------------------------------------------
# Personal Slack DMs — unlike publish_summary_now (one message to the
# team channel), this sends a PRIVATE message to EACH person in
# 🟡/🔴, using their own slack_user_id (the field that already existed
# in each person's "Team" row, but until now wasn't used for anything).
#
# Why this IS "per person" unlike the rest of Slack (see the README,
# "Why the calendar is a per-person connection" section — the same
# reasoning doesn't apply here): the bot token is still ONE, shared,
# connected at the app level — what's "per person" is the message's
# RECIPIENT (channel=slack_user_id instead of channel=team-channel),
# not the credential. No person needs to "connect" anything Slack —
# having their slack_user_id set in their "Team" row is enough.
# ---------------------------------------------------------------------------

# Only people in 🟡/🔴 get notified — deliberately nothing is sent to
# anyone in 🟢, to avoid "everything's fine" noise/spam every time a
# sync runs.
_DM_NOTIFIABLE_STATUSES = {"yellow", "red"}

_DM_STATUS_LABEL = {"yellow": "🟡 yellow", "red": "🔴 red"}


def _build_personal_dm_text(person: str, hours: float, status: str) -> str:
    """Builds the DM text — pure logic, no network, testable without
    mocking anything (same spirit as team_health_analyzer, which
    deliberately separates the calculation/text from the real HTTP
    call)."""
    label = _DM_STATUS_LABEL.get(status, status)
    return (
        f"Hey {person}, you're at *{hours:.1f}h* in meetings this week "
        f"— that puts you at {label}. If you want, you can adjust your threshold from "
        f"the channel summary, or talk it over with your team."
    )


def send_personal_dm_notifications(hours_by_person: Optional[dict] = None,
                                    health_status: Optional[dict] = None) -> dict:
    """Sends a private DM to each person in 🟡/🔴 who has a
    slack_user_id set, using the shared app-level bot token.

    If hours_by_person/health_status aren't passed, they're calculated
    for the current week (same pattern as publish_summary_now: uses
    what's already in SQLite, or runs sync_now() if there's nothing
    yet).

    Best-effort by design: a DM that fails (person with no
    slack_user_id, network error, permissions) NEVER stops the rest —
    it's recorded in the result, not re-raised as an exception. The
    only real exception is PublishError, and only if Slack isn't even
    connected (no point trying to send anything without a bot token).

    Returns:
        dict {person: "sent" | "skipped_green" | "skipped_no_slack_id" |
              "error: <detail>"} — one entry per team member, so the
        GUI can show the full result, not just a single global boolean.
    """
    connection = models.get_oauth_connection("slack")
    if not connection or not connection.get("access_token"):
        raise PublishError(
            "Slack isn't connected. Go to the Connections section and connect Slack first."
        )

    if hours_by_person is None or health_status is None:
        week_start = current_week_start()
        hours_by_person = models.get_hours_for_week(week_start)
        if not hours_by_person:
            result = sync_now()
            hours_by_person = result["hours_by_person"]

        team = models.get_team()
        thresholds_by_person = {
            m["person"]: {"yellow_hours": m["yellow_hours"], "red_hours": m["red_hours"]}
            for m in team
        }
        th = provider_modules.load_team_health_analyzer()
        health_status = {}
        for person, hours in hours_by_person.items():
            person_thresholds = thresholds_by_person.get(person)
            health_status.update(th.classify_team_health({person: hours}, person_thresholds))

    slack_actions = provider_modules.load_slack()
    client = slack_actions.SlackClient(bot_token=connection["access_token"])
    team_by_person = {m["person"]: m for m in models.get_team()}

    results = {}
    for person, hours in hours_by_person.items():
        status = health_status.get(person)
        if status not in _DM_NOTIFIABLE_STATUSES:
            results[person] = "skipped_green"
            continue

        slack_user_id = (team_by_person.get(person) or {}).get("slack_user_id") or ""
        if not slack_user_id:
            results[person] = "skipped_no_slack_id"
            continue

        try:
            text = _build_personal_dm_text(person, hours, status)
            slack_actions.post_message(client, slack_user_id, text=text)
            results[person] = "sent"
        except Exception as exc:  # noqa: BLE001 — a DM that fails doesn't stop the rest
            results[person] = f"error: {exc}"

    return results


# ---------------------------------------------------------------------------
# Background auto-sync — the "best effort" part of this session. The
# decision of whether a sync is due is pure logic and is fully tested;
# the thread that calls it in a loop does NOT have automatic tests
# (testing real timing with a background thread isn't practical in a
# pytest suite) — it only starts from `if __name__ == "__main__"` in
# app.py, never during tests or when the module is imported, so it
# can't interfere with the suite.
# ---------------------------------------------------------------------------

def _should_auto_sync(last_auto_sync_at, frequency_minutes: int, now: datetime = None) -> bool:
    """Pure logic: is an automatic sync due right now, according to
    the saved configuration?

    Args:
        last_auto_sync_at: ISO 8601 of the last automatic run, or None
            if one has never run.
        frequency_minutes: 0 means "manual only", never auto-sync.
        now: so it can be tested without depending on the real clock.
    """
    if frequency_minutes <= 0:
        return False
    if last_auto_sync_at is None:
        return True

    now = now or datetime.now(timezone.utc)
    last = datetime.fromisoformat(last_auto_sync_at.replace("Z", "+00:00"))
    elapsed_minutes = (now - last).total_seconds() / 60.0
    return elapsed_minutes >= frequency_minutes


def run_auto_sync_if_due() -> Optional[dict]:
    """Runs sync_now() if it's due according to notification_settings,
    and also publish_summary_now() if auto_publish_on_sync is on
    (without a Slack failure taking down the auto-sync itself).

    Meant to be called periodically by `start_background_scheduler` —
    doesn't do anything weird if called frequently:
    `_should_auto_sync` is what decides whether it's actually due.

    Returns:
        sync_now()'s result if it ran, None if it wasn't due yet
        (frequency at 0, or not enough time has passed).
    """
    settings = models.get_notification_settings()
    if not _should_auto_sync(settings["last_auto_sync_at"], settings["sync_frequency_minutes"]):
        return None

    result = sync_now()
    models.mark_auto_sync_ran(datetime.now(timezone.utc).isoformat())

    if settings["auto_publish_on_sync"]:
        try:
            publish_summary_now()
        except PublishError:
            pass  # the auto-sync itself doesn't depend on Slack being ready

    if settings["personal_dms_enabled"]:
        try:
            send_personal_dm_notifications()
        except PublishError:
            pass  # same: without Slack connected, it shouldn't take down the auto-sync

    return result


def start_background_scheduler(poll_seconds: int = 60) -> None:
    """Starts a daemon thread that calls run_auto_sync_if_due() every
    `poll_seconds`. Never raises an exception out of the thread — an
    error here shouldn't be able to take down the server.

    **Only called from `if __name__ == "__main__"` in app.py**, not
    from `create_app()` — so it never starts by accident when the
    module is imported (as happens in every test).
    """
    import threading
    import time

    def _loop():
        while True:
            time.sleep(poll_seconds)
            try:
                run_auto_sync_if_due()
            except Exception:  # noqa: BLE001 — best-effort, never take down the thread
                pass

    thread = threading.Thread(target=_loop, daemon=True, name="fika-sync-auto-sync")
    thread.start()
