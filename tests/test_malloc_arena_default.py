"""R114: the launcher caps glibc's malloc arenas at 2, and the diagnostics say who runs with it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer ruled it on 2026-10-01 (answer ``16c``): ``MALLOC_ARENA_MAX=2`` becomes the
default of every instance started with ``scripts/launch.sh``, and the diagnostics must show
which instances run with it, so the performance impact can be read. The reading taken inside
the 2026-09-30 death found 988.7 MB of 3,437.3 MB of anonymous memory freed but held by
glibc's per-thread arenas; the cap is an upper bound on what could be given back, not a
prediction.

Two things are pinned, each with its negative space. The LAUNCHER sets the default and never
overrides a value somebody chose. The READING says what the process STARTED with: glibc reads
the variable once, so a later change to ``os.environ`` can never have applied; a process that
is not on glibc is not "running with the cap" however the variable reads; a value that is not a
plain number is not claimed as applied.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Base
from src.monitoring import forensics, session_hwm
from src.monitoring import soak_window as sw

REPO = Path(__file__).resolve().parents[1]

posix_only = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the launcher is a bash script",
)
linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="the starting environment is read from /proc"
)


# --------------------------------------------------------------------------- #
#  The launcher, run for real against a fake server
# --------------------------------------------------------------------------- #


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _launch(tmp_path: Path, *, env_extra: dict[str, str] | None = None, oo_env: str | None = None) -> str:
    """Run the real ``scripts/launch.sh`` in a throwaway tree whose server records the
    ``MALLOC_ARENA_MAX`` it was started with ("UNSET" when it had none)."""
    root = tmp_path / "oo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "launch.sh", root / "scripts" / "launch.sh")
    (root / "pyproject.toml").write_text("[project]\nname = 'fake'\n", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "activate").write_text("", encoding="utf-8")
    if oo_env is not None:
        (root / "oo.env").write_text(oo_env, encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    seen = tmp_path / "arena.seen"
    _exe(
        fake / "open-omniscience",
        '#!/usr/bin/env bash\nprintf "%s" "${MALLOC_ARENA_MAX-UNSET}" > "$OO_TEST_ARENA_SEEN"\n',
    )
    # The first curl is the launcher's "is one already running?" probe and must fail; the
    # health wait after it succeeds, so the test does not wait 20 s.
    _exe(
        fake / "curl",
        '#!/usr/bin/env bash\nf="$OO_TEST_CURLCOUNT"\nn=$(cat "$f" 2>/dev/null || echo 0)\n'
        'echo $((n + 1)) > "$f"\n[ "$n" -ge 1 ]\n',
    )
    _exe(fake / "xdg-open", "#!/usr/bin/env bash\nexit 0\n")
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("OO_", "XDG_DATA_HOME")) and k != "MALLOC_ARENA_MAX"
    }
    env.update(
        PATH=f"{fake}{os.pathsep}{os.environ['PATH']}",
        HOME=str(tmp_path / "home"),
        OO_TEST_ARENA_SEEN=str(seen),
        OO_TEST_CURLCOUNT=str(tmp_path / "curl.count"),
    )
    env.update(env_extra or {})
    proc = subprocess.run(
        ["bash", str(root / "scripts" / "launch.sh")],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return seen.read_text(encoding="utf-8")


@posix_only
def test_the_launcher_starts_the_server_with_the_arena_cap_when_nobody_chose_one(tmp_path):
    """MUTATION TARGET: delete the export from ``scripts/launch.sh`` and the server starts
    with glibc's default (up to 8 arenas per core) -- the instances the ruling is about."""
    assert _launch(tmp_path) == "2"


@posix_only
def test_a_value_the_operator_already_chose_is_kept(tmp_path):
    """MUTATION TARGET: an unconditional ``export MALLOC_ARENA_MAX=2`` would overwrite an
    operator's own tuning. R114 is a default, never an override."""
    assert _launch(tmp_path, env_extra={"MALLOC_ARENA_MAX": "8"}) == "8"


@posix_only
def test_a_value_recorded_in_the_install_file_is_kept(tmp_path):
    """``oo.env`` is the install's own recorded environment, sourced on every launch. The
    default comes after it, so what it holds is never replaced."""
    assert _launch(tmp_path / "a", oo_env="export MALLOC_ARENA_MAX='4'\n") == "4"
    # and an install file that says nothing about it leaves the default alone
    assert _launch(tmp_path / "b", oo_env="export OO_PORT='8123'\n") == "2"


# --------------------------------------------------------------------------- #
#  The reading: what the process STARTED with
# --------------------------------------------------------------------------- #


def _child_reading(env_extra: dict[str, str], code: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "MALLOC_ARENA_MAX"}
    env.update(env_extra)
    env["PYTHONPATH"] = str(REPO)
    got = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


_READ = "import json; from src.monitoring import session_hwm as h; print(json.dumps(h.allocator_setting()))"
_READ_AFTER_CHANGE = (
    "import json, os; os.environ['MALLOC_ARENA_MAX'] = '99'; "
    "from src.monitoring import session_hwm as h; print(json.dumps(h.allocator_setting()))"
)


@linux_only
def test_a_process_started_with_the_cap_reads_as_running_with_it():
    got = _child_reading({"MALLOC_ARENA_MAX": "2"}, _READ)
    assert got["arena_cap"] == 2
    assert got["source"] == "the environment the process started with"
    if got["allocator"].startswith("glibc"):
        assert got["effective"] is True
        assert got["note"] == "malloc arenas capped at 2 by MALLOC_ARENA_MAX"
    else:  # musl: the variable is there and does nothing
        assert got["effective"] is False and "no effect" in got["note"]


@linux_only
def test_a_process_started_without_it_reads_as_not_capped_never_as_zero():
    got = _child_reading({}, _READ)
    assert got["arena_cap"] is None, "not set is None, never 0"
    assert got["effective"] is False
    if got["allocator"].startswith("glibc"):
        assert "was not set" in got["note"] and "8 malloc arenas per core" in got["note"]


@linux_only
def test_a_later_change_to_the_python_environment_is_not_read_as_what_the_process_runs_with():
    """MUTATION TARGET: glibc read the variable before the first allocation. A process that
    sets ``os.environ`` afterwards (the app does not; a plugin or a test could) changed
    nothing the allocator will ever see, so the reading is the starting environment's."""
    unset = _child_reading({}, _READ_AFTER_CHANGE)
    assert unset["arena_cap"] is None, "set after the start: glibc never saw it"
    capped = _child_reading({"MALLOC_ARENA_MAX": "2"}, _READ_AFTER_CHANGE)
    assert capped["arena_cap"] == 2, "changed after the start: the start is what applied"


def _starting_block(monkeypatch, block: bytes | Exception) -> None:
    """Make ``/proc/self/environ`` read as ``block`` (or fail), and nothing else."""
    real = Path.read_bytes

    def fake(self: Path) -> bytes:
        if str(self) != "/proc/self/environ":
            return real(self)
        if isinstance(block, Exception):
            raise block
        return block

    monkeypatch.setattr(Path, "read_bytes", fake)


def test_a_variable_set_twice_reads_as_its_last_value_as_glibc_and_os_environ_do(monkeypatch):
    _starting_block(monkeypatch, b"A=1\0MALLOC_ARENA_MAX=8\0B=2\0MALLOC_ARENA_MAX=2\0")
    assert session_hwm._starting_value("MALLOC_ARENA_MAX") == (
        "2", "the environment the process started with",
    )
    # a name that is only a prefix of another variable's is not matched
    _starting_block(monkeypatch, b"MALLOC_ARENA_MAX_EXTRA=5\0")
    assert session_hwm._starting_value("MALLOC_ARENA_MAX")[0] is None


def test_where_the_starting_environment_cannot_be_read_os_environ_stands_in_and_says_so(monkeypatch):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    for unreadable in (OSError("no procfs"), b""):
        _starting_block(monkeypatch, unreadable)
        value, source = session_hwm._starting_value("MALLOC_ARENA_MAX")
        assert value == "2"
        assert source.startswith("os.environ") and "could not be read" in source
    monkeypatch.delenv("MALLOC_ARENA_MAX")
    assert session_hwm._starting_value("MALLOC_ARENA_MAX")[0] is None


def test_a_process_that_is_not_on_glibc_is_not_running_with_the_cap(monkeypatch):
    """MUTATION TARGET. ``launch.sh`` exports the variable on macOS too, where the allocator
    ignores it: reading that as "runs with the cap" would put every Mac in the group the
    performance comparison is about."""
    monkeypatch.setattr(session_hwm, "_starting_value", lambda name: ("2", "the environment the process started with"))
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: None)
    got = session_hwm.allocator_setting()
    assert got["effective"] is False
    assert got["allocator"] == f"not glibc ({sys.platform})"
    assert got["arena_cap"] == 2, "what the environment says is still recorded"
    assert "no effect" in got["note"] and "'2'" in got["note"]


def test_a_value_that_is_not_a_plain_number_is_not_claimed_as_applied(monkeypatch):
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    for raw in ("abc", "0", "-2", "2x", "", "1.5"):
        monkeypatch.setattr(session_hwm, "_starting_value", lambda name, raw=raw: (raw, "src"))
        got = session_hwm.allocator_setting()
        assert got["effective"] is None, raw
        assert got["arena_cap"] is None, raw
        assert repr(raw) in got["note"] and "not known" in got["note"], raw
    monkeypatch.setattr(session_hwm, "_starting_value", lambda name: (" 4 ", "src"))
    assert session_hwm.allocator_setting()["arena_cap"] == 4, "surrounding spaces are not a different number"


def test_the_glibc_version_is_asked_of_the_c_library_and_anything_else_is_not_glibc(monkeypatch):
    monkeypatch.setattr(os, "confstr", lambda name: "glibc 2.39", raising=False)
    assert session_hwm._glibc_version() == "glibc 2.39"
    for failing in (ValueError("unrecognized configuration name"), OSError("x")):
        def boom(name, failing=failing):
            raise failing

        monkeypatch.setattr(os, "confstr", boom, raising=False)
        assert session_hwm._glibc_version() is None
    monkeypatch.setattr(os, "confstr", lambda name: "NPTL 2.5", raising=False)
    assert session_hwm._glibc_version() is None, "only glibc's own answer counts"
    monkeypatch.setattr(os, "confstr", lambda name: None, raising=False)
    assert session_hwm._glibc_version() is None


def test_a_reading_that_breaks_degrades_to_unmeasured_and_never_raises(monkeypatch):
    def boom(name):
        raise RuntimeError("procfs on fire")

    monkeypatch.setattr(session_hwm, "_starting_value", boom)
    got = session_hwm.allocator_setting()
    assert got["effective"] is None and got["arena_cap"] is None
    assert "RuntimeError" in got["note"] and "unmeasured" in got["note"]


# --------------------------------------------------------------------------- #
#  The session's record, the crash report, the soak window
# --------------------------------------------------------------------------- #

_CAPPED = {
    "allocator": "glibc 2.39", "arena_cap": 2, "effective": True,
    "source": "the environment the process started with",
    "note": "malloc arenas capped at 2 by MALLOC_ARENA_MAX",
}
_UNCAPPED = {
    "allocator": "glibc 2.39", "arena_cap": None, "effective": False,
    "source": "the environment the process started with",
    "note": "MALLOC_ARENA_MAX was not set: up to 8 malloc arenas per core, glibc's default on a 64-bit machine",
}


@pytest.fixture
def hwm(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    session_hwm.reset_for_tests()
    yield
    session_hwm.reset_for_tests()


def test_a_session_record_carries_the_setting_it_started_with_into_the_next_boots_report(hwm, monkeypatch):
    """MUTATION TARGET. The CRASHED session's own record says whether it ran with the cap:
    the next boot reads it as the previous session's, so a death is read against the setting
    that session ran with, not the one the survivor runs with."""
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_UNCAPPED))
    session_hwm.capture_previous()
    assert session_hwm.current()["allocator"] == _UNCAPPED
    # ... the process dies and the app is launched again, now with the cap: a new process
    # starts with none of this module's state, only the sidecar file the old one left
    session_hwm.reset_for_tests()
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_CAPPED))
    prev = session_hwm.capture_previous()
    assert prev is not None and prev["allocator"] == _UNCAPPED, "the previous session's, not ours"
    assert session_hwm.current()["allocator"] == _CAPPED
    peaks = forensics._previous_peaks()
    assert peaks is not None and peaks["allocator"] == _UNCAPPED
    assert "allocator" in peaks["method"] and "R114" in peaks["method"]


def test_a_session_that_never_called_capture_previous_still_records_its_setting(hwm, monkeypatch):
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_CAPPED))
    monkeypatch.setattr(session_hwm, "_readings", lambda: {"rss_mb": 500.0, "avail_mb": 4000.0})
    session_hwm.observe("testing")
    assert session_hwm.current()["allocator"] == _CAPPED


def test_the_crash_report_names_the_allocator_beside_the_heap_it_explains():
    peaks = {
        "available": True, "rss_max_mb": 3800.0, "allocator": _CAPPED,
        "at_peak": {
            "rss_mb": 3800.0, "at": "2026-09-30T21:08:38+00:00", "rss_anon_mb": 3437.3,
            "heap_in_use_mb": 353.1, "heap_free_held_mb": 988.7, "threads": 29,
        },
    }
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "C allocator (glibc 2.39): malloc arenas capped at 2 by MALLOC_ARENA_MAX" in txt
    assert txt.index("C allocator (glibc 2.39)") < txt.index("made of, at 3800.0 MB"), (
        "the setting is read before the heap it qualifies"
    )
    peaks["allocator"] = _UNCAPPED
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "MALLOC_ARENA_MAX was not set" in txt


def test_a_record_written_before_the_setting_was_kept_renders_without_it():
    peaks = {"available": True, "rss_max_mb": 2800.0, "at_peak": {"rss_mb": 2800.0, "at": "t", "threads": 3}}
    txt = forensics.render_text({"previous_session": {"previous_session_peaks": peaks}})
    assert "made of, at 2800.0 MB" in txt
    assert "C allocator" not in txt, "absent is absent: nothing is invented for an older record"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _soak(monkeypatch, session, *, seconds, **guard):
    from src.scheduler import memguard

    class _Fake(memguard.MemoryGuard):
        def state(self) -> dict:
            return {**super().state(), **guard}

    monkeypatch.setattr(memguard, "memory_guard", _Fake())
    monkeypatch.setattr(
        forensics, "session_uptime",
        lambda: {"measured": True, "started_at": "2026-10-01T00:00:00+00:00", "seconds": seconds},
    )
    return sw.soak_window(session)["memory_guard"]


def test_the_soak_window_says_whether_this_process_runs_with_the_cap_in_every_state(monkeypatch, session):
    """MUTATION TARGET: the memory-guard block returns early in three states (blind, window
    unknown or under the rate floor). The setting is a property of the process, so it rides
    all of them, and it never decides ``measured``."""
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_CAPPED))
    seeing = _soak(monkeypatch, session, seconds=80 * 3600.0, enabled=True, engagements=0,
                   total_engaged_s=0.0, readings_available=True)
    assert seeing["measured"] is True and seeing["allocator"] == _CAPPED
    blind = _soak(monkeypatch, session, seconds=80 * 3600.0, enabled=True, engagements=0,
                  readings_available=False)
    assert blind["measured"] is False and blind["allocator"] == _CAPPED
    young = _soak(monkeypatch, session, seconds=10.0, engagements=1, total_engaged_s=2.0,
                  readings_available=True)
    assert young["measured"] is False and young["allocator"] == _CAPPED
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_UNCAPPED))
    assert _soak(monkeypatch, session, seconds=80 * 3600.0, enabled=True, engagements=2,
                 total_engaged_s=60.0, readings_available=True)["allocator"] == _UNCAPPED
