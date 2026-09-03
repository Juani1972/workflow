"""
Isolated loading of provider modules for the GUI.

`team-health-analyzer`, `calcom-pro` and `gcal` each define an
`actions.py` (and `calcom-pro`/`gcal` also a `client.py`). All three
folders can't be on `sys.path` at the same time with a normal
`import`: `from actions import x` would always resolve to whichever
folder was inserted last, not the one needed each time — this bug was
found while writing `sync_service.py`'s tests (`ImportError` pulling
`calculate_meeting_load` from `gcal/actions.py` instead of
`team-health-analyzer/actions.py`).

Instead of keeping all three folders on `sys.path` at once, each
`load_*()` isolates its own `sys.path` and clears the `sys.modules`
cache for `actions` and `client` before importing, so each provider
always loads its own version — even when `actions.py` internally does
`from client import ...`, that import also resolves fresh against the
correct folder.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

MODULES_DIR = Path(__file__).resolve().parents[2] / "modules"
_GENERIC_MODULE_NAMES = ("actions", "client")


def _load_actions(module_dir_name: str) -> ModuleType:
    dir_path = str(MODULES_DIR / module_dir_name)

    if dir_path in sys.path:
        sys.path.remove(dir_path)
    sys.path.insert(0, dir_path)

    for name in _GENERIC_MODULE_NAMES:
        sys.modules.pop(name, None)

    return importlib.import_module("actions")


def load_team_health_analyzer() -> ModuleType:
    """Returns team-health-analyzer's actions.py module.

    Exposes: calculate_meeting_load, classify_team_health,
    rebalance_queue, summarize_team_report, update_threshold.
    """
    return _load_actions("team-health-analyzer")


def load_calcom_pro() -> ModuleType:
    """Returns calcom-pro's actions.py module.

    Exposes: list_bookings, create_booking, update_booking, and also
    CalComClient (it ends up in actions.py's namespace because
    `from client import CalComClient` is done there).
    """
    return _load_actions("calcom-pro")


def load_gcal() -> ModuleType:
    """Returns gcal's actions.py module.

    Exposes: list_events, create_event, update_event, delete_event,
    find_next_free_slot, and GCalClient (same reason as in calcom-pro).
    """
    return _load_actions("gcal")


def load_slack() -> ModuleType:
    """Returns slack's actions.py module.

    Exposes: post_message, build_summary_blocks, verify_slack_signature,
    parse_slash_command, parse_interactive_payload, and SlackClient
    (same reason as in calcom-pro/gcal).
    """
    return _load_actions("slack")
