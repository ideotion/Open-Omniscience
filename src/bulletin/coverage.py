"""Who covered a country, and who covered it from outside.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask, 2026-08-11: "a section with a per country and per continent top
keywords (including statistics about how many articles were used for calculations),
as well as top keywords concerning articles mentioning that country, to see
difference between local coverage and international coverage of each country."

TWO VANTAGES ON ONE PLACE, and the whole value is in not blending them:

* **Local** — mentions whose SOURCE sits in the country. What outlets there wrote
  about, in their own languages. ``KeywordMention.country`` is the denormalised
  source country, so this is an index scan over mention-sized rows.
* **International** — mentions in articles that NAME the country, from sources
  that do not sit in it. What everyone else said about the place.

The distinction is already drawn in the schema: ``ArticleMentionedPlace``'s own
docstring calls itself "distinct from coverage origin (the source's country on
mentions)". Nothing here reads ``Article``, so neither vantage pays the SQLCipher
codec cost that a keyword_mentions -> articles join would.

WHAT AN ASYMMETRY MEANS, since that is the point of putting them side by side: a
country with local coverage and no international coverage was not written about
from outside THIS corpus during THIS period — which is a fact about what this
operator collected, never about the world's attention. The reverse (covered from
outside, no local sources) usually means no source in that country is enabled here.
Both readings are stated with the figures rather than left to the reader to guess.

The mentioned-place layer is DEDUCED. A place name is a lexical surface form the
extractor does not disambiguate, so "articles mentioning France" includes an
article about a Paris in Texas if the extractor read it that way. That is carried
as a caveat, not corrected here.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select

from src.bulletin.period import Period
from src.catalog.countries import COUNTRY_NAMES, continent_of
from src.database.models import ArticleMentionedPlace, Keyword, KeywordMention

_LOG = logging.getLogger(__name__)

# How many countries get the two-vantage treatment, and how many terms each side
# shows. Both bound the DOCUMENT, never a figure in it: every count below is exact
# over the whole period, and the number of countries left out is stated.
DEFAULT_COUNTRIES = 12
DEFAULT_TERMS = 8

_CAVEAT = (
    "Two different vantages on the same place, deliberately not blended. LOCAL is "
    "what sources located in the country published, in whatever language they "
    "publish in. INTERNATIONAL is what articles from sources elsewhere said while "
    "naming that country. A country with local coverage and no international "
    "coverage was not written about from outside THIS corpus in THIS period, which "
    "says nothing about the world's attention — and the reverse usually means no "
    "source in that country is enabled here. The international side rests on place "
    "names the extractor does not disambiguate: it is deduced, never confirmed, so "
    "a same-named place elsewhere is counted here too. Every count is exact over the "
    "whole period; only how many countries are LISTED is bounded."
)


def _label(code: str) -> str:
    """A country's display name, falling back to the code rather than inventing one."""
    return COUNTRY_NAMES.get(code, code)


def _terms(
    session,
    period: Period,
    *,
    where: list[Any],
    limit: int,
) -> list[dict]:
    """Top keywords by summed mentions under ``where``, with each term's own spread.

    Ordered by mentions, and every row carries the distinct-article count behind it
    — a term carried by one article and a term carried by forty are different facts
    at the same mention total.
    """
    rows = (
        session.query(
            Keyword.term,
            Keyword.normalized_term,
            Keyword.language,
            func.sum(KeywordMention.count),
            func.count(func.distinct(KeywordMention.article_id)),
        )
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(
            KeywordMention.observed_on >= period.start,
            KeywordMention.observed_on < period.end,
            *where,
        )
        .group_by(Keyword.id)
        .order_by(func.sum(KeywordMention.count).desc(), Keyword.normalized_term)
        .limit(int(limit))
        .all()
    )
    return [
        {
            "term": r[0],
            "normalized": r[1],
            "language": r[2],
            "mentions": int(r[3] or 0),
            "articles": int(r[4] or 0),
        }
        for r in rows
    ]


def _articles(session, period: Period, *, where: list[Any]) -> int:
    """Distinct articles behind a vantage — the n the maintainer asked to see."""
    return int(
        session.query(func.count(func.distinct(KeywordMention.article_id)))
        .filter(
            KeywordMention.observed_on >= period.start,
            KeywordMention.observed_on < period.end,
            *where,
        )
        .scalar()
        or 0
    )


def _mentioning(codes: list[str]):
    """The articles that NAME any of ``codes`` as a country.

    ``kind == "country"`` on purpose: a city row would make "articles mentioning
    France" include every article naming Paris, which is a different question and
    one the caller did not ask.
    """
    return select(ArticleMentionedPlace.article_id).where(
        ArticleMentionedPlace.country.in_(codes),
        ArticleMentionedPlace.kind == "country",
    )


def _local_where(codes: list[str]) -> list[Any]:
    return [KeywordMention.country.in_(codes)]


def _international_where(codes: list[str]) -> list[Any]:
    # "From elsewhere" is read off the mention row's own denormalised source
    # country, so the exclusion costs nothing extra. NULL counts as elsewhere: a
    # source with no country recorded is certainly not evidence of local coverage,
    # and dropping those rows would silently shrink the international side.
    return [
        KeywordMention.article_id.in_(_mentioning(codes)),
        (KeywordMention.country.notin_(codes)) | (KeywordMention.country.is_(None)),
    ]


def _vantages(
    session, period: Period, *, codes: list[str], terms_per_side: int
) -> dict[str, Any]:
    """Both vantages for one country or one continent's set of countries."""
    local_w, intl_w = _local_where(codes), _international_where(codes)
    return {
        "local": {
            "terms": _terms(session, period, where=local_w, limit=terms_per_side),
            "articles": _articles(session, period, where=local_w),
            "basis": "sources located here",
        },
        "international": {
            "terms": _terms(session, period, where=intl_w, limit=terms_per_side),
            "articles": _articles(session, period, where=intl_w),
            "basis": "sources elsewhere, naming this place",
        },
    }


def _reading(local_n: int, intl_n: int) -> str:
    """What the pair of counts supports saying, and nothing more."""
    if local_n and intl_n:
        return "covered from inside and from outside"
    if local_n and not intl_n:
        return "covered locally only — no source elsewhere named it in this period"
    if intl_n and not local_n:
        return "covered from outside only — no source located here contributed"
    return "no coverage from either vantage in this period"


def country_coverage(
    session,
    period: Period,
    *,
    source_countries: list[dict] | None = None,
    limit_countries: int = DEFAULT_COUNTRIES,
    terms_per_side: int = DEFAULT_TERMS,
) -> dict:
    """Top keywords per country and per continent, from both vantages.

    ``source_countries`` is the masthead's own per-country article split, reused so
    the section's choice of countries is the same ordering the masthead already
    disclosed rather than a second, unexplained one. Without it the countries are
    resolved here from the same table.
    """
    if source_countries is None:
        rows = (
            session.query(KeywordMention.country, func.count(func.distinct(KeywordMention.article_id)))
            .filter(
                KeywordMention.observed_on >= period.start,
                KeywordMention.observed_on < period.end,
                KeywordMention.country.isnot(None),
            )
            .group_by(KeywordMention.country)
            .order_by(func.count(func.distinct(KeywordMention.article_id)).desc())
            .all()
        )
        source_countries = [{"country": r[0], "articles": int(r[1] or 0)} for r in rows]

    ranked = [str(r["country"]).lower() for r in source_countries if r.get("country")]
    picked = ranked[: int(limit_countries)]

    countries: list[dict] = []
    for code in picked:
        v = _vantages(session, period, codes=[code], terms_per_side=terms_per_side)
        countries.append(
            {
                "country": code,
                "name": _label(code),
                "continent": continent_of(code),
                **v,
                "reading": _reading(v["local"]["articles"], v["international"]["articles"]),
            }
        )

    # Continents are computed from their own member set, NOT summed from the
    # countries above: an article naming two countries on one continent must count
    # once, and summing per-country article totals would count it twice. Keyword
    # MENTIONS would sum correctly (they are extensive) and article spread would not,
    # so one aggregate cannot serve both — a second query is the honest price.
    by_continent: dict[str, list[str]] = {}
    for code in ranked:
        cont = continent_of(code)
        if cont:
            by_continent.setdefault(cont, []).append(code)

    continents: list[dict] = []
    for cont, codes in sorted(by_continent.items()):
        v = _vantages(session, period, codes=codes, terms_per_side=terms_per_side)
        continents.append(
            {
                "continent": cont,
                "countries_contributing": len(codes),
                **v,
                "reading": _reading(v["local"]["articles"], v["international"]["articles"]),
            }
        )
    continents.sort(key=lambda c: -c["local"]["articles"])

    unlisted = ranked[int(limit_countries) :]
    return {
        "section": "country_coverage",
        "countries": countries,
        "continents": continents,
        "countries_total": len(ranked),
        "countries_listed": len(picked),
        "countries_unlisted": len(unlisted),
        "terms_per_side": int(terms_per_side),
        "window": {
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "days": period.days,
            "matches_period": True,
        },
        "method": (
            "two aggregates per place over the period's keyword mentions: LOCAL filters "
            "on the mention's own denormalised source country; INTERNATIONAL filters to "
            "articles carrying a mentioned-place row for that country and excludes "
            "mentions whose source sits there. Exact SQL counts, ordered by summed "
            "mentions, each term carrying its distinct-article spread. Continents are "
            "computed from their member countries rather than summed from them, so an "
            "article naming two of them counts once. Neither query reads article text."
        ),
        "caveat": _CAVEAT,
    }


def build(session, period: Period, ctx: dict) -> dict:
    """Section builder. Reuses the masthead's country ordering when the run has it."""
    masthead = (ctx.get("masthead") or {}) if isinstance(ctx.get("masthead"), dict) else {}
    return country_coverage(
        session,
        period,
        source_countries=masthead.get("source_countries"),
        limit_countries=int(ctx.get("coverage_countries", DEFAULT_COUNTRIES)),
        terms_per_side=int(ctx.get("coverage_terms", DEFAULT_TERMS)),
    )
