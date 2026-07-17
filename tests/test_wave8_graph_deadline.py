"""Item 8 (field-test 2026-07-08): the 2-hop keyword graph is BOUNDED + never 503s.

``GET /api/insights/graph?level=keyword&term=…&hops=2`` fanned out ~6 associations()
calls over a 974K-keyword corpus and blew past the 60 s request deadline -> HTTP 503 ->
a broken frontend. The fix (src/analytics/queries.py + src/api/insights.py):

  * the corpus-total PMI denominator is computed ONCE and threaded into every call
    (byte-identical to the un-bounded path);
  * each term's article set is sampled to a DETERMINISTIC, time-spanning cap so a
    high-frequency seed can't drag the build past budget (no recency bias);
  * the hop-2 fan-out, total nodes and total edges are hard-capped;
  * a soft wall-clock budget returns the hop-1 graph if hop-2 would overrun;
  * every cap that truncates sets ``bounded`` and appends a VISIBLE disclosure to the
    ``caveat`` the frontend already renders — never a silent cut;
  * the hard deadline degrades to an honest actionable 200 payload (``on_timeout``),
    NEVER a 60 s -> 503.

Every test uses an ISOLATED in-memory engine (never SessionLocal); the endpoint tests
route the handler through ``app.dependency_overrides[get_db]`` and pop it in a
``finally`` (the ledger's endpoint-test rule). The pure helpers run anywhere; the
endpoint tests are gated on the crypto extra (``src.api.main``), so they run in CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import queries as q
from src.database.models import Article, Base, Keyword, KeywordMention, Source

try:
    from src.api.main import app  # noqa: F401

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001 - crypto extra/native ext absent in the bare sandbox
    _HAVE_MAIN = False


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _score_like_keys(obj) -> list[str]:
    """Walk the dict KEYS recursively for a forbidden score/ranking field (the ledger's
    no-score check: a caveat legitimately SAYS 'no score', so a naive repr() substring
    check would false-positive — inspect keys, not values). ``pmi``/``weight``/``size``/
    ``cooccur`` are named statistics, not composite scores, and are allowed."""
    found: list[str] = []

    def walk(d):
        if isinstance(d, dict):
            for k, v in d.items():
                kl = str(k).lower()
                if "score" in kl or "ranking" in kl or kl == "rank":
                    found.append(str(k))
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)

    walk(obj)
    return found


def _session():
    # StaticPool shares ONE in-memory connection across threads, so the endpoint (run off
    # the event loop in the threadpool) sees the seeded tables.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _kw(session, term: str) -> Keyword:
    k = Keyword(term=term, normalized_term=term.casefold(), language="en", is_entity=False)
    session.add(k)
    session.flush()
    return k


def _seed_dense(session, *, core: int = 14, sats: int = 6, block: int = 10):
    """Seed a DENSE, deterministic keyword graph and return the hub term.

    Two co-occurrence blocks (raw KeywordMention rows — precise control over density):
      * Block A (articles 0..block-1): the HUB + ``core`` relatives all co-occur → the hub
        has ``core`` hop-1 relatives, each in ``block`` articles.
      * Block B (articles block..2*block-1): the FIRST core relative + ``sats`` satellites
        co-occur (NO hub) → the satellites are genuine hop-2 nodes reachable only via that
        relative. The first relative therefore spans 2*block articles.

    ``article_count`` is set to the true distinct-article count so the associations n_b
    (the maintained counter) is realistic. Returns the hub term.
    """
    src = Source(name="S", domain="dense.test", country="fr")
    session.add(src)
    session.flush()

    hub = "alphahub"
    core_terms = [f"corerel{i:02d}" for i in range(core)]
    sat_terms = [f"satnode{i:02d}" for i in range(sats)]

    # Distinct-article tallies (for article_count) + the mention rows to insert.
    counts: dict[str, int] = {}
    rows: list[tuple[str, int]] = []  # (term, article_id)

    def _mention(term: str, aid: int):
        rows.append((term, aid))
        counts[term] = counts.get(term, 0) + 1

    obs = date(2024, 3, 1)
    # Block A: hub + all core, in articles 0..block-1
    for aid in range(block):
        _mention(hub, aid)
        for t in core_terms:
            _mention(t, aid)
    # Block B: first core relative + satellites, in articles block..2*block-1 (no hub)
    for aid in range(block, 2 * block):
        _mention(core_terms[0], aid)
        for t in sat_terms:
            _mention(t, aid)

    n_articles = 2 * block
    for aid in range(n_articles):
        session.add(
            Article(
                url=f"https://dense.test/{aid}",
                canonical_url=f"https://dense.test/{aid}",
                source_id=src.id,
                title=f"t{aid}",
                content="body",
                hash=f"{aid:064d}",
                language="en",
                published_at=datetime(2024, 3, 1, tzinfo=UTC),
                created_at=datetime.now(UTC),
            )
        )
    session.flush()

    kw_ids: dict[str, int] = {}
    for term in [hub, *core_terms, *sat_terms]:
        kw_ids[term] = _kw(session, term).id
    for term, aid in rows:
        session.add(
            KeywordMention(
                keyword_id=kw_ids[term], article_id=aid, count=1, observed_on=obs
            )
        )
    # Maintain the denormalised counters the associations() n_b path reads.
    for term, aid_count in counts.items():
        session.query(Keyword).filter_by(id=kw_ids[term]).update(
            {Keyword.article_count: aid_count, Keyword.mention_count: aid_count}
        )
    session.commit()
    return hub


def _seed_mentions(session, mention_map: dict[str, list[int]]):
    """Seed EXACTLY the given {term: [article_id, ...]} co-occurrence structure — one
    KeywordMention per (term, article) over the union of article ids, with each keyword's
    denormalised article_count set. Gives per-edge control the block-based _seed_dense
    (uniform weights) can't, so the strongest-edge selection + hop-2 reachability are
    testable non-vacuously."""
    src = Source(name="Sw", domain="weighted.test", country="fr")
    session.add(src)
    session.flush()
    obs = date(2024, 3, 1)
    all_aids = sorted({a for aids in mention_map.values() for a in aids})
    for aid in all_aids:
        session.add(
            Article(
                url=f"https://weighted.test/{aid}",
                canonical_url=f"https://weighted.test/{aid}",
                source_id=src.id, title=f"t{aid}", content="body",
                hash=f"{aid:064d}", language="en",
                published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
            )
        )
    session.flush()
    for term, aids in mention_map.items():
        kid = _kw(session, term).id
        for aid in aids:
            session.add(KeywordMention(keyword_id=kid, article_id=aid, count=1, observed_on=obs))
        session.query(Keyword).filter_by(id=kid).update(
            {Keyword.article_count: len(set(aids)), Keyword.mention_count: len(aids)}
        )
    session.commit()


def _seed_weighted(session):
    """A hub with DISTINCT-weight hop-1 relatives + one bridge relative to a satellite
    cluster (reachable in hop-2 only via the bridge). Returns "hub".

      * hub is in articles 0..29;
      * rel00..rel09 sit in articles 0..(19-i) -> hub co-occurrence 20,19,...,11 (distinct
        edge weights, so 'kept edges are the strongest' is non-vacuous);
      * bridge is in 20..29 (with hub) AND 30..39 (with the satellites, no hub) -> the
        satellites are reachable ONLY as hop-2 nodes via the bridge (so a soft budget that
        skips hop-2 provably drops them).
    """
    m: dict[str, list[int]] = {"hub": list(range(30))}
    for i in range(10):
        m[f"rel{i:02d}"] = list(range(20 - i))
    m["bridge"] = list(range(20, 30)) + list(range(30, 40))
    for j in range(5):
        m[f"sat{j:02d}"] = list(range(30, 40))
    _seed_mentions(session, m)
    return "hub"


# --------------------------------------------------------------------------- #
#  Bounding (pure — runs anywhere)
# --------------------------------------------------------------------------- #
def test_node_cap_is_enforced_and_disclosed():
    s = _session()
    hub = _seed_dense(s, core=14)  # 14 hop-1 relatives > any small node cap

    out = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=6, hop2_parents=3, article_cap=10_000, max_edges=10_000,
    )
    # The node cap is a HARD total-node cap (center counts) ...
    assert len(out["nodes"]) <= 6
    # ... and truncating it is DISCLOSED, never silent.
    assert out.get("bounded") is True
    assert "disclosure" in out
    assert out["disclosure"] in out["caveat"]  # surfaced in the field the frontend renders
    assert _score_like_keys(out) == []
    s.close()


def test_edge_cap_keeps_the_strongest_edges_and_discloses():
    s = _session()
    hub = _seed_weighted(s)  # DISTINCT hop-1 weights 20,19,...,11 (+ bridge 10)

    # Full hop-1 edge set (no edge cap, no hop-2) = the ground truth to compare against.
    full = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=0, article_cap=10_000, max_edges=10_000,
    )
    full_w = sorted((e.get("weight") or 0 for e in full["edges"]), reverse=True)
    assert len(set(full_w)) > 1, "fixture must yield VARYING weights or the next check is vacuous"

    capped = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=0, article_cap=10_000, max_edges=3,
    )
    assert len(capped["edges"]) <= 3
    assert capped.get("bounded") is True
    assert "disclosure" in capped and capped["disclosure"] in capped["caveat"]
    # The kept edges are the STRONGEST three — NOT insertion order, NOT the weakest.
    kept_w = sorted((e.get("weight") or 0 for e in capped["edges"]), reverse=True)
    assert kept_w == full_w[:3]
    assert min(kept_w) > full_w[3]  # every kept edge beats the strongest dropped one
    s.close()


def test_hop2_fanout_capped_on_dense_graph():
    s = _session()
    hub = _seed_dense(s, core=14, sats=6)

    # Generous node/edge caps: the ONLY bound is the hop-2 parent fan-out. With 0 parents
    # there is no hop-2 layer at all; with 2 there is. Either way the build is bounded and
    # the node/edge counts stay far below the naive full expansion.
    zero = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=0, article_cap=10_000, max_edges=10_000,
    )
    assert all(n.get("hop") != 2 for n in zero["nodes"])  # no hop-2 expansion at all

    two = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=2, article_cap=10_000, max_edges=10_000,
    )
    # More parents can only add nodes/edges, never remove them.
    assert len(two["nodes"]) >= len(zero["nodes"])
    # The distinct hop-2 PARENTS that actually spawned an edge is bounded by hop2_parents.
    hop2_parents_used = {e["a"] for e in two["edges"] if e["a"] != two["term"]}
    assert len(hop2_parents_used) <= 2
    s.close()


def test_soft_time_budget_returns_hop1_partial():
    s = _session()
    hub = _seed_weighted(s)  # satellites reachable ONLY as hop-2 nodes via the bridge

    # Ground truth: WITHOUT a budget, hop-2 genuinely reaches the satellites (so the
    # 'hop-2 skipped' assertion below is non-vacuous — there IS hop-2 to skip).
    full = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=11, article_cap=10_000, max_edges=10_000,
        time_budget_s=None,
    )
    assert any(n.get("hop") == 2 for n in full["nodes"]), "fixture must produce hop-2 nodes"

    # A zero soft budget stops the build AFTER hop-1: no hop-2 nodes, a strictly smaller
    # graph, and it is disclosed as bounded (never a 60s runaway).
    partial = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=11, article_cap=10_000, max_edges=10_000,
        time_budget_s=0.0,
    )
    assert all(n.get("hop") != 2 for n in partial["nodes"])  # hop-2 skipped by the budget
    assert len(partial["nodes"]) < len(full["nodes"])  # strictly fewer than the full build
    assert partial.get("bounded") is True
    assert partial["nodes"], "hop-1 partial must still carry the seed + its relatives"
    s.close()


def test_article_sample_is_bounded_deterministic_and_discloses_true_count():
    s = _session()
    hub = _seed_dense(s, core=6, block=10)  # hub is in 10 articles

    # associations() with a small article_cap samples the seed's articles ...
    a1 = q.associations(s, hub, group=True, min_cooccur=1, article_cap=3)
    assert a1["articles_bounded"] is True
    assert a1["articles_sampled"] == 3
    assert a1["n_articles_with_term"] == 10  # the TRUE population, not the sample size
    assert "sample" in a1["caveat"].lower()  # visible disclosure
    # ... deterministically (same sample every call — reproducible).
    a2 = q.associations(s, hub, group=True, min_cooccur=1, article_cap=3)
    assert a2["pairs"] == a1["pairs"]
    # The graph inherits the disclosure.
    g = q.layered_graph(
        s, level="keyword", term=hub, hops=2,
        limit_nodes=200, hop2_parents=4, article_cap=3, max_edges=10_000,
    )
    assert g.get("bounded") is True
    assert _score_like_keys(g) == []
    s.close()


def test_corpus_total_threaded_is_byte_identical():
    """Computing the PMI denominator ONCE and threading it must be byte-identical to
    associations() computing it itself (the graph's perf win costs no accuracy)."""
    s = _session()
    hub = _seed_dense(s, core=6)

    total = (
        s.query(func.count(func.distinct(KeywordMention.article_id))).scalar() or 0
    )
    without = q.associations(s, hub, group=True, min_cooccur=1)
    withtot = q.associations(s, hub, group=True, min_cooccur=1, corpus_total=total)
    assert withtot["corpus_articles"] == without["corpus_articles"]
    assert withtot["pairs"] == without["pairs"]  # identical PMI + co-occurrence
    s.close()


def test_normal_graph_is_not_flagged_bounded():
    """A small corpus under the DEFAULT caps must NOT be flagged bounded and must NOT
    append a disclosure — the disclosure only appears when a cap actually truncates."""
    s = _session()
    hub = _seed_dense(s, core=3, sats=2, block=4)  # tiny: well under every default cap

    out = q.layered_graph(s, level="keyword", term=hub, hops=2)
    assert not out.get("bounded")
    assert "disclosure" not in out
    assert out["caveat"] == "Association is not causation; PMI on small samples is noisy."
    assert _score_like_keys(out) == []
    s.close()


def test_associations_no_cap_omits_bounded_fields():
    """No ``article_cap`` -> no added fields (the /associations endpoint + every existing
    caller are byte-unchanged)."""
    s = _session()
    hub = _seed_dense(s, core=4)

    out = q.associations(s, hub, group=True, min_cooccur=1)
    assert "articles_bounded" not in out
    assert "articles_sampled" not in out
    s.close()


def test_associations_kids_lookup_is_chunked_and_byte_identical(monkeypatch):
    """Audit finding 2026-07-17: `kids` (the distinct co-occurring keyword ids
    derived from co_rows) fed an UNCHUNKED Keyword.id.in_(kids) /
    KeywordMention.keyword_id.in_(kids), with no bound of its own even though
    target_articles is capped -- a term co-occurring with more than SQLite's
    ~999-variable ceiling worth of DISTINCT keywords would crash. Forces
    chunking with a small q._IN_CHUNK (10 co-occurring keywords needing 2-id
    chunks) and asserts the result is BYTE-IDENTICAL to the unchunked default
    -- chunking must be a pure implementation detail, never change the answer."""
    monkeypatch.setattr(q, "_IN_CHUNK", 2, raising=True)
    s = _session()
    hub = _seed_dense(s, core=10, sats=3, block=5)  # 10 distinct co-occurring keywords

    chunked = q.associations(s, hub, group=False, min_cooccur=1)
    monkeypatch.setattr(q, "_IN_CHUNK", 900, raising=True)
    unchunked = q.associations(s, hub, group=False, min_cooccur=1)
    assert chunked["pairs"] == unchunked["pairs"]
    assert len(chunked["pairs"]) >= 10  # actually exercised multiple chunks, not a vacuous pass
    s.close()


def test_associations_with_no_explicit_cap_still_has_a_sqlite_safety_net(monkeypatch):
    """Audit finding 2026-07-17: GET /api/insights/associations (which "powers the
    mind-map") and the top_terms/trending cooccur enrichment both call associations()
    with NO article_cap at all -- so a term co-occurring in more articles than SQLite's
    historical ~999 bound-variable ceiling made the .in_(target_articles) query raise
    "OperationalError: too many SQL variables" instead of returning an honest, bounded
    result. The fix gives the query an effective safety-net cap (GRAPH_ARTICLE_CAP) even
    when the caller passes none, WITH a visible disclosure the moment it actually fires
    -- never a silent truncation."""
    monkeypatch.setattr(q, "GRAPH_ARTICLE_CAP", 3, raising=True)
    s = _session()
    hub = _seed_dense(s, core=6, block=10)  # hub is in 10 articles > the patched cap of 3

    out = q.associations(s, hub, group=True, min_cooccur=1)  # no article_cap passed
    assert out["articles_bounded"] is True
    assert out["articles_sampled"] == 3
    assert out["n_articles_with_term"] == 10  # the TRUE population, never hidden
    assert "sample" in out["caveat"].lower()  # visible disclosure, not silent
    s.close()


# --------------------------------------------------------------------------- #
#  The endpoint (CI — src.api.main needs the crypto extra)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_endpoint_returns_bounded_graph_never_503(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import insights as _ins
    from src.api.main import app as _app
    from src.database.session import get_db

    s = _session()
    hub = _seed_dense(s, core=14, block=10)  # hub in 10 articles

    # Force bounding on a small seeded corpus: patch the module cap so the hub's 10
    # articles are sampled (the endpoint doesn't expose the caps as query params).
    monkeypatch.setattr(q, "GRAPH_ARTICLE_CAP", 3, raising=True)
    # Disable the module-global TTL cache so this DB-specific result can't leak across
    # tests (the ledger's cross-pollution hazard) and we always recompute here.
    monkeypatch.setattr(_ins, "_CACHE_TTL_S", 0, raising=True)

    _app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(_app) as client:
            r = client.get(f"/api/insights/graph?level=keyword&term={hub}&hops=2")
            assert r.status_code == 200, r.text  # NEVER a 60s -> 503
            data = r.json()
            assert data["level"] == "keyword"
            assert data["nodes"], "a real bounded graph, not empty"
            assert data.get("bounded") is True
            assert "disclosure" in data and data["disclosure"]
            assert data["disclosure"] in data["caveat"]  # visible-by-default
            assert "method" in data and "caveat" in data
            assert _score_like_keys(data) == []
            # A degraded/timeout payload must never carry a truthy `locked` (that would
            # bounce the SPA to /unlock) — this is a normal bounded 200.
            assert not data.get("locked")
    finally:
        _app.dependency_overrides.pop(get_db, None)
    s.close()


@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_endpoint_degrades_to_200_message_on_hard_deadline(monkeypatch):
    """If the hard statement deadline still fires (a pathological corpus the bounds didn't
    tame), the endpoint returns an honest actionable 200 payload — NEVER a 503."""
    from fastapi.testclient import TestClient

    from src.api import insights as _ins
    from src.api.main import app as _app
    from src.database.maintenance import StatementTimeout
    from src.database.session import get_db

    s = _session()
    hub = _seed_dense(s, core=4)

    def _boom(*_a, **_k):
        raise StatementTimeout("statement exceeded the 60s deadline and was aborted")

    # The endpoint calls rm.layered_graph; make it raise the typed deadline error.
    monkeypatch.setattr(_ins.rm, "layered_graph", _boom, raising=True)
    monkeypatch.setattr(_ins, "_CACHE_TTL_S", 0, raising=True)  # no cross-test cache leak

    _app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(_app) as client:
            # days=3000 (<=3650) keeps a UNIQUE cache key so a prior test's cached success
            # can't short-circuit the timeout path we are exercising here.
            r = client.get(f"/api/insights/graph?level=keyword&term={hub}&hops=2&days=3000")
            assert r.status_code == 200, r.text  # degraded, not 503
            data = r.json()
            assert data.get("degraded") is True
            assert data["nodes"] == [] and data["edges"] == []
            assert "narrow the term" in data["caveat"].lower()
            assert not data.get("locked")  # must not redirect the SPA to /unlock
            assert _score_like_keys(data) == []
    finally:
        _app.dependency_overrides.pop(get_db, None)
    s.close()


@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_article_ids_path_degrades_as_article_level(monkeypatch):
    """The article-set radial-map path degrades with the ARTICLE shape (level='article' +
    n_articles), not the keyword-graph shape — a client branching on `level` isn't misled."""
    from fastapi.testclient import TestClient

    from src.api import insights as _ins
    from src.api.main import app as _app
    from src.database.maintenance import StatementTimeout
    from src.database.session import get_db

    s = _session()
    _seed_dense(s, core=3)

    def _boom(*_a, **_k):
        raise StatementTimeout("statement exceeded the 60s deadline and was aborted")

    monkeypatch.setattr(_ins.rm, "article_graph", _boom, raising=True)
    monkeypatch.setattr(_ins, "_CACHE_TTL_S", 0, raising=True)

    _app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(_app) as client:
            r = client.get("/api/insights/graph?article_ids=1,2,3")
            assert r.status_code == 200, r.text  # degraded, not 503
            data = r.json()
            assert data["level"] == "article"  # NOT "keyword"
            assert data.get("degraded") is True
            assert data["nodes"] == [] and data["edges"] == []
            assert data.get("n_articles") == 3
            assert "term" not in data  # the article map has no seed term
            assert not data.get("locked")
            assert _score_like_keys(data) == []
    finally:
        _app.dependency_overrides.pop(get_db, None)
    s.close()


@pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")
def test_endpoint_level_validation_unchanged(monkeypatch):
    """The bounding change must not regress the existing level/term validation."""
    from fastapi.testclient import TestClient

    from src.api.main import app as _app
    from src.database.session import get_db

    s = _session()
    _seed_dense(s, core=3)

    _app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(_app) as client:
            assert client.get("/api/insights/graph?level=nope").status_code == 400
            assert client.get("/api/insights/graph?level=keyword").status_code == 400
    finally:
        _app.dependency_overrides.pop(get_db, None)
    s.close()
