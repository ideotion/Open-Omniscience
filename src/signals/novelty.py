"""
Novelty / surprisal — how much *new* information a document contributes to the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The information-theoretic half of §6 anti-amplification. Instead of weighting influence
by raw *volume* (which subsidises the flooder), weight it by **independent information
contributed**: a document's novelty is the share of its word-shingles that the corpus
has **not seen before**. The 1000th repost scores ~0 — not because it is *false* (the
tool never says that) but because it is **not new**, which is simply true. Under this
measure the small, original, independent source *rises* relative to a manufactured
flood — it inverts the feared failure mode.

Honesty (the sharp edge here): novelty is **relative to the corpus and the order** it
was seen in, and it measures *new wording*, not *truth*, *importance* or *quality*. A
genuine fresh report and an inflammatory fabrication can both be novel; novelty only
separates *original* from *derivative*. It is a signal to weight by, never a verdict.

Pure: an incremental in-memory index of shingle hashes; no DB, no network, unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.signals.near_dup import shingles

_CAVEAT = (
    "Novelty is the share of a document's word-shingles not already in the corpus — "
    "*new wording relative to what was seen before*, in the order seen. It measures "
    "originality vs derivation, NOT truth, importance or quality: an original report "
    "and an original fabrication can both score high. Use it to avoid double-counting "
    "echoes, never as a judgement of worth."
)


@dataclass
class NoveltyResult:
    ratio: float | None  # new_shingles / total_shingles, or None if no shingles
    n_shingles: int
    new_shingles: int
    method: str = "share of word-shingles not previously seen in the corpus (incremental)"
    caveat: str = _CAVEAT

    def to_dict(self) -> dict:
        return {
            "ratio": self.ratio,
            "n_shingles": self.n_shingles,
            "new_shingles": self.new_shingles,
            "method": self.method,
            "caveat": self.caveat,
        }


class NoveltyIndex:
    """An incremental corpus index: measure a document's novelty, then absorb it.

    Measure *before* adding, so the first time a story appears it is fully novel and
    every later near-copy is mostly not. ``k`` is the shingle width (must match across
    a run for the numbers to be comparable).
    """

    def __init__(self, k: int = 5):
        self.k = k
        self._seen: set[int] = set()

    def __len__(self) -> int:
        return len(self._seen)

    def novelty(self, text: str) -> NoveltyResult:
        """Novelty of ``text`` against what has been added so far (does NOT add it)."""
        sh = shingles(text, self.k)
        if not sh:
            return NoveltyResult(ratio=None, n_shingles=0, new_shingles=0)
        new = sum(1 for s in sh if s not in self._seen)
        return NoveltyResult(ratio=new / len(sh), n_shingles=len(sh), new_shingles=new)

    def add(self, text: str) -> None:
        """Absorb ``text`` into the corpus index."""
        self._seen |= shingles(text, self.k)

    def measure_and_add(self, text: str) -> NoveltyResult:
        """Measure novelty, then add — the normal streaming use."""
        result = self.novelty(text)
        self.add(text)
        return result


def novelty_scores(documents: list[tuple[str, str]], *, k: int = 5) -> dict[str, NoveltyResult]:
    """Per-document novelty for ``[(id, text), ...]`` processed *in the given order*.

    Order matters: pass documents oldest-first so the earliest original earns the
    novelty and later echoes score low — the honest realisation of "trace to the
    primal source" at the wording level.
    """
    index = NoveltyIndex(k=k)
    return {doc_id: index.measure_and_add(text) for doc_id, text in documents}
