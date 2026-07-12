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
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Editorial buckets a card can be sorted into. The triad behind them
# (convergence → overtold, divergence → investigate/debunk, absence → undertold)
# is the engine; these are its surfaced labels. Order = display order on Home.
BUCKETS: tuple[str, ...] = (
    "rising",  # something is moving / new
    "overtold",  # sources agree too fast / too uniformly (echo, synchrony)
    "undertold",  # something moved but little/nobody covered it
    "investigate",  # sources or data disagree — a question to dig into
    "debunk",  # same event framed in opposing ways — a claim to check
    "watch",  # a change worth keeping an eye on (e.g. a reshaped record)
    "context",  # background / self-audit / standing facts
    "trust",  # data-integrity / hygiene signals about the corpus itself
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
      * ``recipe``  — optional one-click investigation (0.0.8 WP8 / RM-20):
                      ``{"view": "<recipe-id>", "params": {...}}``, rendered by
                      the Home UI as an "Open investigation" button that opens
                      ``/investigate`` in a NEW browser tab, pre-filled. A recipe
                      carries *parameters the user could have typed themselves* —
                      never embedded conclusions, never score-shaped keys
                      (enforced in ``__post_init__``).
      * ``trigger`` — optional "Why am I seeing this?" audit trail (evidence-
                      tiered cards, maintainer-ruled 2026-06-10):
                      ``{"plain": str, "math": [{"label": str, "value": str}]}``.
                      ``plain`` is ONE constant plain-language sentence per card
                      type (no jargon, no embedded data — so the i18n engine can
                      translate it exactly); each ``math`` row is a constant
                      ``label`` (translated the same way) plus a ``value`` of
                      numbers/symbols only (language-neutral). The exact
                      arithmetic that fired the card, reproducible by hand.
    """

    type: str
    title: str
    summary: str
    bucket: str
    method: str
    caveat: str
    # Optional TRANSLATABLE title (S4.5): a fixed keyable TEMPLATE with {named}
    # placeholders whose values are language-neutral DATA (the keyword term, a count,
    # a place) left untranslated. The English ``title`` above stays the fallback (a
    # card without ``title_i18n``, or a browser without OOI18N.tf, shows it), so this
    # is purely additive. The frame translates ×12, the data does not — the same rule
    # that lets ``trigger.plain`` translate. Both are validated in ``__post_init__``.
    title_i18n: str = ""
    title_vars: dict = field(default_factory=dict)
    signal: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    # The FULL article set the card is built from (set-based cards only — convergence,
    # echo-chamber). The UI seeds the analysis window with this exact set so the
    # corpus IS the articles the card identified (maintainer-ruled 2026-06-16), not a
    # re-run search that only approximates a set-based selection. Empty for cards whose
    # selection is a keyword/topic (the query reproduces those) or a whole-corpus
    # distribution (e.g. reading-diet). A list of ids, never a score.
    article_ids: list[int] = field(default_factory=list)
    n: int | None = None
    key: str = ""
    id: str = ""
    created_at: str = ""
    dismissible: bool = True
    recipe: dict | None = None
    trigger: dict | None = None

    def __post_init__(self) -> None:
        if self.bucket not in BUCKETS:
            raise ValueError(f"unknown bucket {self.bucket!r}; use one of {BUCKETS}")
        if self.recipe is not None:
            self._validate_recipe(self.recipe)
        if self.title_i18n:
            self._validate_title_i18n(self.title_i18n, self.title_vars)
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()
        if not self.id:
            basis = f"{self.type}|{self.key or self.title}".encode()
            self.id = hashlib.sha256(basis).hexdigest()[:16]

    @staticmethod
    def _validate_title_i18n(template: str, variables: dict) -> None:
        """A translatable title is a fixed TEMPLATE + language-neutral scalar VARS.

        Every ``{name}`` placeholder in the template MUST have a matching var (else the
        UI would render a literal ``{name}`` — a broken frame, never acceptable), and
        every var value must be a JSON scalar (the data the frame carries; a dict/list
        could smuggle structure the translator can't see). Fails loudly — the same
        honesty-by-construction bar as ``_validate_recipe``."""
        if not isinstance(template, str):
            raise CardSchemaError("title_i18n must be a string template")
        if not isinstance(variables, dict):
            raise CardSchemaError("title_vars must be a dict")
        for k, v in variables.items():
            if v is not None and not isinstance(v, (str, int, float, bool)):
                raise CardSchemaError(
                    f"title_vars[{k!r}] must be a JSON scalar (got {type(v).__name__})"
                )
        placeholders = set(re.findall(r"\{(\w+)\}", template))
        missing = placeholders - set(variables)
        if missing:
            raise CardSchemaError(
                f"title_i18n template has placeholders with no matching title_vars: "
                f"{sorted(missing)}"
            )

    @staticmethod
    def _validate_recipe(recipe: dict) -> None:
        """A recipe is {view, params} with flat JSON-scalar params; the same
        no-composite-score ban as card fields applies to param names (a recipe
        parameterises a view the user could open themselves — it must never
        smuggle a conclusion)."""
        if "view" not in recipe or set(recipe.keys()) - {"view", "params"}:
            raise CardSchemaError("recipe must be {'view': str, 'params': dict}")
        if not isinstance(recipe["view"], str) or not recipe["view"]:
            raise CardSchemaError("recipe.view must be a non-empty string")
        params = recipe.get("params", {})
        if not isinstance(params, dict):
            raise CardSchemaError("recipe.params must be a dict")
        for k, v in params.items():
            name = str(k).lower()
            if name in _BANNED_FIELD_NAMES or any(
                frag in name for frag in _BANNED_FIELD_FRAGMENTS
            ):
                raise CardSchemaError(
                    f"recipe param {k!r}: score/verdict-shaped names are forbidden"
                )
            if v is not None and not isinstance(v, (str, int, float, bool)):
                raise CardSchemaError(
                    f"recipe param {k!r} must be a JSON scalar (got {type(v).__name__})"
                )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            # Optional translatable title (S4.5): the fixed template + its data vars.
            # The UI renders OOI18N.tf(title_i18n, title_vars) when present, else the
            # English ``title`` above (additive; absent for cards without one).
            "title_i18n": self.title_i18n,
            "title_vars": self.title_vars,
            "summary": self.summary,
            "bucket": self.bucket,
            "signal": self.signal,
            "method": self.method,
            "caveat": self.caveat,
            "evidence": self.evidence,
            # The full article set behind a set-based card (exact analysis-window
            # corpus). Empty for keyword/topic/whole-corpus cards. Never a score.
            "article_ids": self.article_ids,
            "n": self.n,
            # The within-type identity (often the keyword/term the card is about);
            # the UI uses it as a fallback seed when a card is clicked to open the
            # analysis window over the card's article selection. Never a score.
            "key": self.key,
            "created_at": self.created_at,
            "dismissible": self.dismissible,
            "recipe": self.recipe,
            "trigger": self.trigger,
        }


# Enforce the §6 ban the moment this module is imported — not only under test.
assert_no_score_fields(Card)
