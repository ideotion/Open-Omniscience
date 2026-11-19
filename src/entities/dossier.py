"""The dossier seed (S05-11 S4): one Wikidata item, and every rail this machine can join to it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief, verbatim: «one entity / topic page joining the rails that exist (news, wiki, law, map,
Places) by QID — a SEED: it states which rails it joins and which it does not; the ≥ 6 rails
bar is 0.8's.» Acceptance: «a QID page renders from fixture rows with its rail list and the
corpus passport (A-1).»

**HOW AN ARTICLE JOINS THE ITEM -- THREE ROUTES, EACH COUNTED.** No new identity rule: every
route is one the entity spine (:mod:`src.entities.spine`) already walks.

* *Named entities.* A person or organisation the corpus mentions whose name
  :func:`~src.entities.spine.entity_qid` resolves to THIS item -- exactly one item, or none.
* *Keywords.* An article keyword whose term is a member of a ring carrying this item, in that
  member's language, and which names no other item (the several-senses refusal, Q412).
* *Places.* The mentions the Place card counts, for every Place whose gazetteer QID is this item.

The article set is the UNION of the three. A route that joins nothing says so with a zero.

**THE RAILS SPLIT THAT SET BY CHANNEL, AND ADD WHAT IS KEYED BY QID OUTSIDE IT.** News and web,
Wikipedia and law are the joined articles split by their source's provenance class (a channel
fact, :mod:`src.catalog.provenance`). Wikipedia also lists the pages the Wikipedia lane holds for
the item; Places lists the Places; the map lists the OpenStreetMap lane's objects tagged with the
item. Rails the app has but cannot join by QID are NAMED with their reason, never left out: a
seed that listed only what it joins would read as the whole picture.

**THE COUNTRY RAILS (S08-01 S2, 0.8 row A).** Statistics, climate, the agenda and its elections are
keyed by COUNTRY, not by item, so they join only an item that IS a country: a Place of OSM kind
``country`` carries it and every such Place names the same country. A city's item never gets its
country's rows (they are about another item), and a disagreement picks none. A series is named with
its periods and dates and no value: a value needs its unit, vintage and comparability fields beside
it. S3's counter says which joined rails had rows on this machine; a rail without rows is a gap.

**NO VERDICT, NO SCORE.** Counts, lists and the passport. No network call: every read is local.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, func, or_, select, union

from src.entities.wikidata_items import is_qid

_LOG = logging.getLogger(__name__)

#: How many article ids the payload carries for "open these in the analysis window" -- the
#: window's own bound (``openAnalysisForIds`` keeps 5,000). The COUNT is never bounded.
IDS_FOR_ANALYSIS = 5_000

#: How many rows a list rail shows (Places, lane pages, map objects). Its total is stated.
_LIST_LIMIT = 24

#: The joined rails, in display order. ``news`` is every provenance class that is not
#: Wikipedia or law: the press, the plain web, newsletters, statistics, cited sources, hazards.
JOINED_RAILS = ("news", "wikipedia", "law", "places", "map")

#: The rails keyed by COUNTRY, not by item (S08-01 S2, 0.8 row A). They join an item only when
#: the item IS a country: a Place of OSM kind ``country`` carries it, and every such Place names
#: the same country. A city's item does not get its country's figures: those are about another
#: item, and showing them here would say they were about the city.
COUNTRY_RAILS = ("stats", "climate", "agenda", "elections")

#: Why a country rail is not joined, by code. The UI keys the words.
COUNTRY_ABSENCE = {
    "not-a-country": (
        "Joined only for a country: no Place on this machine of kind country carries this item."),
    "several-countries": (
        "The Places of kind country carrying this item name more than one country, so none is "
        "picked."),
}

#: Rails the app holds that this dossier does NOT join, each with why. Codes; the UI keys the words.
NOT_JOINED = (
    ("markets", "Market series are keyed by ticker symbol, not by a Wikidata item."),
    ("law_versions",
     "Tracked law texts are keyed by their legal identifier; they join here only through the "
     "corpus articles they were ingested as."),
)

METHOD = (
    "Articles join this item three ways: a person or organisation they mention whose name "
    "resolves to exactly this Wikidata item; an article keyword that is a name of this item "
    "in its own language and of no other item; a place they mention that resolves to a Place "
    "carrying this item. The rails split those articles by their source's channel, then add "
    "what this machine holds under the same item: the Wikipedia lane's pages, the Places and "
    "the OpenStreetMap lane's objects. No network call is made."
)

#: The method's second part, shown only when the item is a country (its own i18n key).
COUNTRY_METHOD = (
    "This item is a country, so the rails keyed by country join too: the statistics and climate "
    "series stored for it, named with their periods and dates but no value, and the agenda's "
    "events and elections for it."
)

CAVEAT = (
    "A seed, not a portrait: it joins the rails listed and names the ones it does not. A name "
    "that could mean several items joins none of them, so an article about this item that "
    "only uses such a name is missing here."
)


def _item_block(session, qid: str, lang: str) -> dict:
    from src.entities.items import cached_item, item_payload

    row = cached_item(session, qid)
    p = item_payload(row)
    if p is None:
        return {"status": "not-cached", "label": None, "description": None, "as_of": None}
    labels = p.get("labels") or {}
    descs = p.get("descriptions") or {}

    def _pick(d: dict) -> tuple[str | None, str | None]:
        for code in (lang, "en"):
            if d.get(code):
                return d[code], code
        for code in sorted(d):
            if d[code]:
                return d[code], code
        return None, None

    label, label_lang = _pick(labels)
    desc, desc_lang = _pick(descs)
    return {
        "status": p.get("status"),
        "label": label,
        "label_lang": label_lang,
        "description": desc,
        "description_lang": desc_lang,
        "as_of": p.get("as_of"),
    }


def item_terms(qid: str) -> dict[str, set[str]]:
    """``{language: {normalized term}}`` -- the item's names the rings carry, unambiguous only.

    A member that also names another item is dropped here: it is the several-senses case the
    spine refuses, and joining through it would merge two items on a coin flip.
    """
    from src.analytics import equivalence
    from src.entities.spine import entity_qid

    out: dict[str, set[str]] = {}
    for ring in equivalence.load_rings():
        if ring.qid != qid:
            continue
        for lang, term in ring.members:
            q, _declined = entity_qid(term, lang)
            if q == qid:
                out.setdefault(lang, set()).add(term)
    return out


def _norm(text: str) -> str:
    """The rings' own normalisation (whitespace collapsed, casefolded)."""
    return " ".join((text or "").split()).casefold()


def _case_variants(terms: set[str]) -> list[str]:
    """The stored spellings a normalised term can take: as written, UPPER (an acronym is stored
    upper-case, WHO != who), Title, and Capitalised. SQL ``IN`` is case-sensitive and SQLite's
    ``lower()`` folds only ASCII, so the candidates are asked for by name and CONFIRMED in Python
    with the rings' own normalisation."""
    out: set[str] = set()
    for t in terms:
        out.update({t, t.upper(), t.title(), t.capitalize()})
    return sorted(out)


def _entity_names(session, terms: dict[str, set[str]], qid: str) -> list[str]:
    """The ArticleEntity names (as stored) that resolve to ``qid``."""
    from src.database.models import ArticleEntity
    from src.entities.spine import entity_qid

    every = set().union(*terms.values()) if terms else set()
    if not every:
        return []
    names: list[str] = []
    for (name,) in session.execute(
        select(ArticleEntity.name).where(ArticleEntity.name.in_(_case_variants(every))).distinct()
    ):
        if name and _norm(name) in every and entity_qid(name)[0] == qid:
            names.append(name)
    return sorted(names)


def _keyword_ids(session, terms: dict[str, set[str]], qid: str) -> tuple[list[int], list[str]]:
    """The Keyword rows that are a name of ``qid`` in their own language (or, untagged, in any)."""
    from src.database.models import Keyword
    from src.entities.spine import entity_qid

    every = set().union(*terms.values()) if terms else set()
    if not every:
        return [], []
    ids: list[int] = []
    shown: set[str] = set()
    for kid, stored, lang in session.execute(
        select(Keyword.id, Keyword.normalized_term, Keyword.language).where(
            Keyword.normalized_term.in_(_case_variants(every))
        )
    ):
        norm = _norm(stored)
        code = (lang or "").split("-")[0].lower()
        ok = norm in terms.get(code, set()) if code else entity_qid(stored)[0] == qid
        if ok:
            ids.append(int(kid))
            shown.add(stored)
    return ids, sorted(shown)


def _places(session, qid: str) -> list:
    from src.database.models import Place

    return list(session.execute(select(Place).where(Place.qid == qid).order_by(Place.id)).scalars())


def _place_clause(places):
    from src.database.models import ArticleMentionedPlace as M

    return or_(*[
        and_(M.name == p.name, M.country == p.country, M.kind != "country") for p in places
    ])


def _route_selects(session, qid: str) -> tuple[dict, list]:
    """Each route's SELECT of article ids, and what it matched on."""
    from src.database.derived_views import KeywordMentionRead, require_mentions_view
    from src.database.models import ArticleEntity, ArticleMentionedPlace
    from src.database.stand_in import not_a_stand_in_article_id

    terms = item_terms(qid)
    names = _entity_names(session, terms, qid)
    kw_ids, kw_terms = _keyword_ids(session, terms, qid)
    places = _places(session, qid)
    routes: dict = {}
    if names:
        routes["entities"] = (
            select(ArticleEntity.article_id).where(
                ArticleEntity.name.in_(names), not_a_stand_in_article_id(ArticleEntity.article_id)), names)
    if kw_ids:
        # The mentions table is where indexing writes an article's keywords; article_keywords is
        # a legacy link table nothing but a backup restore fills, so joining through it found
        # no article on a real corpus (walked 2026-09-30). Read through the R96 seam
        # (the _all view), never the write model, so the segmented-index move does not
        # have to touch this file again.
        require_mentions_view(session)
        routes["keywords"] = (
            select(KeywordMentionRead.article_id).where(
                KeywordMentionRead.keyword_id.in_(kw_ids), not_a_stand_in_article_id(KeywordMentionRead.article_id)), kw_terms)
    if places:
        routes["places"] = (
            select(ArticleMentionedPlace.article_id).where(
                _place_clause(places), not_a_stand_in_article_id(ArticleMentionedPlace.article_id)),
            [p.name for p in places])
    return routes, places


def _count(session, sel) -> int:
    sub = sel.distinct().subquery()
    return int(session.execute(select(func.count()).select_from(sub)).scalar() or 0)


def _map_objects(qid: str) -> dict:
    """The OpenStreetMap lane's objects whose ``wikidata`` tag is ``qid``. A READ of the lane."""
    from sqlalchemy.exc import SQLAlchemyError

    from src.versioned.store import LaneAbsentError, lane_path, lane_session

    if not lane_path("osm").is_file():
        return {"available": False, "objects": [], "reason": "lane-never-run"}
    try:
        from src.osm.lane_models import osm_objects_table as T
        from src.osm.tags import column_name

        wd = T.c[column_name("wikidata")]
        nm = T.c[column_name("name")]
        with lane_session("osm") as lane:
            rows = lane.execute(
                select(T.c.osm_type, T.c.osm_id, T.c.kind, T.c.country_alpha3, nm, T.c.lat, T.c.lon)
                .where(wd == qid).order_by(T.c.osm_type, T.c.osm_id).limit(_LIST_LIMIT)
            ).all()
    except LaneAbsentError:
        return {"available": False, "objects": [], "reason": "lane-never-run"}
    except (SQLAlchemyError, KeyError):
        return {"available": False, "objects": [], "reason": "lane-unreadable"}
    return {
        "available": True,
        "objects": [
            {"osm": f"{t}{i}", "kind": k, "country_alpha3": c, "name": n, "lat": la, "lon": lo}
            for t, i, k, c, n, la, lo in rows
        ],
    }


def item_country(places) -> tuple[dict | None, str | None]:
    """``({"iso2", "iso3"}, None)`` when the item is ONE country, else ``(None, absence code)``.

    The item is a country when a Place of OSM kind ``country`` carries it. Several such Places
    naming different countries pick none (``several-countries``): a guess here would hang one
    country's figures on another."""
    from src.catalog.countries import to_iso2, to_iso3

    codes = set()
    for p in places:
        if (p.kind or "").strip().lower() != "country":
            continue
        iso2 = to_iso2(p.country) or to_iso2(p.country_alpha3)
        if iso2:
            codes.add(iso2)
    if not codes:
        return None, "not-a-country"
    if len(codes) > 1:
        return None, "several-countries"
    iso2 = codes.pop()
    return {"iso2": iso2, "iso3": to_iso3(iso2)}, None


def _area_forms(country: dict) -> list[str]:
    """The ``ref_area`` spellings a statistics row can carry for this country (as published)."""
    return sorted({c.upper() for c in (country.get("iso3"), country.get("iso2")) if c})


def _series_rail(session, country: dict, *, climate: bool) -> dict:
    """The statistics series stored for the country: series, periods and dates, NO value.

    A value needs its unit, its vintage and its comparability fields beside it, which a list
    row cannot hold honestly; the series opens where those are shown. ``climate`` splits the
    rows by producer: the Climate tab's datasets on one rail, every other producer on the other.
    """
    from src.database.models import StatFigure as F
    from src.stats.climate import DATASETS

    climate_agencies = sorted({d.agency for d in DATASETS.values()})
    agency_clause = F.agency.in_(climate_agencies) if climate else F.agency.not_in(climate_agencies)
    where = (F.ref_area.in_(_area_forms(country)), agency_clause)
    total = int(session.execute(
        select(func.count()).select_from(
            select(F.agency, F.series_id).where(*where).distinct().subquery())
    ).scalar() or 0)
    rows = session.execute(
        select(F.agency, F.series_id, F.ref_area, func.count(func.distinct(F.time_period)),
               func.min(F.time_period), func.max(F.time_period), func.max(F.extracted_at))
        .where(*where)
        .group_by(F.agency, F.series_id, F.ref_area)
        .order_by(F.agency, F.series_id, F.ref_area)
        .limit(_LIST_LIMIT)
    ).all()
    series = [
        {"agency": a, "series_id": sid, "ref_area": area, "periods": int(n),
         "first": first, "last": last, "fetched": fetched}
        for a, sid, area, n, first, last, fetched in rows
    ]
    out: dict = {"count": total, "series": series}
    if climate:
        licences = {d.agency: d.licence for d in DATASETS.values()}
        out["licences"] = {a: licences[a] for a in sorted({r["agency"] for r in series})
                           if a in licences}
    return out


def _agenda_rail(country: dict, *, elections: bool) -> dict:
    """The agenda's events for the country (the curated catalogue, read locally).

    ``elections`` keeps that calendar apart: its dates carry the ruled confidence tiers."""
    from src.civic.elections import ELECTIONS_CALENDAR
    from src.events.catalog import agenda

    events = [e for e in agenda(country=country["iso2"])
              if (e.get("calendar") == ELECTIONS_CALENDAR) == elections]
    # The date's own confidence and caveat travel with it (an election's tier, a window, a
    # projection's year): a date without them would read as more certain than it is.
    keep = ("title", "calendar", "next_occurrence", "month", "until_year", "confirmed",
            "date_confidence", "date_caveat", "passed", "projection")
    return {
        "count": len(events),
        "events": [{k: e.get(k) for k in keep if k in e} for e in events[:_LIST_LIMIT]],
    }


def _country_rails(session, places) -> tuple[list[dict], list[dict], dict | None]:
    """The country rails (joined) or their absence (not joined), and the country they used."""
    country, absence = item_country(places)
    if country is None:
        absence = absence or "not-a-country"
        reason = COUNTRY_ABSENCE[absence]
        return [], [{"key": k, "joined": False, "code": absence, "reason": reason}
                    for k in COUNTRY_RAILS], None
    rails = [
        {"key": "stats", "joined": True, "country": country, **_series_rail(session, country, climate=False)},
        {"key": "climate", "joined": True, "country": country, **_series_rail(session, country, climate=True)},
        {"key": "agenda", "joined": True, "country": country, **_agenda_rail(country, elections=False)},
        {"key": "elections", "joined": True, "country": country, **_agenda_rail(country, elections=True)},
    ]
    return rails, [], country


def rail_has_rows(rail: dict) -> bool:
    """Whether a joined rail found anything on this machine (S3's availability counter)."""
    key = rail.get("key")
    if key in ("news", "wikipedia", "law"):
        if rail.get("articles"):
            return True
        return key == "wikipedia" and bool((rail.get("lane") or {}).get("pages"))
    if key == "map":
        return bool((rail.get("lane") or {}).get("objects"))
    return bool(rail.get("count"))


def qid_dossier(session, qid: str, lang: str = "en") -> dict | None:
    """The dossier of ``qid``, or None when ``qid`` is not a QID. Local reads only."""
    from src.analytics.passport import corpus_passport
    from src.catalog.provenance import LAW, WIKIPEDIA, provenance_of
    from src.database.models import Article, Source
    from src.entities.places import mention_count, wiki_pages_for_qid

    if not is_qid(qid):
        return None
    lang = (lang or "en").split("-")[0].strip().lower() or "en"
    routes, places = _route_selects(session, qid)

    route_counts = {
        key: {"articles": _count(session, routes[key][0]) if key in routes else 0,
              "matched_on": routes[key][1] if key in routes else []}
        for key in ("entities", "keywords", "places")
    }

    if routes:
        ids_sel = union(*[r[0] for r in routes.values()])
        ids_sub = select(ids_sel.subquery().c[0])
        passport = corpus_passport(session, ids_sub)
        by_source = session.execute(
            select(Source.id, Source.domain, Source.source_type, func.count(Article.id))
            .join(Article, Article.source_id == Source.id)
            .where(Article.id.in_(ids_sub.scalar_subquery()))
            .group_by(Source.id)
        ).all()
        ids = [int(i) for i in session.execute(
            select(Article.id).where(Article.id.in_(ids_sub.scalar_subquery()))
            .order_by(Article.id).limit(IDS_FOR_ANALYSIS)
        ).scalars()]
    else:
        passport = corpus_passport(session, select(Article.id).where(Article.id.is_(None)))
        by_source = []
        ids = []

    channels: dict[str, int] = {}
    for _sid, dom, st, k in by_source:
        cls = provenance_of(dom, st)
        channels[cls] = channels.get(cls, 0) + int(k)
    news_channels = {c: k for c, k in sorted(channels.items()) if c not in (WIKIPEDIA, LAW)}

    wiki_lane = wiki_pages_for_qid(qid, limit=_LIST_LIMIT)
    map_lane = _map_objects(qid)
    rails = [
        {"key": "news", "joined": True, "articles": sum(news_channels.values()),
         "by_channel": news_channels},
        {"key": "wikipedia", "joined": True, "articles": channels.get(WIKIPEDIA, 0),
         "lane": wiki_lane},
        {"key": "law", "joined": True, "articles": channels.get(LAW, 0)},
        {"key": "places", "joined": True, "count": len(places),
         "places": [{"id": p.id, "name": p.name, "kind": p.kind, "country": p.country,
                     "articles": mention_count(session, p)} for p in places[:_LIST_LIMIT]]},
        {"key": "map", "joined": True, "lane": map_lane},
    ]
    country_rails, country_absent, country = _country_rails(session, places)
    rails += country_rails
    not_joined = country_absent + [{"key": k, "joined": False, "reason": r} for k, r in NOT_JOINED]
    with_rows = [r["key"] for r in rails if rail_has_rows(r)]

    return {
        "qid": qid,
        "lang": lang,
        "item": _item_block(session, qid, lang),
        "routes": route_counts,
        "passport": passport,
        "rails": rails,
        "not_joined": not_joined,
        "country": country,
        # S3: which joined rails had rows on this machine. A rail without rows is a gap, not a 0.
        "availability": {"joined": len(rails), "with_rows": len(with_rows),
                         "rails_with_rows": with_rows,
                         "rails_without_rows": [r["key"] for r in rails if r["key"] not in with_rows]},
        "article_ids": ids,
        "article_ids_bounded": passport["articles"] > len(ids),
        "method": METHOD,
        "method_country": COUNTRY_METHOD if country else None,
        "caveat": CAVEAT,
    }
