"""One official-statistics SERIES as one corpus Article (rulings 5, 30, 31).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07: government data was to go DEEP into search, not sit behind
its own tab. The maintainer's framing was that a figure nobody can find is not in the
corpus, so a series becomes an Article and travels the ordinary path — ``index_article``
for keywords and When/Where/Who, FTS for "GDP china", the Feed, Leads, every corpus-wide
aggregate. There is no bespoke search path here, which is the whole point: a bespoke one
would need every future surface to remember it exists.

IDENTITY is ``(agency, series_id, ref_area)`` — one Article per indicator per area, for
all time. NOT one per vintage: a revision is a new StatFigure row and must be, because
revisions are evidence, but a corpus that gained a near-identical Article every time the
World Bank restated a 1991 figure would be a duplicate farm wearing a provenance label.
So the Article is UPSERTED and its hash decides whether anything changed.

THE RISK THIS CARRIES, stated because it is real and structural: ~9,800 templated
documents entering a corpus is exactly the shape MinHash clusters, and a fabricated
coordination signal would be worse than no search at all. What prevents it is not a
filter but the PROVENANCE MODEL — every series Article belongs to ONE synthetic source
per agency, and the coordination producers (echo_chamber, copypasta, skeleton_echo) all
gate on THREE DISTINCT SOURCES. One source cannot manufacture agreement with itself.
That is asserted in tests/test_series_corpus.py rather than assumed, because it is the
load-bearing property and it lives in someone else's module.

WHAT THIS CHANNEL CONTRIBUTES TO THE SHARED VOCABULARY, measured rather than assumed
(tests/test_series_corpus.py pins it, and render_series carries the full A/B):

* The SUBJECT terms, and nothing else — the indicator's own words and the area's name.
  Over 1,298 real series the ranking reads ``gdp · total · population · rate · income ·
  capita · expenditure · births · labour force``: every one of them what the corpus is
  about.

An earlier cut of this docstring argued the opposite, and the argument is kept here
because the measurement that refuted it is the useful part. It said the PRODUCER's name
belonged in the body ("ruling 30 asks for exactly this") and that the series CODE had to
stay because "dropping it from the body would remove it from FTS too". Both were wrong,
in different ways:

* The producer's name recurs once per article BY CONSTRUCTION, so its count tracks the
  channel's size rather than anything about the corpus. It ranked #1, #2 and #3
  (``world``, ``bank``, ``world bank``, 1,298 each).
* The code was never searchable in the keyword index at all — the tokenizer splits
  ``SP.DYN.LE00.IN`` on its dots, so what gets indexed is ``dyn``/``le00``, the DEBRIS
  of an identifier rather than the identifier.

Together they were a THIRD of the channel's entire term volume. Both now reach a reader
through channels that answer the same question exactly instead of approximately: the
producer through the source (``?source=Official statistics (World Bank)`` and
``?tags=statistics`` each return all 1,298) and the code through
``/api/stats/figures?series_id=`` and this article's own canonical URL.

The body is deliberately DATA-DENSE and prose-thin, for the same reason one level up: a
caveat sentence repeated 9,800 times would make its own vocabulary a top corpus term,
damaging the trusted keyword index for every other article in the corpus to say
something that belongs to the CHANNEL rather than to any one series. The channel says it
once — the provenance class, the source, and the endpoints' own caveat.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.catalog.aggregates import aggregate_name
from src.catalog.countries import classify_ref_area, country_display_name, to_iso2
from src.database.models import Article, Source, StatFigure
from src.stats import indicators as ind

__all__ = [
    "AGENCY_LABELS",
    "ensure_statistics_source",
    "render_series",
    "series_canonical_url",
    "sync_series_corpus",
    "upsert_series_article",
]

#: Display names for the agencies whose series can become Articles. An agency absent
#: here still works — it renders as its own key rather than being refused, because a
#: missing label is a cosmetic gap and refusing would drop real data over it.
AGENCY_LABELS: dict[str, str] = {
    "worldbank": "World Bank",
    "eurostat": "Eurostat",
    "imf": "IMF",
    "oecd": "OECD",
}


def _stats_domain(agency: str) -> str:
    a = (agency or "unknown").strip().lower() or "unknown"
    return f"statistics.{a}.local"


def series_canonical_url(agency: str, series_id: str, ref_area: str) -> str:
    """The stable per-series dedup key — never a real web URL.

    A synthetic scheme (the hazard/law/newsletter convention) so it can never collide
    with a scraped article's canonical_url, and so an upsert can find its own row
    without depending on a producer's URL layout staying still.
    """
    a = (agency or "unknown").strip().lower() or "unknown"
    return f"statistics://{a}/{(series_id or '').strip()}/{(ref_area or '').strip().upper()}"


def ensure_statistics_source(session: Session, agency: str) -> Source:
    """ONE catalog source per agency — statistics-derived rows stay filterable.

    ``source_type="statistics"`` is what maps this to the STATISTICS provenance class
    (src/catalog/provenance.py), so the channel is filterable everywhere for free and
    a reader can exclude it from a corpus-wide figure that should not contain it.

    It is ALSO what keeps the coordination producers honest: one source per agency
    means ~9,800 templated documents share a single source, and a signal that requires
    three distinct sources cannot fire on them.
    """
    a = (agency or "unknown").strip().lower() or "unknown"
    domain = _stats_domain(a)
    src = session.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(
            name=f"Official statistics ({AGENCY_LABELS.get(a, a)})",
            domain=domain,
            rss_url=None,
            source_type="statistics",
            tags="statistics",  # channel-implied; the boot heal covers older rows
        )
        session.add(src)
        session.flush()
    return src


def _area_name(ref_area: str) -> str:
    """A human name for an area, whatever KIND of area it is.

    An aggregate is named as one; a country by its name; an unrecognised code renders
    AS the code rather than being dropped or given an invented name — the same
    three-state honesty ``classify_ref_area`` exists for.
    """
    code = (ref_area or "").strip()
    kind = classify_ref_area(code)
    if kind == "aggregate":
        return aggregate_name(code) or code.upper()
    if kind == "country":
        iso2 = to_iso2(code)
        return (country_display_name(iso2) if iso2 else None) or code.upper()
    return code.upper()


def render_series(
    *,
    agency: str,
    series_id: str,
    ref_area: str,
    points: list[tuple[str, float | None]],
) -> tuple[str, str]:
    """``(title, body)`` for one series. Pure — no session, no clock, no I/O.

    ``points`` is ``(period, value)`` in ascending period order, INCLUDING published
    gaps as ``None``: a gap is a fact about the producer's coverage and dropping it
    would make the span read as continuous when it is not.

    ``agency`` is deliberately kept in the signature though the rendered text no longer
    names it (see the measurement below): a series' identity is the TRIPLE
    (agency, series_id, ref_area), and two producers can publish the same code, so
    dropping it here would invite a caller to treat those as one thing. It reaches the
    reader through the SOURCE, which is where a producer belongs.
    """
    meta = ind.indicator_meta(series_id) or {}
    label = meta.get("label") or series_id
    unit = meta.get("unit") or ""
    area = _area_name(ref_area)

    title = f"{label} — {area}"

    # PROSE-FREE, AND THEN METADATA-FREE — BOTH BY MEASUREMENT, not by taste.
    #
    # Round 1. The first cut carried a tidy summary ("Unit: … Latest reported: …
    # Periods held: … Producer: …") and a one-line caveat. Running the real extractor
    # over it put `producer, gap, unit, held, bank, dash, zero, value, score, series,
    # figure` at the TOP of the corpus ranking — scaffolding repeated once per series
    # outranking what the corpus is about. The caveat was NOT dropped; it moved to
    # where it was always true, the CHANNEL (the source reads "Official statistics
    # (World Bank)", the provenance class is `statistics`, and every Governments
    # endpoint carries the full sentence).
    #
    # Round 2, and the one that decided this shape. The surviving line
    # `{agency_label} · {series_id}` looked harmless — two facts a reader might search
    # for, once each. Measured over 1,298 real series with the real extractor, it was
    # a THIRD of the corpus's entire mention volume, and it owned the top of the
    # ranking outright:
    #
    # (extractor-level term emissions over the same 1,298 series — the A/B; the STORED
    # figures after the stoplist and dedup are 15,288 mentions over 2,354 keywords)
    #
    #     with the line     30,358 emissions  #1 world · #2 bank · #3 world bank
    #                                          (1,298 each = one per article, by
    #                                          construction), #6 totl, #9 gdp world
    #                                          bank, #14 population world bank
    #     without it        20,372 emissions  #1 gdp · total · population · rate ·
    #                                          income · capita · expenditure · births ·
    #                                          labour force — nothing but subject matter
    #
    # A SECOND, UNPREDICTED WIN, measured on the re-render: the repeated line was also
    # what made unrelated series look alike to MinHash. Clustering the real 1,298 at
    # both production thresholds went from 9 clusters with a biggest of 36 members down
    # to 7 with a biggest of 3. The boilerplate was not merely riding the corpus, it was
    # manufacturing the similarity — so the coordination risk the brief flagged for this
    # channel is smaller at the source, with the one-source-per-agency gate (see
    # ensure_statistics_source) still the net beneath it.
    #
    # `totl`/`mktp`/`dyn`/`pcap`/`le00` are the DEBRIS of a machine identifier: the
    # tokenizer splits `SP.DYN.LE00.IN` on its dots, so the keyword index never sees a
    # searchable code, only fragments. Keeping the code bought nothing there and cost
    # those fragments (a code-kept variant was measured too: 23,868 mentions, `totl`
    # still #3).
    #
    # WHAT THIS LOSES, stated rather than glossed. FTS covers `title, content` only, so
    # dropping the line removes two free-text matches: the intact series code — which
    # lives exactly in `/api/stats/figures?series_id=`, an exact lookup rather than a
    # text match, and in this article's own canonical URL — and the producer name,
    # which lives in the source. Both replacements were CHECKED, not assumed, against
    # the 1,298: `/api/articles?source=Official statistics (World Bank)` returns 1298
    # and `?tags=statistics` returns 1298, while `?query=World Bank` and
    # `?query=SP.DYN.LE00.IN` now return 0 — an exact filter answering exactly the
    # question a text match answered approximately. Every SUBJECT search is unchanged
    # ("life expectancy France" 1, "GDP China" 12, "population Brazil" 6, "Gini index"
    # 18). And a free-text "World Bank" that returned 1,298 series stubs ahead of
    # journalism ABOUT the World Bank was arguably the worse answer — though that half
    # is reasoning, not a measurement: this corpus holds no journalism to be buried.
    #
    # THE UNIT. A body of bare numbers is a value without its unit, which the standing
    # rule forbids — but the fix here is smaller than it first looked, and measuring it
    # is what shrank it. An unconditional `({unit})` cost only +367 mentions (+1.8%) and
    # moved nothing into the top 15, so it looked free; a mutation test then showed the
    # guard for it passing with the unit REMOVED, and the reason was that the producer's
    # own labels already state it. 26 of the catalog's 36 read like "GDP growth
    # (annual %)" or "Life expectancy at birth (years)", so appending would have printed
    # "(years) (years)" — duplication dressed as diligence.
    #
    # The World Bank's convention is that a label's trailing PARENTHETICAL qualifies the
    # measure, so that is the test: when the label has one, it already says what the
    # number is; when it has none ("Population, total", "Labour force, total", "Gini
    # index" — 3 of 36) this app states the unit rather than showing a bare column of
    # digits. A substring check was rejected: the label spells units out in words while
    # the unit field uses symbols ("current US$" vs "USD", "metric tons per capita" vs
    # "t/capita"), so it would have missed four of the ten and re-introduced the
    # doubling on exactly those.
    head = f"{area} — {label}"
    if unit and "(" not in label:
        head = f"{head} ({unit})"
    lines = [head, ""]
    # The values themselves, so a reader landing here from a search sees the series
    # rather than a stub, and so FTS can match a figure's own digits. A published gap
    # is a dash: it stays visible as a gap, and the span cannot read as continuous.
    lines.extend(f"{p}: {'—' if v is None else v}" for p, v in points)
    return title, "\n".join(lines)


def upsert_series_article(
    session: Session,
    *,
    agency: str,
    series_id: str,
    ref_area: str,
    points: list[tuple[str, float | None]],
    extractor=None,
    commit: bool = True,
) -> dict:
    """Upsert ONE series as a corpus Article and index it. Idempotent on content hash.

    Re-running over an unchanged series is a no-op that costs one SELECT — which is
    what makes this safe to schedule, and what stops a fresh vintage of one year from
    rewriting the whole corpus.
    """
    if not points:
        return {"series": series_id, "area": ref_area, "status": "skipped-no-points"}

    title, body = render_series(
        agency=agency, series_id=series_id, ref_area=ref_area, points=points
    )
    content_hash = hashlib.sha256(body.encode()).hexdigest()
    url = series_canonical_url(agency, series_id, ref_area)

    art = session.query(Article).filter(Article.canonical_url == url).first()
    created = False
    if art is None:
        src = ensure_statistics_source(session, agency)
        art = Article(
            url=url,
            canonical_url=url,
            source_id=src.id,
            title=title,
            content=body,
            # The prose is English; the DATA is language-neutral. Saying so beats
            # leaving it null and letting the detector guess from a column of digits.
            language="en",
            hash=content_hash,
            published_at=datetime.now(UTC),
        )
        session.add(art)
        session.flush()
        created = True
    elif art.hash == content_hash:
        return {"series": series_id, "area": ref_area, "status": "unchanged",
                "article_id": art.id}
    else:
        art.content = body
        art.hash = content_hash
        art.title = title
    if commit:
        session.commit()

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    tally = index_article(session, art, extractor=extractor, commit=commit)
    return {
        "series": series_id,
        "area": ref_area,
        "status": "created" if created else "updated",
        "article_id": art.id,
        "mentions": tally.get("mentions", 0),
    }


def series_keys(session: Session, *, agency: str = "worldbank") -> list[tuple[str, str]]:
    """Every ``(series_id, ref_area)`` this store holds figures for, in a stable order.

    A DISTINCT over the indexed columns — never a walk of the figures themselves, which
    at a full World Bank load is ~640k rows to answer a question about ~9,800 keys.
    """
    rows = session.execute(
        select(StatFigure.series_id, StatFigure.ref_area)
        .where(StatFigure.agency == agency)
        .distinct()
        .order_by(StatFigure.series_id, StatFigure.ref_area)
    ).all()
    return [(r[0], r[1]) for r in rows]


def _points_for(session: Session, *, agency: str, series_id: str, ref_area: str
                ) -> list[tuple[str, float | None]]:
    """The LATEST vintage of every period for one series, ascending.

    Vintages are preserved in the store (a revision is a new row) but an Article shows
    the current reading: carrying every vintage would make one series read as several
    conflicting ones to a reader who never asked about revision history, which the
    Statistics subtab surfaces on purpose.
    """
    rows = session.execute(
        select(StatFigure.time_period, StatFigure.value, StatFigure.extracted_at)
        .where(
            StatFigure.agency == agency,
            StatFigure.series_id == series_id,
            StatFigure.ref_area == ref_area,
        )
    ).all()
    latest: dict[str, tuple[str, float | None]] = {}
    for period, value, extracted in rows:
        p = str(period or "")
        if not p:
            continue
        prev = latest.get(p)
        if prev is None or str(extracted or "") >= prev[0]:
            latest[p] = (str(extracted or ""), value)
    return [(p, latest[p][1]) for p in sorted(latest)]


def sync_series_corpus(
    session: Session,
    *,
    agency: str = "worldbank",
    extractor=None,
    limit: int = 200,
    start: int = 0,
    should_stop=None,
) -> dict:
    """Materialise stored series as corpus Articles, bounded and resumable.

    ``start`` is an index into the stable ``series_keys`` order, so a caller can page
    through ~9,800 series across passes without holding a cursor this module owns. It
    is deliberately positional rather than an id watermark: the key list is derived, so
    an id would be a watermark over something that has no ids.
    """
    keys = series_keys(session, agency=agency)
    window = keys[start:start + max(1, limit)]
    # Counted in typed locals rather than in the dict: a dict mixing str, int and bool
    # infers as dict[str, object], and every `+= 1` on it is then an error mypy is right
    # about. Assembling once at the end also makes the returned shape readable in one
    # place, which is what the endpoint and the job both render.
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    examined = 0
    stopped = False
    for series_id, ref_area in window:
        if should_stop is not None and should_stop():
            stopped = True
            break
        points = _points_for(session, agency=agency, series_id=series_id, ref_area=ref_area)
        out = upsert_series_article(
            session, agency=agency, series_id=series_id, ref_area=ref_area,
            points=points, extractor=extractor,
        )
        examined += 1
        status = str(out.get("status", ""))
        counts[status if status in counts else "skipped"] += 1
    next_start = start + examined
    return {
        "agency": agency,
        "total_series": len(keys),
        "start": start,
        "examined": examined,
        **counts,
        "stopped": stopped,
        "next_start": next_start,
        # A run that was STOPPED is never complete, however far it got: the operator
        # asked it to stop, so reporting the walk as finished would be a fabricated pass.
        "complete": next_start >= len(keys) and not stopped,
    }
