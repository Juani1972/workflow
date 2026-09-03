"""Unit tests for juani1972/calcom-pro, with urllib.urlopen mocked.

Run: python3 -m pytest railcall-submission/calcom-pro/tests -q
(from the repo root), or `python3 -m pytest tests -q` from this
module's own directory.

No network calls — this validates handler logic (input validation,
request shaping, response parsing, error propagation, the `_h_*`
naming the RailCall loader requires, and the cal-api-version sent per
endpoint) against a real Station install. See STATUS.md / README.md
for what still needs that real run.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import unittest
from unittest.mock import MagicMock, patch


def _load_handler():
    builtins.__rc_helpers__ = {"vault_get": lambda name: {"api_key": "fake-cal-key"}}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "handlers", "handler.py")
    spec = importlib.util.spec_from_file_location("calcom_handler", path)
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
    """The loader-facing contract: _h_<name> exists for every command,
    matching module.json exactly."""

    def test_all_commands_have_h_prefixed_functions(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifest = json.load(open(os.path.join(here, "module.json")))
        for cmd in manifest["commands"]:
            fn = getattr(handler, f"_h_{cmd['name']}", None)
            self.assertTrue(callable(fn), f"missing _h_{cmd['name']}")

    def test_module_declares_between_six_and_ten_commands(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        manifest = json.load(open(os.path.join(here, "module.json")))
        count = len(manifest["commands"])
        self.assertTrue(6 <= count <= 10, f"expected 6-10 commands, got {count}")


class TestListBookings(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_lists_bookings_and_uses_correct_api_version(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": [{"uid": "abc"}]})
        result = handler._h_list_bookings({"status": "upcoming"}, {})
        self.assertEqual(result["count"], 1)
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Cal-api-version"), "2026-05-01")
        self.assertIn("status=upcoming", sent_request.full_url)

    @patch("urllib.request.urlopen")
    def test_empty_list_when_no_bookings(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": []})
        result = handler._h_list_bookings({}, {})
        self.assertEqual(result, {"count": 0, "bookings": []})


class TestGetBooking(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_fetches_booking_and_uses_correct_api_version(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": {"uid": "abc", "status": "accepted"}})
        result = handler._h_get_booking({"booking_uid": "abc"}, {})
        self.assertEqual(result["booking"]["status"], "accepted")
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Cal-api-version"), "2026-02-25")
        self.assertIn("/bookings/abc", sent_request.full_url)

    def test_missing_booking_uid_raises(self):
        with self.assertRaises(handler.CalComError):
            handler._h_get_booking({}, {})


class TestGetAvailability(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_uses_correct_endpoint_params_and_api_version(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            {"data": {"2026-09-01": [{"start": "2026-09-01T09:00:00Z", "end": "2026-09-01T09:30:00Z"}]}}
        )
        result = handler._h_get_availability(
            {"event_type_id": 10, "start_date": "2026-09-01", "end_date": "2026-09-02"}, {}
        )
        self.assertIn("2026-09-01", result["slots"])
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Cal-api-version"), "2024-09-04")
        self.assertIn("eventTypeId=10", sent_request.full_url)
        self.assertIn("format=range", sent_request.full_url)

    def test_missing_required_field_raises(self):
        with self.assertRaises(handler.CalComError):
            handler._h_get_availability({"event_type_id": 10, "start_date": "2026-09-01"}, {})


class TestCreateBooking(unittest.TestCase):
    VALID_INPUTS = {
        "event_type_id": 123,
        "start_iso": "2026-09-01T09:00:00Z",
        "attendee_name": "Ana",
        "attendee_email": "ana@example.com",
        "attendee_timezone": "America/Argentina/Buenos_Aires",
    }

    @patch("urllib.request.urlopen")
    def test_creates_booking_with_correct_api_version(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": {"uid": "new-uid"}})
        result = handler._h_create_booking(self.VALID_INPUTS, {})
        self.assertEqual(result["booking"]["uid"], "new-uid")
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Cal-api-version"), "2026-02-25")

    def test_missing_required_field_raises(self):
        bad_inputs = dict(self.VALID_INPUTS)
        del bad_inputs["attendee_email"]
        with self.assertRaises(handler.CalComError):
            handler._h_create_booking(bad_inputs, {})


class TestRescheduleBooking(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_reschedules_booking_with_confirmed_api_version(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": {"uid": "abc", "start": "2026-09-02T09:00:00Z"}})
        result = handler._h_reschedule_booking(
            {"booking_uid": "abc", "new_start_iso": "2026-09-02T09:00:00Z"}, {}
        )
        self.assertEqual(result["booking"]["start"], "2026-09-02T09:00:00Z")
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Cal-api-version"), "2026-02-25")

    def test_missing_booking_uid_raises(self):
        with self.assertRaises(handler.CalComError):
            handler._h_reschedule_booking({"new_start_iso": "2026-09-02T09:00:00Z"}, {})


class TestCancelBooking(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_cancels_booking_with_correct_api_version_and_body(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": {"uid": "abc", "status": "cancelled"}})
        result = handler._h_cancel_booking({"booking_uid": "abc", "reason": "no longer needed"}, {})
        self.assertEqual(result["booking"]["status"], "cancelled")
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_header("Cal-api-version"), "2026-02-25")
        sent_body = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(sent_body["cancellationReason"], "no longer needed")

    def test_missing_booking_uid_raises(self):
        with self.assertRaises(handler.CalComError):
            handler._h_cancel_booking({}, {})


class TestProtectFocusTime(unittest.TestCase):
    VALID_INPUTS = {
        "event_type_id": 55,
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
        "attendee_name": "Ana",
        "attendee_email": "ana@example.com",
        "attendee_timezone": "UTC",
    }

    @patch("urllib.request.urlopen")
    def test_books_the_earliest_available_slot(self, mock_urlopen):
        availability_response = _mock_response({
            "data": {
                "2026-09-01": [
                    {"start": "2026-09-01T14:00:00Z", "end": "2026-09-01T14:30:00Z"},
                    {"start": "2026-09-01T09:00:00Z", "end": "2026-09-01T09:30:00Z"},
                ]
            }
        })
        booking_response = _mock_response({"data": {"uid": "focus-block-1", "start": "2026-09-01T09:00:00Z"}})
        mock_urlopen.side_effect = [availability_response, booking_response]

        result = handler._h_protect_focus_time(self.VALID_INPUTS, {})

        self.assertTrue(result["booked"])
        self.assertEqual(result["booking"]["start"], "2026-09-01T09:00:00Z")
        # Second call must be the booking POST, using the earliest slot found.
        second_request = mock_urlopen.call_args_list[1][0][0]
        sent_body = json.loads(second_request.data.decode("utf-8"))
        self.assertEqual(sent_body["start"], "2026-09-01T09:00:00Z")

    @patch("urllib.request.urlopen")
    def test_returns_not_booked_when_no_slots_available(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"data": {}})
        result = handler._h_protect_focus_time(self.VALID_INPUTS, {})
        self.assertFalse(result["booked"])
        self.assertIn("reason", result)

    def test_missing_required_field_raises(self):
        bad_inputs = dict(self.VALID_INPUTS)
        del bad_inputs["attendee_timezone"]
        with self.assertRaises(handler.CalComError):
            handler._h_protect_focus_time(bad_inputs, {})


class TestGetMeetingLoad(unittest.TestCase):
    def test_sums_duration_field_when_present(self):
        result = handler._h_get_meeting_load(
            {"bookings": [{"duration": 30}, {"duration": 60}, {"duration": 45}]}, {}
        )
        self.assertEqual(result["total_hours"], 2.25)
        self.assertEqual(result["meeting_count"], 3)

    def test_falls_back_to_start_end_when_no_duration_field(self):
        result = handler._h_get_meeting_load(
            {"bookings": [{"start": "2026-09-01T09:00:00Z", "end": "2026-09-01T10:30:00Z"}]}, {}
        )
        self.assertEqual(result["total_hours"], 1.5)

    def test_empty_list_returns_zero(self):
        result = handler._h_get_meeting_load({"bookings": []}, {})
        self.assertEqual(result, {"total_hours": 0.0, "meeting_count": 0})

    def test_missing_bookings_input_raises(self):
        with self.assertRaises(handler.CalComError):
            handler._h_get_meeting_load({}, {})


class TestVaultAndErrors(unittest.TestCase):
    def test_missing_credential_raises_clear_error(self):
        old_helpers = builtins.__rc_helpers__
        builtins.__rc_helpers__ = {"vault_get": lambda name: None}
        try:
            with self.assertRaises(handler.CalComError):
                handler._h_list_bookings({}, {})
        finally:
            builtins.__rc_helpers__ = old_helpers

    @patch("urllib.request.urlopen")
    def test_http_error_is_not_swallowed(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, MagicMock(read=lambda: b'{"error": "not found"}')
        )
        with self.assertRaises(handler.CalComError):
            handler._h_list_bookings({}, {})


if __name__ == "__main__":
    unittest.main()
