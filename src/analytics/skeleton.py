"""
Keyword fingerprints — the same-skeleton echo tier (planning §3).

Two articles can share a KEYWORD SKELETON (the same set — and, in a template, the same ORDER — of
entities/terms) without being whole-text near-duplicates: a shared press-release template, a
wire-service rewrite, or a genre convention. §3 detects that tier. The near-dup machinery is ideal
to REUSE: ``minhash_signature(set[int])`` is already token-agnostic, so keyword-ids drop straight
in (bypassing text shingles); ``jaccard_estimate`` + ``_connected_components`` cluster them; the
``actor_signature`` sorted-set-hash template gives a stable fingerprint.

This module ships §3's PURE core (no DB, no network): the fingerprint, the MinHash skeleton
clustering, an ORDERED-skeleton comparator (LCS-ratio over ``first_offset``-sorted keyword-id
sequences — order distinguishes a template from a coincidental shared vocabulary), and the
``skeleton_echo`` producer ASSEMBLY given precomputed clusters. Persisting the fingerprint (schema
+ migration + corpus-scale backfill) and wiring the producer into ``refresh_briefing`` on the live
encrypted corpus are OPERATOR-GATED; per §9 this tier lands AFTER the §8 triage batch cleans the
worst junk (a cleaner keyword layer sharpens skeleton matching).

Honesty by construction: a shared skeleton is a SHAPE to investigate, never proof of coordination
(the innocent explanation rides every card); independence is measured by DISTINCT SOURCES, not
article count; a single-source cluster is flagged; a whole-text near-dup is echo_chamber's job, not
this; "absence of a flag is not absence of coordination". No composite score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from src.briefing.card import Card
from src.signals.near_dup import (
    _connected_components,
    jaccard_estimate,
    minhash_signature,
)

# Fire gate: a skeleton echo needs at least this many DISTINCT sources (mirrors echo_chamber).
DEFAULT_MIN_SOURCES = 3


def skeleton_fingerprint(keyword_ids: set[int]) -> str:
    """A stable fingerprint of a keyword SKELETON = blake2b over the sorted keyword-id set
    (mirroring ``actor_signature``'s sorted-set hash). Order-independent by design (the set is
    sorted); the ordered dimension is measured separately by ``ordered_skeleton_similarity``.
    An empty skeleton yields a stable sentinel fingerprint."""
    basis = "|".join(str(i) for i in sorted(keyword_ids)).encode("utf-8")
    return hashlib.blake2b(basis, digest_size=8).hexdigest()


def skeleton_signature(keyword_ids: set[int], *, num_perm: int = 128) -> list[int]:
    """The MinHash signature of a keyword-id skeleton — the thin wrapper that feeds the id set
    STRAIGHT into ``minhash_signature`` (bypassing text shingles). Token-agnostic by construction."""
    return minhash_signature(keyword_ids, num_perm=num_perm)


def skeleton_clusters(
    docs: dict[str, set[int]], *, threshold: float = 0.7, num_perm: int = 128
) -> list[set[str]]:
    """Cluster documents by MinHash-estimated Jaccard of their keyword-id SKELETONS. ``docs`` maps
    a doc id → its keyword-id set. Edges at estimated Jaccard ``>= threshold``; union-find via the
    shared ``_connected_components`` (returns only the multi-doc clusters; singletons are dropped).
    Raises ``ValueError`` on a threshold outside [0, 1]."""
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    ids = list(docs)
    sigs = {d: minhash_signature(docs[d], num_perm=num_perm) for d in ids}
    nodes = set(ids)
    edges: set[tuple[str, str]] = set()
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            # An empty skeleton must never cluster: its sentinel signature matches nothing, and we
            # also guard explicitly so a degenerate all-empty corpus can't form a phantom cluster.
            if not docs[ids[i]] or not docs[ids[j]]:
                continue
            if jaccard_estimate(sigs[ids[i]], sigs[ids[j]]) >= threshold:
                edges.add((ids[i], ids[j]))
    return _connected_components(nodes, edges)


def _lcs_len(a: list[int], b: list[int]) -> int:
    """Longest common SUBSEQUENCE length (classic DP, O(len(a)·len(b)))."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            cur[j] = prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


def ordered_skeleton_similarity(seq_a: list[int], seq_b: list[int]) -> float:
    """ORDER-AWARE skeleton similarity = LCS(seq_a, seq_b) / max(len). Each sequence is the
    article's keyword ids sorted by ``first_offset`` (the order they appear in the text). Two
    articles with the SAME keywords in the SAME order (a template) score ~1.0; the same keywords
    SHUFFLED score lower — which is exactly what separates a copied skeleton from a coincidental
    shared vocabulary. Returns 0.0 for an empty sequence pair."""
    m = max(len(seq_a), len(seq_b))
    if m == 0:
        return 0.0
    return _lcs_len(seq_a, seq_b) / m


def build_skeleton_echo_card(
    *,
    doc_ids: list[str],
    source_of: Mapping[str, str | None],
    article_ids: list[int],
    keyword_ids: set[int],
    is_text_neardup: bool,
    min_sources: int = DEFAULT_MIN_SOURCES,
) -> Card | None:
    """Assemble a ``skeleton_echo`` briefing Card from a PRECOMPUTED skeleton cluster. Fires only
    when the cluster spans ``>= min_sources`` DISTINCT sources AND is NOT a whole-text near-dup
    (that is echo_chamber's job); otherwise returns ``None``. Carries method + caveat (the innocent
    explanation) + n + the EXACT ``article_ids``; a single-source cluster is flagged. No score.

    Pure given its inputs — the DB reads (the cluster, its sources, whether it is a text near-dup)
    are the operator-gated seam."""
    if is_text_neardup:
        return None  # a whole-text near-dup is echo_chamber's signal, not a skeleton echo.
    distinct = len({source_of.get(d) for d in doc_ids if source_of.get(d)})
    if distinct < min_sources:
        return None
    fp = skeleton_fingerprint(keyword_ids)
    return Card(
        type="skeleton_echo",
        title="Same keyword skeleton across sources",
        summary=(
            f"{distinct} distinct sources share the same keyword skeleton without being "
            "whole-text copies — a shape to investigate."
        ),
        bucket="overtold",
        method=(
            f"Same keyword SKELETON (shared entity/term set) across {distinct} distinct sources; "
            "the cluster is NOT a whole-text near-duplicate. Independence measured by distinct "
            "sources, never article count."
        ),
        caveat=(
            "A shared template, wire-service rewrite, or genre convention can produce the same "
            "skeleton innocently — a shape to investigate, never proof of coordination. Absence "
            "of a flag is not absence of coordination."
        ),
        signal={
            "metric": "distinct_sources",
            "value": distinct,
            "skeleton_fingerprint": fp,
            "single_source": distinct == 1,
        },
        n=len(article_ids),
        key=fp,
        article_ids=sorted(article_ids),
    )


def _walk_no_score(obj: Any) -> None:
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-like key: {k}"
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


def run_skeleton_selftest() -> dict:
    """Prove the §3 mechanism on hand-built skeletons — no DB/network/score. Pins fingerprint
    stability + order-independence, MinHash clustering (near-identical skeletons cluster, a
    disjoint one does not), the ordered comparator (same order > shuffled), and the producer gate
    (fires on ≥3 sources, refuses a text near-dup / a single source)."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # Fingerprint: stable + order-independent (a set, so member order can't matter).
    fp1 = skeleton_fingerprint({3, 1, 2})
    fp2 = skeleton_fingerprint({1, 2, 3})
    check("fingerprint_stable_and_order_independent", fp1 == fp2 and len(fp1) == 16, fp1)
    check("fingerprint_distinguishes_skeletons", skeleton_fingerprint({1, 2, 4}) != fp1)

    # Clustering: two near-identical skeletons cluster; a disjoint one stays out.
    base = set(range(1, 41))
    docs = {
        "a": set(base),
        "b": (set(base) - {40}) | {41},         # 39/41 shared → high Jaccard
        "c": set(range(500, 540)),               # disjoint
    }
    clusters = skeleton_clusters(docs, threshold=0.7)
    joined = clusters[0] if clusters else set()
    check("near_identical_skeletons_cluster", len(clusters) == 1 and joined == {"a", "b"}, str(clusters))
    check("empty_skeleton_never_clusters",
          skeleton_clusters({"x": set(), "y": set()}, threshold=0.0) == [])

    # Ordered comparator: same order scores higher than shuffled.
    seq = [10, 20, 30, 40, 50]
    check("ordered_same_is_one", ordered_skeleton_similarity(seq, seq) == 1.0)
    shuffled = [50, 40, 30, 20, 10]
    check("ordered_shuffled_is_lower",
          ordered_skeleton_similarity(seq, shuffled) < 1.0,
          str(ordered_skeleton_similarity(seq, shuffled)))
    check("ordered_empty_is_zero", ordered_skeleton_similarity([], []) == 0.0)

    # Producer gate.
    source_of = {"d1": "A", "d2": "B", "d3": "C"}
    card = build_skeleton_echo_card(
        doc_ids=["d1", "d2", "d3"], source_of=source_of,
        article_ids=[1, 2, 3], keyword_ids={1, 2, 3}, is_text_neardup=False,
    )
    check("fires_on_three_sources", card is not None and card.signal["value"] == 3)
    check("refuses_text_neardup", build_skeleton_echo_card(
        doc_ids=["d1", "d2", "d3"], source_of=source_of,
        article_ids=[1, 2, 3], keyword_ids={1, 2, 3}, is_text_neardup=True) is None)
    check("refuses_below_min_sources", build_skeleton_echo_card(
        doc_ids=["d1", "d2"], source_of={"d1": "A", "d2": "A"},  # one distinct source
        article_ids=[1, 2], keyword_ids={1, 2}, is_text_neardup=False) is None)

    no_score = True
    try:
        if card is not None:
            _walk_no_score(card.signal)
    except AssertionError:
        no_score = False
    check("no_score_field", no_score)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-skeleton-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Hand-built keyword skeletons through the fingerprint / clustering / ordered / "
        "producer cores.",
        "caveat": "Verifies the pure mechanism; persistence + the live producer wiring are "
        "operator-gated (and land after the §8 triage cleanup). No score.",
    }
