#!/usr/bin/env bash
# start_fika_sync.sh — starts the server in the background (without
# staying tied to this terminal) and opens the interface in the
# browser.
#
# On Windows, "Start Fika Sync.bat" directly minimizes the console
# window. Here, the equivalent is running the server as a background
# process (nohup) so it doesn't block the terminal, and as a bonus,
# trying to minimize the terminal window if the environment allows
# it (best effort, not guaranteed on every system).
set -uo pipefail

cd "$(dirname "$0")/fika-sync/gui"

if command -v python3 &>/dev/null; then
    PYCMD=python3
elif command -v python &>/dev/null; then
    PYCMD=python
else
    echo "Python was not found installed."
    echo "Run ./install.sh first"
    exit 1
fi

if [ ! -f app.py ]; then
    echo "fika-sync/gui/app.py was not found"
    echo "Make sure you run this script from the project folder."
    exit 1
fi

PID_FILE="/tmp/fika_sync_server.pid"

# If a server is already running (from a previous run), don't start
# a new one — just reopen the browser.
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Fika Sync is already running (PID $(cat "$PID_FILE")). Opening the browser..."
else
    echo "Starting the Fika Sync server..."
    nohup "$PYCMD" app.py > /tmp/fika_sync_server.log 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
fi

# Open the browser with the interface.
if command -v xdg-open &>/dev/null; then
    xdg-open http://127.0.0.1:5000 &>/dev/null &
elif command -v open &>/dev/null; then
    open http://127.0.0.1:5000
else
    echo "Open http://127.0.0.1:5000 manually in your browser."
fi

# Attempt to minimize this terminal (best effort — depends on the
# system and which terminal app you're using; if it doesn't work,
# nothing breaks, the server keeps running in the background anyway).
if [[ "${OSTYPE:-}" == darwin* ]]; then
    osascript -e 'tell application "Terminal" to set miniaturized of front window to true' 2>/dev/null || true
elif command -v wmctrl &>/dev/null; then
    sleep 1
    wmctrl -r ":ACTIVE:" -b add,hidden 2>/dev/null || true
fi

echo
echo "Fika Sync running at http://127.0.0.1:5000"
echo "To stop it: ./stop_fika_sync.sh"
