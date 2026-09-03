#!/usr/bin/env bash
# stop_fika_sync.sh — shuts down the server left running in the
# background after using start_fika_sync.sh.
set -uo pipefail

PID_FILE="/tmp/fika_sync_server.pid"

if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill "$PID" 2>/dev/null; then
        echo "Server stopped (PID $PID)."
    else
        echo "Could not stop process $PID (it may no longer exist)."
    fi
    rm -f "$PID_FILE"
else
    echo "No running Fika Sync server was found (or it was started from another session/terminal)."
    echo "You can look for it manually with: ps aux | grep 'app.py'"
fi
