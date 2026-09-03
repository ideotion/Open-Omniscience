"""
Standing source AUDITOR (Part-1 Phase 1) — the one-shot quality DIAGNOSTIC generalized into a
continuous, in-app quality gate. FLAG-ONLY this session (ruling Q2a): the auto-demote machinery is
built but ships DEFAULT-OFF, activation gated on the operator's Phase-0 calibration.

THE LOAD-BEARING REFRAME (binding): this audits EXTRACTION VALIDITY / content-vs-non-content, NEVER
editorial merit. "Failing" = *this source's scrapes are systematically not usable articles* (paywall
stubs, nav/index pages, consent walls, wrong-DOM extraction), NEVER "terse or unfamiliar prose" —
which is legitimate variety and is exactly what a naive length/structure auditor would wrongly cut.

Honesty by construction (the project's spec): NO blended score — a source's STATUS is the categorical
rollup of its LIST of failing criteria, each carried with its value + the cohort baseline + n. Every
criterion is corpus-relative to the source's SAME-LANGUAGE cohort (robust median+MAD/percentiles);
a cohort below a floor gets NO baseline (said honestly). Count-only over the corpus (reuses the
source_quality collectors — never the SQLCipher codec column-order trap). Actions are reversible
(``enabled=false`` + a recorded reason, never a delete). A per-region flag-distribution self-audit
protects the de-US-centring investment; a maintainer allowlist caps a trusted atypical source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from src.analytics import source_quality as sq
from src.database.models import Source

SCHEMA = "oo-source-audit-1"

# --- tunables (the "agreed policy" — VISIBLE + configurable; no absolute magic thresholds, all
#     cohort-relative except the two structural floors) ---------------------------------------- #
MIN_SOURCE_ARTICLES = 20   # a source below this has too few articles to audit (reported, not judged)
SOURCE_COHORT_FLOOR = 8    # a language cohort of fewer sources than this gets no criterion baseline
COHORT_ARTICLE_FLOOR = sq.COHORT_FLOOR  # the per-article baseline floor (reused from source_quality)
TAIL_P = 90                # a per-source value beyond its cohort's p90/p10 fails that criterion
# ABSOLUTE floor for an EXTRACTION-FAILURE criterion (pathology = furniture repetition). A source
# whose articles are >= this fraction nav-DOM furniture-repetition is a broken scrape in ABSOLUTE
# terms, so it is caught even when the cohort-relative tail cannot see it — the crucial case where a
# whole same-language cohort is degrading (a scraper regression) or is below the floor, which would
# otherwise let the WORST sources sit AT the robust p90 and escape (the nearest-rank tail trap).
# NEVER applied to the soft/style-ambiguous criteria: an absolute short/outlier/furniture floor would
# flag legitimate terse or atypical prose (the reframe forbids it).
PATHOLOGY_ABS_FLOOR = 0.5

# MINIMUM EVIDENCE for the extraction-failure criterion to fire from the COHORT TAIL.
#
# The tail test is `value > cohort p90`, and for pathology_rate a healthy cohort's p90 is
# exactly 0.0 -- the overwhelming majority of sources have NO furniture-repetition at all.
# So `> p90` reduces to `> 0`, and ANY single pathological article puts a source in the
# "tail". Because this criterion is the extraction-failure signature, `derive_status` then
# escalates it to degraded (alone) or failing (with any soft flag).
#
# Field bundle 2026-08-02: ALL 63 sources reported "failing" were flagged this way, every
# one of them at a pathology_rate BELOW its own absolute floor -- aljazeera.net at 0.0010,
# ladepeche.fr at 0.0023, nicematin.com at 0.0005 (ONE article in 1,992). The report's
# headline was 63 failing / 71 degraded and not one was an extraction failure.
#
# This is the twin of the tail-blindness lesson that put PATHOLOGY_ABS_FLOOR here: that one
# fixed the direction where a DEGRADED cohort hides a broken source; this is the direction
# where a PERFECTLY CLEAN cohort (zero spread, p90 == mad == 0) turns noise into a verdict.
# A rate cannot tell 1 bad article in 1,992 from 600 in 1,200, so the guard is on the raw
# COUNT: below this many pathological articles there is no signature to see, only articles.
#
# Deliberately NOT applied to `abs_hit`: a source at or above the absolute floor is flagged
# on its own evidence whatever its cohort does, which is the property that lesson bought.
_MIN_PATHOLOGY_ARTICLES = 5

# The criteria panel. Each is EXTRACTION-VALIDITY, corpus-relative, and marked whether it is a
# high-confidence EXTRACTION-FAILURE signature (the only kind that can drive auto-demote — never
# structural style). ``bad`` is the tail direction that indicates a problem.
CRITERIA: tuple[dict, ...] = (
    {"name": "outlier_rate", "bad": "high", "extraction_failure": False,
     "desc": "fraction of the source's (segmented-language) articles whose keyword-stat ratios sit "
             "in their cohort tail — a proxy for degenerate extraction, but atypical-legit sources "
             "also run high, so this alone is a WATCH flag, never failing."},
    {"name": "pathology_rate", "bad": "high", "extraction_failure": True,
     "desc": "fraction with the furniture-repetition pathology (high mention_density + low "
             "type_token + high single_kw_dominance) — the nav-DOM 'Share Now x30' signature."},
    {"name": "furniture_share", "bad": "high", "extraction_failure": False,
     "desc": "fraction of the source's top-12 keywords that are cross-source furniture (DF-ubiquity)."},
    {"name": "language_mismatch_rate", "bad": "high", "extraction_failure": False,
     "desc": "fraction of the source's articles whose language differs from its asserted "
             "Source.language — a wrong-DOM / wrong-page extraction signal."},
    {"name": "short_article_rate", "bad": "high", "extraction_failure": False,
     "desc": "fraction of the source's SEGMENTED articles below its cohort's low word-count tail — "
             "a nav/stub CORROBORATOR (script-aware: unsegmented articles are excluded, never "
             "penalised for word_count). SOFT on its own: terse/brief-wire prose is legitimate "
             "variety, so short alone is only a watch — it drives 'failing' ONLY when it corroborates "
             "the pathology (furniture-repetition) extraction-failure signature."},
)
_CRIT_NAMES = tuple(c["name"] for c in CRITERIA)
_EXTRACTION_FAILURE_CRIT = frozenset(c["name"] for c in CRITERIA if c["extraction_failure"])

STATUSES = ("healthy", "watch", "degraded", "failing")


@dataclass
class SourceAudit:
    source_id: int
    domain: str | None
    language: str | None
    region: str | None
    article_count: int
    metrics: dict[str, float] = field(default_factory=dict)      # raw per-source values
    failing_criteria: list[dict] = field(default_factory=list)   # value + baseline + n per failure
    status: str = "healthy"
    allowlisted: bool = False


# --------------------------------------------------------------------------- #
# Per-source count-only metric aggregation (reuses the source_quality collectors)
# --------------------------------------------------------------------------- #

def cohort_from_stats(stats: list) -> dict:
    """The two ARTICLE-level cohort statistics ``per_source_metrics`` judges against, split out
    so they can be computed once over the whole corpus and reused (S5.1). PURE.

    ``baselines`` -- robust per-language baselines for the four count-only ratios.
    ``lang_short_cut`` -- the per-language p10 word count (segmented articles only; a cohort
    below the floor gets ``None``, said honestly, rather than a cut derived from too little).
    """
    baselines = sq.build_baselines(stats, floor=COHORT_ARTICLE_FLOOR)
    lang_wcs: dict[str, list[int]] = {}
    for s in stats:
        if not s.unsegmented and s.word_count is not None:
            lang_wcs.setdefault(s.language, []).append(s.word_count)
    lang_short_cut: dict[str, float | None] = {}
    for lang, wcs in lang_wcs.items():
        rs = sq.robust_stats([float(w) for w in wcs])
        lang_short_cut[lang] = rs["p10"] if rs["n"] >= COHORT_ARTICLE_FLOOR else None
    return {"baselines": baselines, "lang_short_cut": lang_short_cut}


def per_source_metrics(
    session: Session, *, source_ids: set[int] | None = None,
    cohort: dict | None = None,
    stats: list | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> dict[int, dict]:
    """Count-only per-source extraction-validity metrics, derived from the shipped source_quality
    collectors (no article-content decrypt). Returns ``{source_id: {metrics..., language, region,
    article_count, dominant_lang}}``. UNSEGMENTED articles are excluded from the word-count and
    keyword-ratio criteria (script-aware) but still counted in article_count + language_mismatch.

    ``source_ids`` + ``cohort`` are the S5.1 split: judge a handful of sources against a
    cohort computed ONCE over the whole corpus, instead of re-reading the corpus per batch.
    Passing ``source_ids`` without a ``cohort`` raises rather than answering.

    QUARANTINED ARTICLES ARE EXCLUDED, inherited from ``collect_article_stats`` (F4,
    2026-08-03): an article the article gate already condemned as a non-article must not count
    toward its SOURCE's extraction verdict. Two gates sharing an input and disagreeing about it
    is precisely what a single settings panel makes visible and two panels hide.

    The PROVENANCE exemption that the quality REPORT applies is deliberately NOT applied here.
    It would be a different and much larger change than it looks: a source missing from this
    dict is "no evidence to judge" (the 2026-07-23 zero-evidence rule), so exempting the
    synthetic ``hazard.*``/``law.*`` sources would make them permanently unqualifiable, and
    ``select_sources`` admits only qualified sources -- a collection-eligibility change, from a
    finding that was about a distorted BASELINE and a misleading report. Their verdicts were
    never at risk either way (they carry zero pathological articles, and auto-demote is
    default-off), so there is nothing here to fix in a hurry and a real way to get it wrong.
    """
    # ``stats`` lets a caller that has ALREADY scanned pass its rows in. Without it the
    # freeze below scanned the whole corpus TWICE -- once for the article-level cohort and
    # once here -- which the once-per-run statement count caught immediately: 2, not 1.
    if stats is None:
        stats = sq.collect_article_stats(
            session, source_ids=source_ids, should_pause=should_pause
        )
    if cohort is None:
        # No frozen cohort -> derive it from THESE stats, which is only meaningful over the
        # whole corpus. A caller that scopes the scan and supplies no cohort would be judging
        # a handful of sources against a baseline made of themselves, so it is refused rather
        # than answered: a cohort of the accused is the fabricated-baseline defect.
        if source_ids is not None:
            raise ValueError(
                "a scoped per_source_metrics needs a frozen cohort -- deriving the baseline "
                "from the scoped sources alone would judge them against themselves"
            )
        cohort = cohort_from_stats(stats)
    baselines = cohort["baselines"]
    lang_short_cut = cohort["lang_short_cut"]
    outliers = sq.flag_outliers(stats, baselines, floor=COHORT_ARTICLE_FLOOR)
    outlier_ids = {o["article_id"] for o in outliers}
    pathology_ids = {o["article_id"] for o in outliers if o.get("pathology_furniture_repetition")}

    # source metadata + regions (scoped with the scan -- the catalog is tens of thousands of
    # rows and reading all of them per batch is the same defect one table over)
    meta_q = session.query(Source.id, Source.domain, Source.language, Source.region)
    if source_ids is not None:
        meta_q = meta_q.filter(Source.id.in_(sorted(source_ids)))
    src_meta = {int(sid): (dom, lang, reg) for sid, dom, lang, reg in meta_q}

    per: dict[int, dict] = {}
    for s in stats:
        sid = s.source_id
        if sid is None:
            continue
        d = per.setdefault(sid, {
            "n": 0, "n_segmented": 0, "outliers": 0, "pathology": 0, "short": 0,
            "lang_counts": {}, "langs_seen": set(),
        })
        d["n"] += 1
        d["lang_counts"][s.language] = d["lang_counts"].get(s.language, 0) + 1
        d["langs_seen"].add(s.language)
        if s.article_id in outlier_ids:
            d["outliers"] += 1
        if s.article_id in pathology_ids:
            d["pathology"] += 1
        if not s.unsegmented:
            d["n_segmented"] += 1
            cut = lang_short_cut.get(s.language)
            if cut is not None and s.word_count is not None and s.word_count < cut:
                d["short"] += 1

    out: dict[int, dict] = {}
    for sid, d in per.items():
        domain, src_lang, region = src_meta.get(sid, (None, None, None))
        dominant_lang = max(d["lang_counts"], key=lambda k: d["lang_counts"][k]) if d["lang_counts"] else None
        src_base = sq._base_lang(src_lang) if src_lang else None
        # language mismatch: an article's dominant-script language differs from the source's asserted
        # language. Only meaningful when the source declares a language.
        mism = 0
        if src_base:
            for lang, c in d["lang_counts"].items():
                if lang != src_base and lang != "unknown":
                    mism += c
        n = d["n"]
        nseg = d["n_segmented"]
        out[sid] = {
            "domain": domain, "language": src_lang, "region": region,
            "article_count": n, "dominant_lang": dominant_lang or src_base or "unknown",
            "outlier_rate": round(d["outliers"] / nseg, 4) if nseg else 0.0,
            "pathology_rate": round(d["pathology"] / n, 4) if n else 0.0,
            # The RAW count behind pathology_rate. A rate alone cannot tell 1 bad article
            # in 1,992 from 600 in 1,200, and the cohort-tail test cannot either when the
            # cohort's p90 is 0.0 -- see _MIN_PATHOLOGY_ARTICLES.
            "pathology_articles": d["pathology"],
            "language_mismatch_rate": round(mism / n, 4) if (n and src_base) else 0.0,
            "short_article_rate": round(d["short"] / nseg, 4) if nseg else 0.0,
        }
    return out


def frozen_cohort(
    session: Session, *, should_pause: Callable[[], bool] | None = None,
    with_furniture: bool = True, min_articles: int = MIN_SOURCE_ARTICLES,
) -> dict:
    """Every COHORT statistic a qualification verdict is measured against, computed ONCE over
    the whole corpus so a batch of candidates does not re-read it (S5.1).

    Measured before this existed: ``per_source_metrics`` alone held ~131.8 MiB of Python per
    call (a 17.1 MiB aggregate dict, a 75.0 MiB ``ArticleStat`` list at 669 B each, 39.7 MiB
    of per-source dicts) plus the connection's page cache -- **once per batch of 20**, from
    both the bulk job and the per-pass ride-along. The candidates' own metrics are cheap; it
    was always the cohort that cost, and a cohort does not change per batch.

    WHAT THIS CHANGES, stated rather than buried: a batch is judged against a baseline up to
    one run old. That is why ``CRITERIA_VERSION`` is bumped -- an attempt row must not read as
    though it were judged the old way. It is also why the numbers below travel with the
    result: ``token`` says which corpus state the baseline reflects and ``articles`` how much
    of it, so a stale verdict is visible rather than inferred.

    ``with_furniture=False`` skips the cross-source fingerprint DF, which is the expensive
    half (one ``corpus_keywords`` per source over a bounded sample). A caller that skips it
    gets ``furniture_df: None``, and every share then reads 0.0 -- the same honest zero
    ``audit_sources`` already publishes when it declines that layer.

    ``min_articles`` MUST match the threshold the consumer will judge at, and is recorded in
    the result so a mismatch can be refused instead of silently answered. It decides WHICH
    sources form the cohort, so a cut frozen at one threshold is a different baseline from a
    cut frozen at another -- the qualification gate judges at ``TRIAL_MIN_ARTICLES`` (1) and
    the report at ``MIN_SOURCE_ARTICLES`` (20). The parity twin caught this on its first run:
    frozen at 20 against a fixture of 4-article sources, the cut was EMPTY, so three soft
    criteria silently stopped being flaggable.
    """
    from src.analytics import serve_gate

    stats = sq.collect_article_stats(session, should_pause=should_pause)
    cohort = cohort_from_stats(stats)
    per = per_source_metrics(session, cohort=cohort, stats=stats, should_pause=should_pause)
    furn_df: dict[str, int] | None = None
    furn_n: int | None = None
    if with_furniture and per:
        shares_input = list(per)
        source_to_articles = sq_source_to_articles(session, source_ids=set(shares_input))
        import random

        per_top: dict[int, list[str]] = {}
        for sid in shares_input:
            ids = source_to_articles.get(sid, [])
            if not ids:
                per_top[sid] = []
                continue
            if len(ids) > sq.FINGERPRINT_SAMPLE_CAP:
                ids = sorted(
                    random.Random(sq.DEFAULT_SEED + sid).sample(ids, sq.FINGERPRINT_SAMPLE_CAP)
                )
            ck = sq.q.corpus_keywords(session, article_ids=ids, limit=sq.TOP_KEYWORDS)
            per_top[sid] = [term["normalized"] for term in ck.get("terms", [])]
        furn_df = sq.compute_cross_source_df(per_top)
        furn_n = len(per_top)
        _flag, shares = sq.flag_furniture_sources(per_top, furn_df, n_sources=furn_n)
        for sid, m in per.items():
            m["furniture_share"] = shares.get(sid, 0.0)
    else:
        for m in per.values():
            m["furniture_share"] = 0.0

    return {
        "cohort": cohort,
        "cohort_cut": source_cohort_cut(per, min_articles=min_articles),
        "min_articles": min_articles,
        "furniture_df": furn_df,
        "furniture_n_sources": furn_n,
        "token": serve_gate.change_token(session, articles=True, sources=True),
        "articles": len(stats),
        "sources": len(per),
    }


def scoped_metrics(
    session: Session, source_ids: set[int], frozen: dict, *,
    should_pause: Callable[[], bool] | None = None,
) -> dict[int, dict]:
    """The candidates' OWN metrics, scoped in SQL, judged against ``frozen``'s cohort (S5.1).

    A source absent from the result has ZERO stored articles -- the 2026-07-23 zero-evidence
    rule -- and the caller must keep testing MEMBERSHIP rather than reading a missing entry as
    a clean pass."""
    per = per_source_metrics(
        session, source_ids=source_ids, cohort=frozen["cohort"], should_pause=should_pause
    )
    if not per:
        return per
    df = frozen.get("furniture_df")
    if df is None:
        for m in per.values():
            m["furniture_share"] = 0.0
    else:
        shares = _furniture_share_by_source(
            session, list(per), cross_df=df, n_sources=frozen.get("furniture_n_sources"),
        )
        for sid, m in per.items():
            m["furniture_share"] = shares.get(sid, 0.0)
    return per


def _furniture_share_by_source(
    session: Session, source_ids: list[int], *,
    cross_df: dict[str, int] | None = None, n_sources: int | None = None,
) -> dict[int, float]:
    """Per-source top-12 furniture share, reusing the source_quality fingerprint + cross-source DF.
    Bounded per-source sample (the FINGERPRINT_SAMPLE_CAP guard) so the IN(...) stays safe.

    ``cross_df``/``n_sources`` (S5.1) let a caller supply a FROZEN document-frequency map
    instead of deriving one from ``source_ids``. That distinction is load-bearing rather than
    an optimisation: "how much of this source's top-12 is furniture" is measured against how
    ubiquitous those terms are ACROSS SOURCES, so deriving the DF from a 20-source batch would
    give the same source a different share in every batch it appeared in. The source's own
    top-12 is its own metric; the DF is the cohort's."""
    import random

    source_to_articles = sq_source_to_articles(session, source_ids=set(source_ids))
    per_top: dict[int, list[str]] = {}
    for sid in source_ids:
        ids = source_to_articles.get(sid, [])
        if not ids:
            per_top[sid] = []
            continue
        if len(ids) > sq.FINGERPRINT_SAMPLE_CAP:
            ids = sorted(random.Random(sq.DEFAULT_SEED + sid).sample(ids, sq.FINGERPRINT_SAMPLE_CAP))
        ck = sq.q.corpus_keywords(session, article_ids=ids, limit=sq.TOP_KEYWORDS)
        per_top[sid] = [t["normalized"] for t in ck.get("terms", [])]
    df = cross_df if cross_df is not None else sq.compute_cross_source_df(per_top)
    n = n_sources if n_sources is not None else len(per_top)
    _flagged, shares = sq.flag_furniture_sources(per_top, df, n_sources=n)
    return shares


def sq_source_to_articles(
    session: Session, *, source_ids: set[int] | None = None
) -> dict[int, list[int]]:
    """``{source_id: [article_id, ...]}``. ``source_ids`` scopes it in SQL (S5.1) -- the
    unscoped form walks every article row in the corpus, which is fine once per run and is
    not fine once per batch of 20."""
    from src.database.models import Article
    q = session.query(Article.id, Article.source_id)
    if source_ids is not None:
        if not source_ids:
            return {}
        q = q.filter(Article.source_id.in_(sorted(source_ids)))
    out: dict[int, list[int]] = {}
    for aid, sid in q:
        if sid is not None:
            out.setdefault(int(sid), []).append(int(aid))
    return out


# --------------------------------------------------------------------------- #
# Cohort-relative criterion flagging + status derivation (PURE)
# --------------------------------------------------------------------------- #

def source_cohort_cut(per_source: dict[int, dict], *,
                      min_articles: int = MIN_SOURCE_ARTICLES) -> dict[str, dict[str, dict]]:
    """The per-language, per-criterion robust baselines a source is judged against, split out
    of ``flag_criteria`` so they can be frozen once per run (S5.1). PURE.

    This is a SOURCE-level cohort, so it is only meaningful over every auditable source in
    the corpus -- which is exactly why it has to be frozen rather than recomputed from
    whatever handful of candidates a batch happens to hold."""
    auditable = {sid: m for sid, m in per_source.items() if m["article_count"] >= min_articles}
    by_lang: dict[str, dict[str, list[float]]] = {}
    for m in auditable.values():
        lang = m["dominant_lang"]
        c = by_lang.setdefault(lang, {name: [] for name in _CRIT_NAMES})
        for name in _CRIT_NAMES:
            c[name].append(m[name])
    cut: dict[str, dict[str, dict]] = {}
    for lang, vals in by_lang.items():
        cut[lang] = {name: sq.robust_stats(vals[name]) for name in _CRIT_NAMES}
    return cut


def flag_criteria(per_source: dict[int, dict], *, cohort_floor: int = SOURCE_COHORT_FLOOR,
                  min_articles: int = MIN_SOURCE_ARTICLES, tail_p: int = TAIL_P,
                  cohort_cut: dict[str, dict[str, dict]] | None = None) -> dict[int, list[dict]]:
    """For each auditable source, the LIST of criteria whose value sits in the BAD tail of the
    source's SAME-LANGUAGE cohort — each with value + baseline + n + how it was ``flagged_by``. A
    cohort below ``cohort_floor`` sources gets NO baseline, so the SOFT (style-ambiguous) criteria
    are not flaggable there (said honestly, ``baseline: null``). The one EXTRACTION-FAILURE criterion
    (pathology) additionally flags on an ABSOLUTE floor (``PATHOLOGY_ABS_FLOOR``) so a broken scrape
    stays visible even with no usable cohort / a wholly-degraded cohort (the nearest-rank tail trap).
    PURE."""
    auditable = {sid: m for sid, m in per_source.items() if m["article_count"] >= min_articles}
    # The cohort baselines: derived from THESE sources unless a frozen cut is supplied
    # (S5.1). Each rs carries n; usable only when n >= cohort_floor.
    cut = cohort_cut if cohort_cut is not None else source_cohort_cut(
        per_source, min_articles=min_articles
    )

    out: dict[int, list[dict]] = {}
    for sid, m in auditable.items():
        lang = m["dominant_lang"]
        fails: list[dict] = []
        # A language the frozen cohort has never seen has NO baseline -- an empty
        # robust_stats reads n=0, so the soft criteria are not flaggable, which is the
        # same honest answer a below-floor cohort gets. Never a borrowed baseline.
        lang_cut = cut.get(lang, {})
        for crit in CRITERIA:
            name, bad = crit["name"], crit["bad"]
            rs = lang_cut.get(name) or sq.robust_stats([])
            v = m[name]
            has_baseline = rs["n"] >= cohort_floor and rs["p90"] is not None
            tail_hit = has_baseline and ((v > rs["p90"]) if bad == "high" else (v < rs["p10"]))
            # An extraction-failure verdict needs enough evidence to BE a signature. On a
            # clean cohort (p90 == 0.0) the tail test degenerates to "> 0", so a single
            # pathological article would otherwise read as a broken scrape. The absolute
            # floor below is untouched by this.
            if tail_hit and crit["extraction_failure"]:
                if m.get("pathology_articles", 0) < _MIN_PATHOLOGY_ARTICLES:
                    tail_hit = False
            # the absolute-floor escape fires ONLY for an extraction-failure criterion (pathology) —
            # it is what keeps a broken source visible when its cohort can't (see PATHOLOGY_ABS_FLOOR).
            abs_hit = crit["extraction_failure"] and v >= PATHOLOGY_ABS_FLOOR
            if not (tail_hit or abs_hit):
                continue
            flagged_by = (["cohort_tail"] if tail_hit else []) + (["absolute_floor"] if abs_hit else [])
            fails.append({
                "criterion": name, "value": v, "direction": bad,
                "extraction_failure": crit["extraction_failure"],
                "flagged_by": flagged_by,
                "baseline": ({"median": rs["median"], "p10": rs["p10"], "p90": rs["p90"],
                              "mad": rs["mad"], "n": rs["n"]} if has_baseline else None),
                "absolute_floor": PATHOLOGY_ABS_FLOOR if crit["extraction_failure"] else None,
                # The raw evidence behind an extraction-failure flag, so a reader can see
                # whether a rate rests on 6 articles or 600 without recomputing it.
                **({"pathology_articles": m.get("pathology_articles"),
                    "min_articles_for_tail": _MIN_PATHOLOGY_ARTICLES}
                   if crit["extraction_failure"] else {}),
            })
        out[sid] = fails
    return out


def derive_status(failing: list[dict]) -> str:
    """Categorical status from the LIST of failing criteria — NOT a blended score, and built to
    HONOUR THE REFRAME: soft, style-ambiguous signals (short articles, atypical keyword stats,
    furniture overlap) NEVER exceed ``watch`` on their own — terse or unfamiliar prose is legitimate
    variety, so it can never be marked degraded/failing for it. Only the ``extraction_failure``
    signature (pathology_rate = the furniture-repetition / nav-DOM 'Share Now ×30' pattern) can:
    ``failing`` = that signature CORROBORATED by >=1 other tail signal (signature + sustained
    low-yield = a systematically non-usable source); ``degraded`` = the signature ALONE (a lone
    extraction-failure signal worth review, never yet auto-acted); ``watch`` = soft-only signal(s);
    ``healthy`` = none."""
    ef = [f for f in failing if f["extraction_failure"]]
    if ef and len(failing) >= 2:
        return "failing"
    if ef:
        return "degraded"
    if failing:
        return "watch"
    return "healthy"


def should_auto_demote(audit: SourceAudit, *, enabled: bool = False) -> tuple[bool, str | None]:
    """Whether to auto-demote (``enabled=false`` + reason). DEFAULT-OFF (ruling Q2a): with
    ``enabled=False`` this ALWAYS returns ``(False, None)``. When enabled, it fires ONLY on the
    high-confidence extraction-failure signature (status ``failing``, i.e. >=2 extraction-failure
    criteria), NEVER on structural style, NEVER on a soft/watch flag, and NEVER on an allowlisted
    source. Reversible by construction (the caller sets enabled=false + records the reason)."""
    if not enabled or audit.allowlisted or audit.status != "failing":
        return (False, None)
    sig = ", ".join(f"{f['criterion']}={f['value']}" for f in audit.failing_criteria
                    if f["extraction_failure"])
    corrob = ", ".join(f"{f['criterion']}={f['value']}" for f in audit.failing_criteria
                       if not f["extraction_failure"])
    return (True, f"auto-demote: extraction-failure signature ({sig})"
                  + (f" corroborated by {corrob}" if corrob else ""))


def region_self_audit(audits: list[SourceAudit]) -> dict:
    """Per-region flag distribution — the diversity guardrail. Surfaces whether failing/degraded
    flags concentrate in an under-represented region (which would erode the de-US-centring
    investment). Counts only; the operator reads it before enabling any auto-action."""
    # NB: STATUS NAMES ARE NEVER DICT KEYS in the returned payload — "degraded" contains the
    # substring "grade", which the project's recursive no-score key-walkers ban (source_quality /
    # conjunction / scale_bench tests). Per-status tallies ride as {"status": s, "n": n} objects
    # (status as a VALUE, safe) so the audit stays honestly free of score-like keys.
    counts: dict[str, dict[str, int]] = {}
    for a in audits:
        r = a.region or "unknown"
        d = counts.setdefault(r, dict.fromkeys(STATUSES, 0))
        d[a.status] += 1
    out = {}
    for r, d in sorted(counts.items()):
        total = sum(d.values())
        out[r] = {"counts": [{"status": s, "n": d[s]} for s in STATUSES], "total": total,
                  "pct_failing": round(100.0 * d["failing"] / total, 2) if total else 0.0}
    return {
        "by_region": out,
        "caveat": "A high pct_failing concentrated in an under-represented region is a RED FLAG — "
                  "review before enabling auto-demote; never disproportionately cut a bucket. Counts "
                  "only, no score.",
    }


def audit_sources(
    session: Session, *, allowlist: set[str] | None = None, with_furniture: bool = True,
    min_articles: int = MIN_SOURCE_ARTICLES, cohort_floor: int = SOURCE_COHORT_FLOOR,
) -> dict:
    """The full audit: per-source status + failing-criteria list + the region self-audit. Read-only,
    count-only (furniture adds a bounded per-source keyword query when ``with_furniture``). FLAG-ONLY
    — the returned rows carry auto_demote_candidate (computed with enabled=False by default, so it is
    always False here; the caller decides whether to enable). No blended score."""
    allowlist = allowlist or set()
    per = per_source_metrics(session)
    if with_furniture:
        shares = _furniture_share_by_source(session, list(per))
        for sid, m in per.items():
            m["furniture_share"] = shares.get(sid, 0.0)
    else:
        for m in per.values():
            m["furniture_share"] = 0.0

    fails_by_source = flag_criteria(per, cohort_floor=cohort_floor, min_articles=min_articles)
    audits: list[SourceAudit] = []
    for sid, m in per.items():
        if m["article_count"] < min_articles:
            continue
        fails = fails_by_source.get(sid, [])
        allowlisted = (m["domain"] or "") in allowlist
        status = derive_status(fails)
        if allowlisted and status == "failing":
            status = "watch"  # an allowlisted source is never marked failing (guardrail)
        audits.append(SourceAudit(
            source_id=sid, domain=m["domain"], language=m["language"], region=m["region"],
            article_count=m["article_count"],
            metrics={name: m[name] for name in _CRIT_NAMES},
            failing_criteria=fails, status=status, allowlisted=allowlisted,
        ))

    # worst status first, and within a status the LARGEST-corpus source first (most junk = most
    # worth an operator's attention): sort ascending by (status-rank, article_count) then reverse.
    audits.sort(key=lambda a: (STATUSES.index(a.status), a.article_count), reverse=True)
    # per-status tallies as {"status": s, "n": n} objects — NEVER status-as-key ("degraded" would
    # trip the no-score key-walkers; see region_self_audit).
    _counts = dict.fromkeys(STATUSES, 0)
    for a in audits:
        _counts[a.status] += 1
    return {
        "schema": SCHEMA,
        "sources_audited": len(audits),
        "min_articles": min_articles,
        "status_counts": [{"status": s, "n": _counts[s]} for s in STATUSES],
        "criteria": list(CRITERIA),
        "region_self_audit": region_self_audit(audits),
        "sources": [
            {
                "source_id": a.source_id, "domain": a.domain, "language": a.language,
                "region": a.region, "article_count": a.article_count, "status": a.status,
                "allowlisted": a.allowlisted, "metrics": a.metrics,
                "failing_criteria": a.failing_criteria,
                "auto_demote_candidate": should_auto_demote(a, enabled=False)[0],
            }
            for a in audits
        ],
        "method": "Per-source extraction-validity criteria, each corpus-relative to the source's "
                  "same-language cohort (robust median+MAD+percentiles, n shown); status is the "
                  "categorical rollup of the failing-criteria list, never a blended score.",
        "caveat": "Audits EXTRACTION VALIDITY, never editorial merit — terse/unfamiliar prose is "
                  "legitimate variety and is never flagged for it. Flag-only; auto-demote is "
                  "default-off (ruling Q2a) and reversible. A cohort below the floor gets no "
                  "baseline (honest). No composite score.",
    }


def _walk_no_score(obj: Any) -> None:
    """Raises explicitly (never a bare ``assert``, which ``python -O``/
    ``PYTHONOPTIMIZE`` strips silently and would let this self-test's own
    no-fabricated-score check false-pass under that flag — transversal
    audit 09, 2026-07-25, §10.4)."""
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(b in str(k).lower() for b in banned):
                raise AssertionError(f"score-like key: {k}")
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


def run_source_audit_selftest() -> dict:
    """Prove the PURE mechanism (flag_criteria / derive_status / should_auto_demote / region
    self-audit) on hand-built per-source metrics — no DB, no score. The load-bearing checks: the
    EXTRACTION-FAILURE source is flagged failing; an ATYPICAL-but-valid source (terse prose = short
    articles only, no extraction-failure signature) is NOT failing; auto-demote is default-off; an
    allowlisted source is capped; a small cohort gets no baseline."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    def m(sid, *, lang="en", region="gb", n=100, outlier=0.1, path=0.02, mism=0.0, short=0.1,
          furn=0.1, path_articles=None):
        return {"domain": f"s{sid}.example", "language": lang, "region": region, "article_count": n,
                "dominant_lang": lang, "outlier_rate": outlier, "pathology_rate": path,
                # Derived from the rate so the fixture stays self-consistent: the real
                # per_source_metrics carries both, and the tail guard reads the COUNT.
                "pathology_articles": round(path * n) if path_articles is None else path_articles,
                "language_mismatch_rate": mism, "short_article_rate": short, "furniture_share": furn}

    # a healthy cohort (>= floor sources) + one clear EXTRACTION-FAILURE (high pathology + high short)
    per = {i: m(i) for i in range(10)}
    per[99] = m(99, path=0.9, short=0.8, outlier=0.9, furn=0.6)   # deswater-like nav source
    per[50] = m(50, short=0.85)                                    # terse-prose source: ONLY short high
    fails = flag_criteria(per, cohort_floor=8, min_articles=20)
    audits = {sid: SourceAudit(source_id=sid, domain=per[sid]["domain"], language="en", region="gb",
                               article_count=100, metrics={}, failing_criteria=fails.get(sid, []),
                               status=derive_status(fails.get(sid, []))) for sid in per}
    check("extraction_failure_source_is_failing", audits[99].status == "failing", str(audits[99].failing_criteria))
    check("terse_prose_source_not_failing", audits[50].status != "failing",
          f"{audits[50].status}: {[f['criterion'] for f in audits[50].failing_criteria]}")
    check("healthy_source_is_healthy", audits[0].status == "healthy")

    # auto-demote default-off
    check("auto_demote_off_by_default", should_auto_demote(audits[99], enabled=False) == (False, None))
    demote, reason = should_auto_demote(audits[99], enabled=True)
    check("auto_demote_fires_only_when_enabled_on_failing", demote is True and reason is not None)
    check("auto_demote_never_on_terse_prose", should_auto_demote(audits[50], enabled=True)[0] is False)
    allow = SourceAudit(source_id=99, domain="s99.example", language="en", region="gb",
                        article_count=100, failing_criteria=audits[99].failing_criteria,
                        status="watch", allowlisted=True)  # capped at watch by the guardrail
    check("allowlisted_never_auto_demoted", should_auto_demote(allow, enabled=True)[0] is False)

    # small cohort -> no baseline -> the SOFT (style-ambiguous) criteria are not flaggable (honest
    # gap); but the ABSOLUTE extraction-failure floor still catches a broken source there.
    small = {i: m(i) for i in range(3)}
    small[8] = m(8, short=0.9, outlier=0.9, furn=0.9, path=0.0)   # soft-only -> no cohort -> no flags
    small[9] = m(9, path=0.9)                                     # absolute pathology -> still caught
    small_fails = flag_criteria(small, cohort_floor=8, min_articles=20)
    check("small_cohort_no_baseline", small_fails.get(8) == [], str(small_fails.get(8)))
    check("small_cohort_pathology_caught_by_absolute_floor",
          [f["criterion"] for f in small_fails.get(9, [])] == ["pathology_rate"])

    # H1 regression: a DEGRADED cohort where extraction-failure sources are a large fraction — the
    # robust p90 lands on a bad value so the cohort tail can't see them, but the absolute floor keeps
    # the worst visible (it must never read healthy precisely when a whole cohort is breaking).
    degraded_cohort = {i: m(i) for i in range(6)}
    degraded_cohort[97] = m(97, path=0.95, short=0.9, outlier=0.9)
    degraded_cohort[98] = m(98, path=0.95, short=0.9, outlier=0.9)
    dc = flag_criteria(degraded_cohort, cohort_floor=8, min_articles=20)
    dc_status = derive_status(dc.get(97, []))
    check("degraded_cohort_worst_not_healthy",
          any(f["criterion"] == "pathology_rate" for f in dc.get(97, [])) and dc_status != "healthy",
          f"{dc_status}: {[f['criterion'] for f in dc.get(97, [])]}")

    # The CLEAN-cohort direction (field bundle 2026-08-02). A healthy cohort's pathology
    # p90 is exactly 0.0, so `> p90` degenerates to `> 0` and ONE bad article out of
    # thousands read as an extraction failure. All 63 sources the field report called
    # "failing" were this, every one below its own absolute floor.
    clean = {i: m(i, path=0.0, path_articles=0) for i in range(10)}
    clean[42] = m(42, n=1992, path=0.0005, path_articles=1)  # nicematin.com, verbatim
    cf = flag_criteria(clean, cohort_floor=8, min_articles=20)
    check("one_bad_article_in_thousands_is_not_an_extraction_failure",
          derive_status(cf.get(42, [])) != "failing"
          and not any(f["criterion"] == "pathology_rate" for f in cf.get(42, [])),
          f"{derive_status(cf.get(42, []))}: {[f['criterion'] for f in cf.get(42, [])]}")

    # ...and the NEGATIVE-SPACE TWIN: the guard must not blind the tail test. A source with
    # REAL evidence, still well under the absolute floor, must remain visible on the cohort
    # tail alone -- otherwise this fix would have traded false alarms for a real miss.
    clean[43] = m(43, n=400, path=0.05, path_articles=20)
    cf2 = flag_criteria(clean, cohort_floor=8, min_articles=20)
    check("a_real_pathology_signature_below_the_absolute_floor_is_still_flagged",
          any(f["criterion"] == "pathology_rate" for f in cf2.get(43, [])),
          f"{[f['criterion'] for f in cf2.get(43, [])]}")

    # region self-audit + no score
    ra = region_self_audit([SourceAudit(1, "a", "en", "gb", 100, status="failing"),
                            SourceAudit(2, "b", "fr", "fr", 100, status="healthy")])
    gb_failing = next(c["n"] for c in ra["by_region"]["gb"]["counts"] if c["status"] == "failing")
    check("region_self_audit_counts", gb_failing == 1)
    no_score = True
    try:
        _walk_no_score({"criteria": list(CRITERIA)})
        _walk_no_score(ra)
    except AssertionError:
        no_score = False
    check("no_score_field", no_score)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-source-audit-selftest-1",
        "passed": passed, "checks": checks, "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Hand-built per-source metrics through flag_criteria/derive_status/"
                  "should_auto_demote/region_self_audit.",
        "caveat": "Verifies the pure mechanism + the load-bearing reframe (terse prose is not "
                  "failing); the DB aggregation is covered by the pytest corpus. No score.",
    }
