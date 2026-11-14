"""Every date-extraction path hands the extractor the article's own language (R697).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

C16 / RN1 (a): the pooled re-index handed ``extract_dates`` the keyword extractor's
``lang or "en"`` stoplist pick, while the inline store, the collector and the ingest
precompute all pass ``article.language``. An untagged article therefore got English
month and numeric-order rules (``03/04/2024`` read as 4 March) only when the re-index
ran in the pool, so re-indexing the same article twice could store different dates.
Now every path passes the article's own column; an unknown language uses only the
language-neutral patterns, and the stored tag records that no language was known.
"""

from __future__ import annotations

from datetime import UTC, datetime

import src.analytics.reindex_parallel as rp
from src.analytics.extract import BaselineExtractor
from src.analytics.store import reindex_all_batch
from src.database.models import ArticleMentionedDate
from src.timemap.dateextract import extract_dates
from src.timemap.datestore import (
    EXTRACTOR_KNOWN_LANGUAGE,
    EXTRACTOR_NO_LANGUAGE,
    store_for_article,
)
from tests.test_mention_diff_write import _article, _session

# ``03/04/2024`` is a date only under a language that fixes the numeric order; the
# spelled-out date resolves in any language.
TEXT = "The ruling of 03/04/2024 stands, the court said. It was signed on 3 March 2024. " * 3
ANCHOR = "2024-05-01"


def _pooled_dates(ctx) -> set[str]:
    rp._worker_extractor = BaselineExtractor()
    try:
        _aid, _t, _s, _l, err, www = rp._worker_compute(1, TEXT, "t", "en", None, ctx)
    finally:
        rp._worker_extractor = None
    assert err is None, err
    return {d["date"] for d in www["dates"]}


def test_the_pool_does_not_read_an_untagged_article_as_english():
    assert _pooled_dates((None, ANCHOR, None, None)) == {"2024-03-03"}


def test_the_pool_uses_a_known_language():
    assert _pooled_dates((None, ANCHOR, None, "en")) == {"2024-03-03", "2024-03-04"}


def test_a_context_without_the_language_slot_is_unknown_never_english():
    assert _pooled_dates((None, ANCHOR, None)) == {"2024-03-03"}


def test_a_full_reindex_hands_the_pool_the_articles_own_language(monkeypatch):
    s = _session()
    untagged = _article(s, "u", language=None)
    tagged = _article(s, "t", language="fr")
    for a in (untagged, tagged):
        a.content = TEXT
    s.commit()

    seen: list[tuple] = []
    orig = rp.precompute_batch

    def _spy(tasks, **kw):
        seen.extend(tasks)
        return orig(tasks, **kw)

    monkeypatch.setattr(rp, "precompute_batch", _spy)
    reindex_all_batch(s, extractor=BaselineExtractor(), limit=50, scope="full")
    by_id = {t[0]: t for t in seen}
    assert by_id[untagged.id][3] == "en"  # the stoplist pick is unchanged...
    assert by_id[untagged.id][5][3] is None  # ...but dates no longer inherit it
    assert by_id[tagged.id][5][3] == "fr"

    # The pooled answer is the inline answer, article by article.
    for a in (untagged, tagged):
        pooled = _pooled_dates(by_id[a.id][5])
        inline = {d["date"] for d in extract_dates(
            TEXT, anchor=datetime.fromisoformat(by_id[a.id][5][1]).date(), language=a.language
        )}
        assert pooled == inline, (a.language, pooled, inline)


def test_the_stored_tag_records_that_no_language_was_known():
    s = _session()
    untagged = _article(s, "u", language=None)
    tagged = _article(s, "t", language="en")
    for a in (untagged, tagged):
        a.content = TEXT
        a.published_at = datetime(2024, 5, 1, tzinfo=UTC)
    s.commit()
    store_for_article(s, untagged)
    store_for_article(s, tagged)
    got = {
        (r.article_id, r.mentioned_on.isoformat()): r.extractor
        for r in s.query(ArticleMentionedDate).all()
    }
    assert got == {
        (untagged.id, "2024-03-03"): EXTRACTOR_NO_LANGUAGE,
        (tagged.id, "2024-03-03"): EXTRACTOR_KNOWN_LANGUAGE,
        (tagged.id, "2024-03-04"): EXTRACTOR_KNOWN_LANGUAGE,
    }, got


def test_the_marker_fits_the_column():
    assert len(EXTRACTOR_NO_LANGUAGE) <= ArticleMentionedDate.__table__.c.extractor.type.length


def _tag(s, article, on, *, status="candidate", extractor=EXTRACTOR_KNOWN_LANGUAGE):
    from datetime import date

    s.add(ArticleMentionedDate(
        article_id=article.id, mentioned_on=date.fromisoformat(on), precision="day",
        snippet="03/04/2024", confidence=0.9, extractor=extractor, status=status,
    ))
    s.commit()


def _stored(s, article) -> dict[str, tuple[str, str]]:
    return {
        r.mentioned_on.isoformat(): (r.status, r.extractor)
        for r in s.query(ArticleMentionedDate).filter_by(article_id=article.id).all()
    }


def _untagged_with_old_english_guess(s):
    """An untagged article as an earlier pooled re-index left it: 03/04/2024 read as
    4 March under an English guess, and the spelled-out date under the old label."""
    a = _article(s, "u", language=None)
    a.content = TEXT
    a.published_at = datetime(2024, 5, 1, tzinfo=UTC)
    s.commit()
    _tag(s, a, "2024-03-04")
    _tag(s, a, "2024-03-03")
    return a


def test_a_reindex_removes_a_date_guessed_under_english():
    s = _session()
    a = _untagged_with_old_english_guess(s)
    store_for_article(s, a)
    assert _stored(s, a) == {"2024-03-03": ("candidate", EXTRACTOR_NO_LANGUAGE)}


def test_a_human_decision_on_a_guessed_date_is_never_removed():
    s = _session()
    a = _untagged_with_old_english_guess(s)
    s.query(ArticleMentionedDate).filter_by(article_id=a.id).delete()
    s.commit()
    _tag(s, a, "2024-03-04", status="confirmed")
    _tag(s, a, "2024-02-01", status="rejected")
    store_for_article(s, a)
    assert _stored(s, a) == {
        "2024-03-04": ("confirmed", EXTRACTOR_KNOWN_LANGUAGE),
        "2024-02-01": ("rejected", EXTRACTOR_KNOWN_LANGUAGE),
        "2024-03-03": ("candidate", EXTRACTOR_NO_LANGUAGE),
    }


def test_another_extractors_tag_is_never_removed():
    s = _session()
    a = _untagged_with_old_english_guess(s)
    _tag(s, a, "2023-01-09", extractor="llm")
    store_for_article(s, a)
    got = _stored(s, a)
    assert got["2023-01-09"] == ("candidate", "llm")
    assert "2024-03-04" not in got


def test_a_second_store_changes_nothing():
    s = _session()
    a = _untagged_with_old_english_guess(s)
    store_for_article(s, a)
    first = _stored(s, a)
    assert store_for_article(s, a) == 0
    assert _stored(s, a) == first
