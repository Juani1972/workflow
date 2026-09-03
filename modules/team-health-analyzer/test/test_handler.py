import importlib.util
import os

# REAL BUG (found 29 Aug 2026): modules/calcom-pro/handlers/handler.py and
# this file are named the SAME ("handler.py"). With `sys.path.insert` +
# `import handler`, Python caches the module by name in sys.modules -- if
# calcom-pro's tests run first, this `import handler` reuses ITS handler
# instead of loading team-health-analyzer's, and these tests fail with
# AttributeError when running the full suite (`pytest` from the root), even
# though they pass fine in isolation. Solved by loading the module by path
# with a unique name, without touching sys.path or the global sys.modules.
_handler_path = os.path.join(os.path.dirname(__file__), "..", "handlers", "handler.py")
_spec = importlib.util.spec_from_file_location("team_health_analyzer_handler", _handler_path)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def test_analyze_team_health_classifies_correctly():
    out = handler.analyze_team_health({
        "members": [
            {"person_id": "p1", "weekly_meeting_hours": 10, "weekly_threshold": 15},  # 66% green
            {"person_id": "p2", "weekly_meeting_hours": 13, "weekly_threshold": 15},  # 86% yellow
            {"person_id": "p3", "weekly_meeting_hours": 20, "weekly_threshold": 15},  # 133% red
        ]
    }, {})
    assert out["team_summary"] == {"green": 1, "yellow": 1, "red": 1}
    assert out["team_size"] == 3
    by_id = {m["person_id"]: m["severity"] for m in out["members"]}
    assert by_id == {"p1": "green", "p2": "yellow", "p3": "red"}


def test_get_individual_metrics_trend_goes_up():
    out = handler.get_individual_metrics({
        "person_id": "p1", "current_hours": 13, "previous_hours": 9, "weekly_threshold": 15
    }, {})
    assert out["trend_vs_previous_week"] == "up"
    assert out["severity"] == "yellow"  # 13/15 = 86.7% > 80%


def test_get_individual_metrics_no_previous_week():
    out = handler.get_individual_metrics({
        "person_id": "p1", "current_hours": 5, "weekly_threshold": 15
    }, {})
    assert out["trend_vs_previous_week"] is None


def test_generate_report_includes_everyone():
    tm = handler.analyze_team_health({
        "members": [{"person_id": "p1", "weekly_meeting_hours": 20, "weekly_threshold": 15}]
    }, {})
    report = handler.generate_report({"team_metrics": tm}, {})
    assert "p1" in report["markdown"]
    assert "🔴" in report["markdown"]


def test_suggest_optimizations_only_yellow_and_red():
    tm = handler.analyze_team_health({
        "members": [
            {"person_id": "p1", "weekly_meeting_hours": 5, "weekly_threshold": 15},   # green
            {"person_id": "p2", "weekly_meeting_hours": 20, "weekly_threshold": 15},  # red
        ]
    }, {})
    out = handler.suggest_optimizations({"team_metrics": tm}, {})
    ids = [s["person_id"] for s in out["suggestions"]]
    assert "p1" not in ids
    assert "p2" in ids


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
