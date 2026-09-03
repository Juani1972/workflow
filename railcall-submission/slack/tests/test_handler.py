"""Unit tests for juani1972/slack, with urllib.urlopen mocked.

Run: python3 -m pytest railcall-submission/slack/tests -q (from repo
root) or `python3 -m pytest tests -q` from this module's directory.

No network calls — validates handler logic (input validation, the
`_h_*` naming the RailCall loader requires, and specifically Slack's
"HTTP 200 but ok: false" failure pattern, which is the part most
likely to be implemented wrong). See ESTADO.md for what still needs a
real Station install / workspace.
"""

from __future__ import annotations

import builtins
import importlib.util
import json
import os
import unittest
from unittest.mock import MagicMock, patch


def _load_handler():
    builtins.__rc_helpers__ = {"vault_get": lambda name: {"bot_token": "xoxb-fake"}}
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "handlers", "handler.py")
    spec = importlib.util.spec_from_file_location("slack_handler", path)
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


class TestListChannels(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_lists_channels(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            {"ok": True, "channels": [{"id": "C1", "name": "fika-sync"}]}
        )
        result = handler._h_list_channels({}, {})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["channels"][0]["name"], "fika-sync")

    @patch("urllib.request.urlopen")
    def test_default_limit_is_100(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"ok": True, "channels": []})
        handler._h_list_channels({}, {})
        sent_request = mock_urlopen.call_args[0][0]
        self.assertIn("limit=100", sent_request.full_url)


class TestPostMessage(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_posts_message(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response({"ok": True, "channel": "C1", "ts": "123.456"})
        result = handler._h_post_message({"channel": "#fika-sync", "text": "hola equipo"}, {})
        self.assertEqual(result["ts"], "123.456")

    def test_missing_text_raises(self):
        with self.assertRaises(handler.SlackError):
            handler._h_post_message({"channel": "#fika-sync"}, {})

    @patch("urllib.request.urlopen")
    def test_http_200_with_ok_false_is_treated_as_failure(self, mock_urlopen):
        """The Slack-specific detail flagged in the handler docstring:
        Slack answers HTTP 200 even on failure. A naive implementation
        checking only the HTTP status would silently swallow this."""
        mock_urlopen.return_value = _mock_response({"ok": False, "error": "channel_not_found"})
        with self.assertRaises(handler.SlackError) as ctx:
            handler._h_post_message({"channel": "#nonexistent", "text": "hola"}, {})
        self.assertIn("channel_not_found", str(ctx.exception))


class TestVaultAndErrors(unittest.TestCase):
    def test_missing_credential_raises_clear_error(self):
        old_helpers = builtins.__rc_helpers__
        builtins.__rc_helpers__ = {"vault_get": lambda name: None}
        try:
            with self.assertRaises(handler.SlackError):
                handler._h_list_channels({}, {})
        finally:
            builtins.__rc_helpers__ = old_helpers

    @patch("urllib.request.urlopen")
    def test_http_error_is_not_swallowed(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 403, "Forbidden", {}, MagicMock(read=lambda: b'{"error": "invalid_auth"}')
        )
        with self.assertRaises(handler.SlackError):
            handler._h_list_channels({}, {})


if __name__ == "__main__":
    unittest.main()
