"""Unit tests for juani1972/sheets, with urllib.urlopen mocked.

Run: python3 -m pytest railcall-submission/sheets/tests -q (from repo
root) or `python3 -m pytest tests -q` from this module's directory.

No network calls — validates handler logic (input validation, request
shaping, error propagation, the `_h_*` naming the RailCall loader
requires). See ESTADO.md for what still needs a real Station install.
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
    spec = importlib.util.spec_from_file_location("sheets_handler", path)
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


class TestReadValues(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_reads_values(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"values": [["2026-09-01", "ana", "22.0", "red"]]})
        result = handler._h_read_values({"spreadsheet_id": "abc123", "range": "Sheet1!A1:D1"}, {})
        self.assertEqual(result["values"], [["2026-09-01", "ana", "22.0", "red"]])

    @patch("urllib.request.urlopen")
    def test_empty_range_returns_empty_list(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({})
        result = handler._h_read_values({"spreadsheet_id": "abc123", "range": "Sheet1!A1:D1"}, {})
        self.assertEqual(result["values"], [])

    def test_missing_range_raises(self):
        with self.assertRaises(handler.SheetsError):
            handler._h_read_values({"spreadsheet_id": "abc123"}, {})


class TestAppendRow(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_appends_row(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            {"updates": {"updatedRange": "Sheet1!A5:D5", "updatedRows": 1}}
        )
        result = handler._h_append_row(
            {"spreadsheet_id": "abc123", "range": "Sheet1!A:D", "values": ["2026-09-01", "ana", "22.0", "red"]},
            {},
        )
        self.assertEqual(result["updated_rows"], 1)
        self.assertEqual(result["updated_range"], "Sheet1!A5:D5")

    def test_values_must_be_a_list(self):
        with self.assertRaises(handler.SheetsError):
            handler._h_append_row(
                {"spreadsheet_id": "abc123", "range": "Sheet1!A:D", "values": "not-a-list"}, {}
            )

    def test_missing_values_raises(self):
        with self.assertRaises(handler.SheetsError):
            handler._h_append_row({"spreadsheet_id": "abc123", "range": "Sheet1!A:D"}, {})


class TestVaultAndErrors(unittest.TestCase):
    def test_missing_credential_raises_clear_error(self):
        old_helpers = builtins.__rc_helpers__
        builtins.__rc_helpers__ = {"vault_get": lambda name: None}
        try:
            with self.assertRaises(handler.SheetsError):
                handler._h_read_values({"spreadsheet_id": "x", "range": "y"}, {})
        finally:
            builtins.__rc_helpers__ = old_helpers

    @patch("urllib.request.urlopen")
    def test_http_error_is_not_swallowed(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 404, "Not Found", {}, MagicMock(read=lambda: b'{"error": "not found"}')
        )
        with self.assertRaises(handler.SheetsError):
            handler._h_read_values({"spreadsheet_id": "x", "range": "y"}, {})


if __name__ == "__main__":
    unittest.main()
