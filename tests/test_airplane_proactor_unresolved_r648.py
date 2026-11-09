"""R648: on Windows, a proactor class that cannot be resolved makes the guard refuse to ARM, never skip the patch in silence.

R643 patches ``asyncio.windows_events.IocpProactor.connect``/``.sendto``. If a future Python renamed the class, dropped a method or the
module failed to import, the guard used to install without those points and arm anyway: airplane mode would look armed with a known
hole in it. It now logs the fixed refusal at error level and stays unarmed, so the serving gate (R644) answers 503. Tested off
Windows by standing in a win32 ``sys`` for the module and by resolving stand-in modules.
"""

from __future__ import annotations

import logging
import types

import src.ingest.airplane as ap


class _Proactor:
    def connect(self, conn, address):
        return None

    def sendto(self, conn, buf, flags=0, addr=None):
        return None


def test_the_class_resolves_only_with_both_entry_points():
    assert ap._resolve_proactor(types.SimpleNamespace(IocpProactor=_Proactor)) is _Proactor
    assert ap._resolve_proactor(types.SimpleNamespace(IocpProactorV2=_Proactor)) is None  # renamed
    assert ap._resolve_proactor(types.SimpleNamespace(IocpProactor=type("P", (), {"connect": _Proactor.connect}))) is None
    assert ap._resolve_proactor(types.SimpleNamespace(IocpProactor=type("P", (), {"sendto": _Proactor.sendto}))) is None
    assert ap._resolve_proactor(None) is None  # the module failed to import


def test_on_windows_an_unresolved_proactor_refuses_to_arm(monkeypatch, caplog):
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    ap.uninstall_airplane_socket_guard()
    monkeypatch.setattr(ap, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ap, "_orig_proactor_connect", None)
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    try:
        with caplog.at_level(logging.ERROR, logger=ap.__name__):
            assert ap.install_airplane_socket_guard() is False
        assert not ap._airplane_armed, "the guard armed with the proactor unguarded"
        assert not ap.is_installed()
        assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [ap.PROACTOR_UNRESOLVED_REFUSAL]
    finally:
        monkeypatch.undo()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


def test_off_windows_a_missing_class_is_expected_and_arms(monkeypatch):
    """Elsewhere the class does not exist and there is no proactor loop to guard: the guard arms as before."""
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    monkeypatch.setattr(ap, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setattr(ap, "_orig_proactor_connect", None)
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    try:
        assert ap.install_airplane_socket_guard() is True
        assert ap._airplane_armed
    finally:
        monkeypatch.undo()
        if not was_installed:
            ap.uninstall_airplane_socket_guard()
        ap._airplane_armed = was_armed


def test_on_windows_a_resolved_proactor_arms(monkeypatch):
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    monkeypatch.setattr(ap, "sys", types.SimpleNamespace(platform="win32"))
    monkeypatch.setattr(ap, "_orig_proactor_connect", _Proactor.connect)
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    try:
        assert ap._proactor_unresolved() is False
    finally:
        monkeypatch.undo()
        ap._airplane_armed = was_armed
        if was_installed and not ap.is_installed():
            ap._install_patches()
