"""The Place entity: resolution, names ×12, its body, its card, and the wiki join (Q818, Q827, Q819).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q818 = a: «``Place(id = OSM type+id, qid, kind, admin path, names ×12, geometry ref, as_of)`` with
``article_mentioned_places`` resolving into it; its body = the Wikidata/Wikipedia description +
its OSM metadata rendered as metadata; keywords come from that text; it is searchable and
indexed.» Q827 = a: «OSM ``name:xx`` first, Wikidata labels as the fallback, the source shown in
the hover.» Q819 step 2: «OSM objects tagged ``wikidata``/``wikipedia`` -> the same Place as the
wiki page.»

**RESOLUTION CHANGES HOW A PLACE IS FOUND, NEVER WHAT IS FOUND** (the gazetteer-index lesson).
A mention row keeps its name, country, kind, counts and coordinates exactly as the extractor
wrote them. Resolution is a READ: the gazetteer entry the extractor already chose for that
``(name, country)`` -- through the SAME ``lookup`` -- and, when that entry names an OSM object,
the Place keyed on it. Nothing is written back to a mention row, so there is no column to
migrate, carry or heal, and a restore re-resolves by construction.

**A PLACE EXISTS ONLY WHERE THE GAZETTEER NAMES AN OSM OBJECT.** The shipped sample names none,
so on an install without the built artifact (Q805) every mention stays unresolved, and every
surface says why ("the gazetteer has no OSM object for this place") rather than inventing one.

**ONLY WHAT THE CORPUS MENTIONS BECOMES A ROW.** :func:`resolve_mentioned` materialises a Place
for each distinct mentioned place the gazetteer resolves, and nothing else -- the same bound
Q724 puts on the Wikidata cache. Row D (Q817) widens Places to every notable place of an
ingested country.

**THE BODY IS NOT A CORPUS ARTICLE HERE.** A corpus Article rides every backup and export, and
Q823 ⛔ (ODbL) keeps OSM-derived content inside the machine until it is ruled. So the body is
composed on read (:func:`place_body`), its keywords come from the ONE extractor the corpus uses,
and the Place is searchable through the omnibar's Places group (``src/api/search_omni.py``) --
all without a row that could leave the machine. Row D makes notable Places Articles (Q817) when
Q823 allows it; :func:`place_body` is the text it will index.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from src.entities.items import cached_item, item_payload

_LOG = logging.getLogger(__name__)

#: The twelve interface languages, the scope of "names ×12".
LANGS: tuple[str, ...] = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

NAME_SOURCE_OSM = "osm"            # OSM's name:xx tag for the reader's language (Q827, first)
NAME_SOURCE_WIKIDATA = "wikidata"  # the Wikidata label (Q827, the fallback)
NAME_SOURCE_LOCAL = "local"        # neither has one: the local OSM `name`, said so

#: Why a mentioned place did not resolve. Tokens, because they are counted and shown ×12.
UNRESOLVED_COUNTRY_LEVEL = "country-level"      # a country mention: the admin boundaries are row D's
UNRESOLVED_NOT_IN_GAZETTEER = "not-in-gazetteer"
UNRESOLVED_NO_OSM_OBJECT = "no-osm-object"      # the gazetteer knows it but names no OSM object


def _gazetteer():
    from src.catalog.cities import cached_index, gazetteer_meta

    return cached_index(), gazetteer_meta()


def gazetteer_entry(name: str | None, country: str | None, kind: str | None):
    """``(City | None, unresolved_reason | None)`` for a mention, through the extractor's lookup."""
    from src.catalog.cities import lookup

    if (kind or "").strip().lower() == "country":
        return None, UNRESOLVED_COUNTRY_LEVEL
    index, _meta = _gazetteer()
    hit = lookup(index, name or "", country)
    if hit is None:
        return None, UNRESOLVED_NOT_IN_GAZETTEER
    if not hit.osm:
        return hit, UNRESOLVED_NO_OSM_OBJECT
    return hit, None


def _alpha3(cc: str | None) -> str | None:
    if not cc:
        return None
    try:
        from src.catalog.countries import to_iso3

        return to_iso3(cc)
    except Exception:  # noqa: BLE001 - a display code, never worth failing a resolution
        return None


def materialise(session, city, *, vintage: str | None) -> str:
    """Upsert the Place for a gazetteer entry that names an OSM object. Returns its id."""
    from src.database.models import Place

    assert city.osm, "a Place is keyed on its OSM object; the caller checks for one"
    row = session.get(Place, city.osm) or Place(id=city.osm)
    row.qid = city.qid
    row.kind = city.kind
    row.name = city.name
    row.names_json = json.dumps(city.names or {}, ensure_ascii=False, sort_keys=True)
    row.country = city.country
    row.country_alpha3 = _alpha3(city.country)
    if row.admin_path_json is None:
        row.admin_path_json = "[]"
    row.lat, row.lon = city.lat, city.lon
    row.population = city.population
    row.gazetteer_vintage = vintage
    row.as_of = datetime.now(UTC)
    session.add(row)
    return row.id


def resolve_mention(session, name: str | None, country: str | None, kind: str | None) -> dict:
    """``{place_id, reason}`` for one mention -- a READ; materialises nothing."""
    city, reason = gazetteer_entry(name, country, kind)
    if reason is not None:
        return {"place_id": None, "reason": reason}
    from src.database.models import Place

    pid = city.osm
    return {"place_id": pid, "reason": None, "materialised": session.get(Place, pid) is not None}


def resolve_mentioned(session, *, should_stop=None) -> dict:
    """Materialise a Place for every distinct mentioned place the gazetteer resolves. Local only.

    Reads the DISTINCT ``(name, country, kind)`` of the mention table -- the same grouping
    ``corpus_where`` shows -- so the work is bounded by the corpus's vocabulary of places, not
    by its size. Counts every outcome under its own name; never a score.
    """
    from sqlalchemy import func, select

    from src.database.models import ArticleMentionedPlace

    _index, meta = _gazetteer()
    rows = session.execute(
        select(
            ArticleMentionedPlace.name, ArticleMentionedPlace.country, ArticleMentionedPlace.kind,
            func.count(func.distinct(ArticleMentionedPlace.article_id)),
        ).group_by(ArticleMentionedPlace.name, ArticleMentionedPlace.country, ArticleMentionedPlace.kind)
    ).all()
    unresolved: dict[str, int] = {}
    resolved_mentions = 0
    place_ids: set[str] = set()
    stopped = False
    for i, (name, cc, kind, _n) in enumerate(rows):
        if should_stop is not None and should_stop():
            stopped = True
            break
        city, reason = gazetteer_entry(name, cc, kind)
        if reason is not None:
            unresolved[reason] = unresolved.get(reason, 0) + 1
            continue
        place_ids.add(materialise(session, city, vintage=meta.get("vintage")))
        resolved_mentions += 1
        if i % 500 == 499:
            session.commit()
    session.commit()
    return {
        "distinct_mentions": len(rows),
        "resolved": resolved_mentions,
        "places": len(place_ids),
        "unresolved": dict(sorted(unresolved.items())),
        "stopped": stopped,
        "gazetteer": meta,
        "method": (
            "Each distinct mentioned place (name, country, kind) looked up in the gazetteer "
            "the way the extractor looked it up; a Place is written only where the gazetteer "
            "entry names an OpenStreetMap object. No network call. Counts only."
        ),
    }


def _names(place) -> dict[str, str]:
    try:
        v = json.loads(place.names_json) if place.names_json else {}
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def display_name(place, lang: str, item: dict | None = None) -> dict:
    """The name in ``lang`` and WHERE it came from (Q827 = a). Never a fabricated name.

    ``name:xx`` first, the Wikidata label second; with neither, the local OSM ``name`` is
    shown and ``source`` says it is the local name, so a reader is never told a place is
    called something in their language that nobody called it.
    """
    tl = (lang or "").strip().casefold()
    osm = _names(place).get(tl)
    if osm:
        return {"name": osm, "source": NAME_SOURCE_OSM, "lang": tl}
    labels = (item or {}).get("labels") or {}
    if (item or {}).get("status") == "ok" and labels.get(tl):
        return {"name": labels[tl], "source": NAME_SOURCE_WIKIDATA, "lang": tl}
    return {"name": place.name, "source": NAME_SOURCE_LOCAL, "lang": tl}


def names_x12(place, item: dict | None = None) -> list[dict]:
    """Every interface language, each with its name and source, or an honest absence."""
    out = []
    for lang in LANGS:
        d = display_name(place, lang, item)
        if d["source"] == NAME_SOURCE_LOCAL:
            out.append({"lang": lang, "name": None, "source": None})
        else:
            out.append(d)
    return out


def place_body(place, item: dict | None, lang: str = "en") -> dict:
    """Q818's body: the Wikidata description, then the OSM metadata rendered AS metadata.

    Two parts, kept apart: ``description`` is prose a source wrote (Wikidata's, in ``lang``
    when it has one, else English, else none -- and the language is named); ``metadata`` is
    a list of labelled facts, never run together into a sentence that would read as prose
    nobody wrote. ``text`` is the two joined, the input the keyword extractor reads.
    """
    descs = (item or {}).get("descriptions") or {}
    tl = (lang or "").strip().casefold()
    d_lang = tl if descs.get(tl) else ("en" if descs.get("en") else None)
    description = descs.get(d_lang) if d_lang else None
    meta: list[dict] = [
        {"key": "osm", "value": place.id},
        {"key": "kind", "value": place.kind},
        {"key": "country", "value": place.country_alpha3 or (place.country or "").upper() or None},
        {"key": "population", "value": place.population},
        {"key": "coordinates",
         "value": ({"lat": place.lat, "lon": place.lon} if place.lat is not None and place.lon is not None else None)},
        {"key": "qid", "value": place.qid},
    ]
    claims = (item or {}).get("claims") or {}
    if claims.get("P571"):
        meta.append({"key": "inception", "value": claims["P571"][0]})
    lines = [f"{m['key']}: {m['value']}" for m in meta if m["value"] not in (None, "", [])]
    text = "\n".join(([description] if description else []) + [place.name] + lines)
    return {"description": description, "description_lang": d_lang, "metadata": meta, "text": text}


def body_keywords(place, item: dict | None, limit: int = 12) -> list[dict]:
    """Keywords from the body, through the corpus's own extractor. Counts, never a score."""
    from src.analytics.extract import BaselineExtractor

    body = place_body(place, item, "en")
    if not body["description"]:
        # The metadata is labelled facts, not prose: extracting "population" and "kind" from
        # it would mint keywords that describe the card rather than the place.
        return []
    terms = BaselineExtractor().extract(body["description"], title=place.name,
                                        language=body["description_lang"] or "en")
    terms.sort(key=lambda t: (-t.count, t.normalized))
    return [{"term": t.term, "kind": t.kind, "count": t.count} for t in terms[:limit]]


def wiki_pages_for_qid(qid: str | None, limit: int = 24) -> dict:
    """Q819 step 2's wiki side: the lane's pages that carry ``qid``. A READ of ``wiki.db``.

    Both lane tables that hold a page's QID are asked: the stream's followed pages
    (``versioned_entities``) and the walk's listed ones (``wiki_walk_pages``). A lane that has
    never run answers with a named absence, never an empty list that reads as "no page".
    """
    from src.entities.wikidata_items import is_qid

    if not is_qid(qid):
        return {"available": True, "pages": [], "reason": "no-qid"}
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from src.versioned.store import LaneAbsentError, lane_path, lane_session

    if not lane_path("wiki").is_file():
        return {"available": False, "pages": [], "reason": "lane-never-run"}
    pages: list[dict] = []
    try:
        from src.versioned.models import VersionedEntity
        from src.wiki.identity import parse_external_id
        from src.wiki.lane_models import WikiWalkPage

        with lane_session("wiki") as lane:
            for ent in lane.execute(
                select(VersionedEntity).where(VersionedEntity.qid == qid).order_by(VersionedEntity.id).limit(limit)
            ).scalars():
                try:
                    wiki = parse_external_id(ent.external_id).wiki
                except ValueError:
                    wiki = None
                pages.append({"edition": wiki, "title": ent.title, "external_id": ent.external_id,
                              "followed": True})
            seen = {(p["edition"], p["title"]) for p in pages}
            try:
                for wp in lane.execute(
                    select(WikiWalkPage).where(WikiWalkPage.qid == qid).order_by(WikiWalkPage.edition).limit(limit)
                ).scalars():
                    if (wp.edition, wp.title) not in seen:
                        pages.append({"edition": wp.edition, "title": wp.title,
                                      "external_id": f"{wp.edition}:p{wp.page_id}", "followed": False})
            except SQLAlchemyError:
                # A lane file written before the walk existed has no walk table: the stream's
                # pages above still answer.
                pass
    except LaneAbsentError:
        return {"available": False, "pages": [], "reason": "lane-never-run"}
    except SQLAlchemyError:
        return {"available": False, "pages": [], "reason": "lane-unreadable"}
    return {"available": True, "pages": pages[:limit]}


def place_for_wiki_page(session, external_id: str) -> dict:
    """Q819 step 2 from the wiki side: the Place a lane page resolves to, by its QID."""
    from sqlalchemy import select

    from src.database.models import Place
    from src.versioned.models import VersionedEntity
    from src.versioned.store import LaneAbsentError, lane_path, lane_session

    if not lane_path("wiki").is_file():
        return {"place_id": None, "reason": "lane-never-run"}
    try:
        with lane_session("wiki") as lane:
            ent = lane.execute(
                select(VersionedEntity).where(VersionedEntity.external_id == external_id)
            ).scalar_one_or_none()
            qid = ent.qid if ent is not None else None
    except LaneAbsentError:
        return {"place_id": None, "reason": "lane-never-run"}
    if ent is None:
        return {"place_id": None, "reason": "no-such-page"}
    if not qid:
        return {"place_id": None, "reason": "page-has-no-qid", "qid": None}
    ids = [p for (p,) in session.execute(select(Place.id).where(Place.qid == qid).order_by(Place.id))]
    if len(ids) > 1:
        # Two OSM objects carrying one QID (a city node and its boundary relation, say) is
        # a real shape. Both are named; neither is picked.
        return {"place_id": None, "reason": "several-places", "qid": qid, "candidates": ids}
    if not ids:
        return {"place_id": None, "reason": "no-place-with-this-qid", "qid": qid}
    return {"place_id": ids[0], "reason": None, "qid": qid}


def mention_count(session, place) -> int:
    """How many corpus articles mention this place, by the mention rows that resolve into it."""
    from sqlalchemy import func, select

    from src.database.models import ArticleMentionedPlace

    names = {place.name}
    n = session.execute(
        select(func.count(func.distinct(ArticleMentionedPlace.article_id))).where(
            ArticleMentionedPlace.name.in_(names),
            ArticleMentionedPlace.country == place.country,
            ArticleMentionedPlace.kind != "country",
        )
    ).scalar()
    return int(n or 0)


def place_card(session, place_id: str, lang: str = "en") -> dict | None:
    """Everything a Place card shows, or None for an unknown id. No network call."""
    from src.database.models import Place

    place = session.get(Place, place_id)
    if place is None:
        return None
    item = item_payload(cached_item(session, place.qid))
    title = display_name(place, lang, item)
    body = place_body(place, item, lang)
    try:
        admin = json.loads(place.admin_path_json) if place.admin_path_json else []
    except ValueError:
        admin = []
    return {
        "id": place.id,
        "qid": place.qid,
        "kind": place.kind,
        "title": title,
        "local_name": place.name,
        "names": names_x12(place, item),
        "country": place.country,
        "country_alpha3": place.country_alpha3,
        "admin_path": admin,
        "geometry_ref": place.geometry_ref,
        "lat": place.lat,
        "lon": place.lon,
        "population": place.population,
        "gazetteer_vintage": place.gazetteer_vintage,
        "as_of": place.as_of.isoformat() if place.as_of else None,
        "item": {
            "status": (item or {}).get("status") if item else "not-fetched",
            "as_of": (item or {}).get("as_of") if item else None,
        },
        "body": body,
        "keywords": body_keywords(place, item),
        "articles": mention_count(session, place),
        "wiki": wiki_pages_for_qid(place.qid),
        "caveat": (
            "Resolved from the place names found in article text through the gazetteer: a "
            "name match, never a confirmed event site. Names come from OpenStreetMap first, "
            "then Wikidata; a language with neither shows no name."
        ),
    }


def search_places(session, q: str, limit: int = 8) -> dict:
    """Places whose name, in any language either source gives, contains ``q``. Bounded."""
    from sqlalchemy import or_, select

    from src.database.models import Place, WikidataItem

    pat = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    base = (
        select(Place)
        .outerjoin(WikidataItem, WikidataItem.qid == Place.qid)
        .where(or_(
            Place.name.ilike(pat, escape="\\"),
            Place.names_json.ilike(pat, escape="\\"),
            WikidataItem.labels_json.ilike(pat, escape="\\"),
        ))
    )
    from sqlalchemy import func

    total = session.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
    rows = session.execute(base.order_by(Place.population.desc().nullslast(), Place.id).limit(limit)).scalars().all()
    return {
        "items": [
            {"id": p.id, "name": p.name, "qid": p.qid, "kind": p.kind,
             "country": p.country_alpha3 or (p.country or "").upper() or None}
            for p in rows
        ],
        "total": int(total),
    }
