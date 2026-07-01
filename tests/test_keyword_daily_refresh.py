"""keyword_daily incremental refresh + the corpus-epoch guard (data-arch 5A-bis, D3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The rollup is only useful if it stays fresh cheaply AND never lies. D3 refreshes it
incrementally (merge just the new mention tail) but forces a FULL rebuild whenever the
corpus epoch changed — because ``index_article`` does delete-then-reinsert, so an
incremental merge after a re-index would leave the old contribution in the rollup AND add
the re-inserted rows = a doubled number. These tests prove, in-memory:

  4.  incremental after a new batch == a full rebuild (MERGE-add correctness).
  5.  a late-arriving historical-dated batch lands on the CORRECT (old) day.
  6.  an epoch change forces a FULL rebuild, not incremental — and an UNGUARDED incremental
      after a re-index really does double-count (why the guard exists).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, Source

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s, BaselineExtractor()


_n = 0


def _index(session, ex, day: str, content: str) -> Article:
    global _n
    a = Article(
        url=f"https://x.test/{_n}", canonical_url=f"https://x.test/{_n}", source_id=1,
        title="T", content=content, hash=f"h{_n}", country="fr", language="en",
        published_at=datetime(*(int(x) for x in day.split("-")), tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    _n += 1
    session.add(a)
    session.commit()
    index_article(session, a, extractor=ex)
    return a


def _fresh_full(session):
    """A brand-new in-memory store, full-built from the current corpus = ground truth."""
    con = columnar.connect(passphrase=None)
    columnar.build_keyword_daily(session=session, con=con)
    return con


def _counts(con):
    return columnar.windowed_term_counts(con)  # all history, keyword_id -> (mentions, arts)


def test_incremental_matches_a_full_rebuild_on_append(ctx):
    # VERIFY 4: build over batch A, APPEND batch B, refresh incrementally -> identical to a
    # fresh full rebuild over A+B.
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate chamber.")
    _index(session, ex, "2024-03-02", "Senate leaders argued the federal budget tonight.")
    con = columnar.connect(passphrase=None)
    assert columnar.refresh_keyword_daily(con, session, corpus_epoch=1)["mode"] == "full"

    _index(session, ex, "2024-03-03", "The budget debate reached the Senate committee.")
    _index(session, ex, "2024-03-20", "Climate policy and drought dominated the summit.")
    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)  # epoch unchanged
    assert res["mode"] == "incremental" and res["merged_days"] > 0

    assert _counts(con) == _counts(_fresh_full(session)), "incremental == full rebuild"
    # and still byte-exact vs the live query.
    assert columnar.keyword_daily_parity(con, session)["mentions_exact"] is True


def test_late_arriving_historical_batch_lands_on_the_right_day(ctx):
    # VERIFY 5: an article ingested now but DATED earlier is merged onto its true (old) day.
    session, ex = ctx
    _index(session, ex, "2024-03-10", "The federal budget reached the Senate.")
    con = columnar.connect(passphrase=None)
    columnar.refresh_keyword_daily(con, session, corpus_epoch=1)

    # a NEW mention row (higher id) with an OLD observed_on (February)
    _index(session, ex, "2024-02-01", "An earlier federal budget note surfaced late.")
    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    assert res["mode"] == "incremental"

    # the whole rollup equals a full rebuild, and the Feb day is really present.
    assert _counts(con) == _counts(_fresh_full(session))
    feb = con.execute(
        "SELECT SUM(mentions) FROM keyword_daily WHERE day = DATE '2024-02-01'"
    ).fetchone()[0]
    assert feb and int(feb) > 0, "the late historical batch landed on 2024-02-01"


def test_epoch_change_forces_full_rebuild_and_unguarded_incremental_double_counts(ctx):
    # VERIFY 6 + the trap: after re-indexing an EXISTING article, an incremental merge (epoch
    # unchanged) OVER-counts; bumping the epoch forces a full rebuild that is correct again.
    session, ex = ctx
    a0 = _index(session, ex, "2024-03-01", "The federal budget budget gripped the Senate.")
    _index(session, ex, "2024-03-05", "Senate debated the federal budget once more.")
    con = columnar.connect(passphrase=None)
    columnar.refresh_keyword_daily(con, session, corpus_epoch=1)  # full build @ epoch 1

    # re-index an existing article: delete-then-reinsert its mentions with NEW higher ids.
    index_article(session, a0, extractor=ex)

    # WRONG (the trap): epoch unchanged -> incremental merges the re-inserted tail ON TOP of
    # a0's contribution already in the rollup.
    wrong = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    assert wrong["mode"] == "incremental"
    wrong_counts = _counts(con)

    # RIGHT: bump the epoch -> a full rebuild restores correctness.
    right = columnar.refresh_keyword_daily(con, session, corpus_epoch=2)
    assert right["mode"] == "full"
    right_counts = _counts(con)

    ground_truth = _counts(_fresh_full(session))
    assert right_counts == ground_truth, "the epoch-forced full rebuild is correct"
    assert wrong_counts != ground_truth, "the unguarded incremental double-counted (the trap)"
    # concretely: the re-indexed keyword's mentions were inflated above the truth.
    bid = session.query(Keyword).filter_by(normalized_term="budget").first().id
    assert wrong_counts[bid][0] > ground_truth[bid][0]
    assert right_counts[bid][0] == ground_truth[bid][0]


def test_incremental_is_a_noop_when_nothing_new(ctx):
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate.")
    con = columnar.connect(passphrase=None)
    columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    before = _counts(con)

    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)  # no new mentions
    assert res["mode"] == "incremental" and res["merged_days"] == 0
    assert _counts(con) == before, "a no-op refresh changes nothing"


def test_new_keyword_appearing_in_a_tail_gets_metadata(ctx):
    # A keyword that first appears in an incremental tail must be servable (its meta upserted),
    # else windowed_top_terms_raw (which JOINs keyword_meta) would silently drop it.
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate.")
    con = columnar.connect(passphrase=None)
    columnar.refresh_keyword_daily(con, session, corpus_epoch=1)

    _index(session, ex, "2024-03-02", "A pandemic vaccine rollout reached the clinic.")
    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=1)
    assert res["new_keywords"] > 0
    served = {r["normalized"] for r in columnar.windowed_top_terms_raw(con, limit=100)}
    assert "vaccine" in served, "the newly-appeared keyword is servable after incremental"


def test_missing_rollup_triggers_a_full_rebuild(ctx):
    # No prior build (built_epoch unset) -> the first refresh is a FULL build regardless.
    session, ex = ctx
    _index(session, ex, "2024-03-01", "The federal budget gripped the Senate.")
    con = columnar.connect(passphrase=None)
    res = columnar.refresh_keyword_daily(con, session, corpus_epoch=7)
    assert res["mode"] == "full"
    assert _counts(con) == _counts(_fresh_full(session))
    assert columnar._get_meta(con, "keyword_daily.built_epoch") == "7"
