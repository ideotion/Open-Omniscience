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
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml

_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_equivalents.yml"
# Rings generated offline from Wikidata labels (scripts/generate_wikidata_rings.py).
# Read ALONGSIDE the curated file; a curated ring WINS on an id collision.
_GENERATED_PATH = Path(__file__).resolve().parents[2] / "configs" / "keyword_rings_generated.yml"

#: The LOCAL ring file's name inside the data directory. Not a module-level Path,
#: because ``data_dir()`` re-reads the environment on every call while a module
#: constant freezes at import -- the C7 trap, which would make a test (or an operator
#: who moved their data folder) read rings from the folder they left behind.
_LOCAL_RINGS_DIR = "rings"
_LOCAL_RINGS_NAME = "keyword_rings_local.yml"


def shipped_rings_paths() -> tuple[Path, ...]:
    """The ring files that ship WITH the release, in read order (lowest precedence
    first). Public because the backup carries them (Q409 = b) and a second copy of
    these two paths in ``src/backup/`` is how a file gets added here and forgotten
    there."""
    return (_GENERATED_PATH, _PATH)


def local_rings_path() -> Path:
    """``<data dir>/rings/keyword_rings_local.yml`` -- the rings THIS install holds.

    Distinct from the two SHIPPED files above because it is the operator's, not the
    release's: it is where a restored backup's local rings land (Q409 = b, gate row K)
    and where ``S04-06``'s auto-loaded Wikidata rings (Q406 ⛔ = b) will be written.
    Nothing writes it yet; the loader reads it so the restore half can be exercised
    before the writers exist.
    """
    from src.paths import data_dir

    return data_dir() / _LOCAL_RINGS_DIR / _LOCAL_RINGS_NAME


@dataclass(frozen=True)
class Ring:
    id: str
    members: tuple[tuple[str, str], ...]  # (language, normalized_term)
    note: str | None = None
    #: The Wikidata QID the generated ring was resolved from, when it has one. Q418 = a
    #: puts it in the hover, behind the LOCAL preview (invariant #6). Honest NULL for a
    #: CURATED ring: those are hand-vetted from the operator's own logs and were never
    #: resolved from an item, so there is no QID to show -- and inventing one would be a
    #: fabricated citation on the exact surface that exists to let a reader check us.
    qid: str | None = None

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
            qid = str(r.get("qid") or "").strip() or None
            rings.append(
                Ring(
                    id=rid,
                    members=tuple(dict.fromkeys(members)),
                    note=r.get("note"),
                    qid=qid,
                )
            )
    return rings


@lru_cache(maxsize=1)
def load_rings() -> tuple[Ring, ...]:
    """Parse the local + curated + Wikidata-generated ring files (cached).

    Missing/empty files -> no rings. READ ORDER IS PRECEDENCE, lowest first, and a
    later ring of the same id overrides an earlier one:

        local (this install's own, restored or auto-loaded)
        generated (shipped, from Wikidata labels)
        curated (shipped, hand-vetted) -- curation always wins

    THE LOCAL FILE READS FIRST ON PURPOSE, and it is how the gate's design note for
    Q409 = b ("a restored backup's shipped rings must never override a newer release's
    shipped rings") is kept BY CONSTRUCTION rather than by comparing versions. The
    design note proposed carrying each ring file's version and letting the newer win;
    that needs a version the ring files do not have, a comparison rule and a tie-break,
    and it fails open the day any of the three is wrong. Precedence by SOURCE needs
    none of them: a shipped ring beats a restored one whatever their dates, because the
    shipped files are read last."""
    if not _enabled():
        return ()
    by_id: dict[str, Ring] = {}
    for path in (local_rings_path(), _GENERATED_PATH, _PATH):
        for ring in _parse_rings(_read_yaml(path)):
            by_id[ring.id] = ring
    return tuple(by_id.values())


def invalidate_ring_caches() -> None:
    """Drop every memoised view of the ring files.

    Three ``lru_cache(maxsize=1)`` loaders sit on top of the files -- ``load_rings``,
    ``_index`` and ``_multi_index`` -- and none of them has ever had a runtime
    invalidation, because until now nothing could change a ring file while the app was
    running. A RESTORE can (Q409 = b), so this exists and the restore calls it.
    Clearing ``load_rings`` alone would leave the two indexes serving the old set,
    which is the shape where a term resolves through one surface and not another.
    """
    load_rings.cache_clear()
    _index.cache_clear()
    _multi_index.cache_clear()


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


# --------------------------------------------------------------------------- #
# R1 — cross-language query expansion (2026-09-05 keyword-translation plan, slice 1)
# --------------------------------------------------------------------------- #
#
# The rings above are read by every analytics surface and by NOTHING in the search
# path, so a corpus that holds `climat`, `Klima` and `клима́т` answers a search for
# `climate` with the English articles only. This section is the missing consumer.
#
# It is deliberately NOT built on ``ring_of``. That function maps one (language, term)
# to ONE ring id, and the index behind it is a plain dict — so where a (language, term)
# sits in SEVERAL rings the dict silently keeps whichever was parsed last. Measured on
# the shipped table: **91 such (language, term) pairs**, including de `wahl`
# (election / public-election / voting) and de `strom` (electricity / river). Resolving
# those by dict order would expand a search for German *Strom* into river vocabulary and
# say nothing about it. So expansion reads the ring MEMBERS directly, keeps every
# candidate, and REFUSES to choose between them — which is the R2a query-time-choice
# grammar arriving one slice early, on a real and measured population rather than a
# hypothetical one.

_IDEOGRAPHIC_RANGES = (
    (0x3040, 0x30FF),  # Hiragana + Katakana
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
)


def _is_ideographic(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _IDEOGRAPHIC_RANGES)


def _too_short_to_expand(normalized: str) -> bool:
    """A single ALPHABETIC character never expands; a single IDEOGRAPH does.

    The generated ring table carries 139 one-character members. In CJK a single
    character is a whole word -- ja ``軍`` (military), ja ``票`` (vote), zh ``債``
    (debt) -- and refusing those would disable expansion for zh/ja outright, the
    recorded CJK-segmentation trap. In Latin script the one-character members are
    generator noise (en ``d`` and ``q`` both sit in the drone ring), and expanding a
    search for ``d`` into unmanned-aerial-vehicle vocabulary is absurd. Two characters
    is the floor for alphabetic scripts because real acronyms live there: ``ai``,
    ``un``, ``eu``, ``pm`` all resolve to sensible rings.
    """
    return len(normalized) == 1 and not _is_ideographic(normalized)


@lru_cache(maxsize=1)
def _multi_index() -> dict[tuple[str, str], tuple[str, ...]]:
    """(language, normalized) -> EVERY ring id containing it, collision-preserving.

    The counterpart of ``_index()[1]``, which keeps only one. Order follows the parse
    order so the result is deterministic.
    """
    out: dict[tuple[str, str], list[str]] = {}
    for ring in load_rings():
        for lang, term in ring.members:
            bucket = out.setdefault((lang, term), [])
            if ring.id not in bucket:
                bucket.append(ring.id)
    return {k: tuple(v) for k, v in out.items()}


@dataclass(frozen=True)
class RingMatch:
    """One ring the typed term could belong to, with the language that matched it."""

    ring_id: str
    language: str
    label: str
    members: tuple[tuple[str, str], ...]  # (language, term), every member of the ring

    def siblings(self, normalized: str) -> tuple[str, ...]:
        """The ring's other member terms — what expansion actually adds to the query."""
        seen: list[str] = []
        for _lang, term in self.members:
            if term != normalized and term not in seen:
                seen.append(term)
        return tuple(seen)

    def by_language(self) -> dict[str, tuple[str, ...]]:
        """{language: its member terms} — the per-language breakdown R1 requires shown."""
        out: dict[str, list[str]] = {}
        for lang, term in self.members:
            bucket = out.setdefault(lang, [])
            if term not in bucket:
                bucket.append(term)
        return {k: tuple(v) for k, v in out.items()}


#: Why a term that IS in the table was nevertheless not expanded. These are disclosures,
#: not errors: each one is a thing the reader can act on.
DECLINE_SEVERAL_SENSES = "several-senses"  # the term denotes >1 concept; the reader picks
DECLINE_TOO_SHORT = "too-short"  # a lone alphabetic character; see _too_short_to_expand


@dataclass(frozen=True)
class TermExpansion:
    """What expansion did to ONE query term, and why — the unit of the disclosure."""

    term: str  # exactly as typed
    normalized: str
    matches: tuple[RingMatch, ...]  # every candidate ring, never narrowed silently
    applied: RingMatch | None  # the one expanded through, or None
    declined: str | None  # a DECLINE_* reason when matches exist but none was applied
    pinned_ring: str | None = None  # the sense the READER chose, if any (R2a)

    @property
    def siblings(self) -> tuple[str, ...]:
        return self.applied.siblings(self.normalized) if self.applied else ()

    @property
    def expanded(self) -> bool:
        return bool(self.siblings)

    @property
    def pin_applied(self) -> bool:
        """True when the sense the reader chose is the one that was searched."""
        return bool(
            self.pinned_ring
            and self.applied is not None
            and self.applied.ring_id == self.pinned_ring
        )

    @property
    def pin_missed(self) -> bool:
        """The reader asked for a sense this term does not belong to.

        Disclosed rather than silently dropped. A pin travels in a URL, so it can be
        stale (the ring file is regenerated), hand-edited, or simply wrong — and a
        reader who believes they chose a concept, and silently got a different search,
        has been told something false by omission.
        """
        return bool(self.pinned_ring) and not self.pin_applied

    def to_dict(self) -> dict:
        """The payload shape. Counts only, no score, and the method is stated."""
        out: dict = {"term": self.term, "normalized": self.normalized, "expanded": self.expanded}
        if self.pinned_ring:
            out["pinned_ring"] = self.pinned_ring
            out["pin_applied"] = self.pin_applied
        if self.applied is not None:
            out["ring_id"] = self.applied.ring_id
            out["concept"] = self.applied.label
            out["matched_language"] = self.applied.language
            out["added_terms"] = list(self.siblings)
            out["by_language"] = {k: list(v) for k, v in self.applied.by_language().items()}
        if self.declined:
            out["declined"] = self.declined
        # The alternatives ride along for a REFUSAL and for a PIN alike: a reader who has
        # chosen a sense is the one most likely to want a different one, and a surface
        # that has to clear the pin and re-search to find out what else there was would
        # be hiding a list it is already holding.
        if self.declined or self.pinned_ring:
            out["senses"] = [
                {
                    "ring_id": m.ring_id,
                    "concept": m.label,
                    "matched_language": m.language,
                    "by_language": {k: list(v) for k, v in m.by_language().items()},
                }
                for m in self.matches
            ]
        return out


def ring_matches(term: str, *, languages: Iterable[str] | None = None) -> tuple[RingMatch, ...]:
    """Every ring the term belongs to, under any of ``languages`` (default: all).

    Collision-preserving: a (language, term) sitting in several rings yields several
    matches, and a term that is a member under several languages yields one match per
    (ring, language). Deterministic order.
    """
    normalized = _norm(term)
    if not normalized:
        return ()
    index = _multi_index()
    wanted = None if languages is None else {str(x).casefold() for x in languages if x}
    out: list[RingMatch] = []
    seen: set[tuple[str, str]] = set()
    for (lang, tok), ring_ids in index.items():
        if tok != normalized or (wanted is not None and lang not in wanted):
            continue
        for rid in ring_ids:
            if (rid, lang) in seen:
                continue
            meta = ring_meta(rid)
            if meta is None:
                continue
            seen.add((rid, lang))
            out.append(RingMatch(ring_id=rid, language=lang, label=meta.label, members=meta.members))
    out.sort(key=lambda m: (m.ring_id, m.language))
    return tuple(out)


def expand_term(
    term: str,
    *,
    prefer_language: str | None = None,
    languages: Iterable[str] | None = None,
    pinned_ring: str | None = None,
) -> TermExpansion:
    """Resolve ONE query term to at most one ring, keeping every candidate visible.

    ``prefer_language`` is the reader's own language (the UI locale). It NARROWS the
    candidates when it matches any of them, and is otherwise ignored -- a French reader
    typing an English word still gets the English ring, and an English reader typing
    ``climat`` still gets one, because nothing else could have been meant.

    The refusal is the load-bearing half. When the candidates still name several
    concepts after that narrowing, this expands NOTHING and reports the choice. de
    ``strom`` is electricity AND river; de ``wahl`` is election, public-election AND
    voting. Picking one would change which articles match on a coin flip and say
    nothing about it -- and picking the UNION would drag river vocabulary into a search
    about the power grid, just as silently.

    ``pinned_ring`` is that choice, made (R2a: *the reader picks the sense and expansion
    runs per-sense from the chosen QID*). It outranks BOTH the language narrowing and the
    refusal, because it answers the exact question they exist to avoid guessing at -- the
    too-short refusal included, since a lone character is refused for want of a concept
    and a pin supplies one. What it can never do is REACH: it selects among the term's own
    candidate rings and nothing else, so a stale, hand-edited or simply wrong pin cannot
    expand a search into a concept the term does not carry. Such a pin falls through to
    ordinary resolution and is reported by ``pin_missed`` rather than dropped in silence.
    """
    normalized = _norm(term)
    if not normalized or not _enabled():
        return TermExpansion(term=term, normalized=normalized, matches=(), applied=None, declined=None)

    matches = ring_matches(normalized, languages=languages)
    if not matches:
        return TermExpansion(
            term=term, normalized=normalized, matches=(), applied=None, declined=None,
            pinned_ring=pinned_ring,
        )

    if pinned_ring:
        chosen = tuple(m for m in matches if m.ring_id == pinned_ring)
        if chosen:
            return TermExpansion(
                term=term, normalized=normalized, matches=matches, applied=chosen[0],
                declined=None, pinned_ring=pinned_ring,
            )

    if _too_short_to_expand(normalized):
        return TermExpansion(
            term=term, normalized=normalized, matches=matches, applied=None,
            declined=DECLINE_TOO_SHORT, pinned_ring=pinned_ring,
        )

    candidates = matches
    if prefer_language:
        preferred = tuple(m for m in matches if m.language == str(prefer_language).casefold())
        if preferred:
            candidates = preferred

    distinct = {m.ring_id for m in candidates}
    if len(distinct) == 1:
        return TermExpansion(
            term=term, normalized=normalized, matches=matches, applied=candidates[0],
            declined=None, pinned_ring=pinned_ring,
        )
    return TermExpansion(
        term=term, normalized=normalized, matches=matches, applied=None,
        declined=DECLINE_SEVERAL_SENSES, pinned_ring=pinned_ring,
    )



def parse_sense_pins(values: Iterable[str] | None) -> dict[str, str]:
    """``term:ring_id`` pairs -> ``{normalized term: ring id}`` for :class:`QueryExpander`.

    Split on the LAST colon. No ring id in either shipped ring file contains one (measured
    over all 710, and pinned by a test so a future id that does reddens rather than
    silently breaking the parse), while a term a reader typed may -- so the last colon is
    always the separator and the term keeps its own.

    A malformed entry is DROPPED rather than guessed at, and a well-formed one still has to
    name a ring the term actually belongs to: :func:`expand_term` checks that and reports a
    miss. So the two failure modes a URL parameter really has -- a typo and a stale link --
    both end somewhere the reader can see, and neither can widen a search on its own.
    """
    out: dict[str, str] = {}
    for raw in values or ():
        text = str(raw or "").strip()
        if ":" not in text:
            continue
        term, ring = text.rsplit(":", 1)
        term, ring = _norm(term), ring.strip()
        if term and ring:
            out[term] = ring
    return out


#: Q503 (2026-09-15): the cross-language OR fan-out is capped at this many LITERALS per
#: term -- the typed form plus its siblings -- most frequent first, and the ruling's own
#: NOTE adds a toggle that turns the cap OFF, with the cap ON by default.
#:
#: MEASURED on the shipped ring files rather than assumed: 698 rings load, and **140 of
#: them (20.1%) carry more than 40 distinct sibling terms** -- the largest are
#: ``soviet-afghan-war`` (124 distinct forms) and ``covid-19`` (120 forms / 119
#: siblings, spread ar 6 / bn 4 / de 3 / en 23 / es 41 / fr 5 / hi 2 / id 6 / ja 33 /
#: pt 5 / ru 4 / zh 7). So the cap is reached by a fifth of the table, not by a
#: hypothetical outlier, and the disclosure it owes is a live one.
#:
#: THE CAP BOUNDS THE FAN-OUT AND NOTHING ELSE. ``total_forms`` is always the EXACT
#: number of forms the ring offers, and the article total stays the exact, uncapped
#: count of whatever search actually ran (Q515 = b) -- the standing anti-capping rule
#: is that a cap may bound which literals are searched and may never bound a REPORTED
#: NUMBER.
CONCEPT_LITERAL_CAP = 40

#: Injected corpus-frequency resolver: ``terms -> {term: mentions}``. INJECTED rather
#: than imported because this module is pure (no DB) by design -- the same discipline as
#: ``merge_equivalents``'s ``lang_of``. A term the resolver omits is treated as
#: unmeasured, NEVER as zero: an absent frequency and a measured zero are different
#: facts, and only the second is evidence about the corpus.
Frequency = Callable[[Sequence[str]], Mapping[str, int]]


class QueryExpander:
    """A ``build_match`` expansion hook that RECORDS what it did.

    ``build_match`` stays pure and ring-unaware: it calls this for each parsed term and
    ORs in whatever literals come back. The disclosure the surfaces publish is read off
    ``expansions`` afterwards, so the two can never disagree about what was expanded --
    the search and the sentence describing it come from one object.
    """

    def __init__(
        self,
        *,
        prefer_language: str | None = None,
        languages: Iterable[str] | None = None,
        pinned: Mapping[str, str] | None = None,
        cap: int | None = CONCEPT_LITERAL_CAP,
        frequency: Frequency | None = None,
    ) -> None:
        self.prefer_language = prefer_language
        self.languages = tuple(languages) if languages is not None else None
        # Q503 + its NOTE: the fan-out cap, ON by default, ``None`` when the reader turned
        # it off. Counted in LITERALS (the typed form plus its siblings), because that is
        # the unit the ruling's own disclosure speaks in -- "expanded to 40 of 63 forms".
        self.cap = cap if (cap is None or cap > 0) else None
        self.frequency = frequency
        # {normalized term: (kept_siblings, all_siblings, ordering)} -- what the cap did.
        self._capped: dict[str, tuple[tuple[str, ...], tuple[str, ...], str]] = {}
        # {normalized term: ring id} -- the reader's sense choices (R2a). Keyed on the
        # NORMALIZED form because that is what the ring index is keyed on, so `April` and
        # `april` are one choice rather than two that disagree.
        self.pinned: dict[str, str] = {_norm(k): str(v) for k, v in (pinned or {}).items() if v}
        self.expansions: list[TermExpansion] = []
        self._by_term: dict[str, TermExpansion] = {}

    def __call__(self, term: str) -> tuple[str, ...]:
        """Expand one term, recording it ONCE however many times it is asked for.

        One request runs the hook several times by design: the omnibar retries a
        half-typed Boolean as a phrase, and a capped result set is re-counted through
        ``search_total`` with the SAME hook so the count and the rows describe one set.
        Appending per call would make the disclosure say a term was expanded twice, which
        is a statement about our plumbing rather than about the reader's query. The
        memo also means the ring lookup runs once per distinct term per request.
        """
        cached = self._by_term.get(term)
        if cached is not None:
            return self._literals_for(cached)
        result = expand_term(
            term,
            prefer_language=self.prefer_language,
            languages=self.languages,
            pinned_ring=self.pinned.get(_norm(term)),
        )
        self._by_term[term] = result
        self.expansions.append(result)
        return self._literals_for(result)

    def _literals_for(self, result: TermExpansion) -> tuple[str, ...]:
        """The siblings this expander actually ORs in, after ordering and the cap.

        ORDERING IS A CLAIM, so it is recorded rather than assumed. With a ``frequency``
        resolver the siblings are sorted by the corpus's own mention counts, which is the
        "most frequent first" the ruling asks for; without one they keep the ring file's
        own member order and the disclosure says ``ring-order`` instead. A term the
        resolver does not answer for sorts as UNMEASURED and keeps its ring position
        relative to the other unmeasured ones -- never as a measured zero, which would
        push a real form the corpus simply has not indexed yet to the back of the queue
        behind forms it genuinely outranks.
        """
        siblings = result.siblings
        if not siblings:
            return ()
        ordering = "ring-order"
        ordered = siblings
        if self.frequency is not None:
            try:
                counts = self.frequency(siblings)
            except Exception:  # noqa: BLE001 - an unreadable corpus must never break a search
                counts = {}
            if counts:
                ordering = "corpus-frequency"
                # Stable: measured terms first by descending count, then the unmeasured
                # ones in ring order. ``sorted`` is stable, so equal keys keep that order.
                ordered = tuple(
                    sorted(
                        siblings,
                        key=lambda t: (0 if t in counts else 1, -int(counts.get(t, 0))),
                    )
                )
        kept = ordered if self.cap is None else ordered[: max(0, self.cap - 1)]
        self._capped[result.normalized] = (tuple(kept), tuple(ordered), ordering)
        return tuple(kept)

    def cap_record(self, normalized: str) -> tuple[tuple[str, ...], tuple[str, ...], str] | None:
        """``(kept siblings, every sibling, ordering)`` for one resolved term, or ``None``."""
        return self._capped.get(normalized)

    @property
    def any_expanded(self) -> bool:
        """Did the SEARCH actually widen? Read off what was ORed in, never off the ring.

        Under a cap of 1 the ring may offer sixty siblings and the query still searches
        the typed form alone, so reading ``TermExpansion.expanded`` (a fact about the
        RING) would report a widening that did not happen.
        """
        return any(bool(self.searched_siblings(e)) for e in self.expansions)

    def searched_siblings(self, e: TermExpansion) -> tuple[str, ...]:
        """The siblings this expander really ORed in for ``e`` -- cap applied."""
        rec = self._capped.get(e.normalized)
        return rec[0] if rec is not None else ()

    def cap_facts(self, e: TermExpansion) -> dict | None:
        """The anti-capping block for one term: what was searched, out of how many.

        ``total_forms`` is EXACT and is never the cap -- it counts the typed form plus
        every sibling the ring offers, whether or not the fan-out reached them. Emitted
        only when the term expanded at all, because a term that touched no ring has no
        forms to be capped.
        """
        rec = self._capped.get(e.normalized)
        if rec is None:
            return None
        kept, every, ordering = rec
        total_forms = 1 + len(every)
        searched_forms = 1 + len(kept)
        out: dict = {
            "searched_forms": searched_forms,
            "total_forms": total_forms,
            "capped": searched_forms < total_forms,
            "cap": self.cap,
            "ordering": ordering,
        }
        if out["capped"]:
            out["omitted_forms"] = total_forms - searched_forms
        return out

    def disclosure(self) -> dict | None:
        """The payload block, or None when there is nothing to disclose.

        Present whenever a term was expanded OR a term was declined with a choice to
        offer -- a decline is information the reader can act on, not silence. Absent
        when no query term touched a ring at all, so an ordinary search carries no
        extra weight.
        """
        # `pin_missed` earns its place in this list: a pin naming a ring the term does not
        # belong to on a term that neither expanded nor declined would otherwise leave the
        # reader's rejected choice invisible -- the one case where saying nothing is a lie.
        interesting = [e for e in self.expansions if e.expanded or e.declined or e.pin_missed]
        if not interesting:
            return None
        terms = []
        for e in interesting:
            row = e.to_dict()
            facts = self.cap_facts(e)
            if facts is not None:
                row.update(facts)
                # The ROW's own `added_terms` must describe the SEARCH, not the ring --
                # otherwise a capped query lists forms it never looked for, and the
                # keyword group beside it would offer siblings the article count cannot
                # account for (two surfaces disagreeing about one quantity).
                row["added_terms"] = list(self.searched_siblings(e))
            terms.append(row)
        any_capped = any(t.get("capped") for t in terms)
        out: dict = {
            "expanded": self.any_expanded,
            "terms": terms,
            "method": (
                "cross-language expansion through the hand-vetted Wikidata concept rings "
                "(configs/keyword_rings_generated.yml); a term denoting several concepts is "
                "NOT expanded and its senses are listed instead"
            ),
            # NO COUNT IN THE SENTENCE, and that is the fix rather than the wording.
            # It read "Rings cover 698 concepts" -- a number baked into prose, which goes
            # stale the moment the ring file grows AND makes the sentence unkeyable, since
            # a locale key must match verbatim. A Chromium walk (2026-09-17) found this
            # caveat rendered in ENGLISH in ar, zh, ja and hi while every other string on
            # the rail was translated: it is server prose, and the client had no key for
            # it. The count belongs in a payload field that reports counts; a caveat that
            # carries one cannot be translated and cannot stay true.
            "caveat": (
                "This search matched the concept in every language the ring covers, not only "
                "the words you typed. Most terms are in no ring and are unaffected."
            ),
        }
        if any_capped:
            out["capped"] = True
            out["cap"] = self.cap
            # A separate sentence rather than an extension of the caveat above: that one
            # is an already-translated key in twelve locales, and appending to it would
            # change the key and silently un-translate it everywhere (the recorded
            # extend-a-keyed-constant defect).
            out["cap_caveat"] = (
                "The search was widened to the most-mentioned forms only. Turn the limit off "
                "to search every form the concept has."
            )
        return out


# --------------------------------------------------------------------------- #
# The THREE-TIER TRANSLATION LADDER (S04-06; Q401, Q403, Q412, Q418, ruling R7/R8)
# --------------------------------------------------------------------------- #
#
# Q403 = a confirms three tiers and Q401 = a says what the reader sees: the translation
# IS the visible term, followed by a small "translated from <language>" tag, with the
# original and the evidence in the hover. That grammar only works if every surface can
# ask ONE question -- "what does this keyword read as, in my language, and how sure is
# that?" -- and get ONE answer carrying its own provenance. This is that answer.
#
# THE RUNGS, in order, and what each one is:
#   verified   -- a member of the term's Wikidata-sourced RING in the target language.
#                 A published label, checkable against the QID the hover shows.
#   tentative  -- a local model's answer, persisted in `keyword_translations` (Q404).
#                 ALWAYS marked ~, never the trusted index. Supplied BY THE CALLER,
#                 because this module is pure and the tier lives in the database.
#   untranslated -- no answer at either rung. The term keeps its own language, stays
#                 searchable, and is tagged with the language it IS in, because a
#                 foreign keyword the reader cannot place is the thing R7 is about.
#
# AND A FOURTH VALUE THAT IS NOT A RUNG. `same_language` means the ladder was never
# entered: the term is already in the reader's language, so there is nothing to
# translate and nothing to disclose. It is kept apart from `untranslated` because those
# are two different facts and the recorded rule is that two absences must not share a
# sentinel -- a reader told "not translated" about a word already in their own language
# has been told something false, and a surface that tags every native term would be
# noise on the majority of every corpus.
TIER_VERIFIED = "verified"
TIER_TENTATIVE = "tentative"
TIER_UNTRANSLATED = "untranslated"
TIER_SAME_LANGUAGE = "same_language"

#: The refusal Q412 = a asks for: `translate_term` gains the path `expand_term` already
#: has. Re-exported under its own name so a caller reads the tier and the reason without
#: importing the expansion vocabulary.
DECLINE_SEVERAL_SENSES_TR = DECLINE_SEVERAL_SENSES


@dataclass(frozen=True)
class SenseOption:
    """One concept a term could mean, when it means several (Q412 = a).

    Carries what a picker needs to let a reader CHOOSE rather than be guessed at: the
    ring id (the pin grammar's value), the concept label, the QID, and what the concept
    reads as in the target language -- so the picker offers translations, not ring ids.
    """

    ring_id: str
    concept: str
    qid: str | None
    translation: str | None

    def to_dict(self) -> dict:
        return {
            "ring_id": self.ring_id,
            "concept": self.concept,
            "qid": self.qid,
            "translation": self.translation,
        }


@dataclass(frozen=True)
class TermTranslation:
    """What ONE keyword reads as in ONE target language, with its provenance.

    Every field a surface needs is here, so the label grammar cannot be re-derived
    differently on each of the eleven surfaces that render a keyword -- the recorded
    "a second renderer re-derives the rules, and gets them wrong" defect, which is what
    invariant #16's ONE-toolkit rule is actually about.
    """

    text: str | None  # the translation, or None at the untranslated / same-language rungs
    tier: str  # one of the TIER_* values above
    source_lang: str | None  # the language the term IS in (Q402's "translated from X")
    target_lang: str
    ring_id: str | None = None
    qid: str | None = None
    declined: str | None = None  # a DECLINE_* reason when the ladder REFUSED to choose
    senses: tuple[SenseOption, ...] = ()
    model: str | None = None  # tentative tier only: which model said so
    prompt_version: str | None = None  # tentative tier only

    @property
    def translated(self) -> bool:
        return self.tier in (TIER_VERIFIED, TIER_TENTATIVE)

    def to_dict(self) -> dict:
        """The payload every keyword surface reads. Counts and labels, never a score.

        The keys are ADDITIVE over the pre-2026-09-17 shape (`translation` +
        `translation_source`), so a caller that only knows the old two keeps working --
        which is what lets the eleven silent surfaces be converted one at a time instead
        of in one unreviewable sweep.
        """
        out: dict = {"translation_tier": self.tier, "translation_target_lang": self.target_lang}
        if self.source_lang:
            out["translation_source_lang"] = self.source_lang
        if self.text:
            out["translation"] = self.text
            out["translation_source"] = "ring" if self.tier == TIER_VERIFIED else "llm"
        if self.ring_id:
            out["ring_id"] = self.ring_id
        if self.qid:
            out["translation_qid"] = self.qid
        if self.declined:
            out["translation_declined"] = self.declined
        if self.senses:
            out["senses"] = [x.to_dict() for x in self.senses]
        if self.model:
            out["translation_model"] = self.model
        if self.prompt_version:
            out["translation_prompt_version"] = self.prompt_version
        return out


def _senses_for(normalized: str, language: str | None, target_lang: str) -> tuple[SenseOption, ...]:
    """Every distinct concept ``normalized`` belongs to, as pickable options."""
    matches = ring_matches(normalized, languages=[language] if language else None)
    seen: set[str] = set()
    out: list[SenseOption] = []
    for m in matches:
        if m.ring_id in seen:
            continue
        seen.add(m.ring_id)
        meta = ring_meta(m.ring_id)
        out.append(
            SenseOption(
                ring_id=m.ring_id,
                concept=m.label,
                qid=meta.qid if meta else None,
                translation=ring_translation(m.ring_id, target_lang),
            )
        )
    return tuple(out)


def resolve_translation(
    language: str | None,
    normalized: str,
    target_lang: str,
    *,
    ring_id: str | None = None,
    tentative: Mapping[str, Any] | None = None,
    pinned_ring: str | None = None,
) -> TermTranslation:
    """Walk the ladder for one keyword and report WHICH rung answered.

    ``ring_id`` short-circuits the lookup for a row that is already a merged ring row
    (it knows its own ring); ``tentative`` is the caller's ``keyword_translations`` hit,
    a mapping with at least ``text`` and optionally ``model``/``prompt_version`` -- the
    database read cannot happen here because this module is pure by design and is
    imported by paths that hold no session.

    ``pinned_ring`` is the reader's own sense choice, on the same grammar
    :func:`parse_sense_pins` already parses, and it outranks the refusal below for the
    same reason it does in :func:`expand_term`: it answers the exact question the
    refusal exists to avoid guessing at.

    THE REFUSAL IS THE LOAD-BEARING HALF (Q412 = a). Where the term names several
    concepts -- de ``wahl`` is election, public-election AND voting; de ``strom`` is
    electricity AND river -- there is no single translation, and printing one would
    change what the reader believes the row is about on a coin flip. The ladder stops,
    reports ``declined``, and hands back the senses so a picker can offer the choice.
    """
    tl = (target_lang or "").strip().casefold()
    src = (language or "").strip().casefold() or None
    if not tl:
        return TermTranslation(text=None, tier=TIER_UNTRANSLATED, source_lang=src, target_lang="")
    if src and src == tl:
        return TermTranslation(text=None, tier=TIER_SAME_LANGUAGE, source_lang=src, target_lang=tl)

    norm = _norm(normalized)

    # --- rung 1: the VERIFIED ring translation ------------------------------------ #
    rid = ring_id
    if rid is None and src:
        senses = _senses_for(norm, src, tl)
        if pinned_ring and any(x.ring_id == pinned_ring for x in senses):
            rid = pinned_ring
        elif len(senses) > 1:
            # SEVERAL CONCEPTS, NO CHOICE MADE: refuse, and say what the choices are.
            #
            # Q412 = a's own named examples are the shape this covers: de `wahl` is
            # election AND public-election AND voting; de `strom` is electricity AND
            # river. Picking one would change what the reader believes the row is about
            # on a coin flip, and picking the union would print two concepts as one word.
            #
            # MEASURED over the two shipped ring files (2026-09-17): 91 of 21,834
            # (language, term) pairs are collision-prone -- the same 91 `expand_term`
            # already refuses, which is the corroboration that this is the same path the
            # ruling asked to be extended, not a second one beside it. Across en/fr/ar/zh
            # targets that is 246 refusals in 78,371 resolutions (0.31%), against 96.4%
            # verified.
            #
            # A NARROWER RULE WAS TRIED AND REJECTED: refusing only where the senses
            # DISAGREE about the target term would read as kinder, and it fires on
            # exactly ZERO pairs of the shipped table -- while being wrong on the
            # ruling's own headline example, since `wahl`'s three senses translate to
            # three different English strings and Q412 names them as a case to refuse.
            return TermTranslation(
                text=None,
                tier=TIER_UNTRANSLATED,
                source_lang=src,
                target_lang=tl,
                declined=DECLINE_SEVERAL_SENSES_TR,
                senses=senses,
            )
        elif senses:
            rid = senses[0].ring_id
    if rid:
        text = ring_translation(rid, tl)
        meta = ring_meta(rid)
        if text and _norm(text) not in (norm, _norm(normalized)):
            return TermTranslation(
                text=text,
                tier=TIER_VERIFIED,
                source_lang=src,
                target_lang=tl,
                ring_id=rid,
                qid=meta.qid if meta else None,
            )

    # --- rung 2: the TENTATIVE model translation ----------------------------------- #
    # Only reachable when no ring covered the term, which is the doctrine the LLM tier
    # has carried since 2026-06-19: the verified translation always wins.
    text = str((tentative or {}).get("text") or "").strip()
    if text and _norm(text) != norm:
        return TermTranslation(
            text=text,
            tier=TIER_TENTATIVE,
            source_lang=src,
            target_lang=tl,
            ring_id=rid,
            model=(tentative or {}).get("model"),
            prompt_version=(tentative or {}).get("prompt_version"),
        )

    # --- rung 3: UNTRANSLATED, tagged with the language it IS in -------------------- #
    return TermTranslation(
        text=None, tier=TIER_UNTRANSLATED, source_lang=src, target_lang=tl, ring_id=rid
    )


@dataclass(frozen=True)
class ConceptResolution:
    """What ONE typed concept resolves to — the single object both search paths read.

    Q501 (2026-09-15): ``resolve_concept(term, ui_lang, sense)`` is computed ONCE per
    analysis tab and passed to BOTH the FTS path and the keyword-keyed aggregates. This
    is that object. It IS the ``ExpandTerms`` hook (``__call__``), so it can be handed
    straight to :func:`src.database.fts.build_match` / ``search_ids`` / ``search_total``;
    and it carries :attr:`literals`, which is what a keyword-keyed aggregate joins on.
    One object means the article list and every analysis tab cannot disagree about which
    concept they are describing — the property the gate row asks to be demonstrated.

    A query may carry SEVERAL terms (``climate AND policy``). The primary term's numbers
    are the ones this object publishes; the others are resolved by the same expander,
    under the same settings, when ``build_match`` asks for them. So a multi-term query
    still expands consistently and the disclosure still covers every term.
    """

    term: str
    normalized: str
    expansion: TermExpansion
    literals: tuple[str, ...]  # the forms actually SEARCHED, the typed form first
    all_literals: tuple[str, ...]  # every form the ring offers; the anti-capping total
    ordering: str  # "corpus-frequency" | "ring-order" | "literal"
    expander: QueryExpander | None  # None when the reader asked for the literal term

    # -- the ExpandTerms hook -------------------------------------------------- #
    def __call__(self, term: str) -> tuple[str, ...]:
        if self.expander is None:
            return ()
        return self.expander(term)

    # -- the facts a surface publishes ----------------------------------------- #
    @property
    def total_forms(self) -> int:
        """EXACT — the typed form plus every sibling the ring offers. Never the cap."""
        return len(self.all_literals)

    @property
    def searched_forms(self) -> int:
        return len(self.literals)

    @property
    def cap_applied(self) -> bool:
        return self.searched_forms < self.total_forms

    @property
    def expanded(self) -> bool:
        """Did the SEARCH widen? (Not: does the ring offer siblings.)"""
        return self.searched_forms > 1

    def disclosure(self) -> dict | None:
        return self.expander.disclosure() if self.expander is not None else None


def resolve_concept(
    term: str,
    *,
    ui_lang: str | None = None,
    sense: Mapping[str, str] | Iterable[str] | None = None,
    expand: bool = True,
    cap: int | None = CONCEPT_LITERAL_CAP,
    frequency: Frequency | None = None,
    languages: Iterable[str] | None = None,
) -> ConceptResolution:
    """Resolve one typed term to the forms every search path should use (Q501, Q504).

    ``expand=False`` is the reader's "only the words I typed" toggle (Q504's ``?expand=0``).
    It returns a resolution whose ``literals`` is exactly ``(term,)`` and whose hook adds
    NOTHING, so every downstream call is byte-identical to a tree without rings — which is
    what makes the toggle a real refusal rather than an approximation of one.

    ``sense`` is the reader's sense pick (Q504's ``?sense=``). It accepts either the parsed
    ``{term: ring_id}`` mapping or the raw ``term:ring_id`` strings a URL carries, so a
    caller never has to remember which side of :func:`parse_sense_pins` it is on.

    ``cap`` is Q503's fan-out limit, ``None`` when the reader turned it off. ``frequency``
    is the injected corpus-frequency resolver that makes "most frequent first" a
    measurement rather than a claim; without it the ordering is the ring file's own and
    :attr:`ConceptResolution.ordering` says so.

    RING-VERIFIED ONLY (Q514). The forms come from :func:`expand_term`, which reads the
    hand-vetted ring files and nothing else. A tentative (``≈``) machine translation may
    be DISPLAYED beside a keyword, and it can never enter this list — there is no path
    from ``keyword_translations`` into a query here, by construction rather than by a
    filter that could be relaxed. The per-query opt-in the ruling allows would be a
    separate, explicit argument; none exists, so no caller can widen a search on a
    translation nobody verified.
    """
    normalized = _norm(term)
    pins: Mapping[str, str]
    if sense is None:
        pins = {}
    elif isinstance(sense, Mapping):
        pins = dict(sense)
    else:
        pins = parse_sense_pins(sense)

    if not expand or not normalized:
        return ConceptResolution(
            term=term,
            normalized=normalized,
            expansion=TermExpansion(
                term=term, normalized=normalized, matches=(), applied=None, declined=None
            ),
            literals=(term,) if term else (),
            all_literals=(term,) if term else (),
            ordering="literal",
            expander=None,
        )

    expander = QueryExpander(
        prefer_language=(ui_lang or "").strip().casefold() or None,
        languages=languages,
        pinned=pins,
        cap=cap,
        frequency=frequency,
    )
    kept = expander(term)  # warms the memo AND records the cap for this term
    resolved = expander._by_term[term]
    rec = expander.cap_record(resolved.normalized)
    every = rec[1] if rec is not None else resolved.siblings
    ordering = rec[2] if rec is not None else "ring-order"
    return ConceptResolution(
        term=term,
        normalized=normalized,
        expansion=resolved,
        literals=(term, *kept),
        all_literals=(term, *every),
        ordering=ordering,
        expander=expander,
    )
