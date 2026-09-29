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

#: Rails the app holds that this seed does NOT join, each with why. Codes; the UI keys the words.
NOT_JOINED = (
    ("markets", "Market series are keyed by ticker symbol, not by a Wikidata item."),
    ("agenda", "Calendar events carry no Wikidata item."),
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
        if code:
            ok = norm in terms.get(code, set())
        else:
            ok = entity_qid(stored)[0] == qid
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
    from src.database.models import ArticleEntity, ArticleKeyword, ArticleMentionedPlace

    terms = item_terms(qid)
    names = _entity_names(session, terms, qid)
    kw_ids, kw_terms = _keyword_ids(session, terms, qid)
    places = _places(session, qid)
    routes: dict = {}
    if names:
        routes["entities"] = (
            select(ArticleEntity.article_id).where(ArticleEntity.name.in_(names)), names)
    if kw_ids:
        routes["keywords"] = (
            select(ArticleKeyword.article_id).where(ArticleKeyword.keyword_id.in_(kw_ids)), kw_terms)
    if places:
        routes["places"] = (
            select(ArticleMentionedPlace.article_id).where(_place_clause(places)),
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
    not_joined = [{"key": k, "joined": False, "reason": r} for k, r in NOT_JOINED]

    return {
        "qid": qid,
        "lang": lang,
        "item": _item_block(session, qid, lang),
        "routes": route_counts,
        "passport": passport,
        "rails": rails,
        "not_joined": not_joined,
        "article_ids": ids,
        "article_ids_bounded": passport["articles"] > len(ids),
        "method": METHOD,
        "caveat": CAVEAT,
    }
