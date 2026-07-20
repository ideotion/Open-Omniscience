"""
If-this-then-SUGGEST: deductive corroboration opportunities (slice 1: weather).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's ask (2026-06-12): when collected articles cluster around a
climate-event word AND a deduced place, the app should *suggest* checking an
independent data source (Open-Meteo reanalysis) for that place and window —
"if this, then suggest user to fetch". This module is the deductive half: it
scans the LOCAL substrate only (keyword mentions × T12 place mentions ×
article dates) and returns explainable opportunities. It never touches the
network; the fetch itself happens elsewhere, only on the user's consent.

Honesty constraints carried on every opportunity:
  * lexical exact-match against a curated seed vocabulary
    (``configs/corroboration_rules.yml`` — provenance stated in-file);
  * the window is built from ARTICLE dates (publication), not the event's own
    dates — articles may discuss past, forecast or figurative events;
  * coordinates come from the place extractor's gazetteer hit, or an honest
    country-level stand-in via :func:`src.timemap.geocode.geocode` (precision
    is recorded); a cluster with no resolvable coordinate is skipped and
    counted, never pinned to an invented point.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from src.database.models import ArticleMentionedPlace, Keyword, KeywordMention

_LOG = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).resolve().parents[2] / "configs" / "corroboration_rules.yml"

# Bound on SQL IN() chunks (well under SQLite's variable limit).
_IN_CHUNK = 600


@lru_cache(maxsize=1)
def load_rules() -> dict:
    """The curated rule file, parsed once per process (tests may cache_clear)."""
    import yaml

    data = yaml.safe_load(_RULES_PATH.read_text(encoding="utf-8")) or {}
    rules = data.get("rules") or []
    return {
        "as_of": data.get("as_of"),
        "provenance": (data.get("provenance") or "").strip(),
        "rules": rules,
    }


def _term_index(rules: list[dict]) -> dict[str, tuple[str, str]]:
    """normalized term -> (rule_id, language). Terms are stored normalized already."""
    idx: dict[str, tuple[str, str]] = {}
    for rule in rules:
        for lang, terms in (rule.get("terms") or {}).items():
            for t in terms or []:
                norm = " ".join(str(t).split()).casefold()
                if norm:
                    idx[norm] = (rule["id"], lang)
    return idx


def _chunks(seq: list, size: int = _IN_CHUNK):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def find_weather_opportunities(
    session,
    *,
    lookback_days: int = 90,
    min_articles: int = 3,
    pad_days: int = 3,
    limit: int = 6,
    today: date | None = None,
) -> dict:
    """Scan the local substrate for (climate term × place × window) clusters.

    Returns ``{"opportunities": [...], "clusters_total": n, "skipped_no_coords": n,
    "excluded_non_articles": n, "rules_as_of": ..., "provenance": ...}`` — the totals
    are always disclosed so a display bound (``limit``) never silently hides how much
    qualified. Country-level places canonicalize by country CODE (S4.2/C2), so
    "Allemagne"/"Deutschland" never split into two clusters; a suspected homepage/
    section capture is excluded from a cluster's article members (S1.4), disclosed via
    ``excluded_non_articles`` (both the per-opportunity and the corpus-wide total).
    """
    today = today or date.today()
    cutoff = today - timedelta(days=lookback_days)
    cfg = load_rules()
    rules = {r["id"]: r for r in cfg["rules"]}
    terms = _term_index(cfg["rules"])
    if not terms:
        return {"opportunities": [], "clusters_total": 0, "skipped_no_coords": 0,
                "excluded_non_articles": 0,
                "rules_as_of": cfg["as_of"], "provenance": cfg["provenance"]}

    # 1) Which curated terms exist as keywords? (small columns only — the
    #    SQLCipher lesson: never drag article rows through the codec here.)
    kw_rows = (
        session.query(Keyword.id, Keyword.normalized_term)
        .filter(Keyword.normalized_term.in_(list(terms.keys())))
        .all()
    )
    if not kw_rows:
        return {"opportunities": [], "clusters_total": 0, "skipped_no_coords": 0,
                "excluded_non_articles": 0,
                "rules_as_of": cfg["as_of"], "provenance": cfg["provenance"]}
    kw_meta = {kid: (terms[norm][0], norm, terms[norm][1]) for kid, norm in kw_rows}

    # 2) Recent mentions of those keywords (covering-index friendly).
    mention_rows = (
        session.query(KeywordMention.keyword_id, KeywordMention.article_id,
                      KeywordMention.observed_on)
        .filter(
            KeywordMention.keyword_id.in_(list(kw_meta.keys())),
            KeywordMention.observed_on.isnot(None),
            KeywordMention.observed_on >= cutoff,
        )
        .all()
    )
    if not mention_rows:
        return {"opportunities": [], "clusters_total": 0, "skipped_no_coords": 0,
                "excluded_non_articles": 0,
                "rules_as_of": cfg["as_of"], "provenance": cfg["provenance"]}

    # article -> set of (rule_id, term, lang) and the article's observed date(s)
    art_rules: dict[int, set[tuple[str, str, str]]] = {}
    art_dates: dict[int, list[date]] = {}
    for kid, aid, obs in mention_rows:
        art_rules.setdefault(aid, set()).add(kw_meta[kid])
        art_dates.setdefault(aid, []).append(obs)

    # 3) Deduced places for those articles (T12 substrate; small columns).
    place_rows: list[tuple] = []
    art_ids = list(art_rules.keys())
    for chunk in _chunks(art_ids):
        place_rows.extend(
            session.query(
                ArticleMentionedPlace.article_id, ArticleMentionedPlace.name,
                ArticleMentionedPlace.country, ArticleMentionedPlace.kind,
                ArticleMentionedPlace.lat, ArticleMentionedPlace.lon,
            )
            .filter(ArticleMentionedPlace.article_id.in_(chunk))
            .all()
        )

    # 4) Cluster on (rule, place identity) -- country-level mentions canonicalize to the
    #    country CODE (S4.2/C2: "Allemagne"/"Deutschland", "United States"/"America"/"Usa"
    #    are the SAME place, never separate clusters); a city keeps its own identity.
    from src.analytics.place_identity import place_identity

    clusters: dict[tuple[str, str], dict] = {}
    for aid, name, country, kind, lat, lon in place_rows:
        if not (name or "").strip():
            continue
        place_key_id, place_display = place_identity(name, country, kind)
        for rule_id, term, lang in art_rules.get(aid, ()):  # an article can feed several rules
            key = (rule_id, place_key_id)
            c = clusters.setdefault(key, {
                "articles": set(), "dates": [], "terms": set(), "langs": set(),
                "name": place_display, "country": country, "kind": kind, "lat": None, "lon": None,
            })
            c["articles"].add(aid)
            c["dates"].extend(art_dates.get(aid, ()))
            c["terms"].add(term)
            c["langs"].add(lang)
            if c["lat"] is None and lat is not None and lon is not None:
                c["lat"], c["lon"] = lat, lon
                c["geocode"] = kind or "place"

    qualified = {k: c for k, c in clusters.items() if len(c["articles"]) >= min_articles}

    # Non-article member exclusion seam (S1.4, row 10): a suspected homepage/section
    # capture is excluded from a cluster's evidence MEMBERS, disclosed, never silent.
    from src.analytics.non_article_scan import suspected_non_article_ids

    all_member_ids = sorted({aid for c in qualified.values() for aid in c["articles"]})
    suspects = suspected_non_article_ids(session, all_member_ids) if all_member_ids else set()

    skipped_no_coords = 0
    excluded_non_articles = 0
    opportunities: list[dict] = []
    for (rule_id, _pkid), c in qualified.items():
        country = c["country"]
        member_ids = sorted(c["articles"] - suspects)
        n_excluded = len(c["articles"]) - len(member_ids)
        if len(member_ids) < min_articles:
            excluded_non_articles += n_excluded
            continue  # the real, non-suspect evidence no longer clears the gate
        excluded_non_articles += n_excluded
        lat, lon, precision = c["lat"], c["lon"], c.get("geocode")
        if lat is None or lon is None:
            # Honest fallback: a gazetteer city / country stand-in, precision stated.
            try:
                from src.timemap.geocode import geocode

                hit = geocode(country=country or None, place=c["name"])
            except Exception:  # noqa: BLE001 - geocoding is a bonus, never a blocker
                hit = None
            if not hit:
                skipped_no_coords += 1
                continue
            lat, lon, precision = hit["lat"], hit["lon"], hit["geocode"]
        start = min(c["dates"]) - timedelta(days=pad_days)
        end = min(max(c["dates"]) + timedelta(days=pad_days), today)
        rule = rules[rule_id]
        opportunities.append({
            "rule": rule_id,
            "rule_label": rule.get("label") or rule_id,
            "variables": list(rule.get("variables") or []),
            "place": c["name"],
            "place_country": country or None,
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "geocode": precision,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "article_ids": member_ids,
            "n_articles": len(member_ids),
            "excluded_non_articles": n_excluded,
            "terms_matched": sorted(c["terms"]),
            "languages": sorted(c["langs"]),
        })

    opportunities.sort(key=lambda o: (-o["n_articles"], o["rule"], o["place"] or ""))
    return {
        "opportunities": opportunities[:limit],
        "clusters_total": len(opportunities),
        "skipped_no_coords": skipped_no_coords,
        "excluded_non_articles": excluded_non_articles,
        "rules_as_of": cfg["as_of"],
        "provenance": cfg["provenance"],
    }
