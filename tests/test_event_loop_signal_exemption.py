"""R165: the loops that run on the event loop's thread are exempt from the loop-form rule because uvicorn, not Python's default handler, takes SIGINT.

A synchronous loop on the event loop (the lifespan's boot code, a request middleware) is on the main thread, where a Ctrl-C would normally raise
KeyboardInterrupt in whatever line is running. It does not here: ``uvicorn.run`` replaces SIGINT and SIGTERM with a handler that only sets a flag
(``Server.capture_signals``), so the loop runs to its end and the server then shuts down. Measured, 18 of 18 runs, by RC2:
/mnt/project-files/rc-diagnostics/sigint-probe-2026-10-17/REPORT.md (a held-lock spin planted at startup, in the middleware and at shutdown; no
KeyboardInterrupt in the planted code, the lock never left owned).

The exemption holds only while the app is served that way, so this file is its precondition. The allowlist in tests/test_gates_survive_an_interrupt.py
names each exempt function with this file as part of its reason. Part 1 reads the sources; part 2 sends a real SIGINT to a real server.
"""

from __future__ import annotations

import ast
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

#: the signals uvicorn takes, and a handler anywhere else for either of them would take them back
_TAKEN = {"SIGINT", "SIGTERM"}

#: THE ONE handler for SIGTERM outside uvicorn (0.5.1 item 41): ``src.api.database.install_stop_signal_cleanup``. It is installed BEFORE ``uvicorn.run``,
#: so during serving uvicorn's capture has replaced it (the exemption's premise holds) and uvicorn puts it back and re-raises SIGTERM into it as it
#: returns; the handler removes the backup route's plaintext snapshot, restores the default action and signals itself, so it never swallows the
#: signal. What this file checks of it: it registers SIGTERM only, restores ``SIG_DFL`` and re-signals (``os.kill``), and ``_serve`` calls it before
#: ``uvicorn.run``. Anything else that takes either signal is still a problem.
_STOP_CLEANUP = ("src/api/database.py", "install_stop_signal_cleanup")

#: modules that install handlers for those signals in a process of their own, and are imported by no server code (checked below): the OSM reference run
#: is a CLI (scripts/osm_reference_run.py) whose handlers last for the length of its ``with`` and end its own process
_OWN_PROCESS = {"src/osm/reference_run.py": "reference_run"}


def _signal_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"signal", "add_signal_handler", "set_wakeup_fd"}:
            yield node


def _names_in(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _stop_cleanup_calls(tree: ast.AST, path: str) -> tuple[set[ast.Call], list[str]]:
    """The signal calls of the one allowed stop-cleanup function (the SIGTERM registration and the restore of the default action), and what is wrong
    with the function if it is not the shape described at ``_STOP_CLEANUP``. A call that is not one of those two stays unallowed and is reported by the caller."""
    allowed_path, name = _STOP_CLEANUP
    if path != allowed_path:
        return set(), []
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    if not fns:
        return set(), []
    allowed: set[ast.Call] = set()
    problems: list[str] = []
    for call in _signal_calls(fns[0]):
        if call.func.attr != "signal" or len(call.args) < 2:
            continue
        first, second = _names_in(call.args[0]), _names_in(call.args[1])
        if first & _TAKEN == {"SIGTERM"}:
            allowed.add(call)
        elif "SIG_DFL" in second:
            allowed.add(call)
    resignals = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "kill" for c in ast.walk(fns[0]))
    if not resignals:
        problems.append(f"{path}: {name} never re-sends the signal, so it would swallow SIGTERM")
    return allowed, problems


def exemption_problems(sources: dict[str, str], pyproject: str) -> list[str]:
    """Why the event-loop exemption would no longer hold for these sources (``{relative path: text}`` of everything under src/) and this pyproject.
    Empty when it holds."""
    problems: list[str] = []
    main_src = sources.get("src/api/main.py", "")
    main_tree = ast.parse(main_src)
    top = {n.name: n for n in main_tree.body if isinstance(n, ast.FunctionDef)}
    serve_fn = top.get("_serve")
    runs = [
        c for c in ast.walk(serve_fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "run" and "uvicorn" in _names_in(c.func)
    ] if serve_fn is not None else []
    if not runs:
        problems.append("src/api/main.py: _serve() does not serve with uvicorn.run(...)")
    if "main" not in top or not any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_serve" for c in ast.walk(top["main"])):
        problems.append("src/api/main.py: main() does not call _serve()")
    for call in runs:
        for kw in call.keywords:
            if kw.arg and "signal" in kw.arg.lower():
                problems.append(f"src/api/main.py: uvicorn.run(...) is given {kw.arg}=, which changes who takes the signals")
    cleanup_path, cleanup_name = _STOP_CLEANUP
    if cleanup_path in sources and any(isinstance(n, ast.FunctionDef) and n.name == cleanup_name for n in ast.walk(ast.parse(sources[cleanup_path]))):
        calls = [
            c for c in ast.walk(serve_fn) if isinstance(c, ast.Call) and cleanup_name in _names_in(c.func)
        ] if serve_fn is not None else []
        if not calls:
            problems.append(f"src/api/main.py: _serve() does not call {cleanup_name}, so the SIGTERM handler is never installed")
        elif runs and min(c.lineno for c in calls) > min(r.lineno for r in runs):
            problems.append(f"src/api/main.py: _serve() calls {cleanup_name} after uvicorn.run begins, where uvicorn would not put it back")
    if not re.search(r'^open-omniscience\s*=\s*"src\.api\.main:main"\s*$', pyproject, re.MULTILINE):
        problems.append("pyproject.toml: the open-omniscience script is not src.api.main:main")

    for path, module in _OWN_PROCESS.items():
        importers = [p for p, t in sources.items() if p != path and re.search(rf"\b{module}\b", t)]
        if importers:
            problems.append(f"{path} installs SIGINT/SIGTERM handlers for a process of its own, but {importers} mention {module}")

    for path, text in sources.items():
        if path in _OWN_PROCESS:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any("Server" in ast.unparse(b) for b in node.bases):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in {"capture_signals", "install_signal_handlers", "handle_exit"}:
                        problems.append(f"{path}:{item.lineno}: a uvicorn Server subclass overrides {item.name}")
        allowed, stop_problems = _stop_cleanup_calls(tree, path)
        problems.extend(stop_problems)
        for call in _signal_calls(tree):
            if call in allowed:
                continue
            where = f"{path}:{call.lineno}"
            if call.func.attr == "set_wakeup_fd":
                problems.append(f"{where}: signal.set_wakeup_fd")
                continue
            if call.func.attr == "add_signal_handler":
                problems.append(f"{where}: loop.add_signal_handler")
                continue
            first = _names_in(call.args[0]) if call.args else set()
            if first & _TAKEN or "default_int_handler" in _names_in(call):
                problems.append(f"{where}: a handler for {sorted(first & _TAKEN) or 'SIGINT'} (default_int_handler) is installed")
            elif path == "src/api/main.py" and "sig" in first:
                # install_signal_handlers loops over names: it must still be SIGHUP only
                loops = [n for n in ast.walk(tree) if isinstance(n, ast.For) and isinstance(n.iter, ast.Tuple) and call in ast.walk(n)]
                names = {c.value for c in ast.walk(loops[-1].iter) if isinstance(c, ast.Constant)} if loops else set()
                if names != {"SIGHUP"}:
                    problems.append(f"{where}: install_signal_handlers registers {sorted(names) or 'an unknown set'}, not SIGHUP alone")
            elif not (first & {"SIGHUP"}) and path != "src/api/main.py":
                problems.append(f"{where}: signal.signal with a handler this test cannot name")
    return problems


def _repo_sources() -> dict[str, str]:
    return {str(p.relative_to(_ROOT)).replace(os.sep, "/"): p.read_text(encoding="utf-8") for p in (_ROOT / "src").rglob("*.py")}


def test_the_app_is_served_by_uvicorn_run_and_nothing_takes_sigint_or_sigterm_back():
    problems = exemption_problems(_repo_sources(), (_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not problems, "the event-loop exemption of R165 no longer holds: " + "; ".join(problems)


_PYPROJECT_OK = '[project.scripts]\nopen-omniscience = "src.api.main:main"\n'
_MAIN_OK = (
    "import uvicorn, signal\n"
    "def install_signal_handlers():\n"
    "    for name in ('SIGHUP',):\n"
    "        sig = getattr(signal, name)\n"
    "        signal.signal(sig, print)\n"
    "def _serve():\n"
    "    uvicorn.run(app)\n"
    "def main():\n"
    "    _serve()\n"
)


_DB_OK = (
    "import os, signal\n"
    "def install_stop_signal_cleanup():\n"
    "    def _h(signum, frame):\n"
    "        signal.signal(signum, signal.SIG_DFL)\n"
    "        os.kill(os.getpid(), signum)\n"
    "    signal.signal(signal.SIGTERM, _h)\n"
)
_MAIN_CLEANUP = _MAIN_OK.replace("    uvicorn.run(app)\n", "    install_stop_signal_cleanup()\n    uvicorn.run(app)\n")


@pytest.mark.parametrize(
    ("label", "sources", "pyproject", "expect"),
    [
        ("sound", {"src/api/main.py": _MAIN_OK}, _PYPROJECT_OK, None),
        ("sound with the stop cleanup", {"src/api/main.py": _MAIN_CLEANUP, "src/api/database.py": _DB_OK}, _PYPROJECT_OK, None),
        ("the stop cleanup never called", {"src/api/main.py": _MAIN_OK, "src/api/database.py": _DB_OK}, _PYPROJECT_OK, "never installed"),
        (
            "the stop cleanup called after uvicorn.run",
            {"src/api/main.py": _MAIN_OK.replace("    uvicorn.run(app)\n", "    uvicorn.run(app)\n    install_stop_signal_cleanup()\n"), "src/api/database.py": _DB_OK},
            _PYPROJECT_OK,
            "after uvicorn.run",
        ),
        (
            "the stop cleanup taking SIGINT too",
            {"src/api/main.py": _MAIN_CLEANUP, "src/api/database.py": _DB_OK + "    signal.signal(signal.SIGINT, print)\n"},
            _PYPROJECT_OK,
            "SIGINT",
        ),
        (
            "the stop cleanup swallowing the signal",
            {"src/api/main.py": _MAIN_CLEANUP, "src/api/database.py": _DB_OK.replace("        os.kill(os.getpid(), signum)\n", "")},
            _PYPROJECT_OK,
            "swallow",
        ),
        (
            "a second SIGTERM handler beside the allowed one",
            {"src/api/main.py": _MAIN_CLEANUP, "src/api/database.py": _DB_OK + "def other():\n    signal.signal(signal.SIGTERM, print)\n"},
            _PYPROJECT_OK,
            "SIGTERM",
        ),
        ("a SIGINT handler planted elsewhere", {"src/api/main.py": _MAIN_OK, "src/x.py": "import signal\nsignal.signal(signal.SIGINT, signal.default_int_handler)\n"}, _PYPROJECT_OK, "SIGINT"),
        ("a SIGTERM handler planted elsewhere", {"src/api/main.py": _MAIN_OK, "src/x.py": "import signal\nsignal.signal(signal.SIGTERM, lambda *a: None)\n"}, _PYPROJECT_OK, "SIGTERM"),
        ("a loop signal handler", {"src/api/main.py": _MAIN_OK, "src/x.py": "def f(loop):\n    loop.add_signal_handler(2, f)\n"}, _PYPROJECT_OK, "add_signal_handler"),
        ("a plain asyncio.run serving loop", {"src/api/main.py": _MAIN_OK.replace("uvicorn.run(app)", "asyncio.run(serve())")}, _PYPROJECT_OK, "does not serve with uvicorn.run"),
        ("uvicorn.run given a signal option", {"src/api/main.py": _MAIN_OK.replace("run(app)", "run(app, install_signal_handlers=False)")}, _PYPROJECT_OK, "install_signal_handlers"),
        ("the install loop growing SIGINT", {"src/api/main.py": _MAIN_OK.replace("('SIGHUP',)", "('SIGHUP', 'SIGINT')")}, _PYPROJECT_OK, "not SIGHUP alone"),
        ("a Server subclass taking the signals", {"src/api/main.py": _MAIN_OK, "src/s.py": "import uvicorn\nclass S(uvicorn.Server):\n    def capture_signals(self):\n        pass\n"}, _PYPROJECT_OK, "capture_signals"),
        ("another entry point", {"src/api/main.py": _MAIN_OK}, '[project.scripts]\nopen-omniscience = "src.other:main"\n', "not src.api.main:main"),
    ],
)
def test_the_exemption_check_goes_red_on_each_way_of_losing_it(label, sources, pyproject, expect):
    problems = exemption_problems(sources, pyproject)
    if expect is None:
        assert problems == [], problems
    else:
        assert any(expect in p for p in problems), (label, problems)


# --- part 2: a real SIGINT to a real server ------------------------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve_and_interrupt(tmp_path: Path, *, plant: str = "") -> tuple[int, str]:
    """Boot ``main()`` on a throwaway data dir, wait for /api/health, send one SIGINT, return (exit status, stderr). ``plant`` is code run first in
    the child: a deliberately broken server for the red-without run."""
    port = _free_port()
    env = dict(os.environ, OO_DATA_DIR=str(tmp_path), OO_PORT=str(port), OO_DB_PLAINTEXT="1", OO_NO_SCHEDULER="1", PYTHONUNBUFFERED="1")
    # Python installs ``default_int_handler`` for SIGINT at start only when the parent did not leave SIGINT ignored; a suite started as
    # a background job from a non-interactive shell does (SigIgn 0x1001006), and then no handler exists to be taken back or captured.
    # Setting it first gives the child the state an interactive run has, so the test measures uvicorn's capture, not the parent's shell.
    code = f"import signal\nsignal.signal(signal.SIGINT, signal.default_int_handler)\n{plant}\nfrom src.api.main import main\nmain()\n"
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.3)
        else:
            raise AssertionError("the server did not become healthy within 60 s")
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=60)
        return proc.returncode, (out or "") + (err or "")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals: the exemption was measured on POSIX")
def test_a_real_sigint_stops_the_server_through_uvicorn_and_never_raises_keyboardinterrupt(tmp_path):
    status, log = _serve_and_interrupt(tmp_path)
    assert "KeyboardInterrupt" not in log, log[-2000:]
    assert "Application shutdown complete" in log, log[-2000:]
    assert status in (0, 130, 143, -signal.SIGINT), (status, log[-2000:])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals: the exemption was measured on POSIX")
def test_the_run_goes_red_when_the_default_handler_takes_sigint_back(tmp_path):
    """Red-without: the same boot with uvicorn's capture of the signals switched off, which is what a handler installed elsewhere would amount to."""
    plant = (
        "import contextlib, uvicorn.server as _s\n"
        "@contextlib.contextmanager\n"
        "def _no_capture(self):\n    yield\n"
        "_s.Server.capture_signals = _no_capture\n"
    )
    _status, log = _serve_and_interrupt(tmp_path, plant=plant)
    assert "KeyboardInterrupt" in log, "the planted fault was not seen: the real-signal test above proves nothing"
