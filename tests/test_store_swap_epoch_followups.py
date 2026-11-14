"""Lane E follow-ups (a) and (d): a settings save made from state read in the old file never lands in the file that replaced it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

(a) The panic wipe and the repair swap move the store's swap epoch BEFORE they replace the file, not only after, so a save checked
in between (the bulk queue's, made with ``expect_swap``) is refused rather than written into the new file.
(d) A save that waits behind a restore's ``hold_writes`` while the epoch moves is refused with nothing written, once the hold ends.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from src.config import kv_store
from tests.test_kv_store_write_hold import _reset_hold_state
from tests.test_kv_store_write_hold import store as _hold_store  # noqa: F401 - the fixture, re-exported

store = _hold_store

_ROOT = Path(__file__).resolve().parents[1]


def test_the_panic_wipe_moves_the_swap_epoch_before_it_erases(monkeypatch):
    seen: list[int] = []
    before = kv_store.kv_swap_epoch()

    def _erase(**_kw):
        seen.append(kv_store.kv_swap_epoch())
        return {"files_seen": 0, "files_wiped": 0}

    monkeypatch.setattr("src.safety.crypto_erase.quick_crypto_erase", _erase)
    monkeypatch.setattr("src.ingest.activate_kill_switch", lambda *a, **k: None)
    from src.safety.panic import panic_wipe

    panic_wipe(confirm=True)
    assert seen and seen[0] > before, "the wipe ran before the store's swap epoch moved"
    assert kv_store.kv_swap_epoch() > seen[0], "the epoch must move again after the wipe"


def test_the_repair_swap_moves_the_swap_epoch_before_the_swap():
    src = (_ROOT / "src" / "database" / "repair.py").read_text(encoding="utf-8")
    swap = src.index("swap_in_corpus(finished, target, check=written_to_since)")
    before = src.rfind("kv_invalidate()", 0, swap)
    assert before != -1 and src.rfind("def ", before, swap) == -1, "repair.py must call kv_invalidate() before its swap"
    assert src.find("kv_invalidate()", swap) != -1, "and again after it"


def test_a_save_waiting_behind_a_hold_while_the_epoch_moves_is_refused_and_writes_nothing(store, monkeypatch):
    monkeypatch.setattr(kv_store, "KV_WRITE_WAIT_S", 10.0)
    epoch = kv_store.kv_swap_epoch()
    out: dict = {}
    entered = threading.Event()
    release = threading.Event()

    def _holder() -> None:
        with kv_store.hold_writes(5.0):
            entered.set()
            assert release.wait(10)
            kv_store.kv_invalidate()  # the swap, inside the hold

    def _saver() -> None:
        try:
            kv_store.kv_set_json("followup.d", {"v": 1}, expect_swap=epoch)
            out["saved"] = True
        except kv_store.KvSwapped:
            out["refused"] = True
        except Exception as exc:  # noqa: BLE001 - recorded by type for the assertion below
            out["other"] = type(exc).__name__

    h = threading.Thread(target=_holder)
    h.start()
    assert entered.wait(5)
    s = threading.Thread(target=_saver)
    s.start()
    time.sleep(0.3)
    assert s.is_alive(), "the save did not wait behind the hold"
    release.set()
    h.join(10)
    s.join(10)
    assert out == {"refused": True}, out
    con = sqlite3.connect(store)
    try:
        assert con.execute("SELECT COUNT(*) FROM app_state WHERE key = 'followup.d'").fetchone()[0] == 0
    finally:
        con.close()
    _reset_hold_state()


def test_a_save_with_no_swap_since_its_read_still_lands(store):
    epoch = kv_store.kv_swap_epoch()
    kv_store.kv_set_json("followup.d", {"v": 2}, expect_swap=epoch)
    assert kv_store.kv_get_json("followup.d") == {"v": 2}


def test_the_old_reindex_route_stands_back_while_the_backlog_job_runs(monkeypatch):
    """Lane E follow-up (e): /api/insights/reindex never drains the rows the backlog job is draining."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.jobs import insights_backlog as ib

    called: list[int] = []
    monkeypatch.setattr("src.analytics.store.backfill_corpus", lambda *a, **k: called.append(1) or {"indexed": 1})
    monkeypatch.setattr(ib._JOB, "status", lambda: {"running": True})
    client = TestClient(app)
    body = client.post("/api/insights/reindex?limit=5").json()
    assert body["indexed"] == 0 and body["busy"] == ib.KIND, body
    assert called == [], "the page drain ran beside the backlog job"
