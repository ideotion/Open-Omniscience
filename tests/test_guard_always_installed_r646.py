"""R646: airplane mode's socket guard is installed whether or not ``OO_NO_SCHEDULER`` is set.

``OO_NO_SCHEDULER=1`` stops the background scheduler. Until R646 it also left the socket guard out at every place the app installs it
(the lifespan, the deferred startup, the unlock), so a headless instance an operator later took offline rested on the per-call refusals
alone. ``OO_AIRPLANE_SOCKET_GUARD=0`` is now the only setting that leaves the guard out. Only the kill switch's ENGAGE at boot stays
gated on ``OO_NO_SCHEDULER``, because a headless or test process manages the switch itself.

No network: the remote target is TEST-NET-1 (192.0.2.1), and the real connect is replaced by a tripwire for the refusal test.
"""

from __future__ import annotations

import ast
import inspect
import socket
import textwrap

import pytest
from fastapi.testclient import TestClient

import src.api.main as main
import src.api.unlock as unlock
import src.ingest.airplane as ap
from src.ingest import activate_kill_switch, clear_kill_switch


@pytest.fixture
def guard_state(monkeypatch):
    """Start from a process in which the guard was never installed, and leave the guard as the test found it."""
    was_installed = ap._installed
    was_armed = ap._airplane_armed
    if was_installed:
        ap.uninstall_airplane_socket_guard()
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    try:
        yield
    finally:
        clear_kill_switch()
        if ap._installed:
            ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap.install_airplane_socket_guard() if was_armed else ap.ensure_connect_guard_installed()


def test_the_lifespan_arms_the_guard_with_the_scheduler_off_and_airplane_mode_refuses(guard_state):
    """Behavioural: the real lifespan under OO_NO_SCHEDULER=1 arms the guard, and with the kill switch engaged a connect to a remote
    address is refused before the real connect is reached."""
    assert not ap.is_armed()
    with TestClient(main.app) as client:
        assert ap.is_armed(), "OO_NO_SCHEDULER=1 left the airplane socket guard out (R646)"
        assert client.get("/unlock").status_code != 503  # the serving gate opens on the lifespan, with no waiver
    reached: list[object] = []
    saved = ap._orig_connect
    ap._orig_connect = lambda self, address: reached.append(address)  # type: ignore[assignment]
    try:
        activate_kill_switch()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(ap.AirplaneModeError):
                s.connect(("192.0.2.1", 80))
        finally:
            s.close()
    finally:
        clear_kill_switch()
        ap._orig_connect = saved  # type: ignore[assignment]
    assert reached == [], "the real connect was reached in airplane mode"


def test_the_opt_out_still_leaves_the_guard_out(guard_state, monkeypatch):
    """OO_AIRPLANE_SOCKET_GUARD=0 is the one switch that leaves it out, with the scheduler off or on."""
    monkeypatch.setenv("OO_AIRPLANE_SOCKET_GUARD", "0")
    with TestClient(main.app):
        assert not ap.is_armed()


def _install_sites(obj: object) -> list[list[str]]:
    """For every call of ``install_airplane_socket_guard`` in ``obj``'s source, the tests of the ``if`` statements that enclose it."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    sites: list[list[str]] = []

    def walk(node: ast.AST, ifs: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and ast.unparse(child.func).endswith("install_airplane_socket_guard"):
                sites.append(list(ifs))
            walk(child, ifs + [ast.unparse(child.test)] if isinstance(child, ast.If) else ifs)

    walk(tree, [])
    return sites


@pytest.mark.parametrize("obj", [main.lifespan, main._run_startup_upkeep, unlock], ids=["lifespan", "deferred startup", "unlock"])
def test_no_install_site_is_gated_on_the_scheduler_flag(obj):
    """Every place the app installs the guard does it outside any OO_NO_SCHEDULER test."""
    sites = _install_sites(obj)
    assert sites, f"{obj} no longer installs the airplane socket guard"
    for ifs in sites:
        assert not any("OO_NO_SCHEDULER" in t for t in ifs), f"{obj} installs the guard under an OO_NO_SCHEDULER test: {ifs}"


def test_the_serving_gate_has_no_scheduler_waiver():
    fn = ast.parse(textwrap.dedent(inspect.getsource(main._serving_preconditions_hold))).body[0]
    assert isinstance(fn, ast.FunctionDef)
    code = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    assert "OO_NO_SCHEDULER" not in "\n".join(ast.unparse(n) for n in code)
