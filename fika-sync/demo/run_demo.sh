#!/usr/bin/env bash
# demo/run_demo.sh — shows the full workflow in dry-run mode.
#
# Doesn't connect real accounts or spend airlock quota: `railcall workflow
# run` is dry-run by default (only --live sends anything real). Meant for
# recording the 2-3 min video the contest asks for.
#
# Usage:
#   chmod +x demo/run_demo.sh
#   ./demo/run_demo.sh

set -euo pipefail

echo "== 1/4: Checking RailCall installation =="
railcall version

echo ""
echo "== 2/4: Structural workflow audit (read-only, zero-retention) =="
railcall audit workflow.csv

echo ""
echo "== 3/4: Compiling the workflow (generates a signed receipt) =="
railcall build workflow.csv

echo ""
echo "== 4/4: Running in DRY-RUN (nothing real is sent; you'll see the airlock preview) =="
railcall workflow run workflow.csv

echo ""
echo "Done. To run for real (with TEST accounts connected in Studio):"
echo "  railcall workflow run workflow.csv --live"
echo ""
echo "To verify the latest signed receipt with no network:"
echo "  railcall verify"
