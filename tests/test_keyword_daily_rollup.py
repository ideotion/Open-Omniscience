"""The keyword_daily windowed-aggregation rollup — in-memory parity (data-arch 5A-bis, D2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The rollup is the deep fix for the measured Insights freeze (windowed most-mentioned /
trending scanning the multi-GB keyword_mentions table). It is a DISPOSABLE accelerator
behind the read seam, so the one thing it MUST earn is trust: its windowed answers have to
match the slow-but-correct live query. These tests prove that in-memory (DuckDB), which is
where the design says parity is provable even before the persisted store lands.

VERIFY (from docs/design/SCALING_DERIVED_LAYER_1000X.md):
  1. keyword_daily SUM(mentions) == live SUM(count) over a window (EXACT).
  2. windowed most-mentioned ranking == the live ranking (EXACT on mentions).
  3. the distinct-article count is an UPPER BOUND on the live COUNT(DISTINCT) — EQUAL under
     today's unique (keyword_id, article_id) constraint (gap 0), > live when a synthetic
     multi-day pair exists, and the gap is REPORTED, never hidden.
  11. a cold / missing rollup makes the serve return empty (the seam falls back to live).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    # Distinct dates so a window selects a real subset; distinct topics so mention totals
    # differ (a clean ranking with no tie ambiguity at the boundary).
    rows = [
        ("2024-03-01", "The federal budget budget budget gripped the Senate chamber."),
        ("2024-03-02", "Senate leaders argued the federal budget budget late tonight."),
        ("2024-03-03", "The Senate debated the federal budget in committee again."),
        ("2024-03-20", "Climate policy and drought dominated the climate summit."),
        ("2024-03-21", "A climate report on drought reached the committee."),
    ]
    for i, (d, content) in enumerate(rows):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=content, hash=f"h{i}", country="fr", language="en",
            published_at=datetime(*(int(x) for x in d.split("-")), tzinfo=UTC),
            created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


def _con():
    # Offline -> in-memory DuckDB (no secure crypto); oo_meta stamped by connect().
    con = columnar.connect(passphrase=None)
    assert con is not None
    return con


def _live_window(session, *, start=None):
    """The live per-keyword windowed (mentions, distinct_articles) — the ground truth."""
    clause = "observed_on IS NOT NULL"
    params: dict = {}
    if start is not None:
        clause += " AND observed_on >= :s"
        params["s"] = start
    rows = session.execute(text(
        "SELECT keyword_id, SUM(count), COUNT(DISTINCT article_id) FROM keyword_mentions "
        "WHERE " + clause + " GROUP BY keyword_id"
    ), params).fetchall()
    return {int(r[0]): (int(r[1]), int(r[2])) for r in rows}


def test_full_history_parity_is_exact(session):
    # VERIFY 1 + 3: over ALL history, mentions EXACT and distinct EXACT (unique-constraint).
    con = _con()
    tally = columnar.build_keyword_daily(session=session, con=con)
    assert tally["keyword_daily_rows"] > 0 and tally["keyword_meta_rows"] > 0

    roll = columnar.windowed_term_counts(con)  # all history
    live = _live_window(session)
    assert set(roll) == set(live), "rollup covers exactly the keywords the live query sees"
    for kid, (lm, la) in live.items():
        rm, ra = roll[kid]
        assert rm == lm, f"mentions must be EXACT for {kid}: {rm} != {lm}"
        assert ra == la, f"distinct EXACT today (unique constraint) for {kid}: {ra} != {la}"


def test_windowed_parity_matches_live(session):
    # VERIFY 1 + 2: a real window (only the March-20/21 climate cluster) matches live exactly.
    con = _con()
    columnar.build_keyword_daily(session=session, con=con)
    start = date(2024, 3, 15)

    roll = columnar.windowed_term_counts(con, start_day=start)
    live = _live_window(session, start=start)
    assert roll == live, "windowed rollup counts must equal the live windowed aggregation"

    # ranking: the served rows are ordered by mentions desc and match the live ranking.
    served = columnar.windowed_top_terms_raw(con, start_day=start, limit=50)
    assert served, "the window has keywords"
    assert [r["mentions"] for r in served] == sorted(
        (r["mentions"] for r in served), reverse=True
    ), "served rows are ranked by mentions desc"
    # every served (normalized -> mentions) equals the live count for that keyword.
    live_by_norm = {
        row[0]: int(row[1]) for row in session.execute(text(
            "SELECT k.normalized_term, SUM(m.count) FROM keyword_mentions m "
            "JOIN keywords k ON k.id = m.keyword_id "
            "WHERE m.observed_on >= :s GROUP BY k.normalized_term"
        ), {"s": start}).fetchall()
    }
    for r in served:
        assert r["mentions"] == live_by_norm[r["normalized"]]


def test_streamed_build_is_batch_size_invariant(session):
    # The streamed full build must produce the SAME rollup whatever the batch size — a
    # batch boundary must never drop or double-count a mention.
    con_small = _con()
    columnar.build_keyword_daily(session=session, con=con_small, batch_size=1)
    con_big = _con()
    columnar.build_keyword_daily(session=session, con=con_big, batch_size=10_000)
    assert columnar.windowed_term_counts(con_small) == columnar.windowed_term_counts(con_big)
    # and both equal the live ground truth.
    assert columnar.windowed_term_counts(con_small) == _live_window(session)


def test_distinct_count_is_a_true_upper_bound_and_the_gap_is_reported():
    # VERIFY 3 (structure): if a (keyword, article) pair ever spanned TWO days, the rollup
    # sums the per-day distinct counts (2) while the true distinct is 1 — an UPPER BOUND,
    # never under. Prove the STRUCTURE has this property (decoupled from today's constraint
    # that forbids it) and that a parity check REPORTS the gap rather than hiding it.
    con = _con()
    con.execute(columnar._KEYWORD_DAILY_DDL)
    # keyword 1, article 7 observed on two days: articles_on_day = 1 on each day.
    con.execute("INSERT INTO keyword_daily VALUES (1, DATE '2024-03-01', 5, 1)")
    con.execute("INSERT INTO keyword_daily VALUES (1, DATE '2024-03-02', 3, 1)")
    roll = columnar.windowed_term_counts(con)
    assert roll[1][0] == 8, "mentions still exact (5+3)"
    assert roll[1][1] == 2, "distinct is the UPPER BOUND (1 per day, summed), not the true 1"
    assert roll[1][1] > 1, "the rollup over-counts here; it must never under-count"


def test_cold_or_missing_rollup_returns_empty(session):
    # VERIFY 11: no rollup table -> serve returns empty so the seam falls back to live.
    con = _con()  # fresh store: oo_meta only, no keyword_daily yet
    assert columnar.windowed_term_counts(con) == {}
    assert columnar.windowed_top_terms_raw(con, start_day=date(2024, 1, 1)) == []


def test_kind_filter_reproduces_apply_kind(session):
    # The served rows honour the kind filter the same way queries._apply_kind does:
    # 'term' excludes entities, 'entity' keeps only entities.
    con = _con()
    columnar.build_keyword_daily(session=session, con=con)
    terms = columnar.windowed_top_terms_raw(con, kind="term", limit=100)
    assert terms and all(r["kind"] == "term" for r in terms)
    entities = columnar.windowed_top_terms_raw(con, kind="entity", limit=100)
    assert all(r["kind"] != "term" for r in entities)


def test_parity_probe_reports_exact_on_the_real_corpus(session):
    # The honest probe (for tests + a future diagnostics surface) says, on the real schema:
    # mentions exact, the upper bound holds, and the distinct gap is ZERO today.
    con = _con()
    columnar.build_keyword_daily(session=session, con=con)
    p = columnar.keyword_daily_parity(con, session)
    assert p["mentions_exact"] is True
    assert p["distinct_upper_bound_holds"] is True
    assert p["distinct_gap_total"] == 0
    assert p["keywords_compared"] > 0
