"""Assemble normalised space-time signals from every available source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

One shape to rule the map: ``{id, title, kind, lat, lon, t, date, confirmed,
geocode, place, country, url, note, source}``. Sources are layered in *if they
exist* — the curated anchors are always present; the recurring-events agenda and
geocoded corpus join automatically once those modules are installed; live
hazards are injected by the API (they need a network fetch, kept out of this
pure layer). A source that isn't there is simply absent, never faked.
"""

from __future__ import annotations

from datetime import date

from src.timemap import year_float
from src.timemap.anchors import load_anchors
from src.timemap.geocode import geocode

# Known kinds get a stable identity in the legend; anything else falls back.
KNOWN_KINDS = (
    "disaster",
    "conflict",
    "milestone",
    "civic",
    "space",
    "science",
    "climate",
    "sport",
    "economic",
    "political",
    "technology",
    "hazard",
    "article",
)


def _events_signals() -> list[dict]:
    """The recurring-events agenda, geocoded + dated. Empty if events not installed."""
    try:
        from src.events.catalog import agenda
    except Exception:
        return []
    out: list[dict] = []
    for e in agenda():
        occ = e.get("next_occurrence")
        if not occ:  # a movable summit with no fixed date: no point on the axis
            continue
        try:
            d = date.fromisoformat(occ)
        except (TypeError, ValueError):
            continue
        g = geocode(e.get("country"), e.get("region"))
        if not g:  # global/undatable-to-a-place observance: honestly no pin
            continue
        cat = e.get("category")
        kind = cat if cat in KNOWN_KINDS else "civic"
        out.append(
            {
                "id": "agenda:" + str(e.get("title", "")),
                "title": str(e.get("title", "")),
                "kind": kind,
                "lat": g["lat"],
                "lon": g["lon"],
                "t": round(year_float(d), 3),
                "date": d.isoformat(),
                "year": d.year,
                "date_precision": "day",
                "confirmed": bool(e.get("confirmed", False)),
                "place": g.get("place"),
                "country": (e.get("country") or "").lower() or None,
                "url": e.get("official_url"),
                "note": e.get("note"),
                "source": "agenda",
                "geocode": g["geocode"],
            }
        )
    return out


def article_mentions_to_signals(
    rows: list[dict], *, today=None, per_article: int = 3
) -> list[dict]:
    """Dates *mentioned in* article text -> candidate signals (pure; API supplies rows).

    Each row is ``{title, url, content, country, city}``. We extract explicit dates from
    the text (see :mod:`src.timemap.dateextract`) and emit, per article, up to
    ``per_article`` candidates at the article's geocoded source location. These are
    **unconfirmed extractions** (``source='corpus-mention'``, ``confirmed=False``) with
    the matched snippet as provenance — the temporal map draws them as dashed rings. The
    date is *when the story refers to*; the place is the source's, not necessarily the
    event's — both stated in the note.
    """
    from src.timemap.dateextract import extract_dates

    out: list[dict] = []
    for r in rows:
        g = geocode(r.get("country"), r.get("city"))
        if not g:
            continue
        title = (r.get("title") or "").strip() or "(untitled article)"
        for c in extract_dates(r.get("content") or "", today=today, limit=per_article):
            try:
                d = date.fromisoformat(c["date"])
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "id": "mention:" + str(r.get("url") or title) + ":" + c["date"],
                    "title": title,
                    "kind": "article",
                    "lat": g["lat"],
                    "lon": g["lon"],
                    "t": round(year_float(d), 3),
                    "date": c["date"],
                    "year": d.year,
                    "date_precision": c["precision"],
                    "confirmed": False,  # an extracted mention, not a verified event
                    "place": g.get("place"),
                    "country": (r.get("country") or "").lower() or None,
                    "url": r.get("url"),
                    "note": (
                        "Date mentioned in coverage (extracted): “…"
                        + c["text"]
                        + "…”. Placed at the source location — when the story refers to, "
                        "not necessarily where the event occurred."
                    ),
                    "source": "corpus-mention",
                    "geocode": g["geocode"],
                    "extracted": True,
                }
            )
    return out


def _in_window(t: float, start: float | None, end: float | None) -> bool:
    return (start is None or t >= start) and (end is None or t <= end)


def articles_to_signals(rows: list[dict]) -> list[dict]:
    """Corpus articles -> space-time signals (pure; the API supplies ``rows`` from the DB).

    Each row is ``{title, url, published, country, city}``. We place an article at its
    *source/detected location* (geocoded via the gazetteer) on its *publication date* —
    an honest coverage-origin signal, not a claim about where the story happened. An
    article with no date, or no geocodable place, is skipped (never plotted at 0,0).
    """
    out: list[dict] = []
    for r in rows:
        pub = r.get("published")
        if pub is None:
            continue
        d = pub.date() if hasattr(pub, "date") else pub
        try:
            year = d.year
        except AttributeError:
            continue
        g = geocode(r.get("country"), r.get("city"))
        if not g:
            continue
        title = (r.get("title") or "").strip() or "(untitled article)"
        out.append(
            {
                "id": "article:" + str(r.get("url") or title),
                "title": title,
                "kind": "article",
                "lat": g["lat"],
                "lon": g["lon"],
                "t": round(year_float(d), 3),
                "date": d.isoformat(),
                "year": year,
                "date_precision": "day",
                "confirmed": True,  # a real publication date
                "place": g.get("place"),
                "country": (r.get("country") or "").lower() or None,
                "url": r.get("url"),
                "note": "Placed at the source/detected location on its publication date — coverage origin, not the event site.",
                "source": "corpus",
                "geocode": g["geocode"],
            }
        )
    return out


def collect(
    *,
    kinds: set[str] | None = None,
    start: float | None = None,
    end: float | None = None,
    include_events: bool = True,
    extra: list[dict] | None = None,
) -> list[dict]:
    """All locatable+datable signals, filtered by kind and time window, sorted by time.

    ``start``/``end`` are fractional years (see :func:`year_float`). ``extra`` lets
    the API inject already-normalised signals (e.g. live hazards) without this pure
    layer touching the network.
    """
    signals: list[dict] = list(load_anchors())
    if include_events:
        signals += _events_signals()
    if extra:
        signals += [s for s in extra if s.get("lat") is not None and s.get("t") is not None]

    out = []
    for s in signals:
        if kinds and s.get("kind") not in kinds:
            continue
        if not _in_window(s.get("t"), start, end):
            continue
        out.append(s)
    out.sort(key=lambda s: s["t"])
    return out


def time_range(signals: list[dict]) -> dict:
    """Min/max time present (to set the slider extent), plus counts by kind."""
    counts: dict[str, int] = {}
    ts = []
    for s in signals:
        ts.append(s["t"])
        counts[s["kind"]] = counts.get(s["kind"], 0) + 1
    return {
        "min": round(min(ts), 3) if ts else None,
        "max": round(max(ts), 3) if ts else None,
        "count": len(signals),
        "by_kind": counts,
    }
