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

# What the C library says as a process aborts (2026-10-17, the ten SIGABRTs of the three field sets): glibc writes
# "free(): invalid pointer" and its kind to STDERR, which is the launcher window, and nothing kept it -- the app's own
# crash trace holds the Python stacks and not this line, which is what separates heap corruption from an assert.
# The server's stderr now passes through a filter that (1) hands EVERY line on to the window unchanged, as before, and
# (2) records a line ONLY when the WHOLE line is exactly one of the fixed messages below (string equality, no pattern, no tail:
# "free(): anything else" is not one), at most STDERR_KEEP of them per launch; every other line is COUNTED and dropped, never
# stored, so nothing a log line could carry, a passphrase included, can reach the file. The app reads it at the next boot, checks
# each line against the same list (a test pins the two lists equal) and scrubs it again. If awk is missing the server starts
# exactly as before. One summary line per launch (the count of lines dropped) tells "the filter ran and saw nothing" from "no filter".
# glibc 2.41's messages (and the interpreter's fatal-error headers); musl, macOS libc and a newer glibc word theirs differently and
# are an OPEN ITEM, not covered: a message missing from this list is counted as dropped, never stored.
#
# THE NUMBERS. STDERR_KEEP (20 per launch) is what protects the file from one launch that prints the same message in a loop; the
# overflow is still counted (over_cap_lines). The file is trimmed to its newest 100 lines at each launch: five full launches of
# a crash loop, a bound on the file, not a view of how many launches there were.
STDERR_KEEP=20
STDERR_RECORD=""
STDERR_PIDFILE=""
STDERR_MESSAGES='malloc(): unaligned fastbin chunk detected
malloc(): unaligned fastbin chunk detected 2
malloc(): unaligned fastbin chunk detected 3
malloc(): memory corruption
malloc(): memory corruption (fast)
malloc(): unaligned tcache chunk detected
malloc(): smallbin double linked list corrupted
malloc(): invalid size (unsorted)
malloc(): invalid next size (unsorted)
malloc(): mismatching next->prev_size (unsorted)
malloc(): unsorted double linked list corrupted
malloc(): largebin double linked list corrupted (nextsize)
malloc(): largebin double linked list corrupted (bk)
malloc(): corrupted top size
malloc_consolidate(): unaligned fastbin chunk detected
malloc_consolidate(): invalid chunk size
munmap_chunk(): invalid pointer
realloc(): invalid pointer
realloc(): invalid next size
realloc(): invalid old size
free(): invalid pointer
free(): invalid size
free(): too many chunks detected in tcache
free(): unaligned chunk detected in tcache 2
free(): double free detected in tcache 2
free(): invalid next size (fast)
free(): invalid next size (normal)
free(): corrupted unsorted chunks
double free or corruption (fasttop)
double free or corruption (top)
double free or corruption (out)
double free or corruption (!prev)
corrupted size vs. prev_size
corrupted size vs. prev_size while consolidating
corrupted double-linked list
corrupted double-linked list (not small)
Fatal Python error: Aborted
Fatal Python error: Segmentation fault
Fatal Python error: Bus error
Fatal Python error: Illegal instruction
Fatal Python error: Floating point exception'
# The window's copy of stderr is made by `tee`, NOT by awk: some awks (mawk, the default on Debian and Ubuntu) read their whole
# input before they print, so a pass-through done by awk showed the window nothing until the server exited. awk reads only a COPY, so
# at worst it logs late: each recorded line's "at" is when the filter handled it (the end of the run on such an awk), not when the
# message was printed. The filter ignores INT, HUP, TERM and PIPE (the window's Ctrl-C or close reaches the whole process group; the
# server is stopped by this launcher's trap, the pipe then closes, and the filter writes its summary), takes its paths and list through
# the ENVIRONMENT (awk -v would treat a backslash in a folder name as an escape), and removes its own pid file at the end.
stderr_filter() {
    # (INT, HUP, TERM and PIPE are already ignored here: the caller sets them, and an ignored signal stays ignored in children)
    OO_SF_OUT="$STDERR_RECORD" OO_SF_PIDFILE="$STDERR_PIDFILE" OO_SF_BOOT="$1" OO_SF_KEEP="$STDERR_KEEP" \
    OO_SF_MSGS="$(printf '%s' "$STDERR_MESSAGES" | tr '\n' '|')" awk '
    BEGIN {
        out = ENVIRON["OO_SF_OUT"]; pidfile = ENVIRON["OO_SF_PIDFILE"]; boot = ENVIRON["OO_SF_BOOT"]; keep = ENVIRON["OO_SF_KEEP"] + 0
        n = split(ENVIRON["OO_SF_MSGS"], list, "|")
        for (i = 1; i <= n; i++) ok[list[i]] = 1
        kept = 0; dropped = 0; over = 0; thepid = ""
    }
    function stamp(   t) { t = ""; "date -u +%Y-%m-%dT%H:%M:%SZ" | getline t; close("date -u +%Y-%m-%dT%H:%M:%SZ"); return t }
    function pid(   p) {
        if (thepid != "") return thepid
        p = ""; if ((getline p < pidfile) > 0) {} ; close(pidfile)
        if (p ~ /^[0-9]+$/) thepid = p
        return (thepid != "") ? thepid : "null"
    }
    function bootj() { return (boot ~ /^[0-9a-f-]+$/) ? "\"" boot "\"" : "null" }
    {
        if ($0 in ok) {
            if (kept < keep) {
                printf "{\"schema\":\"oo-launcher-stderr-1\",\"at\":\"%s\",\"pid\":%s,\"boot_id\":%s,\"line\":\"%s\"}\n", stamp(), pid(), bootj(), $0 >> out
                kept++
            } else over++
        } else dropped++
    }
    END {
        printf "{\"schema\":\"oo-launcher-stderr-1\",\"at\":\"%s\",\"pid\":%s,\"boot_id\":%s,\"summary\":true,\"kept_lines\":%d,\"dropped_lines\":%d,\"over_cap_lines\":%d}\n", stamp(), pid(), bootj(), kept, dropped, over >> out
        q = pidfile; gsub(/\047/, "\047\\\047\047", q)
        system("rm -f -- \047" q "\047")
    }'
}

# Start the server in the background so we can wait for health, then open a browser.
#
# Cap glibc's malloc arenas at 2 for the SERVER (R114, the maintainer's ruling of 2026-10-01).
# glibc gives every busy thread an arena of its own, up to 8 per online CPU, and memory freed in an
# arena stays held by it until glibc can trim it (a freed chunk of more than about a kilobyte
# goes back to the arena that allocated it, whichever thread frees it; a smaller one waits in
# the freeing thread's own cache first): the app runs dozens of threads, and the one reading
# taken inside a death (2026-09-30) found 988.7 MB of 3,437 MB of anonymous memory freed but
# held by glibc's heap. A value the operator already chose (oo.env above, or the caller's
# environment) is kept, so this is only a default; unset or empty is no choice. glibc reads the
# variable once, when the server process starts, so it takes effect at the next launch; where
# the allocator is not glibc (macOS, Alpine, Windows) it does nothing, and the app's diagnostics
# say which allocator each session ran on.
#
# It is the SERVER's default, so it is given to the server's command alone and never exported:
# the browser opened below does not inherit it, and OO_ARENA_MAX_DEFAULTED=1 tells the server
# the number is this launcher's own, which is how the server keeps it out of the Ollama, vLLM
# and model-download processes it starts (src/llm/model_store.py, launch_env): nothing ruled or
# measured it for them, and the diagnostics report only the server's. A value the operator chose
# is theirs and carries no marker, so it reaches those too, as any environment variable does.
# `env` hands the value to the one command without assigning it in this shell, so an install
# file that declared the variable readonly cannot stop the app from starting.
unset OO_ARENA_MAX_DEFAULTED
STDERR_BOOT="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
_dd="$(oo_data_dir)"
# Not for an ephemeral run (its data folder is a temporary one; a record here would name the wrong place), and only where awk, tee and
# a writable record exist: anything else starts the server exactly as before.
if [ "${OO_EPHEMERAL:-}" != "1" ] && command -v awk >/dev/null 2>&1 && command -v tee >/dev/null 2>&1 \
        && mkdir -p "$_dd/diagnostics" 2>/dev/null; then
    STDERR_RECORD="$_dd/diagnostics/launcher_stderr.jsonl"
    # one pid file PER LAUNCH: two launchers started together must not read each other's server pid
    STDERR_PIDFILE="$_dd/diagnostics/.launcher_stderr.$$.pid"
    { : >> "$STDERR_RECORD"; } 2>/dev/null || STDERR_RECORD=""
    { : > "$STDERR_PIDFILE"; } 2>/dev/null || STDERR_RECORD=""
    # pid files left by a launcher that was killed outright
    find "$_dd/diagnostics" -maxdepth 1 -name '.launcher_stderr.*.pid' -mtime +1 -exec rm -f {} + 2>/dev/null || true
    # Bounded: the newest 100 lines are five full launches of a crash loop.
    if [ -n "$STDERR_RECORD" ] && [ "$({ wc -l < "$STDERR_RECORD"; } 2>/dev/null || echo 0)" -gt 100 ]; then
        { tail -n 100 "$STDERR_RECORD" > "$STDERR_RECORD.tmp" && mv -f "$STDERR_RECORD.tmp" "$STDERR_RECORD"; } 2>/dev/null || rm -f "$STDERR_RECORD.tmp"
    fi
    [ -n "$STDERR_RECORD" ] || STDERR_PIDFILE=""
fi
if [ -n "${MALLOC_ARENA_MAX:-}" ]; then
    if [ -n "$STDERR_RECORD" ]; then
        env MALLOC_ARENA_MAX="$MALLOC_ARENA_MAX" open-omniscience 2> >(trap '' INT HUP TERM PIPE; exec tee >(stderr_filter "$STDERR_BOOT") >&2) &
    else
        env MALLOC_ARENA_MAX="$MALLOC_ARENA_MAX" open-omniscience &
    fi
else
    if [ -n "$STDERR_RECORD" ]; then
        env MALLOC_ARENA_MAX=2 OO_ARENA_MAX_DEFAULTED=1 open-omniscience 2> >(trap '' INT HUP TERM PIPE; exec tee >(stderr_filter "$STDERR_BOOT") >&2) &
    else
        env MALLOC_ARENA_MAX=2 OO_ARENA_MAX_DEFAULTED=1 open-omniscience &
    fi
fi
SERVER=$!
# A failed write here (disk full, a pid file that is not ours) must never end the launcher: this line runs before its traps exist.
[ -z "$STDERR_PIDFILE" ] || { printf '%s\n' "$SERVER" > "$STDERR_PIDFILE"; } 2>/dev/null || true
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
