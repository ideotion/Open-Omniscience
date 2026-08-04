"""Chartable aggregates for the figure surfaces (the GUI visualization plan, §7).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each function here returns a payload shaped for one figure and nothing else: the
rows, plus the ``method``/``caveat``/``n`` the frontend's figMeta panel renders
verbatim. Two properties are load-bearing and easy to lose:

* **Counts only, never a score.** No field or nested key here may be named
  score/rating/rank/trust/verdict/grade — the recursive walkers in
  ``src/briefing/card.py`` ban those as key SUBSTRINGS, and note that the status
  word "degraded" contains "grade", so a per-status tally is emitted as a LIST of
  ``{"status": s, "n": n}`` objects rather than a dict keyed by status.
* **An absence is reported as an absence.** A bucket that was never measured is
  distinguishable in the payload from one measured at zero, because the frontend
  has to hatch the first and draw the second. Getting that wrong here cannot be
  fixed downstream: "0" and "unmeasured" are the same byte once they are merged.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from src.analytics.managed import normalize_lang
from src.database.models import Article, Source

# The sentiment engine is VADER, whose lexicon is English. Every other language is
# an honest GAP, never a fabricated neutral — the scorer refuses rather than
# returning 0.0 for text it cannot read (src/analytics/sentiment.py).
SENTIMENT_LANGS = ("en",)


def _now_iso() -> str:
    """The envelope's own freshness helper, so a figure's as_of is a REAL time.

    Reused rather than reimplemented: ``Envelope`` refuses an empty as_of because
    "an honesty envelope with an invented freshness time would be the very dishonesty
    it exists to prevent" (src/analytics/envelope.py:25-31).
    """
    from src.analytics.envelope import now_iso

    return now_iso()


def quarantine_composition(session: Session, *, limit: int = 40) -> dict:
    """How many articles each quarantine reason condemned, per criteria version.

    Rows are ``{reason, criteria_version, n}``, biggest first. A reason with ZERO
    articles is not a row: the table only holds reasons that actually fired, so a
    zero would have to be invented, and a zero-height bar reads as a measured
    zero. The omission is stated in ``caveat`` instead of being silent.
    """
    total = session.query(func.count(Article.id)).scalar() or 0
    q = (
        session.query(
            Article.quarantine_reason.label("reason"),
            Article.quarantine_criteria_version.label("criteria_version"),
            func.count(Article.id).label("n"),
        )
        .filter(Article.quarantined.is_(True))
        .group_by(Article.quarantine_reason, Article.quarantine_criteria_version)
        .order_by(func.count(Article.id).desc())
        .limit(limit)
    )
    rows: list[dict[str, Any]] = [
        {
            # A row written before the reason column existed, or by a path that did
            # not set it, is reported as unstated rather than bucketed into a
            # plausible-looking reason.
            "reason": r.reason or None,
            "criteria_version": r.criteria_version or None,
            "n": int(r.n or 0),
        }
        for r in q.all()
    ]
    quarantined = sum(r["n"] for r in rows)
    versions = sorted({r["criteria_version"] for r in rows if r["criteria_version"]})
    return {
        "rows": rows,
        "n": quarantined,
        "corpus_articles": total,
        "criteria_versions": versions,
        "method": (
            "Articles with a quarantine stamp, counted by the reason that was recorded "
            "and the criteria version that recorded it."
        ),
        "caveat": (
            "Reasons that condemned no article are absent rather than shown at zero. "
            "Quarantine is reversible and describes extraction validity — whether a page "
            "is an article at all — never the quality or credibility of a source."
        ),
    }


def sentiment_measurability(session: Session, *, limit: int = 24) -> dict:
    """Per language: how many articles have a tone measurement, and how many do not.

    This figure IS the honesty gap it reports. Tone comes from VADER, whose lexicon
    is English, so every other language is UNMEASURED — a state the corpus records
    faithfully (a NULL ``sentiment_score``) and which no chart has ever surfaced.
    Rendering the unmeasured share as a zero-tone bar would be the exact fabricated
    neutral the scorer refuses to produce.

    ``measured``/``unmeasured`` are both real counts. ``supported`` says whether the
    engine can read that language at all, so the frontend can tell "supported and
    happens to be unscored" from "not supported, cannot be scored".
    """
    lang_col = func.coalesce(Article.language, "")
    q = (
        session.query(
            lang_col.label("lang"),
            func.count(Article.id).label("n"),
            func.sum(case((Article.sentiment_score.isnot(None), 1), else_=0)).label("scored"),
        )
        .filter(Article.quarantined.isnot(True))
        .group_by(lang_col)
        .order_by(func.count(Article.id).desc())
    )
    buckets: dict[str, dict] = {}
    untagged = {"n": 0, "measured": 0}
    for r in q.all():
        raw = (r.lang or "").strip()
        n, scored = int(r.n or 0), int(r.scored or 0)
        if not raw:
            # No asserted language. NOT merged into a language bucket and NOT
            # silently backfilled from detected_language: the asserted column is what
            # the tone gate reads, so this count is the size of the gate's own blind
            # spot and is reported apart.
            untagged["n"] += n
            untagged["measured"] += scored
            continue
        key = normalize_lang(raw) or raw.lower()
        b = buckets.setdefault(key, {"language": key, "n": 0, "measured": 0})
        b["n"] += n
        b["measured"] += scored
    rows = sorted(buckets.values(), key=lambda b: (-b["n"], b["language"]))
    for b in rows:
        b["unmeasured"] = b["n"] - b["measured"]
        b["supported"] = b["language"] in SENTIMENT_LANGS
    shown, tail = rows[:limit], rows[limit:]
    return {
        "rows": shown,
        "other": {
            "languages": len(tail),
            "n": sum(b["n"] for b in tail),
            "measured": sum(b["measured"] for b in tail),
            "unmeasured": sum(b["unmeasured"] for b in tail),
        },
        "untagged": untagged,
        "n": sum(b["n"] for b in rows) + untagged["n"],
        "supported_languages": list(SENTIMENT_LANGS),
        "method": (
            "Articles grouped by their asserted language, split by whether a tone value "
            "was stored. Region subtags are folded (en-US counts as en); quarantined "
            "articles are excluded."
        ),
        "caveat": (
            "Tone is measured by a rule-based English lexicon (VADER), so every other "
            "language is UNMEASURED — not neutral. An unmeasured article has no tone "
            "value at all, which is a different thing from a tone of zero."
        ),
    }


def source_concentration(session: Session, *, limit: int = 400) -> dict:
    """The Lorenz curve of how unequally the corpus draws on its sources, plus Gini.

    ``Source.article_count`` is a MAINTAINED counter and it is NULLABLE: on a corpus
    the bounded background reconcile has never touched, every source reads NULL while
    genuinely holding articles. So this follows the fallback the app already
    established at ``src/api/source_io.py:163-177`` — use the counter when it is set,
    otherwise COUNT the articles live — and reports which happened.

    The first cut of this function did not, and filtered ``article_count > 0``. On the
    demo corpus that returned n=0 against 180 real articles across 10 sources: a
    figure stating "no source has any article", which is not a caveat problem but a
    false statement. Reusing a maintained counter means inheriting its documented
    fallback, not just its column.

    ``basis`` uses the same three-state vocabulary as source_io: ``live`` (counted
    now), ``exact`` (maintained and reconciled within 24 h), ``estimated``
    (maintained but unverified or stale). Gini is ``None`` when undefined (fewer than
    two sources, or no articles) and the frontend must print that as undefined, never
    as 0 — a Gini of 0 means perfect EQUALITY, the opposite claim.
    """
    from datetime import UTC, datetime, timedelta

    from src.signals.concentration import gini, top_share

    srcs = session.query(
        Source.id, Source.name, Source.article_count, Source.counter_reconciled_at
    ).all()
    live: dict[int, int] = {
        int(sid): int(cnt)
        for sid, cnt in session.query(Article.source_id, func.count(Article.id))
        .filter(Article.quarantined.isnot(True))
        .group_by(Article.source_id)
        .all()
    }
    now = datetime.now(UTC)
    fresh, stale, counted_live = 0, 0, 0
    pairs: list[tuple[int, str]] = []
    for s in srcs:
        if s.article_count is None:
            n, why = int(live.get(s.id, 0)), "live"
            counted_live += 1
        else:
            n = int(s.article_count)
            ra = s.counter_reconciled_at
            if ra is None:
                why = "estimated"
                stale += 1
            else:
                aware = ra if ra.tzinfo is not None else ra.replace(tzinfo=UTC)
                if now - aware < timedelta(hours=24):
                    why = "exact"
                    fresh += 1
                else:
                    why = "estimated"
                    stale += 1
        if n > 0:
            pairs.append((n, why))
    pairs.sort(key=lambda p: -p[0])
    pairs = pairs[:limit]
    counts = [n for n, _ in pairs]
    # The whole figure is only as good as its weakest input, so one estimated or
    # live-counted member makes the WHOLE curve that basis. Reporting "exact"
    # because most members were exact would be the fabricated pass.
    bases = {why for _, why in pairs}
    basis = "exact" if bases == {"exact"} else ("live" if "live" in bases else "estimated")
    unreconciled = stale + counted_live
    reconciled_at = [s.counter_reconciled_at for s in srcs if s.counter_reconciled_at]
    total = sum(counts)
    # Lorenz: cumulative share of articles against cumulative share of sources,
    # poorest-first, starting at the true origin so the curve is not a fragment.
    asc = sorted(counts)
    curve = [{"sources": 0.0, "articles": 0.0}]
    run = 0
    for i, c in enumerate(asc, start=1):
        run += c
        curve.append({
            "sources": round(i / len(asc), 6) if asc else 0.0,
            "articles": round(run / total, 6) if total else 0.0,
        })
    g = gini([float(c) for c in counts])
    ts = top_share([float(c) for c in counts], 3) if counts else None
    return {
        "curve": curve,
        "gini": None if g is None else round(g, 4),
        "top_share": None if ts is None else round(ts, 4),
        "n": len(counts),
        "articles": total,
        "basis": basis,
        "counters_live": counted_live,
        "counters_fresh": fresh,
        "unreconciled_counters": unreconciled,
        "as_of": (max(reconciled_at).isoformat() if basis == "exact" and reconciled_at
                  else _now_iso()),
        "oldest_reconciled_at": min(reconciled_at).isoformat() if reconciled_at else None,
        # A FIXED sentence, deliberately. The basis-dependent clause used to be
        # concatenated on here, which made the string different on every corpus — and
        # the i18n engine matches an EXACT key, so a composed sentence can never be
        # translated and this honesty text rendered in English in all 11 non-English
        # locales. The varying part travels as the `basis` field and the frontend
        # composes it from its own keyed template (the OOI18N.tf discipline: the frame
        # is keyable, the data is interpolated after translation).
        "method": (
            "Cumulative share of stored articles against cumulative share of sources, "
            "fewest-articles first. Gini is the area between that curve and equality."
        ),
        "caveat": (
            "A description of this corpus's own composition — which sources it happens "
            "to have drawn from — and never a judgement of any source. Concentration "
            "follows what was collected, so it also reflects scraping reach."
        ),
    }


def article_length_distribution(session: Session, *, min_n: int = 1) -> dict:
    """Article word-count distribution over labelled ranges, per language.

    A thin, chartable projection of :func:`src.analytics.article_length.article_length_report`
    — which already bins the values and already flags the unsegmented languages —
    plus the two things a figure needs and the report does not carry:

    * **The unsegmented languages are held OUT of the headline chart.** ``word_count``
      is ``len(text.split())``, which is meaningless for zh/ja/th, and the report's
      own corpus-wide summary silently POOLS them with Latin text. A chart built on
      that pooled summary would be measuring two different things on one axis. They
      are returned separately with their n, so the exclusion is visible rather than
      quiet.
    * **An honest empty branch.** ``summarize([])`` returns all-``None`` percentiles
      with an all-ZERO histogram, which draws as a flat row of empty bars — a
      fabricated "we measured, and it was nothing". ``measurable`` says whether there
      is anything to draw at all.

    THE BINS ARE UNEQUAL IN WIDTH (0-99, 100-299, … 2000+), so this is a categorical
    bar chart over labelled ranges and NOT a density histogram: bar length may be
    read against bar length, but the shape is not a distribution's shape. The
    frontend says so on the axis.

    NOTE the deliberate difference from :func:`quarantine_composition`, which OMITS a
    reason that condemned nothing while this KEEPS a range that holds nothing. It is
    not an inconsistency. A word-count range is a defined interval over a continuous
    quantity, so "no article was 600-999 words" is a real observation and drawing it
    at zero is honest. A quarantine reason is a category that may not exist in this
    corpus's criteria version at all, so a zero there would be an invented slot.

    Cost: this is a full ``articles`` scan, so it belongs behind an explicit user
    action, never a tab-select autoload.
    """
    from src.analytics.article_length import article_length_report

    rep = article_length_report(session)
    by_lang = rep.get("word_count_by_language", {}) or {}
    segmented: dict[str, dict] = {}
    unsegmented: dict[str, dict] = {}
    for lang, s in by_lang.items():
        (unsegmented if s.get("unsegmented") else segmented)[lang] = s
    # Re-bin over the SEGMENTED languages only, by summing their per-language
    # histograms — the report's bucket labels are the shared vocabulary, so this is
    # addition, not a second binning pass with its own boundaries.
    labels: list[str] = []
    for s in segmented.values():
        for lab in (s.get("histogram") or {}):
            if lab not in labels:
                labels.append(lab)
    hist = {lab: 0 for lab in labels}
    for s in segmented.values():
        for lab, c in (s.get("histogram") or {}).items():
            hist[lab] += int(c or 0)
    seg_n = sum(int(s.get("n") or 0) for s in segmented.values())
    unseg_n = sum(int(s.get("n") or 0) for s in unsegmented.values())
    shown = [
        {"language": lang, "n": int(s.get("n") or 0), "median": s.get("median"),
         "p90": s.get("p90")}
        for lang, s in sorted(segmented.items(), key=lambda kv: -int(kv[1].get("n") or 0))
        if int(s.get("n") or 0) >= min_n
    ]
    return {
        "buckets": [{"label": lab, "n": hist[lab]} for lab in labels],
        "languages": shown,
        "excluded_unsegmented": {
            "languages": sorted(unsegmented),
            "n": unseg_n,
        },
        "scanned": int(rep.get("scanned") or 0),
        "with_word_count": int(rep.get("with_word_count") or 0),
        "n": seg_n,
        # The one field the frontend must branch on: an all-zero histogram over an
        # empty set is not a measurement of zeros.
        "measurable": seg_n > 0,
        "method": (
            "Word counts recorded at ingest, grouped into labelled ranges. Languages "
            "whose text is not space-separated are excluded and counted separately, "
            "because a word count is meaningless for them."
        ),
        "caveat": (
            "The ranges are NOT equal in width, so read one bar against another but "
            "not the shape as a distribution. Counts only, never a score — a long "
            "article is not better and a short one is not click-bait."
        ),
    }
