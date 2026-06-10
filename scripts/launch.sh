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
. .venv/bin/activate

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
