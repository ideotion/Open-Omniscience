"""R101: a quarantined article leaves every keyword figure, the language series and the equilibrium lever.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ruling (2026-09-30, the question ``D22`` / ``PRH-06``) asks for ONE slice: the incremental counters (with deltas
when an article is stamped AND when it is un-stamped), the rollup and columnar read side and their live fallbacks
(so one call never answers differently depending on which served it), the per-language series and the lever that
must move with it, and the effect on ``furniture_share`` measured first.

Each test below reproduces the gap on the code before the slice: the corpus is three articles that mention the
same word, and one of them is stamped. Before R101 every served count still said three.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import queries as q
from src.analytics.extract import BaselineExtractor
from src.analytics.store import (
    backfill_keyword_counters,
    index_article,
    reconcile_keyword_counters,
    shift_keyword_counters_for_quarantine,
)
from src.database.derived_views import ensure_derived_views
from src.database.models import Article, Base, Keyword, KeywordMention, Source

WORD = "zanzibarite"
BODY = (
    f"The {WORD} survey found {WORD} deposits near the coast. Officials said the {WORD} "
    "find would be studied by a team of geologists over the coming months."
)


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")  # the live path; the rollup has its own tests below
    engine = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    ensure_derived_views(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr", language="en"))
    s.commit()
    yield s
    s.close()


def _add(db, n: int, *, language: str = "en", when: datetime | None = None, quarantined: bool = False) -> Article:
    when = when or datetime.now(UTC) - timedelta(days=1)
    a = Article(
        url=f"https://x.test/news/{n}",
        canonical_url=f"https://x.test/news/{n}",
        source_id=1,
        title=f"Story {n}",
        content=BODY,
        hash=f"h{n}",
        country="fr",
        language=language,
        published_at=when,
        created_at=when,
        quarantined=quarantined or None,
    )
    db.add(a)
    db.commit()
    return a


def _corpus(db) -> list[Article]:
    arts = [_add(db, n) for n in range(3)]
    for a in arts:
        index_article(db, a, extractor=BaselineExtractor())
    return arts


def _stamp(db, article: Article) -> None:
    """Stamp one article the way the quarantine job does: the stamp and the counter shift in one transaction."""
    db.query(Article).filter(Article.id == article.id).update({"quarantined": True}, synchronize_session=False)
    shift_keyword_counters_for_quarantine(db, [article.id], quarantined=True)
    db.commit()


def _unstamp(db, article: Article) -> None:
    db.query(Article).filter(Article.id == article.id).update({"quarantined": False}, synchronize_session=False)
    shift_keyword_counters_for_quarantine(db, [article.id], quarantined=False)
    db.commit()


def _kw(db) -> Keyword:
    db.expire_all()
    kw = db.query(Keyword).filter(Keyword.normalized_term == WORD).one()
    return kw


def _live_unquarantined(db, kid: int) -> tuple[int, int]:
    """The counters' truth under R101: the GROUP BY over mentions of articles that are not quarantined."""
    m, a = (
        db.query(func.sum(KeywordMention.count), func.count(func.distinct(KeywordMention.article_id)))
        .join(Article, Article.id == KeywordMention.article_id)
        .filter(KeywordMention.keyword_id == kid, Article.quarantined.isnot(True))
        .one()
    )
    return int(m or 0), int(a or 0)


def _row(result: dict) -> dict:
    return next(t for t in result["terms"] if t["normalized"] == WORD)


# --------------------------------------------------------------------------- counters


def test_stamping_an_article_takes_its_mentions_out_of_the_counters(db):
    arts = _corpus(db)
    kw = _kw(db)
    before = (kw.mention_count, kw.article_count)
    assert before[1] == 3
    _stamp(db, arts[0])
    kw = _kw(db)
    assert kw.article_count == 2
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)
    assert kw.mention_count == before[0] - before[0] // 3


def test_unstamping_puts_them_back_exactly(db):
    arts = _corpus(db)
    before = (_kw(db).mention_count, _kw(db).article_count)
    _stamp(db, arts[1])
    _unstamp(db, arts[1])
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == before


def test_reindexing_a_quarantined_article_moves_no_counter(db):
    arts = _corpus(db)
    _stamp(db, arts[2])
    after_stamp = (_kw(db).mention_count, _kw(db).article_count)
    index_article(db, db.get(Article, arts[2].id), extractor=BaselineExtractor())
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == after_stamp == _live_unquarantined(db, kw.id)
    # Its mention rows are still there: quarantine is reversible, so the rows stay.
    assert db.query(KeywordMention).filter(KeywordMention.article_id == arts[2].id).count() > 0


def test_an_article_stored_already_quarantined_never_enters_the_counters(db):
    _corpus(db)
    a = _add(db, 9, quarantined=True)
    index_article(db, a, extractor=BaselineExtractor())
    kw = _kw(db)
    assert kw.article_count == 3
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)


@pytest.mark.parametrize("repair", ["reconcile", "backfill"])
def test_the_authoritative_repairs_leave_quarantined_articles_out_too(db, repair):
    """Otherwise the next reconcile would put back what the stamp took out, and report it as drift repaired."""
    arts = _corpus(db)
    _stamp(db, arts[0])
    want = (_kw(db).mention_count, _kw(db).article_count)
    if repair == "reconcile":
        out = reconcile_keyword_counters(db, budget_s=0)
        assert out["drift_repaired"] == 0
    else:
        backfill_keyword_counters(db)
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == want


def test_the_quarantine_job_write_path_moves_the_counters_and_bumps_the_epoch(db):
    """The real stamp path: a thin homepage body is a ``url_homepage`` candidate."""
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.quarantine_job import default_quarantine_candidates_batch

    _corpus(db)
    junk = Article(
        url="https://x.test/", canonical_url="https://x.test/", source_id=1, title="Home",
        content=f"{WORD} {WORD} menu", hash="junk", country="fr", language="en", word_count=3,
        published_at=datetime.now(UTC) - timedelta(days=1), created_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(junk)
    db.commit()
    index_article(db, junk, extractor=BaselineExtractor())
    with_junk = _kw(db).article_count
    epoch0 = get_corpus_epoch(db)

    out = default_quarantine_candidates_batch(db, article_ids=[junk.id], write=True)
    assert out["newly_written"] == 1, out
    kw = _kw(db)
    assert kw.article_count == with_junk - 1
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)
    assert get_corpus_epoch(db) == epoch0 + 1  # the rollup's change gate cannot see a stamp otherwise

    # Idempotent: a second run over the same article stamps nothing and subtracts nothing.
    again = default_quarantine_candidates_batch(db, article_ids=[junk.id], write=True)
    assert again["newly_written"] == 0
    assert _kw(db).article_count == with_junk - 1
    assert get_corpus_epoch(db) == epoch0 + 1


def test_a_stamp_another_path_landed_first_is_not_subtracted_twice(db, monkeypatch):
    """``to_write`` is read before the write gate; an import's screening may stamp the same article in between. Only
    the UPDATE that really changes the row may move the counters."""
    from src.analytics.quarantine_job import default_quarantine_candidates_batch
    from src.database import writer

    _corpus(db)
    junk = Article(
        url="https://x.test/", canonical_url="https://x.test/", source_id=1, title="Home",
        content=f"{WORD} {WORD} menu", hash="junk2", country="fr", language="en", word_count=3,
        published_at=datetime.now(UTC) - timedelta(days=1), created_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(junk)
    db.commit()
    index_article(db, junk, extractor=BaselineExtractor())
    before = _kw(db).article_count

    real = writer.connection_first
    raced = []

    def other_path_first(session):
        if not raced:  # the other stamping path finishes between the read and the gate
            raced.append(1)
            _stamp(session, junk)
        return real(session)

    monkeypatch.setattr(writer, "connection_first", other_path_first)
    out = default_quarantine_candidates_batch(db, article_ids=[junk.id], write=True)
    assert raced and out["newly_written"] == 0
    kw = _kw(db)
    assert kw.article_count == before - 1, "subtracted once, by the path that stamped it"
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)


# --------------------------------------------------------------------------- served counts (live)


def test_top_terms_corpus_wide_and_windowed_agree_and_leave_it_out(db):
    arts = _corpus(db)
    _stamp(db, arts[0])
    wide = _row(q.top_terms(db, limit=50))
    windowed = _row(q.top_terms(db, days=30, limit=50))
    per_country = _row(q.top_terms(db, days=30, country="fr", limit=50))
    closed = _row(q.top_terms(db, days=30, end=date.today() + timedelta(days=1), limit=50))
    assert wide["articles"] == windowed["articles"] == per_country["articles"] == closed["articles"] == 2
    assert wide["mentions"] == windowed["mentions"] == per_country["mentions"] == closed["mentions"]


def test_trend_bars_leave_it_out_and_the_brush_still_names_it(db):
    arts = _corpus(db)
    full = q.trend(db, WORD, bucket="day")
    _stamp(db, arts[0])
    t = q.trend(db, WORD, bucket="day")
    assert t["articles"] == 2
    assert t["total"] == full["total"] - full["total"] // 3
    lo = date.today() - timedelta(days=30)
    brush = q.trend_range_article_ids(db, WORD, start=lo, end=date.today(), bucket="day")
    assert brush["articles"] == 2
    assert brush["mentions"] == t["total"]  # the selection's total is the bars' own total
    assert brush["quarantined_excluded"] == 1  # the population the bars no longer count, stated


def test_trending_live_counts_leave_it_out(db, monkeypatch):
    """``trending``'s live window sums go through ``windowed_group_counts`` with the shared filter."""
    from src.database import query as dbq

    seen: list[tuple] = []
    real = dbq.windowed_group_counts

    def spy(session, **kw):
        out = real(session, **kw)
        seen.append(out)
        return out

    monkeypatch.setattr(dbq, "windowed_group_counts", spy)
    arts = _corpus(db)
    _stamp(db, arts[0])
    q.trending(db, window_days=7, baseline_days=7, min_recent=1)
    kid = _kw(db).id
    recent = [kept for kept, _groups in seen if kid in kept]
    assert recent, "the live window was never read"
    assert recent[0][kid] == _kw(db).mention_count  # the window sum equals the (filtered) counter


def test_supergroup_live_fallbacks_leave_it_out(db):
    from src.analytics import supergroup_rising, supergroup_stats

    arts = _corpus(db)
    _stamp(db, arts[0])
    kw = _kw(db)
    lo, hi = date.today() - timedelta(days=30), date.today() + timedelta(days=1)
    assert supergroup_stats._per_id_mentions(db, [kw.id])[kw.id] == kw.mention_count
    assert supergroup_stats._windowed_sum(db, [kw.id], lo, hi) == kw.mention_count
    total = db.query(func.sum(Keyword.mention_count)).scalar()
    assert supergroup_rising._corpus_volume(db, lo, hi) == total
    assert sum(p["count"] for p in supergroup_stats.daily_series(db, [kw.id], days=30)) == kw.mention_count


# --------------------------------------------------------------------------- the rollup and the day counts
# The DuckDB rollup's build, tail and parity are pinned in tests/test_rollup_parity_bound.py (a duckdb file a blocking CI job runs).


def test_the_day_counts_table_leaves_it_out_built_and_on_a_stale_day(tmp_path):
    """``trending``'s second store: the per-day table and the stale days it reads live (R623, R625)."""
    from tests.test_day_counts import HI, LO, _build, _corpus, _put_epoch_back, _served

    eng, s, ex = _corpus(tmp_path)
    arts = s.query(Article).order_by(Article.id).all()
    s.query(Article).filter(Article.id == arts[0].id).update({"quarantined": True}, synchronize_session=False)
    s.commit()
    _build(eng)

    def live_unquarantined():
        return {
            int(k): int(v)
            for k, v in s.query(KeywordMention.keyword_id, func.sum(KeywordMention.count))
            .join(Article, Article.id == KeywordMention.article_id)
            .filter(KeywordMention.observed_on >= LO, KeywordMention.observed_on <= HI, Article.quarantined.isnot(True))
            .group_by(KeywordMention.keyword_id)
        }

    assert _served(s) == live_unquarantined()

    # A day made stale (a new article lands on it: the tail) is read live, and its quarantined rows stay out there too.
    from tests.test_day_counts import _add

    late = _add(s, ex, 50, 2)
    s.query(Article).filter(Article.id == late.id).update({"quarantined": True}, synchronize_session=False)
    s.commit()
    _put_epoch_back(s, eng)
    assert _served(s) == live_unquarantined()


# --------------------------------------------------------------------------- language series and the lever


def test_the_language_series_and_the_lever_leave_it_out_together(db):
    from src.database.snapshots import article_counts_by_language
    from src.scheduler.equilibrium import corpus_language_shares

    now = datetime.now(UTC)
    for n in range(3):
        _add(db, 100 + n, language="en", when=now - timedelta(hours=2))
    junk = [_add(db, 200 + n, language="de", when=now - timedelta(hours=2)) for n in range(3)]
    for a in junk:
        db.query(Article).filter(Article.id == a.id).update({"quarantined": True}, synchronize_session=False)
    db.commit()

    shares = corpus_language_shares(db)
    assert shares == {"en": 1.0}
    series = article_counts_by_language(db, days=2, now=now)
    langs = {s["language"]: s["total"] for s in series["series"]}
    assert langs == {"en": 3}


# --------------------------------------------------------------------------- measured first: furniture_share


def test_furniture_share_does_not_move(db):
    """R101 asked for the effect on ``furniture_share`` (it feeds the qualification gate) to be measured first.
    It cannot move: the qualification path already drops quarantined ids before it reads any keyword, and it reads
    per-article mention rows, never the counters or the rollup this slice changes. Pinned so a later change that
    makes it read them has to look here."""
    import inspect

    from src.analytics import source_quality

    src = inspect.getsource(source_quality)
    assert "quarantined_excluded" in src and "Article.quarantined.isnot(True)" in src
    assert "Keyword.article_count" not in src and "Keyword.mention_count" not in src
    assert "rollup_serve" not in src and "columnar" not in src


def test_a_keyword_fold_moves_a_quarantined_articles_rows_but_not_the_counters(tmp_path, monkeypatch):
    """The fold (``src/analytics/keyword_fold.py``) moves every mention row of a folded keyword and moved the
    counters for each one, so it put a quarantined article's mentions back into them. Built on
    ``tests/test_keyword_fold.py``'s corpus and job helpers."""
    import tests.test_keyword_fold as kf

    eng, s = kf._corpus(tmp_path, "old.db", lemma=False, monkeypatch=monkeypatch)
    aid = s.execute(text("SELECT id FROM articles WHERE hash = 'en1'")).scalar()
    s.query(Article).filter(Article.id == aid).update({"quarantined": True}, synchronize_session=False)
    shift_keyword_counters_for_quarantine(s, [aid], quarantined=True)
    s.commit()
    kf._run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    live = {
        int(k): (int(m), int(n))
        for k, m, n in s.execute(text(
            "SELECT keyword_id, SUM(count), COUNT(*) FROM keyword_mentions"
            " WHERE article_id NOT IN (SELECT id FROM articles WHERE quarantined IS 1) GROUP BY keyword_id"
        ))
    }
    bad = [
        (int(kid), (int(mc or 0), int(ac or 0)), live.get(int(kid), (0, 0)))
        for kid, mc, ac in s.execute(text("SELECT id, mention_count, article_count FROM keywords"))
        if (int(mc or 0), int(ac or 0)) != live.get(int(kid), (0, 0))
    ]
    assert not bad, bad
    assert s.execute(text("SELECT COUNT(*) FROM keyword_mentions WHERE article_id = :a"), {"a": aid}).scalar() > 0


def test_the_upgrade_heal_subtracts_the_quarantined_articles_once_and_bumps_the_epoch(db):
    """A store written before R101 counted its quarantined articles. The one-time boot heal subtracts them, bumps the
    corpus epoch so the rollup and the day counts rebuild, and does neither twice."""
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.quarantine_transition import R101_TRANSITION_KEY, heal_r101_transition
    from src.database.models import DerivedMeta

    arts = _corpus(db)
    # The pre-R101 state: an article stamped by the old job, its mentions still in the counters.
    db.query(Article).filter(Article.id == arts[0].id).update({"quarantined": True}, synchronize_session=False)
    db.commit()
    kw = _kw(db)
    assert kw.article_count == 3, "the fixture must start as an old store does, still counting it"
    epoch = get_corpus_epoch(db)
    engine = db.get_bind()

    assert heal_r101_transition(engine)["articles"] == 1
    kw = _kw(db)
    assert kw.article_count == 2
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)
    assert get_corpus_epoch(db) == epoch + 1
    assert db.get(DerivedMeta, R101_TRANSITION_KEY) is not None

    assert heal_r101_transition(engine) == {"skipped": "done"}
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id), "a second boot must not subtract again"
    assert get_corpus_epoch(db) == epoch + 1


def test_init_db_runs_the_upgrade_heal():
    import inspect

    from src.database import session as sess

    src = inspect.getsource(sess.init_db)
    assert "heal_r101_transition(engine)" in src
    assert src.index("heal_r101_transition(engine)") < src.index("align_stamp_to_head(engine)")


def test_the_keyword_hover_stats_leave_a_quarantined_article_out(db):
    arts = _corpus(db)
    _stamp(db, arts[0])
    kw = _kw(db)
    stats = q.keyword_stats(db, WORD)
    assert (stats["mentions"], stats["articles"]) == _live_unquarantined(db, kw.id) == (kw.mention_count, kw.article_count)


def test_the_vocabulary_growth_curve_leaves_a_quarantined_article_out(db):
    from src.analytics.keyword_growth import keyword_growth_curve

    arts = _corpus(db)
    before = keyword_growth_curve(db)["totals"]
    _stamp(db, arts[0])
    after = keyword_growth_curve(db)["totals"]
    assert after["articles"] == before["articles"] - 1
    assert after["tokens"] < before["tokens"]


def test_the_upgrade_heal_on_a_store_with_no_quarantined_article_only_writes_its_marker(db):
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.quarantine_transition import R101_TRANSITION_KEY, heal_r101_transition
    from src.database.models import DerivedMeta

    _corpus(db)
    before = (_kw(db).mention_count, _kw(db).article_count)
    epoch = get_corpus_epoch(db)
    assert heal_r101_transition(db.get_bind()) == {"articles": 0}
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == before
    assert get_corpus_epoch(db) == epoch, "nothing to rebuild: the stores already agree"
    assert db.get(DerivedMeta, R101_TRANSITION_KEY) is not None


def test_a_crash_between_the_epoch_bump_and_the_subtraction_subtracts_exactly_once_on_the_next_boot(db, monkeypatch):
    """The bump commits first; the subtraction and the marker commit together. A failure after the bump leaves no
    marker and no subtraction, so the next boot does both, once."""
    from src.analytics import store
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.analytics.quarantine_transition import R101_TRANSITION_KEY, heal_r101_transition
    from src.database.models import DerivedMeta

    arts = _corpus(db)
    db.query(Article).filter(Article.id == arts[0].id).update({"quarantined": True}, synchronize_session=False)
    db.commit()
    epoch = get_corpus_epoch(db)
    before = (_kw(db).mention_count, _kw(db).article_count)

    def _boom(*a, **k):
        raise RuntimeError("power cut")

    with monkeypatch.context() as m:
        m.setattr(store, "shift_keyword_counters_for_quarantine", _boom)
        assert heal_r101_transition(db.get_bind()) == {"skipped": "error"}
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == before, "nothing subtracted"
    assert get_corpus_epoch(db) == epoch + 1, "the bump landed first"
    assert db.get(DerivedMeta, R101_TRANSITION_KEY) is None

    assert heal_r101_transition(db.get_bind())["articles"] == 1
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)
    assert heal_r101_transition(db.get_bind()) == {"skipped": "done"}
    kw = _kw(db)
    assert (kw.mention_count, kw.article_count) == _live_unquarantined(db, kw.id)
