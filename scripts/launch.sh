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

# --- the evidence files and the launchers that share them (R173, 17 Oct) ---------------------------------------------------------------------
# launcher_exits.jsonl, launcher_stops.jsonl and launcher_stderr.jsonl are written and trimmed by every launcher that runs, and a launcher keeps
# writing for as long as its server lives. A trim is "newest N lines to a temp file, rename over the file": an append between the two steps went
# to the replaced file, two trims shared one temp name, and the stderr filter held the file open for the whole life of the server, so a trim by
# launcher's trim sent every later row of a live one to a file nobody could read (measured: 8 of 96 exit rows, 69 of 96 stop rows, and all 3 stderr
# rows of the launcher whose server was alive, in tests/test_launcher_records_race.py). Now every append and every trim of one file happens under
# ONE lock for that file (flock where there is one, else a directory made with mkdir that holds its owner's pid, so a lock whose owner died is taken
# over and never waited on), a trim writes to a temp name of its own, and the filter appends one row at a time.
# WHAT THE WAIT PROTECTS: a row is never lost to wait for a lock. When the wait runs out the row is still appended and only the trim is skipped
# (the file grows until the next trim that gets the lock). The launcher never blocks its own start or stop on this lock longer than the wait.
# OO_REC_LOCK_WAIT_MS is the longest append-plus-trim hold measured under 8 launchers at once (27.3 ms, 17 Oct), rounded up to 30 (tests/test_launcher_records_race.py
# pins that the constant is not below that measurement).
OO_REC_LOCK_WAIT_MS=30

oo_pid_alive() {
    if [ -d /proc/self ]; then [ -d "/proc/$1" ]; else kill -0 "$1" 2>/dev/null; fi
}

# oo_rec_locked FILE CMD [ARGS...]: run CMD holding the lock of FILE. Returns 99 when the lock was not obtained in time (CMD did not run),
# else CMD's own status.
oo_rec_locked() {
    local f="$1" rc=0 d tries owner
    shift
    if command -v flock >/dev/null 2>&1; then
        { : >> "$f.lock"; } 2>/dev/null || return 99
        (
            flock -w "$(awk -v ms="$OO_REC_LOCK_WAIT_MS" 'BEGIN { printf "%.3f", ms / 1000 }')" 9 || exit 99
            "$@"
        ) 9>>"$f.lock" 2>/dev/null || rc=$?
        return "$rc"
    fi
    d="$f.lock.d"
    tries=$(( OO_REC_LOCK_WAIT_MS / 10 + 1 ))
    while :; do
        if mkdir "$d" 2>/dev/null; then
            printf '%s\n' "$$" > "$d/pid" 2>/dev/null || true
            "$@" || rc=$?
            rm -rf "$d" 2>/dev/null || true
            return "$rc"
        fi
        owner="$(cat "$d/pid" 2>/dev/null || true)"
        case "$owner" in ''|*[!0-9]*) owner="" ;; esac
        # the owner is gone: the lock is taken over. mv is atomic, so of two launchers taking it over only one moves it.
        if [ -n "$owner" ] && ! oo_pid_alive "$owner"; then
            mv "$d" "$d.dead.$$" 2>/dev/null && rm -rf "$d.dead.$$" 2>/dev/null
        fi
        tries=$((tries - 1))
        [ "$tries" -gt 0 ] || return 99
        sleep 0.01 2>/dev/null || sleep 1
    done
}

# append ROW to FILE and, when FILE then has more than MAX lines (MAX 0: never), keep its newest KEEP lines
_oo_rec_append_trim() {
    local f="$1" row="$2" max="$3" keep="$4"
    printf '%s\n' "$row" >> "$f" 2>/dev/null || return 1
    _oo_rec_trim "$f" "$max" "$keep"
    return 0
}
_oo_rec_trim() {
    local f="$1" max="$2" keep="$3"
    [ "$max" -gt 0 ] || return 0
    if [ "$(wc -l < "$f" 2>/dev/null || echo 0)" -gt "$max" ]; then
        # a temp file left by a launcher that was killed between its tail and its mv is removed here: its name carries that launcher pid
        for _t in "$f".tmp.*; do
            [ -e "$_t" ] || continue
            _tp="${_t##*.tmp.}"
            case "$_tp" in ''|*[!0-9]*) continue ;; esac
            [ "$_tp" = "$$" ] || oo_pid_alive "$_tp" || rm -f "$_t" 2>/dev/null
        done
        tail -n "$keep" "$f" > "$f.tmp.$$" 2>/dev/null && mv -f "$f.tmp.$$" "$f" 2>/dev/null || rm -f "$f.tmp.$$"
    fi
    return 0
}
# oo_rec_append FILE ROW MAX KEEP: 0 appended, 1 the append failed
oo_rec_append() {
    local rc=0
    oo_rec_locked "$1" _oo_rec_append_trim "$1" "$2" "$3" "$4" || rc=$?
    if [ "$rc" -eq 99 ]; then
        printf '%s\n' "$2" >> "$1" 2>/dev/null || return 1
        return 0
    fi
    return "$rc"
}
oo_rec_trim() {
    oo_rec_locked "$1" _oo_rec_trim "$1" "$2" "$3" || true
}
# the stderr filter hands each row to this, on stdin
oo_rec_append_stdin() {
    local row=""
    IFS= read -r row || true
    oo_rec_append "$1" "$row" 0 0
}
# The text of the helpers, for the filter: awk starts the appending shell itself, and a function exported through the environment does not reach it under
# every awk and sh (measured: the one-true-awk lost every row, silently, with a close status of 0), so the shell is handed the definitions to eval.
oo_rec_lib() { declare -f oo_pid_alive oo_rec_locked _oo_rec_append_trim _oo_rec_trim oo_rec_append oo_rec_append_stdin; }
# --- end of the evidence file helpers ------------------------------------------------------------------------------------------------------

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
    # Bounded: the newest 20 exits are plenty to see a pattern, and a crash loop must
    # never grow this file without limit.
    oo_rec_append "$f" "$(printf '{"schema":"oo-launcher-exit-1","at":"%s","started_at":"%s","pid":%s,"boot_id":%s,"status":%s,"signal":%s}' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SERVER_STARTED_AT" "$SERVER" "$boot_json" "$status" "$sig_json")" 40 20 || return 1
    EXIT_RECORD="$f"
}

# A STOP SOMEBODY ASKED FOR (R168, 17 Oct). record_exit writes nothing for a stop the window itself saw (STOP_REQUESTED), so an end whose
# teardown did not finish after a Ctrl-C, a closed window or a service stop looked, at the next boot, like a SIGKILL. This writes one small row
# BEFORE anything is forwarded: the signal trapped (INT, TERM or HUP), the server's pid, the machine boot and the time. Nothing from the
# environment or the command line. The app reads it only when the previous session did not end cleanly, and says "stop requested, teardown
# incomplete" instead of leaving the end unexplained. Never fails the stop: every error is swallowed. Bounded like the exit record.
record_stop() {
    local name="$1" boot boot_json="null" dd f
    boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"
    case "$boot" in
        ""|*[!0-9a-f-]*) ;;
        *) boot_json="\"$boot\"" ;;
    esac
    dd="$(oo_data_dir)" || return 0
    f="$dd/diagnostics/launcher_stops.jsonl"
    mkdir -p "$dd/diagnostics" 2>/dev/null || return 0
    oo_rec_append "$f" "$(printf '{"schema":"oo-launcher-stop-1","at":"%s","pid":%s,"boot_id":%s,"signal":"SIG%s"}' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SERVER" "$boot_json" "$name")" 40 20 || true
    return 0
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
# macOS libmalloc words its aborts with the program name, pid, thread and an object address in the line, so they are matched as ONE extended
# regular expression over the WHOLE line (src/monitoring/exit_evidence.py MAC_ABORT_TAILS builds it, a test pins this copy equal to it).
# The variable parts are limited to name characters, digits and hex, so no free text can ride along. POSIX ERE with no intervals: mawk, gawk,
# the one-true-awk macOS ships and busybox awk read it alike. UNTESTED ON macOS ITSELF (see docs/ledger/OPEN_QUEUE.md).
STDERR_MAC_RE='^[A-Za-z0-9._+-]+\([0-9]+,0x[0-9a-f]+\) malloc: (\*\*\* set a breakpoint in malloc_error_break to debug|\*\*\* error for object 0x[0-9a-f]+: pointer being freed was not allocated|pointer 0x[0-9a-f]+ being freed was not allocated|pointer 0x[0-9a-f]+ being freed already on death-row|pointer 0x[0-9a-f]+ being reallocated was not allocated|pointer 0x[0-9a-f]+ of size zero being freed|large entry 0x[0-9a-f]+ reallocated is not properly in table|Non-aligned pointer 0x[0-9a-f]+ being freed|Non-aligned pointer 0x[0-9a-f]+ being freed \(2\)|Pointer 0x[0-9a-f]+ to metadata being freed|Pointer 0x[0-9a-f]+ to metadata being freed \(2\)|non-page-aligned, non-allocated pointer 0x[0-9a-f]+ being freed|double free for ptr 0x[0-9a-f]+)$'
STDERR_MAC_MAX=200
# The window's copy of stderr is made by `tee`, NOT by awk: some awks (mawk, the default on Debian and Ubuntu) read their whole
# input before they print, so a pass-through done by awk showed the window nothing until the server exited. awk reads only a COPY, so
# at worst it logs late: each recorded line's "at" is when the filter handled it (the end of the run on such an awk), not when the
# message was printed. The filter ignores INT, HUP, TERM and PIPE (the window's Ctrl-C or close reaches the whole process group; the
# server is stopped by this launcher's trap, the pipe then closes, and the filter writes its summary), takes its paths and list through
# the ENVIRONMENT (awk -v would treat a backslash in a folder name as an escape), and removes its own pid file at the end.
stderr_filter() {
    # (INT, HUP, TERM and PIPE are already ignored here: the caller sets them, and an ignored signal stays ignored in children)
    OO_SF_OUT="$STDERR_RECORD" OO_SF_PIDFILE="$STDERR_PIDFILE" OO_SF_BOOT="$1" OO_SF_KEEP="$STDERR_KEEP" \
    OO_REC_LIB="$(oo_rec_lib)" OO_REC_LOCK_WAIT_MS="$OO_REC_LOCK_WAIT_MS" OO_SF_MSGS="$(printf '%s' "$STDERR_MESSAGES" | tr '\n' '|')" OO_SF_MRE="$STDERR_MAC_RE" OO_SF_MRE_MAX="$STDERR_MAC_MAX" awk '
    BEGIN {
        out = ENVIRON["OO_SF_OUT"]; pidfile = ENVIRON["OO_SF_PIDFILE"]; boot = ENVIRON["OO_SF_BOOT"]; keep = ENVIRON["OO_SF_KEEP"] + 0
        n = split(ENVIRON["OO_SF_MSGS"], list, "|")
        for (i = 1; i <= n; i++) ok[list[i]] = 1
        mre = ENVIRON["OO_SF_MRE"]; mmax = ENVIRON["OO_SF_MRE_MAX"] + 0
        cmd = "bash -c \047eval \"$OO_REC_LIB\"; oo_rec_append_stdin \"$OO_SF_OUT\"\047"
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
    # one row at a time, through the locked append of the launcher (R173): the file is NOT held open for the life of the server, so a trim by
    # another launcher cannot send these rows to a file nobody reads. If that append cannot run at all, the row is appended directly, as before.
    function emit(row) {
        print row | cmd
        if (close(cmd) != 0) { print row >> out; close(out) }
    }
    {
        if (($0 in ok) || (mre != "" && length($0) <= mmax && $0 ~ mre)) {
            if (kept < keep) {
                emit(sprintf("{\"schema\":\"oo-launcher-stderr-1\",\"at\":\"%s\",\"pid\":%s,\"boot_id\":%s,\"line\":\"%s\"}", stamp(), pid(), bootj(), $0))
                kept++
            } else over++
        } else dropped++
    }
    END {
        emit(sprintf("{\"schema\":\"oo-launcher-stderr-1\",\"at\":\"%s\",\"pid\":%s,\"boot_id\":%s,\"summary\":true,\"kept_lines\":%d,\"dropped_lines\":%d,\"over_cap_lines\":%d}", stamp(), pid(), bootj(), kept, dropped, over))
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
    # pid files left by a launcher that was killed outright: a file named for a launcher pid that no longer runs is removed now. Where
    # /proc exists it is the test of "runs" (kill -0 also fails for another user's live process); a pid that has been reused by another
    # process keeps its file, and the day-old rule below clears it.
    for _f in "$_dd/diagnostics"/.launcher_stderr.*.pid; do
        [ -e "$_f" ] || continue
        _p="${_f##*/.launcher_stderr.}"; _p="${_p%.pid}"
        case "$_p" in ''|*[!0-9]*) continue ;; esac
        [ "$_p" = "$$" ] && continue
        # WHAT THE MINUTE PROTECTS: the previous launch's filter reads this file until its END has written the summary row, and that can
        # follow the launcher's own exit by a moment; a file touched in the last minute is never swept, whatever its pid says.
        [ -z "$(find "$_f" -maxdepth 0 -mmin -1 2>/dev/null)" ] || continue
        # a launcher killed outright can leave its server and filter running, and the filter reads this file for the server's pid:
        # a file whose recorded server still runs is in use and stays
        _sp="$(head -n 1 "$_f" 2>/dev/null || true)"
        case "$_sp" in ''|*[!0-9]*) _sp="" ;; esac
        if [ -d /proc/self ]; then
            if [ -d "/proc/$_p" ] || { [ -n "$_sp" ] && [ -d "/proc/$_sp" ]; }; then continue; fi
            rm -f "$_f" 2>/dev/null || true
        else
            if kill -0 "$_p" 2>/dev/null || { [ -n "$_sp" ] && kill -0 "$_sp" 2>/dev/null; }; then continue; fi
            rm -f "$_f" 2>/dev/null || true
        fi
    done
    find "$_dd/diagnostics" -maxdepth 1 -name '.launcher_stderr.*.pid' -mtime +1 -exec rm -f {} + 2>/dev/null || true
    # Bounded: the newest 100 lines are five full launches of a crash loop.
    if [ -n "$STDERR_RECORD" ] && [ "$({ wc -l < "$STDERR_RECORD"; } 2>/dev/null || echo 0)" -gt 100 ]; then
        oo_rec_trim "$STDERR_RECORD" 100 100
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
#
# INT (Ctrl-C) IS NOT FORWARDED (17 Oct, measured): the terminal already sent that SIGINT to the whole foreground group, the server
# included. Forwarding a SIGTERM beside it gave the server TWO signals for one Ctrl-C, and uvicorn reads a SIGINT that arrives after a
# stop is already under way as the second Ctrl-C ("force quit"): in the runs where the TERM won the race (3 of 14 through this
# launcher; 3 of 3 on the bare server with TERM then INT 30 ms apart) it skipped the app's lifespan shutdown, the teardown that
# writes the clean-stop mark. TERM and HUP are not terminal-group signals, so they are still forwarded (once). After either, the
# launcher WAITS for the server to end, so its own exit comes after the server's teardown and carries the server's status.
# KNOWN RESIDUAL (R168, no fix): a bare `kill -INT <launcher pid>` is not a terminal's Ctrl-C. Nothing sends the server a SIGINT then, and INT is not
# forwarded, so the launcher waits and the server keeps running; stop it with TERM or HUP (forwarded) or close the window. Recorded in docs/ledger/OPEN_QUEUE.md.
STOP_REQUESTED=0
trap 'STOP_REQUESTED=1; record_stop HUP; kill "$SERVER" 2>/dev/null || true' HUP
trap 'STOP_REQUESTED=1; record_stop TERM; kill "$SERVER" 2>/dev/null || true' TERM
trap 'STOP_REQUESTED=1; record_stop INT' INT
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
# A trapped signal ends `wait` while the server is still stopping; wait again until it has really ended (its status is the answer).
while kill -0 "$SERVER" 2>/dev/null; do
    status=0
    wait "$SERVER" || status=$?
done
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
