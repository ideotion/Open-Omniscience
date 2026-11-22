"""Row 121 (0.6 gate row A, register ruling G4): the operator curates suggested predictions in a stored IPCC SPM.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What is pinned: the app SUGGESTS by wording and shows why (the cues), the operator DECIDES and only a decision is
stored, the stored sentence is the server's own copy (never the caller's text), a restore carries the decisions with
local winning, and the surface keeps the caveat visible with the method one click away and sends nothing anywhere.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import ipcc as ipcc_api
from src.backup.merge import merge_corpus
from src.database.models import Article, Base, IpccPrediction
from src.database.session import get_db
from src.ingest import ipcc_predictions as ip
from src.ingest.ipcc_spm import ensure_ipcc_source, spm_entry
from tests._app_engine import app_sqlite_engine
from tests.js_source_helper import function_source

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Wording in the shape of the AR6 SPMs (paraphrased): two projections, one statement about the past, one present-tense
# finding with a likelihood term but nothing future-looking, a PDF line break inside a hyphenated word.
_TEXT = (
    "A.1 It is unequivocal that human influence has warmed the atmosphere, ocean and land since 1850.\n"
    "Global surface temperature will continue to increase until at least mid-century under all emis-\n"
    "sions scenarios considered (high confidence).  The frequency of hot extremes has very likely increased "
    "since the 1950s. Global warming of 2°C is very likely to be exceeded by 2100 under the SSP3-7.0 scenario. "
    "Arctic sea ice in September is likely to be practically absent at least once before 2050."
)


def _h(s: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", s).strip().encode()).hexdigest()


# ------------------------------------------------------------------ the suggester
def test_suggestions_need_a_calibrated_term_and_a_future_word_and_say_which_fired():
    r = ip.suggest(_TEXT, "2021-08-07")
    got = [s.sentence for s in r.suggestions]
    assert got == [
        "Global surface temperature will continue to increase until at least mid-century under all emissions "
        "scenarios considered (high confidence).",
        "Global warming of 2°C is very likely to be exceeded by 2100 under the SSP3-7.0 scenario.",
        "Arctic sea ice in September is likely to be practically absent at least once before 2050.",
    ], "a past finding (no future word) or a statement with no calibrated term was suggested, or the hyphen break stayed"
    first, second, third = r.suggestions
    assert first.confidence == ("high confidence",) and "will" in first.future and "mid-century" in first.future
    assert second.likelihood == ("very likely",), "very likely was read as a second, bare likely"
    assert {"2100", "SSP3-7.0", "scenario"} <= set(second.future)
    assert third.likelihood == ("likely",) and "2050" in third.future
    assert [s.position for s in r.suggestions] == sorted(s.position for s in r.suggestions), "not in the report's order"
    assert ip.suggest(_TEXT, "2021-08-07") == r, "the same text gave different suggestions"


def test_a_year_counts_only_after_the_approval_and_not_at_all_without_one():
    s = "Sea level is very likely to have risen by 2019 in every basin considered here."
    assert not ip.suggest(s, "2021-08-07").suggestions, "a year before the approval read as a horizon"
    s2 = "Sea level is very likely to rise in every basin considered here by 2040."
    assert ip.suggest(s2, "2021-08-07").suggestions
    assert not ip.suggest(s2, None).suggestions, "with no approval date the year cue was guessed"


def test_a_passage_too_long_to_be_one_sentence_is_counted_not_shown_and_a_repeat_is_one_row():
    long = "Warming is very likely to continue in the future under " + "every scenario and pathway " * 60 + "considered."
    rep = "Warming will very likely continue under every scenario considered here."
    r = ip.suggest(f"{long} {rep} {rep}", "2021-08-07")
    assert r.too_long == 1 and [s.sentence for s in r.suggestions] == [rep]


def test_e_g_does_not_end_a_sentence():
    s = "Extremes (e.g. heatwaves) will very likely become more frequent in the future."
    assert [x.sentence for x in ip.suggest(s, "2021-08-07").suggestions] == [s]


def test_the_spm_layout_splits_where_statements_end_and_quotes_what_the_report_printed():
    """The independent read's reproducers: citations, glued footnotes, compounds broken across lines, abbreviations."""
    t = (
        "A.1 Warming will very likely continue (high confidence). {2.3, 4.3, 4.5} (Figure SPM.4) B.1.1 Compared to "
        "1850\u20131900, warming is likely to reach 1.5\u00b0C by 2040. Sea level is projected to rise under SSP5-8.5.21 Sea "
        "level will very likely rise by 2100. Ice will likely melt (high confidence).23 More text here follows today. "
        "The Arctic will very likely warm (Fig. 3) in the long-\nterm future. Global emis-\nsions are projected to be "
        "likely high by mid-\ncentury. Warming under SSP1\u20111.9 is very likely limited. The budget is 2390 \u00b1 240 "
        "GtCO2 and is likely the largest. Warming of 1.5 Global was likely projected."
    )
    got = ip._sentences(t)
    assert "A.1 Warming will very likely continue (high confidence)." in got, "a statement id read as a footnote"
    assert got[1].startswith("B.1.1 Compared"), "a citation glued the next statement on"
    assert not any("{" in x or "Figure SPM" in x for x in got)
    assert "Sea level will very likely rise by 2100." in got and "More text here follows today." in got, "a footnote glued two"
    assert "The Arctic will very likely warm (Fig. 3) in the long-term future." in got, "Fig. split or long-term lost its hyphen"
    assert "Global emissions are projected to be likely high by mid-century." in got
    assert "Warming of 1.5 Global was likely projected." in got, "a decimal read as a footnote"
    cues = {x.sentence: x.future for x in ip.suggest(t, "2021-08-07").suggestions}
    assert "SSP1\u20111.9" in cues["Warming under SSP1\u20111.9 is very likely limited."], "a non-breaking hyphen hid the scenario"
    assert "The budget is 2390 \u00b1 240 GtCO2 and is likely the largest." not in cues, "a quantity read as a year"


# ------------------------------------------------------------------ the routes
@pytest.fixture
def world():
    engine = app_sqlite_engine(":memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, autoflush=False)


def _client(world):
    app = FastAPI()
    app.include_router(ipcc_api.router)

    def _db():
        s = world()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def _store(world, body: str = _TEXT) -> int:
    url = spm_entry("wg1").url
    with world() as s:
        src = ensure_ipcc_source(s)
        a = Article(url=url, canonical_url=url, source_id=src.id, title="WGI SPM", content=body, hash="h-wg1",
                    language="en")
        s.add(a)
        s.commit()
        return int(a.id)


def test_nothing_stored_says_so_and_an_unknown_report_is_404(world):
    c = _client(world)
    assert c.get("/api/ipcc/spm/wg9/predictions").status_code == 404
    d = c.get("/api/ipcc/spm/wg1/predictions").json()
    assert d["stored"] is False and d["items"] == []
    assert d["caveat"] == ip.CAVEAT and d["method"] == ip.METHOD


def test_keep_set_aside_and_take_back_store_only_decisions_with_the_servers_own_text(world):
    aid = _store(world)
    c = _client(world)
    d = c.get("/api/ipcc/spm/wg1/predictions").json()
    assert d["stored"] and d["article_id"] == aid and d["counts"]["suggested"] == 3 and d["counts"]["undecided"] == 3
    with world() as s:
        assert s.query(IpccPrediction).count() == 0, "a suggestion nobody decided on was written down"
    first, second = d["items"][0], d["items"][1]
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": first["hash"], "decision": "kept"}).status_code == 200
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": second["hash"], "decision": "set_aside"}).status_code == 200
    with world() as s:
        rows = {r.sentence_hash: r for r in s.query(IpccPrediction)}
    assert rows[first["hash"]].sentence == first["sentence"] and rows[first["hash"]].decision == "kept"
    assert rows[first["hash"]].method_version == ip.METHOD_VERSION
    d = c.get("/api/ipcc/spm/wg1/predictions").json()
    assert (d["counts"]["kept"], d["counts"]["set_aside"], d["counts"]["undecided"]) == (1, 1, 1)
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": second["hash"], "decision": "kept"}).status_code == 200
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": first["hash"], "decision": "undecided"}).status_code == 200
    with world() as s:
        assert [(r.sentence_hash, r.decision) for r in s.query(IpccPrediction)] == [(second["hash"], "kept")]


def test_a_sentence_that_is_not_a_suggestion_or_a_bad_request_is_refused(world):
    _store(world)
    c = _client(world)
    not_suggested = _h("A.1 It is unequivocal that human influence has warmed the atmosphere, ocean and land since 1850.")
    r = c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": not_suggested, "decision": "kept"})
    assert r.status_code == 404, "a sentence the app never suggested was kept"
    good = c.get("/api/ipcc/spm/wg1/predictions").json()["items"][0]["hash"]
    for body in ({"sentence_hash": good, "decision": "maybe"}, {"sentence_hash": "abc", "decision": "kept"},
                 {"sentence_hash": "Z" * 64, "decision": "kept"}):
        assert c.post("/api/ipcc/spm/wg1/predictions/decide", json=body).status_code == 422, body
    assert c.post("/api/ipcc/spm/wg9/predictions/decide", json={"sentence_hash": good, "decision": "kept"}).status_code == 404
    with world() as s:
        assert s.query(IpccPrediction).count() == 0


def test_a_decision_the_method_no_longer_suggests_stays_listed_in_full(world):
    _store(world)
    c = _client(world)
    item = c.get("/api/ipcc/spm/wg1/predictions").json()["items"][2]
    c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": item["hash"], "decision": "kept"})
    with world() as s:
        a = s.query(Article).one()
        a.content = "Nothing here looks ahead."
        s.commit()
    d = c.get("/api/ipcc/spm/wg1/predictions").json()
    assert d["items"] == []
    assert [(o["hash"], o["sentence"], o["decision"]) for o in d["not_suggested_now"]] == [(item["hash"], item["sentence"], "kept")]
    # it can be switched without being taken back, since a removed one can never be kept again
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": item["hash"], "decision": "set_aside"}).status_code == 200
    assert c.get("/api/ipcc/spm/wg1/predictions").json()["not_suggested_now"][0]["decision"] == "set_aside"
    # and it can still be taken back
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": item["hash"], "decision": "undecided"}).status_code == 200
    assert c.get("/api/ipcc/spm/wg1/predictions").json()["not_suggested_now"] == []


def test_the_prediction_routes_never_reach_the_network(world, monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("a prediction route opened a socket")

    _store(world)
    c = _client(world)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    item = c.get("/api/ipcc/spm/wg1/predictions").json()["items"][0]
    assert c.post("/api/ipcc/spm/wg1/predictions/decide", json={"sentence_hash": item["hash"], "decision": "kept"}).status_code == 200


# ------------------------------------------------------------------ the restore
_META = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0", "alembic_rev": "head", "manifest": None}


def _corpus(path: Path):
    engine = app_sqlite_engine(path, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _decide(s, h: str, decision: str, sentence: str = "s") -> None:
    s.add(IpccPrediction(spm_key="wg1", sentence_hash=h, sentence=sentence, decision=decision, method_version=1,
                         decided_at=datetime(2026, 11, 17)))


def test_a_restore_carries_decisions_local_wins_and_a_rerestore_changes_nothing(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    a, b = "a" * 64, "b" * 64
    with _corpus(live)() as s:
        _decide(s, a, "set_aside", "mine")
        s.commit()
    with _corpus(inc)() as s:
        _decide(s, a, "kept", "theirs")
        _decide(s, b, "kept", "only theirs")
        s.commit()
    results, batch = merge_corpus(inc, live, _META)
    r = results["ipcc_predictions"]
    assert (r["new"], r["duplicate"], r["conflict"]) == (1, 1, 1)
    with _corpus(live)() as s:
        rows = {x.sentence_hash: (x.sentence, x.decision) for x in s.query(IpccPrediction)}
        tracked = s.execute(text("SELECT COUNT(*) FROM merged_rows WHERE batch_id=:b AND table_name='ipcc_predictions'"),
                            {"b": batch}).scalar()
    assert rows == {a: ("mine", "set_aside"), b: ("only theirs", "kept")}, "the incoming decision overwrote the local one"
    assert tracked == 1
    results, _ = merge_corpus(inc, live, _META)
    assert results["ipcc_predictions"]["new"] == 0


def test_a_backup_from_before_the_table_existed_merges_cleanly(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(live)() as s:
        _decide(s, "c" * 64, "kept")
        s.commit()
    with _corpus(inc)() as s:
        s.execute(text("DROP TABLE ipcc_predictions"))
        s.commit()
    results, _ = merge_corpus(inc, live, _META)
    assert results["ipcc_predictions"]["new"] == 0
    with _corpus(live)() as s:
        assert s.query(IpccPrediction).count() == 1


# ------------------------------------------------------------------ the surface
def test_the_panel_keeps_the_caveat_visible_puts_the_method_one_click_away_and_asks_no_network_consent():
    js = (_ROOT / "src/static/app-ipcc.js").read_text(encoding="utf-8")
    html = (_ROOT / "src/static/index.html").read_text(encoding="utf-8")
    assert 'id="ipcc-pred"' in html
    pred = "\n".join(
        function_source(js, name) for name in ("loadIpccPredictions", "_renderPredictions", "ipccDecide")
    )
    assert '/predictions"' in pred and "/predictions/decide" in pred
    assert re.search(r'/predictions/decide",\s*\{method: "POST"', pred), "a decision is a write: a POST (R694)"
    assert 'class="card-caveat"' in pred and "d.caveat" in pred, "the short caveat is not visible"
    assert "<details" in pred and "d.method" in pred, "the method is not one click away"
    assert "ensureOnline" not in pred, "a local read or write asked for the network consent"
    assert "data-ipcc-decide" in pred and "onclick" not in js
    assert "window.confirm(" in pred and "orphan" in pred, "removing a decision that can never be made again asks first"


def test_the_new_strings_ship_in_every_locale():
    keys = [ip.CAVEAT, ip.METHOD, "Suggested predictions", "Keep as a prediction", "Set aside",
            "Decided earlier, no longer suggested by this method"]
    for p in sorted((_ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        missing = [k for k in keys if not d.get(k)]
        assert not missing, (p.name, missing)
