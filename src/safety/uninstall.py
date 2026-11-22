"""Uninstall the local app installation — modes from Minimal to Secure.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A GUI counterpart to ``./install.sh --uninstall`` for users who never open a terminal.

MODES (maintainer-ruled 2026-06-17 — "data dies only in Secure"):
  * minimal  — remove the **virtualenv** + the **desktop launchers**. Keeps the app
               folder AND your data. (The historical default.)
  * full     — minimal + delete the **app folder**. Keeps your data (the data dir
               lives outside the code tree, so it survives).
  * secure   — full + **wipe your data and keys** (best-effort overwrite then delete).
  * custom   — pick exactly what to remove (app folder / data), each off by default.
The virtualenv + launchers are removed in every mode; only the app folder and the
data are optional. HONEST about the limit (same as panic_wipe): an overwrite does NOT
guarantee erasure on SSD/flash/copy-on-write disks — the real protection is that the
corpus was *encrypted at rest* and the key is destroyed. Never a fabricated guarantee.

Doing this safely from the running server is the tricky part: the server runs *from* the
venv (and inside the folder) we may delete. So we don't delete in-process. Instead we hand
a tiny **detached watcher** (the system Python, not the venv) the server's PID and an
explicit plan of absolute paths; it waits for the server to exit, *then* removes them and
writes an **audit log** to ``~/.open-omniscience-uninstall.log`` (survives a full/secure
removal). The endpoint arms a graceful shutdown (closing the DB cleanly first, so the
encrypted store does not emit teardown noise) so the server actually exits. Everything is
dependency-injected so tests never delete anything.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

from src import pid_probe

_LOG = logging.getLogger(__name__)

APP_NAME = "open-omniscience"

# Where the watcher records what it removed (and any failures). In the user's HOME so it
# survives a full/secure removal of the app folder and data dir. Stated in the UI.
AUDIT_LOG = Path.home() / ".open-omniscience-uninstall.log"

# The watcher runs after the server exits, with the SYSTEM Python (the venv is being
# removed). Stdlib only. argv: <server_pid> <json plan>. The plan carries explicit
# absolute paths + flags — the detached process computes NO paths itself (so it can only
# ever remove exactly what plan_uninstall decided in-process).
_WATCHER_SRC = r"""
import os, re, sys, json, time, shutil, datetime, stat, struct
pid = int(sys.argv[1]); plan = json.loads(sys.argv[2])
os.chdir(os.path.expanduser("~"))          # never sit inside a folder we may delete
__PID_PROBE__
for _ in range(240):                        # wait <=120s for the server to exit, then go
    if not pid_alive(pid): break
    time.sleep(0.5)
log = []
def rec(m): log.append(datetime.datetime.now().isoformat(timespec="seconds") + "  " + m)
# R734/R736 (row 334): no line of this log names a path or a process id. A path is written as its role: the data folder as <data>,
# a path inside it or the home folder as <data>/.../<file name> or <home>/.../<file name>, any other as .../<file name> (the
# same form as the diagnostics' path tokens, src/monitoring/path_tokens.py, which this process cannot import). A path it cannot
# read is written as <path withheld>, never as given.
def tok(p):
    try:
        q = os.path.normpath(os.fspath(p)); c = os.path.normcase(q)
        name = os.path.basename(q)
        parts = [x for x in q.replace("\\", "/").split("/") if x]
        if len(parts) >= 2 and parts[-2].lower() in ("home", "users", "documents and settings"):
            return "<home>"                         # a profile folder itself, whatever root holds it: its name is the user's
        for label, root in (("<data>", plan.get("wipe_data_dir")), ("<home>", os.path.expanduser("~"))):
            if not root or root == "~": continue
            r = os.path.normcase(os.path.normpath(root))
            if label == "<home>" and not os.path.basename(r.rstrip("\\/")): continue   # a home of "/" names no role
            if c == r: return label
            if c.startswith(r.rstrip("\\/") + os.sep): return label + "/.../" + name
        for i, seg in enumerate(parts[:-1]):        # inside anyone's profile folder (/home/<name>, C:\\Users\\<name>)
            if seg.lower() in ("home", "users", "documents and settings"):
                return "<home>/.../" + name
        return ".../" + name if name else "<path withheld>"
    except Exception: return "<path withheld>"
# Crypto-erase, stdlib-only + inline (this detached process cannot import src, the venv
# is gone). SQLCipher keeps its 16-byte salt in page 1 of the encrypted DB: destroy that
# page and the key is underivable, so the (possibly multi-GB) ciphertext body is noise
# and is never rewritten. Everything else under the data dir is small and fully
# overwritten. The old code capped EVERY file at the first 4 MiB, so most of a large
# corpus survived (audit OO-02).
PAGE1 = 4096; CHUNK = 8 * 1024 * 1024
# The lane databases join from the plan (row 30): each is an encrypted database with its own salt page, and a whole rewrite of a
# 100 GB lane would turn the uninstall's wipe into hours. Their names come from the lane registry, in-process.
_ENC = ("open_omniscience.db", "custody_log.db", "analytics.duckdb", "analytics.duckdb.kdf", "analytics.duckdb.wal", ".oo_columnar_probe.duckdb") + tuple(plan.get("enc_names") or ())
# The -wal and the -journal are overwritten WHOLE (R708): every commit that touched page 1 left a copy of it, salt
# included, in a WAL frame or the journal far past their first 4 KiB. Only the -shm index (no page data) is head-only.
def header_only(name):
    return name in _ENC or any(name == b + "-shm" for b in _ENC)
def overwrite(p, head_only):
    try:
        if os.path.islink(p) or not os.path.isfile(p): return   # a link is never written through, nor a FIFO or a device
        n = os.path.getsize(p)
        limit = min(n, PAGE1) if head_only else n
        with open(p, "r+b", buffering=0) as f:
            w = 0
            while w < limit:
                c = os.urandom(min(CHUNK, limit - w)); f.write(c); w += len(c)
            f.flush(); os.fsync(f.fileno())
    except OSError: pass
# R792 (part B): ANOTHER process holding the database (a second copy of the app, a database tool) keeps the unlinked files alive
# and can go on committing into them, salt included -- measured on this watcher: a process writing in a loop through it kept
# the salt in 5 runs of 5. Never waited on and never signalled: a descriptor is kept on each SQLite file of an encrypted
# database before it is overwritten and unlinked; once the walk is over, SQLite's lock bytes are taken in one non-blocking
# attempt (only then: closing any descriptor this process has on the file drops its locks), one F_GETLK asks whether another
# process holds a lock (its id is never read), and while one does the kept files are rewritten every STEP s for at most BOUND s,
# each up to its size when kept plus GROWTH. The audit log then says whether another program still had the database open, or
# that it could not be checked (always so on Windows, where an open file cannot be found from here). No path, no process id.
try:
    import fcntl
except ImportError:
    fcntl = None
LAYOUT = "hhqqi" if sys.platform.startswith("linux") else ("qqihh" if sys.platform == "darwin" else None)
BOUND = 2.0; STEP = 0.1; GROWTH = 256 * 1024 * 1024; MAX_KEPT = 64
_SQL = tuple(n for n in _ENC if "duckdb" not in n)
kept = []; held_stat = {"missed": 0, "seen": 0, "ever": False}
def sqlite_kind(name):
    for b in _SQL:
        if name == b: return "head"
        if name in (b + "-wal", b + "-journal"): return "whole"
        if name == b + "-shm": return "shm"
    return None
def keep(p, kind):
    held_stat["seen"] += 1
    if os.name != "posix": return               # an open descriptor would make the unlink fail there
    if len(kept) >= MAX_KEPT: held_stat["missed"] += 1; return   # a bounded number of descriptors; the rest is "could not check"
    try: fd = os.open(p, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    except FileNotFoundError: return
    except OSError: held_stat["missed"] += 1; return
    try:
        st = os.fstat(fd)
        regular = stat.S_ISREG(st.st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(fd); held_stat["missed"] += 1; return
    kept.append((fd, kind, st.st_size + GROWTH))
def flock(kind, start, length):
    if LAYOUT == "hhqqi": return struct.pack(LAYOUT, kind, 0, start, length, 0)
    return struct.pack(LAYOUT, start, length, 0, kind, 0)
def holder(fd):
    if fcntl is None or LAYOUT is None: return None
    try: got = fcntl.fcntl(fd, fcntl.F_GETLK, flock(fcntl.F_WRLCK, 0, 0))
    except (OSError, ValueError): return None
    return struct.unpack(LAYOUT, got[:struct.calcsize(LAYOUT)])[0 if LAYOUT == "hhqqi" else 3] != fcntl.F_UNLCK
def holder_state():
    if os.name != "posix" or fcntl is None or LAYOUT is None: return "unknown"
    unknown = held_stat["missed"] > 0
    if not kept: return "unknown"                # nothing was probed, so nothing was checked
    for fd, _k, _c in kept:
        h = holder(fd)
        if h: held_stat["ever"] = True; return "held"
        unknown = unknown or h is None
    return "unknown" if unknown else "none"
def rewrite_kept(deadline):
    # the salt-bearing heads first, so a long log cannot use the whole bound before a main file's first page is reached
    for fd, kind, cap in sorted(kept, key=lambda e: e[1] == "whole"):
        try:
            size = min(os.fstat(fd).st_size, cap)
            limit = size if kind == "whole" else min(size, PAGE1)
            os.lseek(fd, 0, os.SEEK_SET); w = 0
            while w < limit:
                if time.monotonic() >= deadline: break
                n = min(CHUNK, limit - w)
                w += os.write(fd, bytes(n) if kind == "shm" else os.urandom(n))   # a log index's head is zeroed, never randomised
            os.fsync(fd)
            if time.monotonic() >= deadline: return
        except OSError: pass
def check_other_holders():
    if fcntl is not None and LAYOUT is not None:
        for fd, kind, _c in kept:
            if kind in ("head", "shm"):
                start, length = (0x40000000, 512) if kind == "head" else (120, 9)
                try: fcntl.fcntl(fd, fcntl.F_SETLK, flock(fcntl.F_WRLCK, start, length))
                except (OSError, ValueError): pass
    state = holder_state()
    if state == "held":
        deadline = time.monotonic() + BOUND
        while True:
            rewrite_kept(deadline)
            if time.monotonic() >= deadline: break
            time.sleep(STEP)
            if holder_state() != "held": break
    rewrite_kept(time.monotonic() + BOUND)   # always, whatever was found: what a holder committed before it let go, or unseen
    state = holder_state()
    if held_stat["ever"]: state = "held"     # a program seen holding it during the erase may have written behind the rewrite
    if state == "held":
        rec("THE ERASE MAY BE INCOMPLETE: another program had the database open while the erase ran, and it may have "
            "written the database's key material back to the disk. Close that program or restart the computer; overwriting the "
            "disk's free space after that may reach what it wrote, but not reliably on SSDs or copy-on-write file systems.")
    elif state == "unknown":
        rec("The erase could not check whether another program had the database open (it never can on Windows). If one did, "
            "the erase may be incomplete: close such a program or restart the computer.")
    else:
        rec("Checked: no other program was seen holding the database when the erase ended (a program that had it open "
            "without holding a lock on it at that moment, or one on another computer through a network share, cannot be seen).")
    for fd, _k, _c in kept:
        try: os.close(fd)
        except OSError: pass
    kept.clear()
rec("uninstall watcher start")
for f in plan.get("files", []):
    try: os.remove(f); rec("removed launcher " + tok(f))
    except OSError as e: rec("launcher kept " + tok(f) + " (" + (e.strerror or type(e).__name__) + ")")   # str(e) names the path
v = plan.get("venv")
if v:
    shutil.rmtree(v, ignore_errors=True)
    rec(("removed venv " if not os.path.exists(v) else "venv KEPT (in use?) ") + tok(v))
wd = plan.get("wipe_data_dir")
# R711: a data folder the app does not own (a home folder, a drive root...) is never walked whole or removed. The plan then
# carries the app's own NAMES (decided in-process, src/safety/data_scope.py, its common names such as "models" left out),
# matched against the folder's top level when the wipe runs, so a file the app wrote while it shut down is reached too, plus
# the app's key files by path; everything else stays, and the audit log gives only its COUNT (the names are the operator's).
only = plan.get("app_only")
def linkish(p):   # a symlink, or a Windows junction (os.walk enters those); any reparse point on a Python without isjunction
    try:
        if os.path.islink(p): return True
        if hasattr(os.path, "isjunction"): return os.path.isjunction(p)
        return bool(getattr(os.lstat(p), "st_file_attributes", 0) & 0x400)
    except OSError: return True
def ours(nm):
    for c in dict.fromkeys((nm, re.sub(only["strip"], "", nm))):
        if c and (c in only["names"] or c.startswith(tuple(only["prefixes"])) or c.endswith(tuple(only["suffixes"]))): return True
    return False
def roots():
    if not only: return [wd]
    try: tops = [os.path.join(wd, nm) for nm in sorted(os.listdir(wd)) if ours(nm)]
    except OSError: tops = []
    keys = [os.path.join(wd, k) for k in only.get("key_paths", [])]
    kd = os.path.join(wd, "keys")
    try: keys += [os.path.join(kd, n) for n in os.listdir(kd) if n.endswith(tuple(only.get("key_suffixes", [])))]
    except OSError: pass
    return tops + [p for p in dict.fromkeys(keys) if os.path.lexists(p)]
if wd and os.path.isdir(wd):
    seen = wiped = 0
    for top in roots():
        if top != wd and (linkish(top) or not os.path.isdir(top)):
            k = sqlite_kind(os.path.basename(top))
            if k and linkish(top): held_stat["seen"] += 1; held_stat["missed"] += 1   # a linked store file is never followed
            elif k: keep(top, k)
            seen += 1; overwrite(top, header_only(os.path.basename(top)))
            try: os.remove(top); wiped += 1
            except OSError: pass
            continue
        for root, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if not linkish(os.path.join(root, d))]
            for nm in names:
                seen += 1; fp = os.path.join(root, nm)
                k = sqlite_kind(nm)
                if k and os.path.islink(fp): held_stat["seen"] += 1; held_stat["missed"] += 1
                elif k: keep(fp, k)
                overwrite(fp, header_only(nm))
                try: os.remove(fp); wiped += 1
                except OSError: pass
        if top != wd: shutil.rmtree(top, ignore_errors=True)
    if held_stat["seen"]:
        try: check_other_holders()
        except Exception:                     # never let the check stop the rest of the wipe or the audit log
            rec("The erase could not check whether another program had the database open. If one did, the erase may be "
                "incomplete: close such a program or restart the computer.")
            for fd, _k, _c in kept:
                try: os.close(fd)
                except OSError: pass
    scrubbed = 0                              # optional defence-in-depth free-space scrub
    passes = plan.get("passes")
    if passes in (1, 3, 8):
        try: os.makedirs(wd, exist_ok=True)
        except OSError: pass
        for i in range(passes):
            fp = os.path.join(wd, ".oo_scrub_%d.bin" % i)
            try:
                with open(fp, "wb", buffering=0) as f:
                    while True:
                        try: f.write(os.urandom(CHUNK))
                        except OSError: break
                        scrubbed += CHUNK
                    try: f.flush(); os.fsync(f.fileno())
                    except OSError: pass
            except OSError: pass
            try: os.remove(fp)
            except OSError: pass
    if only:
        try: os.rmdir(os.path.join(wd, "keys"))     # only when empty: what is left in it is not the app's
        except OSError: pass
        try: left = len(os.listdir(wd))
        except OSError: left = -1
        rec("wiped the app's own files in %s, a folder it does not own (%s), and left the folder and %d other entries"
            % (tok(wd), only.get("reason"), left))
    else:
        shutil.rmtree(wd, ignore_errors=True)
    rec("wiped data %s (%d/%d files, crypto-erase: DB salt pages destroyed; %d scrub bytes)" % (tok(wd), wiped, seen, scrubbed))
# DuckDB analytics cache can live outside the data dir (OO_COLUMNAR_DIR). Only present in
# the plan when it actually differs from wd -- head-wipe the two known files there (never
# rmtree an externally-configured directory we don't otherwise own).
sd = plan.get("wipe_store_dir")
if sd and os.path.isdir(sd):
    sd_wiped = 0
    for nm in ("analytics.duckdb", "analytics.duckdb.kdf", "analytics.duckdb.wal", ".oo_columnar_probe.duckdb"):
        fp = os.path.join(sd, nm)
        if os.path.exists(fp):
            overwrite(fp, True)
            try: os.remove(fp); sd_wiped += 1
            except OSError: pass
    rec("wiped columnar store %s (%d files, header-only)" % (tok(sd), sd_wiped))
af = plan.get("app_folder")
if af and os.path.isdir(af):
    shutil.rmtree(af, ignore_errors=True)
    rec(("removed app folder " if not os.path.exists(af) else "app folder KEPT ") + tok(af))
rec("uninstall watcher done")
lp = plan.get("audit_log")
if lp:
    try:
        with open(lp, "a", encoding="utf-8", errors="backslashreplace") as fh:
            fh.write("\n".join(log) + "\n")
    except OSError: pass
"""

# Row 98: the watcher waits for the server with the ONE liveness probe (src/pid_probe.py), carried as source because this
# process cannot import src. Its old inline os.kill(pid, 0) was TerminateProcess on Windows: it killed the server it waited for.
try:
    _WATCHER_SRC = _WATCHER_SRC.replace("__PID_PROBE__\n", textwrap.dedent(inspect.getsource(pid_probe.pid_alive)), 1)
except (OSError, TypeError) as _exc:  # an install without the .py sources: the module still imports, and _default_spawn refuses
    _LOG.warning("uninstall: the liveness probe's source could not be read (%s); the uninstall watcher cannot be started", type(_exc).__name__)



def repo_root() -> Path:
    """The installed app directory (where install.sh and .venv live)."""
    return Path(__file__).resolve().parents[2]


def _desktop_dir() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                             text=True, timeout=3)
        p = Path(out.stdout.strip())
        if out.returncode == 0 and str(p):
            return p
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def _launcher_paths() -> list[Path]:
    """Every launcher install.sh may have created, all OSes (incl. the retired
    Desk launcher from older installs, so uninstall cleans those up too)."""
    apps = Path.home() / ".local" / "share" / "applications"
    desk = _desktop_dir()
    mac = Path.home() / "Desktop"
    stems = (APP_NAME, f"{APP_NAME}-desk", f"{APP_NAME}-uninstall")
    out: list[Path] = []
    for stem in stems:
        out.append(apps / f"{stem}.desktop")
        out.append(desk / f"{stem}.desktop")
    out += [mac / "Open Omniscience.command",
            mac / "Open Omniscience — Desk.command",
            mac / "Uninstall Open Omniscience.command"]
    return out


def _mode_label(*, remove_folder: bool, wipe_data: bool) -> str:
    if wipe_data and remove_folder:
        return "secure"
    if wipe_data:
        return "custom"  # data wiped without removing the folder (only via Customize)
    if remove_folder:
        return "full"
    return "minimal"


def plan_uninstall(src_dir: Path | None = None, *, remove_folder: bool = False,
                   wipe_data: bool = False) -> dict:
    """Discover what an uninstall would remove (pure; deletes nothing).

    ``remove_folder``/``wipe_data`` widen the plan beyond the always-removed venv +
    launchers. The data dir is reported for honesty whether or not it is wiped."""
    root = Path(src_dir) if src_dir else repo_root()
    venv = root / ".venv"
    launchers = [p for p in _launcher_paths() if p.exists()]
    try:
        from src.paths import data_dir as _data_dir
        data = str(_data_dir())
        data_exists = Path(data).is_dir()
    except Exception:  # pragma: no cover - paths always importable in practice
        data, data_exists = None, False
    # The DuckDB analytics cache can live outside the data dir (``OO_COLUMNAR_DIR``).
    # crypto_erase.quick_crypto_erase() head-wipes it there independently of the data-dir
    # walk; the watcher must do the same or a secure uninstall silently misses it when the
    # override is set (audit follow-up on OO-02). Only reported when it actually differs.
    store: str | None = None
    try:
        from src.analytics.columnar import _store_dir as _columnar_store_dir
        s = str(_columnar_store_dir())
        if s != data:
            store = s
    except Exception:  # pragma: no cover - columnar extra may be absent
        store = None
    install_script = root / "install.sh"
    app_folder = str(root) if remove_folder else None
    wipe_data_dir = data if (wipe_data and data and data_exists) else None
    wipe_store_dir = store if (wipe_data and store and Path(store).is_dir()) else None
    # R711: the scope of the data folder, read now (the watcher only applies it). A broad one is wiped by the app's names only.
    data_scope = None
    if data and data_exists:
        try:
            from src.safety.data_scope import folder_scope

            data_scope = folder_scope(Path(data))
        except Exception:  # noqa: BLE001 - unknown scope: reported as unknown, and the wipe below keeps to the app's names
            data_scope = {"broad": True, "reason": "unknown"}
    removable = bool(
        venv.exists() or launchers or (remove_folder and root.exists()) or wipe_data_dir
    )
    return {
        "mode": _mode_label(remove_folder=remove_folder, wipe_data=wipe_data),
        "src_dir": str(root),
        "venv": str(venv) if venv.exists() else None,
        "launchers": [str(p) for p in launchers],
        "data_dir": data,                       # reported for honesty, always
        "install_script": str(install_script) if install_script.exists() else None,
        "remove_folder": remove_folder,
        "app_folder": app_folder,               # the folder removed in full/secure
        "wipe_data": wipe_data,
        "wipe_data_dir": wipe_data_dir,         # the data dir wiped in secure
        "wipe_store_dir": wipe_store_dir,       # OO_COLUMNAR_DIR override, wiped in secure
        "data_scope": data_scope,               # R711: a broad folder keeps everything but the app's own files
        "audit_log": str(AUDIT_LOG),
        "removable": removable,
    }


def _system_python() -> str:
    """A Python that will survive the venv removal (prefer the OS one)."""
    for cand in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if Path(cand).exists():
            return cand
    return shutil.which("python3") or sys.executable


def _lane_names() -> list[str]:
    """The lane database file names, from the lane registry (each with its own salt page)."""
    try:
        from src.versioned.lanes import all_lanes

        return [spec.filename for spec in all_lanes()]
    except Exception:  # noqa: BLE001 - the registry's names as of writing; a whole rewrite is the slow fallback, never a skip
        return ["wiki.db", "law.db", "osm.db", "medical.db"]


def _app_only(scope: dict | None) -> dict | None:
    """The app's own names for the watcher when the data folder is broad (R711), else None (the folder is removed whole)."""
    if not scope or not scope.get("broad"):
        return None
    from src.safety.crypto_erase import (
        _KEY_FILES,
        _KEYS_PENDING,
        _OTHER_KEY_FILES,
        KEY_FORM_SUFFIXES,
    )
    from src.safety.data_scope import owned_spec

    keys = [f"keys/{n}" for n in (*_KEY_FILES, *_OTHER_KEY_FILES, _KEYS_PENDING)]
    return {**owned_spec(shared=True), "key_paths": keys, "key_suffixes": list(KEY_FORM_SUFFIXES), "reason": scope.get("reason")}


def _default_spawn(plan: dict, server_pid: int) -> None:
    """Launch the detached watcher that removes the planned paths after the server exits."""
    payload = {
        "files": plan["launchers"],
        "venv": plan["venv"],
        "app_folder": plan.get("app_folder"),
        "wipe_data_dir": plan.get("wipe_data_dir"),
        "wipe_store_dir": plan.get("wipe_store_dir"),  # OO_COLUMNAR_DIR override, if set
        "passes": plan.get("passes"),  # optional defence-in-depth free-space scrub (1/3/8)
        "enc_names": _lane_names(),  # row 30: the lane databases, header-only like the corpus
        "app_only": _app_only(plan.get("data_scope")),  # R711: a broad data folder is wiped by the app's own names only
        "audit_log": plan.get("audit_log"),
    }
    if "__PID_PROBE__" in _WATCHER_SRC:
        # Without the probe the watcher cannot wait for the server, and erasing while the server still writes is the one outcome
        # this must never have: nothing is started, nothing is erased, and the caller reports the failure.
        raise RuntimeError("the uninstall watcher cannot be started: its liveness probe's source is missing from this install")
    # The watcher outlives the app and has no use for the passphrase: it is not handed the server's copy (``child_env``).
    from src.llm.model_store import child_env

    subprocess.Popen(
        [_system_python(), "-c", _WATCHER_SRC, str(server_pid), json.dumps(payload)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,           # detach: surviving our own shutdown
        env=child_env(),
    )


def _default_arm_shutdown(delay: float = 2.0) -> None:
    """Ask the server to exit gracefully so the watcher can proceed (DB closed first)."""
    def _stop() -> None:
        time.sleep(delay)
        # No disposal here (R689): the signal runs the lifespan shutdown, which stops the jobs and the collector first and disposes
        # after them, the one order every graceful stop takes (src/safety/shutdown.py).
        _LOG.warning("uninstall: stopping the server (graceful signal to self)")
        from src.safety.shutdown import stop_self

        stop_self()
    threading.Thread(target=_stop, name="oo-uninstall", daemon=True).start()


def request_uninstall(*, confirm: bool, remove_folder: bool = False, wipe_data: bool = False,
                      src_dir: Path | None = None, passes: int | None = None,
                      _spawn=_default_spawn, _arm_shutdown=_default_arm_shutdown) -> dict:
    """Schedule removal per the chosen mode, then stop the server.

    Requires ``confirm=True``. ``remove_folder``/``wipe_data`` select the mode
    (minimal/full/secure/custom — see the module docstring). ``passes`` (1/3/8, only
    meaningful when data is wiped) adds an optional defence-in-depth free-space scrub in
    the watcher on top of the crypto-erase. The actual deletion happens in a detached
    watcher *after* this process exits. ``_spawn``/``_arm_shutdown`` are injected in tests
    so nothing is ever deleted there.
    """
    if not confirm:
        raise PermissionError("request_uninstall requires confirm=True")
    plan = plan_uninstall(src_dir, remove_folder=remove_folder, wipe_data=wipe_data)
    if passes is not None:
        plan["passes"] = passes  # honored by the watcher only when data is wiped
    if not plan["removable"]:
        return {**plan, "scheduled": False,
                "note": "Nothing to remove (no virtualenv or launchers found). "
                        "Delete the app folder manually if needed."}
    _spawn(plan, os.getpid())
    _arm_shutdown()
    _LOG.warning("uninstall scheduled: mode=%s venv=%s launchers=%d folder=%s data=%s",
                 plan["mode"], bool(plan["venv"]), len(plan["launchers"]),   # R734/R736: no path in the app's log
                 bool(plan.get("app_folder")), bool(plan.get("wipe_data_dir")))
    overwrite_note = (
        "Overwrite-in-place does NOT guarantee unrecoverability on SSD/flash or "
        "copy-on-write filesystems — the real protection is that your corpus was "
        "encrypted at rest and the key is now destroyed. For a guaranteed wipe, use "
        "full-disk encryption (LUKS/Qubes/Tails) and destroy that key."
    ) if plan.get("wipe_data_dir") else None
    note = ("The app will stop in a moment, then the virtualenv and desktop launchers "
            "are removed")
    if plan.get("app_folder"):
        note += ", the app folder is deleted"
    if plan.get("wipe_data_dir"):
        note += ", and your data and keys are wiped (irreversible)"
    else:
        note += "; your data is KEPT (use Secure mode, or Panic wipe, to destroy it)"
    note += f". An uninstall log is written to {plan['audit_log']}."
    return {**plan, "scheduled": True, "data_kept": not bool(plan.get("wipe_data_dir")),
            "overwrite_limit": overwrite_note, "note": note}
