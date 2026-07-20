"""Keyword families: group surface variants of one entity into a canonical family.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The store keeps every surface form as its own keyword (``Trump``, ``Trump's``,
``Donald Trump``, ``President Donald Trump`` are four rows). That fragments the
mind-map and the trend counts. This module groups those variants into one family
for *display* — it never deletes or rewrites the stored rows, and every family
lists its members, so the grouping is transparent and reversible (the user can
later split it). Honest by construction: a family is an "these look like the same
thing" assertion from cheap, explainable rules, never ground truth.

Rules (deterministic, no ML):
  * **Possessive collapse** — ``trump's`` / ``trump'`` → ``trump`` (any kind).
  * **Honorific stripping** — a leading title (``president``, ``mr``, ``dr`` …) is
    dropped when matching, so ``president donald trump`` ≡ ``donald trump``.
  * **Containment (entities only, same kind)** — a shorter name that is a
    *contiguous* token-run of a longer name of the **same kind** joins it
    (``trump`` ⊂ ``donald trump`` ⊂ ``president donald trump``). The same-kind
    guard avoids false merges like ``Paris`` (location) into ``Paris Hilton``
    (person). Plain topical terms are never subsumed (``climate`` ≠ ``climate
    policy``) — only possessive-collapsed.

The canonical label is the most complete member (most tokens), tie-broken by
mentions. Mentions are summed (a real total); article counts are reported as the
largest member's (an honest lower bound — summing would double-count an article
that mentions two variants).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

try:  # optional ([analysis] extra); display-time lemmatization degrades to a no-op when absent
    import simplemma as _simplemma
except Exception:  # noqa: BLE001 - a core install runs without it
    _simplemma = None  # type: ignore[assignment]

_POSS_APOS_S = re.compile(r"['’]s$")  # trailing 's  -> drop two chars
_POSS_S_APOS = re.compile(r"['’]$")  # trailing '   -> drop the apostrophe only

_HONORIFICS: frozenset[str] = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "mx",
        "dr",
        "sir",
        "dame",
        "lord",
        "lady",
        "prof",
        "professor",
        "president",
        "vice",
        "vp",
        "senator",
        "sen",
        "representative",
        "rep",
        "governor",
        "gov",
        "mayor",
        "minister",
        "chancellor",
        "king",
        "queen",
        "prince",
        "princess",
        "pope",
        "general",
        "gen",
        "colonel",
        "col",
        "captain",
        "capt",
        "sergeant",
        "sgt",
        "ceo",
        "cfo",
        "cto",
        "chairman",
        "chairwoman",
        "chair",
        "director",
        "secretary",
        "saint",
        "st",
    }
)


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def _strip_possessive_token(tok: str) -> str:
    if _POSS_APOS_S.search(tok):
        return tok[:-2] or tok
    if _POSS_S_APOS.search(tok):
        return tok[:-1] or tok
    return tok


def canonical_key(normalized: str) -> str:
    """A stronger dedup key: collapse a trailing possessive on the last token."""
    parts = (normalized or "").split()
    if parts:
        parts[-1] = _strip_possessive_token(parts[-1])
    return " ".join(parts)


def strip_honorifics(normalized: str) -> str:
    """Drop leading honorific tokens (after possessive collapse) for name matching."""
    parts = canonical_key(normalized).split()
    while len(parts) > 1 and parts[0] in _HONORIFICS:
        parts.pop(0)
    return " ".join(parts)


def _is_contiguous_sub(short_toks: list[str], long_toks: list[str]) -> bool:
    n, m = len(short_toks), len(long_toks)
    if n == 0 or n >= m:
        return False
    return any(long_toks[i : i + n] == short_toks for i in range(m - n + 1))


# Bases where the plural is a DISTINCT concept, so a plural must NOT collapse into
# it (mean/means, right/rights, force/forces). Evidence-based + log-tunable, like
# the stoplists — start small, grow from the keyword-diagnostics logs. The scariest
# pairs (new/news, use/uses) never even arise: their singular is a stopword, so it
# is never a keyword (verified on the 2026-06-14 log).
_PLURAL_DENYLIST: frozenset[str] = frozenset(
    {
        "mean", "good", "arm", "custom", "spirit", "content", "saving", "work",
        "force", "right", "new", "use", "glass", "paper", "draft", "ground",
        "letter", "minute", "second", "people",
    }
)


def _plural_bases(norm: str) -> list[str]:
    """Candidate singular stems of a REGULAR plural, most-likely first (or []).

    Conservative + English/Romance-shaped: -ies→-y (cities→city), -es→strip
    (boxes→box), -s→strip (states→state, never -ss). Length-guarded. The caller
    only merges when a candidate ALSO exists as a same-kind term keyword, so a
    non-applicable language (a German -s that isn't a plural) won't false-merge
    unless its "singular" happens to be a real keyword too."""
    out: list[str] = []
    if norm.endswith("ies") and len(norm) >= 5:
        out.append(norm[:-3] + "y")  # cities -> city
    if norm.endswith("es") and len(norm) >= 6:
        base = norm[:-2]
        # -es is the plural suffix ONLY when the base ends in a sibilant
        # (boxes->box, buses->bus, quizzes->quiz, churches->church, dishes->dish)
        # or -o (heroes->hero, potatoes->potato). For "states" the -es base would
        # be "stat" (ends 't') — NOT a real -es plural, so don't offer it; the -s
        # rule below correctly gives "state". Field log 2026-06-17: "states"
        # wrongly merged into a stray "stat" keyword instead of "state" because the
        # bogus -es candidate was tried first and that junk stem happened to exist.
        if base[-1:] in ("s", "x", "z", "o") or base[-2:] in ("ch", "sh"):
            out.append(base)
    if norm.endswith("s") and not norm.endswith("ss") and len(norm) >= 5:
        out.append(norm[:-1])  # states -> state, horses -> horse
    return out


# simplemma languages we lemmatize — the UI/corpus languages it handles well. Unsegmented
# scripts (zh/ja) and languages simplemma covers poorly are deliberately excluded -> no-op
# (a wrong lemma is worse than none, same discipline as the de-US-centring country work).
_LEMMA_LANGS: frozenset[str] = frozenset(
    {"en", "fr", "de", "es", "it", "pt", "nl", "ru", "id"}
)

# Norms whose lemma CHANGES the meaning for a news corpus, so they must NOT be lemmatized:
# media->medium, data->datum, us->we, plus a few stopword-ish flatteners. Evidence-grown +
# log-tunable, exactly like _PLURAL_DENYLIST — start small, grow from the keyword logs.
_MISLEMMA_DENYLIST: frozenset[str] = frozenset(
    {"media", "data", "us", "good", "better", "was", "be", "left", "right"}
)


def _lemma_enabled() -> bool:
    """Display-time lemmatization is ON BY DEFAULT (ruled 2026-07-18). It changes keyword
    grouping app-wide, so the measure-before-trust gate held it off until its retrieval
    impact was assessed — lemmatization is a DISPLAY-layer families change (never touches
    the stored index), which is invisible to the FTS retrieval harness, so an IR-gold-set
    A/B was never the coherent measurement for it. The coherent gate was a PRECISION
    review of the candidate merges: the maintainer ran the ``lemma_preview`` instrument
    over the live ~500k-article corpus (top 500 keywords -> 35 candidate groups / 71
    keywords) and found it clean (regular plurals + verb forms/irregulars only; nothing
    meaning-changing). Opt OUT with ``OO_FAMILY_LEMMA=0`` (a core install without the
    optional ``simplemma`` still no-ops regardless of this default)."""
    return _simplemma is not None and os.getenv("OO_FAMILY_LEMMA", "1") == "1"


def _lemma(norm: str, lang: str | None) -> str:
    """The lemma of a SINGLE-token term in a supported language, else ``norm`` unchanged.

    Reversible by construction (display only — the stored keyword index is never touched)
    and conservative: a multi-token form, an unsupported/unknown language, a denylisted
    norm, a missing ``simplemma``, or any lemmatizer error all fall back to ``norm``. The
    caller only UNIONs terms that share a lemma, so a no-op simply leaves a term standalone."""
    if not norm or " " in norm:
        return norm
    lg = (lang or "").lower()
    if _simplemma is None or lg not in _LEMMA_LANGS or norm in _MISLEMMA_DENYLIST:
        return norm
    try:
        return (_simplemma.lemmatize(norm, lg) or norm).casefold()
    except Exception:  # noqa: BLE001 - never let a lemmatizer hiccup break grouping
        return norm


@dataclass
class Family:
    canonical: str  # display label (the most complete member)
    normalized: str  # canonical dedup key
    kind: str
    mentions: int = 0
    articles: int = 0
    manual: bool = False  # True if a user override shaped this family
    members: list[dict] = field(default_factory=list)
    conflated_by: list[str] = field(default_factory=list)  # e.g. ["lemma"] — visible provenance

    @property
    def variant_count(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict:
        return {
            "term": self.canonical,
            "normalized": self.normalized,
            "kind": self.kind,
            "mentions": self.mentions,
            "articles": self.articles,
            "variants": self.variant_count,
            "manual": self.manual,
            "conflated_by": self.conflated_by,
            "members": [
                {
                    "term": m.get("term"),
                    "normalized": m.get("normalized"),
                    "mentions": int(m.get("mentions", 0) or 0),
                }
                for m in self.members
            ],
        }


def build_families(items: list[dict], overrides: dict[str, dict] | None = None) -> list[Family]:
    """Group keyword rows into families. ``items`` carry normalized/term/kind/mentions
    (and optionally articles). Returns families sorted by total mentions, descending.

    ``overrides`` maps a normalised term to ``{"family_key", "label", "kind"}`` — a
    user's manual decision that is *authoritative* over the automatic rules: forms
    sharing a ``family_key`` are forced together (a merge), and a form keyed to its
    own normalised term is pinned standalone (a split). Overridden forms never take
    part in the automatic possessive/containment grouping.
    """
    overrides = overrides or {}
    recs = []
    for it in items:
        norm = it.get("normalized") or _norm(it.get("term", ""))
        recs.append(
            {
                "it": it,
                "norm": norm,
                "kind": it.get("kind", "term"),
                "ckey": canonical_key(norm),
                "match": strip_honorifics(norm).split(),
                "mentions": int(it.get("mentions", it.get("count", 0)) or 0),
                "articles": int(it.get("articles", 0) or 0),
                "lang": (it.get("language") or "").lower(),
                "lemma_merged": False,
                "ov": overrides.get(norm),
            }
        )

    parent = list(range(len(recs)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    auto = [i for i, r in enumerate(recs) if r["ov"] is None]

    # 1) Possessive / exact collapse: same (kind, canonical key) — auto items only.
    by_ckey: dict[tuple[str, str], int] = {}
    for i in auto:
        key = (recs[i]["kind"], recs[i]["ckey"])
        if key in by_ckey:
            union(by_ckey[key], i)
        else:
            by_ckey[key] = i

    # 1.5) Singular/plural collapse for single-token TERMS (auto only): a regular
    # -s/-es/-ies plural joins its singular family (state/states, country/countries)
    # ONLY when BOTH are plain terms (never entity NAMES — a name plural is a
    # different referent) and the base is not a known meaning-changer
    # (_PLURAL_DENYLIST). The base must EXIST as a same-kind term, so a non-plural
    # word that merely ends in -s won't merge unless its stem is also a real
    # keyword. Reversible via a split override; OO_FAMILY_PLURALS=0 disables.
    if os.getenv("OO_FAMILY_PLURALS", "1") != "0":
        term_by_norm: dict[str, int] = {}
        for i in auto:
            if recs[i]["kind"] == "term" and " " not in recs[i]["norm"]:
                term_by_norm.setdefault(recs[i]["norm"], i)
        for i in auto:
            if recs[i]["kind"] != "term" or " " in recs[i]["norm"]:
                continue
            for base in _plural_bases(recs[i]["norm"]):
                if base in _PLURAL_DENYLIST:
                    break
                j = term_by_norm.get(base)
                if j is not None and j != i:
                    union(j, i)  # plural i -> singular j (the base)
                    break

    # 1.6) Lemma collapse for single-token TERMS (auto only; ON BY DEFAULT since 2026-07-18
    # — see _lemma_enabled). Groups morphological variants a plural heuristic MISSES — verb
    # forms and irregulars (study/studied, run/running, child/children, mouse/mice) — via
    # simplemma, per (kind, language) so an en term never merges a fr one. Same guards as the
    # plural rule (terms only, never entity NAMES; a meaning-changing norm is denylisted;
    # reversible via a split override) PLUS a visible ``conflated_by=["lemma"]`` on the family.
    # OO_FAMILY_LEMMA=0 (or no simplemma) + this skip => byte-identical to the pre-lemma grouping.
    if _lemma_enabled():
        lemma_first: dict[tuple, int] = {}
        for i in auto:
            r = recs[i]
            if r["kind"] != "term" or " " in r["norm"]:
                continue
            lkey = (r["kind"], r["lang"], _lemma(r["norm"], r["lang"]))
            j = lemma_first.get(lkey)
            if j is None:
                lemma_first[lkey] = i
            elif j != i:
                union(j, i)  # variant i -> the lemma's representative j
                recs[i]["lemma_merged"] = True
                recs[j]["lemma_merged"] = True

    # 2) Containment among entities of the same kind (plain terms excluded) — auto only.
    # Guards added from the 2026-06-11 field log (the maintainer's first keyword
    # batch exposed transitive over-merges like security+national+social and
    # "Deep Dive: Iran" absorbing Israel):
    #   G-parent: only CLEAN phrases of 2–3 tokens may act as merge parents —
    #     headline-ish extractions (4+ tokens like "Climate Change and Cities",
    #     or anything containing :;"()') were the hubs that chained unrelated
    #     terms together in the field log.
    #   G-ambiguous: a SINGLE-token form joins only when, after the multi-token
    #     phrases have grouped among themselves, ALL the phrases containing it
    #     share one family. "trump" (only Donald-Trump-rooted parents) merges;
    #     "security" (national security / Social Security / Security Council…)
    #     is ambiguous and honestly stays standalone.
    _JUNK = re.compile(r"[:;()\"«»]|\.{3}")
    ents = [i for i in auto if recs[i]["kind"] != "term" and recs[i]["match"]]

    def _clean_parent(i: int) -> bool:
        return 2 <= len(recs[i]["match"]) <= 3 and not _JUNK.search(recs[i]["it"].get("term", ""))

    # Honorific equivalence merges DIRECTLY (President Donald Trump ≡ Donald
    # Trump): same stripped match + same kind. The old code relied on a shared
    # single token bridging them — the very mechanism the guards remove.
    by_match: dict[tuple, int] = {}
    for i in ents:
        key = (recs[i]["kind"], tuple(recs[i]["match"]))
        if key in by_match:
            union(by_match[key], i)
        else:
            by_match[key] = i

    multi = [i for i in ents if len(recs[i]["match"]) >= 2]
    for a in multi:  # phrase ⊂ longer phrase (both multi-token, parent clean)
        for b in multi:
            if a == b or recs[a]["kind"] != recs[b]["kind"] or not _clean_parent(b):
                continue
            if len(recs[a]["match"]) < len(recs[b]["match"]) and _is_contiguous_sub(
                recs[a]["match"], recs[b]["match"]
            ):
                union(b, a)
    singles = [i for i in ents if len(recs[i]["match"]) == 1]
    for a in singles:
        parents = {
            find(b)
            for b in multi
            if recs[a]["kind"] == recs[b]["kind"]
            and _clean_parent(b)
            and _is_contiguous_sub(recs[a]["match"], recs[b]["match"])
        }
        if len(parents) == 1:  # unambiguous → join; 0 or 2+ → stay standalone
            union(parents.pop(), a)

    # Final grouping: overridden forms group by family_key; the rest by auto-union.
    groups: dict[tuple, list[dict]] = {}
    for i, r in enumerate(recs):
        gkey = ("ov", r["ov"]["family_key"]) if r["ov"] else ("auto", find(i))
        groups.setdefault(gkey, []).append(r)

    families: list[Family] = []
    for gkey, members in groups.items():
        if gkey[0] == "ov":
            label = next((m["ov"].get("label") for m in members if m["ov"].get("label")), None)
            canon = max(members, key=lambda r: (len(r["match"]), r["mentions"]))
            canonical = label or canon["it"].get("term") or " ".join(canon["match"])
            normalized, kind, manual = gkey[1], canon["kind"], True
        else:
            def _label_rank(r):
                toks = len(r["match"])
                clean = 2 <= toks <= 4 and not _JUNK.search(r["it"].get("term", ""))
                return (clean, r["mentions"], min(toks, 3))

            canon = max(members, key=_label_rank)
            canonical = canon["it"].get("term") or " ".join(canon["match"])
            normalized, kind, manual = canon["ckey"], canon["kind"], False
        conflated_by = ["lemma"] if any(r.get("lemma_merged") for r in members) else []
        families.append(
            Family(
                canonical=canonical,
                normalized=normalized,
                kind=kind,
                manual=manual,
                mentions=sum(r["mentions"] for r in members),
                articles=max((r["articles"] for r in members), default=0),
                members=[r["it"] for r in members],
                conflated_by=conflated_by,
            )
        )
    families.sort(key=lambda f: -f.mentions)
    return families
