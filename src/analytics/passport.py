"""The corpus passport (V01 action plan A-1): what a view was computed ON, in one line.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A-1, verbatim: «A compact, constant strip on every analytics surface stating what the view
was computed on: *n articles · sources · countries · languages · date span*.» Its comment:
«Resist making the passport collapsible-by-default; … keep it one line, data-dense, no prose.»

**EVERY FIGURE IS A COUNT OF WHAT IS THERE, AND EVERY GAP IS COUNTED TOO.** A country comes from
the article's SOURCE (``Source.country``, set from the catalogue, the ccTLD or the operator); a
source with none is counted under ``no_country`` rather than dropped, because «3 countries» over
a set where half the articles have no known country is a different sentence from «3 countries»
over a set where all of them do. The same for languages (the authoritative tag first, the
detected one second, else ``no_language``) and dates (``undated``).

**NO CAP.** The set is passed as a SELECT of article ids, never as a Python list, so the passport
of a million-article set is four aggregate queries, not a million-element ``IN``.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.database.models import Article, Source

METHOD = (
    "Counted over the articles this view was computed on. Countries are the countries of the "
    "articles' sources, as the source catalogue records them; languages are each article's "
    "language tag, else the detected language; the date span runs from the earliest to the "
    "latest publication date. Articles missing any of these are counted apart, never dropped."
)


def corpus_passport(session, ids_select) -> dict:
    """The passport of the articles whose ids ``ids_select`` yields (a one-column SELECT).

    Returns counts only: ``articles``, ``sources``, ``countries`` (with ``country_codes``),
    ``no_country``, ``languages`` (with ``language_codes``), ``no_language``, ``first``,
    ``last``, ``undated`` and the ``method`` sentence.
    """
    ids = ids_select.scalar_subquery() if hasattr(ids_select, "scalar_subquery") else ids_select
    in_set = Article.id.in_(ids)

    n, sources, first, last, dated = session.execute(
        select(
            func.count(Article.id),
            func.count(func.distinct(Article.source_id)),
            func.min(Article.published_at),
            func.max(Article.published_at),
            func.count(Article.published_at),
        ).where(in_set)
    ).one()
    n = int(n or 0)

    country_rows = session.execute(
        select(Source.country, func.count(Article.id))
        .join(Source, Source.id == Article.source_id)
        .where(in_set)
        .group_by(Source.country)
    ).all()
    countries = sorted(
        ((str(c).lower(), int(k)) for c, k in country_rows if c), key=lambda r: (-r[1], r[0])
    )
    no_country = sum(int(k) for c, k in country_rows if not c)

    lang = func.coalesce(Article.language, Article.detected_language)
    lang_rows = session.execute(
        select(lang, func.count(Article.id)).where(in_set).group_by(lang)
    ).all()
    langs: dict[str, int] = {}
    no_language = 0
    for code, k in lang_rows:
        c = (str(code).split("-")[0].strip().lower()) if code else ""
        if c:
            langs[c] = langs.get(c, 0) + int(k)
        else:
            no_language += int(k)
    languages = sorted(langs.items(), key=lambda r: (-r[1], r[0]))

    return {
        "articles": n,
        "sources": int(sources or 0),
        "countries": len(countries),
        "country_codes": [{"code": c, "articles": k} for c, k in countries],
        "no_country": no_country,
        "languages": len(languages),
        "language_codes": [{"code": c, "articles": k} for c, k in languages],
        "no_language": no_language,
        "first": first.date().isoformat() if first else None,
        "last": last.date().isoformat() if last else None,
        "undated": n - int(dated or 0),
        "method": METHOD,
    }
