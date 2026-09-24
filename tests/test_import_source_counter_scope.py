"""
PR 6 — the import's source-counter reconcile is scoped to the batch (ruling R25).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE MEASUREMENT BEHIND R25: 2 h 25 min of corpus-wide stages for a 77 MB import whose
merge step took 7 s, of which this one reconcile over all 86,470 sources was 32 minutes
(finding F6). PR 3 fixed the function; the IMPORT still called it unscoped, and recorded
the reason as "the touched set is `temp.map_sources`, a TEMP table gone by the post-swap
session, so scoping means threading several thousand lines through the restore path".

It does not. `merged_rows` is durable provenance the merge already writes and the
post-swap re-index already reads, so the set is one query. These tests pin that, and pin
the thing that matters more than the speed:

  **AN UNDERIVABLE SCOPE MUST WIDEN, NEVER NARROW.** A silently empty scope leaves
  `Source.article_count` stale-LOW and, being non-NULL, the read fallback never fires --
  a wrong count displayed as exact, which is the exact defect S6 was raised about. So
  `None` (cannot derive) and `[]` (derived, nothing touched) must stay distinguishable,
  and `None` must reach the unscoped whole-corpus repair.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.store import reconcile_source_counters
from src.backup.merge import _touched_source_ids
from src.database.models import Article, Base, MergeBatch, MergedRow, Source


def _session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def _batch(s, bid=1):
    s.add(MergeBatch(id=bid, imported_at=datetime.now(UTC)))
    s.flush()
    return bid


def _src(s, name):
    src = Source(name=name, domain=f"{name}.test")
    s.add(src)
    s.flush()
    return src


def _art(s, src_id, h):
    a = Article(url=f"https://x/{h}", canonical_url=f"https://x/{h}", source_id=src_id,
                title="t", content="b", hash=h, language="en", created_at=datetime.now(UTC))
    s.add(a)
    s.flush()
    return a


def _provenance(s, bid, table, row_id):
    s.add(MergedRow(batch_id=bid, table_name=table, row_id=row_id))
    s.flush()


# --- the two populations ---------------------------------------------------- #

def test_a_source_that_gained_articles_is_in_the_scope():
    """The additive merge inserts articles onto EXISTING sources mapped by domain without
    touching their counter -- finding S6, and the main population."""
    s = _session()
    bid = _batch(s)
    existing = _src(s, "existing")
    untouched = _src(s, "untouched")
    _art(s, untouched.id, "old")  # pre-existing article, not from this batch
    gained = _art(s, existing.id, "new")
    _provenance(s, bid, "articles", gained.id)
    s.commit()

    assert _touched_source_ids(s, bid) == [existing.id]


def test_a_source_the_merge_inserted_is_in_the_scope_even_with_no_articles():
    """NOT redundant with the first population: a brand-new source whose articles all
    turned out to be duplicates still arrives with a NULL counter needing a first value."""
    s = _session()
    bid = _batch(s)
    brand_new = _src(s, "brandnew")
    _provenance(s, bid, "sources", brand_new.id)
    s.commit()

    assert _touched_source_ids(s, bid) == [brand_new.id]


def test_both_populations_are_unioned_and_deduplicated():
    s = _session()
    bid = _batch(s)
    a_src, b_src = _src(s, "a"), _src(s, "b")
    art = _art(s, a_src.id, "h1")
    _provenance(s, bid, "articles", art.id)
    _provenance(s, bid, "sources", a_src.id)  # also inserted -> must not appear twice
    _provenance(s, bid, "sources", b_src.id)
    s.commit()

    got = _touched_source_ids(s, bid)
    assert got == sorted({a_src.id, b_src.id})


def test_another_batch_s_rows_are_not_in_this_batch_s_scope():
    """The whole point of scoping: a source another import touched cannot have drifted
    from THIS one."""
    s = _session()
    mine, theirs = _batch(s, 1), _batch(s, 2)
    my_src, their_src = _src(s, "mine"), _src(s, "theirs")
    my_art, their_art = _art(s, my_src.id, "m"), _art(s, their_src.id, "t")
    _provenance(s, mine, "articles", my_art.id)
    _provenance(s, theirs, "articles", their_art.id)
    s.commit()

    assert _touched_source_ids(s, mine) == [my_src.id]
    assert _touched_source_ids(s, theirs) == [their_src.id]


def test_a_batch_that_touched_nothing_derives_an_EMPTY_list_not_None():
    """`[]` and `None` are different answers and must stay so: empty means "verified that
    nothing was touched", None means "could not tell". Only the second may widen."""
    s = _session()
    bid = _batch(s)
    s.commit()
    got = _touched_source_ids(s, bid)
    assert got == [], f"expected an empty list, got {got!r}"
    assert got is not None


def test_articles_source_id_is_not_nullable_so_no_null_source_case_exists():
    """Why there is no "article with no source" test, recorded rather than assumed.

    My first version of `_touched_source_ids` carried a `source_id IS NOT NULL` predicate
    and this was a test for it. Writing the test proved the case impossible: the INSERT
    fails with `NOT NULL constraint failed: articles.source_id`. The predicate was an
    unreachable branch implying a possibility the schema forbids, so it is gone -- and this
    assertion is what makes its removal safe, because it fails the day the column becomes
    nullable and the guard is needed again.
    """
    assert Article.__table__.c.source_id.nullable is False


# --- the asymmetry that matters more than the speed ------------------------- #

def test_an_underivable_scope_returns_None_so_the_caller_widens(monkeypatch):
    """THE LOAD-BEARING TEST. A silently empty scope would leave Source.article_count
    stale-low and, being non-NULL, the read fallback never fires -> a wrong count shown as
    exact, which is S6 exactly. So a failure must return None, and None is
    reconcile_source_counters' UNSCOPED whole-corpus repair."""
    s = _session()
    bid = _batch(s)

    def _boom(*a, **k):
        raise RuntimeError("provenance unreadable")

    monkeypatch.setattr(s, "execute", _boom)
    assert _touched_source_ids(s, bid) is None, "an underivable scope must widen, not narrow"


def test_None_reaches_the_unscoped_repair_and_an_empty_list_is_a_no_op():
    """The two return values have to mean different things at the API too, or the
    distinction above buys nothing."""
    s = _session()
    a, b = _src(s, "a"), _src(s, "b")
    _art(s, a.id, "a1")
    _art(s, b.id, "b1")
    s.commit()

    scoped_empty = reconcile_source_counters(s, source_ids=[])
    assert scoped_empty["scope"] == "scoped" and scoped_empty["sources"] == 0
    assert all(src.article_count is None for src in s.query(Source)), "a no-op wrote nothing"

    unscoped = reconcile_source_counters(s, source_ids=None)
    assert unscoped["scope"] != "scoped"
    assert {src.name: src.article_count for src in s.query(Source)} == {"a": 1, "b": 1}


def test_the_scoped_reconcile_fixes_the_touched_source_and_leaves_the_others_alone():
    """End to end over the derived scope: the batch's source becomes exact, and a source
    the batch never touched keeps its older (honest) state rather than a fresh stamp."""
    s = _session()
    bid = _batch(s)
    touched, other = _src(s, "touched"), _src(s, "other")
    _art(s, other.id, "pre")
    reconcile_source_counters(s)  # everything starts exact
    early = {src.id: src.counter_reconciled_at for src in s.query(Source)}

    art = _art(s, touched.id, "imported")
    _provenance(s, bid, "articles", art.id)
    s.commit()

    out = reconcile_source_counters(s, source_ids=_touched_source_ids(s, bid))
    assert out["scope"] == "scoped" and out["scoped_to"] == 1

    s.expire_all()
    rows = {src.name: src for src in s.query(Source)}
    assert rows["touched"].article_count == 1, "the touched source is now exact"
    assert rows["other"].article_count == 1, "the untouched source keeps its value"
    assert rows["other"].counter_reconciled_at == early[other.id], (
        "and keeps its OLDER stamp -- stamping a source this call never looked at would be "
        "a false freshness claim"
    )


# --- the wiring, which is the deliverable ----------------------------------- #

def test_the_import_call_site_actually_passes_the_scope():
    """CAUGHT BY MUTATION. Replacing the call site's `source_ids=` with `None` left every
    test above green: they exercise the helper and the API, and neither notices that the
    import stopped using them. An unwired change is the whole failure mode here, so the
    wiring is pinned.

    Asserted against the FILE rather than by driving `merge_corpus`, for the reason the
    ledger records: positive facts must not be asserted against mutable process state, and
    reaching this branch for real needs a staged artifact, a working copy and an atomic
    swap. The source is the immutable anchor.
    """
    from pathlib import Path

    src = Path("src/backup/merge.py").read_text(encoding="utf-8")
    assert "source_ids=_touched_source_ids(_epoch_sess, batch_id)," in src, (
        "the import's source-counter reconcile must pass the derived scope"
    )
    assert 'report["source_counters"] = reconcile_source_counters(' in src, (
        "and must publish what it ran, so a scoped run is visible in the report"
    )
    # The aged claim this PR removed must not come back: F6 measured 86,470 sources and 32
    # minutes against a comment that read "cheap; sources are few".
    #
    # ALLOWED ONLY IN A "USED TO" LINE, which is the second time this session an assertion
    # of mine fired on my own explanatory prose quoting the very claim it retires. The
    # phrase has to survive as history; what must not return is the phrase ASSERTED.
    for line in src.splitlines():
        if "cheap; sources are few" in line:
            assert "USED TO" in line, (
                f"the retired claim is being asserted again, not quoted as history: {line.strip()!r}"
            )


def test_the_helper_and_the_call_site_agree_on_the_session_and_batch():
    """A scope derived from a different session or batch than the reconcile uses would be
    silently wrong rather than loud, so both must name the same two locals."""
    from pathlib import Path

    src = Path("src/backup/merge.py").read_text(encoding="utf-8")
    i = src.index('report["source_counters"] = reconcile_source_counters(')
    call = src[i : i + 260]
    assert "_epoch_sess," in call and "_touched_source_ids(_epoch_sess, batch_id)" in call, (
        f"the reconcile and its scope must share one session and batch; got: {call!r}"
    )
