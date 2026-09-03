#!/usr/bin/env python3
"""
Validates that every node in every workflow.csv references a module and
an action that ACTUALLY EXIST in modules/*/module.json.

This catches the class of bug `railcall audit` would detect in its
engine, but that can be checked locally without the proprietary CLI:
misspelled slugs, nonexistent modules, and undeclared action_ids.

Usage:  python3 tools/validate_workflows.py
Exits with code 1 if there are errors (useful for CI).
"""
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_modules() -> dict:
    """slug/module_id -> set of declared action/command names.

    This repo has two manifest conventions under `modules/*/`,
    depending on which session wrote each module:
    - `module.json`: `slug` field, `commands` list (each with a
      `name`) — the RailCall marketplace-style format.
    - `module_spec.json`: `module_id` field, `actions` list (each
      with a `name`) — the older internal format, still the only one
      some modules in this codebase have.
    Both are read and merged; if a module has both files,
    `module.json` wins (it's the newer one)."""
    modules = {}
    for spec_path in sorted(REPO.glob("modules/*/module_spec.json")):
        data = json.loads(spec_path.read_text())
        names = {a["name"] for a in data.get("actions", [])}
        modules[data["module_id"]] = names
    for module_json in sorted(REPO.glob("modules/*/module.json")):
        data = json.loads(module_json.read_text())
        names = {c["name"] for c in data.get("commands", [])}
        modules[data["slug"]] = names
    return modules


def load_unimplemented() -> dict:
    """Modules known to be missing and why (see the JSON for detail).
    Reported as a warning, not an error, so they're not confused with
    genuinely broken references."""
    path = REPO / "tools" / "unimplemented_modules.json"
    if not path.exists():
        return {}
    return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}


def find_workflows() -> list:
    return sorted(REPO.glob("**/workflow.csv"))


def validate(modules: dict) -> tuple:
    errors, warnings = [], []
    for csv_path in find_workflows():
        rel = csv_path.relative_to(REPO)
        with csv_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        ids = [r["node_id"] for r in rows]
        for r in rows:
            nid = r["node_id"]
            where = f"{rel}[{nid}]"

            # inputs must be valid JSON
            raw_inputs = (r.get("inputs") or "").strip()
            if raw_inputs:
                try:
                    json.loads(raw_inputs)
                except json.JSONDecodeError as e:
                    errors.append(f"{where} inputs is not valid JSON: {e}")

            # depends_on must point to existing nodes
            deps = (r.get("depends_on") or "").strip()
            for d in [x.strip() for x in deps.split(";") if x.strip()]:
                if d not in ids:
                    errors.append(f"{where} depends_on points to a nonexistent node '{d}'")

            # module + action resolution
            mod = (r.get("module_dependency") or "").strip()
            action = (r.get("action_id") or "").strip()
            if not mod:
                continue  # pure transform node, no module -- ok

            if mod not in modules:
                known = load_unimplemented()
                if mod in known:
                    warnings.append(
                        f"{where} uses '{mod}', deliberately not implemented: "
                        f"{known[mod]['blocker']}"
                    )
                else:
                    errors.append(
                        f"{where} references module '{mod}', which does NOT exist in modules/. "
                        f"Available slugs: {sorted(modules)}"
                    )
                continue

            # triggers use action_ids like 'webhook.x' / 'cron.x', which
            # are runtime capabilities, not module commands
            if r.get("type") == "trigger" or action.startswith(("webhook.", "cron.")):
                continue

            if action not in modules[mod]:
                errors.append(
                    f"{where} uses action '{action}', which is NOT declared in {mod}. "
                    f"Available actions: {sorted(modules[mod])}"
                )
    return errors, warnings


def main() -> int:
    modules = load_modules()
    print(f"Modules found ({len(modules)}):")
    for slug, cmds in sorted(modules.items()):
        print(f"  {slug}: {len(cmds)} actions")
    print()

    errors, warnings = validate(modules)
    for w in warnings:
        print(f"  WARNING {w}")
    for e in errors:
        print(f"  ERROR {e}")

    print()
    if errors:
        print(f"FAILED: {len(errors)} broken references.")
        return 1
    print("OK: every node resolves to an existing module and action.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
