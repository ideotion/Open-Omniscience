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

# Where the app keeps its data: the SAME precedence as src/paths.py:data_dir(), which a
# test pins this function against -- OO_DATA_DIR, then a writable source checkout's
# data/, then the per-user XDG location.
oo_data_dir() {
    if [ -n "${OO_DATA_DIR:-}" ]; then
        case "$OO_DATA_DIR" in
            "~") printf '%s\n' "$HOME" ;;
            "~/"*) printf '%s\n' "$HOME/${OO_DATA_DIR#\~/}" ;;
            *) printf '%s\n' "$OO_DATA_DIR" ;;
        esac
    elif [ -f "$DIR/pyproject.toml" ] && [ -w "$DIR" ]; then
        printf '%s\n' "$DIR/data"
    else
        printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/open-omniscience"
    fi
}

# How the server ended when this launcher did not stop it (2026-09-26, the daily-crash
# field reports). A process killed with SIGKILL -- the kernel's OOM killer,
# systemd-oomd, earlyoom, a `kill -9` -- runs no code of its own, so its exit status
# is the only account of the death, and only this parent holds it. Before this, the
# window closed as the server died and took the answer with it. One JSON line per
# such exit; the app's next boot reads the line naming its previous pid AND boot (a
# pid alone repeats across reboots). Sets EXIT_RECORD to the file on success.
EXIT_RECORD=""
record_exit() {
    local status="$1" name="" sig_json="null" boot boot_json="null" dd f
    if [ "$status" -gt 128 ]; then
        name="$(kill -l "$((status - 128))" 2>/dev/null || true)"
        [ -n "$name" ] && sig_json="\"SIG${name#SIG}\""
    fi
    boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
    case "$boot" in
        ""|*[!0-9a-f-]*) ;;
        *) boot_json="\"$boot\"" ;;
    esac
    dd="$(oo_data_dir)"
    f="$dd/diagnostics/launcher_exits.jsonl"
    mkdir -p "$dd/diagnostics" 2>/dev/null || return 1
    printf '{"schema":"oo-launcher-exit-1","at":"%s","started_at":"%s","pid":%s,"boot_id":%s,"status":%s,"signal":%s}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SERVER_STARTED_AT" "$SERVER" "$boot_json" "$status" "$sig_json" \
        >> "$f" 2>/dev/null || return 1
    EXIT_RECORD="$f"
    # Bounded: the newest 20 exits are plenty to see a pattern, and a crash loop must
    # never grow this file without limit.
    if [ "$(wc -l < "$f" 2>/dev/null || echo 0)" -gt 40 ]; then
        tail -n 20 "$f" > "$f.tmp" 2>/dev/null && mv -f "$f.tmp" "$f" 2>/dev/null || rm -f "$f.tmp"
    fi
}

# Start the server in the background so we can wait for health, then open a browser.
open-omniscience &
SERVER=$!
SERVER_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
# Stop the server when this launcher exits (window closed / Ctrl-C).
# HUP is in the list because it is the signal the ADVERTISED stop actually sends:
# closing the terminal window HUPs the foreground process group. Without it bash
# takes SIGHUP's default disposition and the EXIT trap is not a reliable path
# (2026-09-02, S0.2). The server also installs its own SIGHUP handler, so the stop
# is graceful whether the signal reaches it directly or through this trap.
# STOP_REQUESTED marks the stop as ASKED FOR before the server is signalled, so the
# exit check below never records a stop the user made as a crash.
STOP_REQUESTED=0
trap 'STOP_REQUESTED=1; kill "$SERVER" 2>/dev/null || true' INT TERM HUP
trap 'kill "$SERVER" 2>/dev/null || true' EXIT

# Wait up to ~20s for the health endpoint.
for _ in $(seq 1 40); do
    if curl -fsS "${BASE}/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
done

open_browser "$URL"

# Keep running (and holding the server) until the user closes the window.
status=0
wait "$SERVER" || status=$?
if [ "$STOP_REQUESTED" = 0 ] && [ "$status" -ne 0 ]; then
    record_exit "$status" || true
    case "$status" in
        # SIGHUP/SIGINT/SIGTERM: a stop somebody ASKED for, just not through this
        # window -- the app's own Stop button (it SIGTERMs itself), a logout, a service
        # manager, a plain kill. uvicorn re-raises the stop signal once its graceful
        # shutdown is done (measured: the parent sees 143), so this is what a requested
        # stop looks like from here. Recorded, so a teardown that did not finish can be
        # told apart on the next boot, but no alarm: the window closes as it always did.
        129|130|143) ;;
        *)
            echo
            case "$status" in
                137) echo "${bold}Open Omniscience was ended from outside without warning (SIGKILL).${rst}"
                     echo "The usual cause is a low-memory killer on this computer." ;;
                132|134|135|136|139) echo "${bold}Open Omniscience crashed (exit status $status).${rst}" ;;
                *)   echo "${bold}Open Omniscience stopped unexpectedly (exit status $status).${rst}"
                     echo "The messages above may say why." ;;
            esac
            [ -n "$EXIT_RECORD" ] && echo "Recorded in $EXIT_RECORD for the app's diagnostics."
            echo
            # The window stays open so this can be read: it used to vanish with the server.
            read -r -p "Press Enter to close this window..." _ || true
            ;;
    esac
fi
exit "$status"
