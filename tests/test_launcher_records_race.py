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

#: The longest append-plus-trim hold measured with 8 launchers at once on 17 Oct (bash 27.3 ms over 320 calls; PowerShell 7, cold, 144.9 ms over 96).
#: WHAT THE WAIT PROTECTS: the time a launcher is willing to wait to trim. A wait below the longest hold would time out on every contended trim.
MEASURED_BASH_HOLD_MS = 27.3
MEASURED_PS_HOLD_MS = 144.9
MSG = "Fatal Python error: Aborted"


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _server_body(mode: str) -> str:
    if mode == "exit3":
        return "exit 3\n"
    if mode == "wait":
        return 'trap \'exit 0\' TERM HUP\necho up > "$OO_TEST_PIDFILE.up"\nwhile :; do sleep 0.1; done\n'
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

    def __init__(self, tmp: Path, *, no_flock: bool = False):
        self.tmp = tmp
        self.data = tmp / "data"
        self.root = tmp / "oo"
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy2(LAUNCH_SH, self.root / "scripts" / "launch.sh")
        (self.root / "pyproject.toml").write_text("[project]\nname='fake'\n", encoding="utf-8")
        (self.root / ".venv" / "bin").mkdir(parents=True)
        (self.root / ".venv" / "bin" / "activate").write_text("", encoding="utf-8")
        self.base_path = os.environ["PATH"]
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


@posix_only
def test_a_lock_held_by_a_live_owner_costs_the_trim_and_not_the_row(tmp_path):
    h, env = _helpers(tmp_path, no_flock=True)
    f = tmp_path / "x.jsonl"
    _seed(f, 60)
    (tmp_path / "x.jsonl.lock.d").mkdir()
    holder = subprocess.Popen(["sleep", "30"])
    try:
        (tmp_path / "x.jsonl.lock.d" / "pid").write_text(str(holder.pid), encoding="utf-8")
        t = time.monotonic()
        subprocess.run(["bash", "-c", f'. "{h}"; oo_rec_append "{f}" \'{{"pid":1}}\' 40 20'], env=env, check=True, timeout=30)
        took = time.monotonic() - t
    finally:
        holder.kill()
        holder.wait()
    rows = _rows(f)[0]
    assert rows[-1] == {"pid": 1} and len(rows) == 61, "the row is appended and the trim is skipped"
    assert took < 2.0, f"the wait is the measured hold, not a guess ({took:.2f} s)"


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
