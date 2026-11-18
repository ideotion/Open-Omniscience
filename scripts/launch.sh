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

# The passphrases the server holds (src/monitoring/secret_scrub.py HELD_ENV_VARS, which
# tests/test_launcher_browser_env.py holds this list to). A scripted start that sets one hands it to
# this launcher's environment, and the server needs it; the browser does not, and a browser started
# with it would keep it in its own environment (/proc/<pid>/environ, a crash report) for as long as it
# runs, long after the app has stopped. `env -u` drops each name for the one command it starts, so the
# variable is never touched in this shell (an install file that declared it readonly cannot stop the
# browser opening), and both openers below get the same environment.
OO_HELD_ENV_VARS="OO_DB_PASSPHRASE OO_KEY_PASSPHRASE"

open_browser() {
    local _drop=() _n
    for _n in $OO_HELD_ENV_VARS; do _drop+=(-u "$_n"); done
    if   command -v xdg-open >/dev/null 2>&1; then env "${_drop[@]}" xdg-open "$1" >/dev/null 2>&1 || true
    elif command -v open     >/dev/null 2>&1; then env "${_drop[@]}" open "$1"     >/dev/null 2>&1 || true
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
  You can close the browser at any time: collection, downloads, backups, imports and
  AI jobs keep running here. This window shows a small panel to reopen the UI.

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

# --- the evidence files and the launchers that share them (R173, R174, 17 Oct) -----------------------------------------------------------------
# launcher_exits.jsonl, launcher_stops.jsonl and launcher_stderr.jsonl are written and trimmed by every launcher that runs, and a launcher keeps
# writing for as long as its server lives. A trim is "newest N lines to a temp file, rename over the file": an append between the two steps went
# to the replaced file, two trims shared one temp name, and the stderr filter held the file open for the whole life of the server, so a trim by
# another launcher sent every later row of a live one to a file nobody could read (measured: 8 of 96 exit rows, 69 of 96 stop rows, and all 3 stderr
# rows of the launcher whose server was alive, in tests/test_launcher_records_race.py). Now every append and every trim of one file happens under
# ONE lock for that file (flock where there is one, else a directory made with mkdir that holds its owner's pid, so a lock whose owner died is taken
# over and never waited on), a trim writes to a temp name of its own, and the filter appends one row at a time.
# NO ROW IS EVER WRITTEN WITHOUT THE LOCK (R174). The launcher waits for the lock only OO_REC_LOCK_WAIT_MS, so it never blocks its own start or stop;
# when that runs out it hands the row to a detached child and carries on at once. The child waits for the same lock with no time bound, then does the
# locked append and the trim if due. A holder that dies releases the lock (the kernel for flock, a dead-pid takeover for the mkdir lock), so the child
# ends once the holder does. THE ONE WAY A ROW CAN STILL BE LATE: a holder that is alive and stuck for ever; the child waits with it. Late is not lost
# while the machine runs; a machine that goes down before the child writes loses the row. A deferred row can land after later rows: the readers order
# by the row's own time, never by its place in the file.
# WHAT THE WAIT PROTECTS: the time the launcher itself is willing to wait before it defers. OO_REC_LOCK_WAIT_MS is the longest append-plus-trim hold
# measured under the heaviest load tried (8 launchers at once beside 8 busy loops on 4 CPUs: 92.4 ms, 17 Oct), rounded up to 100
# (tests/test_launcher_records_race.py pins that the constant is not below that measurement).
OO_REC_LOCK_WAIT_MS=100

oo_pid_alive() {
    if [ -d /proc/self ]; then [ -d "/proc/$1" ]; else kill -0 "$1" 2>/dev/null; fi
}

# _oo_rec_claim FILE: create FILE holding this shell's pid, and only if it does not exist yet (the shell's noclobber opens it O_EXCL, in the kernel). The
# lock and the directory mark are claimed THIS way, never by `mkdir` alone: an `mkdir` is not exclusive everywhere. uutils coreutils 0.10 (the mkdir of
# Ubuntu 26.04, CI 17 Nov) checks that the name is free, then creates it, and reports SUCCESS when another process created it in between, so two
# launchers each "made" the lock and both held it (both pids named by the eight-taker test). The directory is only the container; whoever creates its
# pid file holds it, and one that made the directory but lost the pid file waits like everybody else. The owner is THIS process, not the launcher it was
# forked from: bash 4+ has BASHPID; bash 3.2 (macOS) has not, and there $$ is the launcher's pid in every subshell, so the deferred child would be recorded
# as its parent and a second launcher would take the lock over the moment the parent exited. A simple command with a redirect is forked by this very shell
# (not by a command substitution, which has a subshell of its own), so the sh it starts sees the pid of this shell as its PPID. noclobber is set for the
# one redirect and put back as it was.
_oo_rec_claim() {
    local c=0 r=0
    case $- in *C*) c=1 ;; esac
    set -C
    # r=1: the file was there already (or could not be made), not ours. A pid that could not be WRITTEN into a file this shell did create (a full disk)
    # still leaves the claim this shell's, as an unwritten pid always has: the lock is held and released as usual rather than left for nobody to take.
    if [ -n "${BASHPID:-}" ]; then { printf '%s\n' "$BASHPID" || :; } 2>/dev/null > "$1" || r=1
    else { sh -c 'echo $PPID' || :; } 2>/dev/null > "$1" || r=1
    fi
    [ "$c" = 1 ] || set +C
    return "$r"
}

# _oo_rec_take DIR: make the lock directory and claim it. A directory this call made but could not claim with no pid file in it at all (the create failed
# for another reason: no inode or quota left) is removed again, so it never stays a lock nobody can take over (Opus read, 17 Nov). rmdir removes only an
# EMPTY directory: a pid file anyone has made since keeps it, and a creator whose fresh directory goes this way finds no name to claim and waits.
_oo_rec_take() {
    mkdir "$1" 2>/dev/null || return 1
    ! _oo_rec_claim "$1/pid" || return 0
    [ -e "$1/pid" ] || rmdir "$1" 2>/dev/null || true
    return 1
}

# The takeover mark where the filesystem has no hard links (exFAT, some FUSE and SMB mounts: `ln` always fails there, and without this a dead owner's lock would
# never be taken over again, every row deferred for ever). The mark has the SAME name, "reap", as the linked one, so the two can never be held at once (mkdir
# refuses a name a file holds, and a link made into a directory is not that directory). It is made by mkdir and held by whoever creates its pid file
# (_oo_rec_claim, O_EXCL), never by renaming a prepared directory into place (what `mv` does with a directory name that already exists differs between
# implementations) and never by mkdir alone (not exclusive under uutils 0.10, see _oo_rec_claim). The pid is written in the same step as the claim; a mark whose taker is dead is renamed away and removed, and so is one
# left with no pid (its taker died between the two steps) once a waiter has seen it so for a minute, so nobody waits behind it for ever. Weaker than the linked mark in one
# way: two clearers of one dead taker's mark can still remove a live taker's new one between them, which needs a taker to die first. That is the cost of a
# filesystem without links, never paid where links work.
_oo_rec_reap_dir() {
    local d="$1" owner="$2" mk="$1/reap" me p tok
    tok="${RANDOM:-0}${RANDOM:-0}.$$"
    if mkdir "$mk" 2>/dev/null && _oo_rec_claim "$mk/pid"; then
        me="$(cat "$mk/pid" 2>/dev/null || true)"
        p="$(cat "$d/pid" 2>/dev/null || true)"
        case "$p" in ''|*[!0-9]*) p="" ;; esac
        # an owner with no pid (row 172): still none under the mark, and a second later
        if [ "$owner" = "-" ] && [ -z "$p" ] && [ -n "$me" ] && _oo_rec_still_nopid "$d"; then p="-"; fi
        if [ -n "$me" ] && [ -n "$p" ] && [ "$p" = "$owner" ] && { [ "$owner" = "-" ] || ! oo_pid_alive "$p"; } && [ "$(cat "$mk/pid" 2>/dev/null || true)" = "$me" ] \
            && mv "$d" "$d.dead.$tok" 2>/dev/null; then
            rm -rf "$d.dead.$tok" 2>/dev/null || true
            [ "$owner" != "-" ] || _oo_rec_nopid_cleared "$d"
        elif [ -n "$me" ] && [ "$(cat "$mk/pid" 2>/dev/null || true)" = "$me" ]; then
            # given up (the lock names someone else now): only the pid is taken out, never the mark itself. Between the check above and any removal the
            # name "$d/reap" can come to be another taker's live mark in a newer lock, and removing THAT mark lets two takers in (Opus read, 17 Nov). A mark
            # left with no pid keeps every other taker out; the live lock's release carries it away, and if that holder dies instead it is cleared below
            # after a minute: a wait, never a second holder
            rm -f "$mk/pid" 2>/dev/null || true
        fi
        return 0
    fi
    if [ ! -d "$mk" ]; then _OO_REAP_NOPID=""; return 0; fi
    p="$(cat "$mk/pid" 2>/dev/null || true)"
    case "$p" in ''|*[!0-9]*) p="" ;; esac
    # A mark with no pid is cleared only once THIS waiter has seen it without a pid at every look for a minute of its own clock (bash's SECONDS): never
    # by the mark's mtime, which the filesystems this path serves (SMB with a skewed server clock, FUSE exFAT reading local time as UTC) can make look old
    # at birth. Any look that finds a pid, or no mark, starts the minute again, and the record names this lock, so a live taker's mark (pid-less for the
    # instant between its mkdir and its pid write) is never cleared, whatever inode a later mark reuses.
    if [ -z "$p" ]; then
        # the record is "lock#inode first-look last-look": the same mark (a new one made between two looks has its own inode), and a gap of more than 2 s
        # between looks (the waiter was elsewhere, so it did not see) starts it again
        tok="$mk#$(ls -di "$mk" 2>/dev/null | awk '{print $1}')"
        p="${_OO_REAP_NOPID:-}"; p="${p% *}"
        me="${p##* }"
        case "$me" in ''|*[!0-9]*) me="" ;; esac
        if [ -z "$me" ] || [ "${p% *}" != "$tok" ] || [ $(( ${SECONDS:-0} - ${_OO_REAP_NOPID##* } )) -gt 2 ]; then
            _OO_REAP_NOPID="$tok ${SECONDS:-0} ${SECONDS:-0}"; return 0
        fi
        _OO_REAP_NOPID="$tok $me ${SECONDS:-0}"
        [ $(( ${SECONDS:-0} - me )) -ge 60 ] || return 0
        p=""
    else
        _OO_REAP_NOPID=""
    fi
    if [ -n "$p" ] && oo_pid_alive "$p"; then return 0; fi
    _OO_REAP_NOPID=""
    tok="${RANDOM:-0}${RANDOM:-0}.$$"
    if mv "$mk" "$d/reapd.gone.$tok" 2>/dev/null; then rm -rf "$d/reapd.gone.$tok" 2>/dev/null || true; fi
}

# _oo_rec_nopid_seen DIR: whether the lock DIR, which has NO pid file, has been seen so by THIS waiter at every look for a minute of its own clock (bash's
# SECONDS), the same rule as a directory mark left with no pid (_oo_rec_reap_dir), AND its own mtime is more than a minute old too (R744: a lock being made
# right now is never taken, whatever the waiter's clock says). Row 172: a lock directory with no pid file was waited for and never taken over (it reads as a
# launcher between its mkdir and its pid create, a few instructions), so one left so (a launcher killed at that instant, the release's rm -rf fallback
# meeting a taker's temp mark, a pid file removed by hand) deferred every later row to a child that waited for ever, one more per row. A lock WITH a pid
# file, even an empty one, is never taken over this way (R744). The record is "lock#inode first-look last-look": another directory under the same name
# starts the minute again, and so does a gap of more than 2 s between looks (the waiter was elsewhere, so it did not see). The mtime is a second condition,
# never the only one: a server clock ahead of this one (SMB) delays the takeover by its skew. Once seen old for this lock#inode it stays so (_OO_LOCK_OLD):
# the waiter's own temp mark made inside the lock changes that mtime, and a test made again after it would push the takeover a minute further at every
# attempt, for ever where a pid-less directory mark has to be cleared first (no hard links; the reads of 18 Nov). Both records are dropped by a takeover,
# so a directory made later under the same name, even on a reused inode, starts its own minute; so do a new call and a lock this waiter takes. What is
# left: another waiter takes the old lock over and a launcher makes a new one on the same inode, both between two of this waiter's looks, and that
# launcher is then stopped (not slow) for a second between its mkdir and its pid create: the second look under the mark is its last guard.
_oo_rec_nopid_seen() {
    local tok r first
    tok="$1#$(ls -di "$1" 2>/dev/null | awk '{print $1}' || true)"
    r="${_OO_LOCK_NOPID:-}"; r="${r% *}"
    first="${r##* }"
    case "$first" in ''|*[!0-9]*) first="" ;; esac
    if [ -z "$first" ] || [ "${r% *}" != "$tok" ] || [ $(( ${SECONDS:-0} - ${_OO_LOCK_NOPID##* } )) -gt 2 ]; then
        _OO_LOCK_NOPID="$tok ${SECONDS:-0} ${SECONDS:-0}"; _OO_LOCK_OLD=""; return 1
    fi
    _OO_LOCK_NOPID="$tok $first ${SECONDS:-0}"
    [ $(( ${SECONDS:-0} - first )) -ge 60 ] || return 1
    [ "${_OO_LOCK_OLD:-}" != "$tok" ] || return 0
    [ -n "$(find "$1" -prune -mmin +1 2>/dev/null || true)" ] || return 1
    _OO_LOCK_OLD="$tok"
}

# _oo_rec_still_nopid DIR: called by a taker holding its mark in DIR, a minute after DIR was first seen with no pid file: DIR still has none now AND a
# second later, the re-check made just before the lock is renamed away (R744). The pause is what tells a lock left so from a live launcher between its mkdir and its pid create (a few instructions): the name can be freed
# and made again by such a launcher between this taker's last look and its mark (an inode freed by a removal can be reused at once), and that launcher's
# pid is in its lock long before the second is over. Only a launcher frozen for that second at that instant (stopped, not merely slow) is not told apart.
_oo_rec_still_nopid() {
    [ ! -e "$1/pid" ] && [ ! -L "$1/pid" ] || return 1
    sleep 1 2>/dev/null || :
    [ ! -e "$1/pid" ] && [ ! -L "$1/pid" ]
}

# _oo_rec_nopid_cleared LOCK: the one visible line for a lock taken over this way (R744), on stderr and in LOCK.cleared beside it (one line, replaced each
# time, so it never grows): the waiter that clears is the deferred child, whose stderr goes nowhere once its window is closed.
_oo_rec_nopid_cleared() {
    local line
    _OO_LOCK_NOPID=""; _OO_LOCK_OLD=""
    line="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || true) launcher: took over the record lock $1, which had no owner pid for a minute (pid ${BASHPID:-$$})"
    printf '%s\n' "$line" >&2 2>/dev/null || true
    { printf '%s\n' "$line" > "$1.cleared"; } 2>/dev/null || true
}

# oo_rec_locked FILE CMD [ARGS...]: run CMD holding the lock of FILE. Returns 99 when the lock was not obtained in time (CMD did not run), 98 when no
# lock can be made at all (CMD did not run), else CMD's own status. With OO_REC_LOCK_FOREVER=1 the wait has no bound (the deferred child).
oo_rec_locked() {
    local f="$1" rc=0 d tries owner moved wait_s tok m _l
    shift
    if command -v flock >/dev/null 2>&1; then
        { : >> "$f.lock"; } 2>/dev/null || return 98
        wait_s="-w $(awk -v ms="$OO_REC_LOCK_WAIT_MS" 'BEGIN { printf "%.3f", ms / 1000 }')"
        [ "${OO_REC_LOCK_FOREVER:-}" != 1 ] || wait_s=""
        # Only a flock that can say "the lock was held" apart from "the lock cannot be made" (-E, util-linux) lets a failure of the second kind be told from a
        # timeout: a filesystem that cannot lock at all (NFS without lockd, some FUSE and shared folders) must reach the direct append (98), not be read as
        # "held, try later" for ever. A flock without -E keeps the old reading of every failure as a timeout.
        if [ -z "${_OO_FLOCK_E+x}" ]; then
            if flock -E 99 -n /dev/null true 2>/dev/null; then _OO_FLOCK_E="-E 99"; else _OO_FLOCK_E=""; fi
        fi
        (
            # shellcheck disable=SC2086
            flock $_OO_FLOCK_E $wait_s 9
            r=$?
            if [ "$r" -ne 0 ]; then
                if [ -n "$_OO_FLOCK_E" ] && [ "$r" -ne 99 ]; then exit 98; fi
                exit 99
            fi
            "$@"
        ) 9>>"$f.lock" 2>/dev/null || rc=$?
        return "$rc"
    fi
    d="$f.lock.d"
    _OO_LOCK_NOPID=""; _OO_LOCK_OLD=""  # a minute is seen within one call, never carried over from an earlier one (row 172)
    tries=$(( OO_REC_LOCK_WAIT_MS / 10 + 1 ))
    while :; do
        # held by whoever creates the pid file, never by the mkdir alone (_oo_rec_take): a lock whose pid file is somebody else's is waited for
        if _oo_rec_take "$d"; then
            _OO_LOCK_NOPID=""; _OO_LOCK_OLD=""
            # A lock renamed away (released, or a dead owner's taken over) is nobody's, but a waiter whose path walk reached it just before the rename can still
            # create its temp mark in it after the remover listed it, so the remover's rm -rf leaves it behind (seen once in 30 stress runs, 16 Nov). The holder
            # removes such leftovers: only names a remover makes after the rename, so never a lock anybody holds.
            for _l in "$d".dead.* "$d".rel.*; do [ ! -d "$_l" ] || rm -rf "$_l" 2>/dev/null || true; done
            "$@" || rc=$?
            # released by renaming it away first: a taker's mark made inside it at this moment leaves with it, never keeping the name taken
            tok="$$.${RANDOM:-0}.${RANDOM:-0}"
            if mv "$d" "$d.rel.$tok" 2>/dev/null; then rm -rf "$d.rel.$tok" 2>/dev/null || true; else rm -rf "$d" 2>/dev/null || true; fi
            return "$rc"
        fi
        owner="$(cat "$d/pid" 2>/dev/null || true)"
        case "$owner" in ''|*[!0-9]*) owner="" ;; esac
        # a lock this waiter has seen with no owner pid for a minute is taken over like a dead owner's ("-" names that owner): row 172, _oo_rec_nopid_seen
        if [ -z "$owner" ] && [ -d "$d" ] && [ ! -e "$d/pid" ] && [ ! -L "$d/pid" ]; then
            if _oo_rec_nopid_seen "$d"; then owner="-"; fi
        else
            _OO_LOCK_NOPID=""; _OO_LOCK_OLD=""
        fi
        # The owner is gone: the lock is taken over, and NEVER by moving it while somebody else may hold it (row 100, 16 Nov: the old takeover moved the
        # lock out to read who held it and put a live one back, and in the instant it was out a third launcher made the lock, so two held it at once and
        # a trim's rename dropped the row appended meanwhile: 1 of 8 exit rows lost on Linux CI, mkdir path). Now a taker first makes a REAP mark INSIDE
        # the lock, then reads the owner again under that mark: the same dead pid means the lock is still the dead owner's, and nothing else can change it
        # (its owner is dead and every other taker is held off by the mark), so it is renamed away and removed. Any other answer means the lock was
        # released and made again: the taker removes only its own mark and waits like everybody else. A live holder's lock is never moved.
        # The mark is a FILE born with its taker's pid in it (written to a unique temp name, then hard-linked to "reap": link is atomic and refuses an
        # existing name), so there is never a mark without a pid that nobody could judge. A mark whose taker died is cleared by ONE clearer at a time
        # ("reap.clr", linked the same way and carrying the clearer's pid), and only while "reap" is still that same file with that same dead pid: two
        # clearers that both read the same dead taker can never remove a live taker's new mark between them, which would let two takers in at once
        # (the reads of 16 Nov).
        if [ -n "$owner" ] && { [ "$owner" = "-" ] || ! oo_pid_alive "$owner"; }; then
            m="$(mktemp "$d/reap.XXXXXX" 2>/dev/null)" || m=""
            if [ -n "$m" ] && [ -d "$d/reap" ]; then
                _oo_rec_reap_dir "$d" "$owner"  # a directory mark is there: only the directory mark's own way judges it (a link made now would land inside it)
                rm -f "$m" 2>/dev/null || true
            elif [ -n "$m" ]; then
                { if [ -n "${BASHPID:-}" ]; then printf '%s\n' "$BASHPID"; else sh -c 'echo $PPID'; fi; } 2>/dev/null > "$m" || true
                if [ -s "$m" ] && ln "$m" "$d/reap" 2>/dev/null; then
                    moved="$(cat "$d/pid" 2>/dev/null || true)"
                    case "$moved" in ''|*[!0-9]*) moved="" ;; esac
                    # an owner with no pid is judged again under the mark too: still none, and still none a second later (_oo_rec_still_nopid)
                    if [ "$owner" = "-" ] && [ -z "$moved" ] && [ "$d/reap" -ef "$m" ] && _oo_rec_still_nopid "$d"; then moved="-"; fi
                    # the pid is judged dead again under the mark: a recycled pid that is now a live holder's is never taken for the dead owner
                    if [ -n "$moved" ] && [ "$moved" = "$owner" ] && { [ "$owner" = "-" ] || ! oo_pid_alive "$moved"; } && [ "$d/reap" -ef "$m" ] \
                        && mv "$d" "$d.dead.${m##*.}" 2>/dev/null; then
                        rm -rf "$d.dead.${m##*.}" 2>/dev/null || true
                        [ "$owner" != "-" ] || _oo_rec_nopid_cleared "$d"
                    else
                        # not taken over (or the move failed): only this taker's own mark goes, never a mark it did not make
                        [ ! "$d/reap" -ef "$m" ] || rm -f "$d/reap" 2>/dev/null || true
                    fi
                elif [ -d "$d/reap" ] || { [ ! -e "$d/reap" ] && [ -s "$m" ] && ! ln "$m" "$m.l" 2>/dev/null; }; then
                    _oo_rec_reap_dir "$d" "$owner"  # a directory mark, or no hard links here and no mark: the directory mark's own way
                else
                    rm -f "$m.l" 2>/dev/null || true
                    # a mark already there: if its taker died holding it, clear it so the next pass takes the lock over
                    moved="$(head -n 1 "$d/reap" 2>/dev/null || true)"
                    case "$moved" in ''|*[!0-9]*) moved="" ;; esac
                    if [ -n "$moved" ] && ! oo_pid_alive "$moved"; then
                        if [ -s "$m" ] && ln "$m" "$d/reap.clr" 2>/dev/null; then
                            # this clearer's own link to the mark, then the mark judged again through it: the same file, the same pid, still dead (a pid
                            # recycled to a live taker since the first read is never taken for the dead one)
                            if ln "$d/reap" "$m.got" 2>/dev/null; then
                                if [ "$(head -n 1 "$m.got" 2>/dev/null || true)" = "$moved" ] && ! oo_pid_alive "$moved" && [ "$d/reap" -ef "$m.got" ]; then
                                    rm -f "$d/reap" 2>/dev/null || true
                                fi
                                rm -f "$m.got" 2>/dev/null || true
                            fi
                            [ ! "$d/reap.clr" -ef "$m" ] || rm -f "$d/reap.clr" 2>/dev/null || true
                        else
                            # "reap.clr" carries its clearer's pid like a mark carries its taker's: it goes only once that clearer is dead, never by age
                            moved="$(head -n 1 "$d/reap.clr" 2>/dev/null || true)"
                            case "$moved" in ''|*[!0-9]*) moved="" ;; esac
                            if [ -n "$moved" ] && ! oo_pid_alive "$moved"; then rm -f "$d/reap.clr" 2>/dev/null || true; fi
                        fi
                    fi
                fi
                rm -f "$m" "$m.l" 2>/dev/null || true
            fi
        fi
        if [ "${OO_REC_LOCK_FOREVER:-}" != 1 ]; then
            tries=$((tries - 1))
            [ "$tries" -gt 0 ] || return 99
        elif [ ! -d "$f.lock.d" ] && [ ! -w "$(dirname "$f")" ]; then
            return 98  # the folder cannot be written: no lock will ever be made
        fi
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
# The row of a launcher that could not get the lock in time (R174): a detached child waits for the lock with no bound and then does the locked
# append and the trim. Nothing is written to a file by this function, and the child leaves no file behind but the one-line LOCK.cleared note
# of a lock it took over because it had no owner pid (_oo_rec_nopid_cleared). It ignores the signals a closing window
# sends. (The mkdir lock records the child's own pid, from BASHPID where bash has it and from a one-line sh otherwise.)
_oo_rec_defer() {
    (
        exec < /dev/null > /dev/null 2>&1; trap '' HUP INT TERM PIPE
        OO_REC_LOCK_FOREVER=1
        rc=0
        oo_rec_locked "$1" _oo_rec_append_trim "$1" "$2" "$3" "$4" || rc=$?
        [ "$rc" -ne 98 ] || printf '%s\n' "$2" >> "$1" 2>/dev/null
        exit 0
    ) &
}
# oo_rec_append FILE ROW MAX KEEP: 0 appended or handed on, 1 the append failed
oo_rec_append() {
    local rc=0
    oo_rec_locked "$1" _oo_rec_append_trim "$1" "$2" "$3" "$4" || rc=$?
    case "$rc" in
        99) _oo_rec_defer "$1" "$2" "$3" "$4"; return 0 ;;
        98) printf '%s\n' "$2" >> "$1" 2>/dev/null || return 1; return 0 ;;  # no lock can be made at all (a folder that cannot be written): as before
    esac
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
oo_rec_lib() { declare -f oo_pid_alive _oo_rec_claim _oo_rec_take _oo_rec_reap_dir _oo_rec_nopid_seen _oo_rec_still_nopid _oo_rec_nopid_cleared oo_rec_locked _oo_rec_append_trim _oo_rec_trim _oo_rec_defer oo_rec_append oo_rec_append_stdin; }
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
# THE STOP TRAPS EXIST BEFORE THE SERVER DOES (R674, 13 Nov, measured). They were set a few lines AFTER the server was started, so a TERM or HUP
# that reached this launcher in between found no trap: bash took the signal's default action and died at once, the EXIT trap did not run, nothing
# was forwarded and the server was left running with no window and no stop row. A launcher made to pause there for a moment reproduces it exactly
# (tests/test_launcher_signals.py::test_a_stop_in_the_instant_the_server_starts_is_forwarded): CI met it once, on a loaded runner, as a launcher that
# died of SIGTERM one second after a stop it should have waited out. Now HUP and TERM are trapped first. A stop that arrives before SERVER holds the
# server's pid (the start is a fork, and the trap can run before `SERVER=$!`) is remembered in STOP_SIGNAL and carried out once the pid is known.
# INT keeps its own trap below, set where it always was: it is not forwarded, and the terminal's Ctrl-C reaches the server by itself.
STOP_REQUESTED=0
STOP_SIGNAL=""
SERVER=""
PANEL=""
oo_stop() {
    STOP_REQUESTED=1
    if [ -n "$SERVER" ]; then
        record_stop "$1"
        kill "$SERVER" 2>/dev/null || true
    else
        STOP_SIGNAL="$1"
    fi
}
trap 'STOP_REQUESTED=1; oo_stop HUP' HUP  # STOP_REQUESTED=1 also here: the S0.2 guards read this first trap line for it
trap 'STOP_REQUESTED=1; oo_stop TERM' TERM
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
# a stop that arrived while the server was being started, before its pid was known: carried out now. Once only: oo_stop forwards nothing while
# SERVER is empty, and from here on SERVER is set, so a later stop takes oo_stop's direct path.
if [ -n "$STOP_SIGNAL" ]; then
    record_stop "$STOP_SIGNAL"
    kill "$SERVER" 2>/dev/null || true
fi
# A failed write here (disk full, a pid file that is not ours) must never end the launcher.
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
# (HUP and TERM are trapped above, before the server starts: R674.)
trap 'STOP_REQUESTED=1; record_stop INT' INT
trap 'kill "$SERVER" 2>/dev/null || true; [ -z "$PANEL" ] || kill "$PANEL" 2>/dev/null || true' EXIT

# Wait up to ~20s for the health endpoint.
for _ in $(seq 1 40); do
    if curl -fsS "${BASE}/api/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
done

open_browser "$URL"

# THE TERMINAL PANEL (R600, 8 Nov; R658, 11 Nov): while the server runs, this window shows src/tui/panel.py -- status, an activity log
# that grows for as long as the app runs, and Open UI / Pause collection / Stop app, clickable where the terminal sends mouse clicks -- so the browser can be closed on an instance left running
# and reopened from here. It starts only in a real terminal (stdin AND stdout), only when this install has it and its own Python, and
# never when OO_PANEL=0; anything else keeps the window exactly as before. It is an ordinary child of this launcher and changes no stop path:
#   * it runs in cbreak mode, so a Ctrl-C is still ONE terminal SIGINT to the whole group (the server takes its graceful path, the INT trap
#     records it); the panel only restores the terminal and ends;
#   * TERM or HUP to this launcher still runs the traps above at once: `wait` on the panel is interrupted by a trapped signal, which a
#     FOREGROUND panel would not allow (bash runs a trap only after the foreground command ends);
#   * its "Stop app" is the app's own power button over loopback, the same 143 the exit check below already reads as a requested stop;
#   * the panel ends by itself when the server ends (by the server's identity, never because it was quiet: R658), and it has no close
#     button, so it stays for the life of the app; the launcher waits for it BEFORE reading the server's status, so the crash
#     message below is never drawn under a curses screen.
# `<&0` keeps the terminal as its input: without an explicit redirection bash gives a background command /dev/null.
# It never sees the passphrase: unlocking stays in the browser (R601 keeps going online there too).
PANEL_PY="$DIR/.venv/bin/python"
if [ "${OO_PANEL:-1}" != "0" ] && [ -t 0 ] && [ -t 1 ] && [ -f "$DIR/src/tui/panel.py" ] && [ -x "$PANEL_PY" ]; then
    # env -u: the panel never needs the passphrases, and a browser it opens must not inherit them (secret_scrub.HELD_ENV_VARS)
    env -u OO_DB_PASSPHRASE -u OO_KEY_PASSPHRASE "$PANEL_PY" -m src.tui.panel --port "$PORT" --server-pid "$SERVER" --url "$URL" <&0 &
    PANEL=$!
    while kill -0 "$PANEL" 2>/dev/null; do
        wait "$PANEL" 2>/dev/null || true
    done
    PANEL=""
fi

# Keep running (and holding the server) until the user closes the window.
status=0
wait "$SERVER" || status=$?
# A trapped signal ends `wait` while the server is still stopping; wait again until it has really ended (its status is the answer).
while kill -0 "$SERVER" 2>/dev/null; do
    status=0
    wait "$SERVER" || status=$?
done
# A requested stop that ENDED IN A CRASH (a SIGABRT or SIGSEGV during the teardown: 134, 139) is an exit row too: with only the stop row the next boot read
# it as "a stop was asked ... Not a crash". The statuses a stop ends in when it works (0, 129, 130, 143) stay stop-row only.
crashed_in_stop=0
if [ "$STOP_REQUESTED" = 1 ]; then
    case "$status" in 0|129|130|143) ;; *) crashed_in_stop=1 ;; esac
fi
if { [ "$STOP_REQUESTED" = 0 ] || [ "$crashed_in_stop" = 1 ]; } && [ "$status" -ne 0 ]; then
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
