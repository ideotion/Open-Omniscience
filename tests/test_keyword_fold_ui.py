"""The keyword fold job's surfaces (Q416 = a): the endpoints, /api/jobs, and Settings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_keyword_fold.py`` proves what the job does to a corpus. This file proves an
operator can reach it and read it: the routes compose from the router prefix (the
slice-1c 404 lesson), a refusal answers with a CODE through a real client (CodeQL: no
exception text in a response), the task manager lists a paused fold with Resume, the
buttons are bound by listener rather than inline (Q1127's ratchet), and every string the
surface draws is keyed in all twelve locales. The status line's behaviour is driven in
node (``keyword_fold_node_test.js``) against the function extracted from the shipped file.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from src.analytics import keyword_fold
from src.analytics.keyword_fold import KeywordFoldJobManager

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

#: Every string the fold's Settings row, confirms and status line draw. Named here, not
#: read from the gate: an improving codebase moves a max-gate, so "the i18n gate is green"
#: is not evidence that THESE strings are covered.
_FOLD_STRINGS = [
    "Fold keyword forms (studies → study)",
    "Fold report (.json)",
    "Lemmatisation is off in this install (OO_EXTRACT_LEMMA=0), so there is no base form to fold into.",
    "No lemmatiser is installed, so there is no base form to fold into.",
    "The fold stopped on an error; the log has the details. Folding again continues from where it stopped.",
    "Keywords folded: {folded} · mentions moved: {moved} · keywords whose language changed: {relanguaged}",
    "Setting each keyword's language from its mentions…",
    "Keywords checked: {done} of {total} ({percent}%)",
    "Mentions moved: {moved}",
    "paused for an import",
    "Continue folding keyword forms? It resumes where it stopped. Keywords already checked: {done} of {total}.",
]


def test_fold_status_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "keyword_fold_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_fold_string_is_keyed_in_all_twelve_locales() -> None:
    locales = sorted((_STATIC / "locales").glob("*.json"))
    assert len(locales) == 12
    missing: list[str] = []
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _FOLD_STRINGS:
            if not data.get(s):
                missing.append(f"{path.stem}: {s[:50]}")
            elif "{" in s:
                # a placeholder the translation dropped would print a raw brace or nothing
                want = set(re.findall(r"\{\w+\}", s))
                assert set(re.findall(r"\{\w+\}", data[s])) == want, f"{path.stem}: {s[:50]}"
    assert not missing, missing


def test_the_routes_compose_and_the_job_is_wired_into_the_task_manager() -> None:
    api_src = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    jobs_src = (_ROOT / "src" / "api" / "jobs.py").read_text(encoding="utf-8")
    wiring_src = (_ROOT / "src" / "api" / "_wiring.py").read_text(encoding="utf-8")

    prefix = re.search(r'APIRouter\(prefix="([^"]+)"', api_src)
    assert prefix
    decorated = set(re.findall(r'@router\.(get|post)\("(/keyword-fold-job[^"]*)"', api_src))
    assert {(m, prefix.group(1) + p) for m, p in decorated} == {
        ("post", "/api/insights/keyword-fold-job"),
        ("get", "/api/insights/keyword-fold-job/status"),
        ("get", "/api/insights/keyword-fold-job/report"),
        ("post", "/api/insights/keyword-fold-job/{action}"),
    }
    assert "from src.api.insights import router as insights_router" in wiring_src

    # a DB writer (so arbitration counts it), listed by the aggregator, both actions routed
    from src.api.jobs import _DB_WRITER_KINDS

    assert "keyword-fold" in _DB_WRITER_KINDS
    assert "jobs.extend(_keyword_fold_jobs())" in jobs_src
    assert jobs_src.count('job_id == "keyword-fold"') == 2  # cancel (pauses) and resume

    # the UI reads the report route the endpoint serves
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    assert '"/api/insights/keyword-fold-job/report"' in boot


def test_the_buttons_are_bound_by_listener_never_inline() -> None:
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    boot = (_STATIC / "app-boot.js").read_text(encoding="utf-8")
    for bid in ("kw-fold-btn", "kw-fold-report"):
        tag = re.search(r"<button[^>]*\bid=\"" + bid + r"\"[^>]*>", html)
        assert tag, bid
        assert "onclick" not in tag.group(0), f"{bid} carries an inline handler"
    assert '$("kw-fold-btn")' in boot and 'addEventListener("click", () => foldKeywords(btn))' in boot
    assert '$("kw-fold-report")' in boot
    assert 'id="kw-fold-status"' in html


@pytest.fixture
def fold_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.insights import router

    mgr = KeywordFoldJobManager(state_path=tmp_path / "state.json", report_path=tmp_path / "report.json")
    monkeypatch.setattr(keyword_fold, "get_fold_manager", lambda: mgr)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), mgr


def test_a_refused_start_answers_with_a_code_never_exception_text(fold_client, monkeypatch) -> None:
    client, _mgr = fold_client
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "0")
    want = keyword_fold.refusal()
    assert want in (keyword_fold.REFUSED_LEMMA_OFF, keyword_fold.REFUSED_NO_LEMMATISER)
    for path in ("/api/insights/keyword-fold-job", "/api/insights/keyword-fold-job/resume"):
        r = client.post(path)
        assert r.status_code == 409, path
        assert r.json() == {"detail": {"code": want}}, path
    status = client.get("/api/insights/keyword-fold-job/status").json()
    assert status["refusal"] == want and status["state"] == "idle" and status["running"] is False


def test_resume_with_nothing_paused_says_so(fold_client, monkeypatch) -> None:
    from src.analytics.lemma import lemmatizer_available

    if not lemmatizer_available():
        pytest.skip("simplemma not installed: the refusal would be no-lemmatiser instead")
    client, _mgr = fold_client
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    r = client.post("/api/insights/keyword-fold-job/resume")
    assert r.status_code == 409
    assert r.json() == {"detail": {"code": keyword_fold.REFUSED_NOTHING_PAUSED}}


def test_the_report_and_an_unknown_action_answer_with_codes(fold_client, monkeypatch) -> None:
    client, _mgr = fold_client
    monkeypatch.setattr(keyword_fold, "last_report", lambda: None)
    r = client.get("/api/insights/keyword-fold-job/report")
    assert r.status_code == 404 and r.json() == {"detail": {"code": "no-report"}}
    monkeypatch.setattr(keyword_fold, "last_report", lambda: {"fold": {"keywords_folded": 2}})
    assert client.get("/api/insights/keyword-fold-job/report").json() == {"fold": {"keywords_folded": 2}}
    r = client.post("/api/insights/keyword-fold-job/explode")
    assert r.status_code == 400 and r.json() == {"detail": {"code": "unknown-action"}}


class _Stub:
    def __init__(self, **over) -> None:
        self.s = {
            "state": "idle",
            "phase": "fold",
            "keywords_total": 0,
            "keywords_done": 0,
            "percent": 0.0,
            "tally": {},
            "eta_seconds": None,
            "error": None,
            "running": False,
            "parked_for_exclusive": False,
            "refusal": None,
            **over,
        }

    def status(self) -> dict:
        return self.s


@pytest.mark.parametrize("state", ["idle", "done", "cancelled"])
def test_the_task_manager_lists_nothing_for_a_fold_that_is_not_live(monkeypatch, state) -> None:
    from src.api import jobs

    monkeypatch.setattr(keyword_fold, "get_fold_manager", lambda: _Stub(state=state))
    assert jobs._keyword_fold_jobs() == []


def test_the_task_manager_lists_a_paused_or_failed_fold_with_resume(monkeypatch) -> None:
    from src.api import jobs

    monkeypatch.setattr(
        keyword_fold,
        "get_fold_manager",
        lambda: _Stub(state="paused", keywords_total=40, keywords_done=10, percent=25.0),
    )
    (row,) = jobs._keyword_fold_jobs()
    assert row["id"] == row["kind"] == "keyword-fold"
    assert row["state"] == "paused" and row["actions"] == ["resume", "cancel"]
    assert row["progress"] == {"done": 10, "total": 40, "unit": "keywords", "percent": 25.0}

    monkeypatch.setattr(keyword_fold, "get_fold_manager", lambda: _Stub(state="error", error="failed"))
    (row,) = jobs._keyword_fold_jobs()
    assert row["state"] == "failed" and row["actions"] == ["resume", "cancel"]
    assert row["error"] == "failed" and row["progress"] is None  # no "0 of 0"


def test_the_task_manager_names_the_phase_and_an_import_that_parked_it(monkeypatch) -> None:
    from src.api import jobs

    monkeypatch.setattr(
        keyword_fold,
        "get_fold_manager",
        lambda: _Stub(state="running", running=True, keywords_total=5, parked_for_exclusive=True),
    )
    (row,) = jobs._keyword_fold_jobs()
    assert row["label"] == "Paused for an import — folding keyword forms into their base form"
    assert row["actions"] == ["pause", "cancel"]

    monkeypatch.setattr(
        keyword_fold, "get_fold_manager", lambda: _Stub(state="running", running=True, phase="language")
    )
    (row,) = jobs._keyword_fold_jobs()
    assert row["label"] == "Setting each keyword's language from its mentions"
