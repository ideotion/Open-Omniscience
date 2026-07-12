"""
S2.1 — the A9 write-gate-hold riders, REPRODUCER-FIRST (2026-07-12).

Session A investigated F10/F11/F13/F14 and DECLINED all three lines
(ledger "SESSION A PROGRESS"): F14 non-reproducible (``SessionLocal`` is
``autoflush=False``), F10/F11 backup-path risk > gain, F13 split-risk vs
GIL-marginal. This session's S2 brief re-opens them REPRODUCER-FIRST: build the
empirical gate-hold probe for each claim and ship a change ONLY where a
reproducer proves a real hold worth its risk. The probe idiom is the
``write_gate.stats()["held"]`` pattern from ``tests/test_collect_batching.py``.

Outcome (recorded in the ledger 2026-07-12): all four DECLINED, each with its
reproducer/analysis as evidence —

  * **F14 — REFUTED by test.** ``SessionLocal`` is ``autoflush=False``, so a read
    query never flushes a dirty session and therefore never acquires the write
    gate; the markets ``import_due_feeds`` freshness query cannot hold the gate
    across a feed fetch. (``run_rule`` also commits its writes, so the session is
    not even dirty when ``import_due_feeds`` runs — a second, independent
    refutation.) The test below asserts the gate stays UNHELD across the exact
    dirty-session → read-query → fetch shape the claim describes.
  * **F13 — REAL hold, DECLINED (GIL-marginal + split-risk).** The batched
    collector flush holds the gate across per-article keyword EXTRACTION, not
    just the write (documented + pinned below). The fix — splitting
    ``index_article`` into extract-outside / persist-inside — is high-risk (the
    hottest, most correctness-critical function: idempotency, exact counters,
    when/where/who, sentiment) and GIL-bounded-marginal in throughput: extraction
    is GIL-serialised regardless of the gate, so the only recoverable overlap is
    the amortised fsync window (batching already collapses ~8 extractions onto ONE
    commit, so writes are the small part of the window). Session A's judgment
    stands, now with a reproducer. The test PINS the current property (gate held
    across extraction); if a future session splits it, update this test
    consciously.
  * **F10 — REAL, DECLINED (bounded / best-effort / self-resolving).**
    ``_drain_wal`` checks out a pool connection under the gate (inverted vs
    workers' connection→gate), but via ``engine.connect()`` bounded by
    ``pool_timeout`` and best-effort: a checkpoint failure is caught and the WAL
    rides as a backup member. Never a true deadlock. Backup-path (ZETA), so left
    untouched. Evidence: the code trace + the ``gate_held_s`` telemetry.
  * **F11 — REAL, DECLINED (immaterial + correctness-constrained).**
    ``_corpus_facts`` (table COUNT(*) + the article-hash commitment) runs inside
    the backup's freeze() gate window, but (a) it MUST — the commitment must match
    the streamed at-rest bytes for tamper-evidence — and (b) it is a rounding
    error beside the corpus BYTE STREAM, which is itself emitted under the same
    gate (minutes at 100 GB vs seconds for the facts). Disclosed via
    ``gate_held_s``. Backup-path, so left untouched.

Only the two SAFE (non-backup) reproducers are pinned here (F14, F13); F10/F11
are backup-path and are DECLINED from a code trace, not an invasive test — the
brief's rule is to touch ``stream_backup.py`` only for a demonstrated hold worth
its risk, and neither is.
"""

from __future__ import annotations

import uuid

import requests
from sqlalchemy import func

# --------------------------------------------------------------------------- #
# Minimal fake HTTP layer (mirrors tests/test_collect_batching.py)
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url

    def close(self):
        pass


class _GateProbeSession:
    """Records whether the write gate was held at every article-page GET."""

    def __init__(self):
        self.headers = {}
        self.proxies = {}
        self._routes: dict[str, _FakeResponse] = {}
        self.held_at_fetch: list[bool] = []

    def route(self, url, **kwargs):
        self._routes[url] = _FakeResponse(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _FakeResponse(text="User-agent: *\nAllow: /", content_type="text/plain", url=url)
        if "/news/" in url:
            from src.database.writer import write_gate

            self.held_at_fetch.append(write_gate.stats()["held"])
        if url in self._routes:
            return self._routes[url]
        raise requests.ConnectionError(f"unrouted url {url}")


def _article_html(title, body_sentence):
    body = (body_sentence + " ") * 30
    return (
        f"<html><head><title>{title}</title>"
        f"<meta property='og:title' content='{title}'></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


def _feed_xml(domain, n):
    items = "".join(
        f"<item><title>i{i}</title><link>https://{domain}/news/{i}</link></item>"
        for i in range(n)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def _routed_source(sess, domain, n_items):
    sess.route(
        f"https://{domain}/feed.xml",
        text=_feed_xml(domain, n_items),
        content_type="application/rss+xml",
    )
    for i in range(n_items):
        sess.route(
            f"https://{domain}/news/{i}",
            text=_article_html(f"T{i} {domain}", f"unique {domain} body {i} datum"),
        )


def _fetcher(sess):
    from src.ingest import EthicalFetcher

    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=sess)


# --------------------------------------------------------------------------- #
# F14 — REFUTED: autoflush=False means a read never takes the write gate
# --------------------------------------------------------------------------- #


def test_f14_read_query_on_a_dirty_session_never_acquires_the_write_gate():
    """F14's claimed mechanism: run_rule leaves the session dirty → the markets
    ``import_due_feeds`` freshness query autoflushes → the write gate is held
    across the following feed fetch. This CANNOT fire because ``SessionLocal`` is
    ``autoflush=False``: a read query does not flush a dirty session, so the gate
    is never acquired by the query. Pinned on the REAL gate-wired SessionLocal
    with the exact shape (a pending write, then the CommodityPrice max-date
    freshness read ``import_due_feeds`` issues)."""
    from src.database.models import CommodityPrice, Source
    from src.database.session import init_db, session_scope
    from src.database.writer import write_gate

    init_db()
    with session_scope() as s:
        # run_rule "left the session dirty": a pending, un-flushed write.
        s.add(Source(name=f"dirty-{uuid.uuid4().hex[:6]}",
                     domain=f"dirty-{uuid.uuid4().hex[:6]}.example",
                     language="en", enabled=False))
        assert write_gate.stats()["held"] is False  # nothing flushed yet
        # The exact freshness read import_due_feeds runs per feed. With
        # autoflush=False this does NOT flush the pending Source, so no gate.
        _ = (
            s.query(func.max(CommodityPrice.observed_on))
            .filter(CommodityPrice.symbol == "does-not-exist")
            .scalar()
        )
        assert write_gate.stats()["held"] is False, (
            "a read query autoflushed the dirty session and took the write gate — "
            "F14 would be live; SessionLocal must stay autoflush=False"
        )


def test_f14_sessionlocal_is_autoflush_off_the_property_that_refutes_the_claim():
    """The single source-of-truth guard: the property F14 depends on being FALSE."""
    from src.database.session import SessionLocal

    assert SessionLocal.kw.get("autoflush") is False


# --------------------------------------------------------------------------- #
# F13 — REAL hold, DECLINED: the batched flush holds the gate across extraction
# --------------------------------------------------------------------------- #


def test_f13_batched_flush_holds_the_gate_across_keyword_extraction(monkeypatch):
    """F13 (DECLINED, GIL-marginal + split-risk): the batched collector flush
    holds the single-writer gate ACROSS per-article keyword EXTRACTION, not just
    the write. Proven by probing ``write_gate.stats()["held"]`` from inside the
    extractor: every extraction during a batched flush runs with the gate HELD.

    This DOCUMENTS the property Session A judged not worth splitting (extraction
    is GIL-serialised, so moving it out of the gate does not raise collector
    throughput beyond the amortised-fsync overlap; the split would refactor the
    hottest correctness-critical function). If a future session DOES split
    extraction out of the gate window, this assertion will flip — update it
    consciously and record the reversal in the ledger."""
    from src.analytics import extract as extract_mod
    from src.database.models import Article
    from src.database.session import init_db, session_scope
    from src.database.models import Source
    from src.database.writer import write_gate
    from src.ingest.pipeline import ingest_source

    init_db()
    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "4")

    real_get = extract_mod.get_extractor
    held_during_extract: list[bool] = []

    class _ProbeExtractor:
        def __init__(self, inner):
            self._inner = inner
            self.name = inner.name

        def extract(self, *a, **k):
            held_during_extract.append(write_gate.stats()["held"])
            return self._inner.extract(*a, **k)

    monkeypatch.setattr(extract_mod, "get_extractor", lambda name: _ProbeExtractor(real_get(name)))

    dom = f"f13-{uuid.uuid4().hex[:6]}.example"
    sess = _GateProbeSession()
    _routed_source(sess, dom, 4)
    with session_scope() as s:
        src = Source(name=dom, domain=dom, rss_url=f"https://{dom}/feed.xml",
                     language="en", enabled=False)
        s.add(src)
        s.commit()
        src_id = src.id
        tally = ingest_source(s, src, fetcher=_fetcher(sess))
        assert tally["stored"] == 4

    # The extractor ran once per stored article, and EVERY run was under the gate
    # (the batched flush's window spans the extraction — the F13 hold).
    assert held_during_extract, "extraction never ran"
    assert all(held_during_extract), held_during_extract

    # And, for contrast, the article FETCHES ran with the gate UNHELD (P1.8's
    # own invariant: fetch/extract-of-links happens outside the gate). This keeps
    # the F13 finding scoped to the in-flush keyword extraction, not the fetch.
    assert sess.held_at_fetch == [False, False, False, False], sess.held_at_fetch
    from src.database.session import session_scope as _ss
    with _ss() as s2:
        assert s2.query(Article).filter_by(source_id=src_id).count() == 4
