"""
Coordination detection — collapsing a near-duplicate network into single "actors".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The §6 keystone, made measurable. Trending / prominence / "what's covered" all *count
outlets*, so a well-resourced actor who spins up many outlets converts capital into
apparent consensus. The fix is not to *score* sources but to change the **unit**: treat
coordinated / near-duplicate outlets as a single **actor**.

This module builds that actor graph from **structural facts only** (FUTURE_DEVELOPMENTS
§6 "(B) authenticity/structure signals"):

  * **near-duplicate co-publication** — the *same* story (shared word-shingles, via
    :mod:`near_dup`) appearing across several sources;
  * **lockstep timing** — those near-identical pieces published within a tight window;
  * **shared infrastructure** — pieces served from the same host fingerprint.

It is **high-precision by design** (biased toward *under*-merging — false merges hurt
the innocent, §6): an actor edge needs near-duplicate text *and* (when timestamps are
known) a tight window. It outputs a *proposal with its evidence*; it **never** decides
that coordination is collusion, and it never scores a source. The human disposes — see
the user-guided collapse in the source-integrity layer.

Pure: no DB, no network, fully unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.signals.near_dup import near_duplicate_clusters

_CAVEAT = (
    "Coordination here means a *structural* pattern — the same text across several "
    "sources, close in time and/or sharing infrastructure. It is NOT proof of collusion, "
    "and it never judges the content true or false. Legitimate causes exist: a shared "
    "wire agency, a syndication deal, or independent outlets quoting one primary source. "
    "Detection is high-precision (biased to under-merge); always read the evidence and "
    "treat a proposed actor as a question, not a verdict."
)


@dataclass
class CoordinationEvent:
    """One near-duplicate story co-published by several sources."""

    representative: str                 # a member document id
    sources: list[str]
    documents: list[str]
    span_hours: float | None            # max-min publish time across members (None if unknown)
    avg_similarity: float

    def to_dict(self) -> dict:
        return {
            "representative": self.representative,
            "sources": self.sources,
            "documents": self.documents,
            "span_hours": None if self.span_hours is None else round(self.span_hours, 2),
            "avg_similarity": round(self.avg_similarity, 4),
        }


@dataclass
class Actor:
    """A cluster of sources that repeatedly co-publish near-duplicate content."""

    sources: list[str]
    shared_stories: int                 # number of coordination events spanning these sources
    documents: list[str]
    shared_hosts: list[str] = field(default_factory=list)
    median_span_hours: float | None = None
    events: list[CoordinationEvent] = field(default_factory=list)
    # A stable identity for this actor (hash of member set), attached by the corpus
    # adapter so a user's collapse decision can be persisted and re-applied.
    signature: str | None = None

    def to_dict(self) -> dict:
        return {
            "sources": self.sources,
            "size": len(self.sources),
            "shared_stories": self.shared_stories,
            "documents": self.documents,
            "shared_hosts": self.shared_hosts,
            "median_span_hours": None if self.median_span_hours is None else round(self.median_span_hours, 2),
            "events": [e.to_dict() for e in self.events],
            "signature": self.signature,
        }


@dataclass
class CoordinationResult:
    method: str
    n_documents: int
    n_sources: int
    window_hours: float
    threshold: float
    actors: list[Actor] = field(default_factory=list)
    caveat: str = _CAVEAT

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "n_documents": self.n_documents,
            "n_sources": self.n_sources,
            "window_hours": self.window_hours,
            "threshold": self.threshold,
            "actors": [a.to_dict() for a in self.actors],
            "caveat": self.caveat,
        }


def _median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def detect_coordination(
    documents: list[dict],
    *,
    threshold: float = 0.7,
    window_hours: float = 48.0,
    require_timing: bool = True,
    min_shared_stories: int = 1,
    **near_dup_kwargs,
) -> CoordinationResult:
    """Find coordinated actors among ``documents``.

    Each document is a dict: ``{id, source, text, published_at?(datetime), host?}``.
    A *coordination event* is a near-duplicate cluster spanning ≥2 distinct sources
    (and, when ``require_timing`` and timestamps exist, within ``window_hours``). Sources
    that share ≥ ``min_shared_stories`` such events are collapsed into one actor.
    """
    by_id = {d["id"]: d for d in documents}
    texts = {d["id"]: d.get("text", "") for d in documents}
    nd = near_duplicate_clusters(texts, threshold=threshold, **near_dup_kwargs)

    events: list[CoordinationEvent] = []
    for cluster in nd.clusters:
        srcs, times, docs = [], [], []
        for doc_id in cluster.members:
            d = by_id[doc_id]
            docs.append(doc_id)
            if d.get("source"):
                srcs.append(d["source"])
            t = d.get("published_at")
            if isinstance(t, datetime):
                times.append(t)
        distinct = sorted(set(srcs))
        if len(distinct) < 2:
            continue  # a single source repeating itself is not co-publication
        span = None
        if len(times) >= 2:
            span = (max(times) - min(times)).total_seconds() / 3600.0
        if require_timing and span is not None and span > window_hours:
            continue  # near-dup but spread out — not lockstep
        events.append(CoordinationEvent(
            representative=cluster.representative, sources=distinct, documents=docs,
            span_hours=span, avg_similarity=cluster.avg_similarity,
        ))

    # Build the source graph: an edge between every pair of sources sharing an event.
    pair_counts: dict[tuple[str, str], int] = {}
    source_events: dict[str, list[CoordinationEvent]] = {}
    for ev in events:
        for s in ev.sources:
            source_events.setdefault(s, []).append(ev)
        for i in range(len(ev.sources)):
            for j in range(i + 1, len(ev.sources)):
                key = tuple(sorted((ev.sources[i], ev.sources[j])))
                pair_counts[key] = pair_counts.get(key, 0) + 1

    edges = {pair for pair, c in pair_counts.items() if c >= min_shared_stories}
    nodes = {s for pair in edges for s in pair}

    # Union-find over confirmed edges → actor clusters.
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    comps: dict[str, set[str]] = {}
    for n in nodes:
        comps.setdefault(find(n), set()).add(n)

    actors: list[Actor] = []
    for comp in comps.values():
        comp_sources = sorted(comp)
        comp_events = [ev for ev in events if any(s in comp for s in ev.sources)]
        docs = sorted({d for ev in comp_events for d in ev.documents})
        hosts = sorted({by_id[d].get("host") for d in docs if by_id[d].get("host")})
        actors.append(Actor(
            sources=comp_sources,
            shared_stories=len(comp_events),
            documents=docs,
            shared_hosts=hosts,
            median_span_hours=_median([ev.span_hours for ev in comp_events]),
            events=comp_events,
        ))
    actors.sort(key=lambda a: (-len(a.sources), -a.shared_stories))

    return CoordinationResult(
        method=(f"near-duplicate co-publication (Jaccard ≥ {threshold}) across ≥2 sources"
                + (f" within {window_hours}h" if require_timing else "")
                + f"; sources sharing ≥ {min_shared_stories} story collapsed (union-find)"),
        n_documents=len(documents), n_sources=len({d.get('source') for d in documents if d.get('source')}),
        window_hours=window_hours, threshold=threshold, actors=actors,
    )
