"""Entities on the three-tier ladder, keyed by Wikidata QID (Q415 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q415 = a, verbatim: «The same ladder for entities, keyed by Wikidata QID -- this is the 0.5
entity spine's first concrete use.»

**NO SECOND LADDER.** The keyword ladder (0.4 row M, :mod:`src.analytics.equivalence`) already
walks term -> ring -> translation and reports WHICH rung answered (verified · tentative ·
untranslated, plus the not-a-rung ``same_language``). An entity walks the same rings, with two
differences and no new tier:

* **The identity is the QID.** A generated ring carries the Wikidata item it was resolved
  from; an entity whose name sits in exactly one QID-bearing ring IS that item. A name in
  several rings with different QIDs is the several-senses case Q412 refuses for keywords, and
  it is refused here the same way -- no QID, the senses named -- because picking one would
  merge two people into one on a coin flip.
* **The label comes from the item first** (the cache of :mod:`src.entities.items`), then from
  the ring's member in the target language. Both are the VERIFIED rung: each is Wikidata's own
  label for the item, reached two ways. The payload says which (``translation_source``).

**AN UNRESOLVABLE ENTITY STAYS A PLAIN TERM.** No QID, the untranslated rung, the language it is
in named -- never a guessed item. That is the brief's acceptance line, and the reason
:func:`entity_qid` returns ``(None, reason)`` rather than a best guess.

Pure except for the one optional cache read, which takes a session the caller holds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.analytics import equivalence
from src.entities.wikidata_items import is_qid

DECLINED_SEVERAL_ITEMS = "several-items"
DECLINED_NO_ITEM = "no-item"


def entity_qid(name: str, language: str | None = None) -> tuple[str | None, str | None]:
    """``(qid, None)`` when ``name`` names exactly one item, else ``(None, reason)``.

    Reads the ring table only (no session, no network). ``language`` narrows the lookup to
    the language the name is written in, when known; without it every language is asked,
    which is right for a proper name (``Paris`` is ``Paris`` in six of the twelve).
    """
    langs = [language] if language else None
    qids: list[str] = []
    for rid in equivalence.ring_ids_for(name or "", langs):
        meta = equivalence.ring_meta(rid)
        q = meta.qid if meta else None
        if q and is_qid(q) and q not in qids:
            qids.append(q)
    if len(qids) == 1:
        return qids[0], None
    if len(qids) > 1:
        return None, DECLINED_SEVERAL_ITEMS
    return None, DECLINED_NO_ITEM


@dataclass(frozen=True)
class EntityResolution:
    """What ONE entity name reads as in ONE target language, with its identity and provenance."""

    term: str
    tier: str  # an equivalence.TIER_* value
    target_lang: str
    source_lang: str | None = None
    qid: str | None = None
    label: str | None = None
    label_source: str | None = None  # "wikidata" (the item cache) | "ring"
    declined: str | None = None
    candidate_qids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        """The keyword ladder's payload keys, so the ONE display helper renders it unchanged."""
        out: dict = {"translation_tier": self.tier, "translation_target_lang": self.target_lang}
        if self.source_lang:
            out["translation_source_lang"] = self.source_lang
        if self.label:
            out["translation"] = self.label
            out["translation_source"] = self.label_source
        if self.qid:
            out["qid"] = self.qid
            out["translation_qid"] = self.qid
        if self.declined:
            out["translation_declined"] = self.declined
        if self.candidate_qids:
            out["candidate_qids"] = list(self.candidate_qids)
        return out


def _cached_labels(session, qid: str | None) -> dict[str, str]:
    if session is None or not is_qid(qid):
        return {}
    from src.database.models import WikidataItem

    row = session.get(WikidataItem, qid)
    if row is None or row.status != "ok" or not row.labels_json:
        return {}
    try:
        labels = json.loads(row.labels_json)
    except ValueError:
        return {}
    return labels if isinstance(labels, dict) else {}


def resolve_entity(
    term: str,
    target_lang: str,
    *,
    language: str | None = None,
    session=None,
) -> EntityResolution:
    """Walk the ladder for one entity name. See the module docstring for the rules."""
    tl = (target_lang or "").strip().casefold()
    src = (language or "").strip().casefold() or None
    qid, why = entity_qid(term, src)
    candidates: tuple[str, ...] = ()
    if why == DECLINED_SEVERAL_ITEMS:
        seen: list[str] = []
        for rid in equivalence.ring_ids_for(term or "", [src] if src else None):
            meta = equivalence.ring_meta(rid)
            if meta and meta.qid and is_qid(meta.qid) and meta.qid not in seen:
                seen.append(meta.qid)
        candidates = tuple(seen)
    if not tl:
        return EntityResolution(term=term, tier=equivalence.TIER_UNTRANSLATED, target_lang="",
                                source_lang=src, qid=qid)
    if src and src == tl:
        return EntityResolution(term=term, tier=equivalence.TIER_SAME_LANGUAGE, target_lang=tl,
                                source_lang=src, qid=qid)
    if qid is None:
        return EntityResolution(
            term=term, tier=equivalence.TIER_UNTRANSLATED, target_lang=tl, source_lang=src,
            declined=why if why == DECLINED_SEVERAL_ITEMS else None, candidate_qids=candidates,
        )
    norm = equivalence._norm(term)
    label = _cached_labels(session, qid).get(tl)
    source = "wikidata" if label else None
    if not label:
        for rid in equivalence.ring_ids_for(term, [src] if src else None):
            meta = equivalence.ring_meta(rid)
            if meta and meta.qid == qid:
                label = equivalence.ring_translation(rid, tl)
                if label:
                    source = "ring"
                    break
    if label and equivalence._norm(label) != norm:
        return EntityResolution(term=term, tier=equivalence.TIER_VERIFIED, target_lang=tl,
                                source_lang=src, qid=qid, label=label, label_source=source)
    if label:
        # The item's label in the target language IS the term: nothing to translate, and
        # printing "translated from" beside an identical word would be noise, not a fact.
        return EntityResolution(term=term, tier=equivalence.TIER_SAME_LANGUAGE, target_lang=tl,
                                source_lang=src, qid=qid)
    return EntityResolution(term=term, tier=equivalence.TIER_UNTRANSLATED, target_lang=tl,
                            source_lang=src, qid=qid)


def annotate_www(session, www: dict, target_lang: str | None) -> dict:
    """Put the Who and Where facets of the analysis window on the spine, in place.

    Who: each person or organisation gains its ladder fields (:func:`resolve_entity`).
    Where: each place gains ``place_id`` (or ``place_reason``), and when its Place is on this
    machine, its name in ``target_lang`` with the name's source (Q827). ADDITIVE keys only,
    so the facet's counts, its order and the drill values are untouched -- the name the drill
    sends is still the mention's own ``name``.
    """
    from src.entities.items import cached_item, item_payload
    from src.entities.places import display_name, gazetteer_entry

    tl = (target_lang or "").strip().casefold() or "en"
    for row in ((www.get("who") or {}).get("entities") or []):
        row.update(resolve_entity(row.get("name") or "", tl, session=session).to_dict())
    from src.database.models import Place

    for row in ((www.get("where") or {}).get("places") or []):
        city, reason = gazetteer_entry(row.get("name"), row.get("country"), row.get("kind"))
        if reason is not None:
            row["place_reason"] = reason
            continue
        row["place_id"] = city.osm
        if city.qid:
            row["qid"] = city.qid
        place = session.get(Place, city.osm)
        if place is not None:
            nm = display_name(place, tl, item_payload(cached_item(session, place.qid)))
            row["place_name"] = nm["name"]
            row["place_name_source"] = nm["source"]
    return www
