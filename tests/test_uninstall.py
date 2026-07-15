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
    (home / ".local" / "share" / "applications" / f"{U.APP_NAME}.desktop").write_text("x", encoding="utf-8")
    (home / "Desktop" / f"{U.APP_NAME}-desk.desktop").write_text("x", encoding="utf-8")
    app = tmp_path / "app"
    (app / ".venv").mkdir(parents=True)
    (app / "install.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
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


# --- modes (2026-06-17: "data dies only in Secure") ------------------------- #

def test_plan_modes_carry_folder_and_data_targets(tmp_path, monkeypatch):
    app = _fake_install(tmp_path, monkeypatch)
    minimal = U.plan_uninstall(app)
    assert minimal["mode"] == "minimal"
    assert minimal["app_folder"] is None and minimal["wipe_data_dir"] is None

    full = U.plan_uninstall(app, remove_folder=True)
    assert full["mode"] == "full"
    assert full["app_folder"] == str(app) and full["wipe_data_dir"] is None  # data kept

    secure = U.plan_uninstall(app, remove_folder=True, wipe_data=True)
    assert secure["mode"] == "secure" and secure["app_folder"] == str(app)
    # wipe_data_dir is only set when the data dir actually exists
    assert ("wipe_data_dir" in secure) and ("audit_log" in secure)


def test_plan_reports_columnar_store_override_only_when_it_differs(tmp_path, monkeypatch):
    """The DuckDB analytics cache can live outside the data dir (OO_COLUMNAR_DIR); a
    secure-mode plan must report it separately so the watcher can wipe it too (audit
    OO-02 follow-up: the watcher previously only ever wiped the data dir itself)."""
    app = _fake_install(tmp_path, monkeypatch)
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr("src.paths.data_dir", lambda: data)

    # Same location as the data dir -> not reported (nothing extra to wipe).
    monkeypatch.setattr("src.analytics.columnar._store_dir", lambda: data)
    same = U.plan_uninstall(app, wipe_data=True)
    assert same["wipe_store_dir"] is None

    # A distinct OO_COLUMNAR_DIR override -> reported, and only when it exists on disk.
    store = tmp_path / "columnar-cache"
    monkeypatch.setattr("src.analytics.columnar._store_dir", lambda: store)
    missing = U.plan_uninstall(app, wipe_data=True)
    assert missing["wipe_store_dir"] is None  # doesn't exist yet
    store.mkdir()
    present = U.plan_uninstall(app, wipe_data=True)
    assert present["wipe_store_dir"] == str(store)

    # Never reported outside wipe_data mode (nothing is being destroyed).
    not_wiping = U.plan_uninstall(app, wipe_data=False)
    assert not_wiping["wipe_store_dir"] is None


@pytest.mark.skipif(sys.platform == "win32", reason="watcher uses POSIX detach + shells")
def test_watcher_wipes_columnar_store_override(tmp_path):
    """The watcher must head-wipe the DuckDB cache files under a store_dir override
    without rmtree-ing that externally-configured directory (it may not be ours alone)."""
    import json
    import subprocess

    data = tmp_path / "data"; data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    store = tmp_path / "columnar-cache"; store.mkdir()
    (store / "analytics.duckdb").write_bytes(b"D" * 8192)
    (store / "other_unrelated_file.txt").write_text("keep me", encoding="utf-8")
    audit = tmp_path / "audit.log"
    payload = {
        "files": [], "venv": None, "app_folder": None,
        "wipe_data_dir": str(data), "wipe_store_dir": str(store), "audit_log": str(audit),
    }
    dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
    subprocess.run([sys.executable, "-c", U._WATCHER_SRC, str(dead.pid), json.dumps(payload)],
                   timeout=30, check=True)
    assert not data.exists()
    assert store.exists(), "an externally-configured store dir must not be rmtree'd wholesale"
    assert not (store / "analytics.duckdb").exists()
    assert (store / "other_unrelated_file.txt").exists(), "unrelated files must survive"
    assert "columnar store" in audit.read_text(encoding="utf-8")


def test_secure_request_reports_data_not_kept(tmp_path, monkeypatch):
    app = _fake_install(tmp_path, monkeypatch)
    # give the plan a real data dir to wipe
    data = tmp_path / "data"; data.mkdir(); (data / "corpus.db").write_text("x", encoding="utf-8")
    monkeypatch.setattr("src.paths.data_dir", lambda: data)
    captured = {}
    res = U.request_uninstall(confirm=True, remove_folder=True, wipe_data=True, src_dir=app,
                              _spawn=lambda plan, pid: captured.update(plan=plan),
                              _arm_shutdown=lambda: None)
    assert res["scheduled"] is True and res["data_kept"] is False
    assert res["overwrite_limit"] and "SSD" in res["overwrite_limit"]  # honest limit present
    assert captured["plan"]["wipe_data_dir"] == str(data)
    assert (data / "corpus.db").exists()  # the call itself deleted nothing (watcher mocked)


@pytest.mark.skipif(sys.platform == "win32", reason="watcher uses POSIX detach + shells")
def test_watcher_removes_exactly_the_planned_paths(tmp_path):
    """Run the real detached-watcher source on a sandbox tree (system python) and prove
    it removes venv + launchers + (opt) data dir + app folder, and writes an audit log."""
    import json
    import subprocess

    app = tmp_path / "app"; (app / ".venv").mkdir(parents=True)
    (app / "keepme.txt").write_text("x", encoding="utf-8")
    data = tmp_path / "data"; data.mkdir(); (data / "corpus.db").write_bytes(b"secret-bytes")
    launcher = tmp_path / "x.desktop"; launcher.write_text("x", encoding="utf-8")
    audit = tmp_path / "uninstall.log"
    payload = {
        "files": [str(launcher)], "venv": str(app / ".venv"),
        "wipe_data_dir": str(data), "app_folder": str(app), "audit_log": str(audit),
    }
    # a guaranteed-dead PID so the watcher's "wait for server exit" returns at once
    dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
    subprocess.run([sys.executable, "-c", U._WATCHER_SRC, str(dead.pid), json.dumps(payload)],
                   timeout=30, check=True)
    assert not launcher.exists()
    assert not (app / ".venv").exists()
    assert not data.exists()            # data wiped (secure)
    assert not app.exists()             # app folder removed
    assert audit.exists() and "uninstall watcher done" in audit.read_text(encoding="utf-8")


def test_close_db_quietly_disposes_engine(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: called.__setitem__("n", called["n"] + 1))
    U._close_db_quietly()
    assert called["n"] == 1
    # never raises even if dispose blows up (best-effort shutdown)
    monkeypatch.setattr("src.database.session.dispose_engine",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    U._close_db_quietly()


def test_api_uninstall_plan_preview_deletes_nothing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        r = c.get("/api/safety/uninstall/plan", params={"mode": "secure"})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "secure" and body["remove_folder"] is True and body["wipe_data"] is True
        # unknown mode is rejected
        assert c.get("/api/safety/uninstall/plan", params={"mode": "nope"}).status_code == 400


def test_api_uninstall_unknown_mode_rejected():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        assert c.post("/api/safety/uninstall",
                      json={"confirm": True, "mode": "bogus"}).status_code == 400


def test_api_uninstall_rejects_invalid_passes():
    """Secure uninstall's optional full-overwrite pass count must be validated
    server-side, the same as /api/safety/secure-erase -- parity, not just UI-side
    trust."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        for bad in (0, 2, 4, 100):
            r = c.post("/api/safety/uninstall",
                       json={"confirm": True, "mode": "secure", "passes": bad})
            assert r.status_code == 400


def test_api_uninstall_passes_through_to_request_uninstall(monkeypatch):
    """The chosen pass count actually reaches request_uninstall (and hence the
    watcher's optional free-space scrub) -- Secure uninstall gets the same
    defence-in-depth choice Panic wipe already offers."""
    captured = {}
    monkeypatch.setattr(
        "src.safety.uninstall.request_uninstall",
        lambda **kw: captured.update(kw) or {"scheduled": True, "data_kept": False},
    )
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.post("/api/safety/uninstall",
                  json={"confirm": True, "mode": "secure", "passes": 3})
        assert r.status_code == 200
        assert captured["passes"] == 3
