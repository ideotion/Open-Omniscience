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

import re
from dataclasses import dataclass, field

_POSS_APOS_S = re.compile(r"['’]s$")   # trailing 's  -> drop two chars
_POSS_S_APOS = re.compile(r"['’]$")     # trailing '   -> drop the apostrophe only

_HONORIFICS: frozenset[str] = frozenset({
    "mr", "mrs", "ms", "mx", "dr", "sir", "dame", "lord", "lady", "prof", "professor",
    "president", "vice", "vp", "senator", "sen", "representative", "rep", "governor",
    "gov", "mayor", "minister", "chancellor", "king", "queen", "prince", "princess",
    "pope", "general", "gen", "colonel", "col", "captain", "capt", "sergeant", "sgt",
    "ceo", "cfo", "cto", "chairman", "chairwoman", "chair", "director", "secretary",
    "saint", "st",
})


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
    return any(long_toks[i:i + n] == short_toks for i in range(m - n + 1))


@dataclass
class Family:
    canonical: str            # display label (the most complete member)
    normalized: str           # canonical dedup key
    kind: str
    mentions: int = 0
    articles: int = 0
    members: list[dict] = field(default_factory=list)

    @property
    def variant_count(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict:
        return {
            "term": self.canonical, "normalized": self.normalized, "kind": self.kind,
            "mentions": self.mentions, "articles": self.articles,
            "variants": self.variant_count,
            "members": [
                {"term": m.get("term"), "normalized": m.get("normalized"),
                 "mentions": int(m.get("mentions", 0) or 0)}
                for m in self.members
            ],
        }


def build_families(items: list[dict]) -> list[Family]:
    """Group keyword rows into families. ``items`` carry normalized/term/kind/mentions
    (and optionally articles). Returns families sorted by total mentions, descending.
    """
    recs = []
    for it in items:
        norm = it.get("normalized") or _norm(it.get("term", ""))
        recs.append({
            "it": it, "kind": it.get("kind", "term"),
            "ckey": canonical_key(norm),
            "match": strip_honorifics(norm).split(),
            "mentions": int(it.get("mentions", it.get("count", 0)) or 0),
            "articles": int(it.get("articles", 0) or 0),
        })

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

    # 1) Possessive / exact collapse: same (kind, canonical key).
    by_ckey: dict[tuple[str, str], int] = {}
    for i, r in enumerate(recs):
        key = (r["kind"], r["ckey"])
        if key in by_ckey:
            union(by_ckey[key], i)
        else:
            by_ckey[key] = i

    # 2) Containment among entities of the same kind (plain terms excluded).
    ents = [i for i, r in enumerate(recs) if r["kind"] != "term" and r["match"]]
    for a in ents:
        for b in ents:
            if a == b or recs[a]["kind"] != recs[b]["kind"]:
                continue
            if len(recs[a]["match"]) < len(recs[b]["match"]) and \
                    _is_contiguous_sub(recs[a]["match"], recs[b]["match"]):
                union(b, a)  # shorter (a) joins the more complete (b)

    groups: dict[int, list[dict]] = {}
    for i in range(len(recs)):
        groups.setdefault(find(i), []).append(recs[i])

    families: list[Family] = []
    for members in groups.values():
        canon = max(members, key=lambda r: (len(r["match"]), r["mentions"]))
        families.append(Family(
            canonical=canon["it"].get("term") or " ".join(canon["match"]),
            normalized=canon["ckey"],
            kind=canon["kind"],
            mentions=sum(r["mentions"] for r in members),
            articles=max((r["articles"] for r in members), default=0),
            members=[r["it"] for r in members],
        ))
    families.sort(key=lambda f: -f.mentions)
    return families
