"""A feed's language tag that the article's own script refutes is dropped (R699, cause 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-10-06 keyword triage found Russian news tagged ``en`` (новости: 2,087 of 2,094
articles tagged English), so Russian function words became English keywords. These tests
pin the fix: a tag refuted by COUNTING the letters' script is cleared and the article is
re-deduced like an untagged one, while a tag the script cannot refute (French tagged
English, a two-script language, a short body) is left exactly as asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.script_check import own_scripts, primary_subtag, script_refutes
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, Source

RU = (
    "Правительство России в четверг представило проект бюджета на следующий год, "
    "в котором расходы на социальные программы и инфраструктуру увеличены, а дефицит "
    "должен сократиться. Министр финансов заявил журналистам, что новости о росте "
    "налогов преждевременны и что окончательное решение примет парламент осенью."
)
FR = (
    "Le gouvernement français a présenté mardi un budget consacré à la transition "
    "écologique et à la réforme des retraites, suscitant un vif débat à l'Assemblée "
    "nationale entre la majorité et l'opposition sur le financement des mesures sociales."
)
EN_QUOTING_RU = (
    "The minister answered reporters at length in English after the session, and the "
    "agency later published the full transcript together with the original statement, "
    "which read in part: «Правительство не планирует повышать налоги». Analysts said the "
    "budget would still have to pass parliament in the autumn before taking effect."
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
    if db.get(Source, 1) is None:
        db.add(Source(id=1, name="S", domain="x.test"))
    a = Article(
        id=aid, url=f"https://x/{aid}", canonical_url=f"https://x/{aid}", source_id=1,
        title="T", content=text, hash=f"h{aid}", language=language,
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
    )
    db.add(a)
    db.commit()
    return a


# --------------------------------------------------------------------------- #
# the pure check
# --------------------------------------------------------------------------- #
def test_cyrillic_text_refutes_an_english_tag():
    assert script_refutes("en", RU)
    assert script_refutes("EN-us", RU)  # region and case do not hide the tag


def test_a_same_script_mistag_is_not_refuted():
    # French tagged English: both Latin, so counting letters proves nothing.
    assert not script_refutes("en", FR)


def test_an_english_article_quoting_russian_is_not_refuted():
    assert not script_refutes("en", EN_QUOTING_RU)


def test_a_multi_script_language_is_never_judged():
    # Serbian is written in Cyrillic and in Latin: no count can refute either.
    assert own_scripts("sr") is None
    assert not script_refutes("sr", FR)
    assert not script_refutes("sr", RU)


def test_an_unknown_code_or_no_tag_is_never_judged():
    assert not script_refutes("xx", RU)
    assert not script_refutes(None, RU)
    assert not script_refutes("", RU)


def test_too_few_letters_is_never_a_refutation():
    assert not script_refutes("en", "Новости дня")


def test_japanese_and_chinese_share_han_so_neither_refutes_the_other():
    zh = "中华人民共和国国务院今天发布了关于经济发展的新政策文件，" * 8
    assert not script_refutes("ja", zh)
    assert script_refutes("zh", RU)


def test_primary_subtag():
    assert primary_subtag(" en_GB ") == "en"
    assert primary_subtag(None) == ""


# --------------------------------------------------------------------------- #
# the wiring: index_article (ingest and re-index both pass through it)
# --------------------------------------------------------------------------- #
def test_a_refuted_tag_is_cleared_and_the_article_re_deduced(db):
    pytest.importorskip("py3langid")
    a = _art(db, 1, RU, language="en")
    index_article(db, a, extractor=BaselineExtractor())
    assert a.language is None
    assert a.detected_language == "ru"
    langs = {k.normalized_term: k.language for k in db.query(Keyword).all()}
    assert langs, "the article produced no keywords at all"
    assert "en" not in set(langs.values()), langs
    # The function words the English stoplist could not catch are now caught.
    for fw in ("что", "на", "в", "и"):
        assert fw not in langs, f"Russian function word leaked: {fw}"


def test_a_refuted_tag_with_no_confident_deduction_stays_unknown(db, monkeypatch):
    import src.analytics.langdetect as ld

    monkeypatch.setattr(ld, "detect_language", lambda *a, **k: None)
    a = _art(db, 1, RU, language="en")
    index_article(db, a, extractor=BaselineExtractor())
    assert a.language is None and a.detected_language is None


def test_an_unrefuted_tag_is_left_as_asserted(db):
    a = _art(db, 1, FR, language="en")
    index_article(db, a, extractor=BaselineExtractor())
    assert a.language == "en"
    assert a.detected_language is None
