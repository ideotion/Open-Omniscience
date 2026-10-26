"""``POST /api/safety/secure-erase`` follows a panic wipe in this process, and runs one at a time (audit A-011).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The route carried only ``confirm: true`` in the body, which the page itself supplies, so a request with no
panic behind it filled the live corpus volume to the brim for nothing. The gate is at the route, not in
``full_secure_erase``, so that function (and the uninstall flow that calls it directly) is untouched.
"""

from __future__ import annotations

import threading

import pytest


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api import safety
    from src.api.main import app

    safety._PANIC_DONE.clear()
    with TestClient(app) as client:
        yield client, safety
    safety._PANIC_DONE.clear()


def _spy(monkeypatch, seen: list):
    import src.safety.crypto_erase as crypto_erase

    def fake(passes=1, **_kw):
        seen.append(passes)
        return {"phase": "free-space-scrub", "passes": passes, "bytes_written": 0, "limit": "x"}

    monkeypatch.setattr(crypto_erase, "full_secure_erase", fake)


def test_a_request_with_no_panic_behind_it_is_refused_and_overwrites_nothing(api, monkeypatch):
    client, _ = api
    seen: list = []
    _spy(monkeypatch, seen)
    r = client.post("/api/safety/secure-erase", json={"confirm": True, "passes": 8})
    assert r.status_code == 400
    assert "panic" in r.json()["detail"]
    assert seen == [], "the overwrite ran with no panic wipe behind it"


def test_confirm_is_still_required(api, monkeypatch):
    client, safety = api
    safety._PANIC_DONE.set()
    seen: list = []
    _spy(monkeypatch, seen)
    assert client.post("/api/safety/secure-erase", json={"confirm": False}).status_code == 400
    assert seen == []


def test_after_a_panic_in_this_process_the_overwrite_runs(api, monkeypatch):
    client, safety = api
    monkeypatch.setattr("src.safety.panic_wipe", lambda **_kw: {"files_seen": 0, "files_wiped": 0})
    seen: list = []
    _spy(monkeypatch, seen)
    assert client.post("/api/safety/panic", json={"confirm": True}).status_code == 200
    assert safety._PANIC_DONE.is_set()
    r = client.post("/api/safety/secure-erase", json={"confirm": True, "passes": 3})
    assert r.status_code == 200 and seen == [3]


def test_a_refused_panic_does_not_open_the_gate(api):
    client, safety = api
    assert client.post("/api/safety/panic", json={"confirm": False}).status_code == 400
    assert not safety._PANIC_DONE.is_set()


def test_a_second_overwrite_while_one_runs_is_refused(api, monkeypatch):
    client, safety = api
    safety._PANIC_DONE.set()
    import src.safety.crypto_erase as crypto_erase

    started, release = threading.Event(), threading.Event()

    def slow(passes=1, **_kw):
        started.set()
        assert release.wait(10)
        return {"phase": "free-space-scrub", "passes": passes, "bytes_written": 0, "limit": "x"}

    monkeypatch.setattr(crypto_erase, "full_secure_erase", slow)
    first: dict = {}
    t = threading.Thread(target=lambda: first.update(r=client.post("/api/safety/secure-erase", json={"confirm": True, "passes": 1})))
    t.start()
    try:
        assert started.wait(10)
        r = client.post("/api/safety/secure-erase", json={"confirm": True, "passes": 1})
        assert r.status_code == 409
    finally:
        release.set()
        t.join(10)
    assert first["r"].status_code == 200
    # the lock is released: a third run goes through
    release.set()
    assert client.post("/api/safety/secure-erase", json={"confirm": True, "passes": 1}).status_code == 200


def test_a_bad_pass_count_still_answers_400_and_releases_the_lock(api):
    client, safety = api
    safety._PANIC_DONE.set()
    assert client.post("/api/safety/secure-erase", json={"confirm": True, "passes": 2}).status_code == 400
    assert safety._ERASE_LOCK.acquire(blocking=False), "the lock was left held by a refused request"
    safety._ERASE_LOCK.release()
