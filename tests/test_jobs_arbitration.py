"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

T9 — the visible-jobs view + download arbitration. The dump manager gains a
REAL, reorderable single-download queue (the fr-before-en acceptance case);
/api/jobs aggregates live state from the owning systems (no shadow store);
cancel routes to the owners with the Stop-button semantics stated honestly.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient


class _SlowResp:
    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def raise_for_status(self):  # noqa: D102 - test double
        pass

    def iter_content(self, _chunk):
        for _ in range(3):
            self._gate.wait(5)
            yield b"0123456789"


@pytest.fixture()
def slow_manager(tmp_path):
    from src.wiki.dumps import DumpDownloadManager

    gate = threading.Event()
    mgr = DumpDownloadManager(base_dir=tmp_path, http_get=lambda url, headers: _SlowResp(gate))
    return mgr, gate


def test_second_dump_queues_instead_of_competing(slow_manager):
    mgr, gate = slow_manager
    first = mgr.start("en")
    for _ in range(50):  # wait until the worker marks it downloading
        if mgr.list() and mgr.list()[0]["status"] == "downloading":
            break
        time.sleep(0.02)
    second = mgr.start("fr")
    third = mgr.start("de")
    assert second["status"] == "queued" and third["status"] == "queued"
    assert mgr.queue_order() == ["fr:pages-articles", "de:pages-articles"]
    assert first["key"] == "en:pages-articles"

    # THE acceptance case: put the small fr... actually reorder de before fr.
    new_order = mgr.reorder(["de:pages-articles", "fr:pages-articles"])
    assert new_order == ["de:pages-articles", "de:pages-articles".replace("de", "fr")]

    gate.set()  # let the en download finish -> the pump starts de next
    for _ in range(100):
        statuses = {e["key"]: e["status"] for e in mgr.list()}
        if statuses.get("en:pages-articles") == "done" and statuses.get(
            "de:pages-articles"
        ) in ("downloading", "done"):
            break
        time.sleep(0.02)
    statuses = {e["key"]: e["status"] for e in mgr.list()}
    assert statuses["en:pages-articles"] == "done"
    assert statuses["de:pages-articles"] in ("downloading", "done"), (
        "the REORDERED head of the queue must start next"
    )


def test_pausing_a_queued_dump_removes_it_from_the_order(slow_manager):
    mgr, gate = slow_manager
    mgr.start("en")
    for _ in range(50):
        if mgr.list() and mgr.list()[0]["status"] == "downloading":
            break
        time.sleep(0.02)
    mgr.start("fr")
    assert mgr.queue_order() == ["fr:pages-articles"]
    assert mgr.pause("fr:pages-articles") is True
    assert mgr.queue_order() == []
    statuses = {e["key"]: e["status"] for e in mgr.list()}
    assert statuses["fr:pages-articles"] == "paused"
    gate.set()


def test_queue_order_survives_a_reload(slow_manager, tmp_path):
    from src.wiki.dumps import DumpDownloadManager

    mgr, gate = slow_manager
    mgr.start("en")
    for _ in range(50):
        if mgr.list() and mgr.list()[0]["status"] == "downloading":
            break
        time.sleep(0.02)
    mgr.start("fr")
    mgr.start("de")
    mgr.reorder(["de:pages-articles", "fr:pages-articles"])
    reloaded = DumpDownloadManager(base_dir=tmp_path, http_get=lambda u, h: None)
    assert reloaded.queue_order() == ["de:pages-articles", "fr:pages-articles"]
    gate.set()


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_jobs_view_aggregates_dumps_with_queue_positions(client, monkeypatch, tmp_path):
    from src.wiki import dumps as dumps_mod
    from src.wiki.dumps import DumpDownloadManager

    gate = threading.Event()
    mgr = DumpDownloadManager(base_dir=tmp_path, http_get=lambda url, headers: _SlowResp(gate))
    monkeypatch.setattr(dumps_mod, "_manager", mgr, raising=False)
    monkeypatch.setattr(dumps_mod, "get_manager", lambda: mgr)
    mgr.start("en")
    for _ in range(50):
        if mgr.list() and mgr.list()[0]["status"] == "downloading":
            break
        time.sleep(0.02)
    mgr.start("fr")
    body = client.get("/api/jobs").json()
    assert body["network_busy"] is True
    # PARALLEL ACROSS KINDS: a downloading dump must NOT trigger the
    # arbitration ask -- collection writes the DB, the dump writes a file.
    assert body["db_writers_busy"] is False
    assert body["busy_with"] == []
    by_id = {j["id"]: j for j in body["jobs"]}
    assert by_id["dump:en:pages-articles"]["state"] == "running"
    fr = by_id["dump:fr:pages-articles"]
    assert fr["state"] == "queued" and fr["queue_position"] == 1
    assert "reorder" in fr["actions"]
    assert "no shadow state" in body["method"]

    # Reorder through the API (the acceptance path end-to-end).
    mgr.start("de")
    r = client.post("/api/jobs/dumps/reorder",
                    json={"keys": ["de:pages-articles", "fr:pages-articles"]})
    assert r.json()["queue_order"] == ["de:pages-articles", "fr:pages-articles"]

    # Cancel (pause) the queued fr through the jobs route.
    r = client.post("/api/jobs/dump:fr:pages-articles/cancel")
    assert r.status_code == 200 and "resumable" in r.json()["detail"]
    gate.set()


def test_cancel_collect_states_the_kill_switch_honestly(client):
    from src.ingest import clear_kill_switch
    from src.scheduler import runner as runner_mod

    class _FakeSched:
        def status(self):
            return {"running": True, "active": True}

        def stop(self):
            return True

    try:
        orig = runner_mod.get_scheduler
        runner_mod.get_scheduler = lambda: _FakeSched()
        try:
            body = client.post("/api/jobs/collect:current/cancel").json()
            assert body["online"] is False, "stopping collection must engage the kill switch"
            assert "kill switch" in body["detail"]
        finally:
            runner_mod.get_scheduler = orig
    finally:
        clear_kill_switch()
