"""The server runs on the stdlib asyncio loop, never uvloop (R642).

uvicorn[standard] installs uvloop and uvicorn's default ``loop="auto"`` picks it. uvloop resolves and connects in libuv's C code, past
every ``socket`` call the airplane guard patches (src/ingest/airplane.py), so an async client on the server's loop reached a
non-loopback listener with airplane mode engaged (security read B of R639). ``_serve`` therefore pins ``loop="asyncio"``, and a server
started another way says so loudly at boot.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

import src.api.main as main_mod
import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch

_SRC = Path(__file__).resolve().parents[1] / "src"


def _uvicorn_run_calls() -> list[tuple[str, ast.Call]]:
    calls = []
    for py in _SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("run", "Config")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "uvicorn"
            ):
                calls.append((py.relative_to(_SRC.parent).as_posix(), node))
    return calls


def test_every_uvicorn_entry_point_pins_the_asyncio_loop():
    calls = _uvicorn_run_calls()
    assert calls, "no uvicorn.run(...) found: the server entry point moved and this test must follow it"
    for where, call in calls:
        loop = next((kw.value for kw in call.keywords if kw.arg == "loop"), None)
        assert loop is not None, f"{where}: uvicorn.{call.func.attr}(...) without loop= picks uvloop ('auto')"  # type: ignore[attr-defined]
        assert (isinstance(loop, ast.Name) and loop.id == "SERVER_EVENT_LOOP") or (
            isinstance(loop, ast.Constant) and loop.value == "asyncio"
        ), f"{where}: loop= must be the asyncio loop"
    assert main_mod.SERVER_EVENT_LOOP == "asyncio"


def _loop_from_config(loop_setting: str) -> asyncio.AbstractEventLoop:
    from uvicorn.config import Config

    config = Config("src.api.main:app", loop=loop_setting)
    factory = getattr(config, "get_loop_factory", None)
    if factory is not None:
        made = factory()
        return made() if made is not None else asyncio.new_event_loop()
    config.setup_event_loop()  # older uvicorn: sets the policy instead
    return asyncio.new_event_loop()


def test_the_configured_loop_is_not_uvloop():
    loop = _loop_from_config(main_mod.SERVER_EVENT_LOOP)
    try:
        assert not main_mod._event_loop_is_uvloop(loop), type(loop)
    finally:
        loop.close()
        asyncio.set_event_loop_policy(None)


def test_auto_would_have_picked_uvloop():
    """The control: where uvloop is installed (it is, through uvicorn[standard]), "auto" chooses it and the detector says so."""
    pytest.importorskip("uvloop")
    loop = _loop_from_config("auto")
    try:
        assert main_mod._event_loop_is_uvloop(loop), type(loop)
    finally:
        loop.close()
        asyncio.set_event_loop_policy(None)


def test_on_the_configured_loop_an_async_connect_meets_the_airplane_guard():
    """End to end on the loop the server is pinned to: with airplane mode engaged an async connect to a remote name is refused by the
    socket guard (it resolves through the patched getaddrinfo, which refuses before any lookup)."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    ap.install_airplane_socket_guard()
    loop = _loop_from_config(main_mod.SERVER_EVENT_LOOP)
    try:
        activate_kill_switch()
        with pytest.raises(ap.AirplaneModeError):
            loop.run_until_complete(asyncio.open_connection("example.com", 80))
    finally:
        clear_kill_switch()
        loop.close()
        asyncio.set_event_loop_policy(None)
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed
