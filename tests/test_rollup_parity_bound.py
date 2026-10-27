"""The rollup parity check compares like with like: the live side stops where the build did.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-10-16 benchmark on a running install reported 8,814 mismatches and a broken distinct bound, and
every one of them was a mention the scrape committed AFTER the 856 s build had read its boundary
(``scan_bound = MAX(created_at)``): the build leaves those out on purpose while the live side kept counting
them. These tests write rows from the build's own ``on_batch`` hook (a concurrent scrape) and pin that

* the unbounded comparison shows exactly that signature, and says which way the numbers differ;
* bounded by the ``scan_bound`` the build returns, the same corpus compares exactly;
* a mismatch the bound does NOT explain (a row deleted after it was streamed, a keyword only the rollup
  still holds) stays visible, in the other direction.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.analytics import columnar
from src.monitoring import rollup_benchmark

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

TODAY = datetime.date.today().isoformat()
_LATER = "2099-01-01 00:00:00"  # after any scan bound the tests produce


def _corpus(*, created_at=True):
    """100 articles x 5 keywords, one dated mention each, in an in-memory SQLite."""
    s = Session(create_engine("sqlite://"))
    s.execute(text(
        "CREATE TABLE keywords (id INTEGER PRIMARY KEY, normalized_term TEXT, term TEXT, is_entity INT, "
        "entity_type TEXT, language TEXT, mention_count INT)"
    ))
    s.execute(text(
        "CREATE TABLE keyword_mentions (id INTEGER PRIMARY KEY, keyword_id INT, article_id INT, count INT, "
        "observed_on DATE, created_at TEXT)"
    ))
    for k in range(1, 201):
        s.execute(text("INSERT INTO keywords VALUES (:i,:t,:t,0,NULL,'en',1)"), {"i": k, "t": f"kw{k}"})
    mid = 1
    for a in range(1, 101):
        for j in range(5):
            s.execute(
                text("INSERT INTO keyword_mentions VALUES (:id,:k,:a,2,:d,:c)"),
                {"id": mid, "k": (a * 3 + j) % 200 + 1, "a": a, "d": TODAY,
                 "c": f"2026-10-16 10:00:{a % 60:02d}" if created_at else None},
            )
            mid += 1
    s.commit()
    return s, mid


def _add_mention(s, kid, article, *, created_at=_LATER):
    nid = (s.execute(text("SELECT MAX(id) FROM keyword_mentions")).scalar() or 0) + 1
    s.execute(
        text("INSERT INTO keyword_mentions VALUES (:id,:k,:a,3,:d,:c)"),
        {"id": nid, "k": kid, "a": article, "d": TODAY, "c": created_at},
    )


def _build(s, *, on_first_batch=None):
    con = columnar.connect(passphrase=None)
    seen = {"n": 0}

    def on_batch(stage, rows):
        seen["n"] += 1
        if on_first_batch is not None and seen["n"] == 1 and stage == "mentions":
            on_first_batch()
            s.commit()

    build = columnar.build_keyword_daily(con, s, batch_size=100, on_batch=on_batch)
    return con, build


def test_a_quiet_corpus_is_exact_bounded_or_not():
    s, _ = _corpus()
    con, build = _build(s)
    bound = s.execute(text("SELECT MAX(created_at) FROM keyword_mentions")).scalar()
    assert build["scan_bound"] == bound
    for p in (
        columnar.keyword_daily_parity(con, s),
        columnar.keyword_daily_parity(con, s, scan_bound=build["scan_bound"]),
    ):
        assert p["mentions_exact"] is True and p["mention_mismatches"] == 0
        assert p["distinct_upper_bound_holds"] is True
        assert p["mention_mismatch_rollup_below"] == p["mention_mismatch_rollup_above"] == 0
    assert p["bounded_by_scan_bound"] is True and p["scan_bound"] == bound


def test_a_scrape_committing_during_the_build_is_the_writers_mismatch_not_the_rollups():
    s, _ = _corpus()
    con, build = _build(s, on_first_batch=lambda: [_add_mention(s, (j * 7) % 200 + 1, 1000) for j in range(5)])
    old = columnar.keyword_daily_parity(con, s)  # the benchmark's old comparison
    assert old["mentions_exact"] is False and old["mention_mismatches"] > 0
    assert old["distinct_upper_bound_holds"] is False  # the signature of the 10-16 run
    assert old["bounded_by_scan_bound"] is False and old["scan_bound"] is None
    # ... and it is the direction a late row has: the rollup BELOW live, never above
    assert old["mention_mismatch_rollup_below"] == old["mention_mismatches"]
    assert old["mention_mismatch_rollup_above"] == 0

    new = columnar.keyword_daily_parity(con, s, scan_bound=build["scan_bound"])
    assert new["mentions_exact"] is True and new["mention_mismatches"] == 0
    assert new["distinct_upper_bound_holds"] is True and new["distinct_below_keywords"] == 0
    assert new["bounded_by_scan_bound"] is True


def test_a_row_deleted_after_it_was_streamed_still_shows_as_rollup_above_live():
    s, _ = _corpus()
    con, build = _build(s)
    # one keyword loses ALL its mentions and another loses one, after the build streamed them
    victim_all = s.execute(text("SELECT keyword_id FROM keyword_mentions GROUP BY keyword_id LIMIT 1")).scalar()
    s.execute(text("DELETE FROM keyword_mentions WHERE keyword_id = :k"), {"k": victim_all})
    victim_one = s.execute(
        text("SELECT keyword_id, MIN(id) FROM keyword_mentions WHERE keyword_id <> :k GROUP BY keyword_id LIMIT 1"),
        {"k": victim_all},
    ).fetchone()
    s.execute(text("DELETE FROM keyword_mentions WHERE id = :i"), {"i": victim_one[1]})
    s.commit()
    p = columnar.keyword_daily_parity(con, s, scan_bound=build["scan_bound"])
    assert p["mentions_exact"] is False
    assert p["rollup_only_keywords"] == 1  # the keyword the live window no longer has at all
    assert p["mention_mismatch_rollup_above"] >= 2
    assert p["mention_mismatch_rollup_below"] == 0


def test_with_no_dated_mention_at_build_time_only_the_undated_rows_are_in_reach():
    s, _ = _corpus(created_at=False)  # every created_at is NULL: phase A streams them all
    con, build = _build(s, on_first_batch=lambda: _add_mention(s, 3, 1000))
    assert build["scan_bound"] is None
    p = columnar.keyword_daily_parity(con, s, scan_bound=build["scan_bound"])
    assert p["mentions_exact"] is True and p["scan_bound"] is None and p["bounded_by_scan_bound"] is True
    assert columnar.keyword_daily_parity(con, s)["mentions_exact"] is False  # the late dated row, unbounded


def test_the_benchmarks_live_side_stops_at_the_same_bound():
    s, _ = _corpus()
    con, build = _build(s, on_first_batch=lambda: _add_mention(s, 3, 1000))
    unbounded = {int(r[0]): int(r[1]) for r in rollup_benchmark._live_windowed(s, None)}
    bounded = {int(r[0]): int(r[1]) for r in rollup_benchmark._live_windowed(s, None, scan_bound=build["scan_bound"])}
    roll = {k: v[0] for k, v in columnar.windowed_term_counts(con).items()}
    assert bounded == roll
    assert unbounded != roll and unbounded[3] == bounded[3] + 3


def test_run_rollup_benchmark_reports_the_bound_and_compares_bounded(monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.analytics import rollup_serve

    # This test is about the bound, not the start-time guards (those read the runner's memory and any hold file other tests leave behind; they are
    # pinned in tests/test_rollup_benchmark_guard.py).
    monkeypatch.setattr(rollup_serve, "first_start_decline", lambda: (None, None))

    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article, Base, Keyword, KeywordMention, Source

    e = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    for i in range(6):
        art = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T",
            content="The federal budget gripped the Senate; climate and drought too.", hash=f"h{i}",
            country="fr", language="en", published_at=datetime.datetime(2024, 3, 1 + i, tzinfo=datetime.UTC),
            created_at=datetime.datetime.now(datetime.UTC),
        )
        s.add(art)
        s.commit()
        index_article(s, art, extractor=ex)

    real = columnar.build_keyword_daily
    state = {"done": False}

    def racing_build(con, session, **kw):
        user_hook = kw.get("on_batch")

        def hook(stage, rows):
            if user_hook is not None:
                user_hook(stage, rows)
            if not state["done"] and stage == "mentions":
                state["done"] = True  # a scrape commits a new keyword and its mention after the build began
                kwd = Keyword(term="latecomer", normalized_term="latecomer", language="en")
                s.add(kwd)
                s.flush()
                s.add(KeywordMention(
                    keyword_id=kwd.id, article_id=1, count=3, observed_on=datetime.date.today(),
                    created_at=datetime.datetime(2099, 1, 1),
                ))
                s.commit()

        return real(con, session, **{**kw, "on_batch": hook})

    monkeypatch.setattr(columnar, "build_keyword_daily", racing_build)
    shapes: list[bool] = []
    real_live = rollup_benchmark._live_windowed

    def spy(session, start, **kw):
        shapes.append("scan_bound" in kw)
        return real_live(session, start, **kw)

    monkeypatch.setattr(rollup_benchmark, "_live_windowed", spy)
    out = rollup_benchmark.run_rollup_benchmark(s, repeats=1)
    assert state["done"]
    # per window: the TIMED live query is the shape the app serves (no bound predicate), then ONE bounded read counts
    # the keywords for the parity; a speedup measured against another query is not the speedup a user gets
    assert shapes == [False, True] * len(out["windows"])
    assert out["build"]["scan_bound"] is not None
    assert out["parity"]["bounded_by_scan_bound"] is True and out["parity"]["mentions_exact"] is True
    assert out["parity"]["distinct_upper_bound_holds"] is True
    for w in out["windows"]:
        assert w["counts_match"] is True and w["keywords_live_minus_rollup"] == 0


def test_the_over_count_fields_say_over_count_and_the_old_gap_names_are_gone():
    # "gap" read as distance from live; it counted only the rollup ABOVE live. The 10-16 benchmark showed
    # distinct_upper_bound_holds False beside gap 0 because the rollup was only ever BELOW live.
    s, _ = _corpus()
    con, build = _build(s, on_first_batch=lambda: [_add_mention(s, (j * 7) % 200 + 1, 1000) for j in range(5)])
    old = columnar.keyword_daily_parity(con, s)
    assert old["distinct_upper_bound_holds"] is False and old["distinct_below_keywords"] > 0
    assert old["distinct_over_count_keywords"] == 0 and old["distinct_over_count_total"] == 0
    assert "distinct_gap_keywords" not in old and "distinct_gap_total" not in old
