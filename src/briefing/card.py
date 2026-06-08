"""
The Card — the single unit of surfaced intelligence in the Home briefing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A card is **one measurable signal + the evidence links + a caveat**, pre-sorted
into an editorial bucket. A card *surfaces a signal; it never renders a verdict*
(no "biased", no "propaganda", no "true/fake", no "trust score"). This is the
GUI spine of 0.06: every later capability appears as one more card in the *same*
feed, so it is seen the day it ships.

Honesty guard (in code, not just docs)
---------------------------------------
FUTURE_DEVELOPMENTS §6 forbids a single automated trust/quality score. That ban is
enforced here mechanically: :func:`assert_no_score_fields` rejects any dataclass
field whose name implies a composite quality/trust score, and a test asserts it
holds for :class:`Card`. The numeric ``signal`` a card carries is a *single measured
quantity with a stated method* (e.g. a growth ratio, a Gini value) — never a
blended score over incommensurable dimensions.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Editorial buckets a card can be sorted into. The triad behind them
# (convergence → overtold, divergence → investigate/debunk, absence → undertold)
# is the engine; these are its surfaced labels. Order = display order on Home.
BUCKETS: tuple[str, ...] = (
    "rising",       # something is moving / new
    "overtold",     # sources agree too fast / too uniformly (echo, synchrony)
    "undertold",    # something moved but little/nobody covered it
    "investigate",  # sources or data disagree — a question to dig into
    "debunk",       # same event framed in opposing ways — a claim to check
    "watch",        # a change worth keeping an eye on (e.g. a reshaped record)
    "context",      # background / self-audit / standing facts
    "trust",        # data-integrity / hygiene signals about the corpus itself
)

BUCKET_LABELS: dict[str, str] = {
    "rising": "Rising now",
    "overtold": "Overtold",
    "undertold": "Undertold",
    "investigate": "Worth investigating",
    "debunk": "Check the framing",
    "watch": "Keep watching",
    "context": "Context",
    "trust": "Data integrity",
}

# Field-name fragments that would imply a composite quality/trust score. Banned on
# Card (and intended for Source profiles too) — see §6 "B is forbidden".
_BANNED_FIELD_FRAGMENTS: tuple[str, ...] = (
    "trust_score",
    "credibility",
    "quality_score",
    "veracity",
    "reliability_score",
    "bias_score",
    "verdict",
)
# Bare "score"/"rating"/"rank" are banned as *standalone* field names; we keep the
# check name-based so a legitimate measured quantity can still live in ``signal``.
_BANNED_FIELD_NAMES: frozenset[str] = frozenset({"score", "rating", "rank", "trust"})


class CardSchemaError(TypeError):
    """Raised when a dataclass declares a field that implies a forbidden score."""


def assert_no_score_fields(cls: type) -> None:
    """Fail loudly if ``cls`` declares any composite-score field (§6 honesty guard).

    Called at import time on :class:`Card`; also reusable for the future Source
    profile so the ban is enforced everywhere a contributor might add one by reflex.
    """
    for f in dataclasses.fields(cls):
        name = f.name.lower()
        if name in _BANNED_FIELD_NAMES or any(frag in name for frag in _BANNED_FIELD_FRAGMENTS):
            raise CardSchemaError(
                f"{cls.__name__}.{f.name}: a composite trust/quality 'score' field is "
                f"forbidden (FUTURE_DEVELOPMENTS §6 — B is banned in code, not just prose). "
                f"Surface a single measured quantity in `signal` with its method instead."
            )


@dataclass
class Card:
    """One surfaced signal for the Home briefing.

    Fields:
      * ``type``    — card-type id (stable across runs, e.g. ``"rising"``).
      * ``title``   — short headline of the signal.
      * ``summary`` — one honest sentence a journalist can read at a glance.
      * ``bucket``  — one of :data:`BUCKETS`.
      * ``signal``  — the measured quantity/quantities (``{metric, value, ...}``);
                      a *single* measurement with a method, never a blended score.
      * ``method``  — how the number was computed (always present).
      * ``caveat``  — what it does *not* mean / its limits (always present).
      * ``evidence``— links back to the corpus (``[{title, url, source, ...}]``).
      * ``n``       — sample size behind the signal, when defined.
      * ``key``     — a within-type identity (e.g. the keyword) used to build ``id``.
      * ``id``      — stable id for pin/dismiss (hash of type+key).
      * ``dismissible`` — whether the user can dismiss it (default True).
    """

    type: str
    title: str
    summary: str
    bucket: str
    method: str
    caveat: str
    signal: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    n: int | None = None
    key: str = ""
    id: str = ""
    created_at: str = ""
    dismissible: bool = True

    def __post_init__(self) -> None:
        if self.bucket not in BUCKETS:
            raise ValueError(f"unknown bucket {self.bucket!r}; use one of {BUCKETS}")
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.id:
            basis = f"{self.type}|{self.key or self.title}".encode()
            self.id = hashlib.sha256(basis).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "summary": self.summary,
            "bucket": self.bucket,
            "signal": self.signal,
            "method": self.method,
            "caveat": self.caveat,
            "evidence": self.evidence,
            "n": self.n,
            "created_at": self.created_at,
            "dismissible": self.dismissible,
        }


# Enforce the §6 ban the moment this module is imported — not only under test.
assert_no_score_fields(Card)
