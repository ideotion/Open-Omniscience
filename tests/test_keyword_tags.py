"""Item AC slice 1: curated baseline loader + index-time keyword tagging.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A keyword that matches the curated, dated, local baseline is pre-tagged at
creation along two axes (type + topic). Tags are labelled assertions with source
provenance, applied forward-only; nothing is invented and nothing is a score.
"""

import re
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.baseline import BASELINE_AS_OF, baseline_tags
from src.analytics.extract import ExtractedTerm
from src.analytics.store import _get_or_create_keyword, tags_for_keyword
from src.database.models import Base, KeywordTag


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_baseline_loader_both_axes_and_casefold():
    assert dict(baseline_tags("en", "election")) == {"type": "event", "topic": "politics"}
    # casefold both sides (an acronym is stored upper-case post-2026-06-16)
    assert dict(baseline_tags("en", "ELECTION")) == {"type": "event", "topic": "politics"}
    assert dict(baseline_tags("en", "inflation")) == {"topic": "economy"}  # topic-only entry
    assert dict(baseline_tags("fr", "élection")) == {"type": "event", "topic": "politics"}
    assert baseline_tags("en", "tuesday") == ()  # not in the baseline -> nothing
    assert baseline_tags("xx", "election") == ()  # no file for the language
    assert baseline_tags(None, "election") == ()  # unknown language


def test_baseline_disabled_by_env(monkeypatch):
    monkeypatch.setenv("OO_KEYWORD_TAGS", "0")
    assert baseline_tags("en", "election") == ()


def test_baseline_as_of_is_fresh():
    """Fails once BASELINE_AS_OF ages out of the window, forcing a re-review."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", BASELINE_AS_OF)
    assert m, f"BASELINE_AS_OF must be 'YYYY-MM', got {BASELINE_AS_OF!r}"
    y, mo = int(m.group(1)), int(m.group(2))
    today = date.today()
    age = (today.year - y) * 12 + (today.month - mo)
    assert 0 <= age <= 12, (
        f"keyword baseline is {age} months old (BASELINE_AS_OF={BASELINE_AS_OF}); "
        f"re-review configs/keyword_baseline/*.yml and bump BASELINE_AS_OF."
    )


def test_baseline_tags_applied_at_keyword_creation_forward_only():
    s = _sess()
    t = ExtractedTerm(term="election", normalized="election", kind="term", count=1, first_offset=0)
    kw = _get_or_create_keyword(s, t, language="en", extractor="baseline")
    s.flush()
    tags = {(r.axis, r.tag, r.source) for r in s.query(KeywordTag).filter_by(keyword_id=kw.id)}
    assert tags == {("type", "event", "baseline"), ("topic", "politics", "baseline")}
    # forward-only + idempotent: re-resolving the SAME keyword adds no new tags
    _get_or_create_keyword(s, t, language="en", extractor="baseline")
    s.flush()
    assert s.query(KeywordTag).filter_by(keyword_id=kw.id).count() == 2
    assert tags_for_keyword(s, "election") == {"type": ["event"], "topic": ["politics"]}


def test_non_baseline_keyword_gets_no_tags():
    s = _sess()
    t = ExtractedTerm(term="widget", normalized="widget", kind="term", count=1, first_offset=0)
    kw = _get_or_create_keyword(s, t, language="en", extractor="baseline")
    s.flush()
    assert s.query(KeywordTag).filter_by(keyword_id=kw.id).count() == 0
    assert tags_for_keyword(s, "widget") == {}
