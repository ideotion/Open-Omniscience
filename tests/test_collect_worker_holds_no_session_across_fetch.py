"""S1.0 — a collector worker must not hold a pooled connection across a fetch.

The measured headline of the 2026-09-02 crash analysis: each pooled SQLite
connection carries its own ``PRAGMA cache_size`` page cache, and the collector's
worker kept ONE transaction open from the feed's conditional-GET read, across the
feed fetch and across every article fetch, until the feed bookkeeping committed at
the end. N concurrent workers therefore pinned N page caches for the duration of
the slowest fetch — and the bandwidth governor's back-off cannot reclaim any of
it, because its own contract never preempts a holder.

What is pinned here:

  * the MECHANISM (SQLAlchemy's own behaviour, measured not assumed): an idle
    session holds no connection and re-acquires transparently;
  * the PROPERTY: with N workers blocked inside a fetch, ``pool.checkedout()``
    stays at zero — and the negative twin, that the pre-fix shape reaches N;
  * the OUTCOME is unchanged: the same articles are stored and the tally is the
    same, so the memory is not bought with a behaviour change;
  * the release DECLINES on a dirty session (a rollback there would discard
    pending work — the recorded mid-batch data-loss shape).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from src.database.session import release_idle_connection
from src.ingest.fetch_release import SessionReleasingFetcher, wrap_fetcher


# --------------------------------------------------------------------------- #
# The mechanism this whole slice rests on.
# --------------------------------------------------------------------------- #
def _pooled_engine(path, *, pool_size=2, overflow=4):
    """A real QueuePool engine on a real file — the shape production uses.

    File-backed, not ``sqlite://``: with a QueuePool every in-memory connection is
    its OWN database, so a table created on one is invisible to the next and the
    fixture would be measuring the wrong thing. ``check_same_thread=False`` for the
    same reason production sets it — pooled connections cross threads.
    """
    return sa.create_engine(
        f"sqlite:///{path}",
        poolclass=sa.pool.QueuePool,
        pool_size=pool_size,
        max_overflow=overflow,
        connect_args={"check_same_thread": False},
    )


@pytest.fixture()
def pooled(tmp_path):
    engine = _pooled_engine(tmp_path / "pool.db")
    yield engine, sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    engine.dispose()


def test_an_idle_session_holds_no_pooled_connection(pooled):
    """Measured, never reasoned: the premise the fix is built on."""
    engine, SL = pooled
    s = SL()
    try:
        assert engine.pool.checkedout() == 0
        s.execute(sa.text("select 1")).scalar()
        assert engine.pool.checkedout() == 1, "a read must check a connection out"
        assert release_idle_connection(s) is True
        assert engine.pool.checkedout() == 0, "ending the transaction must hand it back"
        # ...and the session still works: it re-acquires on the next statement.
        s.execute(sa.text("select 1")).scalar()
        assert engine.pool.checkedout() == 1
    finally:
        s.close()


def test_releasing_declines_on_a_dirty_session_and_the_pending_row_survives(pooled):
    """A rollback would DISCARD pending work — so a dirty session is left alone.

    The load-bearing half is the SURVIVAL assertion: a version that released
    unconditionally would still return, and only the row's fate says whether the
    caller's staged work was thrown away (the recorded mid-batch-rollback shape).
    """
    engine, SL = pooled
    Base = sa.orm.declarative_base()

    class Row(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "row_t"
        id = sa.Column(sa.Integer, primary_key=True)
        v = sa.Column(sa.String)

    Base.metadata.create_all(engine)
    s = SL()
    try:
        s.add(Row(v="pending"))
        assert s.new, "the fixture must actually make the session dirty"
        # Both halves are evaluated: asserting the return value FIRST would make the
        # survival check unreachable under the very mutation it exists to catch.
        released = release_idle_connection(s)
        s.commit()
        assert s.query(Row).count() == 1, "the pending row must NOT have been discarded"
        assert released is False, "a dirty session must be declined"
    finally:
        s.close()


def test_the_guard_declines_every_state_a_rollback_would_destroy(pooled):
    """The negative space of the guard, one state per mutation it must survive.

    The first cut checked ``session.new/dirty/deleted`` only. Those are empty the
    moment a caller FLUSHES, while the rows sit unwritten in the open
    transaction — so the guard released, and the flushed work was discarded.
    Reduced to ``if session.new:`` it survived the whole suite, because the only
    fixture used ``session.add()``. One case each, all four reproduced live.
    """
    engine, SL = pooled
    Base = sa.orm.declarative_base()

    class Row(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "guard_t"
        id = sa.Column(sa.Integer, primary_key=True)
        v = sa.Column(sa.String)

    Base.metadata.create_all(engine)

    # (a) FLUSHED but uncommitted — invisible to new/dirty/deleted.
    s = SL()
    try:
        s.add(Row(v="flushed"))
        s.flush()
        assert not (s.new or s.dirty or s.deleted), "the fixture must reach the blind state"
        released = release_idle_connection(s)
        s.commit()
        assert s.query(Row).count() == 1, "a flushed row must not be discarded"
        assert released is False
    finally:
        s.close()

    # (b) DIRTY: a modified persistent object (never `new`).
    s = SL()
    try:
        row = s.query(Row).first()
        row.v = "modified"
        assert s.dirty
        assert release_idle_connection(s) is False
        s.commit()
        assert s.query(Row).filter_by(v="modified").count() == 1
    finally:
        s.close()

    # (c) DELETED.
    s = SL()
    try:
        s.delete(s.query(Row).first())
        assert s.deleted
        assert release_idle_connection(s) is False
        s.rollback()
    finally:
        s.close()

    # (d) An open SAVEPOINT that has WRITTEN: rollback() goes to the ROOT, taking
    # the caller's enclosing block with it.
    s = SL()
    try:
        s.query(Row).count()  # open the outer transaction with a read
        nested = s.begin_nested()
        s.add(Row(v="in-savepoint"))
        s.flush()
        assert s.in_nested_transaction()
        assert release_idle_connection(s) is False
        assert s.in_nested_transaction(), "the savepoint must survive"
        nested.commit()
        s.commit()
        assert s.query(Row).filter_by(v="in-savepoint").count() == 1
    finally:
        s.close()

    # (e) An open SAVEPOINT that has NOT yet written — the case only the
    # savepoint check catches. Removing that check reddened NOTHING while (d)
    # was the only savepoint fixture, because (d) flushes and so is already
    # declined by the has-written marker.
    s = SL()
    try:
        s.query(Row).count()
        nested = s.begin_nested()
        s.query(Row).count()  # a READ inside the savepoint: nothing written yet
        assert s.in_nested_transaction()
        assert not s.info.get("_oo_txn_wrote"), "the fixture must reach the blind state"
        assert release_idle_connection(s) is False
        assert s.in_nested_transaction(), "an unwritten savepoint must survive too"
        nested.commit()
        s.commit()
    finally:
        s.close()


def test_the_guard_declines_bulk_dml_that_leaves_no_orm_state(pooled):
    """``session.execute(insert())`` is invisible to new/dirty/deleted entirely.

    It is caught only by a transaction-level "has written" marker — the ORM
    collections cannot see it at all — and that marker is tracked on the Session
    CLASS so it holds on this isolated engine too, not only on the gated one.
    """
    engine, SL = pooled
    Base = sa.orm.declarative_base()

    class Row(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "bulk_t"
        id = sa.Column(sa.Integer, primary_key=True)
        v = sa.Column(sa.String)

    Base.metadata.create_all(engine)
    s = SL()
    try:
        s.execute(sa.insert(Row).values(v="bulk"))
        assert not (s.new or s.dirty or s.deleted)
        released = release_idle_connection(s)
        s.commit()
        assert s.query(Row).count() == 1, "the bulk insert must not be discarded"
        assert released is False
    finally:
        s.close()


def test_the_session_double_implements_everything_the_guard_reads():
    """A double that omits an attribute the guard reads makes it silently decline.

    That happened: when the guard grew its ``session.info`` and
    ``in_nested_transaction`` checks, the double lacked both, the guard raised
    into its own except, and two tests started passing for the wrong reason.
    """
    import ast as _ast
    import inspect as _inspect

    import textwrap as _tw

    tree = _ast.parse(_tw.dedent(_inspect.getsource(release_idle_connection)))
    reads = {
        n.attr
        for n in _ast.walk(tree)
        if isinstance(n, _ast.Attribute)
        and isinstance(n.value, _ast.Name)
        and n.value.id == "session"
    }
    assert reads, "the guard must read something off the session"
    double = _CountingSession()
    missing = {a for a in reads if not hasattr(double, a)}
    assert not missing, f"the test double is missing {sorted(missing)}"


def test_releasing_never_raises_on_a_broken_session():
    """The hot path must never pay for a release that cannot happen."""

    class _Broken:
        new: tuple = ()
        dirty: tuple = ()
        deleted: tuple = ()

        def in_transaction(self):
            raise RuntimeError("no")

    assert release_idle_connection(_Broken()) is False


# --------------------------------------------------------------------------- #
# The proxy.
# --------------------------------------------------------------------------- #
class _RecordingFetcher:
    def __init__(self, on_fetch=None):
        self.calls: list[str] = []
        self._on_fetch = on_fetch
        self.host_cache = {"kept": 1}

    def fetch(self, url, **kw):
        self.calls.append(url)
        if self._on_fetch:
            self._on_fetch()
        return f"body:{url}"

    def declared_sitemaps(self, url):
        self.calls.append(f"sitemaps:{url}")
        return []

    def cache_stats(self):
        return {"n": 1}


class _CountingSession:
    """A double for a READ-ONLY session in an open transaction.

    Pinned against the real ``Session`` by
    ``test_the_session_double_implements_everything_the_guard_reads`` — a
    hand-written double that omits an attribute the guard consults would make the
    guard silently decline and every test here pass for the wrong reason (which
    is exactly what happened when the guard grew its write-gate check)."""

    def __init__(self):
        self.new: tuple = ()
        self.dirty: tuple = ()
        self.deleted: tuple = ()
        self.info: dict = {}
        self.rollbacks = 0
        self._in_txn = True
        self._in_nested = False

    def in_transaction(self):
        return self._in_txn

    def in_nested_transaction(self):
        return self._in_nested

    def rollback(self):
        self.rollbacks += 1
        self._in_txn = False


def test_every_wrapped_method_releases_BEFORE_it_reaches_the_network():
    """Ordering, checked from inside the call — and over the real method list.

    Asserting the rollback count AFTER the call returns cannot tell release-first
    from release-after: moving ``_release()`` below the delegation in
    ``declared_sitemaps`` alone survived the entire suite. The fake records the
    count at the moment it is entered, and the loop covers whatever
    ``_NETWORK_METHODS`` names, so a method added there is covered without being
    remembered here.
    """
    from src.ingest import fetch_release as fr

    for name in fr._NETWORK_METHODS:
        sess = _CountingSession()
        seen: list[int] = []

        class _Probe:
            def __init__(self, session, log):
                self._s, self._log = session, log

            def __getattr__(self, _n):
                session, log = self._s, self._log

                def _call(*_a, **_kw):
                    log.append(session.rollbacks)
                    return "ok"

                return _call

        proxy = wrap_fetcher(_Probe(sess, seen), sess)
        getattr(proxy, name)("https://example.org/")
        assert seen == [1], (
            f"{name}: the session must already be released when the network is "
            f"reached (rollbacks at entry: {seen})"
        )


def test_the_proxy_is_transparent_for_everything_local():
    proxy = wrap_fetcher(_RecordingFetcher(), _CountingSession())
    assert proxy.cache_stats() == {"n": 1}
    assert proxy.host_cache == {"kept": 1}


def test_an_unknown_private_name_raises_instead_of_recursing():
    """``__slots__`` + ``__getattr__`` recurses on an instance built without
    ``__init__`` (copy, pickle) because the handler reads ``self._fetcher``, which
    is exactly the attribute that is missing. Bail out on private names first."""
    import copy as _copy

    proxy = wrap_fetcher(_RecordingFetcher(), _CountingSession())
    with pytest.raises(AttributeError):
        proxy._not_a_real_attribute  # noqa: B018 - the access IS the assertion
    # copy/pickle are the paths that build an instance with unset slots.
    try:
        _copy.copy(proxy)
    except RecursionError:  # pragma: no cover - the defect this pins
        raise AssertionError("__getattr__ recursed instead of raising") from None
    except Exception:
        pass  # any ordinary failure is fine; a RecursionError is not


def test_re_wrapping_rebinds_the_session_instead_of_nesting():
    """A nested pair would roll back a session the caller never named."""
    first, second = _CountingSession(), _CountingSession()
    raw = _RecordingFetcher()
    once = wrap_fetcher(raw, first)
    twice = wrap_fetcher(once, second)
    assert twice._fetcher is raw, "the raw fetcher must be rebound, not nested"
    twice.fetch("https://example.org/a")
    assert second.rollbacks == 1
    assert first.rollbacks == 0, "the first session must not be touched"


def test_wrapping_is_a_no_op_without_a_session_or_a_fetcher():
    f = _RecordingFetcher()
    assert wrap_fetcher(f, None) is f
    assert wrap_fetcher(None, _CountingSession()) is None


def test_the_release_count_is_measured_not_assumed():
    sess = _CountingSession()
    proxy = wrap_fetcher(_RecordingFetcher(), sess)
    assert isinstance(proxy, SessionReleasingFetcher)
    assert proxy.releases == 0
    proxy.fetch("https://example.org/a")
    assert proxy.releases == 1
    # A session already out of a transaction releases nothing — and says so.
    proxy.fetch("https://example.org/b")
    assert proxy.releases == 1


def test_the_network_method_list_matches_the_fetchers_own_network_surface():
    """A new PUBLIC fetcher method must be classified as wrapped or as local.

    Scoped honestly: it covers the PUBLIC surface only. The fetcher's private
    network helpers (``_guarded_redirect_get``, ``_http_get``, ``_get_robots``)
    are delegated un-released by ``__getattr__`` — and ``monitoring/preflight.py``
    and ``feed_preflight.py`` already call them directly, outside this wrapper
    either way. ``AsyncFunctionDef`` is included because filtering on
    ``FunctionDef`` alone let an async network method through the one guard that
    exists to catch it.
    """
    from src.ingest import fetch_release

    src = Path("src/ingest/__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "EthicalFetcher"
    )
    public = {
        n.name
        for n in cls.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        and not n.name.startswith("_")
    }
    # Everything public on the fetcher is either wrapped or a LOCAL read.
    local_only = {"cache_stats"}
    assert public - local_only == set(fetch_release._NETWORK_METHODS), (
        "EthicalFetcher's public surface changed: decide whether the new method "
        "reaches the network (wrap it) or is local (add it to local_only)."
    )


# --------------------------------------------------------------------------- #
# The property, driven through a fixture SHAPED like the worker (a store-side
# read, then a blocking network call). The real seam is covered structurally by
# test_process_source_pairs_the_fetcher_with_its_own_session and behaviourally by
# the real-ingest_source test at the end of this file.
# --------------------------------------------------------------------------- #
def _blocking_pass(tmp_path, *, wrap: bool, workers: int = 4):
    """Dispatch ``workers`` threads that each read then block inside a 'fetch'.

    Returns the peak ``pool.checkedout()`` observed while every worker was inside
    its fetch — the number the brief asks for.
    """
    engine = _pooled_engine(
        tmp_path / f"blocking-{wrap}.db", pool_size=workers, overflow=workers
    )
    SL = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    all_in = threading.Barrier(workers + 1, timeout=20)
    release = threading.Event()

    def _blocked():
        all_in.wait()
        release.wait(timeout=20)

    def _worker():
        s = SL()
        try:
            # The pipeline's shape: a store-side READ (the dedup check), then the
            # network call that today runs inside that same transaction.
            s.execute(sa.text("select 1")).scalar()
            raw = _RecordingFetcher(on_fetch=_blocked)
            fetcher = wrap_fetcher(raw, s) if wrap else raw
            fetcher.fetch("https://example.org/x")
        finally:
            s.close()

    threads = [threading.Thread(target=_worker) for _ in range(workers)]
    for t in threads:
        t.start()
    try:
        all_in.wait()  # every worker is now INSIDE its fetch
        peak = engine.pool.checkedout()
    finally:
        release.set()
        for t in threads:
            t.join(timeout=20)
        engine.dispose()
    return peak


def test_no_connection_is_held_while_every_worker_is_inside_its_fetch(tmp_path):
    assert _blocking_pass(tmp_path, wrap=True, workers=4) == 0


def test_the_negative_twin_the_unwrapped_shape_pins_one_connection_per_worker(tmp_path):
    """Without the wrapper the same pass reaches one checked-out connection per
    worker — the pre-fix behaviour, so the assertion above cannot pass for free."""
    assert _blocking_pass(tmp_path, wrap=False, workers=4) == 4


def test_process_source_pairs_the_fetcher_with_its_own_session():
    """Structural: the ONE site that owns both must do the pairing.

    Read comment-stripped, so the comment that EXPLAINS the pairing cannot
    satisfy the guard on its own.
    """
    src = Path("src/scheduler/runner.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    tree = ast.parse(body)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_process_source"
    )
    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "wrap_fetcher"
    ]
    assert calls, "_process_source must pair the fetcher with its session"
    assert {a.id for a in calls[0].args if isinstance(a, ast.Name)} == {
        "fetcher",
        "session",
    }
    # ...and the RESULT must become ``fetcher``. Asserting only that the call
    # EXISTS passed against `_unused = wrap_fetcher(fetcher, session)`, under
    # which ingest_source/crawl_source get the raw fetcher and the entire change
    # is inert — with nothing else in the suite catching it.
    assigns = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "wrap_fetcher"
    ]
    assert assigns, "the wrapped fetcher must be assigned, not discarded"
    assert any(
        isinstance(t, ast.Name) and t.id == "fetcher" for a in assigns for t in a.targets
    ), "the wrapper must be bound to `fetcher`, or the call sites get the raw one"


# --------------------------------------------------------------------------- #
# The outcome is unchanged: the memory is not bought with a behaviour change.
# --------------------------------------------------------------------------- #
_PROSE = (
    "The committee published its findings on Tuesday after a review that lasted "
    "several months and drew on evidence from more than a dozen witnesses. The "
    "report describes how the programme was funded, who approved each stage, and "
    "which of the original commitments were met. Officials said the recommendations "
    "would be considered in full, while critics argued that the timetable leaves "
    "little room for meaningful change before the end of the year. A spokesperson "
    "confirmed that the underlying data would be published alongside the report so "
    "that independent analysts can check the calculations for themselves. "
) * 3


def _feed(links):
    items = "".join(f"<item><link>{u}</link><title>t</title></item>" for u in links)
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        f"{items}</channel></rss>"
    )


def _run_ingest(*, wrap: bool, tag: str):
    """Drive the REAL ``ingest_source`` once, with and without the wrapper."""
    import uuid
    from datetime import UTC, datetime

    from src.database.models import Source
    from src.database.session import SessionLocal, init_db
    from src.ingest import FetchResult
    from src.ingest.pipeline import ingest_source

    init_db()
    host = f"{tag}-{uuid.uuid4().hex[:8]}.example"
    links = [f"https://{host}/a{i}" for i in range(3)]

    def _res(url, content, ctype):
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content=content,
            content_type=ctype,
            fetched_at=datetime.now(UTC),
        )

    class _Feeder:
        def fetch(self, url, *, require_html=True, extra_headers=None):
            if url.endswith("/rss"):
                return _res(url, _feed(links), "application/rss+xml")
            # Each body must be UNIQUE — content-hash dedup is by design, so a
            # shared paragraph would collapse the three articles into one stored
            # and two duplicates, and a second run would then find them all
            # already stored. The fixture would be measuring its own text, not
            # the wrapper.
            return _res(
                url,
                f"<html><head><title>Report {url}</title></head>"
                f"<body><article><p>{url} — {_PROSE}</p></article></body></html>",
                "text/html",
            )

    s = SessionLocal()
    try:
        src = Source(
            name=f"S {host}", domain=host, rss_url=f"https://{host}/rss", language="en"
        )
        s.add(src)
        s.commit()
        source_id = src.id
        raw = _Feeder()
        fetcher = wrap_fetcher(raw, s) if wrap else raw
        tally = ingest_source(s, src, fetcher=fetcher)
        releases = getattr(fetcher, "releases", None)
        return tally, releases, source_id
    finally:
        s.close()


def _shared_db_counts() -> dict[str, int]:
    from src.database.models import Article, Keyword, KeywordMention, Source
    from src.database.session import SessionLocal, init_db

    init_db()
    s = SessionLocal()
    try:
        return {
            m.__name__: s.query(m).count()
            for m in (Source, Article, Keyword, KeywordMention)
        }
    finally:
        s.close()


def _drop_run(source_id: int) -> None:
    """Undo everything ``_run_ingest`` committed into the SHARED session DB.

    The recorded 2026-07-06 rule is never to seed ``SessionLocal`` — one
    ``OO_DATA_DIR`` is bound for the whole pytest session, so rows persist for
    every later test, and two ENABLED sources is the shape that has reddened
    ``test_preflight`` before. Driving the REAL ``ingest_source`` is the point of
    this test, so instead of a lookalike engine it cleans up after itself, and
    the caller ASSERTS the counts are restored — which is a stronger claim than
    isolation would have made.
    """
    from sqlalchemy import delete

    from src.database.models import Article, FeedFetchState, Keyword, KeywordMention, Source
    from src.database.session import SessionLocal

    s = SessionLocal()
    try:
        ids = [a.id for a in s.query(Article.id).filter(Article.source_id == source_id).all()]
        if ids:
            s.execute(delete(KeywordMention).where(KeywordMention.article_id.in_(ids)))
        s.execute(delete(Article).where(Article.source_id == source_id))
        s.execute(delete(FeedFetchState).where(FeedFetchState.source_id == source_id))
        s.execute(delete(Source).where(Source.id == source_id))
        # Keywords created by this run are orphans once the mentions are gone.
        s.execute(
            delete(Keyword).where(
                ~Keyword.id.in_(s.query(KeywordMention.keyword_id).distinct())
            )
        )
        s.commit()
    finally:
        s.close()


def test_the_tally_is_unchanged_and_the_wrapper_really_ran():
    before = _shared_db_counts()
    plain, plain_releases, plain_id = _run_ingest(wrap=False, tag="plain")
    wrapped, wrapped_releases, wrapped_id = _run_ingest(wrap=True, tag="wrapped")
    try:
        _assert_outcomes(plain, plain_releases, wrapped, wrapped_releases)
    finally:
        _drop_run(plain_id)
        _drop_run(wrapped_id)
    assert _shared_db_counts() == before, (
        "this test drives the REAL ingest_source against the shared session DB; "
        "it must leave it exactly as it found it"
    )


def _assert_outcomes(plain, plain_releases, wrapped, wrapped_releases):
    assert plain_releases is None, "the control must not be wrapped"
    assert wrapped_releases and wrapped_releases > 0, (
        "the wrapped run must actually have released a connection — otherwise an "
        "identical tally proves nothing about the wrapper"
    )
    assert plain == wrapped, (plain, wrapped)
    assert plain.get("stored") == 3, plain
