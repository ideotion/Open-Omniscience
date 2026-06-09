"""
Near-duplicate detection — MinHash signatures + LSH banding (pure, sub-quadratic).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The cheap, honest way to ask "is this the *same story* as that one?" without heavy
ML: represent each document by the set of its word **shingles**, estimate the
Jaccard similarity of two sets with a **MinHash** signature, and find candidate
near-duplicate pairs in roughly linear time with **Locality-Sensitive Hashing**
(banding) instead of comparing every pair.

This is a *structural* measurement — overlap of text — never a judgement of truth or
quality. The 1000th copy of a wire story is *not new*; that is simply true, and it is
all this module claims. It is the seed of the echo/syndication cards and (with timing
+ infrastructure fingerprints in :mod:`coordination`) of §6 actor-collapse.

Everything here is pure: deterministic hashing, no DB, no network, fully unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from random import Random

# Mersenne prime 2**61 - 1: a large prime for the universal hash family h(x)=(a·x+b) mod p.
_MERSENNE = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1

_WORD_RE = re.compile(r"\w+", re.UNICODE)

_CAVEAT = (
    "Near-duplication measures *text overlap* (shared word-shingles), not meaning, "
    "truth or quality. High overlap means the wording is shared (syndication, copy-"
    "paste, light rewrite); it never implies either copy is right or wrong. MinHash "
    "estimates Jaccard similarity — it is approximate, and short texts are noisy."
)


def shingles(text: str, k: int = 5) -> set[int]:
    """Hashed word k-shingles of ``text`` (a set of 64-bit ints).

    Word-level (not char-level) shingles are robust to whitespace/markup and cheap.
    Texts shorter than ``k`` words fall back to the bag of their words so a short
    headline still yields *some* signal rather than an empty set.
    """
    words = _WORD_RE.findall(text.lower())
    if not words:
        return set()
    if len(words) < k:
        return {_h64(w) for w in words}
    out: set[int] = set()
    for i in range(len(words) - k + 1):
        out.add(_h64(" ".join(words[i : i + k])))
    return out


def _h64(s: str) -> int:
    """A stable 64-bit hash of a string (blake2b, not Python's salted hash())."""
    import hashlib

    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def _hash_family(num_perm: int, *, seed: int = 0) -> list[tuple[int, int]]:
    """``num_perm`` deterministic (a, b) pairs for h(x) = (a·x + b) mod p, a≠0."""
    rng = Random(seed)
    return [(rng.randrange(1, _MERSENNE), rng.randrange(0, _MERSENNE)) for _ in range(num_perm)]


def minhash_signature(elements: set[int], num_perm: int = 128, *, seed: int = 0) -> list[int]:
    """MinHash signature of a shingle set: the min of each hash permutation.

    An empty set yields a sentinel signature (all ``_MERSENNE``) that matches nothing.
    """
    family = _hash_family(num_perm, seed=seed)
    if not elements:
        return [_MERSENNE] * num_perm
    sig = []
    for a, b in family:
        sig.append(min(((a * x + b) % _MERSENNE) for x in elements))
    return sig


def jaccard_estimate(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimate Jaccard similarity as the fraction of equal signature slots."""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    equal = sum(1 for x, y in zip(sig_a, sig_b, strict=False) if x == y)
    return equal / len(sig_a)


@dataclass
class DuplicateCluster:
    """A set of document ids whose texts are mutually near-duplicate."""

    members: list[str]
    representative: str  # earliest/most-central member id (caller-defined)
    avg_similarity: float = 0.0
    evidence: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "members": self.members,
            "representative": self.representative,
            "size": len(self.members),
            "avg_similarity": round(self.avg_similarity, 4),
            "evidence": self.evidence,
        }


@dataclass
class NearDupResult:
    method: str
    n: int  # documents considered
    threshold: float
    clusters: list[DuplicateCluster] = field(default_factory=list)
    caveat: str = _CAVEAT

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "n": self.n,
            "threshold": self.threshold,
            "clusters": [c.to_dict() for c in self.clusters],
            "caveat": self.caveat,
        }


def _lsh_candidate_pairs(
    signatures: dict[str, list[int]], bands: int, rows: int
) -> set[tuple[str, str]]:
    """Candidate near-duplicate id pairs via LSH banding (sub-quadratic)."""
    buckets: dict[tuple, list[str]] = {}
    for doc_id, sig in signatures.items():
        for b in range(bands):
            band = tuple(sig[b * rows : (b + 1) * rows])
            buckets.setdefault((b, band), []).append(doc_id)
    pairs: set[tuple[str, str]] = set()
    for ids in buckets.values():
        if len(ids) < 2:
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.add(tuple(sorted((ids[i], ids[j]))))
    return pairs


def _connected_components(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]]:
    """Union-find over confirmed near-dup edges → clusters."""
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
    return [c for c in comps.values() if len(c) > 1]


def near_duplicate_clusters(
    docs: dict[str, str],
    *,
    threshold: float = 0.7,
    num_perm: int = 128,
    bands: int = 32,
    rows: int = 4,
    seed: int = 0,
) -> NearDupResult:
    """Cluster ``{id: text}`` into near-duplicate groups.

    LSH proposes candidate pairs (cheap); each candidate is *confirmed* only when its
    MinHash-estimated Jaccard ≥ ``threshold`` (high-precision — biased toward
    *under*-merging, per the §6 "false merges hurt the innocent" rule). ``bands * rows``
    must equal ``num_perm``.
    """
    if bands * rows != num_perm:
        raise ValueError(f"bands*rows ({bands * rows}) must equal num_perm ({num_perm})")

    signatures = {
        doc_id: minhash_signature(shingles(text), num_perm, seed=seed)
        for doc_id, text in docs.items()
    }
    candidates = _lsh_candidate_pairs(signatures, bands, rows)

    edges: set[tuple[str, str]] = set()
    sims: dict[tuple[str, str], float] = {}
    for a, b in candidates:
        s = jaccard_estimate(signatures[a], signatures[b])
        if s >= threshold:
            edges.add((a, b))
            sims[(a, b)] = s

    clusters: list[DuplicateCluster] = []
    for comp in _connected_components(set(docs), edges):
        members = sorted(comp)
        member_sims = [sims[p] for p in sims if p[0] in comp and p[1] in comp]
        avg = sum(member_sims) / len(member_sims) if member_sims else 0.0
        clusters.append(
            DuplicateCluster(
                members=members,
                representative=members[0],
                avg_similarity=avg,
            )
        )
    clusters.sort(key=lambda c: (-len(c.members), -c.avg_similarity))

    return NearDupResult(
        method=(
            f"MinHash({num_perm} perm) + LSH({bands}×{rows} banding); pairs confirmed "
            f"at Jaccard ≥ {threshold}"
        ),
        n=len(docs),
        threshold=threshold,
        clusters=clusters,
    )
