"""
Bridge to modules/calcom-pro/handlers/handler.py (already fixed
against Cal.com's real v2 API). Loaded by path with importlib, with a
unique module name, following the same pattern that avoids
collisions in the repo's tests (see modules/*/test/*.py).

Assumes the repo's folder structure as-is:
    <repo_root>/
      modules/calcom-pro/handlers/handler.py
      webapp/backend/calcom_client.py   <- this file

If you move webapp/ outside the repo, adjust REPO_ROOT.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HANDLER_PATH = REPO_ROOT / "modules" / "calcom-pro" / "handlers" / "handler.py"


def load_module_handler(module_dir: str):
    """Loads (or reloads) modules/{module_dir}/handlers/handler.py
    with a unique module name. Reloaded on every call instead of
    cached at the import level, so tests can mock `requests` in
    isolation without interference between cases, and so two
    different modules both named "handler.py" don't collide in
    sys.modules (the same bug already fixed in the repo's tests)."""
    path = REPO_ROOT / "modules" / module_dir / "handlers" / "handler.py"
    if not path.exists():
        raise RuntimeError(
            f"{path} was not found. This backend expects to live inside "
            f"the repo, next to modules/ (see REPO_ROOT in this file)."
        )
    unique_name = f"{module_dir.replace('-', '_')}_handler_live"
    spec = importlib.util.spec_from_file_location(unique_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_calcom_handler():
    """Historical alias -- equivalent to load_module_handler('calcom-pro')."""
    return load_module_handler("calcom-pro")
