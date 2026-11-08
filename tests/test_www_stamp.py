"""R415: the www engine's own stamp (places + entities), apart from the keyword engine's.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What must hold: the www id moves with the www inputs and code and the keyword id does not
(and the converse), the stamp table is written by a full pass and by the www scope, a
failed www savepoint leaves the previous stamp, and the keyword-only scope writes none.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.analytics.engine_identity as ei
from src.analytics.extract import get_extractor
from src.analytics.store import index_article
from src.database.models import Article, ArticleWwwStamp, Base, Source


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="The Daily Test", domain="dailytest.example"))
    s.commit()
    return s


def _article(s, h="a", text="Chancellor Scholz met President Macron in Berlin on 12 March 2024.", country=None):
    a = Article(
        url=f"https://dailytest.example/{h}", canonical_url=f"https://dailytest.example/{h}",
        source_id=1, title="Budget talks", content=text, hash=h, language="en",
        country=country, created_at=datetime.now(UTC),
    )
    s.add(a)
    s.commit()
    return a


def _stamp(s, aid):
    return s.query(ArticleWwwStamp).filter_by(article_id=aid).one_or_none()


def test_a_full_pass_writes_the_www_stamp():
    s = _session()
    a = _article(s)
    assert _stamp(s, a.id) is None
    index_article(s, a, extractor=get_extractor("baseline"))
    st = _stamp(s, a.id)
    assert st is not None
    assert st.engine == ei.www_engine_id()
    assert st.inputs == ei.www_inputs_digest(raw_content=a.content, country=a.country)


def test_the_keywords_scope_writes_no_www_stamp():
    s = _session()
    a = _article(s)
    index_article(s, a, extractor=get_extractor("baseline"), scope="keywords")
    assert _stamp(s, a.id) is None


def test_the_www_scope_stamps_and_touches_nothing_else():
    s = _session()
    a = _article(s)
    index_article(s, a, extractor=get_extractor("baseline"), scope="keywords")
    before = (a.keyword_indexed_at, a.top_keyword_id)
    out = index_article(s, a, extractor=get_extractor("baseline"), scope="www")
    assert out["mentions"] == 0 and out["dates"] == 0
    assert _stamp(s, a.id).engine == ei.www_engine_id()
    assert (a.keyword_indexed_at, a.top_keyword_id) == before


def test_a_changed_body_moves_the_stamp_inputs_on_restamp():
    s = _session()
    a = _article(s)
    index_article(s, a, extractor=get_extractor("baseline"), scope="www")
    first = _stamp(s, a.id).inputs
    a.content = a.content + " Also Paris."
    s.commit()
    index_article(s, a, extractor=get_extractor("baseline"), scope="www")
    assert _stamp(s, a.id).inputs != first


def test_a_failed_www_savepoint_keeps_the_previous_stamp(monkeypatch):
    s = _session()
    a = _article(s)
    index_article(s, a, extractor=get_extractor("baseline"), scope="www")
    first = _stamp(s, a.id)
    first_engine, first_inputs = first.engine, first.inputs
    a.content = a.content + " Also Paris."
    s.commit()

    import src.timemap.whostore as ws

    def boom(*_a, **_k):
        raise ValueError("extraction bug")

    monkeypatch.setattr(ws, "store_entities_for_article", boom)
    index_article(s, a, extractor=get_extractor("baseline"), scope="www")
    st = _stamp(s, a.id)
    assert (st.engine, st.inputs) == (first_engine, first_inputs)


def test_the_www_inputs_digest_reads_each_input():
    base = ei.www_inputs_digest(raw_content="x", country="DE")
    assert ei.www_inputs_digest(raw_content="y", country="DE") != base
    assert ei.www_inputs_digest(raw_content="x", country="FR") != base
    assert ei.www_inputs_digest(raw_content="x", country="DE") == base
    assert ei.www_inputs_digest(raw_content=None, country=None) == ei.www_inputs_digest(raw_content="", country="")


@pytest.mark.parametrize("target", ["configs/cities.yml", "configs/places_gazetteer.yml"])
def test_a_gazetteer_moves_the_www_id_and_not_the_keyword_id(monkeypatch, target):
    kw, www = ei.baseline_engine_id(), ei.www_engine_id()
    real = ei._read
    assert target in ei._data_files()
    monkeypatch.setattr(ei, "_read", lambda rel: (real(rel) or b"") + b"\n# edited" if rel == target else real(rel))
    ei.data_digest.cache_clear()
    ei.www_data_digest.cache_clear()
    ei._stamp_for.cache_clear()
    try:
        assert ei.www_engine_id() != www
        assert ei.baseline_engine_id() == kw
    finally:
        monkeypatch.undo()
        ei.data_digest.cache_clear()
        ei.www_data_digest.cache_clear()
        ei._stamp_for.cache_clear()
    assert ei.www_engine_id() == www


def test_a_keyword_data_file_does_not_move_the_www_id(monkeypatch):
    www = ei.www_engine_id()
    real = ei._read
    target = "configs/keyword_equivalents.yml"
    monkeypatch.setattr(ei, "_read", lambda rel: (real(rel) or b"") + b"\n# edited" if rel == target else real(rel))
    ei.data_digest.cache_clear()
    ei.www_data_digest.cache_clear()
    try:
        assert ei.www_engine_id() == www
    finally:
        monkeypatch.undo()
        ei.data_digest.cache_clear()
        ei.www_data_digest.cache_clear()


def test_a_www_module_edit_moves_the_www_code_digest_and_not_the_keyword_one(monkeypatch):
    kw, www = ei.code_digest(), ei.www_code_digest()
    real = ei._read
    target = "src/timemap/locextract.py"
    assert target in ei.WWW_ONLY_MODULES
    monkeypatch.setattr(ei, "_read", lambda rel: (real(rel) or b"") + b"\n# edited\n" if rel == target else real(rel))
    ei.code_digest.cache_clear()
    ei.www_code_digest.cache_clear()
    try:
        assert ei.www_code_digest() != www
        assert ei.code_digest() == kw
    finally:
        monkeypatch.undo()
        ei.code_digest.cache_clear()
        ei.www_code_digest.cache_clear()


def test_the_two_module_sets_cover_the_union_and_only_shared_files_overlap():
    kw, www = set(ei._kw_modules()), set(ei._www_modules())
    assert kw | www == set(ei.ENGINE_MODULES)
    assert kw & www == set(ei.WWW_SHARED_MODULES) & set(ei.ENGINE_MODULES) or kw & www <= set(ei.WWW_SHARED_MODULES)
    assert not set(ei.WWW_ONLY_MODULES) & kw
