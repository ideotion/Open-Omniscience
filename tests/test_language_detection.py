"""Offline secondary/deduced language detection (field §2.6, maintainer ruling Q3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An article the source/extractor left untagged gets a DEDUCED language (offline,
confidence-gated) so it extracts under the right stoplist instead of leaking its
function words. These tests pin the honest contract: the authoritative `language` is
NEVER overwritten, the detector NEVER guesses (short / unsupported -> None), and a
deduced foreign article's function words are filtered.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, Source

FR = (
    "Le gouvernement français a présenté mardi un budget consacré à la transition "
    "écologique et à la réforme des retraites, suscitant un vif débat à l'Assemblée "
    "nationale entre la majorité et l'opposition sur le financement des mesures sociales."
)
EN = (
    "The central bank held interest rates steady for the rest of the quarter, citing "
    "persistent uncertainty in global energy markets and softer-than-expected consumer "
    "demand at home, and officials said they would reassess the stance at the next "
    "scheduled meeting in the autumn before deciding on any further policy move."
)
# > 200 chars so it exercises the UNsupported-rejection path, not the length gate.
KO = (
    "중앙은행은 글로벌 불확실성 속에서 분기 내내 금리를 동결하기로 결정했다고 화요일 발표했습니다. "
    "당국자들은 가을에 열리는 다음 정례 회의에서 추가적인 정책 변경을 결정하기 전에 입장을 "
    "다시 평가할 것이라고 말했으며 에너지 시장의 변동성과 약한 소비 수요를 근거로 들었습니다."
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _art(db, aid, text, *, language=None):
    db.add(Source(id=1, name="S", domain="x.test")) if db.get(Source, 1) is None else None
    a = Article(
        id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}", source_id=1,
        title="T", content=text, hash=f"h{aid}", language=language,
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
    )
    db.add(a)
    db.commit()
    return a


# --------------------------------------------------------------------------- #
# detect_language: confidence-gated, never guesses
# --------------------------------------------------------------------------- #
def test_detect_language_is_confident_and_supported():
    pytest.importorskip("py3langid")  # the [analysis] lib; core install -> graceful None
    from src.analytics.langdetect import detect_language

    assert detect_language(EN) == "en"
    assert detect_language(FR) == "fr"
    # Never guesses: too short, empty, or an UNsupported language -> None.
    assert detect_language("too short") is None
    assert detect_language("") is None
    assert detect_language(None) is None
    assert detect_language(KO) is None  # detected ko (not in SUPPORTED) -> honest unknown


# --------------------------------------------------------------------------- #
# ingest wiring: deduced language drives the right stoplist; authoritative untouched
# --------------------------------------------------------------------------- #
def test_untagged_foreign_article_gets_deduced_language_and_right_stoplist(db):
    pytest.importorskip("py3langid")
    a = _art(db, 1, FR, language=None)  # untagged
    index_article(db, a, extractor=BaselineExtractor())
    assert a.language is None              # authoritative stays None (never overwritten)
    assert a.detected_language == "fr"     # the deduced SECONDARY language
    kws = {k.normalized_term: k.language for k in db.query(Keyword).all()}
    # The keyword is now labelled French (out of the "?" bucket), and French function
    # words were FILTERED (the §2.6 win) instead of leaking under the English fallback.
    assert kws.get("gouvernement") == "fr"
    for fw in ("dans", "avec", "pour", "entre", "des"):
        assert fw not in kws, f"French function word leaked: {fw}"


def test_authoritative_language_is_never_overwritten(db):
    # An article WITH an authoritative language must not be re-detected / changed.
    a = _art(db, 1, FR, language="en")  # mis-tagged on purpose
    index_article(db, a, extractor=BaselineExtractor())
    assert a.language == "en"            # untouched
    assert a.detected_language is None   # detection skipped entirely


def test_unknown_language_stays_none(db):
    # A short / undetectable untagged article keeps an honest unknown language.
    a = _art(db, 1, "Short.", language=None)
    index_article(db, a, extractor=BaselineExtractor())
    assert a.language is None and a.detected_language is None
