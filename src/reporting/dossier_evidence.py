"""The dossier's signed-evidence export (brief S08-01 S2; 0.8 gate row A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE BUNDLE FORMAT, NOT A SECOND ONE. A dossier is exported as the evidence bundle this app already
signs (:mod:`src.reporting.evidence`): its joined articles are the bundle's items, under the Merkle
root, and the dossier itself rides in the manifest as ``manifest.dossier``. The Ed25519 signature is
over the WHOLE canonical manifest, so a changed rail count, place name or licence line breaks the
signature exactly as a changed item breaks the root, and :func:`~src.reporting.evidence.verify_bundle`
and ``scripts/verify_evidence.py`` check it unchanged.

THE DOSSIER IS A LENS (invariant #31), so the block is what :func:`~src.entities.dossier.qid_dossier`
shows, read from each rail's store at export time: the item, the three join routes and their
counts, every rail with its rows, the rails it does not join with their reasons, the corpus
passport, the method and the caveat. Nothing is computed for the export that the page does not
show, and nothing is scored.

WHAT IT SAYS ABOUT ITSELF. The page carries at most ``IDS_FOR_ANALYSIS`` article ids, so a dossier
whose article count is larger is exported with that many items and says so (``articles_total`` beside
``articles_in_bundle``): a bundle that looked complete while holding a part would be a false record.
The licence lines are the ones that APPLY (Q1008 = a), each with the signal that produced it: the
sources of the bundled articles, the Wikipedia lane's pages, the Places (OSM ids, so ODbL under
Q823 = a), and the OpenStreetMap lane's objects.

TWO THINGS THE BLOCK DOES NOT CARRY AS THE PAGE HAS THEM (the 2026-11-19 reads):

* **No JSON number with a fraction.** The signature is over Python's canonical JSON, which writes a
  whole-degree coordinate as ``52.0``; a browser that saves the file (``JSON.stringify``) writes ``52``,
  and the verifier, reading ``52`` back as an integer, then signs-checks different bytes, so an honest
  file read as tampered. Every float in the block is therefore written as its decimal TEXT
  (``"52.0"``), which no JSON tool rewrites. Article items never held a float.
* **Not which pages this install follows.** The Wikipedia rail marks each lane page ``followed`` or
  walked; in a plaintext file handed to someone else that flag is a list of what the investigator
  watches, so it is left out: the file names the pages, not the watch list.

No network call, no write: it reads, and the endpoint signs.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What the block's signature covers and what it does not, written into the file.
EXPORT_NOTE = (
    "This dossier is the one the app showed for this item when the file was made, read from this "
    "machine's stores. The signature covers it and the article entries; the article entries are "
    "also bound by the Merkle root. It records what was on this machine, not everything that "
    "exists about the item."
)


@dataclass(frozen=True)
class DossierSelection:
    """The articles a dossier export carries, and the block written beside them (no article text)."""

    article_ids: list[int]
    block: dict


#: The fields of a Wikipedia lane page the file carries (``followed`` is left out, see above).
WIKI_PAGE_FIELDS = ("edition", "title", "external_id")


def _stable(obj):
    """``obj`` with every float written as its decimal text, so the signed bytes survive any JSON tool."""
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_stable(v) for v in obj]
    return obj


def _without_watch_list(rails: list[dict]) -> list[dict]:
    out = []
    for r in rails:
        lane = r.get("lane") if r.get("key") == "wikipedia" else None
        if isinstance(lane, dict) and isinstance(lane.get("pages"), list):
            pages = [{k: p.get(k) for k in WIKI_PAGE_FIELDS} for p in lane["pages"] if isinstance(p, dict)]
            r = {**r, "lane": {**lane, "pages": pages}}
        out.append(r)
    return out


def _items_in_bundle(rails: list[dict], bundled: set[int]) -> list[dict]:
    """A corpus rail's listed rows, kept only where the article is one of the bundle's items.

    The rail lists its NEWEST rows (row 200) while the bundle carries the first ids up to its
    bound, so on a large dossier the two differ. A row the Merkle root does not cover would read
    as signed evidence it is not, and its source would be missing from the licence lines.
    """
    out = []
    for r in rails:
        if isinstance(r.get("items"), list):
            r = {**r, "items": [a for a in r["items"] if isinstance(a, dict) and a.get("id") in bundled]}
        out.append(r)
    return out


def _signals(session, article_ids: list[int], rails: list[dict]) -> set[str]:
    from sqlalchemy import select

    from src.backup.attribution import lane_signal, signals_from_sources, table_signal
    from src.database.models import Article, Source

    out: set[str] = set()
    if article_ids:
        rows = session.execute(
            select(Source.domain, Source.source_type)
            .join(Article, Article.source_id == Source.id)
            .where(Article.id.in_(article_ids))
            .distinct()
        ).all()
        out |= signals_from_sources({"domain": d, "source_type": st} for d, st in rows)
    by_key = {r.get("key"): r for r in rails}
    if (by_key.get("places") or {}).get("places"):
        out.add(table_signal("places"))
    if ((by_key.get("map") or {}).get("lane") or {}).get("objects"):
        out.add(lane_signal("osm"))
    if ((by_key.get("wikipedia") or {}).get("lane") or {}).get("pages"):
        out.add(lane_signal("wiki"))
    return out


def dossier_selection(session, qid: str, lang: str = "en") -> DossierSelection | None:
    """The dossier of ``qid`` as an export: its article ids (stand-ins left out) and the block.

    ``None`` when ``qid`` is not a Wikidata item id."""
    from sqlalchemy import select

    from src.backup.attribution import attribution_dicts
    from src.database.models import Article
    from src.database.stand_in import not_a_stand_in_article
    from src.entities.dossier import qid_dossier

    d = qid_dossier(session, qid, lang)
    if d is None:
        return None
    ids = [int(i) for i in d.get("article_ids") or []]
    if ids:
        # A repair's stand-in is a place-holder for a lost row, never evidence (the same rule as
        # every other evidence selection).
        ids = [int(i) for i in session.execute(
            select(Article.id).where(Article.id.in_(ids), not_a_stand_in_article()).order_by(Article.id)
        ).scalars()]
    rails = _items_in_bundle(_without_watch_list(list(d.get("rails") or [])), set(ids))
    block = {
        "qid": d["qid"],
        "lang": d.get("lang"),
        "item": d.get("item"),
        "routes": d.get("routes"),
        "passport": d.get("passport"),
        "rails": rails,
        "not_joined": d.get("not_joined") or [],
        "rails_carried": [r.get("key") for r in rails],
        "rails_not_carried": [r.get("key") for r in d.get("not_joined") or []],
        "articles_total": int((d.get("passport") or {}).get("articles") or 0),
        "articles_in_bundle": len(ids),
        "articles_bounded": bool(d.get("article_ids_bounded")),
        "attribution": attribution_dicts(_signals(session, ids, rails)),
        "country": d.get("country"),
        "availability": d.get("availability"),
        "method": d.get("method"),
        "method_country": d.get("method_country"),
        "caveat": d.get("caveat"),
        "export_note": EXPORT_NOTE,
    }
    return DossierSelection(article_ids=ids, block=_stable(block))


def plan_summary(sel: DossierSelection) -> dict:
    """What the review screen lists about the dossier part of the file, before it is written."""
    b = sel.block
    return {
        "qid": b["qid"],
        "label": (b.get("item") or {}).get("label"),
        "rails_carried": b["rails_carried"],
        "rails_not_carried": b["rails_not_carried"],
        "articles_total": b["articles_total"],
        "articles_in_bundle": b["articles_in_bundle"],
        "articles_bounded": b["articles_bounded"],
        "attribution": b["attribution"],
    }
