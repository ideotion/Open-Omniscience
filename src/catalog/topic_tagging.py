"""Rule-based topic tagging against SKOS thesauri, and its measurement (C-L3, Q913, Q1146).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A topic is a LENS, never a verdict. :func:`tag_text` matches a thesaurus label as a whole-word
sequence in a title or provision and returns what matched and HOW, so nothing is hidden:

* ``exact``  -- a ``prefLabel`` that names one concept: a rule hit.
* ``approx`` -- marked ``≈``: the label is an ``altLabel``, or it names MORE than one concept in
  the SAME scheme (both concepts are returned, neither is picked). Perception, not judgment.

* ``approx`` with reason ``unsegmented_substring`` (R680, OPEN_QUEUE 38(d)): in a language of
  ``UNSEGMENTED_LANGUAGES`` (zh, ja, th, my, km, lo; and ko, which does space its words but is
  kept in the set conservatively) a word boundary cannot be checked, so a
  label is matched as a SUBSTRING of a run of text, and EVERY such hit is ≈, whatever the
  label. A one-character label is never matched there: it would hit inside unrelated words.
  "One character" counts letters, not combining marks. A label with inner punctuation or a space
  (情報・通信) is found only where the text writes it joined (情報通信), since a match never crosses
  one; such labels are counted so the narrower reach is visible.

* R690: combining marks and joiners belong to their word in every script (a vowel sign or a virama
  never splits a Hindi or Bengali word, a haraka never splits an Arabic one). A language in
  ``UNVERIFIED_LANGUAGES`` is not tagged at all until a test shows its matching works: its items count
  as unsupported, never as a precision figure. In a language without spaces a substring hit must also
  start and end on a syllable edge (never cutting off a vowel sign, a Thai or Lao vowel letter
  written after its consonant, a Burmese final closed by asat, a stacked consonant or a vowel written
  before its consonant); that is what took Khmer, Lao and Burmese out of that set. It does not
  find WORD edges: a label can still match across two syllables of different words, which is why every
  such hit stays ≈.

The classifier's module home (S06-02 S4, "record it") is ``src/catalog/topic_tagging.py``.
No network, no model. An item in a language no loaded scheme carries a single label for is
reported by :func:`measure` as ``unsupported_languages``, never silently scored as zero.

:func:`measure` scores the rules on a LABELLED SAMPLE and states the ≈ share. A figure whose
denominator is zero is ``None`` with a reason, never ``0``; every figure carries ``n``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

UNSEGMENTED_LANGUAGES = frozenset({"zh", "ja", "ko", "th", "my", "km", "lo"})

#: R690(3)/(4): languages whose matching no test shows working yet. Their labels never make the language
#: taggable, so a sample item in one is counted as unsupported and no precision figure is published for it.
#: A language leaves this set only with a test that matches real words of its script. Khmer, Lao and
#: Burmese left it with the syllable-edge rule below and tests on real words (tests/test_topic_sample.py).
UNVERIFIED_LANGUAGES: frozenset[str] = frozenset()

# A substring hit in a language without spaces must start and end on a syllable edge (R690 follow-up):
# - never end right before a combining mark (a vowel sign, a final-consonant mark, a tone mark) that
#   belongs to the syllable the match would cut;
# - never start right after a stacking sign (Khmer coeng U+17D2, Burmese virama U+1039), which binds the
#   next consonant to the one before it;
# - never start right after, or end on, a vowel written before its consonant (Thai U+0E40-U+0E44,
#   Lao U+0EC0-U+0EC4), which belongs to the following syllable;
# - never end right before a Thai or Lao vowel written AFTER its consonant as a plain letter (category
#   Lo, not a mark: Thai U+0E30, U+0E32, U+0E45, Lao U+0EB0, U+0EB2);
# - never end right before a Burmese consonant closed by asat (U+103A), which is that syllable's final.
# A variation selector (U+FE00-U+FE0F, U+E0100-U+E01EF) is a mark by category but picks a glyph, never a
# syllable, so it does not count as one.
_STACKERS = frozenset({"\u17d2", "\u1039"})
_LEADING_VOWELS = frozenset(chr(c) for c in (*range(0x0E40, 0x0E45), *range(0x0EC0, 0x0EC5)))
_TRAILING_VOWEL_LETTERS = frozenset({"\u0e30", "\u0e32", "\u0e45", "\u0eb0", "\u0eb2"})
_ASAT = "\u103a"


def _is_variation_selector(ch: str) -> bool:
    c = ord(ch)
    return 0xFE00 <= c <= 0xFE0F or 0xE0100 <= c <= 0xE01EF

# Optional in ordinary writing, so dropped before tokenizing (never a boundary): a text that carries them
# and a label that does not are the same word. Arabic harakat, tanwin, shadda, sukun, superscript alef and
# tatweel; Hebrew points and cantillation (U+0591-U+05C7 minus the maqaf and the punctuation in that block);
# the zero-width joiner and non-joiner, which Persian and Indic text uses or omits for the same word.
_OPTIONAL = frozenset(
    chr(c)
    for c in (
        *range(0x064B, 0x0653), 0x0670, 0x0640,
        *(c for c in range(0x0591, 0x05C8) if c not in (0x05BE, 0x05C0, 0x05C3, 0x05C6)),
        0x200C, 0x200D,
    )
)

CAVEAT = (
    "Topics are assigned by label rules over titles and provisions: a lens, never a verdict. "
    "Marked ≈ are approximate (an alternative label, a label shared by several concepts, or a label found inside "
    "text written without spaces between words)."
)


def _in_word(ch: str) -> bool:
    """A letter or digit, or a combining mark (Mn, Mc, Me): both belong to the word (R690(1)).

    ``[^\\W_]+`` alone split a word at every vowel sign and virama (Devanagari, Bengali, Thai) and at every
    Arabic haraka, because marks are not alphanumeric: मनुष्य ("human") folded to मन + ुष + ्य, so the label
    मन ("mind") matched inside it as an EXACT whole word.
    """
    return ch.isalnum() or unicodedata.category(ch)[0] == "M"


def fold(text: str) -> tuple[str, ...]:
    """Case-folded NFKC word tokens; diacritics and combining marks stay with their letters."""
    words: list[str] = []
    cur: list[str] = []
    for ch in unicodedata.normalize("NFKC", text).casefold():
        if ch in _OPTIONAL:
            continue
        if _in_word(ch):
            if cur or ch.isalnum():  # a stray mark with no letter before it starts no word
                cur.append(ch)
        elif cur:
            words.append("".join(cur))
            cur = []
    if cur:
        words.append("".join(cur))
    return tuple(words)


def _base_letters(s: str) -> int:
    """Letters and digits, not counting marks: one Khmer or Devanagari syllable is several code points."""
    return sum(1 for c in s if c.isalnum())


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
        # unsegmented languages: (lang, label string) -> the same entries, matched as substrings (R680)
        self.substrings: dict[tuple[str, str], list[tuple[str, str, str, bool]]] = {}
        self.languages: set[str] = set()
        #: per unsegmented language, the one-character labels never matched (R680), counted so they do not vanish
        self.short_labels: dict[str, int] = {}
        #: per unsegmented language, the labels with inner punctuation or a space, matched only written joined
        self.split_labels: dict[str, int] = {}
        #: per language of UNVERIFIED_LANGUAGES, the labels set aside (R690(3)), counted so they do not vanish
        self.unverified_labels: dict[str, int] = {}
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
        self.max_chars = max((len(k[1]) for k in self.substrings), default=0)

    def _add(self, lang: str, label: str, scheme: str, uri: str, is_pref: bool) -> None:
        toks = fold(label)
        if not toks:
            return
        if lang in UNVERIFIED_LANGUAGES:  # R690(3): never taggable until a test shows it works
            self.unverified_labels[lang] = self.unverified_labels.get(lang, 0) + 1
            return
        if lang in UNSEGMENTED_LANGUAGES:
            key = "".join(toks)
            if len(toks) > 1:
                # 情報・通信, 국제 관계: a match never crosses punctuation or space, so the label is found only
                # where the text writes it joined (情報通信, 국제관계). Counted, so the narrower reach is visible.
                self.split_labels[lang] = self.split_labels.get(lang, 0) + 1
            if _base_letters(key) < 2:  # never matched, so it does not make the language taggable either
                self.short_labels[lang] = self.short_labels.get(lang, 0) + 1
                return
            self.languages.add(lang)
            self.substrings.setdefault((lang, key), []).append((scheme, uri, label, is_pref))
            return
        self.languages.add(lang)
        self.entries.setdefault((lang, toks), []).append((scheme, uri, label, is_pref))


def _on_syllable_edges(run: str, start: int, end: int) -> bool:
    """True when ``run[start:end]`` neither cuts a syllable at its start nor at its end."""
    if start > 0 and (run[start - 1] in _STACKERS or run[start - 1] in _LEADING_VOWELS):
        return False
    if run[end - 1] in _STACKERS or run[end - 1] in _LEADING_VOWELS:
        return False
    if end >= len(run):
        return True
    nxt = run[end]
    if nxt in _TRAILING_VOWEL_LETTERS or (end + 1 < len(run) and run[end + 1] == _ASAT):
        return False
    return not (unicodedata.category(nxt)[0] == "M" and not _is_variation_selector(nxt))


def _substring_hits(text: str, lang: str, index: Index) -> list[tuple[str, str, str, bool]]:
    """Longest-first, non-overlapping label hits inside each run of text, never across punctuation or space (R680)."""
    hits: list[tuple[str, str, str, bool]] = []
    for run in fold(text):
        i = 0
        while i < len(run):
            for n in range(min(index.max_chars, len(run) - i), 1, -1):
                hit = index.substrings.get((lang, run[i:i + n]))
                if hit and _on_syllable_edges(run, i, i + n):
                    hits.extend(hit)
                    i += n
                    break
            else:
                i += 1
    return hits


def tag_text(text: str, lang: str, index: Index) -> list[Tag]:
    """Longest-match-first, non-overlapping label hits of ``text`` (in ``lang``)."""
    out: list[Tag] = []
    if lang in UNSEGMENTED_LANGUAGES:
        for s, u, label, _p in _substring_hits(text, lang, index):
            out.append(Tag(s, u, label, lang, "approx", "unsegmented_substring"))
        return _one_per_concept(out)
    toks = fold(text)
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
    return _one_per_concept(out)


def _one_per_concept(out: list[Tag]) -> list[Tag]:
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
    exact and ≈ tiers separately, and recall of the expected concepts. Items in a language no
    loaded scheme carries a label for are counted in ``unsupported_languages`` and left out of
    every ratio; an unsegmented language that does carry labels is scored, every hit ≈ (R680).
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
        if lang not in index.languages:
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
        "one_character_labels_skipped": dict(index.short_labels),
        "labels_matched_only_when_written_joined": dict(index.split_labels),
        "unverified_languages": {
            "labels_set_aside": dict(index.unverified_labels),
            "reason": "no test yet shows this script's words are matched correctly, so no figure is given (R690)",
        },
        "method": "whole-word label match (longest first) over the text, per language; "
                  "alt labels and labels shared by several concepts are marked ≈; in a language written "
                  "without spaces a label of two or more characters is matched inside a run of text, only "
                  "where it starts and ends on a syllable edge, and every such hit is ≈ (R680, R690)",
        "caveat": CAVEAT + " The sample's size and choice bound what these figures mean.",
    }


def resolve_sample(sample: list[dict[str, Any]], artifact: dict[str, Any], *, label_lang: str = "en") -> dict[str, Any]:
    """Turn a sample labelled by PREFERRED LABEL into one labelled by concept, against ONE loaded thesaurus.

    The labelled sample (``src/catalog/data/topic_sample_law_titles.json``) names each expected topic by the thesaurus's
    own preferred label in ``label_lang`` (``expected_labels``), because the concept ids are the thesaurus's and are not
    in the tree until the operator builds it. A label the artifact does not carry is NEVER matched loosely: it is listed in
    ``unresolved`` and left out of the item's expected set, so a guess cannot pass for a label. Returns
    ``{"sample": [...as measure() takes it], "unresolved": [{"id", "label"}], "resolved": n, "other_schemes": {scheme: n}}``;
    ``other_schemes`` counts the expected labels written for another thesaurus, so a scheme-name mismatch is visible
    rather than silently resolving nothing.
    """
    scheme = artifact.get("scheme")
    by_label: dict[str, list[str]] = {}
    for uri, c in (artifact.get("concepts") or {}).items():
        label = (c.get("pref") or {}).get(label_lang)
        if label:
            by_label.setdefault(" ".join(fold(label)), []).append(uri)
    out: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    resolved = 0
    other: dict[str, int] = {}
    for item in sample:
        expected: list[str] = []
        for want in item.get("expected_labels") or []:
            if want.get("scheme") != scheme:
                key = str(want.get("scheme"))
                other[key] = other.get(key, 0) + 1
                continue
            uris = by_label.get(" ".join(fold(want.get("label", ""))), [])
            if len(uris) == 1:
                expected.append(uris[0])
                resolved += 1
            else:  # absent, or a preferred label two concepts share: either way not one concept
                unresolved.append({"id": item["id"], "label": want.get("label", "")})
        out.append({"id": item["id"], "lang": item["lang"], "text": item["text"], "expected": expected})
    return {"sample": out, "unresolved": unresolved, "resolved": resolved, "other_schemes": other}


def asdicts(tags: list[Tag]) -> list[dict[str, Any]]:
    return [asdict(t) | {"approx": t.approx} for t in tags]
