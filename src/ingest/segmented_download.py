"""
Segmented multi-circuit bulk downloads — the C11 wiring (2026-07-24 throughput
brief, S-C) over the ALREADY-SHIPPED pure cores in ``src.ingest.tor_throughput``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``plan_segments``/``reassemble`` and ``rank_mirrors`` (tor_throughput.py) are pure,
fully-tested cores; their own module docstring says the real multi-circuit GET is
OPERATOR-GATED. This module is that missing orchestration layer, built to be
called by a bulk-artifact download manager (Wikipedia dumps, OSM region extracts,
a future large-legal-base download) — but it ships DORMANT BY DEFAULT: neither
shipped catalog carries a verified mirror list or a per-file checksum today (no
real Wikipedia/Geofabrik mirror endpoint or checksum-fetch mechanism could be
confirmed from this sandbox — inventing one would be exactly the fabrication this
project's own honesty non-negotiables forbid). This is the SAME posture the
bundled httpfs extension registry uses: ship the pin blank, verify before use —
the mechanism is real and tested against fixtures, ready to activate the moment
an operator or a future networked session supplies a real mirror list + a real
whole-file checksum for a given artifact.

Bounded RAM: ``reassemble`` holds the WHOLE reassembled file in memory (fine for
a tiny test fixture, never safe for a genuinely bulk multi-GB artifact — a full
Wikipedia dump or the OSM planet file can be tens of GB). ``segmented_fetch``
REFUSES to engage above ``max_bytes`` and returns ``None`` instead; the caller's
existing streaming-to-disk Range-resume path — safe at ANY size — is the
fallback. This is a genuine safety gate, not a stub.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.ingest.tor_throughput import plan_segments, rank_mirrors, reassemble

_LOG = logging.getLogger(__name__)

# See the module docstring's "Bounded RAM" note. Operator-tunable, conservative
# defaults: a whole-file in-memory reassembly is only attempted for a modestly
# sized artifact; anything larger falls back to the proven streaming path.
DEFAULT_MAX_SEGMENTED_BYTES = int(os.getenv("OO_SEGMENTED_DOWNLOAD_MAX_MB", "500")) * 1024 * 1024
DEFAULT_SEGMENT_COUNT = max(2, int(os.getenv("OO_SEGMENTED_DOWNLOAD_SEGMENTS", "4")))


def segmented_fetch(
    url: str,
    *,
    total_bytes: int,
    expected_sha256: str,
    fetch_segment: Callable[[str, int, int], bytes],
    n_segments: int = DEFAULT_SEGMENT_COUNT,
    max_bytes: int = DEFAULT_MAX_SEGMENTED_BYTES,
    min_seg: int = 1024 * 1024,
) -> bytes | None:
    """Fetch ``url`` as ``n_segments`` byte-range parts (each via ``fetch_segment``,
    which the caller wires to a real isolated-circuit GET — a distinct isolation
    token per segment is what makes segments of the SAME file ride SEPARATE Tor
    circuits, the entire point of segmenting) and reassemble with a MANDATORY
    integrity check (``reassemble``'s own contract: refuses a gap, a truncation,
    or a checksum mismatch, LOUDLY).

    Returns ``None`` — never engages, no partial fetch attempted — when:
      * ``expected_sha256`` is empty (the whole point is a VERIFIED download,
        never an unverified one silently accepted);
      * ``total_bytes`` is non-positive or exceeds ``max_bytes`` (the bounded-RAM
        safety gate — see the module docstring);
      * fewer than 2 segments would result (not worth the parallel-fetch
        machinery for a file too small to split).

    A segment fetch failure (an exception from ``fetch_segment``) propagates —
    the caller's own retry/error handling around the whole call decides what to
    do. A reassembly integrity failure (``ValueError`` from ``reassemble``) ALSO
    propagates — it is a genuine defect (a corrupt/short/reordered segment, or a
    tampered fetch), never silently swallowed into a fallback "success".
    """
    if not expected_sha256:
        _LOG.debug("segmented_fetch: no expected_sha256 supplied — refusing to engage")
        return None
    if total_bytes <= 0 or total_bytes > max_bytes:
        return None
    segs = plan_segments(total_bytes, n_segments, min_seg=min_seg)
    if len(segs) < 2:
        return None
    parts: list[tuple[int, bytes]] = []
    with ThreadPoolExecutor(max_workers=len(segs)) as ex:
        futures = {ex.submit(fetch_segment, url, s, e): (s, e) for s, e in segs}
        for fut in as_completed(futures):
            start, _end = futures[fut]
            parts.append((start, fut.result()))
    return reassemble(parts, expected_total=total_bytes, expected_sha256=expected_sha256)


def choose_mirror(
    canonical_url: str,
    mirrors: list[str],
    *,
    probe: Callable[[str], Mapping],
    probes_per_mirror: int = 1,
) -> str:
    """Pick the fastest REACHABLE mirror for a bulk download via ``rank_mirrors``.

    ``mirrors`` is an operator/config-supplied list of alternate URLs for the
    SAME artifact — empty by default for every shipped catalog entry today (see
    the module docstring); never fabricated here. Each of ``canonical_url`` and
    every ``mirrors`` entry is probed ``probes_per_mirror`` time(s) via the
    injected ``probe`` callable (the caller wires this to a real latency check);
    ``rank_mirrors`` ranks by measured MEDIAN latency, with ok-rate/n reported
    separately (no composite score), an unreachable candidate listed last — never
    dropped, so ``canonical_url`` always remains a valid fallback.

    Returns ``canonical_url`` unchanged when ``mirrors`` is empty (byte-identical
    to not having this feature at all) or when every candidate is unreachable
    (degrade to the canonical URL rather than fail the whole download outright).
    A ``probe`` exception reads as an unreachable result for that one candidate,
    never a crash of the whole selection.
    """
    if not mirrors:
        return canonical_url
    samples: dict[str, list[dict]] = {}
    for candidate in (canonical_url, *mirrors):
        probes: list[dict] = []
        for _ in range(max(1, probes_per_mirror)):
            try:
                probes.append(dict(probe(candidate)))
            except Exception:  # noqa: BLE001 - a probe failure reads as unreachable, not a crash
                probes.append({"ok": False, "latency_ms": None})
        samples[candidate] = probes
    ranked = rank_mirrors(samples)["mirrors"]
    top = ranked[0]
    return str(top["mirror"]) if top["reachable"] else canonical_url


def default_fetch_segment(url: str, start: int, end: int) -> bytes:
    """Real-network default for ``segmented_fetch``'s ``fetch_segment``: routes
    through the guarded factory (kill switch / protected-mode proxy honoured,
    never a silent transport downgrade) with a PER-SEGMENT isolation token, so
    segments of the SAME file ride separate Tor circuits."""
    from src.safety.fetcher import guarded_session

    token = f"{url}#seg-{start}-{end}"
    resp = guarded_session(isolation_token=token).get(
        url, headers={"Range": f"bytes={start}-{end - 1}"}, timeout=60
    )
    resp.raise_for_status()
    return resp.content


def default_mirror_probe(url: str) -> dict:
    """Real-network default for ``choose_mirror``'s ``probe``: a timed HEAD
    request through the guarded factory. Best-effort — any failure reads as
    unreachable (``ok: False``), never crashes the mirror-selection loop."""
    from src.safety.fetcher import guarded_session

    t0 = time.monotonic()
    try:
        resp = guarded_session(isolation_token=url).head(url, allow_redirects=True, timeout=15)
        resp.raise_for_status()
        return {"ok": True, "latency_ms": (time.monotonic() - t0) * 1000.0}
    except Exception:  # noqa: BLE001 - unreachable is a valid probe result, not a crash
        return {"ok": False, "latency_ms": None}
