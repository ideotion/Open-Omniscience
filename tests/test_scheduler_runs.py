"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Tests for the scheduler run log + opt-in delta drop-folder (0.0.8 part 2,
WP3 / RM-06): one auditable JSONL line per run (success AND failure), the
delta export writes the envelope file only when configured, and the
export_dir setting round-trips with off-as-default.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from src.scheduler.runlog import export_delta, recent_runs, record_run
from src.scheduler.runner import BackgroundScheduler
from src.scheduler.settings import SchedulerSettings


def test_record_and_read_runs_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    record_run({"started_at": "t0", "ok": True, "result": {"n": 1}})
    record_run({"started_at": "t1", "ok": False, "error": "boom"})
    runs = recent_runs(limit=10)
    assert [r["started_at"] for r in runs] == ["t1", "t0"]  # newest first
    assert runs[0]["ok"] is False and "boom" in runs[0]["error"]


def test_do_run_records_success_and_failure_lines(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    ok_sched = BackgroundScheduler(
        run_once_fn=lambda: {"tally": 3},
        settings_provider=lambda: SchedulerSettings(mode="rss"),
    )
    ok_sched._do_run()

    def _boom():
        raise RuntimeError("fetch exploded")

    bad_sched = BackgroundScheduler(
        run_once_fn=_boom, settings_provider=lambda: SchedulerSettings(mode="crawl")
    )
    bad_sched._do_run()

    runs = recent_runs(limit=10)
    assert len(runs) == 2
    fail, ok = runs[0], runs[1]
    assert ok["ok"] is True and ok["mode"] == "rss" and ok["result"] == {"tally": 3}
    assert fail["ok"] is False and fail["mode"] == "crawl"
    assert "fetch exploded" in fail["error"]
    assert fail["started_at"] and fail["finished_at"]


def _seed_article(session, *, minutes_ago: int) -> str:
    from src.database.models import Article, Source

    domain = f"sr-{uuid.uuid4().hex[:8]}.example"
    src = Source(name=f"SR {domain}", domain=domain, language="en")
    session.add(src)
    session.flush()
    a = Article(
        url=f"https://{domain}/a",
        canonical_url=f"https://{domain}/a",
        source_id=src.id,
        title="Delta article",
        content="body " * 30,
        language="en",
        hash=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    a.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    session.add(a)
    session.flush()
    return a.hash


def test_export_delta_writes_envelope_with_only_new_articles(tmp_path):
    from src.database.session import SessionLocal, init_db

    init_db()
    s = SessionLocal()
    try:
        old_hash = _seed_article(s, minutes_ago=120)  # old: must NOT be in the delta
        new_hash = _seed_article(s, minutes_ago=1)  # new: must be
        started = datetime.now(UTC) - timedelta(minutes=30)
        out = export_delta(s, started_at=started, export_dir=str(tmp_path / "drop"))
        assert out is not None
        doc = json.loads((tmp_path / "drop" / out.split("/")[-1]).read_text(encoding="utf-8"))
        assert doc["export_schema"] == "oo-export-1"
        assert doc["kind"] == "scheduler-delta"
        # Membership, not global count: the suite shares one hermetic DB, so other
        # tests' fresh articles may also fall inside the window -- that is correct
        # delta behaviour, not noise to assert away.
        hashes = {row["hash"] for row in doc["data"]}
        assert new_hash in hashes and old_hash not in hashes
        assert doc["count"] == len(doc["data"]) >= 1
    finally:
        s.close()


def test_export_delta_returns_none_when_nothing_new(tmp_path):
    from src.database.session import SessionLocal, init_db

    init_db()
    s = SessionLocal()
    try:
        started = datetime.now(UTC) + timedelta(minutes=5)  # in the future: nothing matches
        out = export_delta(s, started_at=started, export_dir=str(tmp_path / "drop2"))
        assert out is None
        assert not (tmp_path / "drop2").exists()  # no folder, no file -- truly off
    finally:
        s.close()


def test_export_dir_setting_defaults_off_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    from src.scheduler.settings import load_settings, save_settings

    assert load_settings().export_dir == ""  # off by default
    s = save_settings({"export_dir": str(tmp_path / "x")})
    assert s.export_dir == str(tmp_path / "x")
    assert load_settings().export_dir == str(tmp_path / "x")
    s = save_settings({"export_dir": ""})
    assert s.export_dir == "" and load_settings().export_dir == ""


def test_runs_api_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    record_run({"started_at": "t0", "ok": True})
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/scheduler/runs?limit=5")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["runs"][0]["started_at"] == "t0"
