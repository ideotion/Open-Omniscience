"""The app's own server start runs on the stdlib asyncio loop, never uvloop (R642).

uvicorn[standard] installs uvloop and uvicorn's default ``loop="auto"`` picks it. uvloop resolves and connects in libuv's C code, past
every ``socket`` call the airplane guard patches (src/ingest/airplane.py), so an async client on the server's loop reached a
non-loopback listener with airplane mode engaged (security read B of R639). ``_serve`` therefore pins ``loop="asyncio"``, and a server started
another way on any other loop (``python -m uvicorn src.api.main:app`` without ``--loop asyncio`` picks uvloop) refuses to start.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

import src.api.main as main_mod
import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch

_ROOT = Path(__file__).resolve().parents[1]
#: Names a module can serve with. Only ``uvicorn.run``/``uvicorn.Config`` through the bare module name are allowed (so the check
#: below can read their ``loop=``); the other ways of reaching them that an AST can see are refused (a dynamic lookup it cannot see
#: is not claimed).
_SERVING_NAMES = {"run", "Config", "Server", "main"}


def _trees():
    for top in ("src", "scripts"):
        for py in (_ROOT / top).rglob("*.py"):
            yield py.relative_to(_ROOT).as_posix(), ast.parse(py.read_text(encoding="utf-8"))


def _uvicorn_run_calls() -> list[tuple[str, ast.Call]]:
    calls = []
    for where, tree in _trees():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SERVING_NAMES
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "uvicorn"
            ):
                calls.append((where, node))
    return calls


def test_uvicorn_is_never_reached_around_the_checked_call():
    """An alias (``import uvicorn as uv``), a ``from uvicorn import run/Config/Server``, ``uvicorn.main`` or a ``uvicorn.Server`` would
    serve past the ``loop=`` check below, so none of the forms an AST can see may exist: an alias, any ``import uvicorn.<sub>``, a
    from-import of a serving name or of the ``config``/``server``/``main`` submodules, ``uvicorn.<submodule>`` or ``uvicorn.Server``, a
    ``uvicorn.run``/``Config`` that is passed around instead of called, and ``getattr(uvicorn, ...)``."""
    problems = []
    for where, tree in _trees():
        called = {
            id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)
        }  # same parse as the walk below
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                problems += [
                    f"{where}: import {a.name} as {a.asname}"
                    for a in node.names
                    if a.name.split(".")[0] == "uvicorn" and a.asname
                ]
                problems += [
                    f"{where}: import {a.name}" for a in node.names if a.name.startswith("uvicorn.")
                ]
            elif (
                isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "uvicorn"
            ):
                problems += [
                    f"{where}: from {node.module} import {a.name}"
                    for a in node.names
                    if a.name in _SERVING_NAMES | {"config", "server", "main"}
                ]
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "uvicorn"
                and (
                    node.attr in ("Server", "main", "config", "server")
                    or (node.attr in ("run", "Config") and id(node) not in called)
                )
            ):
                problems.append(f"{where}: uvicorn.{node.attr}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "uvicorn"
            ):
                problems.append(f"{where}: getattr(uvicorn, ...)")
    assert not problems, problems


def test_every_uvicorn_entry_point_pins_the_asyncio_loop():
    calls = _uvicorn_run_calls()
    assert calls, (
        "no uvicorn.run(...) found: the server entry point moved and this test must follow it"
    )
    for where, call in calls:
        assert not any(kw.arg is None for kw in call.keywords), (
            f"{where}: **kwargs could carry loop='auto'"
        )
        loop = next((kw.value for kw in call.keywords if kw.arg == "loop"), None)
        assert loop is not None, (
            f"{where}: {ast.unparse(call.func)}(...) without loop= picks uvloop ('auto')"
        )
        if isinstance(loop, ast.Name):
            assert where == "src/api/main.py" and loop.id == "SERVER_EVENT_LOOP", (
                f"{where}: loop= must be the asyncio loop"
            )
        else:
            assert isinstance(loop, ast.Constant) and loop.value == "asyncio", (
                f"{where}: loop= must be the asyncio loop"
            )
    assert main_mod.SERVER_EVENT_LOOP == "asyncio"


def _loop_from_config(loop_setting: str) -> asyncio.AbstractEventLoop:
    from uvicorn.config import Config

    config = Config("src.api.main:app", loop=loop_setting)
    factory = getattr(config, "get_loop_factory", None)
    if factory is not None:
        made = factory()
        return made() if made is not None else asyncio.new_event_loop()
    raise AssertionError(
        "this uvicorn has no Config.get_loop_factory; the loop check must follow its API"
    )


def test_the_configured_loop_is_not_uvloop():
    loop = _loop_from_config(main_mod.SERVER_EVENT_LOOP)
    try:
        assert main_mod._event_loop_is_stdlib(loop), type(loop)
    finally:
        loop.close()
        asyncio.set_event_loop_policy(None)


#: Where core's ``uvicorn[standard]`` installs uvloop: its own marker (``sys_platform != 'win32'`` and CPython, not cygwin). There the
#: tests below import it outright, so a core install without it FAILS rather than skips (a skip would be green in every CI job).
_UVLOOP_INSTALLED_BY_CORE = (
    sys.platform not in ("win32", "cygwin") and sys.implementation.name == "cpython"
)
_needs_uvloop = pytest.mark.skipif(
    not _UVLOOP_INSTALLED_BY_CORE, reason="uvicorn[standard] installs no uvloop on this platform"
)


@_needs_uvloop
def test_auto_would_have_picked_uvloop():
    """The control: where uvloop is installed (it is, through uvicorn[standard]), "auto" chooses it and the detector says so."""
    import uvloop  # noqa: F401 - present by construction here; an ImportError is the failure this test exists to report

    loop = _loop_from_config("auto")
    try:
        assert not main_mod._event_loop_is_stdlib(loop), type(loop)
    finally:
        loop.close()
        asyncio.set_event_loop_policy(None)


@pytest.mark.parametrize(
    "host",
    [
        "example.com",
        pytest.param(
            "192.0.2.1",
            marks=pytest.mark.skipif(
                sys.platform == "win32",
                reason="the proactor loop connects an IP literal through ConnectEx, past the guard: a stated SECURITY.md residual",
            ),
        ),
    ],
)
def test_on_the_configured_loop_an_async_connect_meets_the_airplane_guard(host):
    """End to end on the loop the server is pinned to: with airplane mode engaged an async connect is refused by the socket guard,
    a name at the patched getaddrinfo and an IP literal (which skips the lookup) at the patched connect. The real calls are replaced
    by tripwires, so a broken guard fails here instead of reaching the network."""

    def _tripwire(*a, **k):
        raise AssertionError("the real socket call was reached with airplane mode engaged")

    # The loop is made FIRST: nothing that can raise may sit between the swap below and the try that undoes it.
    loop = _loop_from_config(main_mod.SERVER_EVENT_LOOP)
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard(), (
        "the guard is disabled here (OO_AIRPLANE_SOCKET_GUARD=0?); this test would egress"
    )
    # Saved and put back by hand BEFORE the uninstall below, which writes these names back onto ``socket`` (monkeypatch would undo
    # them only after it, leaving the tripwires installed as the "real" calls).
    real_getaddrinfo, real_connect = ap._orig_getaddrinfo, ap._orig_connect
    ap._orig_getaddrinfo, ap._orig_connect = _tripwire, _tripwire
    try:
        activate_kill_switch()
        with pytest.raises(ap.AirplaneModeError):
            loop.run_until_complete(asyncio.open_connection(host, 80))
    finally:
        ap._orig_getaddrinfo, ap._orig_connect = real_getaddrinfo, real_connect
        clear_kill_switch()
        loop.close()
        asyncio.set_event_loop_policy(None)
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


def _run_lifespan_on(loop: asyncio.AbstractEventLoop) -> None:
    async def enter() -> None:
        async with main_mod.lifespan(main_mod.app):
            pass

    loop.run_until_complete(enter())


@_needs_uvloop
def test_lifespan_refuses_to_start_on_uvloop(caplog):
    """A start that ends up on uvloop (a bare ``python -m uvicorn``) fails closed before the lifespan does anything else."""
    import uvloop  # noqa: F401 - see test_auto_would_have_picked_uvloop

    loop = _loop_from_config("auto")
    try:
        assert not main_mod._event_loop_is_stdlib(loop)
        with caplog.at_level("ERROR"), pytest.raises(RuntimeError) as refused:
            _run_lifespan_on(loop)
    finally:
        loop.close()
        asyncio.set_event_loop_policy(None)
    assert str(refused.value) == main_mod.SERVER_EVENT_LOOP_REFUSAL
    assert (
        "--loop asyncio" in main_mod.SERVER_EVENT_LOOP_REFUSAL
        and "launcher" in main_mod.SERVER_EVENT_LOOP_REFUSAL
    )
    assert main_mod.SERVER_EVENT_LOOP_REFUSAL in caplog.text


def test_any_non_stdlib_loop_is_refused():
    """The rule is an allowlist (the stdlib's loops), not a uvloop denylist: a loop class from anywhere else is refused too."""

    class ForeignLoop(asyncio.SelectorEventLoop):
        pass

    ForeignLoop.__module__ = "someloop.impl"
    loop = ForeignLoop()
    try:
        with pytest.raises(RuntimeError, match="refuses to start on this event loop"):
            _run_lifespan_on(loop)
    finally:
        loop.close()


@pytest.mark.parametrize(
    ("module", "name", "stdlib"),
    [
        ("asyncio.unix_events", "_UnixSelectorEventLoop", True),
        ("asyncio.windows_events", "ProactorEventLoop", True),
        ("uvloop", "Loop", False),
        (
            "notasyncio.x",
            "SelectorEventLoop",
            False,
        ),  # a substring match on the module, or on "selector", would let this pass
        ("asyncio_compat", "SelectorEventLoop", False),
        ("someloop.asyncio", "Loop", False),
    ],
)
def test_the_detector_is_an_exact_module_allowlist(module, name, stdlib):
    fake = type(name, (), {"__module__": module})()
    assert main_mod._event_loop_is_stdlib(fake) is stdlib


def test_the_refusal_check_runs_before_any_startup_work():
    """Nothing of the lifespan's own work happens on a refused loop: the check is its first statement."""
    import inspect

    body = inspect.getsource(main_mod.lifespan)
    tree = ast.parse(textwrap.dedent(body))
    fn = tree.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    stmts = [
        s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    assert isinstance(stmts[0], ast.Import) and isinstance(stmts[1], ast.If), (
        "the loop check must open the lifespan"
    )
    assert "_event_loop_is_stdlib" in ast.unparse(stmts[1].test)
