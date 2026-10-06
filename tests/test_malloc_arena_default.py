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
is the one glibc applies when it accepts it (checked against the real allocator below; a first
value glibc ignores lets the second apply, and the reading does not claim either);
``GLIBC_TUNABLES`` is read in every copy, as glibc reads it; a value glibc would ignore
or read differently ("4 ", "08", "010") is not claimed as applied; a process that is not on
glibc, or that has LOADED another malloc, is not "running with the cap" however the variable
reads (what counts is the file the loader mapped, read from the process's own map: an
``LD_PRELOAD`` entry that did not load is no replacement, and one that loaded under another name
is); and ``GLIBC_TUNABLES`` naming the arena limit, which outranks the variable, is not guessed
at.
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


def _run_launcher(
    tmp_path: Path,
    *,
    env_extra: dict[str, str] | None = None,
    oo_env: str | None = None,
    running: bool = False,
) -> dict[str, str | None]:
    """Run the real ``scripts/launch.sh`` in a throwaway tree and report what its children saw.

    ``server`` is the ``MALLOC_ARENA_MAX`` the server was started with, ``marker`` its
    ``OO_ARENA_MAX_DEFAULTED``, ``browser`` the ``MALLOC_ARENA_MAX`` the browser the launcher
    opened was started with: each "UNSET" when the child had none, and None when that child never
    ran. ``running`` takes the "a server is already healthy" path, which starts no server."""
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
    browser = tmp_path / "browser.seen"
    _exe(
        fake / "open-omniscience",
        '#!/usr/bin/env bash\nprintf "%s|%s" "${MALLOC_ARENA_MAX-UNSET}" '
        '"${OO_ARENA_MAX_DEFAULTED-UNSET}" > "$OO_TEST_ARENA_SEEN"\n',
    )
    # The first curl is the launcher's "is one already running?" probe and must fail; the
    # health wait after it succeeds, so the test does not wait 20 s. In ``running`` mode the
    # probe itself succeeds.
    _exe(
        fake / "curl",
        "#!/usr/bin/env bash\nexit 0\n"
        if running
        else '#!/usr/bin/env bash\nf="$OO_TEST_CURLCOUNT"\nn=$(cat "$f" 2>/dev/null || echo 0)\n'
        'echo $((n + 1)) > "$f"\n[ "$n" -ge 1 ]\n',
    )
    _exe(
        fake / "xdg-open",
        '#!/usr/bin/env bash\nprintf "%s" "${MALLOC_ARENA_MAX-UNSET}" > "$OO_TEST_BROWSER_SEEN"\n',
    )
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("OO_", "XDG_DATA_HOME")) and k != "MALLOC_ARENA_MAX"
    }
    env.update(
        PATH=f"{fake}{os.pathsep}{os.environ['PATH']}",
        HOME=str(tmp_path / "home"),
        OO_TEST_ARENA_SEEN=str(seen),
        OO_TEST_BROWSER_SEEN=str(browser),
        OO_TEST_CURLCOUNT=str(tmp_path / "curl.count"),
    )
    env.update(env_extra or {})
    proc = subprocess.run(
        ["bash", str(root / "scripts" / "launch.sh")],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    server, marker = seen.read_text(encoding="utf-8").split("|") if seen.exists() else (None, None)
    return {
        "server": server,
        "marker": marker,
        "browser": browser.read_text(encoding="utf-8") if browser.exists() else None,
    }


def _launch(tmp_path: Path, *, env_extra: dict[str, str] | None = None, oo_env: str | None = None) -> str | None:
    """The ``MALLOC_ARENA_MAX`` the launcher started the server with ("UNSET" when it had none)."""
    return _run_launcher(tmp_path, env_extra=env_extra, oo_env=oo_env)["server"]


@posix_only
def test_the_launcher_starts_the_server_with_the_arena_cap_when_nobody_chose_one(tmp_path):
    """MUTATION TARGET: delete the cap from the server's command in ``scripts/launch.sh`` and
    the server starts with glibc's default (up to 8 arenas per core) -- the instances the
    ruling is about."""
    assert _launch(tmp_path) == "2"


@posix_only
def test_a_value_the_operator_already_chose_is_kept(tmp_path):
    """MUTATION TARGET: an unconditional ``MALLOC_ARENA_MAX=2`` on the server's command would
    overwrite an operator's own tuning. R114 is a default, never an override."""
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
    """MUTATION TARGETS. The default is decided AFTER ``oo.env`` is read, so an install file
    that unsets the variable, or leaves it empty, has chosen no number and gets the default;
    decided BEFORE the file it would reach the server unset, or empty. And an EMPTY value
    from the caller is no choice either (``-n``/``:-``, not ``-v``/``-``): glibc ignores an
    empty value, so keeping it would leave the arenas uncapped while the launcher reads as
    having capped them."""
    assert _launch(tmp_path / "a", oo_env="unset MALLOC_ARENA_MAX\n") == "2"
    assert _launch(tmp_path / "b", oo_env="export MALLOC_ARENA_MAX=\n") == "2"
    assert _launch(tmp_path / "c", env_extra={"MALLOC_ARENA_MAX": ""}) == "2"


@posix_only
def test_the_default_is_the_servers_alone_the_browser_the_launcher_opens_never_gets_it(tmp_path):
    """MUTATION TARGET: ``export`` it again and the browser, started from the launcher's own
    shell on both paths (a fresh start, and "a server is already running", which starts no
    server at all), inherits a setting that was ruled and measured for the server. What the
    operator exports is the operator's own, and reaches the browser as it always did."""
    started = _run_launcher(tmp_path / "a")
    assert (started["server"], started["browser"]) == ("2", "UNSET")
    running = _run_launcher(tmp_path / "b", running=True)
    assert (running["server"], running["browser"]) == (None, "UNSET")
    assert _run_launcher(tmp_path / "c", env_extra={"MALLOC_ARENA_MAX": "8"})["browser"] == "8"


@posix_only
def test_the_launcher_marks_its_own_default_and_nothing_else(tmp_path):
    """MUTATION TARGETS: the marker is how the server tells the launcher's default (kept out
    of the LLM engines it starts) from a number somebody chose (which reaches them). Set it
    always and an operator's own tuning is stripped from the engines; never and the default
    reaches them. A marker the CALLER's environment already carried is not this launcher's word
    about this number, so it is cleared."""
    default = _run_launcher(tmp_path / "a")
    assert (default["server"], default["marker"]) == ("2", "1")
    operators = (
        {"env_extra": {"MALLOC_ARENA_MAX": "8"}},
        {"env_extra": {"MALLOC_ARENA_MAX": "2"}},  # the same number, still their choice
        {"oo_env": "export MALLOC_ARENA_MAX='4'\n"},
        {"oo_env": "MALLOC_ARENA_MAX=3\n"},
    )
    for n, kwargs in enumerate(operators):
        got = _run_launcher(tmp_path / f"operator{n}", **kwargs)
        assert got["marker"] == "UNSET", (kwargs, got)
    stale = _run_launcher(
        tmp_path / "stale", env_extra={"MALLOC_ARENA_MAX": "8", "OO_ARENA_MAX_DEFAULTED": "1"}
    )
    assert (stale["server"], stale["marker"]) == ("8", "UNSET")


@posix_only
def test_an_install_file_that_makes_the_variable_readonly_cannot_stop_the_app_starting(tmp_path):
    """The default is handed to the server's command through ``env``, not assigned in the
    launcher's own shell: a ``readonly`` declaration in ``oo.env`` (only an operator writes one)
    made the assignment fail, and ``set -e`` ended the launcher with no server."""
    got = _run_launcher(tmp_path, oo_env="readonly MALLOC_ARENA_MAX=4\n")
    assert (got["server"], got["marker"]) == ("4", "UNSET")


def test_the_launchers_marker_is_the_one_the_server_reads():
    """The launcher is bash and the server is Python, so nothing but this ties the spelling of
    the marker in one to the constant the other strips: a typo in either keeps the launcher's
    default in the LLM engines while every other test stays green."""
    from src.llm import model_store

    script = (REPO / "scripts" / "launch.sh").read_text(encoding="utf-8")
    assert f"{model_store.ARENA_DEFAULT_MARKER}=1" in script
    assert f"unset {model_store.ARENA_DEFAULT_MARKER}" in script


# --------------------------------------------------------------------------- #
#  The engines the server starts do not take the launcher's default
# --------------------------------------------------------------------------- #


@pytest.fixture
def engine_env(tmp_path, monkeypatch):
    """The server's own environment as the launcher leaves it (the default and its marker),
    with the model store inside ``tmp_path`` and no operator-set store variables."""
    from src.llm import model_store

    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: tmp_path)
    for var in ("OLLAMA_MODELS", "HF_HOME", "HF_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    monkeypatch.setenv(model_store.ARENA_DEFAULT_MARKER, "1")
    return monkeypatch


def test_the_launchers_default_is_left_out_of_what_an_engine_is_started_with(engine_env):
    """MUTATION TARGET: drop the strip from ``launch_env`` and Ollama and vLLM run on a cap that
    was ruled and measured for the app server alone, and that no diagnostic reads for them."""
    from src.llm import model_store

    marker = model_store.ARENA_DEFAULT_MARKER
    got = model_store.launch_env({"PATH": "/bin", "MALLOC_ARENA_MAX": "2", marker: "1"})
    assert "MALLOC_ARENA_MAX" not in got and marker not in got
    assert got["PATH"] == "/bin", "the rest of the environment is untouched"
    # the server's own environment is only read, never changed
    assert os.environ["MALLOC_ARENA_MAX"] == "2" and os.environ[marker] == "1"


def test_an_operators_own_value_still_reaches_the_engines_like_any_environment_variable(engine_env):
    """MUTATION TARGET: stripping the variable whenever it is present, marked or not, would
    discard a number the operator chose on purpose (their environment, or ``oo.env``). The
    marker, which means nothing to a child, is never passed on, whatever it says."""
    from src.llm import model_store

    marker = model_store.ARENA_DEFAULT_MARKER
    assert model_store.launch_env({"MALLOC_ARENA_MAX": "4"})["MALLOC_ARENA_MAX"] == "4"
    for said in ("0", "", "yes"):
        got = model_store.launch_env({"MALLOC_ARENA_MAX": "4", marker: said})
        assert got["MALLOC_ARENA_MAX"] == "4" and marker not in got, said
    # a marker with nothing to strip is harmless
    assert marker not in model_store.launch_env({marker: "1"})


def test_every_spawner_of_an_engine_or_a_download_builds_its_environment_without_the_default(
    engine_env, tmp_path
):
    """The three spawners the app has -- the Ollama daemon, the vLLM server, and the installs and
    weights download -- all take the environment from ``launch_env``, so none of them inherits
    the launcher's default. A fourth that built its own from ``os.environ`` would, and this is
    the list to extend. The Ollama install SCRIPT (``installer.run_installer``) is a deliberate
    non-member, not a forgotten one: a short shell that downloads and unpacks the binary, not an
    engine, which inherits the server's environment as it is (the daemon it installs is started by
    the service manager, with its own)."""
    from src.llm import model_store, ollama_lifecycle, vllm_lifecycle

    marker = model_store.ARENA_DEFAULT_MARKER
    for what, env in (
        ("the vLLM server", vllm_lifecycle._server_env()),
        ("the installs and the weights download", vllm_lifecycle._install_env(tmp_path / "pip")),
    ):
        assert "MALLOC_ARENA_MAX" not in env and marker not in env, what

    spawned: dict = {}

    class _Daemon:
        pid = 1

        def poll(self):
            return None

    engine_env.setattr(ollama_lifecycle, "_proc", None)  # restored afterwards: start() sets it
    engine_env.setattr(ollama_lifecycle, "binary_path", lambda: "/fake/ollama")
    engine_env.setattr(ollama_lifecycle, "is_running", lambda: False)
    engine_env.setattr(
        ollama_lifecycle.subprocess, "Popen", lambda argv, **kw: spawned.update(kw) or _Daemon()
    )
    ollama_lifecycle.start(wait=False)
    assert spawned, "the daemon was not spawned"
    assert "MALLOC_ARENA_MAX" not in spawned["env"] and marker not in spawned["env"], "the Ollama daemon"

    # and an operator's own value reaches all three
    engine_env.delenv(marker)
    engine_env.setenv("MALLOC_ARENA_MAX", "6")
    assert vllm_lifecycle._server_env()["MALLOC_ARENA_MAX"] == "6"
    assert vllm_lifecycle._install_env(tmp_path / "pip")["MALLOC_ARENA_MAX"] == "6"
    spawned.clear()
    ollama_lifecycle.start(wait=False)
    assert spawned["env"]["MALLOC_ARENA_MAX"] == "6"


# --------------------------------------------------------------------------- #
#  The reading: what the process STARTED with
# --------------------------------------------------------------------------- #


def _child_reading(env_extra: dict[str, str], code: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _ALLOCATOR_VARIABLES}
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

# Starts ``_COUNT_ARENAS`` through ``execve`` with an environment block that names one variable
# twice, first then last: no ``dict``-based API (subprocess, os.execve) can build such a block,
# and it is exactly what the allocator's lookup rule is about.
_EXEC_WITH_TWO_VALUES = """
import ctypes, os, sys
name, first, last, code = sys.argv[1:5]
rest = [f"{k}={v}".encode() for k, v in os.environ.items() if k != name]
entries = [f"{name}={first}".encode(), f"{name}={last}".encode(), *rest]
envp = (ctypes.c_char_p * (len(entries) + 1))(*entries, None)
argv = (ctypes.c_char_p * 4)(sys.executable.encode(), b"-c", code.encode(), None)
libc = ctypes.CDLL(None, use_errno=True)
libc.execve(sys.executable.encode(), argv, envp)
sys.exit("execve failed, errno %d" % ctypes.get_errno())
"""


# The three variables the reading is about: a child starts with none of them but the ones a test gives it,
# whatever the machine running the tests had set.
_ALLOCATOR_VARIABLES = ("MALLOC_ARENA_MAX", "GLIBC_TUNABLES", "LD_PRELOAD")


def _count_arenas(env_extra: dict[str, str] | None = None, *, twice: tuple[str, str, str] | None = None) -> dict:
    """What glibc did in a child started with ``env_extra``, or with one variable named twice
    (``twice`` = its name, first value, last value), and what the app's reading said there."""
    env = {k: v for k, v in os.environ.items() if k not in _ALLOCATOR_VARIABLES}
    env.update(env_extra or {})
    env["PYTHONPATH"] = str(REPO)
    cmd = [sys.executable, "-c", _COUNT_ARENAS]
    if twice is not None:
        cmd = [sys.executable, "-c", _EXEC_WITH_TWO_VALUES, *twice, _COUNT_ARENAS]
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
    first_wins = _count_arenas(twice=("MALLOC_ARENA_MAX", "3", "1"))
    assert first_wins["reading"]["arena_cap"] == 3
    assert first_wins["arenas"] == 3, "glibc applied the first value, as the reading says"
    last_is_bigger = _count_arenas(twice=("MALLOC_ARENA_MAX", "1", "3"))
    assert last_is_bigger["reading"]["arena_cap"] == 1
    assert last_is_bigger["arenas"] == 1, "glibc applied the first value here too"


# The values glibc IGNORES (it reads the whole value and gives up on one that is not a number it takes): a trailing
# blank or letter, a fraction, zero, an empty value, a digit that is not an ASCII one, a number past 64 bits. The
# next entry of the variable applies in their place. Measured on glibc 2.39 by naming each first and ``2`` second.
_IGNORED_VALUES = ("4 ", " 4 ", "abc", "2x", "08", "1.5", "0", "", "٣", "1٣", "２", "9" * 23)


@linux_only
def test_a_first_value_glibc_ignores_lets_the_second_apply_and_the_reading_claims_neither(arena_baseline):
    """glibc applies the first value it ACCEPTS, not the first it sees: measured, ``("4 ", "2")`` gave 2 arenas and
    so did ``("abc", "2")``. The reading takes the first entry, which glibc ignored, so it says not known: it
    never claims the second (which applied) and never the first (which did not). This is also where "glibc
    ignores this value" is PROVEN for the rows of the table below that expect the baseline: those rows alone
    cannot tell a value glibc ignored from one it took as a cap past every arena there is, on a machine where the
    two give the same count (three CPUs or more)."""
    for first in _IGNORED_VALUES:
        got = _count_arenas(twice=("MALLOC_ARENA_MAX", first, "2"))
        assert got["arenas"] == min(2, arena_baseline), (first, got["arenas"])
        assert got["reading"]["effective"] is None and got["reading"]["arena_cap"] is None, (first, got["reading"])


@linux_only
def test_a_first_value_glibc_reads_as_a_huge_number_applies_so_a_negative_one_bounds_nothing(arena_ceiling):
    """The coordinator's delta check of #1312, N2: the table's ``-2`` row said glibc IGNORES a negative number, and a
    machine with three or more CPUs could not tell (a value ignored and a cap past every arena both keep 17 there).
    glibc reads the value with ``strtoul``, which takes a sign: ``-2`` is the largest number there is, and named
    first it keeps every arena even with ``2`` behind it (measured, glibc 2.39: 17 against 2). The reading does not
    claim it (``unknown``), which is modest and not wrong. The row now says what glibc did."""
    for first in ("-2", "9" * 18):
        got = _count_arenas(twice=("MALLOC_ARENA_MAX", first, "2"))
        assert got["arenas"] == arena_ceiling, (first, got["arenas"], arena_ceiling)


@linux_only
def test_glibc_tunables_named_twice_is_read_in_every_copy_because_glibc_parses_each(arena_baseline):
    """MUTATION TARGET: taking the first copy only. Measured, glibc 2.39: ``GLIBC_TUNABLES`` named twice, the limit
    in the SECOND copy only, with the variable at 2, gave 1 arena where a reading of the first copy said capped at 2."""
    both = {"MALLOC_ARENA_MAX": "2"}
    for first, last, kept in (
        ("glibc.malloc.tcache_count=0", "glibc.malloc.arena_max=1", 1),
        ("glibc.malloc.arena_max=1", "glibc.malloc.tcache_count=0", 1),
        ("glibc.malloc.arena_max=3", "glibc.malloc.arena_max=1", 1),
    ):
        got = _count_arenas(both, twice=("GLIBC_TUNABLES", first, last))
        assert got["arenas"] == kept, (first, last, got["arenas"])
        assert got["reading"]["effective"] is None and got["reading"]["arena_cap"] is None, (first, last, got["reading"])
    got = _count_arenas(both, twice=("GLIBC_TUNABLES", "glibc.malloc.tcache_count=0", "glibc.malloc.tcache_count=1"))
    assert got["arenas"] == min(2, arena_baseline) and got["reading"]["effective"] is True, got


@pytest.fixture(scope="module")
def arena_baseline() -> int:
    """The arenas 16 allocating threads leave with none of the three variables, taken once for the
    module; skips where there is nothing for a cap to bound."""
    return _arena_baseline()


@pytest.fixture(scope="module")
def arena_ceiling(arena_baseline) -> int:
    """The arenas the same threads leave under a cap that is valid and far past any limit: what a cap glibc
    APPLIES but that bounds nothing keeps. It is the baseline wherever glibc's own default limit (8 arenas per
    online CPU) is above what 16 threads ask for (three CPUs or more); below that the default bites (16 on two,
    8 on one) and a cap that bounds nothing keeps MORE than the baseline, so a row that expects glibc to have
    applied such a cap compares with this and a row that expects glibc to have ignored the setting with the
    baseline (the coordinator's delta check of #1312, N2: both were the baseline, which only holds on four)."""
    ceiling = _count_arenas({"MALLOC_ARENA_MAX": "1000"})["arenas"]
    assert ceiling >= arena_baseline, "a cap past every arena cannot keep fewer than the default does"
    return ceiling


# What the reading is to say for a child started with ``env``, and what glibc must have done there.
# ``claim``: ``("capped", N)`` is "runs with the cap, N"; ``"unknown"`` is "not known" (effective None, no
# cap named); ``"not set"`` is "not capped" (effective False). ``arenas``: an int is "glibc kept that many"
# (no more than the ceiling); ``"baseline"`` is "glibc ignored the setting" (it kept what its own default
# limit allows); ``"ceiling"`` is "glibc applied a cap that bounds nothing" (it kept what 16 threads ask for);
# None is "glibc did something the reading does not claim to know" (the figure goes in the failure message
# and is not asserted). Measured on glibc 2.39 with 16 allocating threads; a glibc that reads a value
# differently fails the row with the figure in its message, which is what these are for. The two tokens are
# told apart only where the default limit bites (fewer than three CPUs), so
# ``test_a_first_value_glibc_ignores_lets_the_second_apply_and_the_reading_claims_neither`` and its twin
# prove each value's class by naming it first and a bounding value second, which tells them apart anywhere.
_REAL_SHAPES = [
    ("not set", {}, "not set", "baseline"),
    ("a plain number", {"MALLOC_ARENA_MAX": "3"}, ("capped", 3), 3),
    ("a leading blank", {"MALLOC_ARENA_MAX": " 4"}, ("capped", 4), 4),
    ("a leading tab", {"MALLOC_ARENA_MAX": "\t2"}, ("capped", 2), 2),
    ("a number far past the arenas there are", {"MALLOC_ARENA_MAX": "9" * 18}, ("capped", int("9" * 18)), "ceiling"),
    # What follows the digits makes glibc ignore the whole value: these are NOT the caps they look like.
    ("a trailing blank", {"MALLOC_ARENA_MAX": "4 "}, "unknown", "baseline"),
    ("blanks on both sides", {"MALLOC_ARENA_MAX": " 4 "}, "unknown", "baseline"),
    ("a trailing letter", {"MALLOC_ARENA_MAX": "2x"}, "unknown", "baseline"),
    ("a leading zero before an 8", {"MALLOC_ARENA_MAX": "08"}, "unknown", "baseline"),
    ("a fraction", {"MALLOC_ARENA_MAX": "1.5"}, "unknown", "baseline"),
    ("zero", {"MALLOC_ARENA_MAX": "0"}, "unknown", "baseline"),
    ("an empty value", {"MALLOC_ARENA_MAX": ""}, "unknown", "baseline"),
    ("an Arabic-Indic digit", {"MALLOC_ARENA_MAX": "\u0663"}, "unknown", "baseline"),
    ("an ASCII digit and an Arabic-Indic one", {"MALLOC_ARENA_MAX": "1\u0663"}, "unknown", "baseline"),
    ("a full-width digit", {"MALLOC_ARENA_MAX": "\uff12"}, "unknown", "baseline"),
    ("a number past 64 bits", {"MALLOC_ARENA_MAX": "9" * 23}, "unknown", "baseline"),
    # glibc DOES read these as numbers; the reading does not claim them, so it is only ever too modest. A
    # negative one is among them: ``strtoul`` takes the sign, so ``-2`` is the largest number there is, a cap that
    # bounds nothing (the row said glibc IGNORES it until the coordinator's delta check of #1312, N2).
    ("a negative number", {"MALLOC_ARENA_MAX": "-2"}, "unknown", "ceiling"),
    ("octal", {"MALLOC_ARENA_MAX": "010"}, "unknown", None),
    ("hexadecimal", {"MALLOC_ARENA_MAX": "0x4"}, "unknown", None),
    ("a plus sign", {"MALLOC_ARENA_MAX": "+4"}, "unknown", None),
    # A tunable naming the limit outranks the variable, in either direction.
    ("the tunable alone", {"GLIBC_TUNABLES": "glibc.malloc.arena_max=1"}, "unknown", 1),
    ("the tunable and a bigger variable",
     {"GLIBC_TUNABLES": "glibc.malloc.arena_max=1", "MALLOC_ARENA_MAX": "8"}, "unknown", 1),
    ("the tunable and a smaller variable",
     {"GLIBC_TUNABLES": "glibc.malloc.arena_max=8", "MALLOC_ARENA_MAX": "2"}, "unknown", 8),
    # Tunables about something else, and a preload that is no malloc replacement, leave the variable alone.
    ("another tunable", {"GLIBC_TUNABLES": "glibc.malloc.tcache_count=0", "MALLOC_ARENA_MAX": "2"},
     ("capped", 2), 2),
    ("a tunable with a similar name", {"GLIBC_TUNABLES": "glibc.malloc.arena_test=4", "MALLOC_ARENA_MAX": "2"},
     ("capped", 2), 2),
    # ``:`` is what separates tunables. A ``;`` makes the value of the tunable before it invalid, so glibc ignores
    # that one and the variable applies: an arena limit AFTER a semicolon is never read; one BEFORE it is named,
    # and the reading, which does not interpret the string, says it is not known (modest, never wrong).
    ("tunables joined by a semicolon, the limit second",
     {"GLIBC_TUNABLES": "glibc.malloc.tcache_count=0;glibc.malloc.arena_max=8", "MALLOC_ARENA_MAX": "2"},
     ("capped", 2), 2),
    ("tunables joined by a semicolon, the limit first",
     {"GLIBC_TUNABLES": "glibc.malloc.arena_max=8;glibc.malloc.tcache_count=0", "MALLOC_ARENA_MAX": "2"},
     "unknown", 2),
    ("a preloaded library that is no allocator", {"LD_PRELOAD": "libm.so.6", "MALLOC_ARENA_MAX": "2"},
     ("capped", 2), 2),
    # A preload the loader skipped (it says so on stderr and goes on) is no malloc replacement, whatever its name.
    ("a preload that does not load", {"LD_PRELOAD": "/nonexistent/libjemalloc.so.2", "MALLOC_ARENA_MAX": "2"},
     ("capped", 2), 2),
]


@linux_only
@pytest.mark.parametrize(("label", "env", "claim", "arenas"), _REAL_SHAPES, ids=[r[0] for r in _REAL_SHAPES])
def test_the_reading_is_checked_against_what_glibc_does_for_each_shape_its_rules_are_about(
        arena_baseline, arena_ceiling, label, env, claim, arenas):
    """The number, tunables and preload rules of ``allocator_setting`` were pinned by fakes only: a fake
    says what the rule is, never that glibc agrees. Each row starts a REAL child with that environment,
    counts the arenas glibc kept (``malloc_info``) and asks the app's own reading in the same process.
    SOUNDNESS first: the reading never says "runs with the cap" for a cap glibc did not apply, and never
    says "not capped" for one it did (the figure beside every row is glibc's). MUTATION TARGETS: each
    rule of ``_plain_count``, ``_tunes_arena_max``, the not-set branch and the reading of what LOADED. A
    REPLACED malloc is pinned below by a stand-in library the loader really loads (it is named like an
    allocator and defines no malloc, so it tests which file the reading follows, not what jemalloc does)
    and, where the machine has one, by a real jemalloc."""
    got = _count_arenas(env)
    reading, kept = got["reading"], got["arenas"]
    where = (
        f"[{label}] glibc kept {kept} arenas (baseline {arena_baseline}, ceiling {arena_ceiling}); "
        f"the reading: {reading}"
    )
    if claim == "not set":
        assert reading["effective"] is False and reading["arena_cap"] is None, where
    elif claim == "unknown":
        assert reading["effective"] is None and reading["arena_cap"] is None, where
    else:
        assert reading["effective"] is True and reading["arena_cap"] == claim[1], where
    if reading["effective"] is True:
        assert kept <= reading["arena_cap"], "the reading says capped, and glibc kept more than the cap: " + where
    if reading["effective"] is False:
        assert kept == arena_baseline, "the reading says not capped, and glibc capped: " + where
    if arenas == "baseline":
        assert kept == arena_baseline, "glibc was to ignore this setting: " + where
    elif arenas == "ceiling":
        assert kept == arena_ceiling, "glibc was to apply a cap that bounds nothing: " + where
    elif isinstance(arenas, int):
        assert kept == min(arenas, arena_ceiling), "glibc was to keep that many: " + where


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


def _proc_maps(monkeypatch, maps: str | Exception) -> None:
    """Make ``/proc/self/maps`` read as ``maps`` (or fail), and nothing else."""
    real = Path.read_bytes

    def fake(self: Path) -> bytes:
        if self.as_posix() != "/proc/self/maps":
            return real(self)
        if isinstance(maps, Exception):
            raise maps
        return maps.encode("utf-8")

    monkeypatch.setattr(Path, "read_bytes", fake)


def _loaded(monkeypatch, *files: str) -> None:
    """Make the process read as having loaded exactly these files (base names)."""
    monkeypatch.setattr(session_hwm, "_loaded_files", lambda: list(files))


def test_a_variable_set_twice_reads_as_its_first_value_as_glibc_and_os_environ_do(monkeypatch):
    """The unit half of the real-allocator test above: the first entry wins, an empty first
    entry is still the first, and a name that is only a prefix of another variable's, or an
    entry that is not an assignment, is not matched. ``GLIBC_TUNABLES`` is the exception, because
    glibc parses every copy of it: the copies are joined with ``:``."""
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
    _starting_block(monkeypatch, b"GLIBC_TUNABLES=glibc.malloc.tcache_count=0\0X=1\0GLIBC_TUNABLES=glibc.malloc.arena_max=1\0")
    tunables = session_hwm._starting_values("GLIBC_TUNABLES")[0]["GLIBC_TUNABLES"]
    assert tunables == "glibc.malloc.tcache_count=0:glibc.malloc.arena_max=1", "every copy, in order"
    assert session_hwm._tunes_arena_max(tunables) is True, "a limit named only in the second copy is seen"
    _starting_block(monkeypatch, b"GLIBC_TUNABLES=\0GLIBC_TUNABLES=glibc.malloc.arena_max=1\0")
    tunables = session_hwm._starting_values("GLIBC_TUNABLES")[0]["GLIBC_TUNABLES"]
    assert tunables == ":glibc.malloc.arena_max=1" and session_hwm._tunes_arena_max(tunables) is True, "an empty first copy too"
    _starting_block(monkeypatch, b"MALLOC_ARENA_MAX=3\0MALLOC_ARENA_MAX=1\0GLIBC_TUNABLES=glibc.malloc.tcache_count=0\0")
    got, _source = session_hwm._starting_values("MALLOC_ARENA_MAX", "GLIBC_TUNABLES")
    assert got == {"MALLOC_ARENA_MAX": "3", "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0"}, "only the tunables are joined"


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
    """MUTATION TARGET. ``launch.sh`` gives the server the variable on macOS too, where the allocator
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
        "glibc.malloc.arena_max=8:glibc.malloc.tcache_count=0",
        "glibc.malloc.arena_max=8;glibc.malloc.tcache_count=0",  # glibc ignores the semicolon form: modest
    ):
        for variable in ("2", None):
            _started_with(monkeypatch, MALLOC_ARENA_MAX=variable, GLIBC_TUNABLES=tunables)
            got = session_hwm.allocator_setting()
            assert got["effective"] is None and got["arena_cap"] is None, (tunables, variable)
            assert "GLIBC_TUNABLES" in got["note"] and "not known" in got["note"]
    for tunables in (
        "glibc.malloc.tcache_count=0", "glibc.malloc.arena_test=4", "glibc.malloc.arena_max_x=3", "",
        "glibc.malloc.tcache_count=0;glibc.malloc.arena_max=8",  # not a separator glibc reads: the limit is never seen
    ):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2", GLIBC_TUNABLES=tunables)
        got = session_hwm.allocator_setting()
        assert got["effective"] is True and got["arena_cap"] == 2, tunables


def test_a_malloc_replacement_the_process_loaded_has_no_glibc_arenas_for_the_cap_to_bound(monkeypatch):
    """MUTATION TARGET. Measured, glibc 2.39: with libjemalloc loaded, ``MALLOC_ARENA_MAX=2`` leaves glibc's
    malloc unused, so the process does not run with the cap however the variable reads. What counts is what
    LOADED (the process's own map), not what ``LD_PRELOAD`` says: an entry the loader skipped is no
    replacement, and one it loaded under another name is (the real-loader tests below). Libraries that are not
    allocators (a ``libgtk3-nocsd`` is common) change nothing, and neither does Intel's ``libtbbmalloc``,
    which takes malloc over only through its proxy."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    for files in (
        ["python3.13", "libjemalloc.so.2", "libc.so.6"],
        ["libfoo.so", "libtcmalloc_minimal.so.4"],
        ["libmimalloc.so"],
        ["LIBJEMALLOC.so"],
        ["libtbbmalloc_proxy.so.2"],
    ):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2")
        _loaded(monkeypatch, *files)
        got = session_hwm.allocator_setting()
        assert got["effective"] is False and got["arena_cap"] is None, files
        assert "replaced by" in got["note"] and "no effect" in got["note"] and "'2'" in got["note"], files
    _started_with(monkeypatch)
    _loaded(monkeypatch, "libjemalloc.so.2")
    got = session_hwm.allocator_setting()
    assert got["effective"] is False and "(it was set to" not in got["note"]
    for files in (["libgtk3-nocsd.so.0"], [], ["libfoo.so", "libc.so.6"], ["libtbbmalloc.so.2"]):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2")
        _loaded(monkeypatch, *files)
        got = session_hwm.allocator_setting()
        assert got["effective"] is True and got["arena_cap"] == 2, files


def test_the_reading_follows_what_loaded_and_not_the_name_ld_preload_gives(monkeypatch):
    """MUTATION TARGET: judging the preload by its NAME again. Both ends of it, each measured with a real
    jemalloc on glibc 2.39: an entry the loader could not load (``LD_PRELOAD=/nonexistent/libjemalloc.so.2``,
    skipped with a message) left the process on two capped glibc arenas, while the reading said malloc was
    replaced; the same library through a symlink named ``libfastalloc.so`` left it on one arena, while the
    reading said it was capped at 2. ``/etc/ld.so.preload`` is the third way in, and names nothing here."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    _started_with(monkeypatch, MALLOC_ARENA_MAX="2", LD_PRELOAD="/nonexistent/libjemalloc.so.2")
    _loaded(monkeypatch, "python3.13", "libc.so.6")
    got = session_hwm.allocator_setting()
    assert got["effective"] is True and got["arena_cap"] == 2, got
    _started_with(monkeypatch, MALLOC_ARENA_MAX="2", LD_PRELOAD="/opt/fast/libfastalloc.so")
    _loaded(monkeypatch, "python3.13", "libjemalloc.so.2", "libc.so.6")
    got = session_hwm.allocator_setting()
    assert got["effective"] is False and got["arena_cap"] is None and "libjemalloc.so.2" in got["note"], got
    _started_with(monkeypatch, MALLOC_ARENA_MAX="2")  # nothing in the environment at all
    got = session_hwm.allocator_setting()
    assert got["effective"] is False and "libjemalloc.so.2" in got["note"], "a replacement /etc/ld.so.preload asked for"


def test_a_loaded_replacement_outranks_the_tunables_that_would_otherwise_make_the_reading_unknown(monkeypatch):
    """MUTATION TARGET (the order of the two checks). ``glibc.malloc.arena_max`` tunes glibc's malloc, which a
    process that runs another one does not use: the reading is "replaced", a known answer, and not "not known"."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    _started_with(monkeypatch, MALLOC_ARENA_MAX="2", GLIBC_TUNABLES="glibc.malloc.arena_max=8")
    _loaded(monkeypatch, "libjemalloc.so.2")
    got = session_hwm.allocator_setting()
    assert got["effective"] is False and "replaced by" in got["note"], got
    _loaded(monkeypatch, "libc.so.6")
    assert session_hwm.allocator_setting()["effective"] is None, "without the replacement the tunables decide, as before"


def test_where_the_loaded_files_cannot_be_read_a_preload_that_names_a_replacement_is_a_doubt_and_no_claim(monkeypatch):
    """MUTATION TARGET. With no map to read the environment is all there is, and what it NAMES is a reason to
    doubt the cap, not proof of a replacement: the reading says it is not known, with the name in it. Nothing
    named, nothing doubted: the variable is read as it always was."""
    monkeypatch.setattr(session_hwm, "_glibc_version", lambda: "glibc 2.39")
    monkeypatch.setattr(session_hwm, "_loaded_files", lambda: None)
    _started_with(monkeypatch, MALLOC_ARENA_MAX="2", LD_PRELOAD="/usr/lib/libjemalloc.so.2:libfoo.so")
    got = session_hwm.allocator_setting()
    assert got["effective"] is None and got["arena_cap"] is None, got
    assert "libjemalloc.so.2" in got["note"] and "could not be read" in got["note"], got["note"]
    assert "not known" in got["note"] and "'2'" in got["note"], got["note"]
    for preload in ("libgtk3-nocsd.so.0", "", None):
        _started_with(monkeypatch, MALLOC_ARENA_MAX="2", LD_PRELOAD=preload)
        got = session_hwm.allocator_setting()
        assert got["effective"] is True and got["arena_cap"] == 2, preload


_MAPS = """\
55d0c0a00000-55d0c0a01000 r--p 00000000 fd:01 1310722                    /usr/bin/python3.13
55d0c0a01000-55d0c0a50000 r-xp 00001000 fd:01 1310722                    /usr/bin/python3.13
55d0c1b4a000-55d0c1c4e000 rw-p 00000000 00:00 0                          [heap]
7f3c1c000000-7f3c1c021000 rw-p 00000000 00:00 0 
7f3c1d3a4000-7f3c1d3a6000 r--p 00000000 fd:01 1048594                    /usr/lib/x86_64-linux-gnu/libjemalloc.so.2
7f3c1d3a6000-7f3c1d3b9000 r-xp 00002000 fd:01 1048594                    /usr/lib/x86_64-linux-gnu/libjemalloc.so.2
7f3c1d800000-7f3c1d828000 r--p 00000000 fd:01 1048576                    /usr/lib/x86_64-linux-gnu/libc.so.6
7f3c1d900000-7f3c1d902000 r--p 00000000 fd:01 1048601                    /opt/my libs/libfoo bar.so
7f3c1d902000-7f3c1d904000 r--p 00000000 fd:01 1048602                    /opt/jemalloc-notes/libgone.so (deleted)
7ffd4b3f6000-7ffd4b417000 rw-p 00000000 00:00 0                          [stack]
7ffd4b5c8000-7ffd4b5cc000 r--p 00000000 00:00 0                          [vvar]
"""


def test_the_loaded_files_are_the_base_names_the_map_lists_each_once_in_order(monkeypatch):
    """Anonymous mappings and the ``[heap]``, ``[stack]`` and ``[vvar]`` pseudo-files are no files; a library is
    listed once per mapping and read once; a path with a blank in it stays whole; ``(deleted)`` is no part
    of a name; and a directory called jemalloc does not make the library in it one."""
    _proc_maps(monkeypatch, _MAPS)
    got = session_hwm._loaded_files()
    assert got == ["python3.13", "libjemalloc.so.2", "libc.so.6", "libfoo bar.so", "libgone.so"], got
    assert session_hwm._malloc_replacement(got) == "libjemalloc.so.2"
    assert session_hwm._malloc_replacement(["libc.so.6", "libgone.so"]) is None
    assert session_hwm._malloc_replacement([]) is None
    _proc_maps(monkeypatch, OSError("no procfs"))
    assert session_hwm._loaded_files() is None, "unreadable is None, never an empty list"
    _proc_maps(monkeypatch, "")
    assert session_hwm._loaded_files() == [], "readable and empty is an empty list"


@linux_only
def test_the_real_kernels_map_lists_the_file_a_symlink_points_to_and_forgets_it_when_it_is_unmapped(tmp_path):
    """The assumption the reading rests on, against the real kernel rather than a fake: a file mapped through a
    symlink is listed under the name of the file it points to, and a mapping that is gone is gone."""
    import mmap

    target = tmp_path / "libjemalloc.so.2"
    target.write_bytes(b"\0" * mmap.PAGESIZE)
    link = tmp_path / "libfastalloc.so"
    link.symlink_to(target)
    with open(link, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ):
        files = session_hwm._loaded_files()
    assert files is not None and "libjemalloc.so.2" in files and "libfastalloc.so" not in files, files
    assert session_hwm._malloc_replacement(files) == "libjemalloc.so.2"
    assert "libjemalloc.so.2" not in (session_hwm._loaded_files() or [])


def _standin_library(tmp_path: Path) -> Path | None:
    """A shared library named like jemalloc that defines no malloc, built with the machine's C compiler; None
    where there is none. The loader maps it as it would the real one."""
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if cc is None:
        return None
    source = tmp_path / "standin.c"
    source.write_text("int oo_standin(void) { return 0; }\n", encoding="utf-8")
    out = tmp_path / "libjemalloc.so.2"
    built = subprocess.run([cc, "-shared", "-fPIC", "-o", str(out), str(source)],
                           capture_output=True, text=True, timeout=120)
    return out if built.returncode == 0 else None


_LOADED_AND_READ = (
    "import json; from src.monitoring import session_hwm as h; "
    "print(json.dumps({'loaded': h._loaded_files(), 'reading': h.allocator_setting()}))"
)


@linux_only
def test_the_loader_is_what_decides_a_library_through_a_symlink_loads_and_a_path_it_cannot_open_does_not(tmp_path):
    """The two Opus-read cases through a REAL loader. The library is a stand-in: named like the allocator and
    loaded like one, with no malloc of its own, so this pins which file the reading follows and nothing about
    jemalloc's arenas (a real one is the next test, where the machine has it)."""
    if session_hwm._glibc_version() is None:
        pytest.skip("not glibc")
    library = _standin_library(tmp_path)
    if library is None:
        pytest.skip("no C compiler here to build the stand-in library")
    link = tmp_path / "libfastalloc.so"
    link.symlink_to(library)
    got = _child_reading({"LD_PRELOAD": str(link), "MALLOC_ARENA_MAX": "2"}, _LOADED_AND_READ)
    assert "libjemalloc.so.2" in got["loaded"] and "libfastalloc.so" not in got["loaded"], got["loaded"]
    assert got["reading"]["effective"] is False and "libjemalloc.so.2" in got["reading"]["note"], got["reading"]
    skipped = _child_reading(
        {"LD_PRELOAD": str(tmp_path / "nowhere" / "libjemalloc.so.2"), "MALLOC_ARENA_MAX": "2"}, _LOADED_AND_READ)
    assert not [f for f in skipped["loaded"] if "jemalloc" in f], skipped["loaded"]
    assert skipped["reading"]["effective"] is True and skipped["reading"]["arena_cap"] == 2, skipped["reading"]


def _real_jemalloc() -> Path | None:
    for pattern in ("/usr/lib/*/libjemalloc.so.2", "/usr/lib64/libjemalloc.so.2", "/usr/lib/libjemalloc.so.2",
                    "/usr/local/lib/libjemalloc.so.2", "/opt/homebrew/lib/libjemalloc.so.2"):
        for found in sorted(Path("/").glob(pattern.lstrip("/"))):
            return found
    return None


@linux_only
def test_a_real_jemalloc_the_machine_has_is_read_as_replacing_malloc_and_leaves_glibc_one_arena(
        arena_baseline, tmp_path):
    """Where the machine has jemalloc (the review machine does; CI may not): 16 allocating threads with it
    preloaded leave glibc one arena where they leave ``arena_baseline`` without, even with the cap set, and the
    reading says malloc is replaced -- also when the library is reached through a symlink with another name."""
    library = _real_jemalloc()
    if library is None:
        pytest.skip("no libjemalloc on this machine")
    link = tmp_path / "libfastalloc.so"
    link.symlink_to(library)
    for preload in (str(library), str(link)):
        got = _count_arenas({"LD_PRELOAD": preload, "MALLOC_ARENA_MAX": "2"})
        assert got["arenas"] <= 1, (preload, got["arenas"], arena_baseline)
        assert got["reading"]["effective"] is False and "replaced by libjemalloc" in got["reading"]["note"], got["reading"]


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
