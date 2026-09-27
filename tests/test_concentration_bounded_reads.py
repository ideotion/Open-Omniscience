"""The Home cards read only the keyword groups they test, not a whole window of them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIELD CASE (crash bundle, 2026-09-26, a 3.9 GB machine): the fatal stretch was a
burst of about 15 M Python objects and 930 MB in 45 seconds, during collection. The
briefing refresh runs after every pass and whenever Home finds its cache stale, and
MEASURED on generated corpora its flooded-topic card was the one read that grew faster
than the corpus: 26 MB at 10k articles, 174 MB at 40k. It fetched every (source,
keyword) pair of an 84-day baseline, 740k of them at 40k articles, to test 74. On a
200k-article corpus that is a few million pairs at about four objects each: the size of
the burst, though the bundle does not record which code made it.

Four readers now ask only for what their own filters can keep: the flood and bury
detectors put their count floors in a HAVING, the flood detector reads a prior share only
for a pair that passed its recent filters, and ``trending`` and the emergence detector
keep a group only when their loop would read it (``src.database.query.grouped_counts``).

Two kinds of test, because each alone proves too little:

* SAME ANSWER. Each reader runs twice on random corpora, once as shipped and once with
  every filter switched off, which is the old shape: fetch every group, let the loop
  skip. The two answers must be equal in full, order included. A filter that dropped a
  group the loop reads would give a prior count of 0 or a missing candidate and differ.
* MEMORY. ``tracemalloc`` peaks at N and 4N on a corpus whose answer stays the same size.
  The filtered reader must stay flat, and the unfiltered one must grow, which is what
  shows the corpus exercises the defect at all.
"""

from __future__ import annotations

import gc
import random
import tracemalloc
from datetime import date, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Query, sessionmaker

from src.analytics import concentration
from src.analytics.concentration import find_buried_topics, find_flooded_topics
from src.analytics.emergence import find_manufactured_emergence
from src.analytics.queries import trending, trending_windows
from src.database import query as query_mod
from src.database.models import Base

TODAY = date.today()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / 'c.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _unfiltered(monkeypatch) -> None:
    """Switch every new filter off: the readers fetch every group, as they used to."""
    monkeypatch.setattr(Query, "having", lambda self, *a, **k: self)
    monkeypatch.setattr(
        concentration,
        "_flood_pairs_to_test",
        lambda chunk, recent_kw_by_source, *a, **k: {
            sid: set(recent_kw_by_source[sid]) for sid in chunk if recent_kw_by_source.get(sid)
        },
    )
    real = query_mod.grouped_counts
    monkeypatch.setattr(
        query_mod, "grouped_counts", lambda session, stmt, keep: real(session, stmt, lambda k, v: True)
    )


# --------------------------------------------------------------------------- #
# Random corpora
# --------------------------------------------------------------------------- #
def _random_corpus(s, seed: int) -> None:
    rng = random.Random(seed)
    n_sources, n_keywords, n_articles = 14, 1200, 1600
    fresh = range(n_keywords + 1, n_keywords + 31)  # seen only this week: emergence
    for sid in range(1, n_sources + 1):
        s.execute(
            sa.text("INSERT INTO sources (id, name, domain, language) VALUES (:i, :n, :d, :l)"),
            {"i": sid, "n": f"S{sid}", "d": f"s{sid}.test", "l": rng.choice(["en", "fr"])},
        )
    for kid in range(1, fresh[-1] + 1):
        s.execute(
            sa.text(
                "INSERT INTO keywords (id, term, normalized_term, language) VALUES (:i, :t, :t, :l)"
            ),
            {"i": kid, "t": f"kwz{kid}", "l": rng.choice(["en", "fr", None])},
        )
    # Each source has a few favourite keywords it leans on; favourites shift with time,
    # so some sources flood a topic recently that they barely carried before.
    favourites = {sid: rng.sample(range(1, 200), 6) for sid in range(1, n_sources + 1)}
    rows = []
    for aid in range(1, n_articles + 1):
        sid = rng.randint(1, n_sources)
        age = int(rng.triangular(0, 110, 0))
        day = TODAY - timedelta(days=age)
        s.execute(
            sa.text(
                "INSERT INTO articles (id, url, canonical_url, source_id, content, hash, language) "
                "VALUES (:i, :u, :u, :s, 'x', :h, 'en')"
            ),
            {"i": aid, "u": f"https://s{sid}.test/{aid}", "s": sid, "h": f"h{aid}"},
        )
        fav = favourites[sid][:3] if age > 7 else favourites[sid][3:]
        kids = set(rng.sample(fav, rng.randint(0, 2)))
        kids |= {min(n_keywords, int(rng.paretovariate(1.2))) for _ in range(rng.randint(1, 6))}
        kids |= {rng.randint(1, n_keywords) for _ in range(rng.randint(0, 8))}
        if age < 7 and rng.random() < 0.4:
            kids.add(rng.choice(fresh))
        for kid in kids:
            rows.append({"a": aid, "k": kid, "s": sid, "d": day, "c": rng.randint(1, 3)})
    # Two thin sources whose baselines sit at and just under the flood detector's floor
    # of 3 prior articles, so a pair of theirs is tested or skipped on that floor alone.
    aid = n_articles
    for sid, n_prior in ((n_sources + 1, 3), (n_sources + 2, 2)):
        s.execute(
            sa.text("INSERT INTO sources (id, name, domain, language) VALUES (:i, :n, :d, 'en')"),
            {"i": sid, "n": f"S{sid}", "d": f"s{sid}.test"},
        )
        # Its topic is in every recent article and in the first prior one, so its prior
        # share is not 0 and reading it as 0 would move the z.
        for n, age in enumerate([40] * n_prior + [2] * 5):
            aid += 1
            s.execute(
                sa.text(
                    "INSERT INTO articles (id, url, canonical_url, source_id, content, hash, "
                    "language) VALUES (:i, :u, :u, :s, 'x', :h, 'en')"
                ),
                {"i": aid, "u": f"https://s{sid}.test/{aid}", "s": sid, "h": f"h{aid}"},
            )
            kids = {rng.randint(1, 40)}
            if age == 2 or n == 0:
                kids.add(sid % 7 + 1)
            for kid in kids:
                rows.append({"a": aid, "k": kid, "s": sid,
                             "d": TODAY - timedelta(days=age), "c": 1})
    s.execute(
        sa.text(
            "INSERT INTO keyword_mentions (article_id, keyword_id, source_id, observed_on, count) "
            "VALUES (:a, :k, :s, :d, :c)"
        ),
        rows,
    )
    s.commit()


def _answers(s) -> dict:
    return {
        "flood": find_flooded_topics(
            s, min_recent_articles=3, min_prior_articles=3, min_share=0.1, z_min=0.3,
            min_recent_count=2, max_items=100_000,
        ),
        # A share floor of 0 makes every recent pair of a qualifying source a pair to
        # test, so the prior read spans several 400-id chunks.
        "flood-every-pair": find_flooded_topics(
            s, min_recent_articles=1, min_prior_articles=1, min_share=0.0, z_min=-50.0,
            min_recent_count=1, max_items=100_000,
        ),
        # Every topic that clears the floors is tested (no top-N cut), so a floor that
        # moved by one changes the family of tests and so every q-value.
        "bury": find_buried_topics(
            s, min_source_articles=5, min_corpus_articles=4, min_corpus_sources=2,
            min_corpus_share=0.005, z_min=0.2, fdr_q=0.9, max_topics=100_000,
            max_items=100_000,
        ),
        "emergence": find_manufactured_emergence(
            s, max_prior=1, min_recent_articles=2, min_sources=2, max_candidates=100_000,
            max_items=100_000,
        ),
        "trending": trending(s, window_days=7, baseline_days=30, min_recent=2, limit=100_000),
        "trending-24h": trending(s, window_days=1, baseline_days=7, min_recent=1, limit=100_000),
        "trending-country": trending(
            s, window_days=7, baseline_days=30, min_recent=2, limit=100_000, country="xx"
        ),
        "trending-windows": trending_windows(s, limit=50, series_top=3),
    }


def _sizes(answers: dict) -> dict:
    out = {}
    for name, a in answers.items():
        if "windows" in a:
            out[name] = sum(len(w["terms"]) for w in a["windows"])
        else:
            out[name] = len(a.get("items", a.get("terms", [])))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_every_reader_gives_the_answer_it_gave_when_it_read_everything(db, monkeypatch, seed):
    _random_corpus(db, seed)
    tested: list[int] = []
    real_pairs = concentration._flood_pairs_to_test

    def spy(*a, **k):
        wanted = real_pairs(*a, **k)
        tested.append(len({kid for kids in wanted.values() for kid in kids}))
        return wanted

    monkeypatch.setattr(concentration, "_flood_pairs_to_test", spy)
    shipped = _answers(db)
    db.rollback()
    _unfiltered(monkeypatch)
    everything = _answers(db)
    assert shipped == everything
    sizes = _sizes(shipped)
    # A comparison of two empty answers proves nothing: each reader must have found
    # something on this corpus (the country-scoped trending is empty by design, which
    # pins that the country filter still reaches the query).
    assert all(sizes[name] > 0 for name in sizes if name != "trending-country"), sizes
    assert sizes["trending-country"] == 0
    # ... and the prior read of the flood detector had to span several 400-id chunks.
    assert max(tested) > 400, tested


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
def _peak(fn) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _flood_corpus(s, tail: int) -> None:
    """Ten sources, each flooding one keyword this week, plus ``tail`` one-article
    keywords per source in the baseline and in the week: the answer stays ten items
    while the (source, keyword) pairs grow with ``tail``."""
    s.execute(sa.text("DELETE FROM keyword_mentions"))
    s.execute(sa.text("DELETE FROM keywords"))
    s.execute(sa.text("DELETE FROM sources"))
    for sid in range(1, 11):
        s.execute(
            sa.text("INSERT INTO sources (id, name, domain) VALUES (:i, :n, :d)"),
            {"i": sid, "n": f"S{sid}", "d": f"s{sid}.test"},
        )
        s.execute(
            sa.text("INSERT INTO keywords (id, term, normalized_term) VALUES (:i, :t, :t)"),
            {"i": sid, "t": f"floodz{sid}"},
        )
    recent = (TODAY - timedelta(days=2)).isoformat()
    prior = (TODAY - timedelta(days=40)).isoformat()
    # Per source: 10 recent articles all on its flood keyword, 20 prior articles on none.
    s.execute(sa.text(
        "WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < 99) "
        "INSERT INTO keyword_mentions (article_id, keyword_id, source_id, observed_on, count) "
        "SELECT i + 1, (i / 10) + 1, (i / 10) + 1, :d, 1 FROM n"
    ), {"d": recent})
    # The tail: one mention per (source, tail keyword) in the baseline and in the week,
    # on that source's existing articles so the article counts do not move.
    s.execute(sa.text(
        "WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < :m - 1) "
        "INSERT INTO keyword_mentions (article_id, keyword_id, source_id, observed_on, count) "
        "SELECT 100000 + (i % 10) * 20 + ((i / 10) % 20), 1000 + i / 10, (i % 10) + 1, :d, 1 "
        "FROM n"
    ), {"m": 10 * tail, "d": prior})
    s.execute(sa.text(
        "WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < :m - 1) "
        "INSERT INTO keyword_mentions (article_id, keyword_id, source_id, observed_on, count) "
        "SELECT (i % 10) * 10 + ((i / 10) % 10) + 1, 1000 + i / 10, (i % 10) + 1, :d, 1 FROM n"
    ), {"m": 10 * tail, "d": recent})
    s.commit()


_TAIL = 2_000


def _flood_peaks(s) -> tuple[int, int, dict]:
    _flood_corpus(s, _TAIL)
    find_flooded_topics(s, max_items=100)  # warm the statement cache before measuring
    small = _peak(lambda: find_flooded_topics(s, max_items=100))
    _flood_corpus(s, 4 * _TAIL)
    found: dict = {}
    large = _peak(lambda: found.update(find_flooded_topics(s, max_items=100)))
    return small, large, found


def test_the_flood_reader_does_not_hold_every_pair_of_the_baseline(db):
    small, large, found = _flood_peaks(db)
    assert found["count"] == 10  # the answer stayed the same size
    assert large < 2.0 * small, (small, large)  # measured 1.02x


def test_the_unfiltered_flood_reader_grows_with_the_pairs(db, monkeypatch):
    """The control: with the filters off, the same corpus does grow the peak, so the
    flat reading above is the fix and not a corpus that never exercised it."""
    _unfiltered(monkeypatch)
    small, large, found = _flood_peaks(db)
    assert found["count"] == 10
    assert large > 2.5 * small, (small, large)  # measured 4.0x


def _trend_corpus(s, tail: int) -> None:
    """Five keywords rising this week, plus ``tail`` keywords seen once this week and
    once in the baseline, which the ``min_recent`` floor never keeps."""
    s.execute(sa.text("DELETE FROM keyword_mentions"))
    s.execute(sa.text("DELETE FROM keywords"))
    for kid in range(1, 6):
        s.execute(
            sa.text("INSERT INTO keywords (id, term, normalized_term) VALUES (:i, :t, :t)"),
            {"i": kid, "t": f"risez{kid}"},
        )
    recent = (TODAY - timedelta(days=1)).isoformat()
    prior = (TODAY - timedelta(days=20)).isoformat()
    s.execute(sa.text(
        "WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < 49) "
        "INSERT INTO keyword_mentions (article_id, keyword_id, observed_on, count) "
        "SELECT i + 1, (i % 5) + 1, :d, 1 FROM n"
    ), {"d": recent})
    for day, base in ((recent, 1_000_000), (prior, 2_000_000)):
        s.execute(sa.text(
            "WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < :m - 1) "
            "INSERT INTO keyword_mentions (article_id, keyword_id, observed_on, count) "
            "SELECT :b + i, 100 + i, :d, 1 FROM n"
        ), {"m": tail, "d": day, "b": base})
    s.commit()


def _trend_peaks(s) -> tuple[int, int, dict]:
    _trend_corpus(s, 20_000)
    trending(s, window_days=7, baseline_days=30, min_recent=2)  # warm the statement cache
    small = _peak(lambda: trending(s, window_days=7, baseline_days=30, min_recent=2))
    _trend_corpus(s, 80_000)
    found: dict = {}
    large = _peak(lambda: found.update(trending(s, window_days=7, baseline_days=30, min_recent=2)))
    return small, large, found


def test_trending_keeps_only_the_keywords_it_scores(db):
    small, large, found = _trend_peaks(db)
    assert found["count"] == 5
    # The count of keywords seen this week is still every one of them.
    assert found["keywords_with_recent_mentions"] == 5 + 80_000
    # Measured 1.00x: what is left is one fetch chunk of rows, the same at any size.
    assert large < 1.5 * small, (small, large)


def test_unfiltered_trending_grows_with_the_window(db, monkeypatch):
    """The control. Measured 2.5x, not 4x, because the unfiltered path here already
    streams its rows and holds only the two dicts: the old ``.all()`` held both."""
    _unfiltered(monkeypatch)
    small, large, found = _trend_peaks(db)
    assert found["count"] == 5
    assert large > 2.0 * small, (small, large)


# --------------------------------------------------------------------------- #
# grouped_counts itself
# --------------------------------------------------------------------------- #
def test_grouped_counts_keeps_order_counts_every_group_and_closes_on_error(db):
    db.execute(
        sa.text(
            "INSERT INTO keyword_mentions (article_id, keyword_id, observed_on, count) "
            "VALUES (1, 3, :d, 2), (2, 1, :d, 5), (3, 2, :d, 1), (4, 3, :d, 4)"
        ),
        {"d": TODAY},
    )
    db.commit()
    from sqlalchemy import func, select

    from src.database.models import KeywordMention

    stmt = select(KeywordMention.keyword_id, func.sum(KeywordMention.count)).group_by(
        KeywordMention.keyword_id
    )
    kept, groups = query_mod.grouped_counts(db, stmt, lambda k, v: v >= 5)
    assert (list(kept.items()), groups) == ([(1, 5), (3, 6)], 3)

    def boom(k, v):
        raise RuntimeError("keep failed")

    opened = []
    real_execute = db.execute

    def spy(*a, **k):
        opened.append(real_execute(*a, **k))
        return opened[-1]

    db.execute = spy
    try:
        with pytest.raises(RuntimeError):
            query_mod.grouped_counts(db, stmt, boom)
    finally:
        del db.execute
    # A statement left open would pin SQLite's read mark until garbage collection.
    assert opened and opened[-1].closed
