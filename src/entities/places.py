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

**THE BODY IS NOT A CORPUS ARTICLE HERE.** It was composed on read (:func:`place_body`) while
Q823 (ODbL) was open, so that no OSM-derived Article could ride a backup before it was ruled;
Q823 = a (2026-09-29) lets OSM data leave with OSM's credit and the ODbL line, but nothing
here needed to change: the body's keywords still come from the ONE extractor the corpus uses,
and the Place is searchable through the omnibar's Places group (``src/api/search_omni.py``).
Row D makes notable Places Articles (Q817); :func:`place_body` is the text it will index.
The Place ROW itself rides a backup restore (``_merge_places``), credited by the attribution
seam.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

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
    # An entry that came from a file carries that file's own vintage (possibly none); only a City built
    # by hand, with no source, takes the caller's. A place artifact with no vintage never borrows the world file's.
    row.gazetteer_vintage = city.vintage if city.source is not None else vintage
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
    notable = _notable_pass(session, should_stop) if not stopped else None
    return {
        "osm_notable": notable,
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


#: The caveat of a Place read from an OSM country's notable objects rather than from a mention.
OSM_NOTABLE_CAVEAT = (
    "Read from the OpenStreetMap data of a country you read: a notable place (a settlement, an "
    "administrative area, or an object linked to Wikidata or Wikipedia). Names come from "
    "OpenStreetMap first, then Wikidata; a language with neither shows no name."
)


def materialise_notable(session, *, should_stop=None) -> dict:
    """Q817 = a: every NOTABLE object of every complete OSM country becomes a Place. Local only.

    Notable is the lane's own flag (``src/osm/tags.py:classify``): administrative areas, every
    ``place=*`` and any object carrying ``wikidata``/``wikipedia``. Two refinements, both
    stated: an administrative area is its RELATION (the ways of its border carry the same tags
    and are not places), and an object with no ``name`` is counted, never made a Place called
    nothing. A Place the gazetteer already resolved keeps its gazetteer facts; this adds where
    its geometry lives. The body stays composed on read, never an Article (row D's call).
    """
    from sqlalchemy import select

    from src.database.models import Place
    from src.osm.lane_models import OsmCountry, osm_objects_table
    from src.osm.tags import column_name
    from src.versioned import store

    out: dict[str, Any] = {"places": 0, "created": 0, "unnamed": 0, "border_ways": 0, "countries": [], "stopped": False}
    if not store.lane_exists("osm"):
        return out
    t = osm_objects_table
    col = lambda k: t.c[column_name(k)]  # noqa: E731 - one-line column lookup
    with store.lane_session("osm") as ls:
        countries = [c.alpha3 for c in ls.query(OsmCountry).filter_by(status="complete").order_by(OsmCountry.alpha3)]
        rows = ls.execute(
            select(t.c.osm_type, t.c.osm_id, t.c.kind, t.c.primary_key, t.c.primary_value, t.c.country_alpha3,
                   t.c.lat, t.c.lon, t.c.names, col("name"), col("wikidata"), col("population"))
            .where(t.c.notable.is_(True), t.c.country_alpha3.in_(countries))
            .order_by(t.c.country_alpha3, t.c.osm_type, t.c.osm_id)
        ).all()
    out["countries"] = countries
    from src.osm.places import TYPE_WORDS

    for i, (otype, oid, kind, pkey, pval, a3, lat, lon, names_json, name, qid, pop) in enumerate(rows):
        if should_stop is not None and should_stop():
            out["stopped"] = True
            break
        if kind == "admin" and otype != "r":
            out["border_ways"] += 1
            continue
        if not (name or "").strip():
            out["unnamed"] += 1
            continue
        pid = f"{TYPE_WORDS[otype]}/{oid}"
        row = session.get(Place, pid)
        if row is None:
            row = Place(id=pid, name=name[:200])
            out["created"] += 1
        names = json.loads(names_json) if names_json else {}
        if row.gazetteer_vintage is None:
            # Not resolved from a mention: every fact here is the lane's. The columns' widths
            # (200, 32) are the table's; OSM's own values rarely approach them.
            row.name = name[:200]
            row.kind = (pval if pkey == "place" else (f"{pkey}={pval}" if pkey else None) or "")[:32] or None
            row.names_json = json.dumps({k: v for k, v in names.items() if k in LANGS}, ensure_ascii=False, sort_keys=True)
            row.country_alpha3 = a3
            try:
                from src.osm.ingest import country_codes

                row.country = country_codes(a3)[0].lower()
            except ValueError:  # a code the lane stored but the catalogue does not know
                row.country = None
            row.lat, row.lon = lat, lon
            try:
                row.population = int(str(pop).replace(" ", "").replace(",", "")) if pop else None
            except ValueError:
                row.population = None      # a free-text population is not a number
        row.qid = row.qid or (qid if qid and re.fullmatch(r"Q\d+", qid) else None)
        if row.admin_path_json is None:
            row.admin_path_json = "[]"
        row.geometry_ref = f"osm.db:{pid}"
        row.as_of = datetime.now(UTC)
        session.add(row)
        out["places"] += 1
        if i % 1000 == 999:
            session.commit()
    session.commit()
    return out


def _notable_pass(session, should_stop) -> dict:
    """The OSM lane's part of the Places job: the name/address indexes, then the notable Places.

    Degrades to a named error rather than costing the mention pass its result."""
    try:
        from src.osm.places import refresh_indexes

        indexed = refresh_indexes()
        got = materialise_notable(session, should_stop=should_stop)
        return {**got, "indexed": sorted(indexed)}
    except Exception as exc:  # noqa: BLE001 - reported in the job's result, never silent
        _LOG.warning("places: the OSM lane's pass failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}


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


def mention_article_ids(session, place, *, cap: int = 20_000) -> tuple[list[int], int]:
    """The corpus articles naming this place (the rows :func:`mention_count` counts), lowest ids
    first, at most ``cap`` of them, and how many there are in all."""
    from sqlalchemy import select

    from src.database.models import ArticleMentionedPlace

    ids = session.execute(
        select(ArticleMentionedPlace.article_id).where(
            ArticleMentionedPlace.name.in_({place.name}),
            ArticleMentionedPlace.country == place.country,
            ArticleMentionedPlace.kind != "country",
        ).distinct().order_by(ArticleMentionedPlace.article_id)
    ).scalars().all()
    ids = [int(i) for i in ids]
    return ids[:cap], len(ids)


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
        "origin": "gazetteer" if place.gazetteer_vintage else ("osm-lane" if place.geometry_ref else "gazetteer"),
        "osm": _osm_facts(place),
        "caveat": (
            "Resolved from the place names found in article text through the gazetteer: a "
            "name match, never a confirmed event site. Names come from OpenStreetMap first, "
            "then Wikidata; a language with neither shows no name."
        ) if place.gazetteer_vintage or not place.geometry_ref else OSM_NOTABLE_CAVEAT,
    }


def _osm_facts(place) -> dict | None:
    """The OSM lane's row for this Place, when the lane holds it: its tag and the data's date."""
    if not (place.geometry_ref or "").startswith("osm.db:"):
        return None
    try:
        from src.osm.places import object_card

        card = object_card(place.geometry_ref.split(":", 1)[1])
    except Exception:  # noqa: BLE001 - a locked or missing lane: the card still opens
        _LOG.debug("place card: the OSM lane could not be read", exc_info=True)
        return {"held": None}
    if card is None:
        return {"held": False}
    return {"held": True, "tag": card["tag"], "vintage": card["vintage"], "country_name": card["country_name"]}


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
