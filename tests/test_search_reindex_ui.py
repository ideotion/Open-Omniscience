"""The search re-index's surfaces (S04-07 S8): the endpoints, /api/jobs, and Settings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_fts_cjk_arabic.py`` proves what the job does to the index. This file proves an
operator can reach it and read it: the routes compose from the router prefix (the slice-1c
404 lesson), a refusal answers with a CODE through a real client (CodeQL: no exception text
in a response), the task manager lists a paused run with Resume and counts ARTICLES rather
than ids, the buttons are bound by listener rather than inline (Q1127's ratchet), and every
string the surface draws is keyed in all twelve locales. The status line's behaviour is
driven in node (``search_reindex_node_test.js``) against the function extracted from the
shipped file.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from src.database import fts_reindex
from src.database.fts_reindex import SearchReindexJobManager

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

#: Every string the Settings row, the confirms and the status line draw. Named here, not
#: read from the gate: an improving codebase moves a max-gate, so "the i18n gate is green"
#: is not evidence that THESE strings are covered.
_STRINGS = [
    "Re-index search (Arabic, Chinese, Japanese)",
    "Index older articles the way new ones are indexed: Arabic spelling variants folded together, Chinese and Japanese split into words. Pausable from the task manager.",
    "Search re-index report (.json)",
    "The report of the last completed search re-index: articles checked and re-indexed, by script.",
    "This store's search index has not been upgraded yet. Restart the app once, then run this again.",
    "The search re-index stopped on an error; the log has the details. Running it again continues from where it stopped.",
    "Articles checked: {checked} · re-indexed: {reindexed} (Arabic: {arabic} · Chinese: {chinese} · Japanese: {japanese})",
    "Indexed without word splitting, their segmenter is no longer installed: {n}",
    "Articles checked: {done} of {total} ({percent}%)",
    "Re-indexed: {n}",
    "paused for an import",
    "Continue the search re-index? It resumes where it stopped ({percent}% done).",
    "Re-index search for Arabic, Chinese and Japanese now? Articles whose search entry would change are indexed again; nothing else is touched. It runs in the background and can be paused from the task manager.",
]


def test_status_line_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "search_reindex_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_string_is_keyed_in_all_twelve_locales() -> None:
    locales = sorted((_STATIC / "locales").glob("*.json"))
    assert len(locales) == 12
    missing: list[str] = []
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _STRINGS:
            if not data.get(s):
                missing.append(f"{path.stem}: {s[:50]}")
            elif "{" in s:
                # a placeholder the translation dropped would print a raw brace or nothing
                want = set(re.findall(r"\{\w+\}", s))
                assert set(re.findall(r"\{\w+\}", data[s])) == want, f"{path.stem}: {s[:50]}"
    assert not missing, missing


def test_the_hint_the_page_draws_is_the_key_the_locales_carry() -> None:
    """DOM text is translated by matching it as a key, so the hint must match to the byte."""
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    hint = re.search(r'<div class="hint">(New articles are indexed so that a search[^<]*)</div>', html)
    assert hint
    fr = json.loads((_STATIC / "locales" / "fr.json").read_text(encoding="utf-8"))
    assert fr.get(hint.group(1)), "the Settings hint is not a locale key"


def test_the_routes_compose_and_the_job_is_wired_into_the_task_manager() -> None:
    api_src = (_ROOT / "src" / "api" / "search_omni.py").read_text(encoding="utf-8")
    jobs_src = (_ROOT / "src" / "api" / "jobs.py").read_text(encoding="utf-8")
    wiring_src = (_ROOT / "src" / "api" / "_wiring.py").read_text(encoding="utf-8")

    prefix = re.search(r'APIRouter\(prefix="([^"]+)"', api_src)
    assert prefix
    decorated = set(re.findall(r'@router\.(get|post)\("(/index-job[^"]*)"', api_src))
    assert {(m, prefix.group(1) + p) for m, p in decorated} == {
        ("post", "/api/search/index-job"),
        ("get", "/api/search/index-job/status"),
        ("get", "/api/search/index-job/report"),
        ("post", "/api/search/index-job/{action}"),
    }
    assert "from src.api.search_omni import router as search_omni_router" in wiring_src

    # a DB writer (so arbitration counts it), listed by the aggregator, both actions routed
    from src.api.jobs import _DB_WRITER_KINDS

    assert "search-reindex" in _DB_WRITER_KINDS
    assert "jobs.extend(_search_reindex_jobs())" in jobs_src
    assert jobs_src.count('job_id == "search-reindex"') == 2  # cancel (pauses) and resume

    # the UI reads the report route the endpoint serves
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    assert '"/api/search/index-job/report"' in boot


def test_the_buttons_are_bound_by_listener_never_inline() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    for bid in ("fts-reindex-btn", "fts-reindex-report"):
        tag = re.search(r"<button[^>]*\bid=\"" + bid + r"\"[^>]*>", html)
        assert tag, bid
        assert "onclick" not in tag.group(0), f"{bid} carries an inline handler"
    assert '$("fts-reindex-btn")' in boot and 'addEventListener("click", () => reindexSearch(btn))' in boot
    assert '$("fts-reindex-report")' in boot
    assert 'id="fts-reindex-status"' in html


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.search_omni import router

    mgr = SearchReindexJobManager(state_path=tmp_path / "state.json", report_path=tmp_path / "report.json")
    monkeypatch.setattr(fts_reindex, "get_search_reindex_manager", lambda: mgr)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), mgr


def test_resume_with_nothing_paused_answers_with_a_code(client) -> None:
    c, _mgr = client
    r = c.post("/api/search/index-job/resume")
    assert r.status_code == 409
    assert r.json() == {"detail": {"code": fts_reindex.REFUSED_NOTHING_PAUSED}}


def test_a_second_start_while_running_answers_with_a_code(client, monkeypatch) -> None:
    c, mgr = client
    monkeypatch.setattr(mgr, "_alive", lambda: True)
    r = c.post("/api/search/index-job")
    assert r.status_code == 409 and r.json() == {"detail": {"code": fts_reindex.REFUSED_RUNNING}}


def test_the_report_and_an_unknown_action_answer_with_codes(client, monkeypatch) -> None:
    c, _mgr = client
    monkeypatch.setattr(fts_reindex, "last_report", lambda: None)
    r = c.get("/api/search/index-job/report")
    assert r.status_code == 404 and r.json() == {"detail": {"code": "no-report"}}
    monkeypatch.setattr(fts_reindex, "last_report", lambda: {"articles_reindexed": 2})
    assert c.get("/api/search/index-job/report").json() == {"articles_reindexed": 2}
    r = c.post("/api/search/index-job/explode")
    assert r.status_code == 400 and r.json() == {"detail": {"code": "unknown-action"}}
    st = c.get("/api/search/index-job/status").json()
    assert st["state"] == "idle" and st["running"] is False


class _Stub:
    def __init__(self, **over) -> None:
        self.s = {
            "state": "idle",
            "cursor": None,
            "max_id": 0,
            "percent": 0.0,
            "articles_total": 0,
            "articles_checked": 0,
            "tally": {},
            "error": None,
            "running": False,
            "parked_for_exclusive": False,
            **over,
        }

    def status(self) -> dict:
        return self.s


@pytest.mark.parametrize("state", ["idle", "done", "cancelled"])
def test_the_task_manager_lists_nothing_for_a_run_that_is_not_live(monkeypatch, state) -> None:
    from src.api import jobs

    monkeypatch.setattr(fts_reindex, "get_search_reindex_manager", lambda: _Stub(state=state))
    assert jobs._search_reindex_jobs() == []


def test_the_task_manager_lists_a_paused_or_failed_run_with_resume(monkeypatch) -> None:
    from src.api import jobs

    monkeypatch.setattr(
        fts_reindex,
        "get_search_reindex_manager",
        lambda: _Stub(state="paused", cursor=900, max_id=1000, percent=90.0, articles_total=40, articles_checked=10),
    )
    (row,) = jobs._search_reindex_jobs()
    assert row["id"] == row["kind"] == "search-reindex"
    assert row["state"] == "paused" and row["actions"] == ["resume", "cancel"]
    # a COUNT of articles for people; the percent is the cursor's place in the id range
    assert row["progress"] == {"done": 10, "total": 40, "unit": "articles", "percent": 90.0}

    monkeypatch.setattr(
        fts_reindex, "get_search_reindex_manager", lambda: _Stub(state="error", error="index-not-upgraded")
    )
    (row,) = jobs._search_reindex_jobs()
    assert row["state"] == "failed" and row["actions"] == ["resume", "cancel"]
    assert row["error"] == "index-not-upgraded" and row["progress"] is None  # no "0 of 0"


def test_the_task_manager_names_an_import_that_parked_it(monkeypatch) -> None:
    from src.api import jobs

    monkeypatch.setattr(
        fts_reindex,
        "get_search_reindex_manager",
        lambda: _Stub(state="running", running=True, articles_total=5, parked_for_exclusive=True),
    )
    (row,) = jobs._search_reindex_jobs()
    assert row["label"].startswith("Paused for an import")
    assert row["actions"] == ["pause", "cancel"]


def test_the_status_counts_articles_and_restores_them_after_a_restart(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"state": "running", "cursor": 7, "max_id": 20, "total": 12, "tally": {"articles_checked": 5}}),
        encoding="utf-8",
    )
    st = SearchReindexJobManager(state_path=state, report_path=tmp_path / "r.json").status()
    assert st["state"] == "paused" and st["articles_total"] == 12 and st["articles_checked"] == 5
    assert st["percent"] == 35.0
