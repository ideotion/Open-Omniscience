"""
Story lineage — trace an echoed story toward its primal/original source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

For a near-duplicate cluster (the *same* story across many outlets), reconstruct the chain
**primary → first report → echoes**: order by earliest publication, detect explicit **wire
attribution** ("according to Reuters", "(AFP)", "Bloomberg reported") and citations, and
surface the structure so a journalist can foreground original reporting over derivative
echoes (FUTURE_DEVELOPMENTS §2).

Honesty (the bright line): **"earliest we saw" ≠ "the truth", and ≠ "the real origin".**
The tool shows lineage and structure from *your* corpus; it never auto-labels anything true
or original. Down-weighting derivative sources is the user's call, transparent and reversible.

Pure: no DB, no network, unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Major wire agencies (lowercase tokens). Attribution to a wire is a strong signal that a
# piece is *derivative* of the wire's original reporting.
_WIRE_AGENCIES = {
    "reuters": "Reuters",
    "afp": "AFP",
    "agence france-presse": "AFP",
    "associated press": "Associated Press",
    "ap": "Associated Press",
    "bloomberg": "Bloomberg",
    "pa media": "PA Media",
    "press association": "PA Media",
    "dpa": "dpa",
    "efe": "EFE",
    "ansa": "ANSA",
    "tass": "TASS",
    "xinhua": "Xinhua",
    "kyodo": "Kyodo",
    "yonhap": "Yonhap",
    "pti": "PTI",
    "ians": "IANS",
}
# "according to X", "X reported/said", "(X)" near the start — attribution patterns.
_ATTRIB_RES = [
    re.compile(r"\baccording to ([A-Z][\w .&'-]{2,40})", re.UNICODE),
    re.compile(r"\b([A-Z][\w .&'-]{2,40}) (?:reported|said|reports|wrote)\b"),
    re.compile(r"\(\s*([A-Za-z][\w .&'-]{1,30})\s*\)"),
]

_CAVEAT = (
    "Lineage is reconstructed from YOUR corpus by publication time + explicit attribution. "
    "'Earliest seen' is not proof of the true origin, and wire attribution shows a piece is "
    "derivative, not that it is right or wrong. It foregrounds structure; the human judges."
)


def detect_wire_attribution(text: str) -> str | None:
    """Return the canonical wire-agency name if the text attributes to one, else None."""
    low = (text or "").lower()
    # Prefer an explicit "(Reuters)"/"according to Reuters" near a recognised agency.
    for token, canonical in _WIRE_AGENCIES.items():
        if re.search(rf"\b{re.escape(token)}\b", low):
            # Avoid the bare "ap"/"efe" false positives unless attribution-shaped.
            if len(token) <= 2:
                if re.search(
                    rf"\(\s*{re.escape(token)}\s*\)|according to {re.escape(token)}\b"
                    rf"|\b{re.escape(token)} (?:reported|said)\b",
                    low,
                ):
                    return canonical
                continue
            return canonical
    return None


def detect_attribution(text: str) -> str | None:
    """Return the first explicitly-cited source ('according to X', 'X reported'), if any."""
    wire = detect_wire_attribution(text)
    if wire:
        return wire
    for rx in _ATTRIB_RES[:2]:  # the two attribution-verb patterns (skip the noisy paren one)
        m = rx.search(text or "")
        if m:
            return m.group(1).strip()
    return None


@dataclass
class LineageItem:
    doc_id: str
    source: str | None
    published_at: datetime | None
    wire: str | None
    cites: str | None

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "wire": self.wire,
            "cites": self.cites,
        }


@dataclass
class LineageResult:
    n: int
    primary: LineageItem | None  # earliest in the corpus (a candidate, not "the truth")
    wire_origin: str | None  # a wire agency the chain attributes to, if any
    chain: list[LineageItem] = field(default_factory=list)  # time-ordered
    method: str = "near-duplicate cluster ordered by publication time + wire/citation detection"
    caveat: str = _CAVEAT

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "primary": self.primary.to_dict() if self.primary else None,
            "wire_origin": self.wire_origin,
            "chain": [c.to_dict() for c in self.chain],
            "method": self.method,
            "caveat": self.caveat,
        }


def trace_lineage(docs: list[dict]) -> LineageResult:
    """Trace lineage of a set of near-duplicate documents.

    Each doc: ``{id, source?, text?, published_at?(datetime)}``. The chain is ordered by
    ``published_at`` (documents with no date sort last, after the dated ones). The earliest
    dated document is the *primary candidate*; an attributed wire agency (if any) is the
    likeliest true origin upstream of the corpus.
    """
    items = [
        LineageItem(
            doc_id=str(d["id"]),
            source=d.get("source"),
            published_at=d.get("published_at")
            if isinstance(d.get("published_at"), datetime)
            else None,
            wire=detect_wire_attribution(d.get("text", "")),
            cites=detect_attribution(d.get("text", "")),
        )
        for d in docs
    ]
    # Dated first (ascending), then undated (stable).
    dated = sorted([i for i in items if i.published_at], key=lambda i: i.published_at)
    undated = [i for i in items if not i.published_at]
    chain = dated + undated
    primary = chain[0] if chain else None
    wire_origin = next((i.wire for i in chain if i.wire), None)
    return LineageResult(n=len(items), primary=primary, wire_origin=wire_origin, chain=chain)
