"""
P1.8 — collector-path write batching: fewer gate windows, ZERO loss.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-07-09 field pass measured 847,351 s of cumulative writer-gate wait
(~22% of all worker time) — three gate windows + fsyncs per stored article.
Batching shares ONE write transaction across several articles. The bar is the
maintainer's standing rule: ZERO LOSS —

  * in-batch dedup keys on the ACTUAL unique column (articles.hash — the
    email-import lesson);
  * a commit-time collision/lock ROLLS BACK AND REDOES the batch one article
    at a time (the proven ``ingest_emails`` fallback): a colliding article is
    counted a duplicate, its batch-mates are stored — never dropped;
  * a process death between batch commits loses nothing: staged-but-uncommitted
    articles are simply re-fetched next pass and dedup by content hash;
  * the gate is NEVER held across a fetch (fetch/extract stage outside it);
  * a real contention race (batched ingest vs a concurrent writer on the live
    SessionLocal) keeps exact counters.

Measured here too: the batched path takes FEWER gate acquisitions than the
legacy per-article path for the same feed.
"""

from __future__ import annotations

import threading
import uuid

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, ArticleLink, Base, KeywordMention, Source
from src.ingest import EthicalFetcher
from src.ingest.batch import ArticleBatch, collect_batch_size
from src.ingest.pipeline import IngestResult, ingest_source

# --------------------------------------------------------------------------- #
# Fake HTTP layer (the test_ingest conventions)
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.proxies = {}
        self._routes: dict[str, FakeResponse] = {}

    def route(self, url, **kwargs):
        self._routes[url] = FakeResponse(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        if url.endswith("/robots.txt"):
            return FakeResponse(text="User-agent: *\nAllow: /", content_type="text/plain", url=url)
        if url in self._routes:
            return self._routes[url]
        raise requests.ConnectionError(f"unrouted url {url}")


def _article_html(title, body_sentence, *, link=None):
    body = (body_sentence + " ") * 30  # well over the extractor's min length
    a = f'<a href="{link}">source material</a>' if link else ""
    return (
        f"<html><head><title>{title}</title>"
        f"<meta property='og:title' content='{title}'></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p>{a}</article></body></html>"
    )


def _feed_xml(domain, n):
    items = "".join(
        f"<item><title>i{i}</title><link>https://{domain}/news/{i}</link></item>"
        for i in range(n)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def _routed_source(sess, domain, n_items, *, distinct=True, link=None):
    """Route one source's feed + article pages on the fake session."""
    sess.route(
        f"https://{domain}/feed.xml",
        text=_feed_xml(domain, n_items),
        content_type="application/rss+xml",
    )
    for i in range(n_items):
        body = f"unique {domain} body {i if distinct else 0} datum" + uuid.uuid4().hex[:4] * 0
        body = f"unique {domain} body {i if distinct else 0} datum"
        sess.route(
            f"https://{domain}/news/{i}",
            text=_article_html(f"T{i if distinct else 0} {domain}", body, link=link),
        )


def _fetcher(sess):
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)


def _mem_db(domain):
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    src = Source(name=domain, domain=domain, rss_url=f"https://{domain}/feed.xml", language="en")
    s.add(src)
    s.commit()
    return s, src


# --------------------------------------------------------------------------- #
# The batched happy path
# --------------------------------------------------------------------------- #


def test_batched_ingest_stores_everything_with_keywords_and_links(monkeypatch):
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "3")
    domain = "batch-happy.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    _routed_source(sess, domain, 5, link="https://cited-origin.example/report")
    tally = ingest_source(db, source, fetcher=_fetcher(sess))
    assert tally["stored"] == 5
    assert tally["duplicate"] == 0
    assert tally.get("staged", 0) == 0  # nothing left buffered after the source
    assert db.query(Article).count() == 5
    # The batched path still indexes keywords AND links per article.
    assert db.query(KeywordMention).count() > 0
    assert db.query(ArticleLink).filter_by(link_type="external").count() == 5
    db.close()


def test_batch_disabled_env_is_the_legacy_per_article_path(monkeypatch):
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "0")
    assert collect_batch_size() == 0
    domain = "batch-off.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    _routed_source(sess, domain, 3)
    tally = ingest_source(db, source, fetcher=_fetcher(sess))
    assert tally["stored"] == 3
    assert db.query(Article).count() == 3
    db.close()


def test_in_batch_duplicate_hash_dedups_before_the_flush(monkeypatch):
    """Two feed items serving the SAME body share a content hash and must
    dedup inside the uncommitted batch (the actual-unique-column lesson)."""
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "8")
    domain = "batch-dup.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    _routed_source(sess, domain, 4, distinct=False)  # every page = same body
    tally = ingest_source(db, source, fetcher=_fetcher(sess))
    assert tally["stored"] == 1
    assert tally["duplicate"] == 3
    assert db.query(Article).count() == 1
    db.close()


def test_reingesting_a_flushed_feed_is_idempotent(monkeypatch):
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "2")
    domain = "batch-idem.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    _routed_source(sess, domain, 4)
    t1 = ingest_source(db, source, fetcher=_fetcher(sess))
    t2 = ingest_source(db, source, fetcher=_fetcher(sess))
    assert t1["stored"] == 4
    assert t2["stored"] == 0
    assert t2["duplicate"] == 4
    assert db.query(Article).count() == 4
    db.close()


# --------------------------------------------------------------------------- #
# Zero loss: collision on the Nth article, death between commits
# --------------------------------------------------------------------------- #


def test_flush_collision_redoes_per_article_and_drops_no_batch_mate(monkeypatch):
    """The negative-space skeptic: the Nth article collides (IntegrityError at
    batch commit) — its batch-mates MUST still be stored, the collider counted
    a duplicate, nothing raised."""
    domain = "batch-collide.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    _routed_source(sess, domain, 3)

    # A concurrent writer stored article 1's content between the staging
    # dedup-check and the flush: blind the flush-time recheck so the batch
    # commit genuinely collides on UNIQUE articles.hash.
    from src.ingest.pipeline import store_fetched

    batch = ArticleBatch(db, source, size=10)
    fetcher = _fetcher(sess)
    for i in range(3):
        fetched = fetcher.fetch(f"https://{domain}/news/{i}")
        out = store_fetched(db, source, fetched, batch=batch)
        assert out.result is IngestResult.STAGED
    # Insert the conflicting row via a "concurrent worker" (same store).
    victim = batch._pending[1]
    db.add(Article(
        url="https://elsewhere.example/copy", canonical_url="https://elsewhere.example/copy",
        source_id=source.id, title="copy", content=victim.text, hash=victim.content_hash,
    ))
    db.commit()
    # Blind the flush-time recheck (simulating the insert landing AFTER it).
    monkeypatch.setattr("src.ingest.pipeline._exists", lambda *a, **k: False)
    batch.flush()
    monkeypatch.undo()
    assert batch.tally["stored"] == 2  # the batch-mates survived
    assert batch.tally["duplicate"] == 1  # the collider, honestly counted
    assert batch.tally["errors"] == 0
    # Every distinct body is stored exactly once: the two batch-mates + the
    # pre-inserted copy (the collider dedups against it — never a second row).
    assert db.query(Article).count() == 3
    db.close()


def test_death_between_batch_commits_loses_nothing_on_reingest(monkeypatch):
    """A process death with a half-flushed source: the staged-but-uncommitted
    articles are simply re-fetched next pass (content-hash dedup keeps the
    committed half single)."""
    domain = "batch-death.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    _routed_source(sess, domain, 4)
    from src.ingest.pipeline import store_fetched

    batch = ArticleBatch(db, source, size=10)
    fetcher = _fetcher(sess)
    for i in range(4):
        store_fetched(db, source, fetcher.fetch(f"https://{domain}/news/{i}"), batch=batch)
    # Flush only half: commit 2, then "die" with 2 still staged.
    half = batch._pending[2:]
    batch._pending = batch._pending[:2]
    batch.flush()
    assert batch.tally["stored"] == 2
    del half  # the process is gone; staged entries evaporate
    db.rollback()

    # Next pass re-ingests the same feed through the normal batched path.
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "8")
    tally = ingest_source(db, source, fetcher=_fetcher(sess))
    assert tally["stored"] == 2  # exactly the lost half
    assert tally["duplicate"] == 2  # the committed half dedups
    assert db.query(Article).count() == 4
    db.close()


# --------------------------------------------------------------------------- #
# The gate: fewer acquisitions, and a real contention race with exact counters
# --------------------------------------------------------------------------- #


def _gate_grants() -> int:
    from src.database.writer import write_gate

    return write_gate.stats()["grants"]


@pytest.mark.usefixtures()
def test_batched_path_takes_fewer_gate_windows_than_legacy(monkeypatch):
    """The P1.8 point, measured: same feed, gate acquisitions counted."""
    from src.database.session import init_db, session_scope

    init_db()
    counts = {}
    for label, batch_env, dom in (
        ("legacy", "0", f"gw-legacy-{uuid.uuid4().hex[:6]}.example"),
        ("batched", "8", f"gw-batched-{uuid.uuid4().hex[:6]}.example"),
    ):
        monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", batch_env)
        sess = FakeSession()
        _routed_source(sess, dom, 6)
        with session_scope() as s:
            src = Source(name=dom, domain=dom, rss_url=f"https://{dom}/feed.xml",
                         language="en", enabled=False)
            s.add(src)
            s.flush()
            before = _gate_grants()
            tally = ingest_source(s, src, fetcher=_fetcher(sess))
            counts[label] = _gate_grants() - before
            assert tally["stored"] == 6
    assert counts["batched"] < counts["legacy"], counts


def test_contention_race_batched_ingest_vs_concurrent_writer_exact_counters(monkeypatch):
    """The zero-loss bar under real concurrency: a batched feed ingest races a
    writer hammering the same store — every row lands, exact counts, no lock
    errors escape."""
    from src.database.session import init_db, session_scope

    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "4")
    init_db()
    tag = uuid.uuid4().hex[:8]
    dom = f"race-{tag}.example"
    n_feed, n_other = 8, 25
    sess = FakeSession()
    _routed_source(sess, dom, n_feed)
    with session_scope() as s:
        src = Source(name=dom, domain=dom, rss_url=f"https://{dom}/feed.xml",
                     language="en", enabled=False)
        other = Source(name=f"other-{tag}", domain=f"other-{tag}.example",
                       language="en", enabled=False)
        s.add_all([src, other])
        s.flush()
        src_id, other_id = src.id, other.id

    errors: list[Exception] = []
    tally_holder: dict = {}

    def _ingest():
        try:
            with session_scope() as s:
                src2 = s.get(Source, src_id)
                tally_holder.update(ingest_source(s, src2, fetcher=_fetcher(sess)))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def _hammer():
        try:
            for i in range(n_other):
                with session_scope() as s:
                    s.add(Article(
                        url=f"https://other-{tag}.example/{i}",
                        canonical_url=f"https://other-{tag}.example/{i}",
                        source_id=other_id, title=f"o{i}",
                        content=f"other body {tag} {i}", hash=f"race-{tag}-{i}",
                    ))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_ingest), threading.Thread(target=_hammer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert tally_holder["stored"] == n_feed
    with session_scope() as s:
        assert s.query(Article).filter_by(source_id=src_id).count() == n_feed
        assert s.query(Article).filter_by(source_id=other_id).count() == n_other


# --------------------------------------------------------------------------- #
# The gate is NEVER held across a network fetch (the reproduced hazard, pinned)
# --------------------------------------------------------------------------- #


class _GateProbeSession(FakeSession):
    """Records whether the write gate was held at every article GET."""

    def __init__(self):
        super().__init__()
        self.held: list[bool] = []

    def get(self, url, **kw):
        if "/news/" in url:
            from src.database.writer import write_gate

            self.held.append(write_gate.stats()["held"])
        return super().get(url, **kw)


def test_gate_is_never_held_during_an_article_fetch(monkeypatch):
    """Reproduced before the fix: feed bookkeeping written BEFORE the article
    loop left the session dirty, the loop's first dedup SELECT AUTOFLUSHED it,
    and the write gate was then held ACROSS the article fetch (legacy: the
    first fetch; batched: the WHOLE feed — the field log's 438 s max single
    write-wait signature). Pinned on the REAL gate-wired SessionLocal, both
    paths, first-contact feed (the worst case: the validators row is new)."""
    from src.database.session import init_db, session_scope

    init_db()
    for env in ("0", "8"):  # legacy AND batched
        monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", env)
        dom = f"gatehold{env}-{uuid.uuid4().hex[:6]}.example"
        sess = _GateProbeSession()
        _routed_source(sess, dom, 4)
        with session_scope() as s:
            src = Source(name=dom, domain=dom, rss_url=f"https://{dom}/feed.xml",
                         language="en", enabled=False)
            s.add(src)
            s.commit()
            t = ingest_source(s, src, fetcher=_fetcher(sess))
            assert t["stored"] == 4
        assert sess.held == [False, False, False, False], (env, sess.held)


def test_sequential_next_source_never_inherits_a_dirty_gate(monkeypatch):
    """The sequential pass shares ONE session across sources: source A's feed
    bookkeeping must be COMMITTED before ingest_source returns, or source B's
    first dedup query autoflushes it and holds the gate across B's fetches."""
    from src.database.models import FeedFetchState
    from src.database.session import init_db, session_scope

    init_db()
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "8")
    doms = [f"seq{i}-{uuid.uuid4().hex[:6]}.example" for i in range(2)]
    sess = _GateProbeSession()
    for d in doms:
        _routed_source(sess, d, 3)
    with session_scope() as s:
        srcs = []
        for d in doms:
            src = Source(name=d, domain=d, rss_url=f"https://{d}/feed.xml",
                         language="en", enabled=False)
            s.add(src)
            srcs.append(src)
        s.commit()
        for src in srcs:
            ingest_source(s, src, fetcher=_fetcher(sess))
        # No fetch — of EITHER source — ever ran under a held gate.
        assert sess.held == [False] * 6, sess.held
        # And the bookkeeping still landed (deferred, never dropped).
        for src in srcs:
            state = s.get(FeedFetchState, src.id)
            assert state is not None and state.last_status == 200


# --------------------------------------------------------------------------- #
# Crawl path parity
# --------------------------------------------------------------------------- #


def test_crawl_path_batches_and_tallies_exactly(monkeypatch):
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "3")
    from src.ingest.crawl import CrawlConfig, crawl_source

    domain = "batch-crawl.example"
    db, source = _mem_db(domain)
    sess = FakeSession()
    links = "".join(f'<a href="https://{domain}/p/{i}">art {i}</a>' for i in range(4))
    sess.route(f"https://{domain}", text=f"<html><body>{links}</body></html>")
    for i in range(4):
        sess.route(
            f"https://{domain}/p/{i}",
            text=_article_html(f"C{i}", f"crawl body {domain} {i} datum"),
        )
    report = crawl_source(db, source, fetcher=_fetcher(sess),
                          config=CrawlConfig(max_depth=1, max_pages=10))
    assert report.tally["stored"] == 4
    assert db.query(Article).count() == 4
    db.close()
