"""Tests for the GUI uninstall service (no real deletion or shutdown is executed).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import sys

import pytest

import src.safety.uninstall as U


def _fake_install(tmp_path, monkeypatch):
    """A throwaway 'installation': fake HOME with launchers + an app dir with a .venv."""
    home = tmp_path / "home"
    (home / ".local" / "share" / "applications").mkdir(parents=True)
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(U, "_desktop_dir", lambda: home / "Desktop")
    (home / ".local" / "share" / "applications" / f"{U.APP_NAME}.desktop").write_text("x")
    (home / "Desktop" / f"{U.APP_NAME}-desk.desktop").write_text("x")
    app = tmp_path / "app"
    (app / ".venv").mkdir(parents=True)
    (app / "install.sh").write_text("#!/usr/bin/env bash\n")
    return app


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="uninstall discovers XDG .desktop launchers (Linux/macOS); install.sh "
    "is not a Windows install path",
)
def test_plan_discovers_venv_and_launchers_but_never_data(tmp_path, monkeypatch):
    app = _fake_install(tmp_path, monkeypatch)
    plan = U.plan_uninstall(app)
    assert plan["removable"] is True
    assert plan["venv"].endswith(".venv")
    assert any("open-omniscience.desktop" in f for f in plan["launchers"])
    assert any("open-omniscience-desk.desktop" in f for f in plan["launchers"])
    assert plan["install_script"].endswith("install.sh")
    # data dir is reported for honesty but is NOT a removal target
    assert "data_dir" in plan
    assert plan["data_dir"] not in plan["launchers"]
    assert plan["data_dir"] != plan["venv"]


def test_plan_empty_install_is_not_removable(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".local" / "share" / "applications").mkdir(parents=True)
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(U, "_desktop_dir", lambda: home / "Desktop")
    plan = U.plan_uninstall(tmp_path / "nope")
    assert plan["removable"] is False and plan["venv"] is None and plan["launchers"] == []


def test_request_requires_confirm(tmp_path, monkeypatch):
    app = _fake_install(tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        U.request_uninstall(confirm=False, src_dir=app,
                            _spawn=lambda *a: None, _arm_shutdown=lambda: None)


def test_request_schedules_but_deletes_nothing_in_process(tmp_path, monkeypatch):
    app = _fake_install(tmp_path, monkeypatch)
    calls = {}

    def fake_spawn(plan, pid):
        calls["plan"], calls["pid"] = plan, pid

    def fake_arm():
        calls["armed"] = True

    res = U.request_uninstall(confirm=True, src_dir=app,
                              _spawn=fake_spawn, _arm_shutdown=fake_arm)
    assert res["scheduled"] is True and res["data_kept"] is True
    assert calls["pid"] == os.getpid()              # watcher is told to wait for THIS server
    assert calls["plan"]["venv"].endswith(".venv")
    assert calls["armed"] is True
    # the call itself deleted nothing — removal is the (mocked) watcher's job
    assert (app / ".venv").exists()


def test_request_noop_when_nothing_to_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.setattr(U, "_desktop_dir", lambda: tmp_path / "empty-home" / "Desktop")
    spawned = []
    res = U.request_uninstall(confirm=True, src_dir=tmp_path / "nope",
                              _spawn=lambda *a: spawned.append(a), _arm_shutdown=lambda: spawned.append("arm"))
    assert res["scheduled"] is False
    assert spawned == []                            # never spawn/stop when there's nothing to do


def test_api_uninstall_requires_confirm():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        assert c.post("/api/safety/uninstall", json={"confirm": False}).status_code == 400


def test_api_uninstall_confirm_calls_service(monkeypatch):
    # Guard the real destructive path: stub the service so the test process is never
    # signalled and nothing is spawned/deleted.
    monkeypatch.setattr("src.safety.uninstall.request_uninstall",
                        lambda **kw: {"scheduled": True, "data_kept": True, "stub": True})
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.post("/api/safety/uninstall", json={"confirm": True})
        assert r.status_code == 200 and r.json()["scheduled"] is True
