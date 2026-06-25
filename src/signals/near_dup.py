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
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from random import Random

# Mersenne prime 2**61 - 1: a large prime for the universal hash family h(x)=(a·x+b) mod p.
# Domain bounds chosen so a·x+b fits in 64 bits EXACTLY (a,b < 2^31; x reduced to
# 32 bits): the numpy fast path and the pure-Python fallback then compute the
# *identical* signature — clusters never depend on which optional deps are
# installed (performance batch 2026-06-12; the briefing refresh measured 36 s
# at the live corpus scale, >95% of it in this module's pure-Python inner loop).
_MERSENNE = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1
_AB_BOUND = 1 << 31

try:  # optional accelerator (the analysis extra); identical math either way
    import numpy as _np
except ImportError:  # pragma: no cover - exercised on core-only installs
    _np = None

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


def shared_word_ngrams(
    docs: dict[str, str],
    *,
    k: int = 8,
    min_docs: int = 2,
    max_phrases: int = 200,
) -> list[dict]:
    """Verbatim ``k``-word phrases that appear in at least ``min_docs`` DISTINCT documents.

    Unlike :func:`shingles` (which *hashes* word k-shingles for MinHash), this keeps the
    phrase TEXT, so a caller can SHOW the copied span — the seed of the copypasta /
    shared-talking-point card. Consecutive shared k-grams within a document are merged into
    the longest contiguous phrase, and each reported phrase carries the documents that
    contain it IN FULL (the intersection of its constituent k-grams' document sets), so a
    copied sentence is reported once as its whole text rather than as many overlapping
    windows. A phrase wholly contained (word-aligned) in a longer reported phrase over the
    same-or-fewer documents is dropped.

    Returns ``[{"phrase", "n_docs", "doc_ids"}]`` sorted by ``n_docs`` desc. Pure: no DB,
    no network; case-folded and whitespace-normalised via the shared word tokeniser. This
    is a *structural* measurement — shared text — never a judgement of intent or truth.
    """
    if k < 1 or min_docs < 2:
        return []
    toks = {d: _WORD_RE.findall(t.lower()) for d, t in docs.items()}
    gram_docs: dict[tuple[str, ...], set[str]] = {}
    for d, ws in toks.items():
        for i in range(len(ws) - k + 1):
            gram_docs.setdefault(tuple(ws[i : i + k]), set()).add(d)

    def _shared(g: tuple[str, ...]) -> bool:
        return len(gram_docs.get(g, ())) >= min_docs

    # Walk each document, merging maximal runs of consecutive shared k-grams into spans.
    spans: dict[str, set[str]] = {}
    for ws in toks.values():
        n = len(ws)
        i = 0
        while i <= n - k:
            if not _shared(tuple(ws[i : i + k])):
                i += 1
                continue
            j = i
            while j + 1 <= n - k and _shared(tuple(ws[j + 1 : j + 1 + k])):
                j += 1
            words = ws[i : j + k]
            # Documents containing the WHOLE span = intersection of its k-grams' doc sets.
            common: set[str] = set.intersection(
                *(gram_docs[tuple(words[t : t + k])] for t in range(len(words) - k + 1))
            )
            if len(common) >= min_docs:
                spans.setdefault(" ".join(words), set()).update(common)
            i = j + 1

    # Sort + dedup over (phrase, docs) TUPLES — keeping the heterogeneous result dicts
    # out of the comparison logic so the keys stay precisely typed (str / set[str]) —
    # then build the result dicts at the very end. A phrase fully contained (word-
    # aligned) in a longer one over the same-or-fewer documents is dropped.
    ordered = sorted(spans.items(), key=lambda kv: (-len(kv[0]), -len(kv[1])))
    kept: list[tuple[str, set[str]]] = []
    for phrase, ds in ordered:
        rp = f" {phrase} "
        if any(rp in f" {kp} " and ds <= kds for kp, kds in kept):
            continue
        kept.append((phrase, ds))
    kept.sort(key=lambda kv: (-len(kv[1]), -len(kv[0])))
    return [
        {"phrase": p, "n_docs": len(ds), "doc_ids": sorted(ds)} for p, ds in kept[:max_phrases]
    ]


def _h64(s: str) -> int:
    """A stable 64-bit hash of a string (blake2b, not Python's salted hash())."""
    import hashlib

    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


@lru_cache(maxsize=8)
def _hash_family(num_perm: int, seed: int = 0) -> tuple[tuple[int, int], ...]:
    """``num_perm`` deterministic (a, b) pairs for h(x) = (a·x + b) mod p, a≠0.

    a, b < 2^31 so that with x reduced to 32 bits the affine form stays below
    2^64 — exact in unsigned 64-bit arithmetic (the numpy path) and in Python
    ints alike. Cached: the family is pure in (num_perm, seed).
    """
    rng = Random(seed)
    return tuple(
        (rng.randrange(1, _AB_BOUND), rng.randrange(0, _AB_BOUND)) for _ in range(num_perm)
    )


def minhash_signature(elements: set[int], num_perm: int = 128, *, seed: int = 0) -> list[int]:
    """MinHash signature of a shingle set: the min of each hash permutation.

    An empty set yields a sentinel signature (all ``_MERSENNE``) that matches
    nothing. Vectorised through numpy when available; the pure-Python fallback
    computes the identical numbers (parity is unit-tested), so results never
    depend on optional dependencies.
    """
    family = _hash_family(num_perm, seed)
    if not elements:
        return [_MERSENNE] * num_perm
    if _np is not None:
        x = _np.fromiter(elements, dtype=_np.uint64, count=len(elements))
        x &= _np.uint64(_MAX_HASH)  # reduce to the 32-bit domain (exactness bound)
        ab = _np.asarray(family, dtype=_np.uint64)  # (num_perm, 2)
        # (a·x + b) % p, broadcast: num_perm × n — max value < 2^63 + 2^31 < 2^64.
        hashed = (ab[:, 0:1] * x[_np.newaxis, :] + ab[:, 1:2]) % _np.uint64(_MERSENNE)
        return [int(v) for v in hashed.min(axis=1)]
    reduced = [x & _MAX_HASH for x in elements]
    return [min((a * x + b) % _MERSENNE for x in reduced) for a, b in family]


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


# Memo for repeat clustering of the SAME documents within a process: the Home
# briefing refresh runs the pass several times over one recent-news window
# (echo_chamber + lonely_signal + story_lineage — audit finding F-005). The
# function is pure, so identical inputs may return the cached result; the key
# fingerprints the full content + parameters, and results are copied out so a
# caller can never mutate the cache.
_MEMO_MAX = 8
_memo: OrderedDict[bytes, NearDupResult] = OrderedDict()


def _fingerprint(docs: dict[str, str], params: tuple) -> bytes:
    import hashlib

    h = hashlib.blake2b(digest_size=16)
    h.update(repr(params).encode())
    for doc_id in sorted(docs):
        h.update(doc_id.encode("utf-8", "replace"))
        h.update(b"\x00")
        h.update(docs[doc_id].encode("utf-8", "replace"))
        h.update(b"\x01")
    return h.digest()


def _copy_result(r: NearDupResult) -> NearDupResult:
    return NearDupResult(
        method=r.method,
        n=r.n,
        threshold=r.threshold,
        clusters=[
            DuplicateCluster(
                members=list(c.members),
                representative=c.representative,
                avg_similarity=c.avg_similarity,
                evidence=[dict(e) for e in c.evidence],
            )
            for c in r.clusters
        ],
    )


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

    key = _fingerprint(docs, (threshold, num_perm, bands, rows, seed))
    cached = _memo.get(key)
    if cached is not None:
        _memo.move_to_end(key)
        return _copy_result(cached)

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

    result = NearDupResult(
        method=(
            f"MinHash({num_perm} perm) + LSH({bands}×{rows} banding); pairs confirmed "
            f"at Jaccard ≥ {threshold}"
        ),
        n=len(docs),
        threshold=threshold,
        clusters=clusters,
    )
    _memo[key] = _copy_result(result)
    while len(_memo) > _MEMO_MAX:
        _memo.popitem(last=False)
    return result
