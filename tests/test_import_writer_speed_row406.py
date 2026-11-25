"""Row 406: the single writer's per-article work got cheaper, and its results did not move.

Two changes, each pinned here against the behaviour it replaced:

- ``index_article`` inserts the keywords an article creates in ONE flush after its term loop instead of one flush per
  new keyword. The keyword ids, the baseline tags and the mention rows must be exactly what the per-keyword flush gave.
- ``script_check.own_script_share`` counts letters per distinct character. The share and the letter count must be
  exactly what the per-character loop gave.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from src.analytics import script_check as sc
from src.analytics import store
from src.analytics.extract import BaselineExtractor
from src.database.models import Article, Base, Keyword, KeywordMention, KeywordTag, Source
from tests._app_engine import app_sqlite_engine

_TEXTS = (
    "The election and the referendum dominated talks. Inflation, recession and unemployment rose. "
    "NATO and the WHO met in Geneva about sanctions and a ceasefire treaty.",
    "A second election: sanctions again, inflation again, and new words like turbine, harbour and quarry. "
    "The IMF said unemployment fell while the ECB watched recession risks.",
    "Nothing new here: election, inflation, turbine, harbour. The WHO and the IMF.",
)


def _db():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _index_all(session) -> tuple[list, list, list]:
    for i, text in enumerate(_TEXTS):
        a = Article(
            url=f"https://x.test/{i}",
            canonical_url=f"https://x.test/{i}",
            source_id=1,
            title="T",
            content=text,
            hash=f"h{i}",
            language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        session.add(a)
        session.commit()
        store.index_article(session, a, extractor=BaselineExtractor(), country="fr")
        session.commit()
    kws = [
        (k.id, k.term, k.normalized_term, k.language, k.is_entity, k.entity_type, k.is_ngram, k.ngram_size)
        for k in session.query(Keyword).order_by(Keyword.id)
    ]
    tags = [(t.id, t.keyword_id, t.axis, t.tag, t.source) for t in session.query(KeywordTag).order_by(KeywordTag.id)]
    mentions = sorted(
        (m.keyword_id, m.article_id, m.count, m.first_offset) for m in session.query(KeywordMention)
    )
    return kws, tags, mentions


def test_one_flush_per_article_gives_the_ids_tags_and_mentions_of_one_flush_per_keyword(monkeypatch):
    batched = _index_all(_db())

    real = store._get_or_create_keyword

    def _per_keyword(session, t, *, created=None, **kw):  # the behaviour before row 406: a flush for each new keyword
        return real(session, t, **kw)

    monkeypatch.setattr(store, "_get_or_create_keyword", _per_keyword)
    per_keyword = _index_all(_db())

    assert batched == per_keyword
    kws, tags, mentions = batched
    assert len(kws) > 20 and mentions
    tagged = {kid for _, kid, *_ in tags}
    by_id = {k[0]: k[2] for k in kws}
    assert {by_id[k] for k in tagged} >= {"election", "inflation", "ceasefire"}, "the baseline tags were not written"


def test_created_needs_the_prefetched_map():
    import pytest

    with pytest.raises(ValueError):
        store._get_or_create_keyword(None, None, language="en", extractor="baseline", created=[])  # type: ignore[arg-type]


def _per_character(language, text):
    allowed = sc.own_scripts(language)
    if allowed is None:
        return None
    letters = own = 0
    for ch in sc._visible_text(text)[: sc.SAMPLE_CHARS]:
        if not ch.isalpha():
            continue
        letters += 1
        if sc._script_of(ch) in allowed:
            own += 1
    return (own / letters if letters else 0.0), letters


def test_the_script_share_counted_per_distinct_character_is_the_per_character_count():
    rnd = random.Random(406)
    pools = ("abcdefXYZ éü", "новости мир", "Αθήνα", "東京ひらがなカタカナ한국", "<div class=x>", "١٢٣ عربي", "12 ., !")
    for _ in range(400):
        text = "".join(rnd.choice(rnd.choice(pools)) for _ in range(rnd.randint(0, 7000)))
        for lang in ("en", "ru", "ja", "zh", "ko", "el", "ar", "sr", None):
            assert sc.own_script_share(lang, text) == _per_character(lang, text), lang
