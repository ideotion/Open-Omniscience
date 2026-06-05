#!/usr/bin/env bash
#
# Open Omniscience launcher  --  what the double-click icon runs.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# Starts the local web app (loopback only), waits until it is healthy, and opens
# your browser. Designed for non-technical users: it prints a clear banner and a
# single instruction -- close this window to stop the app.

set -euo pipefail

# Repo root = the directory above this script (scripts/ -> repo).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PORT="${OO_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

if [ ! -d .venv ]; then
    echo "Open Omniscience is not installed yet. Run ./install.sh in: $DIR" >&2
    read -r -p "Press Enter to close..." _ || true
    exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate

bold=$'\033[1m'; blu=$'\033[36m'; rst=$'\033[0m'
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
    if curl -fsS "$URL/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
done

# Open the default browser, cross-platform, best-effort.
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
elif command -v open    >/dev/null 2>&1; then open "$URL"    >/dev/null 2>&1 || true
else echo "  Open this address in your browser: $URL"
fi

# Keep running (and holding the server) until the user closes the window.
wait "$SERVER"
