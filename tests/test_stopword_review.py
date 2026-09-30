"""The stopword review screen's logic and routes (R98, D11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The refusals are the point, so most of these are negative space: a word nobody proposed is not
decidable; a platform name (R104) and a translated concept (R102) are not acceptable; a decision
changes no stoplist; the export is text, applied nowhere; and the screen offers no control that
sets a keyword's kind (R107).
"""

from __future__ import annotations

import textwrap

import pytest
import yaml
from fastapi.testclient import TestClient

from src.analytics import stopword_review as sr
from src.api.main import app
from src.config import kv_store


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    kv_store.kv_invalidate()
    cfg = tmp_path / "review"
    cfg.mkdir()
    (cfg / "_keep_platform_names.yml").write_text("platform_names:\n  - facebook\n  - twitter\n", encoding="utf-8")
    (cfg / "en.yml").write_text(
        textwrap.dedent(
            """
            language: en
            batches:
              - id: en-test-a
                generated: 2026-10-01
                source: a test fixture
                method: invented numbers
                candidates:
                  - {term: permalink, articles: 900, mentions: 2000, class: page_word}
                  - {term: comments, articles: 880, mentions: 1900, class: page_word}
                  - {term: follow, articles: 700, mentions: 1500, class: page_word}
                  - {term: facebook, articles: 650, mentions: 1200, class: page_word}
                  - {term: election, articles: 600, mentions: 1100, class: other}
                  - {term: the, articles: 5000, mentions: 90000, class: function_word}
                  - {term: "yes", articles: 50, mentions: 70, class: function_word}
              - id: en-test-b
                generated: 2026-10-02
                source: a second fixture
                method: invented numbers
                candidates:
                  - {term: permalink, articles: 950, mentions: 2100, class: page_word}
            """
        ),
        encoding="utf-8",
    )
    (cfg / "zz.yml").write_text("language: zz\nbatches: [\n", encoding="utf-8")  # malformed
    monkeypatch.setattr(sr, "CONFIG_DIR", cfg)
    monkeypatch.setattr(sr, "_KEEP_FILE", cfg / "_keep_platform_names.yml")
    yield
    kv_store.kv_invalidate()


def _ring_member(monkeypatch, lang: str, term: str) -> None:
    from src.analytics import equivalence

    real = equivalence.ring_of
    monkeypatch.setattr(equivalence, "ring_of", lambda lg, n: "ring-x" if (lg, n) == (lang, term) else real(lg, n))


def test_batches_merge_by_term_keeping_the_larger_evidence_and_report_a_bad_file():
    data = sr.load_batches()
    assert set(data["languages"]) == {"en"}
    assert [e["file"] for e in data["errors"]] == ["zz.yml"]
    state = sr.review_state(None, "en")
    by = {r["term"]: r for r in state["candidates"]}
    assert by["permalink"]["articles"] == 950 and by["permalink"]["batch"] == "en-test-b"


def test_words_the_language_already_drops_are_set_aside_not_reviewed():
    state = sr.review_state(None, "en")
    terms = {r["term"] for r in state["candidates"]}
    assert not ({"the", "yes", "comments"} & terms)  # already on the English lists
    assert state["counts"]["already_listed"] >= 1
    assert {"permalink", "follow", "election", "facebook"} <= terms


def test_an_unproposed_word_cannot_be_decided():
    with pytest.raises(sr.ReviewError):
        sr.record_decision("en", "banana", "accept")
    with pytest.raises(sr.ReviewError):
        sr.record_decision("fr", "permalink", "accept")  # proposed for en, not fr


def test_a_platform_name_cannot_be_accepted_but_can_be_rejected():
    with pytest.raises(sr.ReviewError, match="platform name"):
        sr.record_decision("en", "facebook", "accept")
    assert sr.record_decision("en", "facebook", "reject")["decision"] == "reject"
    row = next(r for r in sr.review_state(None, "en")["candidates"] if r["term"] == "facebook")
    assert row["blocked"] == "platform_name" and row["decision"] == "reject"


def test_a_ring_member_cannot_be_accepted(monkeypatch):
    _ring_member(monkeypatch, "en", "election")
    with pytest.raises(sr.ReviewError, match="translated concept"):
        sr.record_decision("en", "election", "accept")
    row = next(r for r in sr.review_state(None, "en")["candidates"] if r["term"] == "election")
    assert row["blocked"] == "ring_member"


def test_decisions_persist_and_clear_and_unknown_ones_are_refused():
    sr.record_decision("en", "permalink", "accept")
    sr.record_decision("en", "follow", "reject")
    kv_store.kv_invalidate()  # a fresh read, as after a restart
    counts = sr.review_state(None, "en")["counts"]
    assert (counts["accepted"], counts["rejected"]) == (1, 1)
    assert sr.languages() == [{"language": "en", "candidates": 7, "decided": 2}]
    sr.record_decision("en", "permalink", "clear")
    assert sr.review_state(None, "en")["counts"]["accepted"] == 0
    with pytest.raises(sr.ReviewError):
        sr.record_decision("en", "permalink", "maybe")


def test_a_decision_changes_no_stoplist():
    from src.analytics.extract import _stopset, global_stopwords

    before_en, before_global = _stopset("en"), global_stopwords()
    sr.record_decision("en", "permalink", "accept")
    assert _stopset("en") == before_en and global_stopwords() == before_global


def test_the_export_is_yaml_text_with_accepted_and_rejected_words():
    sr.record_decision("en", "permalink", "accept")
    sr.record_decision("en", "follow", "reject")
    doc = sr.export_batch(None, "en")
    parsed = yaml.safe_load(doc)
    assert parsed["language"] == "en"
    assert parsed["accepted"] == ["permalink"] and parsed["rejected"] == ["follow"]
    assert parsed["reviewed_batches"] == ["en-test-a", "en-test-b"]
    assert "Not applied anywhere" in doc
    empty = yaml.safe_load(sr.export_batch(None, "fr"))
    assert empty["accepted"] == [] and empty["rejected"] == [] and empty["reviewed_batches"] == []


def test_a_word_yaml_would_misread_is_quoted_in_the_export(monkeypatch):
    assert yaml.safe_load("- " + sr._yaml_scalar("yes")) == ["yes"]
    assert yaml.safe_load("- " + sr._yaml_scalar("null")) == ["null"]
    assert yaml.safe_load("- " + sr._yaml_scalar("123")) == ["123"]


def test_the_collision_evidence_reads_the_keywords_of_other_languages(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base, Keyword

    eng = create_engine(f"sqlite:///{tmp_path / 'k.db'}")
    Base.metadata.create_all(eng)
    with Session(eng) as db:
        db.add_all(
            [
                Keyword(term="permalink", normalized_term="permalink", language="fr", article_count=40),
                Keyword(term="permalink", normalized_term="permalink", language="en", article_count=900),
                Keyword(term="follow", normalized_term="follow", language="de", article_count=1),
            ]
        )
        db.commit()
        state = sr.review_state(db, "en")
    by = {r["term"]: r for r in state["candidates"]}
    assert by["permalink"]["elsewhere"] == [{"language": "fr", "articles": 40}]  # own language excluded
    assert by["follow"]["elsewhere"] == []  # below the floor, and not shown as a collision
    sr.record_decision("en", "permalink", "accept")
    with Session(eng) as db:
        doc = sr.export_batch(db, "en")
    assert "also a keyword in fr (40)" in doc  # the collision travels with the accepted word
    assert "also a keyword" not in sr.export_batch(None, "en")  # no session: nothing unmeasured is said


def test_the_routes_dispatch_and_the_refusal_is_a_409():
    with TestClient(app) as c:
        r = c.get("/api/keywords/stopword-review/languages")
        assert r.status_code == 200 and r.json()["languages"][0]["language"] == "en"
        assert c.get("/api/keywords/stopword-review", params={"language": "en"}).status_code == 200
        ok = c.put("/api/keywords/stopword-review/decision", json={"language": "en", "term": "permalink", "decision": "accept"})
        assert ok.status_code == 200, ok.text
        bad = c.put("/api/keywords/stopword-review/decision", json={"language": "en", "term": "facebook", "decision": "accept"})
        assert bad.status_code == 409 and "platform name" in bad.json()["detail"]
        exp = c.get("/api/keywords/stopword-review/export", params={"language": "en"})
        assert exp.status_code == 200, exp.text
        body = exp.json()
        assert body["filename"] == "stopword-review-en.yml" and body["accepted"] == 1
        assert "accepted:" in body["yaml"]


def test_no_control_in_the_module_or_router_sets_a_kind():
    """R107: kinds come from sources and no control sets one."""
    import inspect

    from src.api import stopword_review as api

    for mod in (sr, api):
        body = inspect.getsource(mod)
        for forbidden in ("entity_type", "set_kind", "kind_override", "keyword_kinds"):
            assert forbidden not in body, (mod.__name__, forbidden)
