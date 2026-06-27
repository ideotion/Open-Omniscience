"""Gold-set loader + the BM25F weight A/B (keyword-engine P3 operational path).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The IR eval harness had the metrics + GoldQuery format but no documented FILE input and
no one-call A/B. These pin: load_gold_set parses the bundled template + fails LOUDLY on
malformed input, and bm25f_weight_ab measures a real ranking change (title-heavy vs
body-heavy BM25F) over a live FTS corpus + a gold set -- the measure-before-trust loop
end-to-end on the P5.1a change.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.ir_eval import (
    GoldQuery,
    GoldSetError,
    bm25f_weight_ab,
    load_gold_set,
)
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source

_TEMPLATE = "configs/ir_eval/gold_set.example.json"


def test_load_gold_set_parses_the_bundled_template():
    gold = load_gold_set(_TEMPLATE)
    assert {g.id for g in gold} == {"q_inflation", "q_central_bank_known_item", "q_election_fr"}
    by_id = {g.id: g for g in gold}
    assert by_id["q_election_fr"].language == "fr"
    assert by_id["q_central_bank_known_item"].axis == "known-item"
    # doc-id keys are stringified, grades are graded ints; the _about block is ignored
    assert by_id["q_inflation"].relevances == {"101": 2, "102": 1, "103": 0}


def test_load_gold_set_fails_loudly_on_malformed(tmp_path):
    with pytest.raises(GoldSetError):
        load_gold_set(tmp_path / "missing.json")  # no file
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(GoldSetError):
        load_gold_set(bad_json)

    def _w(obj) -> str:
        p = tmp_path / "g.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return str(p)

    with pytest.raises(GoldSetError):  # not a queries list
        load_gold_set(_w({"queries": "nope"}))
    with pytest.raises(GoldSetError):  # missing query text
        load_gold_set(_w({"queries": [{"id": "q1"}]}))
    with pytest.raises(GoldSetError):  # grade out of {0,1,2}
        load_gold_set(_w({"queries": [{"id": "q1", "query": "x", "relevances": {"1": 3}}]}))
    with pytest.raises(GoldSetError):  # duplicate id
        load_gold_set(_w({"queries": [
            {"id": "q1", "query": "x"}, {"id": "q1", "query": "y"}]}))
    with pytest.raises(GoldSetError):  # empty
        load_gold_set(_w({"queries": []}))


def _corpus():
    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
    return Session


def _add(s, h, title, content):
    a = Article(url=f"u{h}", canonical_url=f"u{h}", source_id=1, title=title, content=content,
                hash=h, language="en", created_at=datetime.now(UTC))
    s.add(a)
    s.flush()
    return a.id


def test_bm25f_weight_ab_measures_a_ranking_change():
    Session = _corpus()
    with Session() as s:
        # "inflation" is in the TITLE of one article (graded highly relevant) and only the
        # BODY of another (graded relevant). Title-heavy weights should rank the grade-2
        # doc first (higher nDCG); body-heavy weights flip it (lower nDCG).
        title_id = _add(s, "t1", "Inflation report", "general coverage of markets and trade")
        body_id = _add(s, "b1", "Markets report", "a long body that mentions inflation once here")
        s.commit()
        gold = [GoldQuery("q", "inflation", "en", "topic",
                          {str(title_id): 2, str(body_id): 1})]
        out = bm25f_weight_ab(s, gold, weights_a=(10.0, 1.0), weights_b=(1.0, 10.0))
        # the A/B is non-vacuous: title-heavy (A) scores higher nDCG than body-heavy (B),
        # so the recorded A->B delta is negative -- the change is MEASURABLE, not guessed.
        assert out["a"]["overall"]["ndcg"] > out["b"]["overall"]["ndcg"]
        assert out["delta"]["ndcg_delta"] < 0
        # recall is unchanged (both docs are found by both weightings) -- reported separately
        assert out["delta"]["recall_delta"] == 0
        assert "score" not in out  # no composite score


def test_ir_eval_endpoint_runs_over_a_gold_set_file(tmp_path):
    """The in-app path: GET /api/diagnostics/ir-eval loads a server-side gold-set file +
    scores the live search (and A/Bs BM25F weights), so the maintainer runs the whole
    measure-before-trust loop in-app. 400 on a missing/malformed gold set or half-specified
    weights -- never a silent skip."""
    from src.api.main import app
    from src.database.session import get_db

    Session = _corpus()
    with Session() as s:
        title_id = _add(s, "t1", "Inflation report", "general coverage of markets and trade")
        body_id = _add(s, "b1", "Markets report", "a long body that mentions inflation once here")
        s.commit()
    gold_file = tmp_path / "gold.json"
    gold_file.write_text(json.dumps({"queries": [
        {"id": "q", "query": "inflation", "relevances": {str(title_id): 2, str(body_id): 1}}
    ]}), encoding="utf-8")

    def _override():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            # single-config eval at the current default
            r = client.get("/api/diagnostics/ir-eval", params={"gold_path": str(gold_file)})
            assert r.status_code == 200 and r.json()["result"]["schema"] == "oo-ir-eval-1"
            # BM25F A/B: title-heavy beats body-heavy -> a negative A->B ndcg delta
            ab = client.get("/api/diagnostics/ir-eval", params={
                "gold_path": str(gold_file), "weights_a": "10,1", "weights_b": "1,10"}).json()
            assert ab["result"]["delta"]["ndcg_delta"] < 0
            # malformed inputs are loud 400s, never silent
            assert client.get("/api/diagnostics/ir-eval",
                              params={"gold_path": str(tmp_path / "nope.json")}).status_code == 400
            assert client.get("/api/diagnostics/ir-eval", params={
                "gold_path": str(gold_file), "weights_a": "10,1"}).status_code == 400  # half-specified
    finally:
        app.dependency_overrides.pop(get_db, None)
