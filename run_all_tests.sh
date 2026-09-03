#!/usr/bin/env bash
# run_all_tests.sh
#
# Runs ALL of the repo's test suites and shows a final summary.
#
# Why this exists: the modules under modules/, railcall-submission/
# and fika-sync/gui/tests use "flat" imports (`from client import
# ...`, `from actions import ...`, `from handler import ...`) with
# their own sys.path.insert() in each test, instead of full-package
# imports. Several different modules have files with the same name
# (client.py, actions.py, handler.py, test_handler.py...). A single
# `pytest` run from the repo root imports all of them into the same
# process, and Python caches each module name the first time it's
# seen — the second "client.py" that's imported ends up wrongly
# reusing the first one, and those tests fail even though the code
# is correct.
#
# The solution is to run each test folder in its own Python process
# (clean sys.modules in each one), which is exactly what this script
# does. It doesn't modify any existing module.
#
# Usage:
#   ./run_all_tests.sh          # runs everything, summary at the end
#   ./run_all_tests.sh -v       # also shows each suite's full output

set -uo pipefail
cd "$(dirname "$0")"

VERBOSE=0
if [[ "${1:-}" == "-v" ]]; then
  VERBOSE=1
fi

# Known test folders in the repo (relative to the root).
TEST_DIRS=(
  "fika-sync/gui/tests"
  "fika-sync/test"
  "modules/asana/test"
  "modules/budget-guardian-core/tests"
  "modules/calcom-pro/test"
  "modules/calcom-pro/tests"
  "modules/gcal/test"
  "modules/gcal/tests"
  "modules/meeting-debt-tracker/tests"
  "modules/notion/test"
  "modules/sheets/test"
  "modules/sheets/tests"
  "modules/slack/test"
  "modules/slack/tests"
  "modules/team-health-analyzer/test"
  "modules/team-health-analyzer/tests"
  "modules/zoom/test"
  "railcall-submission/calcom-pro/tests"
  "railcall-submission/gcal/tests"
  "railcall-submission/sheets/tests"
  "railcall-submission/slack/tests"
  "test"
  "webapp/backend"
)

total_passed=0
total_failed=0
total_skipped=0
failed_dirs=()

for dir in "${TEST_DIRS[@]}"; do
  if [[ ! -d "$dir" ]]; then
    echo "⚠️  Folder not found, skipping: $dir"
    continue
  fi

  output=$(cd "$dir" && python3 -m pytest -q . 2>&1)
  status=$?

  # Extract "N passed", "N failed", "N skipped" from the last summary line.
  passed=$(grep -oE '[0-9]+ passed' <<<"$output" | grep -oE '[0-9]+' || echo 0)
  failed=$(grep -oE '[0-9]+ failed' <<<"$output" | grep -oE '[0-9]+' || echo 0)
  skipped=$(grep -oE '[0-9]+ skipped' <<<"$output" | grep -oE '[0-9]+' || echo 0)
  errors=$(grep -oE '[0-9]+ error' <<<"$output" | grep -oE '[0-9]+' || echo 0)

  total_passed=$((total_passed + passed))
  total_failed=$((total_failed + failed))
  total_skipped=$((total_skipped + skipped))

  if [[ $status -ne 0 ]]; then
    failed_dirs+=("$dir")
    echo "❌ $dir  ($passed passed, $failed failed, $skipped skipped${errors:+, $errors errors})"
  else
    echo "✅ $dir  ($passed passed, $skipped skipped)"
  fi

  if [[ $VERBOSE -eq 1 || $status -ne 0 ]]; then
    echo "$output" | sed 's/^/    /'
    echo ""
  fi
done

echo ""
echo "================ SUMMARY ================"
echo "Total passed:  $total_passed"
echo "Total skipped: $total_skipped"
echo "Total failed:  $total_failed"

if [[ ${#failed_dirs[@]} -gt 0 ]]; then
  echo ""
  echo "Suites with failures:"
  for d in "${failed_dirs[@]}"; do
    echo "  - $d"
  done
  exit 1
fi

echo ""
echo "🎉 All suites passed."
exit 0
