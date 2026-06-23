"""Field-log data-loss regression: import + scrape never collide on the writer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the END-TO-END proof of the single-writer gate (keystone #1,
SCRAPING_AUTOMATION_PLAN Step 2) against the EXACT scenario the maintainer
elevated (field log 2026-06-13, finding A):

  A commodity import collided with the active scrape on the single SQLite
  writer. Copper/aluminum/nickel/zinc were FETCHED OK over Tor, then FAILED TO
  STORE -- "store error: OperationalError: database is locked", retryable:false
  -- and the real downloaded data was DISCARDED. WAL lets readers pass but two
  WRITERS still serialise at the SQLite layer.

``tests/test_write_gate.py`` proves the gate PRIMITIVE on a throwaway
sessionmaker. THIS file proves the bug is closed where it actually bit, in two
complementary ways:

  1. ``test_concurrent_import_and_scrape_lose_no_data`` -- an INTEGRATION test on
     the REAL application ``SessionLocal`` (with the production gate wiring from
     ``src/database/session.py``) + the REAL ``import_points`` (the function that
     lost the metals) racing a scrape-style ``Article`` store. The system as a
     whole loses nothing. (Defence-in-depth -- gate + 30 s busy_timeout +
     ``run_write_with_retry`` -- all contribute; this asserts the OUTCOME the
     maintainer requires: every fetched row persists.)

  2. ``test_gate_is_what_prevents_the_lock`` -- the ISOLATION proof that the GATE
     itself is load-bearing, not redundant: on a deliberately hostile engine
     (a short busy_timeout, the retry backstop bypassed -- the field-log
     condition) the SAME concurrent writers raise "database is locked" WITHOUT
     the gate handlers, and ZERO with them. This is the controlled experiment
     behind claim (1).

Plus the WAL invariant: a READ proceeds while a write holds the gate -- reads
are NEVER serialised.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Integer, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import (
    Article,
    ArticleMentionedDate,
    CommodityPrice,
    Keyword,
    KeywordMention,
    Source,
)
from src.database.session import SessionLocal, init_db, session_scope
from src.database.write import is_locked_error
from src.database.writer import (
    _on_after_transaction_end,
    _on_before_flush,
    gate_enabled,
    write_gate,
)
from src.markets.csv_feeds import import_points

# --------------------------------------------------------------------------- #
# Helpers (real app wiring)
# --------------------------------------------------------------------------- #


def _make_source(tag: str) -> int:
    """Persist one Source (the FK every Article needs) and return its id."""
    with session_scope() as s:
        src = Source(name=f"src-{tag}", domain=f"{tag}.example", enabled=True, language="en")
        s.add(src)
        s.flush()
        return int(src.id)


def _store_article(source_id: int, tag: str, n: int) -> None:
    """Write ONE article the way the ingest pipeline does: ORM add + commit.

    Each row is unique (the ``hash`` column is UNIQUE), so a successful run is
    provable by an exact count -- a lost write shows up as a missing row.
    """
    with session_scope() as s:
        uniq = f"{tag}-{n}-{uuid.uuid4().hex}"
        s.add(
            Article(
                url=f"https://{tag}.example/{uniq}",
                canonical_url=f"https://{tag}.example/{uniq}",
                source_id=source_id,
                title=f"art {uniq}",
                content=f"body of article {uniq}",
                hash=uniq,
                language="en",
            )
        )
        # session_scope commits on exit -> gate taken on flush, released on the
        # transaction end. No call-site change: this is the production wiring.


# --------------------------------------------------------------------------- #
# (1) Integration: the field-log scenario on the real SessionLocal
# --------------------------------------------------------------------------- #


def test_concurrent_import_and_scrape_lose_no_data():
    """The copper/nickel loss must be impossible: a real ``import_points`` and a
    real article store, run concurrently against the app ``SessionLocal``, both
    persist EVERY row with zero "database is locked"."""
    init_db()
    tag = "dl" + uuid.uuid4().hex[:6]
    source_id = _make_source(tag)

    symbols = [f"{tag}_Cu", f"{tag}_Al", f"{tag}_Ni", f"{tag}_Zn"]  # the field-log metals
    points_per_symbol = 30
    base = date(2026, 1, 1)
    series = {
        sym: [(base + timedelta(days=i), 100.0 + i) for i in range(points_per_symbol)]
        for sym in symbols
    }
    n_scrape_threads, articles_per_thread = 3, 20

    errors: list[BaseException] = []
    locked_errors: list[BaseException] = []
    import_results: list[dict] = []

    def _record(exc: BaseException) -> None:
        # Every failure goes to ``errors``; a lock additionally to ``locked_errors``
        # so the assertion can name the field-log regression specifically.
        errors.append(exc)
        if is_locked_error(exc):
            locked_errors.append(exc)

    def import_worker(sym: str) -> None:
        s = SessionLocal()
        try:
            import_results.append(
                import_points(
                    s, symbol=sym, points=series[sym], market=f"{tag}_market",
                    source="field-log-regression",
                )
            )
        except BaseException as exc:  # noqa: BLE001 - capture for the assertion
            _record(exc)
        finally:
            s.close()

    def scrape_worker(start: int, count: int) -> None:
        try:
            for k in range(count):
                _store_article(source_id, tag, start + k)
        except BaseException as exc:  # noqa: BLE001 - capture for the assertion
            _record(exc)

    threads = [threading.Thread(target=import_worker, args=(s,), name=f"imp-{s}") for s in symbols]
    for w in range(n_scrape_threads):
        threads.append(
            threading.Thread(
                target=scrape_worker, args=(w * articles_per_thread, articles_per_thread),
                name=f"scrape-{w}",
            )
        )

    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)  # no-deadlock: the gate FIFO must drain well within this

    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"writers did not finish (possible deadlock): {alive}"
    assert locked_errors == [], (
        f"a writer hit 'database is locked' -- the field-log data loss is back: {locked_errors!r}"
    )
    assert errors == [], f"a concurrent writer failed unexpectedly: {errors!r}"

    expected_prices = len(symbols) * points_per_symbol
    expected_articles = n_scrape_threads * articles_per_thread
    with session_scope() as s:
        got_prices = (
            s.query(CommodityPrice).filter(CommodityPrice.market == f"{tag}_market").count()
        )
        got_articles = (
            s.query(Article).filter(Article.url.like(f"https://{tag}.example/%")).count()
        )
    assert got_prices == expected_prices, (
        f"commodity points were lost: stored {got_prices}, expected {expected_prices}"
    )
    assert got_articles == expected_articles, (
        f"scraped articles were lost: stored {got_articles}, expected {expected_articles}"
    )
    assert sum(r["imported"] for r in import_results) == expected_prices
    assert not write_gate.stats()["held"]  # no leak past the storm
    assert time.monotonic() - started < 60


# --------------------------------------------------------------------------- #
# (1b) Integration: the FULL index_article pipeline under parallel ingest load
# --------------------------------------------------------------------------- #


def test_parallel_index_article_loses_no_keyword_or_date_rows():
    """Many workers each ingest + index_article concurrently against the real
    gated ``SessionLocal``; ZERO keyword / mention / date rows are dropped and the
    denormalised keyword COUNTERS stay exact (field brief 2026-06-23 §3.1).

    Production runs up to ~50 parallel collect workers against one encrypted
    writer; ``index_article`` does several sub-writes per article (Keyword + a
    KeywordMention + the When/Where/Who rows) AND maintains the denormalised
    ``Keyword.mention_count`` / ``article_count`` via per-article deltas. If the
    single-writer gate let two such ingests interleave, a mention row could be
    lost OR a counter delta could be applied on a stale read. Every article here
    shares the keywords ("inflation", "elections", "economy", "summit") and the
    date "15 September 2024", so those keywords' counter deltas + that date's row
    are written under maximum contention — the strongest test of the gate."""
    init_db()
    tag = "ix" + uuid.uuid4().hex[:6]
    source_id = _make_source(tag)
    ext = BaselineExtractor()

    n_workers, articles_per_worker = 6, 15
    total = n_workers * articles_per_worker
    # A coined keyword created ONLY by this test (pure letters so the code-token
    # filter keeps it, no other test uses it) -> its corpus-wide counters are
    # provably exact regardless of what else lives in the shared test DB. The shared
    # natural keywords give a second, MY-article-scoped check that extraction landed.
    sentinel = "zzqxsentinel"
    body = (
        "the WHO summit in Berlin on 15 September 2024 discussed inflation and "
        f"elections across the wider economy worldwide {sentinel}"
    )

    errors: list[BaseException] = []
    locked_errors: list[BaseException] = []

    def _record(exc: BaseException) -> None:
        errors.append(exc)
        if is_locked_error(exc):
            locked_errors.append(exc)

    def ingest_worker(w: int) -> None:
        s = SessionLocal()
        try:
            for k in range(articles_per_worker):
                uniq = f"{tag}-{w}-{k}-{uuid.uuid4().hex}"
                a = Article(
                    url=f"https://{tag}.example/{uniq}",
                    canonical_url=f"https://{tag}.example/{uniq}",
                    source_id=source_id,
                    title=f"Report {uniq}",
                    content=f"Report on {body}.",
                    hash=uniq,
                    language="en",
                    published_at=datetime(2024, 9, 1, tzinfo=UTC),
                )
                s.add(a)
                s.flush()  # assign id (takes the gate)
                index_article(s, a, extractor=ext)  # sub-writes + commit, gated
        except BaseException as exc:  # noqa: BLE001 - capture for the assertion
            _record(exc)
        finally:
            s.close()

    threads = [
        threading.Thread(target=ingest_worker, args=(w,), name=f"ingest-{w}")
        for w in range(n_workers)
    ]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(90)

    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"ingest workers did not finish (possible deadlock): {alive}"
    assert locked_errors == [], (
        f"a worker hit 'database is locked' under parallel ingest: {locked_errors!r}"
    )
    assert errors == [], f"a concurrent ingest worker failed unexpectedly: {errors!r}"

    with session_scope() as s:
        ids = [
            r[0]
            for r in s.query(Article.id).filter(
                Article.url.like(f"https://{tag}.example/%")
            )
        ]
        assert len(ids) == total, f"articles lost: {len(ids)} != {total}"

        # ZERO dropped date rows: every article's When-row landed under contention.
        n_dates = (
            s.query(ArticleMentionedDate)
            .filter(ArticleMentionedDate.article_id.in_(ids))
            .count()
        )
        assert n_dates == total, f"date rows dropped: {n_dates} != {total}"

        # ZERO dropped mention rows + EXACT counters, proven on the SENTINEL keyword
        # (created only by this test, so its corpus-wide counters are provably exact).
        # A missing gate would drop a mention row OR drift the per-article counter
        # delta under contention -- both caught here.
        kw = s.query(Keyword).filter_by(normalized_term=sentinel).one()
        live = s.query(KeywordMention).filter_by(keyword_id=kw.id).count()
        assert live == total, f"sentinel mention rows dropped: {live} != {total}"
        assert kw.article_count == total, (
            f"sentinel article_count drift: {kw.article_count} != {total}"
        )
        assert kw.mention_count == total, (
            f"sentinel mention_count drift: {kw.mention_count} != {total}"
        )

        # The shared natural keywords also all landed -- scoped to MY articles so the
        # check is robust to a shared test DB other tests have written to (NEVER assert
        # corpus-wide positive facts against the shared singleton -- CLAUDE.md).
        for term in ("inflation", "elections", "economy"):
            kw2 = s.query(Keyword).filter_by(normalized_term=term).one()
            mine = (
                s.query(KeywordMention)
                .filter(
                    KeywordMention.keyword_id == kw2.id,
                    KeywordMention.article_id.in_(ids),
                )
                .count()
            )
            assert mine == total, f"mention rows dropped for {term!r}: {mine} != {total}"

    assert not write_gate.stats()["held"]  # no gate leak past the storm
    assert time.monotonic() - started < 90


# --------------------------------------------------------------------------- #
# (2) Isolation proof: the GATE is what prevents the lock (controlled experiment)
# --------------------------------------------------------------------------- #


class _Base(DeclarativeBase):
    pass


class _Px(_Base):
    """Stand-in for a price row: a tiny, fast write to maximise contention."""

    __tablename__ = "px_probe"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    w: Mapped[int] = mapped_column(Integer)


def _hostile_sessionmaker(tmp_path, *, with_gate: bool):
    """A file-backed SQLite sessionmaker reproducing the FIELD-LOG CONDITION:
    a short busy_timeout so two writers WILL collide, and the retry backstop is
    not in play (we add rows directly). ``with_gate`` toggles the production gate
    handlers so the gate's contribution is isolated."""
    db = tmp_path / f"hostile-{'gate' if with_gate else 'nogate'}.db"
    engine = create_engine(
        f"sqlite:///{db}", future=True, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=50")  # short: contention bites immediately
        cur.close()

    _Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, future=True)
    if with_gate:
        event.listen(maker, "before_flush", _on_before_flush)
        event.listen(maker, "after_transaction_end", _on_after_transaction_end)
    return engine, maker


def _hammer(maker, *, n_threads=8, per_thread=40):
    """Run many concurrent committing writers; return (locked_count, other_errs)."""
    locked: list[str] = []
    other: list[Exception] = []

    def worker(wid: int) -> None:
        for _ in range(per_thread):
            s = maker()
            try:
                s.add(_Px(w=wid))
                s.commit()
            except OperationalError as exc:
                (locked if is_locked_error(exc) else other).append(str(exc))
                try:
                    s.rollback()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                s.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return locked, other


def test_gate_is_what_prevents_the_lock(tmp_path):
    """Controlled experiment: on the hostile engine the SAME concurrent writers
    LOCK without the gate handlers and DON'T with them -- proving the gate is the
    fix, not a redundant layer over busy_timeout/retry.

    The control (no gate) is asserted to be a meaningful demonstration: if a slow
    CI box happened not to provoke a single lock without the gate, the experiment
    proves nothing, so we require the control to actually have raised the locked
    error before trusting the with-gate result. The with-gate run must be a clean
    zero regardless.
    """
    if not gate_enabled():  # pragma: no cover - escape hatch only
        return

    # Control: WITHOUT the gate, the field-log condition reproduces the loss.
    eng_ng, maker_ng = _hostile_sessionmaker(tmp_path, with_gate=False)
    try:
        locked_ng, other_ng = _hammer(maker_ng)
    finally:
        eng_ng.dispose()
    assert other_ng == [], f"unexpected non-lock error in the control: {other_ng!r}"
    if not locked_ng:
        # The control is a PRECONDITION, not the proof: if a fast box (e.g. the
        # macOS arm64 CI runner) cannot provoke contention, the experiment is
        # INCONCLUSIVE, not failed -- skip rather than redden a non-deterministic
        # timing race (OO-D15-006). The gate proof itself is the with-gate run
        # below (must be a clean zero) plus the end-to-end data-loss test.
        pytest.skip(
            "control did not reproduce 'database is locked' on this box -- the "
            "timing experiment is inconclusive here (the with-gate proof and the "
            "end-to-end data-loss test still cover the gate)"
        )

    # Treatment: WITH the production gate handlers, zero locks.
    eng_g, maker_g = _hostile_sessionmaker(tmp_path, with_gate=True)
    try:
        locked_g, other_g = _hammer(maker_g)
    finally:
        eng_g.dispose()
    assert other_g == [], f"unexpected non-lock error with the gate: {other_g!r}"
    assert locked_g == [], (
        f"the gate failed to prevent 'database is locked' ({len(locked_g)} locks) -- "
        "the single-writer serialisation regressed"
    )
    assert not write_gate.stats()["held"]  # no leak


# --------------------------------------------------------------------------- #
# (3) WAL invariant: a READ proceeds while a WRITE holds the gate
# --------------------------------------------------------------------------- #


def test_read_proceeds_while_a_write_holds_the_gate():
    """Reads must NEVER be serialised by the write gate -- WAL lets a reader pass
    a writer. We hold the gate on one thread (mid-write, as the gate intends) and
    prove a SELECT on another thread returns without waiting for the release."""
    if not gate_enabled():  # pragma: no cover - escape hatch only
        return
    init_db()
    tag = "rd" + uuid.uuid4().hex[:6]
    source_id = _make_source(tag)
    _store_article(source_id, tag, 0)  # seed one committed row for the read to see

    write_holds = threading.Event()
    read_done = threading.Event()
    release_write = threading.Event()
    read_elapsed: list[float] = []

    def writer() -> None:
        s = SessionLocal()
        try:
            s.add(
                Article(
                    url=f"https://{tag}.example/holder",
                    canonical_url=f"https://{tag}.example/holder",
                    source_id=source_id,
                    content="holder",
                    hash=f"{tag}-holder-{uuid.uuid4().hex}",
                    language="en",
                )
            )
            s.flush()  # <-- gate acquired here; transaction still open
            assert write_gate.held_by_current_thread()
            write_holds.set()
            release_write.wait(10)  # keep holding until the reader has proven it
            s.commit()
        finally:
            s.close()

    def reader() -> None:
        write_holds.wait(5)
        assert write_gate.stats()["held"]  # a write window IS open
        t0 = time.monotonic()
        with session_scope() as s:  # pure read; must NOT take the gate
            s.query(Article).filter(Article.url.like(f"https://{tag}.example/%")).count()
        read_elapsed.append(time.monotonic() - t0)
        read_done.set()

    tw = threading.Thread(target=writer, name="holder-writer")
    tr = threading.Thread(target=reader, name="reader")
    tw.start()
    tr.start()

    assert read_done.wait(8), "a read blocked behind an open write -- read concurrency broke"
    assert write_gate.stats()["held"], "writer should still hold the gate when the read returned"
    release_write.set()
    tw.join(10)
    tr.join(10)

    assert not tw.is_alive() and not tr.is_alive()
    assert read_elapsed and read_elapsed[0] < 5.0  # the read did not wait out the writer
    assert not write_gate.stats()["held"]  # gate freed after the writer committed
