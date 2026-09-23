"""
R22 — counters deferred for an exclusive drain, disclosed as `estimated` meanwhile.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DISCLOSURE IS THE FEATURE, NOT THE DECORATION. The speed-up is allowed only because
the envelope tells the truth while it is happening, so the tests that matter most here
are the ones that would catch a fast, silent, wrong answer:

  * `counter_envelope` reports `estimated` while the marker is open EVEN THOUGH every
    watermark is fresh -- the exact state a deferred drain creates, and the one the
    pre-R22 envelope answered `exact` to;
  * the marker SURVIVES the process, because the case it exists for is a crash mid-drain,
    where the counters are least correct and nothing is left running to know it;
  * a PARTIAL reconcile does not close it;
  * the end-of-drain reconcile RESTARTS rather than resuming, because a resumed sweep
    reports `complete` while leaving earlier-stamped keywords drifted.

Everything else is ordinary: deferral must not change the counters a completed drain
ends up with, only when they are written.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.counter_deferral import (
    COUNTER_DEFERRAL_KEY,
    close_deferral,
    deferral_open_since,
    is_deferral_open,
    open_deferral,
)
from src.analytics.extract import ExtractedTerm
from src.analytics.store import counter_envelope, index_article, reindex_articles
from src.database.models import Article, Base, DerivedMeta, Keyword, KeywordMention, Source


def _engine(path="sqlite://"):
    eng = create_engine(
        path, connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    return eng


def _session(eng=None):
    eng = eng or _engine()
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="S", domain="s.test"))
    s.commit()
    return s


class _FakeExtractor:
    name = "fake"

    def __init__(self, terms):
        self._terms = terms

    def extract(self, text, language=None, **kw):
        return list(self._terms)


def _terms(n):
    return [
        ExtractedTerm(term=f"t{i}", normalized=f"t{i}", kind="term", count=2, first_offset=i)
        for i in range(n)
    ]


def _article(s, h):
    a = Article(url=f"https://s.test/{h}", canonical_url=f"https://s.test/{h}", source_id=1,
                title="T", content="body", hash=h, language="en", created_at=datetime.now(UTC))
    s.add(a)
    s.commit()
    return a


def _live_counts(s):
    return {
        kid: (int(m or 0), int(a or 0))
        for kid, m, a in s.query(
            KeywordMention.keyword_id,
            func.sum(KeywordMention.count),
            func.count(func.distinct(KeywordMention.article_id)),
        ).group_by(KeywordMention.keyword_id)
    }


def _stored_counts(s):
    return {k.id: (k.mention_count, k.article_count) for k in s.query(Keyword)}


# --- the honesty hole this ruling is about --------------------------------- #

def test_the_envelope_says_estimated_while_deferred_even_with_every_watermark_fresh():
    """THE LOAD-BEARING TEST. A deferred drain does not touch last_reconciled_at, so the
    pre-R22 envelope answered `exact` over counters that were drifting. Fresh watermarks
    everywhere is not an edge case here -- it is the state the ruling creates."""
    s = _session()
    a = _article(s, "a")
    index_article(s, a, extractor=_FakeExtractor(_terms(3)), country=None, city=None)
    fresh = datetime.now(UTC)
    for kw in s.query(Keyword):
        kw.last_reconciled_at = fresh
    s.commit()

    assert counter_envelope(s).basis == "exact", "precondition: fresh watermarks read exact"

    open_deferral(s, reason="test")
    env = counter_envelope(s)
    assert env.basis == "estimated"
    assert "DEFERRED" in env.method

    close_deferral(s)
    assert counter_envelope(s).basis == "exact", "closing must restore the real answer"


def test_the_marker_outlives_the_process_that_opened_it():
    """The case it exists for is a crash mid-drain. An in-process flag would die with the
    process that knew the counters were wrong; this one is read back from the store by a
    session that never saw the drain."""
    eng = _engine()
    first = _session(eng)
    open_deferral(first, reason="drain")
    first.close()  # the process goes away mid-drain

    second = sessionmaker(bind=eng, future=True)()
    assert is_deferral_open(second) is True
    assert deferral_open_since(second) is not None


def test_reopening_keeps_the_original_timestamp():
    """'Estimated since when' must be the earliest unmaintained moment. Re-opening with a
    later stamp would quietly shorten the window being disclosed."""
    s = _session()
    early = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    first = open_deferral(s, now=early)
    second = open_deferral(s, now=early + timedelta(hours=5))
    assert first == second == early.isoformat(timespec="seconds")


def test_an_unreadable_marker_is_disclosed_as_deferred(monkeypatch):
    """A read that failed cannot support an `exact` claim, so it degrades toward the
    disclosure -- the opposite direction from the corpus-epoch read, deliberately."""
    s = _session()

    def _boom(*a, **k):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(s, "get", _boom)
    assert deferral_open_since(s) == "unknown"


def test_close_reports_whether_anything_was_actually_cleared():
    s = _session()
    assert close_deferral(s) is False
    open_deferral(s)
    assert close_deferral(s) is True
    assert s.get(DerivedMeta, COUNTER_DEFERRAL_KEY) is None


# --- what deferral does, and does not, change ------------------------------ #

def test_index_article_still_writes_the_same_mentions_when_counters_are_deferred():
    """Deferral changes WHEN counters are written, never the mentions they come from."""
    s = _session()
    a = _article(s, "a")
    out = index_article(
        s, a, extractor=_FakeExtractor(_terms(4)), country=None, city=None,
        maintain_counters=False,
    )
    assert out["mentions"] == 4
    assert s.query(KeywordMention).filter_by(article_id=a.id).count() == 4


def test_deferred_indexing_leaves_the_counters_behind_on_purpose():
    """The drift is real and intended; the marker is what makes it honest. Without this
    test the deferral could silently be a no-op and every other test would still pass."""
    s = _session()
    a = _article(s, "a")
    index_article(
        s, a, extractor=_FakeExtractor(_terms(3)), country=None, city=None,
        maintain_counters=False,
    )
    s.commit()
    assert _live_counts(s), "mentions were written"
    assert all(m == 0 and n == 0 for m, n in _stored_counts(s).values()), (
        "counters must NOT have been maintained"
    )


def test_a_deferred_reindex_ends_with_counters_equal_to_the_live_group_by():
    """The end of the drain is where the truth comes back. Whatever was skipped per
    article must be exactly restored by the final reconcile."""
    s = _session()
    arts = [_article(s, f"a{i}") for i in range(4)]
    ex = _FakeExtractor(_terms(5))
    for a in arts:
        index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    before = _stored_counts(s)
    assert before and all(m > 0 for m, _ in before.values())

    out = reindex_articles(
        s, extractor=ex, article_ids=[a.id for a in arts], commit_batch=2, defer_counters=True
    )
    assert out["reindexed"] == 4
    assert is_deferral_open(s) is False, "a completed drain closes its own disclosure"

    live = _live_counts(s)
    stored = {k: v for k, v in _stored_counts(s).items() if v != (0, 0)}
    assert stored == live, "counters must equal the live GROUP BY after the drain"


def test_a_deferred_and_an_undeferred_reindex_agree_exactly():
    """The strongest statement available: same corpus, same work, same numbers."""
    results = []
    for defer in (False, True):
        s = _session()
        arts = [_article(s, f"a{i}") for i in range(4)]
        ex = _FakeExtractor(_terms(5))
        for a in arts:
            index_article(s, a, extractor=ex, country=None, city=None)
        s.commit()
        reindex_articles(
            s, extractor=ex, article_ids=[a.id for a in arts], commit_batch=2,
            defer_counters=defer,
        )
        results.append({
            k.normalized_term: (k.mention_count, k.article_count) for k in s.query(Keyword)
        })
    assert results[0] == results[1]


def test_an_undeferred_reindex_never_opens_the_marker():
    s = _session()
    a = _article(s, "a")
    ex = _FakeExtractor(_terms(2))
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()
    reindex_articles(s, extractor=ex, article_ids=[a.id], defer_counters=False)
    assert is_deferral_open(s) is False


def test_deferral_is_declined_rather_than_silent_when_the_marker_cannot_open(monkeypatch):
    """No marker, no deferral. Losing the speed-up is a cost we may pay; losing the
    disclosure is not ours to trade away."""
    import src.analytics.counter_deferral as cd

    s = _session()
    a = _article(s, "a")
    ex = _FakeExtractor(_terms(3))

    def _boom(*args, **kwargs):
        raise RuntimeError("cannot write the marker")

    monkeypatch.setattr(cd, "open_deferral", _boom)

    # ASSERTED ON WHAT index_article WAS ASKED TO DO, not on the counters afterwards.
    # Caught by mutation: making the failure path defer anyway left an end-of-run
    # reconcile that repaired the counters, so a counters-afterwards assertion passed
    # over exactly the window of undisclosed drift this test exists to forbid.
    import src.analytics.store as store

    asked: list[bool] = []
    real = store.index_article

    def _spy(session, article, **kw):
        asked.append(bool(kw.get("maintain_counters", True)))
        return real(session, article, **kw)

    monkeypatch.setattr(store, "index_article", _spy)
    reindex_articles(s, extractor=ex, article_ids=[a.id], defer_counters=True)

    assert asked and all(asked), (
        f"without a marker every article must stay maintained, got maintain_counters={asked}"
    )
    stored = {k: v for k, v in _stored_counts(s).items() if v != (0, 0)}
    assert stored == _live_counts(s)


def test_an_incomplete_reconcile_leaves_the_disclosure_standing(monkeypatch):
    """A budgeted sweep that stopped early verified SOME keywords. Closing the marker on
    it would republish `exact` over the ones it never reached -- the same false claim the
    marker exists to prevent, arriving at the end of the drain instead of the start."""
    import src.analytics.store as store

    s = _session()
    a = _article(s, "a")
    ex = _FakeExtractor(_terms(3))
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()

    def _partial(session, **kw):
        return {"keywords": 1, "with_mentions": 1, "drift_repaired": 0,
                "as_of": datetime.now(UTC).isoformat(), "complete": False,
                "resumed_from_id": 0, "cursor_id": 5, "budget_s": 0}

    monkeypatch.setattr(store, "reconcile_keyword_counters", _partial)
    reindex_articles(s, extractor=ex, article_ids=[a.id], defer_counters=True)

    assert is_deferral_open(s) is True, "an unfinished reconcile must not close the marker"
    assert counter_envelope(s).basis == "estimated"


def test_a_reconcile_that_raises_leaves_the_disclosure_standing(monkeypatch):
    """Same asymmetry as everywhere else here: failing to close is an understated
    freshness claim, closing early is a false one."""
    import src.analytics.store as store

    s = _session()
    a = _article(s, "a")
    ex = _FakeExtractor(_terms(3))
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()

    def _boom2(session, **kw):
        raise RuntimeError("reconcile failed")

    monkeypatch.setattr(store, "reconcile_keyword_counters", _boom2)
    out = reindex_articles(s, extractor=ex, article_ids=[a.id], defer_counters=True)

    assert out["reindexed"] == 1, "a failed reconcile must not fail the re-index"
    assert is_deferral_open(s) is True


# --- the reconcile must restart, not resume -------------------------------- #

def test_the_end_of_drain_reconcile_restarts_instead_of_resuming(monkeypatch):
    """A resumed sweep reports `complete` having skipped every keyword below an earlier
    partial pass's cursor -- keywords this drain drifted and that still carry fresh
    watermarks. That is a false `exact`, reintroduced by the resume optimisation."""
    import src.analytics.store as store

    s = _session()
    a = _article(s, "a")
    ex = _FakeExtractor(_terms(3))
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()

    seen: list[bool] = []
    real = store.reconcile_keyword_counters

    def _spy(session, **kw):
        seen.append(bool(kw.get("restart")))
        return real(session, **kw)

    monkeypatch.setattr(store, "reconcile_keyword_counters", _spy)
    reindex_articles(s, extractor=ex, article_ids=[a.id], defer_counters=True)
    assert seen == [True], f"the drain's reconcile must restart, got restart={seen}"


def test_restart_ignores_a_stale_cursor_and_sweeps_from_the_beginning():
    from src.analytics.store import RECONCILE_CURSOR_KEY, _cursor_set, reconcile_keyword_counters

    s = _session()
    a = _article(s, "a")
    index_article(s, a, extractor=_FakeExtractor(_terms(3)), country=None, city=None)
    s.commit()

    _cursor_set(s, RECONCILE_CURSOR_KEY, 10_000_000)  # as if a partial pass got far
    resumed = reconcile_keyword_counters(s, budget_s=0)
    assert resumed["resumed_from_id"] == 10_000_000

    _cursor_set(s, RECONCILE_CURSOR_KEY, 10_000_000)
    restarted = reconcile_keyword_counters(s, budget_s=0, restart=True)
    assert restarted["resumed_from_id"] == 0
    assert restarted["with_mentions"] >= 1, "a restart actually sweeps the keywords"


# --- who owns the reconcile -------------------------------------------------- #

def test_an_already_open_marker_means_an_outer_drain_owns_the_reconcile(monkeypatch):
    """THE COST GUARD, not a detail. The drain calls reindex_articles once per import
    batch. If each call reconciled at its own end, a ten-batch drain would pay ten
    whole-corpus GROUP BYs over 11 M keywords to save one batch's per-article updates --
    strictly slower than never deferring at all."""
    import src.analytics.store as store

    s = _session()
    a = _article(s, "a")
    ex = _FakeExtractor(_terms(3))
    index_article(s, a, extractor=ex, country=None, city=None)
    s.commit()

    calls: list[dict] = []
    real = store.reconcile_keyword_counters

    def _spy(session, **kw):
        calls.append(kw)
        return real(session, **kw)

    monkeypatch.setattr(store, "reconcile_keyword_counters", _spy)

    open_deferral(s, reason="the outer drain")  # an outer caller owns it
    reindex_articles(s, extractor=ex, article_ids=[a.id], defer_counters=True)

    assert calls == [], "a batch inside an owned drain must not reconcile"
    assert is_deferral_open(s) is True, "and must not lift the outer drain's disclosure"


def test_finish_deferral_reconciles_restarting_and_then_closes():
    from src.analytics.store import finish_deferral

    s = _session()
    a = _article(s, "a")
    index_article(s, a, extractor=_FakeExtractor(_terms(3)), country=None, city=None)
    s.commit()
    open_deferral(s)

    out = finish_deferral(s)
    assert out == {"reconciled": True, "closed": True, "complete": True}
    assert is_deferral_open(s) is False
    stored = {k: v for k, v in _stored_counts(s).items() if v != (0, 0)}
    assert stored == _live_counts(s)


def test_finish_deferral_keeps_the_disclosure_when_the_reconcile_fails(monkeypatch):
    import src.analytics.store as store

    s = _session()
    open_deferral(s)

    def _boom(session, **kw):
        raise RuntimeError("no")

    monkeypatch.setattr(store, "reconcile_keyword_counters", _boom)
    out = store.finish_deferral(s)
    assert out["closed"] is False
    assert is_deferral_open(s) is True
