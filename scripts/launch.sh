#!/usr/bin/env bash
#
# Open Omniscience launcher  --  what the double-click icons run.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# Starts the local web app (loopback only), waits until it is healthy, and opens
# your browser. Designed for non-technical users: it prints a clear banner and a
# single instruction -- close this window to stop the app.
#
# Usage: launch.sh [console]
#   There is ONE interface (maintainer verdict 2026-06-10). Any argument --
#   including "desk" from an old launcher icon -- opens the app at /.
#   If a server is already running, this just opens your browser.

set -euo pipefail

UI_PATH="/"; UI_NAME="Console"

# Repo root = the directory above this script (scripts/ -> repo).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

# Persistent app environment (A11): if the installer recorded settings -- notably an
# opt-in persistent OO_DATA_DIR pointing at a bind-mounted/external volume so the corpus
# survives on a disposable/ephemeral VM -- load them so every launch uses that location.
# The file lives in the install tree (0600, owner-only); a plain KEY='value' env file.
if [ -f "$DIR/oo.env" ]; then
    # shellcheck disable=SC1091
    . "$DIR/oo.env" || true
fi

PORT="${OO_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
URL="${BASE}${UI_PATH}"

open_browser() {
    if   command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
    elif command -v open     >/dev/null 2>&1; then open "$1"     >/dev/null 2>&1 || true
    else echo "  Open this address in your browser: $1"
    fi
}

# If a server is already healthy, just open the browser and exit -- never
# start a second one.
if curl -fsS "${BASE}/api/health" >/dev/null 2>&1; then
    echo "Open Omniscience is already running -- opening it in your browser."
    open_browser "$URL"
    exit 0
fi

if [ ! -d .venv ]; then
    echo "Open Omniscience is not installed yet. Run ./install.sh in: $DIR" >&2
    read -r -p "Press Enter to close..." _ || true
    exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate || true
# A venv breaks if the system Python changed under it (e.g. an OS update between
# launches) -- the app then fails to start from the icon until reinstalled. Detect
# that HERE and tell the user exactly what to do, instead of exiting cryptically
# (which can make the launcher window vanish before the error is read).
if ! command -v open-omniscience >/dev/null 2>&1; then
    echo "Open Omniscience can't start: its Python environment looks broken" >&2
    echo "(this usually happens when the system Python changed after an OS update)." >&2
    echo "Repair it by re-running the installer:" >&2
    echo "    $DIR/install.sh" >&2
    read -r -p "Press Enter to close..." _ || true
    exit 1
fi

bold=$'\033[1m'; blu=$'\033[36m'; rst=$'\033[0m'
[ -f "$DIR/assets/logo.txt" ] && { printf '\n%s' "$blu$bold"; cat "$DIR/assets/logo.txt"; printf '%s' "$rst"; }
cat <<EOF

${bold}${blu}Open Omniscience${rst} is starting...

  Your browser will open at: ${bold}${URL}${rst}
  ${bold}To stop the app:${rst} close this window (or press Ctrl-C).

EOF

# Start the server in the background so we can wait for health, then open a browser.
open-omniscience &
SERVER=$!
# Stop the server when this launcher exits (window closed / Ctrl-C).
trap 'kill "$SERVER" 2>/dev/null || true' EXIT INT TERM

# Wait up to ~20s for the health endpoint.
for _ in $(seq 1 40); do
    if curl -fsS "${BASE}/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
done

open_browser "$URL"

# Keep running (and holding the server) until the user closes the window.
wait "$SERVER"
