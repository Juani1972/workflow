"""Unit tests for juani1972/gcal, with urllib.urlopen mocked.

Run: python3 -m pytest railcall-submission/gcal/tests -q (from repo
root) or `python3 -m pytest tests -q` from this module's directory.

No network calls — validates handler logic (input validation, request
shaping, error propagation, the `_h_*` naming the RailCall loader
requires, and the pure `_first_free_slot` calculation) without a real
Station install. See ESTADO.md for what still needs that real run.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import unittest
from unittest.mock import MagicMock, patch


def _load_handler():
    builtins.__rc_helpers__ = {"vault_get": lambda name: {"access_token": "fake-google-token"}}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "handlers", "handler.py")
    spec = importlib.util.spec_from_file_location("gcal_handler", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


handler = _load_handler()


def _mock_response(payload: dict):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    cm.__exit__.return_value = False
    return cm


class TestModuleShape(unittest.TestCase):
    def test_all_commands_have_h_prefixed_functions(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifest = json.load(open(os.path.join(here, "module.json")))
        for cmd in manifest["commands"]:
            fn = getattr(handler, f"_h_{cmd['name']}", None)
            self.assertTrue(callable(fn), f"missing _h_{cmd['name']}")


class TestListEvents(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_lists_events(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"items": [{"id": "evt1"}, {"id": "evt2"}]})
        result = handler._h_list_events(
            {"calendar_id": "ana@example.com", "time_min_iso": "2026-09-01T00:00:00Z",
             "time_max_iso": "2026-09-07T00:00:00Z"}, {}
        )
        self.assertEqual(result["count"], 2)

    def test_missing_required_field_raises(self):
        with self.assertRaises(handler.GCalError):
            handler._h_list_events({"calendar_id": "ana@example.com"}, {})


class TestFindNextFreeSlot(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_finds_free_slot_via_freebusy(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            {"calendars": {"ana@example.com": {"busy": []}}}
        )
        result = handler._h_find_next_free_slot(
            {
                "calendar_id": "ana@example.com",
                "duration_minutes": 30,
                "search_start_iso": "2026-09-01T09:00:00+00:00",
                "search_end_iso": "2026-09-01T17:00:00+00:00",
            },
            {},
        )
        self.assertIsNotNone(result["slot"])
        self.assertEqual(result["slot"]["start"], "2026-09-01T09:00:00+00:00")

    def test_missing_duration_raises(self):
        with self.assertRaises(handler.GCalError):
            handler._h_find_next_free_slot(
                {"calendar_id": "ana@example.com", "search_start_iso": "x", "search_end_iso": "y"}, {}
            )


class TestFirstFreeSlotPureLogic(unittest.TestCase):
    """No network at all — this is the pure calculation, portable
    verbatim from modules/gcal/actions.py per the handler docstring."""

    def test_returns_gap_before_first_busy_period(self):
        busy = [{"start": "2026-09-01T10:00:00+00:00", "end": "2026-09-01T11:00:00+00:00"}]
        slot = handler._first_free_slot(
            busy, "2026-09-01T09:00:00+00:00", "2026-09-01T17:00:00+00:00", 30
        )
        self.assertEqual(slot["start"], "2026-09-01T09:00:00+00:00")

    def test_returns_none_when_no_gap_fits(self):
        busy = [{"start": "2026-09-01T09:00:00+00:00", "end": "2026-09-01T17:00:00+00:00"}]
        slot = handler._first_free_slot(
            busy, "2026-09-01T09:00:00+00:00", "2026-09-01T17:00:00+00:00", 30
        )
        self.assertIsNone(slot)


class TestCreateUpdateDeleteEvent(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_creates_event(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"id": "new-evt"})
        result = handler._h_create_event(
            {
                "calendar_id": "ana@example.com",
                "summary": "Focus time",
                "start_iso": "2026-09-01T09:00:00Z",
                "end_iso": "2026-09-01T10:00:00Z",
                "timezone": "America/Argentina/Buenos_Aires",
            },
            {},
        )
        self.assertEqual(result["event"]["id"], "new-evt")

    @patch("urllib.request.urlopen")
    def test_updates_event(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"id": "evt1", "summary": "Renamed"})
        result = handler._h_update_event(
            {"calendar_id": "ana@example.com", "event_id": "evt1", "updates": {"summary": "Renamed"}}, {}
        )
        self.assertEqual(result["event"]["summary"], "Renamed")

    @patch("urllib.request.urlopen")
    def test_deletes_event(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({})
        result = handler._h_delete_event({"calendar_id": "ana@example.com", "event_id": "evt1"}, {})
        self.assertEqual(result, {"deleted": True})

    def test_missing_updates_raises(self):
        with self.assertRaises(handler.GCalError):
            handler._h_update_event({"calendar_id": "ana@example.com", "event_id": "evt1"}, {})


class TestVaultAndErrors(unittest.TestCase):
    def test_missing_credential_raises_clear_error(self):
        old_helpers = builtins.__rc_helpers__
        builtins.__rc_helpers__ = {"vault_get": lambda name: None}
        try:
            with self.assertRaises(handler.GCalError):
                handler._h_list_events(
                    {"calendar_id": "x", "time_min_iso": "a", "time_max_iso": "b"}, {}
                )
        finally:
            builtins.__rc_helpers__ = old_helpers

    @patch("urllib.request.urlopen")
    def test_http_error_is_not_swallowed(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, MagicMock(read=lambda: b'{"error": "not found"}')
        )
        with self.assertRaises(handler.GCalError):
            handler._h_list_events(
                {"calendar_id": "x", "time_min_iso": "a", "time_max_iso": "b"}, {}
            )


if __name__ == "__main__":
    unittest.main()
