"""The passphrase stays in the one process that opens the corpus: no engine, download or installer child inherits it (2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``OO_DB_PASSPHRASE`` is how a scripted or headless start hands the app its passphrase (and ``OO_KEY_PASSPHRASE`` the one that wraps
the signing keys: ``secret_scrub.HELD_ENV_VARS`` lists both), and ``subprocess`` gives a child the environment of its parent
unless it is told otherwise. Ollama, the vLLM server, the weights download and the Ollama installer are
third-party programs that run for a long time and can reach the network; none can open the corpus or has a reason to try. A copy in
their environment is in their memory, in ``/proc/<pid>/environ`` and in anything a crash of theirs writes (the vLLM server's output
goes to a log file in the data folder). ``model_store.child_env`` is the one place the variable is dropped, ``launch_env`` starts from
it, and the installer script's child and the uninstall watcher (which outlives the app) take it directly. The children that DO need
the passphrase (the restore child, the OSM reference run) are handed it by name and are not tested here.

The last part is a walk over ``src/``: every call that starts a process either passes an ``env=`` or is in ``_INHERITS`` with the
reason it may inherit the server's environment, held to zero slack both ways, so that the next spawner has to be placed.
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from src.llm import installer, model_store
from src.monitoring.secret_scrub import HELD_ENV_VARS

PASS = "Qv9#k'L-72mZpx"
KEY_PASS = "Zk4#signing-wrap'Rt"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def engine_env(tmp_path, monkeypatch):
    """The server's environment as a scripted start leaves it (the passphrase set), with the model store inside ``tmp_path``."""
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: tmp_path)
    for var in ("OLLAMA_MODELS", "HF_HOME", "HF_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(model_store.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv("OO_KEY_PASSPHRASE", KEY_PASS)
    monkeypatch.setenv("OO_TEST_KEEP", "kept")
    return monkeypatch


def _held(env) -> list[str]:
    """The variables that hand a process a passphrase and that ``env`` holds."""
    return [name for name in HELD_ENV_VARS if name in env]


def test_the_names_are_the_ones_the_store_and_the_signing_keys_read():
    """MUTATION TARGET: a constant spelled differently from what ``connect`` or ``signing`` reads, so the pop removes nothing,
    or a third variable that holds a passphrase and is on no list."""
    assert model_store.PASSPHRASE_ENV == "OO_DB_PASSPHRASE"
    assert HELD_ENV_VARS == (model_store.PASSPHRASE_ENV, "OO_KEY_PASSPHRASE")
    source = (ROOT / "src" / "database" / "connect.py").read_text(encoding="utf-8")
    assert f'os.environ.get("{model_store.PASSPHRASE_ENV}")' in source, "the store no longer reads the variable by this name"
    signing = (ROOT / "src" / "custody" / "signing.py").read_text(encoding="utf-8")
    assert 'os.getenv("OO_KEY_PASSPHRASE")' in signing, "the signing keys no longer read the variable by this name"


def test_child_env_drops_the_passphrase_and_nothing_else_and_leaves_the_servers_environment_as_it_is(engine_env):
    """MUTATION TARGET: the pop left out, or the whole environment replaced."""
    before = dict(os.environ)
    assert _held(before) == list(HELD_ENV_VARS), "the control: the server holds both"
    got = model_store.child_env()
    assert _held(got) == [], "neither the store's passphrase nor the signing keys' goes to a child"
    assert got == {k: v for k, v in before.items() if k not in HELD_ENV_VARS}
    assert dict(os.environ) == before and os.environ[model_store.PASSPHRASE_ENV] == PASS, "the server keeps what it holds"
    handed = {"PATH": "/usr/bin", model_store.PASSPHRASE_ENV: PASS, "OO_KEY_PASSPHRASE": KEY_PASS}
    assert model_store.child_env(handed) == {"PATH": "/usr/bin"}
    assert handed[model_store.PASSPHRASE_ENV] == PASS, "the mapping it was given is a source, not a place to write"
    assert handed["OO_KEY_PASSPHRASE"] == KEY_PASS


def test_launch_env_starts_from_it_and_keeps_its_own_work(engine_env, tmp_path):
    """MUTATION TARGET: ``launch_env`` building its copy from ``os.environ`` itself again."""
    got = model_store.launch_env()
    assert _held(got) == []
    assert got["OO_TEST_KEEP"] == "kept"
    assert got["OLLAMA_MODELS"] == str(tmp_path / "models" / "ollama") and got["HF_HOME"] == str(tmp_path / "models" / "huggingface")
    assert _held(model_store.launch_env({model_store.PASSPHRASE_ENV: PASS, "OO_KEY_PASSPHRASE": KEY_PASS, "PATH": "/bin"})) == []


def test_every_engine_and_download_spawner_starts_from_an_environment_without_the_passphrase(engine_env, tmp_path):
    """The three spawners the app has (the Ollama daemon, the vLLM server, the installs and the weights download) take their
    environment from ``launch_env``. A fourth that built its own from ``os.environ`` would carry the passphrase, and this is the
    list to extend."""
    from src.llm import ollama_lifecycle, vllm_lifecycle

    assert _held(vllm_lifecycle._server_env()) == [], "the vLLM server"
    assert _held(vllm_lifecycle._install_env(tmp_path / "pip")) == [], "the installs and the weights download"

    spawned: dict = {}

    class _Daemon:
        pid = 1

        def poll(self):
            return None

    engine_env.setattr(ollama_lifecycle, "_proc", None)  # restored afterwards: start() sets it
    engine_env.setattr(ollama_lifecycle, "binary_path", lambda: "/fake/ollama")
    engine_env.setattr(ollama_lifecycle, "is_running", lambda: False)
    engine_env.setattr(ollama_lifecycle.subprocess, "Popen", lambda argv, **kw: spawned.update(kw) or _Daemon())
    ollama_lifecycle.start(wait=False)
    assert spawned, "the daemon was not spawned"
    assert _held(spawned["env"]) == [], "the Ollama daemon"
    assert spawned["env"]["OO_TEST_KEEP"] == "kept"


def test_the_installer_script_does_not_inherit_the_passphrase_and_keeps_the_rest_of_the_environment(engine_env, tmp_path):
    """MUTATION TARGET: ``env=`` left out of the installer's ``Popen``, which hands the script the server's whole environment. The
    script is a real ``sh`` that reports what it was given."""
    engine_env.setenv("OO_DATA_DIR", str(tmp_path))
    body = (
        b'#!/bin/sh\necho "passphrase=[${OO_DB_PASSPHRASE:-unset}]"\necho "signing=[${OO_KEY_PASSPHRASE:-unset}]"\n'
        b'echo "kept=[${OO_TEST_KEEP:-unset}]"\nexit 0\n'
    )
    sha = hashlib.sha256(body).hexdigest()
    staged = installer.stage_installer(body, sha)
    engine_env.setattr(installer, "_is_root", lambda: True)
    engine_env.setattr(installer, "platform_support", lambda: {"os": "linux", "arch": "x86_64", "scripted": True, "download_url": "x"})
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    out = list(installer.run_installer(str(staged)))
    assert "passphrase=[unset]" in out and "signing=[unset]" in out, out
    assert "kept=[kept]" in out, out
    assert out[-1] == "__exit__ 0"
    assert PASS not in "\n".join(out) and KEY_PASS not in "\n".join(out)


def test_a_real_child_of_the_servers_own_environment_would_have_it(engine_env):
    """The control: ``subprocess`` with no ``env=`` hands the passphrase over, so the tests above measure something."""
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["sh", "-c", 'echo "[${OO_DB_PASSPHRASE:-unset}][${OO_KEY_PASSPHRASE:-unset}]"'], capture_output=True, text=True, timeout=30
    )
    assert proc.stdout.strip() == f"[{PASS}][{KEY_PASS}]"
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["sh", "-c", 'echo "[${OO_DB_PASSPHRASE:-unset}][${OO_KEY_PASSPHRASE:-unset}]"'],
        capture_output=True, text=True, timeout=30, env=model_store.child_env(),
    )
    assert proc.stdout.strip() == "[unset][unset]"


def test_the_uninstall_watcher_that_outlives_the_app_does_not_inherit_the_passphrase(engine_env):
    """MUTATION TARGET: ``env=`` left out of the watcher's ``Popen``. It is detached (``start_new_session``) and runs after the app
    has gone, for as long as the wipe takes: the one child nobody expects to still be holding anything."""
    from src.safety import uninstall

    seen: dict = {}
    engine_env.setattr(uninstall.subprocess, "Popen", lambda argv, **kw: seen.update(kw) or None)
    uninstall._default_spawn({"launchers": [], "venv": None}, 4242)
    assert seen, "the watcher was not started"
    assert _held(seen["env"]) == [] and seen["env"]["OO_TEST_KEEP"] == "kept"
    assert seen["start_new_session"] is True


# --------------------------------------------------------------------------- #
#  Every process the app starts
# --------------------------------------------------------------------------- #
_SUBPROCESS_CALLS = frozenset({"Popen", "run", "check_output", "check_call", "call", "getoutput", "getstatusoutput"})
_POOLS = frozenset({"ProcessPoolExecutor", "create_subprocess_exec", "create_subprocess_shell"})


def _spawn_calls(tree: ast.AST) -> list[tuple[int, str, bool]]:
    """``(line, what, given)`` for each call that starts a process: ``subprocess.*``, ``os.system``/``popen``/``exec*``/``spawn*``,
    a ``ProcessPoolExecutor``, ``multiprocessing`` ``Process``/``Pool`` and asyncio's subprocess calls, under the names the
    module imports them by. ``given`` is whether the call names an ``env`` or hands a ``**`` mapping (read as carrying one: the
    runtime tests above read what it carries). A spawn through a wrapper of the module's own is outside the walk."""
    modules: dict[str, str] = {}  # local name -> module it names
    names: dict[str, tuple[str, str]] = {}  # local name -> (module, attribute)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in {"subprocess", "os", "multiprocessing", "asyncio"}:
                    modules[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module in {"subprocess", "os", "multiprocessing", "asyncio", "concurrent.futures"}:
            for a in node.names:
                names[a.asname or a.name] = (node.module, a.name)
    found: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        module = attr = None
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            module, attr = modules.get(node.func.value.id), node.func.attr
            if module is None and node.func.value.id in {"ctx", "_mp", "mp"}:  # a multiprocessing context
                module = "multiprocessing"
        elif isinstance(node.func, ast.Name) and node.func.id in names:
            module, attr = names[node.func.id]
        if module is None or attr is None:
            continue
        spawns = (
            (module == "subprocess" and attr in _SUBPROCESS_CALLS)
            or (module == "os" and (attr in {"system", "popen"} or attr.startswith(("exec", "spawn", "posix_spawn"))))
            or (module in {"asyncio", "concurrent.futures"} and attr in _POOLS)
            or (module == "multiprocessing" and attr in {"Process", "Pool"})
        )
        if spawns:
            given = any(k.arg == "env" or k.arg is None for k in node.keywords)
            found.append((node.lineno, f"{module}.{attr}", given))
    # a ProcessPoolExecutor named directly (``from concurrent.futures import ProcessPoolExecutor``) is read by the branch above
    return found


_WALK_CASES = {
    "a call with no env": ("import subprocess\nsubprocess.run(['x'])\n", [("subprocess.run", False)]),
    "a call with an env": ("import subprocess\nsubprocess.Popen(['x'], env=e)\n", [("subprocess.Popen", True)]),
    "a call with a mapping splat": ("import subprocess\nsubprocess.Popen(['x'], **kw)\n", [("subprocess.Popen", True)]),
    "an alias of the module": ("import subprocess as sp\nsp.check_output(['x'])\n", [("subprocess.check_output", False)]),
    "a name imported from it": ("from subprocess import run as go\ngo(['x'])\n", [("subprocess.run", False)]),
    "os.execv": ("import os\nos.execv('a', ['a'])\n", [("os.execv", False)]),
    "os.system": ("import os\nos.system('x')\n", [("os.system", False)]),
    "a process pool": ("from concurrent.futures import ProcessPoolExecutor\nProcessPoolExecutor(max_workers=1)\n", [("concurrent.futures.ProcessPoolExecutor", False)]),
    "a context's process": ("import multiprocessing\nctx = multiprocessing.get_context('spawn')\nctx.Process(target=f)\n", [("multiprocessing.Process", False)]),
    "asyncio's": ("import asyncio\nasyncio.create_subprocess_exec('x')\n", [("asyncio.create_subprocess_exec", False)]),
    "a method of another object": ("class A:\n    def run(self): ...\nA().run()\nother.run(['x'])\n", []),
    "a run of something else": ("import threading\nthreading.Thread(target=f).start()\n", []),
}


@pytest.mark.parametrize("case", sorted(_WALK_CASES))
def test_the_spawn_walk_reads_each_shape_of_a_call_that_starts_a_process(case):
    source, expected = _WALK_CASES[case]
    assert [(what, given) for _, what, given in _spawn_calls(ast.parse(source))] == expected


#: Modules of ``src/`` with a call that starts a process and names no ``env``: the child inherits the server's environment, which
#: holds the passphrase on a scripted or headless start. Each says why that is right for it. Held to zero slack both ways.
_INHERITS = {
    "analytics/reindex_parallel.py": "the keyword workers of a re-index: the app's own code, which never opens the corpus (it extracts from the text it is handed), started by the standard library; they hold the inherited core limit, and where the hard limit is 0 the forkserver they are forked from engages the guard when it starts (`core_guard_preload`) and each worker engages it first in `_worker_init`",
    "api/diagnostics/bundle.py": "`sysctl -n machdep.cpu.brand_string`: a fixed local read of the processor's name, for under two seconds, whose output the app reads",
    "llm/backend.py": "`nvidia-smi --query-gpu`: a fixed local read of the driver's report, for under five seconds, whose output the app reads",
    "llm/installer.py": "`sudo -n true`: a fixed local test of whether sudo asks for a password, for under five seconds (the install script beside it is given `child_env()`)",
    "monitoring/forensics.py": "`qubesdb-read`: a fixed local read, for under three seconds, whose output the app reads",
    "monitoring/kernel_log.py": "`journalctl`, `dmesg` and `systemctl`, which `exit_evidence` reaches through the same helper: fixed local reads, each under a hard timeout, whose output the app reads",
    "monitoring/llm_throughput.py": "`nvidia-smi`: a fixed local read of the GPU's use, for under five seconds, whose output the app reads",
    "monitoring/windows_locks.py": "one read-only PowerShell cmdlet, bounded by a timeout, whose output the app reads",
    "safety/data_volume.py": "`os.execv` of this same program: it IS the app, which holds the passphrase by design and engages the core guard again at its start",
    "safety/uninstall.py": "`xdg-user-dir DESKTOP`: a fixed local read, for under three seconds (the detached watcher beside it is given `child_env()`)",
}


def test_every_process_the_app_starts_is_given_an_environment_or_inherits_one_for_a_written_reason():
    """MUTATION TARGET: a spawner added without ``env=`` and without a place in ``_INHERITS``, or the watcher's ``env=`` taken out.
    The passphrase is in the server's environment on a scripted or headless start, and a child that was never asked whether it
    needs it is where a copy of it comes to be kept (``child_env`` says what a child has no use for)."""
    without: dict[str, list[str]] = {}
    given: set[str] = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT / "src").as_posix()
        for line, what, has_env in _spawn_calls(ast.parse(path.read_text(encoding="utf-8"))):
            (given if has_env else set()).add(rel)
            if not has_env:
                without.setdefault(rel, []).append(f"{what}, line {line}")
    assert {"llm/ollama_lifecycle.py", "llm/vllm_lifecycle.py", "llm/installer.py", "monitoring/release_run.py", "osm/reference_run.py",
            "safety/uninstall.py", "api/main.py"} <= given, f"the walk must find them, not nothing: {sorted(given)}"
    assert set(without) == set(_INHERITS), (
        f"start a process with no env and no reason: { {k: v for k, v in without.items() if k not in _INHERITS} }; "
        f"listed but no longer doing so (take them out): {sorted(set(_INHERITS) - set(without))}"
    )
    assert all(len(reason) > 40 for reason in _INHERITS.values()), "a reason, not a placeholder"
