#!/usr/bin/env bash
# install.sh — installs the Fika Sync GUI's dependencies.
set -euo pipefail

cd "$(dirname "$0")/fika-sync/gui"

echo "============================================"
echo "  Installing Fika Sync"
echo "============================================"
echo

if command -v python3 &>/dev/null; then
    PYCMD=python3
elif command -v python &>/dev/null; then
    PYCMD=python
else
    echo "ERROR: Python was not found installed."
    echo "Install it from https://www.python.org/downloads/"
    echo "(on Mac you can also use 'brew install python3')."
    exit 1
fi

echo "Python found: $($PYCMD --version)"
echo

if [ ! -f requirements.txt ]; then
    echo "ERROR: fika-sync/gui/requirements.txt was not found"
    echo "Make sure you run this script from the project folder,"
    echo "without moving or renaming folders."
    exit 1
fi

echo "Installing dependencies (Flask, requests)..."
echo

if ! "$PYCMD" -m pip install -r requirements.txt; then
    echo
    echo "Retrying with --break-system-packages"
    echo "(needed on some systems where Python is managed"
    echo "by the OS, like recent Ubuntu/Debian)..."
    "$PYCMD" -m pip install -r requirements.txt --break-system-packages
fi

echo
echo "============================================"
echo "  Installation complete"
echo "============================================"
echo
echo "You can now run ./start_fika_sync.sh to open the application."
