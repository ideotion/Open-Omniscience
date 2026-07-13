"""
Tor throughput — the per-kind bandwidth ladder + segmented-download math (planning §5).

Circuit isolation is already built (``_with_stream_isolation`` injects per-token SOCKS auth). What
§5 adds — a per-kind token-bucket LADDER, segmented multi-circuit Range downloads, and measured
mirror selection — is absent. This module ships their PURE, INJECTABLE cores; the real
multi-circuit GET over live Tor (Accept-Ranges/206 negotiation, probing real mirrors, wiring the
ladder into ``run_scrape_once``) is OPERATOR-GATED.

Three cores:
  * ``KindLadder`` — a per-kind token bucket (injected clock) that emits an admission ORDER
    honouring a per-kind FLOOR. Ordering ≠ exclusion: a kind is never removed, and its floor debt
    guarantees it is served rather than starved by a high-rate kind.
  * ``plan_segments`` / ``reassemble`` — byte-range math with an INTEGRITY check, so a segmented
    download can never silently yield a partial or corrupt file (a gap/overlap/checksum mismatch
    fails LOUDLY).
  * ``rank_mirrors`` — a pure ranker over injected probe samples, ordered by MEASURED latency with
    ok-rate + n reported separately (no composite score; an unreachable mirror is listed last,
    never deleted).

Honesty (§5 non-negotiables): never silently downgrade transport; ordering ≠ exclusion (every kind
keeps a floor); per-host politeness is never traded for speed (it lives in the fetcher's host lock,
untouched here); no composite score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


class KindLadder:
    """A pure per-kind STRIDE scheduler (weighted-fair, provably starvation-free, clock-free).
    ``rates`` = the relative priority WEIGHT per kind (commodities/markets > interactive > RSS >
    crawl, the ledger's ladder); ``floors`` = a minimum guaranteed weight (a LOWER BOUND, so a low-
    or zero-priority kind is never starved — ordering ≠ exclusion). The effective weight is
    ``max(rate, floor)``, so raising a kind's floor gives it real proportional VOLUME, not just a
    tie-break.

    Each kind has a ``stride = 1 / weight``; ``next_kind`` serves the pending kind with the lowest
    ``pass`` (virtual time) and advances its pass by its stride. A high-weight kind has a small
    stride, so its pass grows slowly and it is served OFTEN; a low-weight kind is served rarely but
    ALWAYS eventually (its pass becomes the minimum once the busy kinds' passes catch up) — never
    starved, whatever the weights. Deterministic (no clock needed): it decides ORDER + proportional
    SHARE; the real network / BandwidthGovernor paces the actual dispatch.

    A kind whose weight is 0 (rate 0 AND no floor) asks for no share and is never served — an
    HONEST no-op, not a starvation (it can be given a floor to guarantee it a share)."""

    def __init__(
        self,
        rates: Mapping[str, float],
        floors: Mapping[str, float] | None = None,
    ) -> None:
        if not rates:
            raise ValueError("rates must name at least one kind")
        self.rates = {k: float(v) for k, v in rates.items()}
        self.floors = {k: float((floors or {}).get(k, 0.0)) for k in self.rates}
        self.weight = {k: max(self.rates[k], self.floors[k]) for k in self.rates}
        self.stride = {
            k: (1.0 / w if w > 0 else float("inf")) for k, w in self.weight.items()
        }
        self.passv = dict.fromkeys(self.rates, 0.0)
        self.served = dict.fromkeys(self.rates, 0)

    def next_kind(self, pending: set[str]) -> str | None:
        """The kind to admit next given the kinds with pending work, or ``None`` when none has a
        positive weight (nothing to schedule). Serves the lowest-``pass`` kind and advances it —
        a positive-weight pending kind is never starved (its pass is bounded, so it wins eventually)."""
        cand = [
            k for k in pending if k in self.rates and self.stride[k] != float("inf")
        ]
        if not cand:
            return None
        chosen = min(cand, key=lambda k: (self.passv[k], -self.weight[k], k))
        self.passv[chosen] += self.stride[chosen]
        self.served[chosen] += 1
        return chosen


def plan_segments(total: int, n: int, *, min_seg: int = 1) -> list[tuple[int, int]]:
    """Split ``total`` bytes into up to ``n`` CONTIGUOUS, non-overlapping half-open ranges
    ``[start, end)`` covering ``[0, total)``, each ≥ ``min_seg`` bytes (so a segmented download over
    ``n`` circuits carves the file cleanly). Fewer than ``n`` segments are returned when the file is
    too small to give each ``min_seg`` (a file smaller than ``min_seg`` is ONE whole segment).

    Raises ``ValueError`` on a non-positive ``n``/``min_seg``. Returns ``[]`` for a non-positive
    total (nothing to download)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if min_seg < 1:
        raise ValueError("min_seg must be >= 1")
    if total <= 0:
        return []
    k = min(n, max(1, total // min_seg))
    base, rem = divmod(total, k)
    segs: list[tuple[int, int]] = []
    start = 0
    for i in range(k):
        length = base + (1 if i < rem else 0)
        segs.append((start, start + length))
        start += length
    return segs


def reassemble(
    parts: list[tuple[int, bytes]],
    *,
    expected_total: int,
    expected_sha256: str,
) -> bytes:
    """Reassemble segmented parts ``[(start, data), ...]`` into the whole file, verifying INTEGRITY
    the whole way. ``expected_total`` and ``expected_sha256`` are MANDATORY — the data-safety line is
    "refuse rather than trust", so integrity is enforced by construction, never opt-in (a caller
    that omits or ``None``-s either gets a loud ``ValueError``, not a silently-unverified file).
    Contiguity from 0 (no gap, no overlap) catches a truncated/reordered set; ``expected_total``
    catches truncation; ``expected_sha256`` (the whole-file digest from the manifest / dump index)
    catches a CONTENT swap that contiguity alone cannot. Any violation raises ``ValueError`` LOUDLY,
    so a segmented multi-circuit download can never pass off a partial or corrupt file as complete.
    Order of ``parts`` does not matter; a missing middle segment is caught as a gap; the digest
    comparison is case-insensitive (a manifest's uppercase hex is accepted)."""
    if expected_total is None:
        raise ValueError("expected_total is required — refusing to reassemble without it")
    if not expected_sha256:
        raise ValueError(
            "expected_sha256 is required — refusing to trust a segmented download without an "
            "integrity check"
        )
    ordered = sorted(parts, key=lambda p: p[0])
    out = bytearray()
    cursor = 0
    for start, data in ordered:
        if start != cursor:
            raise ValueError(
                f"segment gap/overlap: next part starts at {start}, expected {cursor}"
            )
        out.extend(data)
        cursor += len(data)
    if cursor != expected_total:
        raise ValueError(f"reassembled length {cursor} != expected {expected_total}")
    if hashlib.sha256(out).hexdigest() != expected_sha256.lower():
        raise ValueError("reassembled checksum mismatch — corrupt download, refusing")
    return bytes(out)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def rank_mirrors(samples: Mapping[str, list[dict]]) -> dict:
    """Rank download mirrors by MEASURED latency. ``samples`` maps a mirror → its probe results
    ``[{ok: bool, latency_ms: float, size: int|None}, ...]``. Ranks the mirrors that responded (at
    least one ``ok`` probe) by ascending MEDIAN latency; an unreachable mirror is listed LAST, never
    deleted (ordering ≠ exclusion). Each mirror carries its ok-rate + n so a low-confidence pick is
    visible — the fields stand ALONE, never blended into a composite score."""
    ranked: list[dict] = []
    for url, probes in samples.items():
        n = len(probes)
        ok_probes = [p for p in probes if p.get("ok")]
        latencies = [float(p["latency_ms"]) for p in ok_probes if p.get("latency_ms") is not None]
        med = _median(latencies)
        ranked.append(
            {
                "mirror": url,
                "n": n,
                "ok": len(ok_probes),
                "ok_rate": (len(ok_probes) / n) if n else 0.0,
                "median_latency_ms": med,
                "reachable": med is not None,
            }
        )
    # reachable first, by ascending median latency; unreachable last (kept, not excluded).
    ranked.sort(
        key=lambda r: (
            r["median_latency_ms"] is None,
            r["median_latency_ms"] if r["median_latency_ms"] is not None else float("inf"),
            r["mirror"],
        )
    )
    return {
        "mirrors": ranked,
        "method": (
            "Ordered by measured MEDIAN latency among probes that responded; ok-rate and n are "
            "reported separately, never blended into a score."
        ),
        "caveat": (
            "Latency is measured over n probes — a low n or a low ok-rate is less certain. "
            "Ordering ≠ exclusion: an unreachable mirror is listed last, never deleted. Transport "
            "is never silently downgraded."
        ),
    }


def _walk_no_score(obj: Any) -> None:
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-like key: {k}"
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


def run_tor_throughput_selftest() -> dict:
    """Prove the §5 mechanism on deterministic fixtures — no network, no score. Pins: the ladder
    never starves a floored low-rate kind (ordering ≠ exclusion); segment planning tiles the file
    exactly and respects min_seg; reassembly catches a gap/overlap/checksum defect LOUDLY; mirror
    ranking orders by measured latency and keeps an unreachable mirror last."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    def _run_ladder(rates, floors, *, steps=200):
        lad = KindLadder(rates=rates, floors=floors)
        served: list[str] = []
        for _ in range(steps):
            k = lad.next_kind(set(rates))
            if k is not None:
                served.append(k)
        return served

    # Priority: a high-weight 'markets' is served far more than a low-weight 'crawl'...
    served = _run_ladder({"markets": 5.0, "crawl": 0.5}, {"markets": 0.0, "crawl": 0.2})
    check("ladder_serves_high_rate_more", served.count("markets") > served.count("crawl"),
          f"markets={served.count('markets')} crawl={served.count('crawl')}")
    check("ladder_low_weight_kind_still_served", served.count("crawl") >= 1)
    # ...but a FLOORED kind NEVER starves an equal-weight peer (the skeptic's F2: a floor at the
    # peer's weight must not lock the peer out). Both must be served.
    starve = _run_ladder({"a": 1.0, "b": 1.0}, {"a": 0.0, "b": 1.0})
    check("ladder_floor_never_starves_a_peer", starve.count("a") >= 1 and starve.count("b") >= 1,
          f"a={starve.count('a')} b={starve.count('b')}")
    # A zero-priority kind with a floor is served at its FLOOR weight (the floor delivers VOLUME,
    # not just a tie-break) — over 40 slots at weight 0.5 vs 4.0 it is served several times.
    floored = _run_ladder({"fast": 4.0, "slow": 0.0}, {"fast": 0.0, "slow": 0.5}, steps=40)
    check("ladder_floor_delivers_volume", floored.count("slow") >= 3, f"slow={floored.count('slow')}")
    check("ladder_empty_pending_yields_none", KindLadder({"a": 1.0}).next_kind(set()) is None)

    # Segments tile the file exactly.
    segs = plan_segments(100, 4, min_seg=10)
    covered = sum(e - s for s, e in segs)
    contiguous = all(segs[i][1] == segs[i + 1][0] for i in range(len(segs) - 1))
    check("segments_tile_exactly", covered == 100 and segs[0][0] == 0 and segs[-1][1] == 100
          and contiguous, str(segs))
    check("segments_respect_min_seg", all((e - s) >= 10 for s, e in segs), str(segs))
    check("tiny_file_is_one_segment", plan_segments(5, 4, min_seg=10) == [(0, 5)])
    check("empty_file_no_segments", plan_segments(0, 4) == [])

    # Reassembly integrity.
    data = b"abcdefghij"
    parts = [(0, data[0:4]), (4, data[4:10])]
    check("reassemble_roundtrip",
          reassemble(parts, expected_total=10, expected_sha256=hashlib.sha256(data).hexdigest())
          == data)
    good_sum = hashlib.sha256(data).hexdigest()
    gap_caught = False
    try:
        reassemble([(0, b"ab"), (4, b"ef")], expected_total=6, expected_sha256=good_sum)  # gap
    except ValueError:
        gap_caught = True
    check("reassemble_catches_a_gap", gap_caught)
    sum_caught = False
    try:
        reassemble([(0, b"abcd"), (4, b"XXXXXX")], expected_total=10, expected_sha256=good_sum)
    except ValueError:
        sum_caught = True
    check("reassemble_catches_a_checksum_mismatch", sum_caught)
    # The data-safety line: integrity is MANDATORY — a content-swap that satisfies contiguity must
    # be REFUSED, and omitting the checksum must refuse rather than trust.
    swap_caught = False
    try:
        reassemble([(0, b"BBB"), (3, b"AAA")], expected_total=6,
                   expected_sha256=hashlib.sha256(b"AAABBB").hexdigest())
    except ValueError:
        swap_caught = True
    check("reassemble_refuses_a_content_swap", swap_caught)
    no_sum_caught = False
    try:
        reassemble([(0, b"abcd")], expected_total=4, expected_sha256="")  # no checksum
    except ValueError:
        no_sum_caught = True
    check("reassemble_refuses_without_a_checksum", no_sum_caught)

    # Mirror ranking.
    mirrors = rank_mirrors(
        {
            "slow": [{"ok": True, "latency_ms": 900}, {"ok": True, "latency_ms": 1100}],
            "fast": [{"ok": True, "latency_ms": 100}, {"ok": True, "latency_ms": 120}],
            "dead": [{"ok": False, "latency_ms": None}, {"ok": False, "latency_ms": None}],
        }
    )
    order = [m["mirror"] for m in mirrors["mirrors"]]
    check("mirrors_ranked_by_latency", order == ["fast", "slow", "dead"], str(order))
    check("unreachable_mirror_kept_last",
          mirrors["mirrors"][-1]["mirror"] == "dead" and mirrors["mirrors"][-1]["reachable"] is False)

    no_score = True
    try:
        _walk_no_score(mirrors)
    except AssertionError:
        no_score = False
    check("no_score_field", no_score)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-tor-throughput-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Deterministic fixtures through the ladder / segment / reassembly / mirror cores.",
        "caveat": "Verifies the pure mechanism; the real multi-circuit Tor GET is operator-gated. "
        "No score.",
    }
