"""Diagnostics tooling fixes from the 2026-11-14 field report (row 74).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each test pins one thing a field bundle said that was not so: an interrupted card section read as a broken card, a counter
deferral read as drift, "installed but not started" beside ``installed: false``, K5/K6 from the previous build, and errors
crowded out of the bundle by one logger's warnings.
"""

from __future__ import annotations

import json
import sqlite3

import src.monitoring.errorlog as errorlog
from src.api import diagnostics_plan as plan
from src.briefing import card_audit
from src.llm import vllm_lifecycle as V
from src.monitoring import integrity


# --------------------------------------------------------------------------- #
# card audit: a section the deadline stopped is not an error in the card
# --------------------------------------------------------------------------- #
def _interrupted():
    raise sqlite3.OperationalError("interrupted")


def test_a_section_stopped_by_an_expired_deadline_says_so(monkeypatch):
    import src.database.maintenance as m

    monkeypatch.setattr(m, "deadline_expired", lambda s: True)
    out = card_audit._safe_section("keywords", _interrupted, session=object())
    assert out["section_ok"] is False
    assert out["stopped_by"] == "statement deadline"
    assert "error" not in out


def test_a_section_that_fails_inside_its_deadline_is_still_an_error(monkeypatch):
    import src.database.maintenance as m

    monkeypatch.setattr(m, "deadline_expired", lambda s: False)
    out = card_audit._safe_section("keywords", _interrupted, session=object())
    assert out["section_ok"] is False
    assert "stopped_by" not in out


# --------------------------------------------------------------------------- #
# corpus integrity: an open counter deferral is not drift
# --------------------------------------------------------------------------- #
def _report(deferred_since):
    return {
        "orphan_keywords": 0,
        "dangling_mentions_missing_article": 0,
        "dangling_mentions_missing_keyword": 0,
        "foreign_key_violations": 0,
        "counter_drift": {"deferred_since": deferred_since, "keywords_with_mention_drift": 40, "keywords_with_article_drift": 12},
    }


def test_counter_drift_counts_when_no_deferral_is_open():
    drift, found, _incomplete = integrity._verdict(_report(None))
    assert drift is True
    assert "counter_drift_mentions" in found


def test_counter_drift_is_not_counted_while_a_deferral_is_open():
    drift, found, incomplete = integrity._verdict(_report("2026-11-14T10:00:00"))
    assert drift is None, "the other checks are clean and the counter ones are not established"
    assert not found
    assert {"counter_drift_mentions", "counter_drift_articles"} <= set(incomplete)


# --------------------------------------------------------------------------- #
# vLLM: "installed but not started" only when it is installed
# --------------------------------------------------------------------------- #
def _free_port(monkeypatch, installed):
    monkeypatch.setattr(V, "is_installed", installed)
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("OO_VLLM_URL", f"http://127.0.0.1:{port}")
    return V.port_occupant(timeout=1.0)


def test_a_free_port_on_a_machine_without_vllm_does_not_say_installed(monkeypatch):
    occ = _free_port(monkeypatch, lambda: False)
    assert occ["state"] == "free"
    assert "not installed" in occ["detail"] and "installed but" not in occ["detail"]


def test_a_free_port_with_vllm_installed_says_not_started(monkeypatch):
    occ = _free_port(monkeypatch, lambda: True)
    assert "installed but not started" in occ["detail"]


def test_an_unreadable_install_state_is_not_guessed(monkeypatch):
    def boom():
        raise RuntimeError("no")

    occ = _free_port(monkeypatch, boom)
    assert "could not be read" in occ["detail"]


# --------------------------------------------------------------------------- #
# the bundle: kpi.json reads what the scans write, so it runs after them
# --------------------------------------------------------------------------- #
def test_kpi_runs_after_the_scans():
    records = [("runtime.json", 1), ("kpi.json", 2), ("errors.json", 3)]
    rest, tail = plan.after_scans(records)
    assert [m[0] for m in rest] == ["runtime.json", "errors.json"]
    assert [m[0] for m in tail] == ["kpi.json"]


# --------------------------------------------------------------------------- #
# the error journal: warnings cannot crowd an error out of the bundle
# --------------------------------------------------------------------------- #
def _journal(monkeypatch, tmp_path, records):
    path = tmp_path / "app_errors.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    monkeypatch.setattr(errorlog, "_log_path", lambda: path)


def test_older_errors_carries_the_errors_the_newest_window_misses(monkeypatch, tmp_path):
    old = [{"at": f"2026-11-14T0{i}:00:00", "level": "ERROR", "logger": "src.db", "message": f"e{i}"} for i in range(3)]
    noise = [{"at": "2026-11-14T10:00:00", "level": "WARNING", "logger": "src.wiki", "message": "w"}] * 10
    _journal(monkeypatch, tmp_path, old + noise)
    out = errorlog.older_errors(skip_newest=10, limit=2)
    assert out["found"] == 3
    assert [r["message"] for r in out["records"]] == ["e1", "e2"], "the newest of the older errors, oldest first"
    assert errorlog.older_errors(skip_newest=13)["found"] == 0, "nothing older than the window"


def test_the_summary_names_the_logger_that_fills_the_journal(monkeypatch, tmp_path):
    noise = [{"at": "2026-11-14T10:00:00", "level": "WARNING", "logger": "src.wiki", "message": "w"}] * 5
    _journal(monkeypatch, tmp_path, [*noise, {"at": "2026-11-14T11:00:00", "level": "ERROR", "logger": "src.db", "message": "e"}])
    rows = errorlog.summary()["logger_breakdown"]["rows"]
    assert rows[0] == {"logger": "src.wiki", "level": "WARNING", "count": 5}
    assert {"logger": "src.db", "level": "ERROR", "count": 1} in rows


def test_an_unreadable_deferral_marker_does_not_hide_measured_drift():
    drift, found, _incomplete = integrity._verdict(_report("unknown"))
    assert drift is True and "counter_drift_mentions" in found


def test_the_deferral_marker_is_read_before_the_deadline_opens():
    # Read after the drift query, an expired deadline made the read fail and answer "unknown".
    import inspect

    src = inspect.getsource(integrity.corpus_integrity)
    assert src.index("deferral_open_since(session)") < src.index("with statement_deadline(session):")
