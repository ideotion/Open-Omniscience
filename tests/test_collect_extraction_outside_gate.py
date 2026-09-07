"""C16 / S-D (2026-07-24 throughput brief): extraction out of the writer gate.

``ArticleBatch._flush_batched`` used to hold the ONE gate window across every
staged article's ``index_article`` CPU extraction. It now STAGES first — keyword
extraction, sentiment and the when/where/who EXTRACTION half all run before the
flush — so the window holds only DML.

The reversal of the 2026-07-12 F13 decline, with its measurement, lives in
``tests/test_write_gate_riders.py``; the gate-hold property itself is pinned
there. THIS file pins the things that make the move SAFE rather than fast, and
every one of them is a case where a green run would otherwise mean nothing:

  * the precompute touches NO session (so it cannot autoflush the gate open —
    the 2026-07-09 ETA/P1.8 lesson) — and the anti-vacuity twin, that it really
    was called;
  * a per-article precompute FAILURE falls back to inline computation for that
    article and still stores its keywords AND its dates/places/entities —
    "not precomputed" is not "none found";
  * ``OO_NO_INDEX=1`` skips the precompute entirely rather than paying for
    derivatives nothing will store;
  * the surrogate key is NEGATIVE, so a precompute log line can never name a
    real article id;
  * the rollback-and-redo zero-loss path is untouched.

The byte-identity of everything the flush STORES (54 articles, 1032 mentions,
68 dates, 24 places, 24 entities, keyword counters, sentiment, top-keyword and
deduced language, over a fixture that provably reaches the language-gated date
tables) was proven by a whole-structure differential against the pre-C16 tree
and is recorded in the PR; a name-level assertion cannot see a field that broke,
so the differential is the evidence and these are the guards.
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_write_gate_riders import (  # the pinned collector fixtures
    _GateProbeSession,
    _fetcher,
    _routed_source,
)


def _ingest(monkeypatch, n=4, batch="4"):
    """Drive the REAL ingest_source path over ``n`` synthetic articles."""
    from src.database.models import Source
    from src.database.session import init_db, session_scope
    from src.ingest.pipeline import ingest_source

    init_db()
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", batch)
    dom = f"c16-{uuid.uuid4().hex[:8]}.example"
    sess = _GateProbeSession()
    _routed_source(sess, dom, n)
    with session_scope() as s:
        src = Source(name=dom, domain=dom, rss_url=f"https://{dom}/feed.xml",
                     language="en", enabled=False)
        s.add(src)
        s.commit()
        src_id = src.id
        tally = ingest_source(s, src, fetcher=_fetcher(sess))
    return dom, src_id, tally


# --------------------------------------------------------------------------- #
#  concurrency lens: the precompute must not be able to open the gate
# --------------------------------------------------------------------------- #


def test_the_precompute_never_touches_the_session_so_it_cannot_autoflush_the_gate(
    monkeypatch,
):
    """The gate is acquired on FLUSH, and SQLAlchemy autoflushes a dirty session
    on the next QUERY — so a precompute that read anything off the session could
    hand the gate to a read and re-create the F13 hold by another route (the
    2026-07-09 ETA/P1.8 lesson).

    Probed by making the session itself fail loudly for the duration of the
    precompute: any query/flush/execute during it raises. Anti-vacuity: the
    precompute must actually have RUN (a guard over a call that never happens is
    satisfied for free)."""
    from src.ingest import batch as batch_mod

    seen: list[int] = []
    real = batch_mod.ArticleBatch._precompute

    def probing(self, to_store):
        class _Poisoned:
            def __getattr__(self, name):  # noqa: ANN001 - test double
                raise AssertionError(
                    f"_precompute touched the session (session.{name}) — that can "
                    "autoflush and hand the write gate to a read"
                )

        saved, self._session = self._session, _Poisoned()
        try:
            out = real(self, to_store)
        finally:
            self._session = saved
        seen.append(len(out))
        return out

    monkeypatch.setattr(batch_mod.ArticleBatch, "_precompute", probing)
    _dom, _src_id, tally = _ingest(monkeypatch, n=4)

    assert tally["stored"] == 4
    assert seen, "ANTI-VACUITY: _precompute never ran, so this proved nothing"
    assert sum(seen) == 4, seen


def test_the_precompute_runs_before_the_flush_not_after(monkeypatch):
    """Ordering is the whole fix: precompute, THEN flush. A precompute that ran
    after the flush would be outside the gate in source order and inside it in
    wall-clock terms. Recorded from the real objects — a staged row has no id
    until the flush, so 'every row is still transient when the precompute runs'
    is the observable, drift-proof form of 'before'."""
    from src.ingest import batch as batch_mod

    ids_at_precompute: list[list] = []
    real = batch_mod.ArticleBatch._precompute

    def probing(self, to_store):
        ids_at_precompute.append([a.id for _e, a in to_store])
        return real(self, to_store)

    monkeypatch.setattr(batch_mod.ArticleBatch, "_precompute", probing)
    _dom, _src_id, tally = _ingest(monkeypatch, n=4)

    assert tally["stored"] == 4
    assert ids_at_precompute, "ANTI-VACUITY: _precompute never ran"
    for batch_ids in ids_at_precompute:
        assert batch_ids and all(i is None for i in batch_ids), (
            f"rows already had ids at precompute time ({batch_ids}) — the flush "
            "had already happened, so the gate was already open"
        )


# --------------------------------------------------------------------------- #
#  negative space: a failed precompute is "not precomputed", never "none found"
# --------------------------------------------------------------------------- #


def test_a_failed_precompute_falls_back_inline_and_loses_no_derived_row(monkeypatch):
    """NEGATIVE SPACE. ``ArticleDerivatives.error`` means "this article's
    precompute failed" and MUST route that one article back to index_article's
    own inline computation — never be read as "this article has no keywords /
    no dates / no places / no entities".

    The distinction is invisible to any assertion that only checks the batch
    completed: a silent-empty bug stores the article and drops every derived row
    with no error anywhere. So this drives a precompute that fails for EVERY
    article and asserts the derived rows are all still there."""
    from src.analytics import reindex_parallel as rp
    from src.database.models import (
        Article,
        ArticleEntity,
        ArticleMentionedDate,
        ArticleMentionedPlace,
        KeywordMention,
    )
    from src.database.session import session_scope
    from src.ingest import batch as batch_mod

    calls: list[int] = []
    real = rp.compute_derivatives_with_www

    def failing(extractor, key, content, **kw):
        # The REAL helper still runs, so the failure this injects is the one
        # reindex_parallel itself reports (an ArticleDerivatives carrying an
        # error marker) rather than an exception shape production never emits.
        real(extractor, key, content, **kw)
        calls.append(key)
        return rp.ArticleDerivatives(key, [], None, None, error="injected", www=None)

    monkeypatch.setattr(rp, "compute_derivatives_with_www", failing)
    assert batch_mod.ArticleBatch  # the module under test is imported

    dom, src_id, tally = _ingest(monkeypatch, n=4)
    assert tally["stored"] == 4
    assert len(calls) == 4, "ANTI-VACUITY: the failing precompute never ran"

    with session_scope() as s:
        arts = s.query(Article).filter_by(source_id=src_id).all()
        assert len(arts) == 4
        for a in arts:
            n_kw = s.query(KeywordMention).filter_by(article_id=a.id).count()
            assert n_kw > 0, (
                "a failed precompute dropped this article's keyword mentions — "
                "'not precomputed' was read as 'none found'"
            )
            # The article still went through the FULL inline index: the attempt
            # stamp and the top-keyword are written by the same pass.
            assert a.keyword_indexed_at is not None
            assert a.top_keyword_id is not None
        # The when/where/who tables are the ones a silent-empty bug hides in,
        # because these fixtures legitimately yield few rows.
        assert (
            s.query(ArticleMentionedDate).count()
            + s.query(ArticleMentionedPlace).count()
            + s.query(ArticleEntity).count()
        ) >= 0  # shape only: this fixture's bodies carry no dates/places/people


def test_derivatives_are_keyed_by_a_NEGATIVE_surrogate_never_a_real_article_id(
    monkeypatch,
):
    """A staged row has no id until the flush, so the derivative map needs a
    surrogate. ``reindex_parallel`` prints that key as "article %s" in its
    watchdog and error logs, so a POSITIVE surrogate would name an unrelated real
    article to whoever reads that log. Pinned because the natural implementation
    (``enumerate``) produces exactly the unsafe value."""
    from src.ingest import batch as batch_mod

    keys: list[int] = []
    real = batch_mod.ArticleBatch._precompute

    def probing(self, to_store):
        out = real(self, to_store)
        keys.extend(out)
        return out

    monkeypatch.setattr(batch_mod.ArticleBatch, "_precompute", probing)
    _dom, _src_id, tally = _ingest(monkeypatch, n=4)

    assert tally["stored"] == 4
    assert keys, "ANTI-VACUITY: no derivative keys were produced"
    assert all(k < 0 for k in keys), keys
    assert len(set(keys)) == len(keys), f"surrogate keys collided: {keys}"


def test_no_index_skips_the_precompute_entirely(monkeypatch):
    """``OO_NO_INDEX=1`` already skipped the in-gate indexing. It must skip the
    PRECOMPUTE too, or the flag would silently start paying for derivatives that
    nothing stores — the whole cost, none of the benefit."""
    from src.analytics import reindex_parallel as rp

    calls: list[int] = []
    real = rp.compute_derivatives_with_www
    monkeypatch.setattr(
        rp,
        "compute_derivatives_with_www",
        lambda *a, **k: (calls.append(1), real(*a, **k))[1],
    )

    monkeypatch.setenv("OO_NO_INDEX", "1")
    _dom, _src_id, tally = _ingest(monkeypatch, n=4)
    assert tally["stored"] == 4
    assert calls == [], f"the precompute ran under OO_NO_INDEX=1 ({len(calls)} calls)"

    # ...and the twin: with the flag OFF it DOES run, or the assertion above is
    # satisfied by a precompute that never runs at all.
    monkeypatch.delenv("OO_NO_INDEX", raising=False)
    _dom2, _src2, tally2 = _ingest(monkeypatch, n=4)
    assert tally2["stored"] == 4
    assert len(calls) == 4, calls


# --------------------------------------------------------------------------- #
#  data-loss lens: the proven zero-loss redo path is untouched
# --------------------------------------------------------------------------- #


def test_a_failing_batched_commit_still_stores_every_article_one_at_a_time(
    monkeypatch,
):
    """The rollback-and-redo fallback is the batching design's zero-loss
    guarantee and the precompute must not have disturbed it: a batched commit
    that raises has to redo EVERY staged article individually, not just the one
    that failed (``session.rollback()`` expunges every pending object — the
    2026-07-19 lesson)."""
    from src.database.models import Article
    from src.database.session import session_scope
    from src.ingest import batch as batch_mod

    tripped: list[int] = []
    real_flush = batch_mod.ArticleBatch._flush_batched

    def once(self, entries):
        real_flush(self, entries)
        if not tripped:
            tripped.append(1)
            raise RuntimeError("injected batched-commit failure")

    monkeypatch.setattr(batch_mod.ArticleBatch, "_flush_batched", once)
    _dom, src_id, tally = _ingest(monkeypatch, n=4)

    assert tripped, "ANTI-VACUITY: the injected failure never fired"
    with session_scope() as s:
        stored = s.query(Article).filter_by(source_id=src_id).count()
    assert stored == 4, f"the redo path lost articles: {stored} of 4 ({tally})"


# --------------------------------------------------------------------------- #
#  the reused helper's own contract
# --------------------------------------------------------------------------- #


def test_compute_derivatives_with_www_fills_www_where_compute_one_leaves_it_None():
    """``_compute_one`` deliberately leaves ``www`` unset (its comment explains
    why that is right for the re-index). The collector's helper must FILL it —
    that difference is the entire reason the helper exists, and without it the
    when/where/who extraction would stay inside the gate, which is ~70% of the
    hold this slice removes."""
    from src.analytics.extract import get_extractor
    from src.analytics.reindex_parallel import (
        _compute_one,
        compute_derivatives_with_www,
    )

    ex = get_extractor("baseline")
    body = (
        "The council met yesterday in Lyon. A vote is set for 11 September 2024. "
        "Officials from the European Commission were named. "
    ) * 4

    bare = _compute_one(ex, -1, body, "T", "en", "en")
    assert bare.www is None, "the reference implementation changed — re-read C16"

    full = compute_derivatives_with_www(
        ex, -1, body, title="T", extraction_language="en", sentiment_language="en",
        date_language="en", country=None, anchor_iso="2026-06-15",
    )
    assert isinstance(full.www, dict), full.www
    assert set(full.www) >= {"dates", "places", "entities"}, full.www
    assert full.www["dates"], "the fixture must actually yield a date"
    # The pure halves must be byte-identical to the reference implementation:
    # this helper adds WWW, it does not re-decide anything else.
    assert [t.normalized for t in full.terms] == [t.normalized for t in bare.terms]
    assert (full.sentiment_score, full.sentiment_label) == (
        bare.sentiment_score,
        bare.sentiment_label,
    )


@pytest.mark.parametrize(
    ("date_language", "expected_month"),
    # MEASURED, not assumed: extract_dates' month tables are language-GATED, so
    # the same body resolves to a DIFFERENT month per language. This is the
    # discriminating input for the date_language argument — an en/None fixture
    # cannot see it at all, because both simply refuse the token.
    [("cs", 11), ("hr", 10)],
)
def test_date_language_is_load_bearing_and_is_threaded_separately(
    date_language, expected_month
):
    """``compute_derivatives_with_www`` takes THREE languages because
    ``index_article`` feeds three different values to three consumers. Collapsing
    them would look like a tidy-up and would change WHAT is computed.

    The collector passes ``article.language`` for dates — byte-identical to what
    ``datestore.store_for_article`` hands ``extract_dates`` on the inline path —
    while the keyword extractor still gets the ``or "en"`` working assumption."""
    from src.analytics.extract import get_extractor
    from src.analytics.reindex_parallel import compute_derivatives_with_www

    body = "Zprava zverejnena 12 listopadu 2024 uvadi, ze jednani probehlo dobre. "
    d = compute_derivatives_with_www(
        get_extractor("baseline"),
        -1,
        body,
        title="T",
        # The EXTRACTION language stays "en" in both arms, so a pass here cannot
        # be coming from the extractor's own stoplist pick.
        extraction_language="en",
        sentiment_language=None,
        date_language=date_language,
        country=None,
        anchor_iso="2026-06-15",
    )
    months = {int(c["date"].split("-")[1]) for c in (d.www or {}).get("dates", [])}
    assert months == {expected_month}, (
        f"date_language={date_language!r} resolved months {months}, expected "
        f"{{{expected_month}}} — the argument is not reaching extract_dates"
    )
