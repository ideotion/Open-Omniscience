"""
Tests for src/ai_layer/qualification_assist.py -- the propose-only LLM
nav-soup/extraction-junk flagging pass (B7.2, 2026-07-24 field-feedback
Session B). No network: an injected fake client stands in for the model.
Negative-space is mandatory (the standing skeptic doctrine): every
should-be-empty/unparseable input must yield nothing, never a guess.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import qualification_assist as QA
from src.database.models import Article, Base, Source


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class _FixedReplyClient:
    def __init__(self, reply: str):
        self._reply = reply

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult(self._reply)


class _KeywordAwareClient:
    """Answers based on which canary text is in the prompt, plus 'junk'/'article'
    substrings for real test articles -- lets one client drive a mixed batch."""

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        low = prompt.lower()
        if "storm" in low or "residents" in low:
            return _FakeResult("article")
        if "subscribe" in low or "privacy policy" in low:
            return _FakeResult("junk")
        if "real content" in low:
            return _FakeResult("article")
        if "menu list" in low:
            return _FakeResult("junk")
        return _FakeResult("I refuse to answer.")


class _RaisingClient:
    def generate(self, *a, **kw):
        from src.llm.ollama import LLMUnavailable

        raise LLMUnavailable("simulated outage")


# --------------------------------------------------------------------------- #
# parse_verdict / classify_article_for_qualification -- pure, no DB.
# --------------------------------------------------------------------------- #


def test_parse_verdict_accepts_exact_words_case_and_punctuation_insensitive():
    assert QA.parse_verdict("article") == "article"
    assert QA.parse_verdict("Junk.") == "junk"
    assert QA.parse_verdict("  ARTICLE  ") == "article"


def test_parse_verdict_rejects_anything_else_never_guesses():
    assert QA.parse_verdict("I think this is an article, maybe.") is None
    assert QA.parse_verdict("") is None
    assert QA.parse_verdict(None) is None
    assert QA.parse_verdict("junky") is None  # not an exact match


def test_classify_returns_none_for_empty_text_without_calling_the_model():
    class _NeverCallMe:
        def generate(self, *a, **kw):
            raise AssertionError("empty text must never reach the model")

    out = QA.classify_article_for_qualification(_NeverCallMe(), "", "   ", model="stub:test")
    assert out is None


def test_classify_happy_path():
    out = QA.classify_article_for_qualification(
        _FixedReplyClient("junk"), "T", "some content", model="stub:test"
    )
    assert out == "junk"


def test_classify_propagates_client_errors_for_the_caller_to_handle():
    with pytest.raises(Exception):  # noqa: B017 - LLMUnavailable, imported lazily above
        QA.classify_article_for_qualification(_RaisingClient(), "T", "c", model="stub:test")


# --------------------------------------------------------------------------- #
# check_canaries
# --------------------------------------------------------------------------- #


def test_check_canaries_ok_on_a_correctly_classifying_client():
    out = QA.check_canaries(_KeywordAwareClient(), model="stub:test")
    assert out["ok"] is True
    assert out["article_verdict"] == "article" and out["junk_verdict"] == "junk"


def test_check_canaries_flags_not_ok_on_a_wrong_client():
    out = QA.check_canaries(_FixedReplyClient("junk"), model="stub:test")  # always says junk
    assert out["ok"] is False


# --------------------------------------------------------------------------- #
# propose_qualification_flags -- in-memory DB.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _mk_article(db, src, i, *, title="T", content="c"):
    a = Article(
        url=f"https://src.test/{i}", canonical_url=f"https://src.test/{i}",
        source_id=src.id, title=title, content=content, hash=f"h{i}",
    )
    db.add(a)
    db.flush()
    return a


def test_propose_flags_junk_articles_and_never_touches_source_row(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    _mk_article(db, src, 1, title="Real article", content="this is real content about a storm")
    _mk_article(db, src, 2, title="Nav page", content="this is a menu list of links")
    db.commit()
    before_status, before_tags = src.status, src.tags

    out = QA.propose_qualification_flags(db, src.id, _KeywordAwareClient(), model="stub:test")
    assert out["checked"] == 2
    assert out["junk_count"] == 1 and out["article_count"] == 1
    assert out["flagged"][0]["verdict"] == "junk"
    assert out["canary"]["ok"] is True

    db.refresh(src)
    assert src.status == before_status and src.tags == before_tags  # UNTOUCHED


def test_propose_flags_an_unparseable_reply_stores_no_verdict(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    _mk_article(db, src, 1, title="Weird page", content="asdkjaslkdjaslkjd nonsense text")
    db.commit()

    out = QA.propose_qualification_flags(db, src.id, _KeywordAwareClient(), model="stub:test")
    assert out["unparseable_count"] == 1
    assert out["article_count"] == 0 and out["junk_count"] == 0
    assert out["flagged"] == []


def test_propose_over_a_source_with_no_articles_is_an_honest_zero(db):
    src = Source(name="Empty", domain="empty.test", tags="news")
    db.add(src)
    db.commit()

    out = QA.propose_qualification_flags(db, src.id, _KeywordAwareClient(), model="stub:test")
    assert out["checked"] == 0
    assert out["flagged"] == []


def test_propose_bounds_to_max_articles(db):
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    for i in range(10):
        _mk_article(db, src, i, title="Real article", content="this is real content about storms")
    db.commit()

    out = QA.propose_qualification_flags(
        db, src.id, _KeywordAwareClient(), model="stub:test", max_articles=3
    )
    assert out["checked"] == 3


# --------------------------------------------------------------------------- #
# run_and_persist_qualification_assist / last_qualification_assist_report
# --------------------------------------------------------------------------- #


def test_run_and_persist_writes_a_dated_json_and_never_touches_the_source(db, tmp_path, monkeypatch):
    monkeypatch.setattr(QA, "_dir", lambda: tmp_path)
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    _mk_article(db, src, 1, title="Real article", content="this is real content about a storm")
    db.commit()

    out = QA.run_and_persist_qualification_assist(
        db, src.id, _KeywordAwareClient(), model="stub:test"
    )
    assert out["schema"] == QA.QUALIFICATION_ASSIST_SCHEMA
    assert out["source_id"] == src.id
    assert out["path"] and out["filename"]

    files = list(tmp_path.glob(f"oo-qualification-assist-{src.id}-*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text(encoding="utf-8"))
    assert on_disk["source_id"] == src.id


def test_last_report_is_an_honest_stub_when_nothing_has_run(tmp_path, monkeypatch):
    monkeypatch.setattr(QA, "_dir", lambda: tmp_path)
    out = QA.last_qualification_assist_report()
    assert out["available"] is False


def test_last_report_can_filter_by_source_id(db, tmp_path, monkeypatch):
    monkeypatch.setattr(QA, "_dir", lambda: tmp_path)
    src1 = Source(name="S1", domain="s1.test", tags="news")
    src2 = Source(name="S2", domain="s2.test", tags="news")
    db.add_all([src1, src2])
    db.flush()
    _mk_article(db, src1, 1, title="A", content="this is real content about a storm")
    _mk_article(db, src2, 2, title="B", content="this is real content about a storm")
    db.commit()

    QA.run_and_persist_qualification_assist(db, src1.id, _KeywordAwareClient(), model="stub:test")
    QA.run_and_persist_qualification_assist(db, src2.id, _KeywordAwareClient(), model="stub:test")

    only_src1 = QA.last_qualification_assist_report(source_id=src1.id)
    assert only_src1["source_id"] == src1.id


def test_run_qualification_assist_selftest_passes():
    out = QA.run_qualification_assist_selftest()
    assert out["passed"] is True
