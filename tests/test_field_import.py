"""Row 414: the Field data button's three import files -- numbers only, 200 KB each, no corpus read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.diagnostics import field_import as fi
from src.backup import runlog
from src.monitoring.secret_scrub import holding

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path / "run_logs")
    monkeypatch.setenv("OO_RUN_JOURNAL", "1")
    runlog._CURRENT = None
    yield
    cur = runlog._CURRENT
    if cur is not None:
        cur.end("test-teardown")
    runlog._CURRENT = None


# --- the projection -------------------------------------------------------------------------------------------------


def test_numbers_and_the_apps_own_tokens_pass_and_text_does_not():
    counts: dict[str, int] = {}
    out = fi.projected(
        {
            "seconds": 1936.7,
            "articles": 258903,
            "committed": True,
            "outcome": "ok",
            "engine": "e1-6fd3d4e1cad4a1961f7ed45ea7580142",
            "started_at": "2026-11-15T11:29:35+00:00",
            "reason": "no incoming article is stamped by this engine",
            "died_in_stage": "merge_step:country codes",
            "summary_line": "Breaking news tonight",  # a sentence under a key that is not one of the app's own
            "title": "Election",  # a one-word string under a title key
            "source": "https://example.org/a?b=c",
            "dest": "/home/someone/data/open_omniscience.db",
            "backup": "202610311717_OpenOmniscience_Backup.oo",
            "label": "OOS6",
            "stages": {"merge_step:country codes": 83.7, "side_files_and_custody": 112.9},
            "by_domain": {"example.org": 3, "en": 5},
            "ids": list(range(500)),
            "short": [1, 2, 3],
        },
        counts=counts,
    )
    assert out["seconds"] == 1936.7 and out["articles"] == 258903 and out["committed"] is True
    assert (
        out["outcome"] == "ok"
        and out["engine"].startswith("e1-")
        and out["started_at"].startswith("2026-11-15")
    )
    assert out["reason"] == "no incoming article is stamped by this engine"
    assert out["died_in_stage"] == "merge_step:country codes"
    for k in ("summary_line", "title", "source", "dest", "backup", "label"):
        assert out[k] is None, k
    assert out["stages"] == {"merge_step:country codes": 83.7, "side_files_and_custody": 112.9}
    assert out["by_domain"] == {"en": 5}
    assert out["ids"] == {"len": 500} and out["short"] == [1, 2, 3]
    assert counts["strings"] == 6 and counts["keys"] == 1 and counts["long_lists"] == 1
    text = json.dumps(out)
    for leak in ("example.org", "/home/", "Backup", "OOS6", "Breaking", "Election"):
        assert leak not in text


def test_a_held_passphrase_is_withheld_even_when_it_looks_like_a_token():
    secret = "Corr3ct_Horse_Battery"
    with holding(secret):
        counts: dict[str, int] = {}
        out = fi.projected({"outcome": secret, secret: 1, "ok": "fine"}, counts=counts)
    assert out == {"outcome": None, "ok": "fine"}
    assert counts == {"strings": 1, "keys": 1}
    assert secret not in json.dumps(out)


def test_a_value_that_matches_nothing_is_withheld():
    out = fi.projected({"stage": "x" * 500, "phase": "café", "outcome": b"bytes", "n": object()})
    assert out == {"stage": None, "phase": None, "outcome": None, "n": None}


# --- the size rule --------------------------------------------------------------------------------------------------


def test_the_oldest_entries_are_dropped_until_the_file_fits_and_it_says_so():
    entries = [
        {"i": i, "pad": [i] * 60, "more": {f"k{j}": j for j in range(40)}} for i in range(1000)
    ]
    payload = fi._fi_envelope("t", entries, {})
    data = fi.bounded(payload)
    assert len(data) <= fi.FIELD_IMPORT_MAX_BYTES
    body = json.loads(data)
    assert body["dropped_oldest"] > 0
    assert body["count"] + body["dropped_oldest"] == 1000
    assert body["entries"][0]["i"] == 0  # newest first: the newest is kept


def test_an_entry_too_large_on_its_own_is_replaced_by_its_size():
    big = {"pad": [list(range(60))] * 60}
    body = json.loads(fi.bounded(fi._fi_envelope("t", [big, {"i": 1}], {}), limit=10_000))
    assert body["entries"][0]["too_large"] is True and body["entries"][0]["bytes"] > 5_000
    assert body["entries"][1] == {"i": 1}


# --- the three files ------------------------------------------------------------------------------------------------


def test_the_run_journal_file_keeps_stage_times_and_settings_and_withholds_the_label():
    rl = runlog.begin("restore", label="My backup on /home/someone/x.oo")
    assert rl is not None
    runlog.milestone("knobs", reindex_workers=2, merge_cache_mb=256, exclusive=True)
    with runlog.stage("prepare_staged:validate"):
        pass
    runlog.end("ok")
    body = json.loads(fi.bounded(fi.build_run_journal()))
    assert body["kind"] == "run-journal" and body["count"] == 1
    entry = body["entries"][0]
    assert "prepare_staged:validate" in entry["summary"]["stages"]
    assert entry["milestones"]["knobs"][0]["merge_cache_mb"] == 256
    assert entry["summary"]["outcome"] == "ok"
    text = json.dumps(body)
    assert "/home/someone" not in text and "My backup" not in text


def test_the_import_reports_file_keeps_counts_and_timings(tmp_path):
    from src.backup.import_reports import persist_import_report

    persist_import_report(
        "restore",
        {
            "outcome": "ok",
            "plan": {
                "articles": {"new": 258903, "duplicate": 547},
                "articles_samples": [{"title": "A title", "url": "https://x.y/z"}],
            },
            "timings": {"stages": {"quarantine_scan": 3396.2}, "wall_s": 7465.0},
            "import_run": {
                "id": "imp-20261115T112935Z-476095",
                "label": "/media/usb/backups/OOS-6",
            },
        },
    )
    body = json.loads(fi.bounded(fi.build_import_reports()))
    assert body["count"] == 1
    rep = body["entries"][0]["report"]
    assert rep["plan"]["articles"] == {"new": 258903, "duplicate": 547}
    assert rep["timings"]["stages"]["quarantine_scan"] == 3396.2
    assert rep["import_run"]["id"] == "imp-20261115T112935Z-476095"
    text = json.dumps(body)
    for leak in ("A title", "x.y", "/media/usb", "OOS-6"):
        assert leak not in text


def test_the_drain_status_file_never_counts_the_backlog(monkeypatch):
    from src.api import backup_v2
    from src.backup import merge

    def _no_corpus_read(*_a, **_k):
        raise AssertionError("the field file read the corpus")

    monkeypatch.setattr(merge, "reindex_backlog", _no_corpus_read)
    monkeypatch.setattr(
        backup_v2._REINDEX_RESUME_JOB,
        "status",
        lambda: {
            "state": "done",
            "metrics": {"articles_per_second": 11.64, "rate_by_store_gib": None},
            "backlog": {"x": 1},
        },
    )
    body = json.loads(fi.bounded(fi.build_drain_status()))
    entry = body["entries"][0]
    assert "backlog" not in entry
    assert entry["metrics"]["articles_per_second"] == 11.64
    assert body["backlog"].startswith("not read here")


def test_the_routes_exist_and_answer_within_the_limit():
    from fastapi.testclient import TestClient

    from src.api.diagnostics._base import router

    paths = {getattr(r, "path", "") for r in router.routes}
    for p in (
        "/api/diagnostics/field-run-journal",
        "/api/diagnostics/field-import-reports",
        "/api/diagnostics/field-drain-status",
    ):
        assert p in paths
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    for p in ("/api/diagnostics/field-run-journal", "/api/diagnostics/field-import-reports"):
        r = client.get(p)
        assert r.status_code == 200 and len(r.content) <= fi.FIELD_IMPORT_MAX_BYTES
        assert "attachment" in r.headers["content-disposition"]


# --- the drain's rate against the store's size ----------------------------------------------------------------------


def test_the_drain_rate_is_bucketed_by_the_store_size_when_each_interval_began():
    from src.api import backup_v2 as b

    gib = 1 << 30
    t = {"now": 0.0}
    size = {"bytes": int(1.5 * gib)}
    run: dict = {}
    s = b._StoreRateSampler(run, clock=lambda: t["now"], size=lambda: size["bytes"])
    s.observe(0)
    t["now"], size["bytes"] = 2.0, int(1.6 * gib)
    s.observe(10)  # under the sample interval: nothing counted yet
    t["now"], size["bytes"] = 6.0, int(2.2 * gib)
    s.observe(60)
    t["now"] = 12.0
    s.observe(90)
    assert b._rate_by_store_gb(run) == [
        {"store_gib": 1, "articles": 60, "seconds": 6.0, "articles_per_second": 10.0},
        {"store_gib": 2, "articles": 30, "seconds": 6.0, "articles_per_second": 5.0},
    ]
    assert (
        b._drain_metrics({**run, "articles": 90, "wall_s": 12.0})["rate_by_store_gb"][0][
            "store_gib"
        ]
        == 1
    )


def test_a_sampler_without_a_size_counts_nothing_and_never_raises():
    from src.api import backup_v2 as b

    run: dict = {}
    t = {"now": 0.0}
    s = b._StoreRateSampler(run, clock=lambda: t["now"], size=lambda: None)
    for i in range(5):
        t["now"] += 10
        s.observe(i * 10)
    assert b._rate_by_store_gb(run) == []

    def _boom():
        raise OSError("gone")

    s2 = b._StoreRateSampler(run, clock=lambda: t["now"], size=_boom)
    s2.observe(
        1
    )  # the size helper is the guarded one in production; a raising one is still swallowed here
    assert b._rate_by_store_gb(run) == []


# --- the button -----------------------------------------------------------------------------------------------------


def test_the_button_saves_the_three_files():
    js = (ROOT / "src/static/app-diagnostics.js").read_text(encoding="utf-8")
    start = js.index("const FIELD_DATA_EXPORTS = [")
    block = js[start : js.index("];", start)]
    urls = [
        line.split('url: "', 1)[1].split('"', 1)[0]
        for line in block.splitlines()
        if 'url: "' in line
    ]
    assert urls[-3:] == [
        "/api/diagnostics/field-run-journal",
        "/api/diagnostics/field-import-reports",
        "/api/diagnostics/field-drain-status",
    ]
