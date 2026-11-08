"""Rule-based topic tagging against SKOS thesauri, and its measurement (C-L3, Q913, Q1146).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A topic is a LENS, never a verdict. :func:`tag_text` matches a thesaurus label as a whole-word
sequence in a title or provision and returns what matched and HOW, so nothing is hidden:

* ``exact``  -- a ``prefLabel`` that names one concept: a rule hit.
* ``approx`` -- marked ``≈``: the label is an ``altLabel``, or it names MORE than one concept in
  the SAME scheme (both concepts are returned, neither is picked). Perception, not judgment.

The classifier's module home (S06-02 S4, "record it") is ``src/catalog/topic_tagging.py``.
No network, no model. Whitespace-delimited scripts only (ar/de/en/es/fr/pt/ru); a language
written without spaces is reported by :func:`measure` as ``unsupported_languages``, never
silently scored as zero.

:func:`measure` scores the rules on a LABELLED SAMPLE and states the ≈ share. A figure whose
denominator is zero is ``None`` with a reason, never ``0``; every figure carries ``n``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

UNSEGMENTED_LANGUAGES = frozenset({"zh", "ja", "ko", "th", "my", "km", "lo"})

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

CAVEAT = (
    "Topics are assigned by label rules over titles and provisions: a lens, never a verdict. "
    "Marked ≈ are approximate (an alternative label, or a label shared by several concepts)."
)


def fold(text: str) -> tuple[str, ...]:
    """Case-folded NFKC word tokens; diacritics are kept (they separate real words)."""
    return tuple(_TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()))


@dataclass(frozen=True)
class Tag:
    scheme: str
    concept: str
    label: str
    lang: str
    tier: str  # "exact" | "approx"
    approx_reason: str | None  # None for exact; "alt_label" | "ambiguous_label"

    @property
    def approx(self) -> bool:
        return self.tier == "approx"


class Index:
    """Label -> concepts, per language, built once from loaded artifacts."""

    def __init__(self, artifacts: list[dict[str, Any]]):
        # (lang, tokens) -> list of (scheme, concept, label, is_pref)
        self.entries: dict[tuple[str, tuple[str, ...]], list[tuple[str, str, str, bool]]] = {}
        self.schemes: list[str] = []
        self.empty: list[str] = []
        for art in artifacts:
            scheme = art["scheme"]
            self.schemes.append(scheme)
            if not art.get("concepts"):
                self.empty.append(scheme)
            for uri, c in art.get("concepts", {}).items():
                for lang, label in c.get("pref", {}).items():
                    self._add(lang, label, scheme, uri, True)
                for lang, labels in c.get("alt", {}).items():
                    for label in labels:
                        self._add(lang, label, scheme, uri, False)
        self.max_len = max((len(k[1]) for k in self.entries), default=0)

    def _add(self, lang: str, label: str, scheme: str, uri: str, is_pref: bool) -> None:
        toks = fold(label)
        if toks:
            self.entries.setdefault((lang, toks), []).append((scheme, uri, label, is_pref))


def tag_text(text: str, lang: str, index: Index) -> list[Tag]:
    """Longest-match-first, non-overlapping label hits of ``text`` (in ``lang``)."""
    toks = fold(text)
    out: list[Tag] = []
    i = 0
    while i < len(toks):
        hit = None
        for n in range(min(index.max_len, len(toks) - i), 0, -1):
            hit = index.entries.get((lang, toks[i:i + n]))
            if hit:
                break
        if not hit:
            i += 1
            continue
        per_scheme: dict[str, set[str]] = {}
        for s, u, _l, _p in hit:
            per_scheme.setdefault(s, set()).add(u)
        for s, u, label, is_pref in hit:
            if len(per_scheme[s]) > 1:  # ambiguous WITHIN one scheme; the same word in two schemes is two exact tags
                reason: str | None = "ambiguous_label"
            elif not is_pref:
                reason = "alt_label"
            else:
                reason = None
            out.append(Tag(s, u, label, lang, "approx" if reason else "exact", reason))
        i += n
    best: dict[tuple[str, str], Tag] = {}
    for t in out:  # one tag per concept; an exact hit replaces an earlier ≈ one
        key = (t.scheme, t.concept)
        if key not in best or (best[key].approx and not t.approx):
            best[key] = t
    return list(best.values())


def _ratio(num: int, den: int, reason: str) -> dict[str, Any]:
    return {"value": num / den, "n": den} if den else {"value": None, "n": 0, "reason": reason}


def measure(sample: list[dict[str, Any]], index: Index) -> dict[str, Any]:
    """Score the rules on a labelled sample ``[{id, lang, text, expected: [concept uri, ...]}]``.

    Reports, each with ``n``: ``tagged_share`` (items given at least one tag),
    ``approx_share`` (of ALL assigned tags, the share marked ≈), precision overall and for the
    exact and ≈ tiers separately, and recall of the expected concepts. Items in an unsegmented
    language are counted in ``unsupported_languages`` and left out of every ratio.
    """
    unsupported: dict[str, int] = {}
    scored = 0
    tagged = 0
    assigned = approx_assigned = 0
    tp = {"all": 0, "exact": 0, "approx": 0}
    n_tier = {"all": 0, "exact": 0, "approx": 0}
    expected_total = expected_found = 0
    for item in sample:
        lang = item["lang"]
        if lang in UNSEGMENTED_LANGUAGES:
            unsupported[lang] = unsupported.get(lang, 0) + 1
            continue
        scored += 1
        tags = tag_text(item["text"], lang, index)
        expected = set(item.get("expected", []))
        got = {t.concept for t in tags}
        if tags:
            tagged += 1
        expected_total += len(expected)
        expected_found += len(expected & got)
        for t in tags:
            assigned += 1
            approx_assigned += t.approx
            right = t.concept in expected
            for key in ("all", t.tier):
                n_tier[key] += 1
                tp[key] += right
    return {
        "n_items": scored,
        "unsupported_languages": unsupported,
        "tagged_share": _ratio(tagged, scored, "no scored items"),
        "approx_share": _ratio(approx_assigned, assigned, "no tags were assigned"),
        "precision": _ratio(tp["all"], n_tier["all"], "no tags were assigned"),
        "precision_exact": _ratio(tp["exact"], n_tier["exact"], "no exact tags were assigned"),
        "precision_approx": _ratio(tp["approx"], n_tier["approx"], "no ≈ tags were assigned"),
        "recall": _ratio(expected_found, expected_total, "the sample expects no concept"),
        "schemes": index.schemes,
        "schemes_without_concepts": index.empty,
        "method": "whole-word label match (longest first) over the text, per language; "
                  "alt labels and labels shared by several concepts are marked ≈",
        "caveat": CAVEAT + " The sample's size and choice bound what these figures mean.",
    }


def asdicts(tags: list[Tag]) -> list[dict[str, Any]]:
    return [asdict(t) | {"approx": t.approx} for t in tags]
