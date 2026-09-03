"""Handlers for the your-handle/team-health-analyzer module.

Unlike calcom-pro, this module does NOT call any external API --
it operates on data already passed to it by the workflow that invokes
it (hence "auth": {"type": "none"} in module.json). That makes it
100% testable without network mocks, and it's the same code tested
in test_handler.py.
"""


def _classify(pct: float) -> str:
    if pct <= 80:
        return "green"
    if pct <= 100:
        return "yellow"
    return "red"


def analyze_team_health(inputs: dict, context: dict) -> dict:
    members = inputs["members"]
    results = []
    for m in members:
        threshold = m["weekly_threshold"] or 1  # avoids division by zero
        pct = round((m["weekly_meeting_hours"] / threshold) * 100, 1)
        results.append({
            "person_id": m["person_id"],
            "pct_of_threshold": pct,
            "severity": _classify(pct),
        })
    counts = {"green": 0, "yellow": 0, "red": 0}
    for r in results:
        counts[r["severity"]] += 1
    return {
        "members": results,
        "team_summary": counts,
        "team_size": len(members),
    }


def get_individual_metrics(inputs: dict, context: dict) -> dict:
    threshold = inputs["weekly_threshold"] or 1
    current = inputs["current_hours"]
    previous = inputs.get("previous_hours")
    pct = round((current / threshold) * 100, 1)
    trend = None
    if previous is not None:
        if current > previous:
            trend = "up"
        elif current < previous:
            trend = "down"
        else:
            trend = "flat"
    return {
        "person_id": inputs["person_id"],
        "pct_of_threshold": pct,
        "severity": _classify(pct),
        "trend_vs_previous_week": trend,
    }


def generate_report(inputs: dict, context: dict) -> dict:
    tm = inputs["team_metrics"]
    summary = tm.get("team_summary", {})
    lines = [
        "# Team health report",
        "",
        f"- 🟢 Healthy: {summary.get('green', 0)}",
        f"- 🟡 At the limit: {summary.get('yellow', 0)}",
        f"- 🔴 Overloaded: {summary.get('red', 0)}",
        "",
        "## Per-person detail",
    ]
    for m in tm.get("members", []):
        emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[m["severity"]]
        lines.append(f"- {emoji} {m['person_id']}: {m['pct_of_threshold']}% of threshold")
    return {"markdown": "\n".join(lines)}


def suggest_optimizations(inputs: dict, context: dict) -> dict:
    tm = inputs["team_metrics"]
    suggestions = []
    for m in tm.get("members", []):
        if m["severity"] == "red":
            suggestions.append({
                "person_id": m["person_id"],
                "action": "protect_focus_time",
                "reason": f"{m['pct_of_threshold']}% of weekly threshold exceeded",
            })
        elif m["severity"] == "yellow":
            suggestions.append({
                "person_id": m["person_id"],
                "action": "monitor",
                "reason": f"{m['pct_of_threshold']}% of threshold, close to the limit",
            })
    return {"suggestions": suggestions}
