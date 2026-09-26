"""How the previous session ENDED: the witnesses outside the process (2026-09-26).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two field instances on 4 GB machines died within a minute of running out of memory,
and the kernel log held no line about either death, so the app could not say what
ended them. These pin the three witnesses added for the next one -- the launcher's
exit status, the user-space memory killers' journal lines, a native crash trace -- and
the negative space around them: a stop the user asked for is never recorded as a
crash, a line about another process is never matched, and no witness means "unknown",
never "clean".
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from src import paths
from src.monitoring import exit_evidence as ee
from src.monitoring import forensics, kernel_log, session_hwm
from src.monitoring import session_history as sh

REPO = Path(__file__).resolve().parents[1]

posix_only = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the launcher is a bash script and the signals are POSIX",
)


@pytest.fixture
def dd(monkeypatch, tmp_path):
    d = tmp_path / "data"
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    monkeypatch.delenv("OO_NO_KERNEL_LOG", raising=False)
    return d


def _write_exit(d: Path, **rec) -> None:
    (d / "diagnostics").mkdir(parents=True, exist_ok=True)
    with open(d / "diagnostics" / ee.LAUNCHER_EXITS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema": "oo-launcher-exit-1", **rec}) + "\n")


# --------------------------------------------------------------------------- #
#  The launcher, run for real against fake commands
# --------------------------------------------------------------------------- #


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _launcher_tree(tmp_path: Path, server_body: str) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "oo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "launch.sh", root / "scripts" / "launch.sh")
    (root / "pyproject.toml").write_text("[project]\nname = 'fake'\n", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "activate").write_text("", encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    _exe(fake / "open-omniscience", '#!/usr/bin/env bash\necho $$ > "$OO_TEST_PIDFILE"\n' + server_body)
    # The FIRST curl is the launcher's "is one already running?" probe and must fail;
    # every later one is the health wait, which succeeds so no test waits 20 s.
    _exe(
        fake / "curl",
        '#!/usr/bin/env bash\nf="$OO_TEST_CURLCOUNT"\nn=$(cat "$f" 2>/dev/null || echo 0)\n'
        'echo $((n + 1)) > "$f"\n[ "$n" -ge 1 ]\n',
    )
    _exe(fake / "xdg-open", "#!/usr/bin/env bash\nexit 0\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "XDG_DATA_HOME"))}
    env.update(
        PATH=f"{fake}{os.pathsep}{os.environ['PATH']}",
        HOME=str(tmp_path / "home"),
        OO_TEST_PIDFILE=str(tmp_path / "server.pid"),
        OO_TEST_CURLCOUNT=str(tmp_path / "curl.count"),
    )
    return root, env


def _run_launcher(root: Path, env: dict[str, str], *, tty: bool = False) -> subprocess.CompletedProcess:
    """Run the launcher. ``tty=True`` gives it a terminal for stdin, as a launcher
    window does -- bash's ``read -p`` prints its prompt only then -- with one Enter
    already typed, so a held window is released and the test never hangs."""
    cmd = ["bash", str(root / "scripts" / "launch.sh")]
    if not tty:
        return subprocess.run(
            cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
        )
    import pty

    master, slave = pty.openpty()
    try:
        os.write(master, b"\n")
        return subprocess.run(cmd, env=env, stdin=slave, capture_output=True, text=True, timeout=60)
    finally:
        os.close(slave)
        os.close(master)


def _exits(root: Path) -> list[dict]:
    f = root / "data" / "diagnostics" / ee.LAUNCHER_EXITS
    if not f.exists():
        return []
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


@posix_only
def test_a_sigkilled_server_is_recorded_by_its_parent_and_the_window_says_so(tmp_path):
    """MUTATION TARGET. Nothing inside a SIGKILLed process can record its death; the
    launcher is its parent and the only witness. Drop the record and this fails."""
    root, env = _launcher_tree(tmp_path, "sleep 0.3\nkill -9 $$\n")
    proc = _run_launcher(root, env, tty=True)
    assert proc.returncode == 137, proc.stderr
    pid = int((tmp_path / "server.pid").read_text().strip())
    [rec] = _exits(root)
    assert rec["pid"] == pid
    assert rec["status"] == 137 and rec["signal"] == "SIGKILL"
    assert rec["schema"] == "oo-launcher-exit-1"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rec["at"])
    # the machine boot rides with the pid: a pid alone repeats across reboots
    assert rec["boot_id"] == sh.machine_boot_id()
    assert "without warning (SIGKILL)" in proc.stdout
    assert f"Recorded in {root / 'data' / 'diagnostics' / ee.LAUNCHER_EXITS}" in proc.stdout
    assert "Press Enter to close this window" in proc.stderr, "the window is held open"


@posix_only
def test_a_server_that_exits_with_an_error_is_recorded_without_a_signal(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.3\nexit 3\n")
    proc = _run_launcher(root, env)
    assert proc.returncode == 3
    [rec] = _exits(root)
    assert rec["status"] == 3 and rec["signal"] is None
    assert "stopped unexpectedly (exit status 3)" in proc.stdout


@posix_only
def test_the_apps_own_stop_button_is_recorded_but_never_alarms(tmp_path):
    """MUTATION TARGET. The in-app Stop sends the server SIGTERM, and uvicorn re-raises
    it after the graceful shutdown, so the launcher sees 143 (measured with uvicorn
    0.49). Announcing that as "stopped unexpectedly" and holding the window would call
    every ordinary Stop a crash. It is still recorded: a teardown that did not finish
    is then visible on the next boot."""
    root, env = _launcher_tree(tmp_path, "sleep 0.3\nkill -TERM $$\n")
    proc = _run_launcher(root, env, tty=True)
    assert proc.returncode == 143
    [rec] = _exits(root)
    assert rec["signal"] == "SIGTERM"
    assert ee.describe_exit(rec)["kind"] == "stopped"
    assert "unexpectedly" not in proc.stdout and "Recorded in" not in proc.stdout
    assert "Press Enter" not in proc.stderr, "an ordinary Stop closes the window as before"


@posix_only
def test_a_clean_exit_is_not_a_crash(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.3\nexit 0\n")
    proc = _run_launcher(root, env)
    assert proc.returncode == 0
    assert _exits(root) == []
    assert "stopped" not in proc.stdout.lower()


@posix_only
def test_a_stop_the_user_asked_for_is_never_recorded_as_a_crash(tmp_path):
    """Closing the window HUPs the launcher, which then kills the server itself: the
    server's non-zero status is the launcher's own doing, never a crash."""
    root, env = _launcher_tree(tmp_path, "exec sleep 30\n")
    proc = subprocess.Popen(
        ["bash", str(root / "scripts" / "launch.sh")],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 30
        count = tmp_path / "curl.count"
        # Past the health wait (a second curl), so the launcher is parked in `wait`.
        while time.monotonic() < deadline:
            if count.exists() and int(count.read_text().strip() or 0) >= 2:
                break
            time.sleep(0.05)
        time.sleep(0.3)
        proc.send_signal(signal.SIGHUP)
        proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert _exits(root) == [], "a stop the user asked for must not read as a crash"


def _bash_data_dir(env: dict[str, str], dir_: Path) -> str:
    src = (REPO / "scripts" / "launch.sh").read_text(encoding="utf-8")
    func = re.search(r"^oo_data_dir\(\) \{\n.*?^\}\n", src, re.S | re.M)
    assert func, "launch.sh must define oo_data_dir()"
    script = func.group(0) + f"\nDIR={shlex.quote(str(dir_))}\noo_data_dir\n"
    out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


@posix_only
def test_the_launcher_and_the_app_agree_on_the_data_folder(monkeypatch, tmp_path):
    """The launcher writes where the app will READ: if the two disagreed, every record
    would land in a folder nobody looks at, silently."""
    monkeypatch.setattr(paths, "_ensure", lambda p: p)  # compare paths, create nothing
    base = {k: v for k, v in os.environ.items() if not k.startswith(("OO_DATA_DIR", "XDG_DATA_HOME"))}
    home = tmp_path / "home"

    for value in (str(tmp_path / "explicit"), "~/oo-data"):
        monkeypatch.setenv("OO_DATA_DIR", value)
        monkeypatch.setenv("HOME", str(home))
        env = {**base, "OO_DATA_DIR": value, "HOME": str(home)}
        assert _bash_data_dir(env, REPO) == str(paths.data_dir())

    monkeypatch.delenv("OO_DATA_DIR", raising=False)
    # the source checkout (where launch.sh actually lives)
    assert _bash_data_dir(base, REPO) == str(paths.data_dir())
    # not a checkout: the per-user XDG location
    elsewhere = tmp_path / "not-a-checkout"
    elsewhere.mkdir()
    monkeypatch.setattr(paths, "_REPO_ROOT", elsewhere)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    env = {**base, "XDG_DATA_HOME": str(tmp_path / "xdg")}
    assert _bash_data_dir(env, elsewhere) == str(paths.data_dir())


def test_the_launcher_keeps_a_stop_signal_trap_first():
    """The existing S0.2 guard reads the FIRST trap line; the stop trap must stay it."""
    src = (REPO / "scripts" / "launch.sh").read_text(encoding="utf-8")
    first = next(ln for ln in src.splitlines() if ln.strip().startswith("trap "))
    assert "HUP" in first and "STOP_REQUESTED=1" in first


# --------------------------------------------------------------------------- #
#  Reading the launcher's record
# --------------------------------------------------------------------------- #


def test_the_record_for_the_previous_pid_is_the_one_read(dd):
    _write_exit(dd, pid=111, status=137, signal="SIGKILL", at="2026-09-26T15:53:40Z")
    _write_exit(dd, pid=222, status=134, signal="SIGABRT", at="2026-09-26T16:00:00Z")
    got = ee.launcher_exit(111)
    assert got["signal"] == "SIGKILL" and got["kind"] == "killed"
    assert "low-memory killer" in got["meaning"]
    assert ee.launcher_exit(222)["kind"] == "crashed"
    assert ee.launcher_exit(333) is None, "no record for a pid is no record, never a guess"
    assert ee.launcher_exit(None) is None


def test_an_exit_status_without_a_signal_reads_as_the_app_stopping_itself(dd):
    _write_exit(dd, pid=5, status=1, signal=None)
    got = ee.launcher_exit(5)
    assert got["kind"] == "exited" and "status 1" in got["meaning"]


def test_a_record_from_another_boot_is_never_this_sessions(dd):
    """MUTATION TARGET. An app started the same way at every login gets much the same
    pid after each reboot, so a pid alone would pin last week's SIGKILL on today's
    session. A record without a boot (or a caller without one) still matches."""
    _write_exit(dd, pid=2345, boot_id="aaaa", status=137, signal="SIGKILL")
    assert ee.launcher_exit(2345, "bbbb") is None
    assert ee.launcher_exit(2345, "aaaa")["signal"] == "SIGKILL"
    assert ee.launcher_exit(2345)["signal"] == "SIGKILL"
    _write_exit(dd, pid=2346, status=134, signal="SIGABRT")
    assert ee.launcher_exit(2346, "bbbb")["signal"] == "SIGABRT"


def test_a_damaged_line_is_skipped_not_fatal(dd):
    (dd / "diagnostics").mkdir(parents=True)
    (dd / "diagnostics" / ee.LAUNCHER_EXITS).write_text(
        '{"pid": 7, "status": 137, "signal": "SIGKILL"}\nnot json\n', encoding="utf-8"
    )
    assert ee.launcher_exit(7)["signal"] == "SIGKILL"


# --------------------------------------------------------------------------- #
#  The journal: the right boot, and the user-space killers
# --------------------------------------------------------------------------- #


def test_a_boot_id_is_passed_to_journalctl_without_its_dashes():
    """MEASURED on systemd 255: `journalctl -b <dashed uuid>` fails with "Failed to add
    match ... Invalid argument"; the same id as 32 hex digits is accepted."""
    assert kernel_log.journal_boot_arg("70cacdac-1f11-4243-9a79-210ef1ae75e2") == (
        "70cacdac1f1142439a79210ef1ae75e2"
    )
    assert kernel_log.journal_boot_arg(None) == "0"


def _capture_runs(monkeypatch, mapping=None):
    seen: list[list[str]] = []

    def _run(cmd, **kw):
        seen.append(list(cmd))
        rc, text = (mapping or {}).get("any", (0, "kernel: Linux version 6.18\nkernel: ACPI ok"))
        return subprocess.CompletedProcess(cmd, rc, text, "")

    monkeypatch.setattr(kernel_log.subprocess, "run", _run)
    monkeypatch.setattr(kernel_log.shutil, "which", lambda _n: "/usr/bin/journalctl")
    return seen


def test_the_kernel_read_goes_to_the_boot_the_session_ran_in(monkeypatch):
    seen = _capture_runs(monkeypatch)
    monkeypatch.setattr(sh, "machine_boot_id", lambda: "aaaaaaaa-0000-0000-0000-000000000001")
    same = kernel_log.read_kernel_evidence(9, since="2026-09-26T15:14:49+00:00",
                                           boot="aaaaaaaa-0000-0000-0000-000000000001")
    assert [c[:4] for c in seen] == [["journalctl", "-k", "-b", "0"]], "same boot: read this one only"
    assert same["boot"]["same_as_this_boot"] is True
    seen.clear()
    other = kernel_log.read_kernel_evidence(9, boot="bbbbbbbb-0000-0000-0000-000000000002")
    assert seen[0][:4] == ["journalctl", "-k", "-b", "bbbbbbbb000000000000000000000002"]
    assert len(seen) == 1 and other["boot"]["same_as_this_boot"] is False


def test_a_failed_read_is_never_hidden_behind_another_boots_success(monkeypatch):
    """MUTATION TARGET. With the legacy two reads, a failed read of THIS boot used to
    vanish as soon as the previous boot read fine, and the report said "the kernel log
    was read" about the one log that mattered and had not been."""

    def _run(cmd, **kw):
        if "-1" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "kernel: Linux version 6.18", "")
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(kernel_log.subprocess, "run", _run)
    monkeypatch.setattr(kernel_log.shutil, "which", lambda _n: "/usr/bin/journalctl")
    got = kernel_log.read_kernel_evidence(9, since="2026-09-26T15:14:49+00:00")
    assert got["verdict"] == "no-kernel-evidence"
    assert any("this boot" in r and "timed out" in r for r in got["unread"])
    assert "for previous boot only" in got["reason"]


_OOMD = (
    "2026-09-26T15:53:31+0000 box systemd-oomd[612]: Killed "
    "/user.slice/user-1000.slice/user@1000.service/app.slice/app-term-4242.scope due to "
    "memory used (3.8G) / total (3.9G) and swap used (0.9G) / total (1.0G) being more than 90.00%"
)
_EARLYOOM = (
    "2026-09-26T15:53:31+0000 box earlyoom[500]: sending SIGTERM to process 216352 uid 1000 "
    '"python3": oom_score 900, VmRSS 2800 MiB'
)
_OTHER = "2026-09-26T15:50:00+0000 box earlyoom[500]: sending SIGTERM to process 9999 uid 1000 \"firefox\""
_CORE = "2026-09-26T15:53:31+0000 box systemd-coredump[700]: Process 216352 (python3) of user 1000 dumped core."


def _journal(monkeypatch, text: str, rc: int = 0) -> list[list[str]]:
    seen: list[list[str]] = []

    def _run(cmd):
        seen.append(list(cmd))
        return rc, text

    monkeypatch.setattr(ee, "_run", _run)
    monkeypatch.setattr(ee.shutil, "which", lambda _n: "/usr/bin/journalctl")
    return seen


def test_systemd_oomd_is_matched_by_the_cgroup_it_killed(monkeypatch):
    seen = _journal(monkeypatch, _OTHER + "\n" + _OOMD)
    ours = "/user.slice/user-1000.slice/user@1000.service/app.slice/app-term-4242.scope"
    got = ee.read_userspace_killers(216352, since="x", boot="aaaa-bbbb", cgroup=ours)
    assert got["verdict"] == "userspace-oom-kill"
    assert got["lines"] == [_OOMD], "a line about another process is never ours"
    cmd = seen[0]
    assert cmd[:3] == ["journalctl", "-b", "aaaabbbb"]
    assert all(t in cmd for t in ("systemd-oomd", "earlyoom", "nohang", "systemd-coredump"))
    # a process in a CHILD cgroup of the killed one died with it
    got = ee.read_userspace_killers(1, cgroup=ours + "/sub")
    assert got["verdict"] == "userspace-oom-kill"
    # a sibling cgroup whose name merely starts the same is not ours
    assert ee.read_userspace_killers(1, cgroup=ours + "0")["verdict"] == "no-userspace-evidence"


def test_earlyoom_and_a_core_dump_are_matched_by_pid(monkeypatch):
    _journal(monkeypatch, _OTHER + "\n" + _EARLYOOM)
    assert ee.read_userspace_killers(216352)["verdict"] == "userspace-oom-kill"
    _journal(monkeypatch, _CORE)
    assert ee.read_userspace_killers(216352)["verdict"] == "core-dump"
    _journal(monkeypatch, _OTHER)
    got = ee.read_userspace_killers(216352)
    assert got["verdict"] == "no-userspace-evidence" and got["lines"] == []
    assert "never" not in got["verdict"] and "clean" not in got["verdict"]


def test_a_journal_this_user_cannot_read_is_a_permission_gap(monkeypatch):
    hint = (
        "-- No entries --\nHint: You are currently not seeing messages from other users and "
        "the system.\n      Users in groups 'adm', 'systemd-journal' can see all messages."
    )
    _journal(monkeypatch, hint)
    got = ee.read_userspace_killers(216352)
    assert got["verdict"] == "no-journal" and "permission gap" in got["reason"]


def test_the_journal_read_honours_the_kernel_log_opt_out(monkeypatch):
    seen = _journal(monkeypatch, _EARLYOOM)
    monkeypatch.setenv("OO_NO_KERNEL_LOG", "1")
    assert ee.read_userspace_killers(216352)["verdict"] == "disabled"
    assert seen == [], "opted out means not read at all"


def test_the_root_cgroup_is_no_handle(monkeypatch, tmp_path):
    fake = tmp_path / "cgroup"
    fake.write_text("0::/\n", encoding="ascii")
    real_path = ee.Path

    monkeypatch.setattr(ee, "Path", lambda p: real_path(fake) if p == "/proc/self/cgroup" else real_path(p))
    assert ee.own_cgroup() is None
    fake.write_text("1:name=systemd:/x\n0::/user.slice/app.scope\n", encoding="ascii")
    assert ee.own_cgroup() == "/user.slice/app.scope"


# --------------------------------------------------------------------------- #
#  The native crash trace
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(sys.platform == "win32", reason="SIGABRT semantics are POSIX")
def test_a_native_abort_leaves_every_threads_stack_for_the_next_boot(dd):
    """End to end in a real child process: faulthandler armed by the app writes the
    trace, and the next boot finds it by the dead process's pid."""
    code = textwrap.dedent(
        """
        import faulthandler, os, sys, threading, time
        from src.monitoring.exit_evidence import arm_crash_trace
        assert arm_crash_trace()["armed"]
        threading.Thread(target=time.sleep, args=(30,), name="oo-collect_3", daemon=True).start()
        print(os.getpid(), flush=True)
        faulthandler._sigabrt()
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, env={**os.environ, "OO_DATA_DIR": str(dd)},
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == -signal.SIGABRT, proc.stderr
    pid = int(proc.stdout.split()[0])
    got = ee.previous_trace(pid, sh.machine_boot_id())
    assert got is not None
    assert got["summary"].startswith("Fatal Python error: Aborted")
    body = "\n".join(got["lines"])
    assert "Current thread" in body and "Thread 0x" in body, "every thread, not just the crashing one"
    assert ee.previous_trace(pid + 1) is None
    if sh.machine_boot_id():
        assert ee.previous_trace(pid, "another-boot") is None, "same pid, another boot"


def test_the_trace_section_ends_at_the_next_session_and_a_quiet_session_has_none(dd):
    path = ee.crash_trace_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        "=== open-omniscience session pid=10 started=2026-09-26T15:00:00+00:00 ===\n"
        "Fatal Python error: Segmentation fault\n\nCurrent thread 0x1 (most recent call first):\n"
        '  File "x.py", line 1 in f\n'
        "\n=== open-omniscience session pid=11 started=2026-09-26T15:10:00+00:00 ===\n"
        "\n=== open-omniscience session pid=12 started=2026-09-26T15:20:00+00:00 ===\n",
        encoding="utf-8",
    )
    got = ee.previous_trace(10)
    assert got["summary"] == "Fatal Python error: Segmentation fault"
    assert not any("pid=11" in ln for ln in got["lines"])
    assert ee.previous_trace(11) is None, "a session that did not crash has no trace"
    # a header written before the boot was named still matches, whatever the caller's boot
    assert ee.previous_trace(10, "aaaa")["summary"] == "Fatal Python error: Segmentation fault"


def test_a_trace_from_another_boot_with_the_same_pid_is_not_this_sessions(dd):
    path = ee.crash_trace_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        "=== open-omniscience session pid=2345 boot=aaaa started=2026-09-20T09:00:00+00:00 ===\n"
        "Fatal Python error: Segmentation fault\n"
        "\n=== open-omniscience session pid=2345 boot=bbbb started=2026-09-26T09:00:00+00:00 ===\n",
        encoding="utf-8",
    )
    assert ee.previous_trace(2345, "bbbb") is None, "today's session with that pid did not crash"
    assert ee.previous_trace(2345, "aaaa")["summary"] == "Fatal Python error: Segmentation fault"


def test_an_exception_that_ends_the_server_is_kept_under_its_session(dd):
    path = ee.crash_trace_path()
    path.parent.mkdir(parents=True)
    path.write_text(f"=== open-omniscience session pid={os.getpid()} started=x ===\n", encoding="utf-8")
    try:
        raise MemoryError("the event loop could not allocate")
    except MemoryError as exc:
        ee.note_fatal_exception(exc)
    got = ee.previous_trace(os.getpid())
    assert got["summary"].startswith("Uncaught exception ended the server")
    assert any("MemoryError: the event loop could not allocate" in ln for ln in got["lines"])


def test_the_trace_can_be_turned_off(dd, monkeypatch):
    monkeypatch.setenv("OO_CRASH_TRACE", "0")
    assert ee.arm_crash_trace() == {"armed": False, "reason": "OO_CRASH_TRACE=0"}


def test_the_server_arms_the_trace_and_keeps_an_escaping_exception():
    """Source guard: the entry point that runs the server arms the trace and records
    an exception escaping uvicorn.run before re-raising it."""
    src = (REPO / "src" / "api" / "main.py").read_text(encoding="utf-8")
    serve = src[src.index("def _serve() -> None:"):]
    assert serve.index("arm_crash_trace()") < serve.index("uvicorn.run(")
    assert "note_fatal_exception(exc)" in serve


# --------------------------------------------------------------------------- #
#  The combined account, the report, the ledger
# --------------------------------------------------------------------------- #


def test_how_it_ended_names_only_the_witnesses_that_answered():
    none = ee.how_it_ended(launcher=None, killers={"verdict": "no-userspace-evidence"},
                           kernel={"verdict": "no-kernel-evidence"}, trace=None)
    assert none["known"] is False and "no witness" in none["summary"]
    got = ee.how_it_ended(
        launcher={"signal": "SIGKILL", "status": 137},
        killers={"verdict": "userspace-oom-kill", "lines": [_OOMD]},
        kernel={"verdict": "no-kernel-evidence"},
        trace=None,
    )
    assert got["known"] is True
    assert "systemd-oomd logged killing this process" in got["summary"]
    assert "the launcher saw it end by SIGKILL" in got["summary"]


@pytest.fixture
def unclean_prev(dd, monkeypatch):
    prev = {"state": "running", "pid": 216352, "started_at": "2026-09-26T15:14:49+00:00"}
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", prev)
    monkeypatch.setattr(forensics, "_PREV_LOADED", True)
    monkeypatch.setattr(forensics, "_KERNEL_EVIDENCE", {
        "verdict": "no-kernel-evidence", "lines": [], "reason": "nothing in the kernel log",
    })
    monkeypatch.setattr(forensics, "_JOURNAL_EXIT_EVIDENCE", {
        "userspace_killers": {"verdict": "userspace-oom-kill", "lines": [_EARLYOOM]},
        "running_killers": {"known": True, "active": ["earlyoom"]},
    })
    return prev


def test_the_report_carries_every_witness_and_says_how_it_ended(unclean_prev, dd):
    _write_exit(dd, pid=216352, status=137, signal="SIGKILL", at="2026-09-26T15:53:40Z")
    rep = forensics.previous_session_report()
    ev = rep["exit_evidence"]
    assert ev["launcher"]["signal"] == "SIGKILL"
    assert ev["crash_trace"] is None
    assert ev["running_killers"]["active"] == ["earlyoom"]
    assert rep["how_it_ended"]["known"] is True
    assert "earlyoom logged killing this process" in rep["how_it_ended"]["summary"]
    txt = forensics.render_text({"previous_session": rep})
    assert "- how it ended:" in txt
    assert "launcher: SIGKILL at 2026-09-26T15:53:40Z" in txt
    assert "memory killers running on this machine now: earlyoom" in txt
    assert "crash trace: none for that session" in txt


def test_a_clean_session_carries_no_exit_evidence(dd, monkeypatch):
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", {"state": "clean", "pid": 5})
    monkeypatch.setattr(forensics, "_PREV_LOADED", True)
    rep = forensics.previous_session_report()
    assert "exit_evidence" not in rep and "how_it_ended" not in rep


def test_a_journal_read_still_running_says_so(unclean_prev, monkeypatch):
    monkeypatch.setattr(forensics, "_JOURNAL_EXIT_EVIDENCE", None)
    rep = forensics.previous_session_report()
    assert rep["exit_evidence"]["userspace_killers"]["verdict"] == "not-read"


def test_the_sentinel_records_its_boot_and_cgroup(dd, monkeypatch):
    monkeypatch.setattr(sh, "machine_boot_id", lambda: "70cacdac-1f11-4243-9a79-210ef1ae75e2")
    monkeypatch.setattr(ee, "own_cgroup", lambda: "/user.slice/app.scope")
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    forensics.record_session_start()
    state = json.loads((dd / "session_state.json").read_text(encoding="utf-8"))
    assert state["boot_id"] == "70cacdac-1f11-4243-9a79-210ef1ae75e2"
    assert state["cgroup"] == "/user.slice/app.scope"
    sh._reset_for_tests()


def test_the_summary_line_of_a_pass_is_not_taken_as_the_last_sample(dd):
    """The 2026-09-26 export printed "rss {'first': 587.2, ...} MB, available None MB":
    the pass's closing summary line was read as a tick."""
    dd.mkdir(parents=True, exist_ok=True)
    tick = {"ts": "2026-09-26T16:06:50Z", "rss_mb": 1394.8, "mem_avail_mb": 1800.0, "pass_id": "p"}
    summary = {"ts": "2026-09-26T16:06:51Z", "kind": "summary", "pass_id": "p",
               "rss_mb": {"first": 587.2, "last": 1394.8, "max": 1500.2}}
    (dd / "collect_perf.jsonl").write_text(json.dumps(tick) + "\n" + json.dumps(summary) + "\n", encoding="utf-8")
    got = forensics._last_collect_perf_sample()
    assert got["rss_mb"] == 1394.8 and got["mem_avail_mb"] == 1800.0
    txt = forensics.render_text({"previous_session": {"last_collector_sample": got}})
    assert "{'first'" not in txt and "available None" not in txt
    assert "rss 1394.8 MB, available 1800.0 MB" in txt
    # a tick cut short by the death itself is skipped, never the end of the search
    with open(dd / "collect_perf.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"ts": "2026-09-26T16:06:55Z", "rss_mb": 14')
    assert forensics._last_collect_perf_sample()["rss_mb"] == 1394.8


def test_the_ledger_end_line_carries_the_signal_across_sessions(dd, monkeypatch):
    """The ledger spans many sessions, so a machine that crashes daily shows WHICH
    signal each death was -- and the chronology passes it through."""
    from src.monitoring import chronology as ch

    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    sh._reset_for_tests()
    t0 = 1_790_000_000.0
    monkeypatch.setattr(sh.time, "time", lambda: t0)
    sh.record_boot(None)
    sh.tick_once(now_wall=t0 + 600, now_mono=sh._STARTED_MONO + 600)
    _write_exit(dd, pid=os.getpid(), status=137, signal="SIGKILL", at="2026-09-26T15:53:40Z")
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: t0 + 900)
    sh.record_boot({"state": "running", "pid": os.getpid()})
    end = next(r for r in sh.read_records() if r["kind"] == "end")
    assert end["clean"] is False
    assert end["exit"]["signal"] == "SIGKILL" and end["exit"]["kind"] == "killed"
    events = ch.chronology(anchor="install", now=t0 + 1000)["events"]
    unclean = next(e for e in events if e["kind"] == "end-unclean")
    assert unclean["detail"]["exit"]["signal"] == "SIGKILL"
    sh._reset_for_tests()


# --------------------------------------------------------------------------- #
#  What the memory was made of at its peak
# --------------------------------------------------------------------------- #


@pytest.fixture
def hwm(dd, monkeypatch):
    session_hwm.reset_for_tests()
    yield
    session_hwm.reset_for_tests()


def test_a_new_peak_records_what_the_memory_was_made_of(hwm, monkeypatch):
    readings = iter([
        {"rss_mb": 1000.0, "avail_mb": 2000.0},
        {"rss_mb": 900.0, "avail_mb": 2100.0},
    ])
    monkeypatch.setattr(session_hwm, "_readings", lambda: next(readings))
    monkeypatch.setattr(session_hwm, "_heap_walk_is_safe", lambda r: True)
    session_hwm.observe("collecting")
    peak = session_hwm.current()["at_peak"]
    assert peak["rss_mb"] == 1000.0
    if sys.platform.startswith("linux"):
        assert {"rss_anon_mb", "rss_file_mb", "threads"} <= set(peak)
    assert isinstance(peak["py_alloc_blocks"], int)
    # not a new peak: the composition stays the one taken AT the peak
    session_hwm._LAST_COMPOSITION = 0.0
    session_hwm.observe("collecting")
    assert session_hwm.current()["at_peak"]["rss_mb"] == 1000.0


def test_the_export_says_what_the_peak_was_made_of():
    peaks = {"available": True, "rss_max_mb": 2800.0, "at_peak": {
        "rss_mb": 2800.0, "at": "2026-09-26T15:53:20+00:00", "rss_anon_mb": 2650.0,
        "rss_file_mb": 150.0, "swapped_out_mb": 700.0, "threads": 41, "py_alloc_blocks": 9_000_000,
    }}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "made of, at 2800.0 MB (2026-09-26T15:53:20+00:00): anonymous 2650.0 MB" in txt
    assert "swapped out 700.0 MB" in txt and "threads 41" in txt
    assert "C heap not read" in txt, "an unread heap is named, never shown as zero"


def _parked_in_app_code(ev):
    """A thread parked inside a function whose file is under the app's own src/."""
    ns: dict = {}
    fake = session_hwm._APP_SRC + "/fake/parked.py"
    exec(compile("def parked(ev):\n    ev.wait(30)\n", fake, "exec"), ns)
    t = threading.Thread(target=ns["parked"], args=(ev,), name="oo-fake-worker", daemon=True)
    t.start()
    return t


def test_every_thread_is_named_with_the_app_code_it_is_in():
    """MUTATION TARGET. A faulthandler dump prints thread ids, not names, and the
    innermost frame of a working thread is usually a library: the snapshot must say
    WHICH thread and which of the app's own functions it was running."""
    ev = threading.Event()
    t = _parked_in_app_code(ev)
    try:
        time.sleep(0.05)
        snap = session_hwm.thread_snapshot()
    finally:
        ev.set()
        t.join(5)
    mine = next(e for e in snap if e["name"] == "oo-fake-worker")
    assert mine["stack"][0].startswith("threading.py:") and mine["stack"][0].endswith(" wait")
    assert "src/fake/parked.py:2 parked" in mine["stack"]
    assert mine["tid"] == t.native_id, "the kernel's id, so CPU can be diffed across snapshots"
    assert any(e.get("sampler") for e in snap), "the sampling thread marks itself"


def test_cpu_is_read_for_the_working_threads_only(monkeypatch):
    """Every /proc read releases the GIL, and under the burst being recorded each one
    waits a switch interval: reading all forty-odd threads measured 0.5-0.7 s. The
    waiting threads are marked instead, and only the working ones are read."""
    ev = threading.Event()
    parked = _parked_in_app_code(ev)
    ns: dict = {}
    spin_src = "def spin(ev):\n    while not ev.is_set():\n        sum(range(2000))\n"
    exec(compile(spin_src, session_hwm._APP_SRC + "/fake/spin.py", "exec"), ns)
    busy = threading.Thread(target=ns["spin"], args=(ev,), name="oo-fake-busy", daemon=True)
    busy.start()
    asked: list[int] = []
    real = session_hwm._thread_cpu
    monkeypatch.setattr(session_hwm, "_thread_cpu", lambda tids: asked.extend(tids) or real(tids))
    try:
        time.sleep(0.2)
        snap = session_hwm.thread_snapshot()
    finally:
        ev.set()
        parked.join(5)
        busy.join(5)
    by_name = {e["name"]: e for e in snap}
    assert by_name["oo-fake-worker"].get("waiting") is True
    assert parked.native_id not in asked and "cpu_s" not in by_name["oo-fake-worker"]
    assert busy.native_id in asked and by_name["oo-fake-busy"]["stack"][0].startswith("src/fake/spin.py")
    if sys.platform.startswith("linux"):
        assert by_name["oo-fake-busy"]["cpu_s"] > 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc is Linux's")
def test_a_threads_cpu_is_read_from_the_right_proc_fields():
    t0 = time.thread_time()
    while time.thread_time() - t0 < 0.3:
        sum(range(10000))
    got = session_hwm._thread_cpu([threading.get_native_id()])[threading.get_native_id()]
    assert abs(got - time.thread_time()) < 0.2, (got, time.thread_time())
    assert session_hwm._thread_cpu([]) == {} and session_hwm._thread_cpu([2**30]) == {}


def test_only_the_apps_own_directory_is_app_code():
    """A ``/src/`` elsewhere in a path (a Python built under /usr/local/src) is not the
    app, or every stdlib frame would read as the app's own code."""
    assert session_hwm._short_path("/usr/local/src/Python-3.13/Lib/threading.py") == "threading.py"
    assert session_hwm._short_path(session_hwm._APP_SRC + "/api/main.py") == "src/api/main.py"
    assert session_hwm._short_path(
        "/home/u/.venv/lib/python3.13/site-packages/sqlalchemy/engine/base.py"
    ) == "sqlalchemy/engine/base.py"


_SHORT = {"rss_mb": 2699.0, "avail_mb": 586.4, "total_mb": 3924.7, "swap_used_mb": 1024.0}


def test_memory_running_short_records_what_every_thread_was_doing(hwm, monkeypatch, dd):
    """MUTATION TARGET. The field death was a 45 s burst: the snapshot has to be taken
    below the line and be on disk AT ONCE (the throttle could outlive the process), in
    its own file so the marks' routine rewrite stays small, and it has to reach the
    next boot's report."""
    monkeypatch.setattr(session_hwm, "_readings", lambda: dict(_SHORT))
    monkeypatch.setattr(session_hwm, "_heap_walk_is_safe", lambda r: False)
    session_hwm.capture_previous()
    session_hwm.observe("collecting")
    assert not (dd / "session_pressure.json").exists(), (
        "the collector's monitor feeds the memory guard: it never pays for a snapshot"
    )
    ev = threading.Event()
    t = _parked_in_app_code(ev)
    try:
        time.sleep(0.05)
        session_hwm.observe(may_snapshot_threads=True)
    finally:
        ev.set()
        t.join(5)
    marks = json.loads((dd / "session_hwm.json").read_text(encoding="utf-8"))
    doc = json.loads((dd / "session_pressure.json").read_text(encoding="utf-8"))
    assert "pressure" not in marks and marks["pressure_taken"] == 1
    assert (doc["pid"], doc["started_at"]) == (marks["pid"], marks["started_at"])
    [snap] = doc["snapshots"]
    assert snap["avail_mb"] == 586.4 and snap["line_mb"] == round(3924.7 * 0.15, 1)
    assert snap["rss_mb"] == 2699.0 and "heap_in_use_mb" not in snap["memory"]
    assert any(e["name"] == "oo-fake-worker" for e in snap["threads"])
    # the next boot reads it as the previous session's, and starts clean
    session_hwm.reset_for_tests()
    prev = session_hwm.capture_previous()
    assert prev is not None and prev["pressure"] == doc["snapshots"] and prev["pressure_taken"] == 1
    assert not (dd / "session_pressure.json").exists()
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": dict(
        prev, available=True)}})
    assert "when memory ran short (1 snapshot(s) of every thread, taken below 588.7 MB" in txt
    assert "oo-fake-worker" not in txt, "a thread parked in a wait is counted, not listed"
    assert "more thread(s) waiting or not listed" in txt


def test_a_slide_is_recorded_step_by_step_and_a_plateau_once(hwm):
    """MUTATION TARGET. One snapshot at the crossing, one per new low a step further
    down, none while memory sits on a plateau, and a new episode only once memory has
    come back above the line by the re-arm margin."""
    total = 4000.0
    line = session_hwm._pressure_line_mb(total)  # 600 MB
    step = line * session_hwm._PRESSURE_STEP_SHARE  # 75 MB
    gap = session_hwm._PRESSURE_MIN_INTERVAL_S
    due = session_hwm._pressure_due

    def r(avail):
        return {"avail_mb": avail, "total_mb": total}

    assert not due(r(line + 1), 1000.0), "above the line"
    assert due(r(line - 10), 1000.0), "the crossing"
    assert not due(r(line - 10 - step + 1), 1000.0 + gap), "less than a step lower"
    assert not due(r(line - 10), 1000.0 + 10 * gap), "a plateau, however long"
    assert not due(r(line - 10 - step), 1000.0 + gap / 2), "a step lower, but too soon"
    assert due(r(line - 10 - step), 1000.0 + gap), "a step lower"
    assert not due(r(line + 1), 2000.0) and not due(r(line - 10), 2000.0 + gap), (
        "back above the line but inside the margin is the same episode"
    )
    assert not due(r(line * session_hwm._PRESSURE_REARM_SHARE + 1), 3000.0)
    assert due(r(line - 10), 3000.0 + gap), "a new episode after the re-arm"
    assert not due({"avail_mb": 10.0}, 4000.0), "unknown RAM takes no snapshot"


def test_the_newest_snapshots_are_kept_and_all_are_counted(hwm, monkeypatch, dd):
    avail = [600.0]
    monkeypatch.setattr(session_hwm, "_readings",
                        lambda: {"avail_mb": avail[0], "total_mb": 4000.0, "rss_mb": 3000.0})
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: [])
    monkeypatch.setattr(session_hwm, "_PRESSURE_STEP_SHARE", 0.05)  # a 30 MB step
    session_hwm.capture_previous()
    keep = session_hwm._PRESSURE_KEEP
    for _ in range(keep + 3):
        session_hwm._LAST_PRESSURE = 0.0
        avail[0] -= 40.0
        session_hwm.observe(may_snapshot_threads=True)
    doc = json.loads((dd / "session_pressure.json").read_text(encoding="utf-8"))
    assert doc["taken"] == keep + 3 and len(doc["snapshots"]) == keep
    assert doc["snapshots"][-1]["avail_mb"] == 600.0 - 40.0 * (keep + 3), "the last one is kept"
    assert len(session_hwm.current()["pressure"]) == keep
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": {
        "available": True, "rss_max_mb": 3000.0, "pressure": doc["snapshots"],
        "pressure_taken": doc["taken"]}}})
    assert f"{keep} snapshot(s) of every thread; {keep + 3} taken, the newest {keep} kept" in txt


def test_a_pressure_file_from_another_session_is_never_this_ones(hwm, dd):
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "session_hwm.json").write_text(json.dumps(
        {"pid": 4242, "started_at": "2026-09-26T15:00:00+00:00", "rss_max_mb": 900.0}))
    (dd / "session_pressure.json").write_text(json.dumps(
        {"pid": 4242, "started_at": "2026-09-25T09:00:00+00:00", "taken": 2,
         "snapshots": [{"at": "2026-09-25T09:10:00+00:00", "avail_mb": 100.0}]}))
    prev = session_hwm.capture_previous()
    assert prev is not None and "pressure" not in prev


def test_the_busiest_thread_is_the_one_that_worked_between_snapshots():
    """A thread's lifetime CPU says what it did since boot; the order must follow the
    CPU spent while the memory went, and a missing file must be named."""
    def snap(at, avail, threads):
        return {"at": at, "avail_mb": avail, "line_mb": 588.7, "memory": {}, "threads": threads}

    old = {"name": "oo-old-busy", "tid": 1, "stack": ["src/a.py:1 f"]}
    new = {"name": "oo-burst", "tid": 2, "stack": ["src/b.py:2 g"]}
    snaps = [
        snap("2026-09-26T15:52:40+00:00", 580.0, [dict(old, cpu_s=900.0), dict(new, cpu_s=5.0)]),
        snap("2026-09-26T15:53:00+00:00", 150.0, [dict(old, cpu_s=901.0), dict(new, cpu_s=20.0)]),
    ]
    lines = forensics._render_pressure(snaps, 2)
    second = lines[lines.index(next(x for x in lines if "15:53:00" in x)):]
    assert "oo-burst" in second[1] and "+15.0 s in the 20 s before" in second[1]
    assert "oo-old-busy" in second[2] and "+1.0 s in the 20 s before" in second[2]
    assert forensics._render_pressure([], 3) == [
        "  - when memory ran short: 3 snapshot(s) of every thread were taken, but their "
        "file (session_pressure.json) was not found"
    ]


def test_memory_is_read_between_the_liveness_ticks(monkeypatch):
    """The field burst went from 1 GB available to none in 45 s; a once-a-minute read
    could miss it entirely. The liveness thread reads memory every MEMORY_WATCH_S and
    still ticks the ledger only once per TICK_S."""
    from src.monitoring import session_history as sh

    ticks, reads = [], []
    monkeypatch.setattr(sh, "TICK_S", 0.3)
    monkeypatch.setattr(sh, "MEMORY_WATCH_S", 0.02)
    monkeypatch.setattr(sh, "tick_once", lambda: ticks.append(1))
    monkeypatch.setattr(session_hwm, "observe", lambda *a, **k: reads.append(k))
    sh._STOP.clear()
    t = threading.Thread(target=sh._loop, daemon=True)
    t.start()
    try:
        time.sleep(0.45)
    finally:
        sh._STOP.set()
        t.join(5)
        sh._STOP.clear()
    assert 1 <= len(ticks) <= 2
    assert len(reads) >= 4 * len(ticks), (ticks, reads)
    assert all(k == {"may_snapshot_threads": True} for k in reads), "the one snapshotting thread"


def test_no_snapshot_above_the_line(hwm, monkeypatch, dd):
    monkeypatch.setattr(session_hwm, "_readings",
                        lambda: {"rss_mb": 900.0, "avail_mb": 2000.0, "total_mb": 3924.7})
    monkeypatch.setattr(session_hwm, "_heap_walk_is_safe", lambda r: True)
    session_hwm.observe(may_snapshot_threads=True)
    assert "pressure" not in session_hwm.current()
    assert not (dd / "session_pressure.json").exists()
    # a large machine's line is capped: 1 GB, never 15 % of 64 GB
    assert session_hwm._pressure_line_mb(65536.0) == 1024.0


def test_the_heap_walk_is_skipped_when_memory_is_already_short(hwm, monkeypatch):
    """glibc's heap walk touches free chunks all over the heap; on a machine that is
    swapping it would page them back in at the worst moment."""
    calls = []
    monkeypatch.setattr(session_hwm, "_glibc_heap", lambda: calls.append(1) or {"heap_in_use_mb": 1.0})
    assert session_hwm._heap_walk_is_safe({"avail_mb": 200.0, "total_mb": 4000.0}) is False
    assert session_hwm._heap_walk_is_safe({"avail_mb": 1000.0, "total_mb": 4000.0}) is True
    assert session_hwm._heap_walk_is_safe({"avail_mb": 1000.0}) is False, "unknown RAM is not safe"
    assert session_hwm._heap_walk_is_safe({}) is False, "unknown availability is not safe"
    out = session_hwm.composition(walk_heap=False)
    assert calls == [] and "heap_in_use_mb" not in out


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc only")
def test_glibc_reports_heap_in_use_and_free_but_held():
    got = session_hwm._glibc_heap()
    if got is None:
        pytest.skip("not glibc 2.33+ (musl, or an older glibc)")
    assert got["heap_in_use_mb"] > 0
    assert got["heap_free_held_mb"] >= 0
