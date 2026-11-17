"""Suggested predictions in a stored IPCC Summary for Policymakers, for the operator to curate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row 121 (0.6 gate row A, register ruling G4 = default: "operator-curated prediction extraction from
a suggested list"). THE APP SUGGESTS, THE OPERATOR DECIDES:

  * a sentence is SUGGESTED by its wording alone: it carries one of the IPCC's calibrated likelihood
    or confidence terms AND a future-looking word (``projected``, ``will``, a year after the report's
    approval, a scenario name). The cues that fired travel with every suggestion, so the reason is on
    the row and nothing is a score;
  * nothing is stored until a person keeps a sentence or sets it aside (``IpccPrediction``). A
    suggestion nobody looked at is recomputed from the stored text every time, never written down as
    if it were a finding;
  * the sentence text a decision stores is the app's own copy of the stored report, never text a
    caller sent: a decision names a suggestion by its hash and the server looks the sentence up.

The method is deterministic (same text, same suggestions, same order), local (the text is the copy
already in the corpus; no request leaves the machine) and versioned (:data:`METHOD_VERSION`), so a
kept sentence a later method no longer suggests stays kept and is shown as such.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

#: Bump when the cue lists or the sentence split change: the surface says which method suggested.
METHOD_VERSION = 1

#: Visible beside the list (translated ×12): the short caveat (R685: one short caveat stays visible).
CAVEAT = "Suggested by wording, not understood: you decide which sentences are predictions."
#: One click away (translated ×12): how a sentence comes to be suggested.
METHOD = (
    "A sentence is suggested when it carries one of the IPCC's calibrated likelihood or confidence "
    "terms (such as very likely or high confidence) and a future-looking word (projected, will, a "
    "year after the report's approval, a scenario name). The words that matched are shown on each "
    "row. Only the copy of the report stored in your corpus is read; nothing is sent anywhere."
)

#: A passage longer than this is almost always a table, a figure caption or a run of headings that
#: the PDF extraction joined, not one sentence. It is counted and said, never shown as a suggestion.
SENTENCE_MAX_CHARS = 1200
_SENTENCE_MIN_CHARS = 25

# The IPCC AR6 calibrated language (the uncertainty guidance note), longest first so that
# "very likely" is read as itself and never as a second, bare "likely".
_LIKELIHOOD_TERMS = (
    "about as likely as not",
    "exceptionally unlikely",
    "more likely than not",
    "extremely unlikely",
    "virtually certain",
    "extremely likely",
    "very unlikely",
    "very likely",
    "unlikely",
    "likely",
)
_LIKELIHOOD_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(t) for t in _LIKELIHOOD_TERMS) + r")(?![\w-])", re.IGNORECASE
)
_CONFIDENCE_RE = re.compile(r"(?<![\w-])((?:very\s+)?(?:low|medium|high)\s+confidence)(?![\w-])", re.IGNORECASE)

_FUTURE_WORDS_RE = re.compile(
    r"(?<![\w-])("
    r"projected|projections?|will|would|is\s+expected\s+to|are\s+expected\s+to|future|"
    r"near[\s-]term|mid[\s-]term|long[\s-]term|mid-century|end\s+of\s+the\s+(?:21st\s+)?century|"
    r"21st\s+century|scenarios?|pathways?|SSP\d-\d\.\d"
    r")(?![\w-])",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?<!\d)(2\d{3})(?!\d)")
_YEAR_CEILING = 2500  # a "year" past this is a figure, not a horizon

_HYPHEN_BREAK_RE = re.compile(r"(?<=[a-z])-\s*\n\s*(?=[a-z])")
_SPACE_RE = re.compile(r"\s+")
# A sentence ends at . ! or ? followed by space and something that starts one: a capital, a digit
# (a numbered statement) or an opening bracket. "e.g." and "i.e." are kept whole.
_SPLIT_RE = re.compile(r"(?<!\be\.g\.)(?<!\bi\.e\.)(?<=[.!?])\s+(?=[A-Z0-9(\[{])")


@dataclass(frozen=True)
class Suggestion:
    sentence: str
    hash: str
    position: int  # the sentence's place in the stored text, from 0: the list keeps the report's order
    likelihood: tuple[str, ...] = field(default=())
    confidence: tuple[str, ...] = field(default=())
    future: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict:
        return {
            "hash": self.hash,
            "sentence": self.sentence,
            "position": self.position,
            "cues": {
                "likelihood": list(self.likelihood),
                "confidence": list(self.confidence),
                "future": list(self.future),
            },
        }


@dataclass(frozen=True)
class Reading:
    suggestions: tuple[Suggestion, ...]
    sentences_read: int
    too_long: int  # passages over SENTENCE_MAX_CHARS, counted and not shown


def sentence_hash(sentence: str) -> str:
    """The identity of a sentence: SHA-256 of its whitespace-normalised text. Stable across installs."""
    return hashlib.sha256(_SPACE_RE.sub(" ", sentence).strip().encode("utf-8")).hexdigest()


def _sentences(text: str) -> list[str]:
    joined = _HYPHEN_BREAK_RE.sub("", text or "")
    flat = _SPACE_RE.sub(" ", joined).strip()
    if not flat:
        return []
    return [s.strip() for s in _SPLIT_RE.split(flat) if s.strip()]


def _unique(found: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for f in found:
        f = _SPACE_RE.sub(" ", f).strip()
        if f.lower() not in (o.lower() for o in out):
            out.append(f)
    return tuple(out)


def _future_cues(sentence: str, approved_year: int | None) -> tuple[str, ...]:
    found = [m.group(1) for m in _FUTURE_WORDS_RE.finditer(sentence)]
    if approved_year is not None:
        found += [y for y in _YEAR_RE.findall(sentence) if approved_year < int(y) <= _YEAR_CEILING]
    return _unique(found)


def suggest(text: str, approved: str | None) -> Reading:
    """Every sentence of ``text`` the wording rule suggests, in the report's order.

    ``approved`` is the catalog's ISO approval date; a year after it is a future-looking cue. With
    no approval date the year cue is not used at all, rather than guessed.
    """
    approved_year = int(approved[:4]) if approved and approved[:4].isdigit() else None
    out: list[Suggestion] = []
    seen: set[str] = set()
    too_long = 0
    sentences = _sentences(text)
    for pos, s in enumerate(sentences):
        if len(s) < _SENTENCE_MIN_CHARS:
            continue
        likelihood = _unique([m.group(1) for m in _LIKELIHOOD_RE.finditer(s)])
        confidence = _unique([m.group(1) for m in _CONFIDENCE_RE.finditer(s)])
        if not (likelihood or confidence):
            continue
        future = _future_cues(s, approved_year)
        if not future:
            continue
        if len(s) > SENTENCE_MAX_CHARS:
            too_long += 1
            continue
        h = sentence_hash(s)
        if h in seen:  # the same sentence twice in one report (a repeated box): one row
            continue
        seen.add(h)
        out.append(Suggestion(s, h, pos, likelihood, confidence, future))
    return Reading(tuple(out), len(sentences), too_long)
