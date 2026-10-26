"""The launcher evidence files never lose a row to another launcher (R173).

Before: launcher_exits.jsonl, launcher_stops.jsonl and launcher_stderr.jsonl are written and trimmed by every launcher that runs. A trim was "newest N
lines to ``f.tmp``, rename over f": an append between the two steps went to the replaced file, two trims shared one temp name, and the stderr filter held
the file open for the life of the server, so a trim by another launcher sent every later row of a live one to a file nobody could read. MEASURED 17 Oct
with 8 launchers at once, the file seeded to 39 rows so the trim fires: bash exit rows 8 lost of 96, bash stop rows 69 of 96 (files left with 0 and 1
lines), PowerShell exit rows 4 of 48 with 2 torn lines; and the launcher whose server was alive lost all 3 of its stderr rows (0 of 3 in 3 of 3 rounds)
when two later launchers started and ended under it.
After: every append and every trim of one file happens under one lock for that file (flock, else a directory holding its owner's pid; a named Mutex in
PowerShell), a trim writes to a temp name of its own, the filter appends one row at a time, and a lock not obtained in time costs the TRIM, never the row.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAUNCH_SH = REPO / "scripts" / "launch.sh"
LAUNCH_PS1 = REPO / "scripts" / "launch_server.ps1"

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the launcher is a bash script")
_PWSH = os.environ.get("OO_PWSH") or shutil.which("pwsh")
_needs_pwsh = pytest.mark.skipif(not _PWSH or os.name == "nt", reason="no PowerShell 7 here (OO_PWSH)")

#: The longest append-plus-trim hold measured on 17 Oct under the heaviest load tried: 8 launchers at once beside 8 busy loops on 4 CPUs (bash 92.4 ms
#: over 72 holds; PowerShell 7, cold, 515.0 ms over 48; unloaded they were 27.3 ms and 144.9 ms). WHAT THE WAIT PROTECTS: the time a launcher is willing to
#: wait for the lock before it hands its row to a deferred writer (a wait below the longest hold defers more rows, and costs latency only, never a row).
MEASURED_BASH_HOLD_MS = 92.4
MEASURED_PS_HOLD_MS = 515.0
MSG = "Fatal Python error: Aborted"


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _server_body(mode: str) -> str:
    if mode == "exit3":
        return "exit 3\n"
    if mode == "wait":
        return 'trap \'exit 0\' TERM HUP\necho up > "$OO_TEST_PIDFILE.up"\nwhile :; do sleep 0.1; done\n'
    if mode == "abort_in_stop":  # a server that aborts (134) while it shuts down on a requested stop
        return 'trap \'exit 134\' TERM HUP\necho up > "$OO_TEST_PIDFILE.up"\nwhile :; do sleep 0.1; done\n'
    if mode == "slowerr":
        return f'echo "{MSG}" >&2\nsleep 4\necho "{MSG}" >&2\nexit 3\n'
    raise AssertionError(mode)


def _seed(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"schema": "seed", "pid": 900000 + i}) + "\n" for i in range(n)), encoding="utf-8")


def _rows(path: Path) -> tuple[list[dict], int]:
    """(rows, torn lines): a line that is not JSON is counted and never read as a row."""
    out: list[dict] = []
    torn = 0
    for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []:
        if not x.strip():
            continue
        try:
            out.append(json.loads(x))
        except ValueError:
            torn += 1
    return out, torn


class _Bash:
    """Launchers over ONE data folder. Each gets a bin folder of its own: a stub rewritten under a running bash script changes what it runs."""

    def __init__(self, tmp: Path, *, no_flock: bool = False, awk: str | None = None):
        self.tmp = tmp
        self.data = tmp / "data"
        self.root = tmp / "oo"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy2(LAUNCH_SH, self.root / "scripts" / "launch.sh")
        (self.root / "pyproject.toml").write_text("[project]\nname='fake'\n", encoding="utf-8")
        (self.root / ".venv" / "bin").mkdir(parents=True)
        (self.root / ".venv" / "bin" / "activate").write_text("", encoding="utf-8")
        self.base_path = os.environ["PATH"]
        if awk:  # an awk of the named implementation first on the PATH, as the all-awk test of the filter does
            d = tmp / "awkbin"
            d.mkdir()
            _exe(d / "awk", f'#!/bin/sh\nexec "{awk}" "$@"\n')
            self.base_path = f"{d}{os.pathsep}{self.base_path}"
        if no_flock:  # every tool but flock, so the launcher takes the mkdir-lock path
            tools = tmp / "tools"
            tools.mkdir()
            for d in self.base_path.split(os.pathsep):
                if not os.path.isdir(d):
                    continue
                for n in os.listdir(d):
                    p = os.path.join(d, n)
                    if n != "flock" and not (tools / n).exists() and os.access(p, os.X_OK) and os.path.isfile(p):
                        (tools / n).symlink_to(p)
            self.base_path = str(tools)
            assert not shutil.which("flock", path=self.base_path)

    def start(self, name: str, mode: str) -> tuple[subprocess.Popen, Path]:
        mine = self.tmp / f"bin_{name}"
        mine.mkdir()
        _exe(mine / "curl", '#!/usr/bin/env bash\nf="$OO_TEST_CURLCOUNT"\nn=$(cat "$f" 2>/dev/null || echo 0)\necho $((n+1)) > "$f"\n[ "$n" -ge 1 ]\n')
        _exe(mine / "xdg-open", "#!/usr/bin/env bash\nexit 0\n")
        _exe(mine / "open-omniscience", '#!/usr/bin/env bash\necho $$ > "$OO_TEST_PIDFILE"\n' + _server_body(mode))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "XDG_DATA_HOME"))}
        env.update(PATH=f"{mine}{os.pathsep}{self.base_path}", HOME=str(self.tmp / "home"), OO_DATA_DIR=str(self.data),
                   OO_TEST_PIDFILE=str(self.tmp / f"{name}.pid"), OO_TEST_CURLCOUNT=str(self.tmp / f"{name}.curl"))
        proc = subprocess.Popen(["bash", str(self.root / "scripts" / "launch.sh")], cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return proc, self.tmp / f"{name}.pid"


def _pid(path: Path, secs: float = 30) -> int:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if path.exists() and path.read_text(encoding="utf-8").strip().isdigit():
            return int(path.read_text(encoding="utf-8").strip())
        time.sleep(0.05)
    raise AssertionError(f"{path} never got a pid")


def _exits_round(tmp: Path, n: int, **kw) -> tuple[list[int], Path]:
    b = _Bash(tmp, **kw)
    f = b.data / "diagnostics" / "launcher_exits.jsonl"
    _seed(f, 39)  # one more row from each launcher and the over-40 trim fires
    procs = [b.start(f"l{i}", "exit3") for i in range(n)]
    for p, _ in procs:
        p.wait(timeout=120)
    return [_pid(pf) for _, pf in procs], f


def _assert_all_present(pids: list[int], f: Path, what: str) -> None:
    rows, torn = _rows(f)
    missing = [p for p in pids if p not in {r.get("pid") for r in rows}]
    assert not missing, f"{what}: {len(missing)} of {len(pids)} rows lost ({len(rows)} lines left, {torn} torn)"
    assert not torn, f"{what}: {torn} torn lines"
    assert len(rows) <= 40, f"{what}: the trim did not run ({len(rows)} lines)"


@posix_only
@pytest.mark.parametrize("no_flock", [False, True], ids=["flock", "mkdir-lock"])
def test_eight_launchers_at_once_lose_no_exit_row(tmp_path, no_flock):
    for r in range(3):
        sub = tmp_path / f"r{r}"
        sub.mkdir()
        pids, f = _exits_round(sub, 8, no_flock=no_flock)
        _assert_all_present(pids, f, f"exits round {r}")


@posix_only
@pytest.mark.parametrize("no_flock", [False, True], ids=["flock", "mkdir-lock"])
def test_eight_launchers_stopped_at_once_lose_no_stop_row(tmp_path, no_flock):
    for r in range(3):
        sub = tmp_path / f"r{r}"
        sub.mkdir()
        b = _Bash(sub, no_flock=no_flock)
        f = b.data / "diagnostics" / "launcher_stops.jsonl"
        _seed(f, 39)
        procs = [b.start(f"l{i}", "wait") for i in range(8)]
        for _, pf in procs:
            end = time.monotonic() + 30
            while not Path(str(pf) + ".up").exists() and time.monotonic() < end:
                time.sleep(0.05)
            assert Path(str(pf) + ".up").exists(), "a fake server did not start"
        time.sleep(1.0)  # the launcher installs its traps right after the server starts
        pids = [_pid(pf) for _, pf in procs]
        for p, _ in procs:
            os.kill(p.pid, signal.SIGTERM)
        for p, _ in procs:
            p.wait(timeout=60)
        _assert_all_present(pids, f, f"stops round {r}")


@posix_only
@pytest.mark.parametrize("no_flock", [False, True], ids=["flock", "mkdir-lock"])
def test_a_live_launchers_stderr_rows_survive_the_trim_of_a_later_launcher(tmp_path, no_flock):
    """A's server prints an abort header, waits, prints another. B then C start and end under it (the file is over 100 lines again after B's summary, so
    C's launch-time trim fires). A's 2 line rows and its summary must all be in the file that is there at the end."""
    b = _Bash(tmp_path, no_flock=no_flock)
    f = b.data / "diagnostics" / "launcher_stderr.jsonl"
    _seed(f, 101)
    a, apid = b.start("A", "slowerr")
    time.sleep(1.5)
    for name in ("B", "C"):
        p, _ = b.start(name, "exit3")
        p.wait(timeout=60)
    a.wait(timeout=60)
    time.sleep(0.5)
    mine = [r for r in _rows(f)[0] if r.get("pid") == _pid(apid)]
    assert sum(1 for r in mine if "line" in r) == 2 and sum(1 for r in mine if r.get("summary")) == 1, mine
    assert len(_rows(f)[0]) <= 105


# --- the lock itself: a held lock costs the TRIM and never the row; a dead owner's lock is taken over ------------------------------------------

def _helpers(tmp: Path, *, no_flock: bool) -> tuple[Path, dict[str, str]]:
    src = LAUNCH_SH.read_text(encoding="utf-8")
    block = src[src.index("OO_REC_LOCK_WAIT_MS="):src.index("# --- end of the evidence file helpers")]
    h = tmp / "helpers.sh"
    h.write_text(block, encoding="utf-8")
    env = dict(os.environ)
    if no_flock:
        b = _Bash(tmp / "tools_holder", no_flock=True)
        env["PATH"] = b.base_path
    return h, env


def _wait_for(pred, secs: float = 20) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


@posix_only
@pytest.mark.parametrize("no_flock", [False, True], ids=["flock", "mkdir-lock"])
def test_a_row_that_times_out_is_written_under_the_lock_after_the_holder_trims_never_before(tmp_path, no_flock):
    """R174. A holder takes the lock and trims slowly (tail ... sleep ... mv). A second launcher, 0.3 s in, cannot get the lock inside its wait. On the
    R173 build it appended WITHOUT the lock, between the holder's tail and its mv, and the mv took the row away (the loaded 8-way sweep lost 15 of 240).
    Now it returns at once, having handed the row to a detached child that waits for the lock, and the row is in the file after the trim, once."""
    h, env = _helpers(tmp_path, no_flock=no_flock)
    f = tmp_path / "x.jsonl"
    _seed(f, 60)
    slow = (f'. "{h}"; OO_REC_LOCK_WAIT_MS=100; _slow() {{ tail -n 20 "$1" > "$1.tmp.slow"; sleep 1.5; mv -f "$1.tmp.slow" "$1"; }}; '
            f'oo_rec_locked "{f}" _slow "{f}"')
    holder = subprocess.Popen(["bash", "-c", slow], env=env)
    try:
        time.sleep(0.4)  # the holder is inside its slow trim
        t = time.monotonic()
        subprocess.run(["bash", "-c", f'. "{h}"; OO_REC_LOCK_WAIT_MS=100; oo_rec_append "{f}" \'{{"pid":7}}\' 40 20'], env=env, check=True, timeout=30)
        took = time.monotonic() - t
        assert took < 1.0, f"the launcher handed the row on and went; it did not wait for the holder ({took:.2f} s)"
        assert {"pid": 7} not in _rows(f)[0], "nothing is written while the lock is held by someone else"
        holder.wait(timeout=30)
        assert _wait_for(lambda: {"pid": 7} in _rows(f)[0]), "the deferred row never landed"
    finally:
        holder.kill()
        holder.wait()
    time.sleep(0.5)
    rows = _rows(f)[0]
    assert sum(1 for r in rows if r == {"pid": 7}) == 1 and len(rows) == 21, "once, after the holder's trim (20 kept) and before any later trim is due"
    assert sorted(x.name for x in tmp_path.iterdir() if x.name.startswith("x.jsonl")) in (["x.jsonl", "x.jsonl.lock"], ["x.jsonl"]), "the child left no file behind"


@posix_only
def test_a_filesystem_that_cannot_lock_gets_the_row_appended_directly_not_lost(tmp_path):
    """Opus read of #1444. `flock ... || exit 99` read every flock failure as "held, try later"; the deferred child (no time bound) then failed the same way and
    wrote nothing, so on a volume that cannot lock at all (NFS without lockd, some FUSE and shared folders) the exit, stop and stderr rows vanished. A flock that
    says "cannot lock" (not its -E 99 for "held") now reaches the direct append, as a folder that cannot be written already did."""
    h, env = _helpers(tmp_path, no_flock=False)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    # works on /dev/null (the probe for -E) and fails on the data file's lock descriptor, as a filesystem without lock support does
    _exe(fake / "flock", '#!/bin/sh\ncase "$*" in *"/dev/null true"*) exit 0 ;; esac\necho "flock: 9: no locks available" >&2\nexit 1\n')
    env["PATH"] = f"{fake}{os.pathsep}{env['PATH']}"
    f = tmp_path / "x.jsonl"
    _seed(f, 3)
    subprocess.run(["bash", "-c", f'. "{h}"; OO_REC_LOCK_WAIT_MS=100; oo_rec_append "{f}" \'{{"pid":9}}\' 40 20'], env=env, check=True, timeout=30)
    assert _wait_for(lambda: {"pid": 9} in _rows(f)[0]), "the row was lost on a filesystem that cannot lock"


@posix_only
def test_a_stop_whose_teardown_crashes_leaves_an_exit_row_and_a_clean_stop_does_not(tmp_path):
    """Opus read of #1444. A Ctrl-C followed by an abort (134) in the teardown left only the stop row, which the next boot reads as "a stop was asked ... Not a
    crash". The crash status is now an exit row as well; the statuses a working stop ends in (here 0) still write none."""
    results = {}
    for mode, label in (("abort_in_stop", "crash"), ("wait", "clean")):
        sub = tmp_path / label
        sub.mkdir()
        b = _Bash(sub)
        proc, pf = b.start("l0", mode)
        end = time.monotonic() + 30
        while not Path(str(pf) + ".up").exists() and time.monotonic() < end:
            time.sleep(0.05)
        assert Path(str(pf) + ".up").exists(), "the fake server did not start"
        time.sleep(1.0)  # the launcher installs its traps right after the server starts
        pid = _pid(pf)
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=60)
        results[label] = (pid, _rows(b.data / "diagnostics" / "launcher_exits.jsonl")[0], _rows(b.data / "diagnostics" / "launcher_stops.jsonl")[0])
    pid, exits, stops = results["crash"]
    assert any(r.get("pid") == pid and r.get("status") == 134 for r in exits), "a crash in a requested stop's teardown has no exit row"
    assert any(r.get("pid") == pid for r in stops), "the stop row is still written"
    pid, exits, stops = results["clean"]
    assert not any(r.get("pid") == pid for r in exits), "a stop that ended well wrote an exit row"
    assert any(r.get("pid") == pid for r in stops)


@posix_only
@pytest.mark.parametrize("no_flock", [False, True], ids=["flock", "mkdir-lock"])
def test_a_holder_that_is_stuck_for_ever_makes_the_row_late_and_a_killed_holder_releases_it(tmp_path, no_flock):
    """The ONE way a row is late (R174): the holder is alive and does not let go. The row waits with it, is not lost, and is written the moment the holder dies."""
    h, env = _helpers(tmp_path, no_flock=no_flock)
    f = tmp_path / "x.jsonl"
    _seed(f, 5)
    holder = subprocess.Popen(["bash", "-c", f'. "{h}"; oo_rec_locked "{f}" sleep 300'], env=env, start_new_session=True)
    try:
        time.sleep(0.5)
        subprocess.run(["bash", "-c", f'. "{h}"; OO_REC_LOCK_WAIT_MS=50; oo_rec_append "{f}" \'{{"pid":8}}\' 40 20'], env=env, check=True, timeout=30)
        time.sleep(1.5)
        assert {"pid": 8} not in _rows(f)[0], "late while the holder lives"
        os.killpg(holder.pid, signal.SIGKILL)  # the holder and what it was running die together, as a killed launcher does
        holder.wait()
        assert _wait_for(lambda: {"pid": 8} in _rows(f)[0], 30), "written once the holder is gone"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()


@posix_only
def test_a_lock_whose_owner_died_is_taken_over_not_waited_on(tmp_path):
    h, env = _helpers(tmp_path, no_flock=True)
    f = tmp_path / "x.jsonl"
    _seed(f, 60)
    dead = subprocess.Popen(["true"])
    dead.wait()
    (tmp_path / "x.jsonl.lock.d").mkdir()
    (tmp_path / "x.jsonl.lock.d" / "pid").write_text(str(dead.pid), encoding="utf-8")
    subprocess.run(["bash", "-c", f'. "{h}"; oo_rec_append "{f}" \'{{"pid":2}}\' 40 20'], env=env, check=True, timeout=30)
    rows = _rows(f)[0]
    assert rows[-1] == {"pid": 2} and len(rows) == 20, "the dead owner's lock was taken over, so this append trimmed"
    assert not (tmp_path / "x.jsonl.lock.d").exists(), "and released"


@posix_only
def test_the_wait_is_not_below_what_was_measured_and_is_named_for_it():
    sh = int(re.search(r"^OO_REC_LOCK_WAIT_MS=(\d+)$", LAUNCH_SH.read_text(encoding="utf-8"), re.M).group(1))
    ps = int(re.search(r"^\$RecLockWaitMs = (\d+)$", LAUNCH_PS1.read_text(encoding="utf-8"), re.M).group(1))
    assert sh >= MEASURED_BASH_HOLD_MS and sh - MEASURED_BASH_HOLD_MS < 10, "rounded up from the measurement, not a guess"
    assert ps >= MEASURED_PS_HOLD_MS and ps - MEASURED_PS_HOLD_MS < 10
    assert "4 CPUs" in LAUNCH_SH.read_text(encoding="utf-8") and "4 CPUs" in LAUNCH_PS1.read_text(encoding="utf-8"), "the load the number was measured under is named"
    assert "WHAT THE WAIT PROTECTS" in LAUNCH_SH.read_text(encoding="utf-8")


@posix_only
def test_the_awk_filter_no_longer_holds_the_file_open():
    src = LAUNCH_SH.read_text(encoding="utf-8")
    awk = src[src.index("stderr_filter() {"):src.index("# Start the server in the background")]
    assert ">> out" in awk and "close(out)" in awk and "close(cmd)" in awk
    assert re.search(r'printf "[^\n]*>> out\n', awk) is None, "a row is never printed straight to the held file"


# --- PowerShell 7 on Linux, a fake server: the same 8-launcher run -----------------------------------------------------------------------------

@_needs_pwsh
def test_eight_powershell_launchers_lose_no_exit_row_and_tear_no_line(tmp_path):
    copy = tmp_path / "w.ps1"
    copy.write_text(LAUNCH_PS1.read_text(encoding="utf-8"), encoding="utf-8")
    data = tmp_path / "data"
    f = data / "diagnostics" / "launcher_exits.jsonl"
    _seed(f, 39)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
    procs = []
    for i in range(8):
        server = tmp_path / f"server_{i}"
        _exe(server, "#!/usr/bin/env bash\nexit 3\n")
        marker = tmp_path / f"{i}.marker"
        procs.append((subprocess.Popen([_PWSH, "-NoProfile", "-File", str(copy), "-App", str(server), "-Marker", str(marker), "-DataDir", str(data)],
                                       env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), marker))
    for p, _ in procs:
        p.wait(timeout=120)
    _assert_all_present([int(m.read_text(encoding="utf-8")) for _, m in procs], f, "pwsh exits")
    assert not list((data / "diagnostics").glob("*.tmp.*")), "no temp file left behind"


def test_the_ps1_text_has_the_mutex_the_replace_and_a_row_per_attempt():
    t = LAUNCH_PS1.read_text(encoding="utf-8")
    assert "System.Threading.Mutex" in t and "[System.IO.File]::Replace(" in t and "[NullString]::Value" in t
    assert "$writable = $false" not in t, "a failed append no longer switches the later rows off"
    assert "WriteAllLines($exitRecord" not in t and "WriteAllLines($stopRecord" not in t and "WriteAllLines($stderrRecord" not in t


# --- what the change leaves behind, and what keeps it from going back (R173 confirmations) -------------------------------------------------

@posix_only
def test_the_rows_are_the_bytes_they_were_before_the_lock(tmp_path):
    """No new field and no new byte: the exact shape of every row, with the time and the pids blanked."""
    b = _Bash(tmp_path)
    p, _ = b.start("a", "slowerr")
    p.wait(timeout=60)
    q, qpf = b.start("w", "wait")
    end = time.monotonic() + 20
    while not Path(str(qpf) + ".up").exists() and time.monotonic() < end:
        time.sleep(0.05)
    time.sleep(0.8)
    os.kill(q.pid, signal.SIGTERM)
    q.wait(timeout=60)
    # The stderr filter is a process substitution: it writes its summary row when the pipe CLOSES, after the launcher itself has exited (scripts/launch.sh
    # says so at the filter). The loaded full-suite run of 17 Oct read the file before the last launch's summary row (kept_lines 0) was written and saw
    # every other row; so the read waits for the two summary rows this test starts, up to the same 20 s the test gives the server to come up.
    stderr_rows = b.data / "diagnostics" / "launcher_stderr.jsonl"
    end = time.monotonic() + 20
    while time.monotonic() < end:
        if stderr_rows.exists() and stderr_rows.read_text(encoding="utf-8").count('"summary":true') >= 2:
            break
        time.sleep(0.05)

    def shape(name):
        return re.sub(r'"(at|started_at)":"[^"]*"|"pid":\d+|"boot_id":"[^"]*"', lambda m: m.group(0).split(":")[0] + ":X", (b.data / "diagnostics" / name).read_text(encoding="utf-8"))

    assert shape("launcher_exits.jsonl") == '{"schema":"oo-launcher-exit-1","at":X,"started_at":X,"pid":X,"boot_id":X,"status":3,"signal":null}\n'
    assert shape("launcher_stops.jsonl") == '{"schema":"oo-launcher-stop-1","at":X,"pid":X,"boot_id":X,"signal":"SIGTERM"}\n'
    line = '{"schema":"oo-launcher-stderr-1","at":X,"pid":X,"boot_id":X,"line":"' + MSG + '"}\n'
    assert shape("launcher_stderr.jsonl") == line + line + ('{"schema":"oo-launcher-stderr-1","at":X,"pid":X,"boot_id":X,"summary":true,"kept_lines":2,"dropped_lines":0,"over_cap_lines":0}\n'
                                                      + '{"schema":"oo-launcher-stderr-1","at":X,"pid":X,"boot_id":X,"summary":true,"kept_lines":0,"dropped_lines":0,"over_cap_lines":0}\n')


@posix_only
def test_after_a_normal_exit_only_the_empty_flock_files_are_left(tmp_path):
    pids, f = _exits_round(tmp_path, 3)
    left = sorted(x.name for x in f.parent.iterdir())
    assert left == ["launcher_exits.jsonl", "launcher_exits.jsonl.lock", "launcher_stderr.jsonl", "launcher_stderr.jsonl.lock"], left
    assert all(x.stat().st_size == 0 for x in f.parent.glob("*.lock")), "the lock files hold no bytes"


@posix_only
def test_the_mkdir_lock_leaves_nothing_after_a_normal_exit(tmp_path):
    pids, f = _exits_round(tmp_path, 3, no_flock=True)
    assert sorted(x.name for x in f.parent.iterdir()) == ["launcher_exits.jsonl", "launcher_stderr.jsonl"], "the rows' files and nothing of the lock"


@posix_only
def test_a_killed_holder_leaves_its_lock_directory_and_the_next_append_takes_it_over_and_removes_it(tmp_path):
    h, env = _helpers(tmp_path, no_flock=True)
    f = tmp_path / "x.jsonl"
    f.write_text("", encoding="utf-8")
    # the holder is killed with SIGKILL while it holds the lock (it kills the shell that took the lock)
    subprocess.run(["bash", "-c", f'. "{h}"; oo_rec_locked "{f}" bash -c \'kill -9 $PPID\''], env=env, timeout=30)
    d = tmp_path / "x.jsonl.lock.d"
    assert d.is_dir() and [x.name for x in d.iterdir()] == ["pid"], "the stale lock stays until the next launcher"
    assert (d / "pid").stat().st_size <= 8, "a pid and a newline: the only bytes a killed holder can leave"
    subprocess.run(["bash", "-c", f'. "{h}"; oo_rec_append "{f}" \'{{"pid":3}}\' 40 20'], env=env, check=True, timeout=30)
    assert not d.exists() and sorted(x.name for x in tmp_path.iterdir() if x.name.startswith("x.")) == ["x.jsonl"]
    assert _rows(f)[0] == [{"pid": 3}]


@posix_only
def test_a_temp_file_left_by_a_killed_trim_is_removed_by_the_next_trim_and_a_live_ones_is_not(tmp_path):
    h, env = _helpers(tmp_path, no_flock=False)
    f = tmp_path / "x.jsonl"
    _seed(f, 60)
    dead = subprocess.Popen(["true"])
    dead.wait()
    live = subprocess.Popen(["sleep", "30"])
    try:
        (tmp_path / f"x.jsonl.tmp.{dead.pid}").write_text("x" * 100, encoding="utf-8")
        (tmp_path / f"x.jsonl.tmp.{live.pid}").write_text("y", encoding="utf-8")
        subprocess.run(["bash", "-c", f'. "{h}"; oo_rec_append "{f}" \'{{"pid":4}}\' 40 20'], env=env, check=True, timeout=30)
        names = sorted(x.name for x in tmp_path.iterdir() if x.name.startswith("x.jsonl.tmp"))
    finally:
        live.kill()
        live.wait()
    assert names == [f"x.jsonl.tmp.{live.pid}"], names


@posix_only
def test_the_filter_is_handed_the_helper_source_not_exported_functions():
    """Pin for the eval path: an exported bash function did not reach the shell the one-true-awk starts, and every row was lost with a close status of 0."""
    src = LAUNCH_SH.read_text(encoding="utf-8")
    assert "export -f" not in src, "a function in the environment is also copied into the server's environment"
    assert 'eval \\"$OO_REC_LIB\\"' in src and 'OO_REC_LIB="$(oo_rec_lib)"' in src


@posix_only
@pytest.mark.skipif(not shutil.which("original-awk"), reason="no one-true-awk here")
def test_the_filter_records_under_the_one_true_awk(tmp_path):
    b = _Bash(tmp_path, awk=shutil.which("original-awk"))
    f = b.data / "diagnostics" / "launcher_stderr.jsonl"
    p, pf = b.start("A", "slowerr")
    p.wait(timeout=60)
    mine = _rows(f)[0]
    assert sum(1 for r in mine if "line" in r) == 2 and sum(1 for r in mine if r.get("summary")) == 1, mine


@_needs_pwsh
def test_a_powershell_trim_removes_the_temp_file_of_a_dead_launcher_and_keeps_a_live_ones(tmp_path):
    copy = tmp_path / "w.ps1"
    copy.write_text(LAUNCH_PS1.read_text(encoding="utf-8"), encoding="utf-8")
    data = tmp_path / "data"
    f = data / "diagnostics" / "launcher_exits.jsonl"
    _seed(f, 45)
    dead = subprocess.Popen(["true"])
    dead.wait()
    live = subprocess.Popen(["sleep", "30"])
    try:
        (f.parent / f"launcher_exits.jsonl.tmp.{dead.pid}").write_text("x" * 50, encoding="utf-8")
        (f.parent / f"launcher_exits.jsonl.tmp.{live.pid}").write_text("y", encoding="utf-8")
        server = tmp_path / "server"
        _exe(server, "#!/usr/bin/env bash\nexit 3\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
        subprocess.run([_PWSH, "-NoProfile", "-File", str(copy), "-App", str(server), "-DataDir", str(data)], env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        names = sorted(x.name for x in f.parent.glob("launcher_exits.jsonl.tmp.*"))
    finally:
        live.kill()
        live.wait()
    assert names == [f"launcher_exits.jsonl.tmp.{live.pid}"], names


def test_the_reader_orders_stderr_lines_by_the_rows_own_time_not_by_their_place_in_the_file(tmp_path, monkeypatch):
    """R174: a row handed on by a launcher that could not get the lock lands after later rows. The lines shown are in the order they were printed."""
    from src.monitoring import exit_evidence as ee

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    d = tmp_path / "diagnostics"
    d.mkdir()
    rows = [{"schema": "oo-launcher-stderr-1", "at": at, "pid": 4242, "boot_id": None, "line": line}
            for at, line in (("2026-10-17T10:00:03Z", "free(): invalid pointer"), ("2026-10-17T10:00:01Z", "Fatal Python error: Aborted"),
                             ("2026-10-17T10:00:02Z", "free(): invalid size"))]
    (d / ee.LAUNCHER_STDERR).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = ee.launcher_stderr(4242, None, "2026-10-17T09:00:00Z")
    assert ee.STDERR_LINES_SHOWN == 2
    assert got["lines"] == ["free(): invalid size", "free(): invalid pointer"], "the newest two by the rows' own time, oldest first (file order would show 'Fatal ...' and 'invalid size')"


@_needs_pwsh
def test_a_powershell_row_that_times_out_is_written_by_a_detached_child_under_the_mutex_after_the_holder_lets_go(tmp_path):
    import hashlib

    data = tmp_path / "data"
    f = data / "diagnostics" / "launcher_exits.jsonl"
    _seed(f, 5)
    name = "OOLauncherRecords-" + hashlib.sha1(str(f).lower().encode("utf-8")).hexdigest().upper()
    holder = tmp_path / "hold.ps1"
    holder.write_text(f'$m = New-Object System.Threading.Mutex($false, "{name}"); [void]$m.WaitOne(); Set-Content "{tmp_path}/held" 1; Start-Sleep 4; $m.ReleaseMutex()',
                      encoding="utf-8")
    copy = tmp_path / "w.ps1"
    copy.write_text(LAUNCH_PS1.read_text(encoding="utf-8").replace("$RecLockWaitMs = 520", "$RecLockWaitMs = 100"), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
    h = subprocess.Popen([_PWSH, "-NoProfile", "-File", str(holder)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_for(lambda: (tmp_path / "held").exists(), 30), "the holder never took the mutex"
        server = tmp_path / "server"
        _exe(server, "#!/usr/bin/env bash\nexit 3\n")
        marker = tmp_path / "m"
        subprocess.run([_PWSH, "-NoProfile", "-File", str(copy), "-App", str(server), "-Marker", str(marker), "-DataDir", str(data)], env=env,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        pid = int(marker.read_text(encoding="utf-8"))
        assert pid not in {r.get("pid") for r in _rows(f)[0]}, "nothing is written while the mutex is held by someone else"
        h.wait(timeout=30)
        assert _wait_for(lambda: pid in {r.get("pid") for r in _rows(f)[0]}, 60), "the deferred row never landed"
    finally:
        h.kill()
        h.wait()
    time.sleep(1.0)
    assert sum(1 for r in _rows(f)[0] if r.get("pid") == pid) == 1
    assert sorted(x.name for x in f.parent.iterdir()) == ["launcher_exits.jsonl", "launcher_stderr.jsonl"], "the child left no file behind"


def pid_in_rows(f: Path, pid: str) -> bool:
    return int(pid) in {r.get("pid") for r in _rows(f)[0]}


def _all_cmdlines() -> list[str]:
    out = []
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                out.append((d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace"))
            except OSError:
                continue
    return out


@posix_only
@pytest.mark.parametrize("no_flock", [False, True], ids=["flock", "mkdir-lock"])
def test_a_deferred_bash_row_is_never_in_any_command_line(tmp_path, no_flock):
    """R174 / the passphrase rule: a command line is visible to every local user. The row of a launcher that deferred it stays in the memory of the
    detached subshell. The marker is assembled at run time so it is not in the text of the caller's own script either."""
    if not Path("/proc/self/cmdline").exists():
        pytest.skip("no /proc")
    h, env = _helpers(tmp_path, no_flock=no_flock)
    f = tmp_path / "x.jsonl"
    _seed(f, 5)
    marker = "SECRET-ROW-MARKER-31415"
    holder = subprocess.Popen(["bash", "-c", f'. "{h}"; oo_rec_locked "{f}" sleep 8'], env=env, start_new_session=True)
    try:
        time.sleep(0.5)
        subprocess.run(["bash", "-c", f'. "{h}"; OO_REC_LOCK_WAIT_MS=50; m="$(printf %s {marker[::-1]} | rev)"; oo_rec_append "{f}" "{{\\"m\\":\\"$m\\"}}" 40 20'],
                       env=env, check=True, timeout=30)
        time.sleep(0.5)  # the detached subshell is waiting for the lock now
        seen = [c for c in _all_cmdlines() if marker in c and "shell-snapshots" not in c and "pytest" not in c]  # not the shell that runs this very test
        assert seen == [], f"the row is in a command line: {seen[:1]}"
        os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()
        assert _wait_for(lambda: any(r.get("m") == marker for r in _rows(f)[0]), 30), "and it still lands"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()


@_needs_pwsh
def test_a_deferred_powershell_row_is_never_in_the_childs_command_line(tmp_path):
    """The child's command line is ONE fixed script: two rows with different pids, times and folders give the identical decoded script, and it holds none of
    the row's fields or the folder. The row travels through the child's standard input."""
    import base64
    import hashlib

    if not Path("/proc/self/cmdline").exists():
        pytest.skip("no /proc")
    scripts = []
    for n in range(2):
        sub = tmp_path / f"run{n}"
        sub.mkdir()
        data = sub / "data"
        f = data / "diagnostics" / "launcher_exits.jsonl"
        _seed(f, 5)
        name = "OOLauncherRecords-" + hashlib.sha1(str(f).lower().encode("utf-8")).hexdigest().upper()
        holder = sub / "hold.ps1"
        holder.write_text(f'$m = New-Object System.Threading.Mutex($false, "{name}"); [void]$m.WaitOne(); Set-Content "{sub}/held" 1; Start-Sleep 12; $m.ReleaseMutex()',
                          encoding="utf-8")
        copy = sub / "w.ps1"
        copy.write_text(LAUNCH_PS1.read_text(encoding="utf-8").replace("$RecLockWaitMs = 520", "$RecLockWaitMs = 100"), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
        h = subprocess.Popen([_PWSH, "-NoProfile", "-File", str(holder)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            assert _wait_for(lambda sub=sub: (sub / "held").exists(), 30)
            server = sub / "server"
            _exe(server, f"#!/usr/bin/env bash\nsleep 0.{n + 2}\nexit 3\n")
            marker = sub / "m"
            subprocess.run([_PWSH, "-NoProfile", "-File", str(copy), "-App", str(server), "-Marker", str(marker), "-DataDir", str(data)], env=env,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            pid = marker.read_text(encoding="utf-8").strip()
            time.sleep(0.5)
            enc = [c for c in _all_cmdlines() if "-EncodedCommand " in c and "hold.ps1" not in c]
            assert enc, "the deferred child is not running"
            for c in enc:
                script = base64.b64decode(c.split("-EncodedCommand ", 1)[1].split()[0]).decode("utf-16-le")
                assert "oo-launcher" not in script and str(sub) not in script and f'"pid":{pid}' not in script and "exits.jsonl" not in script, "a field of the row or the path is in the command line"
                scripts.append(script)
        finally:
            h.kill()
            h.wait()
        # let the deferred child finish before the next run: the mutex is gone with the holder
        _wait_for(lambda f=f, pid=pid: pid_in_rows(f, pid), 60)
    assert len(set(scripts)) == 1, "the command line is the same fixed script whatever the row is"




@posix_only
@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="the holder's own pid is read from /proc here; macOS has none")
def test_the_mkdir_lock_records_the_pid_of_the_shell_holding_it_without_bashpid(tmp_path):
    """macOS ships bash 3.2, which has no BASHPID: `${BASHPID:-$$}` then recorded the LAUNCHER's pid for a lock held by its deferred child, so a second launcher
    saw the launcher exit and took a lock over that the child still held. The recorded pid is the holder's own, with and without BASHPID."""
    h, env = _helpers(tmp_path, no_flock=True)
    f = tmp_path / "x.jsonl"
    _seed(f, 3)
    show = (f'. "{h}"; _show() {{ read -r mine _ < /proc/self/stat; printf "%s %s\\n" "$mine" "$(cat "{f}.lock.d/pid")"; }}; '
            f'unset BASHPID; ( oo_rec_locked "{f}" _show ) ; ( BASHPID=; unset BASHPID; oo_rec_locked "{f}" _show )')
    out = subprocess.run(["bash", "-c", show], env=env, capture_output=True, text=True, check=True, timeout=30).stdout.split("\n")
    for line in [x for x in out if x]:
        mine, recorded = line.split()
        assert mine == recorded, f"the lock names pid {recorded}, held by {mine}"


@posix_only
def test_a_takeover_does_not_carry_off_a_lock_a_live_launcher_made_between_the_read_and_the_move(tmp_path):
    """The takeover race of the mkdir lock: launcher A reads a dead owner, the lock is released and made again by a LIVE launcher B, and A's mv moves B's lock. The
    interleaving is forced by a `mv` that makes B's lock just before the real one runs. A puts it back, runs nothing under it, and defers its row."""
    h, env = _helpers(tmp_path, no_flock=True)
    f = tmp_path / "x.jsonl"
    _seed(f, 3)
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock = tmp_path / "x.jsonl.lock.d"
    lock.mkdir()
    (lock / "pid").write_text(str(dead.pid), encoding="utf-8")
    live = subprocess.Popen(["sleep", "120"])
    try:
        script = (f'. "{h}"; OO_REC_LOCK_WAIT_MS=50; mv() {{ printf "%s\\n" {live.pid} > "{lock}/pid"; command mv "$@"; }}; '
                  f'oo_rec_append "{f}" \'{{"pid":5}}\' 0 0')
        subprocess.run(["bash", "-c", script], env=env, check=True, timeout=30)
        assert lock.is_dir() and (lock / "pid").read_text(encoding="utf-8").strip() == str(live.pid), "the live launcher's lock was put back"
        assert {"pid": 5} not in _rows(f)[0], "and nothing was written under it"
    finally:
        live.kill()
        live.wait()
    assert _wait_for(lambda: {"pid": 5} in _rows(f)[0], 30), "the deferred row lands once the live holder is gone"


@posix_only
@pytest.mark.parametrize("case", ["empty", "remade"])
def test_a_takeover_puts_back_a_lock_whose_owner_has_not_written_its_pid_yet_and_never_nests_it(tmp_path, case):
    """Opus read: a live launcher that has made the lock directory and not yet written its pid reads as an empty owner; the takeover that moved it used to delete it.
    And a lock made again while the moved one is held must not have the moved one nested inside it."""
    h, env = _helpers(tmp_path, no_flock=True)
    f = tmp_path / f"{case}.jsonl"
    _seed(f, 3)
    lock = tmp_path / f"{case}.jsonl.lock.d"
    dead = subprocess.Popen(["true"])
    dead.wait()
    lock.mkdir()
    (lock / "pid").write_text(str(dead.pid), encoding="utf-8")
    shadow = (f': > "{lock}/pid"' if case == "empty" else f'command mv "{lock}" "{lock}.stash"; mkdir "{lock}"; sleep 100 & printf "%s\\n" $! > "{lock}/pid"')
    # The shadow runs ONCE (mkdir is atomic): the deferred child is forked from this shell and inherits the `mv` function, so a shadow that fired on every
    # call would, in the child, put a new live lock back between the test's removal of the old one and the child's own takeover, and the row would wait for
    # the stand-in's 100 s (CI, 2026-10-26: two `sleep` orphans where the test starts one).
    script = f'. "{h}"; OO_REC_LOCK_WAIT_MS=50; mv() {{ if mkdir "{tmp_path}/{case}.shadow" 2>/dev/null; then {shadow}; fi; command mv "$@"; }}; oo_rec_append "{f}" \'{{"pid":6}}\' 0 0'
    subprocess.run(["bash", "-c", script], env=env, check=True, timeout=30)
    try:
        assert lock.is_dir(), "the lock a launcher made in between is still there"
        assert not list(lock.glob("*.dead.*")), "the moved lock was not nested inside it"
        assert not list(tmp_path.glob(f"{case}.jsonl.lock.d.dead.*")), "and none was left behind"
        assert {"pid": 6} not in _rows(f)[0], "nothing was written under a lock somebody else holds"
    finally:
        pidfile = lock / "pid"
        held = pidfile.read_text(encoding="utf-8").strip() if pidfile.exists() else ""
        if held.isdigit():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(held), signal.SIGKILL)
        subprocess.run(["rm", "-rf", str(lock), str(lock) + ".stash"])
    assert _wait_for(lambda: {"pid": 6} in _rows(f)[0], 30), "the deferred row lands once that lock is gone"
