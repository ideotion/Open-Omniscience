"""R114: the launcher caps glibc's malloc arenas at 2, and the diagnostics say who runs with it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer ruled it on 2026-10-01 (answer ``16c``): ``MALLOC_ARENA_MAX=2`` becomes the
default of every instance started with ``scripts/launch.sh``, and the diagnostics must show
which instances run with it, so the performance impact can be read. The reading taken inside
the 2026-09-30 death found 988.7 MB of 3,437.3 MB of anonymous memory (28.8%) freed but held by
glibc's heap; the cap is an upper bound on what could be given back, not a prediction.

Two things are pinned, each with its negative space. The LAUNCHER sets the default and never
overrides a value somebody chose. The READING says what the process STARTED with, and says it
the way the allocator reads it: glibc reads the variable once, so a later change to
``os.environ`` can never have applied; a variable set twice counts as its FIRST value, which
is the one glibc applies (checked against the real allocator below); a value glibc would ignore
or read differently ("4 ", "08", "010") is not claimed as applied; a process that is not on
glibc, or that preloads another malloc, is not "running with the cap" however the variable
reads; and ``GLIBC_TUNABLES`` naming the arena limit, which outranks the variable, is not
guessed at.
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
    # a plain assignment (no export) is the install's own choice too
    assert _launch(tmp_path / "c", oo_env="MALLOC_ARENA_MAX=3\n") == "3"


@posix_only
def test_a_variable_the_install_file_unsets_or_empties_still_gets_the_default(tmp_path):
    """MUTATION TARGETS. The default is applied AFTER ``oo.env`` is read, so an install file
    that unsets the variable, or leaves it empty, has chosen no number and gets the default;
    exported BEFORE the file it would reach the server unset, or empty. And an EMPTY value
    from the caller is no choice either (``:-``, not ``-``): glibc ignores an empty value, so
    keeping it would leave the arenas uncapped while the launcher reads as having capped them."""
    assert _launch(tmp_path / "a", oo_env="unset MALLOC_ARENA_MAX\n") == "2"
    assert _launch(tmp_path / "b", oo_env="export MALLOC_ARENA_MAX=\n") == "2"
    assert _launch(tmp_path / "c", env_extra={"MALLOC_ARENA_MAX": ""}) == "2"


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

# 16 threads that each allocate, kept alive while glibc reports its arenas (``malloc_info``).
# A thread gets an arena of its own at its first allocation until the limit is reached. The
# child prints what glibc did (``arenas``) beside what the app's own reading made of the
# environment it was started with, so the two are compared on one process.
_COUNT_ARENAS = """
import ctypes, json, os, re, tempfile, threading
libc = ctypes.CDLL(None)
libc.fopen.restype = ctypes.c_void_p
libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
libc.fclose.argtypes = [ctypes.c_void_p]
libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
started, hold = threading.Barrier(17, timeout=30), threading.Event()
def work():
    blocks = [bytearray(100_000) for _ in range(20)]
    started.wait()
    hold.wait(60)
    del blocks
threads = [threading.Thread(target=work) for _ in range(16)]
for t in threads:
    t.start()
started.wait()
fd, path = tempfile.mkstemp()
os.close(fd)
fp = libc.fopen(path.encode(), b"w")
libc.malloc_info(0, fp)
libc.fclose(fp)
with open(path, encoding="utf-8") as fh:
    arenas = len(re.findall(r"<heap nr=", fh.read()))
os.unlink(path)
hold.set()
for t in threads:
    t.join()
from src.monitoring import session_hwm
print(json.dumps({"arenas": arenas, "reading": session_hwm.allocator_setting()}))
"""

# Starts ``_COUNT_ARENAS`` through ``execve`` with an environment block that names
# MALLOC_ARENA_MAX twice, first then last: no ``dict``-based API (subprocess, os.execve) can
# build such a block, and it is exactly what the allocator's lookup rule is about.
_EXEC_WITH_TWO_VALUES = """
import ctypes, os, sys
first, last, code = sys.argv[1:4]
rest = [f"{k}={v}".encode() for k, v in os.environ.items() if k != "MALLOC_ARENA_MAX"]
entries = [f"MALLOC_ARENA_MAX={first}".encode(), f"MALLOC_ARENA_MAX={last}".encode(), *rest]
envp = (ctypes.c_char_p * (len(entries) + 1))(*entries, None)
argv = (ctypes.c_char_p * 4)(sys.executable.encode(), b"-c", code.encode(), None)
libc = ctypes.CDLL(None, use_errno=True)
libc.execve(sys.executable.encode(), argv, envp)
sys.exit("execve failed, errno %d" % ctypes.get_errno())
"""


def _count_arenas(env_extra: dict[str, str] | None = None, *, twice: tuple[str, str] | None = None) -> dict:
    """What glibc did in a child started with ``env_extra``, or with ``MALLOC_ARENA_MAX`` named
    twice (``twice`` = first value, last value), and what the app's reading said there."""
    env = {k: v for k, v in os.environ.items() if k != "MALLOC_ARENA_MAX"}
    env.update(env_extra or {})
    env["PYTHONPATH"] = str(REPO)
    cmd = [sys.executable, "-c", _COUNT_ARENAS]
    if twice is not None:
        cmd = [sys.executable, "-c", _EXEC_WITH_TWO_VALUES, twice[0], twice[1], _COUNT_ARENAS]
    got = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.strip().splitlines()[-1])


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


def _arena_baseline() -> int:
    """The arenas 16 allocating threads leave on glibc WITHOUT the variable; skips where there
    is nothing for the cap to bound (not glibc, or a runtime that never creates per-thread
    arenas, a preloaded jemalloc among them)."""
    if session_hwm._glibc_version() is None:
        pytest.skip("not glibc: MALLOC_ARENA_MAX is a glibc setting")
    uncapped = _count_arenas()["arenas"]
    if uncapped <= 2:
        pytest.skip(f"this environment gave 16 threads {uncapped} arenas even without the cap")
    return uncapped


@linux_only
def test_the_cap_really_bounds_the_allocators_arenas_on_this_machine():
    """What ``effective: true`` stands on. The reading says a process runs with the cap
    when glibc was started with it; this measures that glibc then keeps to it for the
    allocations a Python process makes (``malloc_info`` lists the arenas): on the review
    machine (glibc 2.39, 4 cores) 16 allocating threads left 17 arenas without the variable
    and 2 with it. The baseline comes first: where nothing makes per-thread arenas (a sandbox,
    a preloaded malloc replacement) there is nothing to bound and the test skips."""
    uncapped = _arena_baseline()
    capped = _count_arenas({"MALLOC_ARENA_MAX": "2"})
    assert capped["arenas"] <= 2, f"started with the cap, glibc still reports {capped['arenas']} arenas"
    assert uncapped > capped["arenas"]
    assert capped["reading"]["effective"] is True and capped["reading"]["arena_cap"] == 2, (
        "the app's own reading, in the process that was capped, says so"
    )


@linux_only
def test_a_variable_set_twice_counts_as_its_first_value_because_that_is_the_one_glibc_applies():
    """MUTATION TARGET (taking the LAST entry). Measured, glibc 2.39: a block naming
    ``MALLOC_ARENA_MAX`` as 3 and then as 1 gives 3 arenas, and ``os.environ`` reads 3 too. A
    reading that took the later one would say "capped at 1" for an allocator that kept three,
    and the reverse order would say "capped at 8" for one that kept one. Both ends are checked
    against the real allocator, which is what stops a later glibc from making this a guess."""
    _arena_baseline()
    first_wins = _count_arenas(twice=("3", "1"))
    assert first_wins["reading"]["arena_cap"] == 3
    assert first_wins["arenas"] == 3, "glibc applied the first value, as the reading says"
    last_is_bigger = _count_arenas(twice=("1", "3"))
    assert last_is_bigger["reading"]["arena_cap"] == 1
    assert last_is_bigger["arenas"] == 1, "glibc applied the first value here too"


def _starting_block(monkeypatch, block: bytes | Exception) -> None:
    """Make ``/proc/self/environ`` read as ``block`` (or fail), and nothing else."""
    real = Path.read_bytes

    def fake(self: Path) -> bytes:
        if self.as_posix() != "/proc/self/environ":  # str(self) is backslashed on Windows
            return real(self)
        if isinstance(block, Exception):
            raise block
        return block

    monkeypatch.setattr(Path, "read_bytes", fake)


def _started_with(monkeypatch, **variables: str | None) -> None:
    """Make the process read as started with exactly these variables (any other was not set)."""
    values: dict[str, str | None] = {"MALLOC_ARENA_MAX": None, "GLIBC_TUNABLES": None, "LD_PRELOAD": None}
    values.update(variables)
    monkeypatch.setattr(
        session_hwm, "_starting_values",
        lambda *names: ({name: values.get(name) for name in names}, "the environment the process started with"),
    )


def test_a_variable_set_twice_reads_as_its_first_value_as_glibc_and_os_environ_do(monkeypatch):
    """The unit half of the real-allocator test above: the first entry wins, an empty first
    entry is still the first, and a name that is only a prefix of another variable's, or an
    entry that is not an assignment, is not matched."""
    _starting_block(monkeypatch, b"A=1\0MALLOC_ARENA_MAX=8\0B=2\0MALLOC_ARENA_MAX=2\0")
    assert session_hwm._starting_values("MALLOC_ARENA_MAX", "LD_PRELOAD") == (
        {"MALLOC_ARENA_MAX": "8", "LD_PRELOAD": None}, "the environment the process started with",
    )
    _starting_block(monkeypatch, b"MALLOC_ARENA_MAX=\0MALLOC_ARENA_MAX=2\0")
    assert session_hwm._starting_values("MALLOC_ARENA_MAX")[0] == {"MALLOC_ARENA_MAX": ""}
    _starting_block(monkeypatch, b"MALLOC_ARENA_MAX_EXTRA=5\0MALLOC_ARENA_MAX\0X_MALLOC_ARENA_MAX=3\0")
    assert session_hwm._starting_values("MALLOC_ARENA_MAX")[0] == {"MALLOC_ARENA_MAX": None}
    _starting_block(monkeypatch, b"GLIBC_TUNABLES=glibc.malloc.arena_max=8\0LD_PRELOAD=libjemalloc.so.2\0")
    got, _source = session_hwm._starting_values("MALLOC_ARENA_MAX", "GLIBC_TUNABLES", "LD_PRELOAD")
    assert got == {
        "MALLOC_ARENA_MAX": None, "GLIBC_TUNABLES": "glibc.malloc.arena_max=8",
        "LD_PRELOAD": "libjemalloc.so.2",
    }, "one read of the block answers for every name"


def test_where_the_starting_environment_cannot_be_read_os_environ_stands_in_and_says_so(monkeypatch):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    _starting_block(monkeypatch, OSError("no procfs"))
    values, source = session_hwm._starting_values("MALLOC_ARENA_MAX", "LD_PRELOAD")
    assert values == {"MALLOC_ARENA_MAX": "2", "LD_PRELOAD": None}
    assert source.startswith("os.environ") and "could not be read" in source
    monkeypatch.delenv("MALLOC_ARENA_MAX")
    assert session_hwm._starting_values("MALLOC_ARENA_MAX")[0] == {"MALLOC_ARENA_MAX": None}


def test_an_empty_starting_environment_is_an_env_i_start_and_not_an_unreadable_one(monkeypatch):
    """MUTATION TARGET. ``env -i`` leaves nothing to read, and nothing was set: glibc saw no
    variable. A later ``os.environ`` assignment (a plugin, a test) therefore never applied, and
    must not make the process read as capped."""
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    _starting_block(monkeypatch, b"")
    values, source = session_hwm._starting_values("MALLOC_ARENA_MAX")
    assert values == {"MALLOC_ARENA_MAX": None}
    assert source == "the environment the process started with"
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    got = session_hwm.allocator_setting()
    assert got["effective"] is False and got["arena_cap"] is None


def test_a_process_that_is_not_on_glibc_is_not_running_with_the_cap(monkeypatch):
    """MUTATION TARGET. ``launch.sh`` exports the variable on macOS too, where the allocator
    ignores it: reading that as "runs with the cap" would put every Mac in the group the
    performance comparison is about. ``arena_cap`` names the cap the process RUNS with, so it
    is None there; what the environment says is in the note."""
    _started_with(monkeypatch, MALLOC_ARENA_MAX="2")
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: None)
    got = session_hwm.allocator_setting()
    assert got["effective"] is False
    assert got["allocator"] == f"not glibc ({sys.platform})"
    assert got["arena_cap"] is None, "no cap exists to name"
    assert "no effect" in got["note"] and "'2'" in got["note"]


def test_a_value_glibc_would_ignore_or_read_differently_is_not_claimed_as_applied(monkeypatch):
    """MUTATION TARGETS (``strip()``, ``isdigit``, the ASCII test, the lower bound). Measured,
    glibc 2.39: blanks and tabs may LEAD a number (``" 4"`` and ``"\t2"`` apply), anything
    after the digits makes glibc ignore the whole value (``"4 "``, ``" 4 "`` and ``"2x"``: the
    default 17 arenas), a leading 0 is octal (``"010"`` is 8, ``"08"`` is ignored), ``0x`` is
    hex, and a number that overflows is ignored. None of those is claimed: the reading says it
    does not know. Non-ASCII digits are ``isdigit`` for Python and nothing for glibc."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    for raw in (
        "abc", "0", "-2", "+4", "2x", "", "1.5", "4 ", " 4 ", "4\n", "08", "010", "0x4", "\u0663",
        "1\u0663", "\uff12", "9" * 19, "9" * 23,
    ):
        _started_with(monkeypatch, MALLOC_ARENA_MAX=raw)
        got = session_hwm.allocator_setting()
        assert got["effective"] is None, raw
        assert got["arena_cap"] is None, raw
        assert repr(raw) in got["note"] and "not known" in got["note"], raw
    for raw, cap in ((" 4", 4), ("\t2", 2), ("1", 1), ("17", 17), ("9" * 18, int("9" * 18))):
        _started_with(monkeypatch, MALLOC_ARENA_MAX=raw)
        got = session_hwm.allocator_setting()
        assert got["effective"] is True and got["arena_cap"] == cap, raw
        assert got["note"] == f"malloc arenas capped at {cap} by MALLOC_ARENA_MAX"


def test_glibc_tunables_that_name_the_arena_limit_outrank_the_variable_and_are_not_guessed_at(monkeypatch):
    """MUTATION TARGET. Measured, glibc 2.39: ``glibc.malloc.arena_max`` in ``GLIBC_TUNABLES``
    beats ``MALLOC_ARENA_MAX`` in either order, and on its own it caps the arenas of a process
    whose variable reads "not set". Neither reading is the truth, so the answer is "not
    known". Tunables that are about something else leave the variable's reading alone."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    for tunables in (
        "glibc.malloc.arena_max=8",
        "glibc.malloc.tcache_count=0:glibc.malloc.arena_max=8",
        "glibc.malloc.arena_max=8;glibc.malloc.tcache_count=0",
    ):
        for variable in ("2", None):
            _started_with(monkeypatch, MALLOC_ARENA_MAX=variable, GLIBC_TUNABLES=tunables)
            got = session_hwm.allocator_setting()
            assert got["effective"] is None and got["arena_cap"] is None, (tunables, variable)
            assert "GLIBC_TUNABLES" in got["note"] and "not known" in got["note"]
    for tunables in ("glibc.malloc.tcache_count=0", "glibc.malloc.arena_test=4", "glibc.malloc.arena_max_x=3", ""):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2", GLIBC_TUNABLES=tunables)
        got = session_hwm.allocator_setting()
        assert got["effective"] is True and got["arena_cap"] == 2, tunables


def test_a_preloaded_malloc_replacement_has_no_glibc_arenas_for_the_cap_to_bound(monkeypatch):
    """MUTATION TARGET. Measured, glibc 2.39: with libjemalloc preloaded, ``MALLOC_ARENA_MAX=2``
    leaves glibc's malloc unused, so the process does not run with the cap however the variable
    reads. Preloaded libraries that are not allocators (a ``libgtk3-nocsd`` is common) change
    nothing."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    for preload in (
        "/usr/lib/x86_64-linux-gnu/libjemalloc.so.2",
        "libfoo.so:libtcmalloc_minimal.so.4",
        "libfoo.so libmimalloc.so",
        "LIBJEMALLOC.so",
    ):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2", LD_PRELOAD=preload)
        got = session_hwm.allocator_setting()
        assert got["effective"] is False and got["arena_cap"] is None, preload
        assert "replaced by" in got["note"] and "no effect" in got["note"] and "'2'" in got["note"], preload
    _started_with(monkeypatch, LD_PRELOAD="libjemalloc.so.2")
    got = session_hwm.allocator_setting()
    assert got["effective"] is False and "(it was set to" not in got["note"]
    for preload in ("libgtk3-nocsd.so.0", "", "/opt/jemalloc-notes/libfoo.so"):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2", LD_PRELOAD=preload)
        got = session_hwm.allocator_setting()
        assert got["effective"] is True and got["arena_cap"] == 2, preload


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
    def boom(*names):
        raise RuntimeError("procfs on fire")

    monkeypatch.setattr(session_hwm, "_starting_values", boom)
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
    """MUTATION TARGET: the memory-guard block returns early in four states (guard state
    unreadable, blind, window unknown or under the rate floor). The setting is a property of
    the process, so it rides all of them, and it never decides ``measured``."""
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


def test_the_soak_window_names_the_allocator_even_when_the_guard_cannot_be_read(monkeypatch, session):
    """The fourth early return: the guard's own state is unreadable. The setting does not come
    from the guard, so the one question that cannot be asked of it is not the reason to omit it."""
    from src.scheduler import memguard

    class _Broken(memguard.MemoryGuard):
        def state(self) -> dict:
            raise RuntimeError("no guard here")

    monkeypatch.setattr(memguard, "memory_guard", _Broken())
    monkeypatch.setattr(session_hwm, "allocator_setting", lambda: dict(_CAPPED))
    got = sw.soak_window(session)["memory_guard"]
    assert got["measured"] is False and "memory-guard state unavailable" in got["reason"]
    assert got["allocator"] == _CAPPED
