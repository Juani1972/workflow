"""
meeting-debt-tracker
=====================

Pure logic for the `meeting-debt` workflow: when a person's protected
focus time gets bumped or cancelled (a higher-priority meeting
overrides it), the team "owes" that time back to them. This module
keeps track of that debt — how much is owed, to whom, and when it
needs to be escalated — without calling any external API.

Like `team-health-analyzer`, this is intentionally 100% pure logic:
it can be tested without mocking anything, and it's the easiest piece
of the whole `meeting-debt` workflow to defend.

Exposed actions (5):
    1. record_debt
    2. repay_debt
    3. get_balance
    4. classify_debt_severity
    5. summarize_debt_report
"""

from __future__ import annotations


DEFAULT_SEVERITY_THRESHOLDS = {
    "watch_minutes": 60.0,     # >= this much accumulated debt => "watch"
    "critical_minutes": 180.0,  # >= this => "critical"
}

SEVERITY_OK = "ok"
SEVERITY_WATCH = "watch"
SEVERITY_CRITICAL = "critical"

SEVERITY_EMOJI = {
    SEVERITY_OK: "🟢",
    SEVERITY_WATCH: "🟡",
    SEVERITY_CRITICAL: "🔴",
}


# ---------------------------------------------------------------------------
# 1. record_debt
# ---------------------------------------------------------------------------

def record_debt(ledger, person, minutes, reason, created_at, entry_id=None):
    """Records a new focus-time debt.

    Args:
        ledger: existing list of entries (not mutated).
        person: who the time is owed to.
        minutes: how many minutes of focus time were lost. Must be
            positive.
        reason: short text explaining what overrode it (e.g. "Meeting
            with ACME client rescheduled to 10:00").
        created_at: ISO 8601 timestamp of when it happened.
        entry_id: optional explicit id; if not passed, a sequential
            one is generated based on the ledger's current size.

    Returns:
        New list of entries (doesn't mutate `ledger`).

    Raises:
        ValueError: if minutes isn't positive.
    """
    if minutes <= 0:
        raise ValueError(f"minutes must be positive, got: {minutes!r}")

    entry_id = entry_id or f"debt-{len(ledger) + 1}"
    new_entry = {
        "id": entry_id,
        "person": person,
        "minutes": minutes,
        "repaid_minutes": 0.0,
        "reason": reason,
        "created_at": created_at,
    }
    return list(ledger) + [new_entry]


# ---------------------------------------------------------------------------
# 2. repay_debt
# ---------------------------------------------------------------------------

def repay_debt(ledger, person, minutes):
    """Marks debt as repaid, oldest first (FIFO).

    Never repays more than the person actually owes: if `minutes`
    exceeds the outstanding balance, the surplus simply isn't used
    (no "negative credit" or error results).

    Args:
        ledger: existing list of entries (not mutated).
        person: who the time is being given back to.
        minutes: minutes of focus time actually recovered. Must be
            positive.

    Returns:
        New list of entries with the repayments applied.

    Raises:
        ValueError: if minutes isn't positive.
    """
    if minutes <= 0:
        raise ValueError(f"minutes must be positive, got: {minutes!r}")

    remaining = minutes
    new_ledger = []
    for entry in ledger:
        if entry["person"] != person or remaining <= 0:
            new_ledger.append(dict(entry))
            continue

        owed = entry["minutes"] - entry["repaid_minutes"]
        if owed <= 0:
            new_ledger.append(dict(entry))
            continue

        applied = min(owed, remaining)
        remaining -= applied

        updated_entry = dict(entry)
        updated_entry["repaid_minutes"] = entry["repaid_minutes"] + applied
        new_ledger.append(updated_entry)

    return new_ledger


# ---------------------------------------------------------------------------
# 3. get_balance
# ---------------------------------------------------------------------------

def get_balance(ledger, person):
    """Sums a person's outstanding (unrepaid) minutes.

    Returns:
        float, minutes of focus time still owed. 0.0 if they have no
        debt or don't appear in the ledger.
    """
    return sum(
        max(0.0, entry["minutes"] - entry["repaid_minutes"])
        for entry in ledger
        if entry["person"] == person
    )


# ---------------------------------------------------------------------------
# 4. classify_debt_severity
# ---------------------------------------------------------------------------

def classify_debt_severity(balance_minutes, thresholds=None):
    """Classifies a debt balance as 🟢 ok / 🟡 watch / 🔴 critical.

    Same shape as team_health_analyzer.classify_team_health, so
    summarize_debt_report can be written with the same ordering and
    emoji logic.
    """
    t = {**DEFAULT_SEVERITY_THRESHOLDS, **(thresholds or {})}
    if balance_minutes >= t["critical_minutes"]:
        return SEVERITY_CRITICAL
    if balance_minutes >= t["watch_minutes"]:
        return SEVERITY_WATCH
    return SEVERITY_OK


# ---------------------------------------------------------------------------
# 5. summarize_debt_report
# ---------------------------------------------------------------------------

def summarize_debt_report(ledger, thresholds=None):
    """Generates the text published to Slack with the debt status.

    Args:
        ledger: list of entries (output of record_debt/repay_debt).
        thresholds: optional, see classify_debt_severity.

    Returns:
        str in simple markdown format, people with debt sorted from
        most to least critical. If nobody has outstanding debt,
        returns an "all clear" message.
    """
    people = sorted({entry["person"] for entry in ledger})
    balances = {person: get_balance(ledger, person) for person in people}
    balances = {person: b for person, b in balances.items() if b > 0}

    if not balances:
        return "*Focus time debt*\n\n✅ Nobody has focus time pending repayment."

    order = {SEVERITY_CRITICAL: 0, SEVERITY_WATCH: 1, SEVERITY_OK: 2}
    people_sorted = sorted(
        balances.keys(),
        key=lambda p: (order[classify_debt_severity(balances[p], thresholds)], -balances[p]),
    )

    lines = ["*Focus time debt*", ""]
    for person in people_sorted:
        balance = balances[person]
        severity = classify_debt_severity(balance, thresholds)
        emoji = SEVERITY_EMOJI[severity]
        hours = balance / 60.0
        lines.append(f"{emoji} *{person}* — owed {balance:.0f} min ({hours:.1f}h) of focus time")

    critical_people = [
        p for p in balances if classify_debt_severity(balances[p], thresholds) == SEVERITY_CRITICAL
    ]
    if critical_people:
        lines.append("")
        lines.append(
            "⚠️ Critical accumulated debt for: " + ", ".join(critical_people) +
            " — prioritize giving them that time back this week."
        )

    return "\n".join(lines)
