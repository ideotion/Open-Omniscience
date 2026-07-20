"""Cross-language keyword equivalence — merge curated rings into grouped views.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``configs/keyword_equivalents.yml`` curates language-qualified rings — e.g.
``election`` = {en:election, en:elections, fr:élection, fr:élections, de:wahl,
es:elección, pt:eleição, id:pemilu}. This module is the LIVE consumer the rings
file always lacked: in grouped analytics (top terms, associations / mind-map,
the family & keyword graph) the members of one ring collapse into a single
concept, so ``election`` is one row instead of eight per-language fragments.

HONESTY BY CONSTRUCTION (the maintainer's standing rules for this feature):
  * **Language-qualified.** A ring member is ``lang:term``; ``fr:main`` (hand)
    must never pull in the English adjective ``main``. We match on
    (effective-language, normalized): the stored ``Keyword.language``, falling
    back to the dominant ``language_signature`` — a SIGNATURE-SUPPORTED join, so
    an en-dominant "main" stays out of the fr ``hand`` ring.
  * **Per-language counts stay visible.** A merged row carries every member with
    its own language + count (``language_breakdown``) — nothing is hidden, the
    sum is just presented as one concept.
  * **The user can split.** A ``KeywordFamilyOverride`` that pins a term
    standalone (a "split") removes it from its ring — the same mechanism that
    splits an auto-family.
  * **It groups, never invents.** Only members that actually exist in the corpus
    are merged; an empty/missing file is a no-op. ``OO_KEYWORD_EQUIV=0`` disables.

This module is pure (no DB): ``merge_equivalents`` operates on the row dicts the
grouping functions already produce, given a ``lang_of`` resolver the caller fills
from the DB. That keeps it unit-testable without a database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_equivalents.yml"
# Rings generated offline from Wikidata labels (scripts/generate_wikidata_rings.py).
# Read ALONGSIDE the curated file; a curated ring WINS on an id collision.
_GENERATED_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_rings_generated.yml"


@dataclass(frozen=True)
class Ring:
    id: str
    members: tuple[tuple[str, str], ...]  # (language, normalized_term)
    note: str | None = None

    @property
    def label(self) -> str:
        # Human label = the ring id with separators spaced (kept ASCII-stable).
        return self.id.replace("-", " ")


def _enabled() -> bool:
    return os.getenv("OO_KEYWORD_EQUIV", "1") != "0"


def _norm(term: str) -> str:
    return " ".join((term or "").split()).casefold()


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _parse_rings(data: dict) -> list[Ring]:
    """Pure: a ``{"rings": [...]}`` mapping -> the valid Rings (>=2 members)."""
    rings: list[Ring] = []
    for r in (data or {}).get("rings", []) or []:
        rid = str(r.get("id", "")).strip()
        members: list[tuple[str, str]] = []
        for m in r.get("members", []) or []:
            s = str(m).strip()
            if ":" not in s:
                continue
            lang, term = s.split(":", 1)
            lang, term = lang.strip().casefold(), _norm(term)
            if lang and term:
                members.append((lang, term))
        if rid and len(members) >= 2:  # a 1-member ring would merge nothing
            rings.append(Ring(id=rid, members=tuple(dict.fromkeys(members)), note=r.get("note")))
    return rings


@lru_cache(maxsize=1)
def load_rings() -> tuple[Ring, ...]:
    """Parse the curated + the Wikidata-generated ring files (cached).

    Missing/empty files -> no rings. The generated file is read FIRST and the
    curated file SECOND, so a hand-curated ring of the same id OVERRIDES the
    generated one (curation always wins)."""
    if not _enabled():
        return ()
    by_id: dict[str, Ring] = {}
    for ring in _parse_rings(_read_yaml(_GENERATED_PATH)) + _parse_rings(_read_yaml(_PATH)):
        by_id[ring.id] = ring
    return tuple(by_id.values())


@lru_cache(maxsize=1)
def _index() -> tuple[frozenset[str], dict[tuple[str, str], str], dict[str, Ring]]:
    """(all member terms, (lang,term)->ring_id, ring_id->Ring)."""
    terms: set[str] = set()
    by_lang_term: dict[tuple[str, str], str] = {}
    by_id: dict[str, Ring] = {}
    for ring in load_rings():
        by_id[ring.id] = ring
        for lang, term in ring.members:
            terms.add(term)
            by_lang_term[(lang, term)] = ring.id
    return frozenset(terms), by_lang_term, by_id


def is_ring_term(normalized: str) -> bool:
    """Cheap pre-filter: is this normalized term a member of ANY ring (any lang)?"""
    return _norm(normalized) in _index()[0]


def ring_terms() -> frozenset[str]:
    """All normalized member terms across all rings (for candidate pre-filtering)."""
    return _index()[0]


def ring_of(language: str | None, normalized: str) -> str | None:
    """The ring id for (effective-language, normalized), or None.

    Matching is language-qualified: a member ``fr:main`` only matches when the
    keyword's effective language is fr. An unknown language never matches (the
    caller is expected to resolve it from the signature first) — conservative by
    design, so we never fabricate a cross-language merge.

    DELIBERATELY case-insensitive (the 2026-07-18 "entity acronym" case seam):
    an entity keyword's normalized form is kept UPPERCASE (WHO != who, USA != usa
    — the acronym ruling), while ring members are written lowercase in the
    curated/generated config. ``_norm()`` casefolds BOTH the config member (at
    parse time, in ``_parse_rings``) and this lookup's ``normalized`` argument, so
    an all-caps entity form matches its lowercase-written ring member with no
    special-case code — verified end-to-end (USA/США/EUA/ABD one ring) in
    tests/test_keyword_equivalence.py.
    """
    if not language:
        return None
    return _index()[1].get((language.casefold(), _norm(normalized)))


def ring_meta(ring_id: str) -> Ring | None:
    return _index()[2].get(ring_id)


def ring_translation(ring_id: str, target_lang: str) -> str | None:
    """The VERIFIED translation of a ring into ``target_lang`` — the ring's member
    term in that language (Wikidata-QID-sourced), or None when the ring carries no
    member in that language. Works even when that member is not itself in the corpus,
    because a ring lists ALL its language members from the curated/generated table."""
    ring = ring_meta(ring_id)
    if not ring:
        return None
    tl = (target_lang or "").casefold()
    if not tl:
        return None
    for lang, term in ring.members:
        if lang.casefold() == tl:
            return term
    return None


def translate_term(language: str | None, normalized: str, target_lang: str) -> str | None:
    """Verified translation of one keyword into ``target_lang`` via its ring, or None.

    A keyword is translatable when it belongs to a cross-language ring that has a
    member in the target language. Language-qualified (so we never fabricate a
    translation from an ambiguous bare term); ``language`` is the keyword's effective
    language. Returns None for a same-language no-op (the target IS the source)."""
    tl = (target_lang or "").casefold()
    if not tl or (language or "").casefold() == tl:
        return None
    rid = ring_of(language, normalized)
    return ring_translation(rid, target_lang) if rid else None


def _is_split(overrides: dict[str, dict] | None, normalized: str) -> bool:
    """A user 'split' override pins a term to its own normalized key -> keep it out."""
    if not overrides:
        return False
    ov = overrides.get(normalized)
    return ov is not None and ov.get("family_key") == normalized


def group_rows(
    rows: list[dict],
    *,
    lang_of: Callable[[str], str | None],
    overrides: dict[str, dict] | None = None,
) -> list[tuple[str, Any]]:
    """Partition rows into ring groups, preserving first-seen order.

    Returns a list of ``("solo", row)`` (a non-member, a split-overridden term, or
    the lone present member of a ring) and ``("ring", (ring_id, [member rows]))``
    for rings with ≥2 members present. Each caller then aggregates its OWN fields
    (mentions, or cooccur/pmi, or recent/prior) over the member rows — the ring
    lookup + honesty rules (language-qualified, split-aware) live here once.
    """
    if not load_rings():
        return [("solo", r) for r in rows]
    groups: dict[str, list[dict]] = {}
    order: list[tuple[str, Any]] = []
    for row in rows:
        norm = row.get("normalized") or _norm(row.get("term", ""))
        rid = None if _is_split(overrides, norm) else ring_of(lang_of(norm), norm)
        if rid is None:
            order.append(("solo", row))
            continue
        if rid not in groups:
            groups[rid] = []
            order.append(("ring", rid))
        groups[rid].append(row)
    resolved: list[tuple[str, Any]] = []
    for kind, payload in order:
        if kind == "solo":
            resolved.append(("solo", payload))
        else:
            members = groups[payload]
            if len(members) == 1:
                resolved.append(("solo", members[0]))
            else:
                resolved.append(("ring", (payload, members)))
    return resolved


def merge_equivalents(
    rows: list[dict],
    *,
    lang_of: Callable[[str], str | None],
    overrides: dict[str, dict] | None = None,
    mention_key: str = "mentions",
    article_key: str = "articles",
) -> list[dict]:
    """Collapse rows whose (effective-language, normalized) share a ring.

    ``rows`` are the grouped dicts the analytics already produce (each has at
    least ``normalized`` and ``mention_key``; ``term``/``kind``/``article_key``/
    ``members`` optional). ``lang_of(normalized)`` returns the effective language
    (stored or signature-dominant) — the caller fills it from the DB.

    A merged row carries ``ring_id``, the summed ``mention_key``, an honest
    ``article_key`` (the max member's, never a double-counting sum), a visible
    ``language_breakdown`` {lang: mentions}, and ``members`` listing every member
    with its language. Non-members and split-overridden terms pass through
    untouched. Order is otherwise preserved (merged row takes its best member's
    position) so the caller's ranking is respected.
    """
    out: list[dict] = []
    for kind, payload in group_rows(rows, lang_of=lang_of, overrides=overrides):
        if kind == "solo":
            out.append(payload)
        else:
            ring_id, members = payload
            out.append(_merge_group(ring_id, members, lang_of, mention_key, article_key))
    return out


def _merge_group(
    ring_id: str,
    members: list[dict],
    lang_of: Callable[[str], str | None],
    mention_key: str,
    article_key: str,
) -> dict:
    members = sorted(members, key=lambda r: -int(r.get(mention_key, 0) or 0))
    lead = members[0]
    meta = ring_meta(ring_id)
    lang_breakdown: dict[str, int] = {}
    member_view: list[dict] = []
    for r in members:
        norm = r.get("normalized") or _norm(r.get("term", ""))
        lg = lang_of(norm) or "?"
        m = int(r.get(mention_key, 0) or 0)
        lang_breakdown[lg] = lang_breakdown.get(lg, 0) + m
        member_view.append(
            {"term": r.get("term"), "normalized": norm, "language": lg, mention_key: m}
        )
    merged = dict(lead)  # inherit the lead member's other fields (kind, pmi, …)
    merged["term"] = (meta.label if meta else ring_id)
    merged["normalized"] = f"ring:{ring_id}"
    merged["ring_id"] = ring_id
    if meta and meta.note:
        merged["ring_note"] = meta.note
    merged[mention_key] = sum(int(r.get(mention_key, 0) or 0) for r in members)
    merged[article_key] = max(int(r.get(article_key, 0) or 0) for r in members)
    merged["language_breakdown"] = lang_breakdown
    merged["members"] = member_view
    merged["variants"] = len(member_view)
    return merged


def candidate_languages(
    pairs: Iterable[tuple[str, str | None, dict[str, int] | None]],
) -> dict[str, str | None]:
    """Resolve effective language for ring-candidate terms.

    ``pairs`` = (normalized, stored_language, signature) for every term that IS a
    ring member. Effective language = the stored language if known, else the
    dominant of the signature (signature-supported join), else None. Returns
    {normalized: effective_language} — the ``lang_of`` map for merge_equivalents.
    """
    out: dict[str, str | None] = {}
    for norm, stored, sig in pairs:
        if stored:
            out[norm] = stored
        elif sig:
            out[norm] = max(sig, key=lambda k: sig[k])
        else:
            out[norm] = None
    return out
