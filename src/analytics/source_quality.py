"""
Source & article quality diagnostic — a TEMPORARY, removable EXPORT-ONLY triage bundle.

The live corpus contains items that are NOT articles (paywall stubs, nav/index pages, consent
walls, or one nav element like "Share Now" repeated with little text between). This produces the
evidence an external analyst needs to decide, PER SOURCE, whether to EXCLUDE it (a bad source),
OPTIMIZE the extractor (a real article the scraper mangled), or KEEP it (a genuine edge). It
detects non-articles THREE independent ways whose blind spots don't overlap — per-article
keyword-stat outliers (Layer A), a text sample from three independent selectors (Layer B), and
per-source keyword fingerprints (Layer C) — then hands the analyst a text sample + fingerprints.

BINDING honesty + safety (mirrors src/ai_layer/triage.py's EXPORT-ONLY precedent):
  * READ-ONLY. No writes to ANY table (never the trusted keyword index). No network. EXPORT-ONLY.
  * NO COMPOSITE SCORE anywhere. Every flag carries its raw value + the cohort baseline + n. Flags
    are DEDUCED candidates, never verdicts.
  * COUNT-ONLY over the whole corpus; Article.content is decrypted ONLY for the bounded text heads
    of the SAMPLED articles (the SQLCipher codec column-order trap: content sits before word_count
    in column order, so a per-row read of a late column drags content — we read the small columns
    in ONE pass, like article_length_report, and pull content only for the ≤N sampled ids).
  * ROBUST statistics only (median + MAD + percentiles) — keyword distributions are heavy-tailed,
    so mean/σ would lie. A cohort below a floor gets NO baseline, said honestly.
  * The pure core takes ``generated_at`` injected (never calls datetime.now itself) so it is
    deterministic and testable; the endpoint stamps the time.

The three-way design's POINT is the non-overlapping blind spots: a stats selector only finds what
its stats measure, so a fake with normal stats is invisible to it — the random control catches
those. The README spells out the recall-gap analysis this enables.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics import queries as q
from src.analytics.managed import UNSEGMENTED
from src.catalog.provenance import HAZARD, LAW, NEWSLETTER, STATISTICS, WIKIPEDIA, provenance_of
from src.database.models import Article, ArticleLink, KeywordMention, Source
from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

# Provenance classes a keyword-RATIO audit cannot meaningfully judge (F4, 2026-08-03). These are
# not scrapes: a hazard record is a provider's own event line, a law document is a statute, a wiki
# page is an encyclopedia article, a newsletter is an email. Their ratios are legitimately unlike
# journalism, so measuring them against a news cohort describes the channel, not the extraction.
# Reused from PROVENANCE_CLASSES rather than re-listed, so a new class must be triaged here.
# `cited` and `web` are deliberately absent -- both ARE scraped web articles.
_AUDIT_EXEMPT_CLASSES = frozenset({HAZARD, LAW, WIKIPEDIA, NEWSLETTER, STATISTICS})

SCHEMA = "oo-source-quality-2"  # v2: unsegmented languages are NOT-ASSESSED (all 4 metrics N/A)

# --- Tunables (all disclosed in the manifest; propose, never auto-apply) ------------------- #
DEFAULT_SEED = 20260713          # fixed so the random-per-source control is reproducible
COHORT_FLOOR = 30                # a cohort below this n gets no baseline (said honestly)
TAIL_HIGH_P = 90                 # a value >= cohort p90 is a high-tail outlier
TAIL_LOW_P = 10                  # a value <= cohort p10 is a low-tail outlier
TEXT_HEAD_CHARS = 1500           # bounded content head for a sampled article
OUTLIER_CAP_PER_DIM_PER_SOURCE = 3   # so a noisy source can't flood the sample
FINGERPRINT_CAP_PER_SOURCE = 3
TOP_KEYWORDS = 12                # the per-source fingerprint size
# A source's fingerprint is computed over at most this many of its articles (seeded sample). Keeps
# the corpus_keywords IN(...) clause safely under SQLite's variable limit (999 on some SQLCipher
# builds); a top-12 furniture fingerprint is stable over a sample of this size. Disclosed per source.
FINGERPRINT_SAMPLE_CAP = 800
_IN_CHUNK = 800                  # chunk size for id IN(...) queries (stay under the 999-var floor)
# A keyword is "furniture" (cross-source ubiquitous) if it tops this fraction of sources...
FURNITURE_UBIQUITY_FRAC = 0.30
FURNITURE_MIN_SOURCES = 5        # ...but never below this absolute count (small corpus guard).
FURNITURE_SHARE_THRESHOLD = 0.34  # a source is flagged if >= this share of its top-12 is furniture
# The metadata-only pre-label thresholds, named ONCE so `_pre_label` and the `cheap_signal`
# selector cannot drift apart (F3, 2026-08-03 — the selector exists precisely because these two
# signals out-measured the expensive machinery, so a selector picking on a different bar than the
# label reports would make the enrichment figure meaningless).
_HIGH_LINK_DENSITY = 0.05        # external links per word
_VERY_SHORT_WORDS = 40
CHEAP_SIGNAL_CAP_PER_SOURCE = 3  # so one link-heavy source cannot flood the sample

# The 4 count-only dimensions and which tail is the suspicious one (for the "Share Now" pathology).
# high mention_density + low type_token + high single_kw_dominance TOGETHER = furniture repetition.
_METRICS = ("mention_density", "type_token", "vocab_sparsity", "single_kw_dominance")

# Cheap boilerplate phrases for the heuristic PRE-LABEL (a hint for the analyst, never a verdict).
_BOILERPLATE_PHRASES = (
    "subscribe to continue", "subscribe now", "enable javascript", "please enable",
    "page not found", "404", "access denied", "sign in to", "log in to", "create an account",
    "accept all cookies", "cookie policy", "we use cookies", "consent", "share now", "read more",
    "continue reading", "you have reached your", "for full access", "register to read",
)


def _base_lang(lang: str | None) -> str:
    return (lang or "unknown").split("-")[0].lower()


def _chunks(seq: list[int], n: int = _IN_CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# --------------------------------------------------------------------------- #
# Layer A — per-article count-only keyword-stat metrics + robust cohort baselines
# --------------------------------------------------------------------------- #

@dataclass
class ArticleStat:
    article_id: int
    source_id: int | None
    language: str
    word_count: int | None
    total_mentions: int
    distinct_keywords: int
    max_single_kw: int
    unsegmented: bool
    metrics: dict[str, float | None] = field(default_factory=dict)


def compute_metrics(
    *, word_count: int | None, total_mentions: int, distinct_keywords: int, max_single_kw: int,
    unsegmented: bool,
) -> dict[str, float | None]:
    """The 4 count-only ratios, or ``None`` where they cannot be trusted — never a fabricated 0.

    For an UNSEGMENTED language (zh/ja/th) ALL FOUR are ``None``: word_count is meaningless
    (``len(text.split())``), AND — the v2 correction — keyword extraction itself is degenerate
    without a segmenter (few/giant tokens), so type_token and single_kw_dominance are unreliable
    too. So an unsegmented article has no assessable metric and is never an outlier; its LANGUAGE
    is flagged as not-assessed instead. (v1 marked only the two word_count metrics N/A, which let
    the whole unsegmented cohort read as 100% flagged.)"""
    if unsegmented:
        return dict.fromkeys(_METRICS, None)

    def _ratio(num: float, den: float | None) -> float | None:
        if den is None or den <= 0:
            return None
        return round(num / den, 5)

    return {
        "mention_density": _ratio(total_mentions, word_count),      # mentions per word (furniture ↑)
        "type_token": _ratio(distinct_keywords, total_mentions),    # distinct/total (repetition ↓)
        "vocab_sparsity": _ratio(distinct_keywords, word_count),    # distinct per word
        "single_kw_dominance": _ratio(max_single_kw, total_mentions),  # one keyword's share (↑)
    }


def audited_source_ids(sources: dict[int, Source]) -> tuple[set[int], dict[str, int]]:
    """Split sources into the ones a keyword-ratio audit can meaningfully judge, and the ones
    it cannot. Returns ``(audited_ids, excluded_counts_by_class)``.

    F4, 2026-08-03. The 100%-outlier-rate cohort in both field exports was led by the app's
    OWN synthetic sources: 194 articles from ``hazard.usgs.local`` (a hazard "article" is
    "M 5.0 - Kermadec Islands region" -- word_count None, language unknown), plus the
    ``law.*.local`` documents. Nothing here is a scrape at all, so "does this source's
    extraction look valid?" is not a question the ratios can answer about them.

    The cost was never a wrong verdict -- those sources carry ZERO pathological articles, so
    nothing would have auto-demoted them, and this fix does not change any status. The cost is
    that 194 non-prose records sat inside the ``unknown`` language cohort (n=3,698) shaping
    everyone ELSE's p10/p90 baseline, and that the report described them as pathological-looking
    sources.

    The exemption is BY PROVENANCE CLASS -- an asserted fact about the ingest channel -- never
    by "looks unusual". A legitimately terse real news source stays fully audited, which is the
    property that keeps this from becoming a way to excuse bad scrapes.
    """
    audited: set[int] = set()
    excluded: dict[str, int] = {}
    for sid, src in sources.items():
        cls = provenance_of(src.domain if src else None, src.source_type if src else None)
        if cls in _AUDIT_EXEMPT_CLASSES:
            excluded[cls] = excluded.get(cls, 0) + 1
        else:
            audited.add(int(sid))
    return audited, excluded


def collect_article_stats(
    session: Session, *, audited_ids: set[int] | None = None,
) -> list[ArticleStat]:
    """Whole-corpus, COUNT-ONLY. One pass over the small article columns (word_count, language,
    source_id — the article_length_report pattern; the codec decrypts each page once, the
    documented diagnostic cost) joined in Python with per-article keyword aggregates from the
    mention tables (SUM(count), COUNT distinct keywords, MAX(count)) — Article.content is NEVER
    read here.

    QUARANTINED ARTICLES ARE EXCLUDED (F4, 2026-08-03). The article gate and the source gate
    were two independent passes over the same articles, and this one applied no quarantine
    filter at all -- so an article the article gate had already condemned as a non-article
    still counted toward its SOURCE's verdict, and toward the cohort baseline every other
    source is judged against. ``_query_articles`` has always applied this filter; the auditor
    simply never did.

    ``audited_ids``, when given, restricts the pass to sources a ratio audit can judge (see
    ``audited_source_ids``). ``None`` keeps every source, so a caller that has not resolved
    provenance still gets the old behaviour rather than an empty report.
    """
    # per-article keyword aggregates (one indexed group-by over keyword_mentions; no content).
    agg: dict[int, tuple[int, int, int]] = {}
    for aid, total, distinct, mx in (
        session.query(
            KeywordMention.article_id,
            func.coalesce(func.sum(KeywordMention.count), 0),
            func.count(),
            func.coalesce(func.max(KeywordMention.count), 0),
        ).group_by(KeywordMention.article_id)
    ):
        agg[int(aid)] = (int(total or 0), int(distinct or 0), int(mx or 0))

    stats: list[ArticleStat] = []
    for aid, wc, lang, sid in session.query(
        Article.id, Article.word_count, Article.language, Article.source_id
    ).filter(Article.quarantined.isnot(True)):
        if audited_ids is not None and (sid is None or int(sid) not in audited_ids):
            continue
        total, distinct, mx = agg.get(int(aid), (0, 0, 0))
        base = _base_lang(lang)
        unseg = base in UNSEGMENTED
        stats.append(
            ArticleStat(
                article_id=int(aid),
                source_id=int(sid) if sid is not None else None,
                language=base,
                word_count=int(wc) if wc is not None else None,
                total_mentions=total,
                distinct_keywords=distinct,
                max_single_kw=mx,
                unsegmented=unseg,
                metrics=compute_metrics(
                    word_count=int(wc) if wc is not None else None,
                    total_mentions=total, distinct_keywords=distinct, max_single_kw=mx,
                    unsegmented=unseg,
                ),
            )
        )
    return stats


def robust_stats(values: Sequence[float | None]) -> dict:
    """Median + MAD + p10/p50/p90/p99 + n over the non-None values. Robust (heavy-tailed
    distributions) — never mean/σ. Empty -> honest zeros with n=0."""
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return {"n": 0, "median": None, "mad": None, "p10": None, "p50": None, "p90": None, "p99": None}

    def _pct(p: float) -> float:
        k = max(0, min(n - 1, int(round((p / 100.0) * (n - 1)))))
        return round(vals[k], 5)

    median = _pct(50)
    devs = sorted(abs(v - median) for v in vals)
    mad = round(devs[len(devs) // 2] if len(devs) % 2 else (devs[len(devs) // 2 - 1] + devs[len(devs) // 2]) / 2.0, 5)
    return {"n": n, "median": median, "mad": mad, "p10": _pct(10), "p50": median, "p90": _pct(90), "p99": _pct(99)}


def pathology_rate_by_source(
    outliers: Sequence[dict], source_to_articles: dict[int, list[int]],
) -> dict[int, float]:
    """Per source, the fraction of its articles carrying the furniture-repetition conjunction.

    The export emitted only the per-ARTICLE boolean, so the quantity the admission gate
    actually decides on could not be read off the report at all -- you could see that 24
    articles were pathological without being able to see whether any SOURCE was anywhere
    near the floor that would disqualify it. This is that distribution.

    A source with no pathological article is included at 0.0 on purpose: the shape of the
    distribution is the finding, and dropping the zeros would make a corpus where nothing
    is wrong look identical to one that was never measured.
    """
    counts: dict[int, int] = {}
    for rec in outliers:
        if rec["pathology_furniture_repetition"] and rec["source_id"] is not None:
            sid = int(rec["source_id"])
            counts[sid] = counts.get(sid, 0) + 1
    return {
        sid: round(counts.get(sid, 0) / len(ids), 6)
        for sid, ids in source_to_articles.items() if ids
    }


def build_observed(
    *, cross_df: dict[str, int], furniture_ubiquity_cut: int, outliers: Sequence[dict],
    source_to_articles: dict[int, list[int]],
) -> dict:
    """The range each threshold was meant to cut, printed beside the threshold.

    Pure and injected-input only, so it is testable without a corpus. Every entry answers
    one question a reader of the old report could not answer: is this threshold reachable
    by anything in this corpus at all?
    """
    df_values = sorted(cross_df.values())
    df_stats = robust_stats([float(v) for v in df_values])
    df_max = float(df_values[-1]) if df_values else 0.0

    rates = pathology_rate_by_source(outliers, source_to_articles)
    rate_values = sorted(rates.values())
    rate_stats = robust_stats(rate_values)
    rate_max = rate_values[-1] if rate_values else 0.0
    worst = sorted(rates.items(), key=lambda kv: (-kv[1], kv[0]))[:10]

    return {
        "cross_source_df": {
            "max": df_max, "p90": df_stats["p90"], "p99": df_stats["p99"],
            "n_terms": df_stats["n"],
            "threshold": furniture_ubiquity_cut,
            "reachable": bool(df_values) and df_max >= furniture_ubiquity_cut,
            "source_flag": "retired",
            "note": (
                "the DF-ubiquity SOURCE FLAG is RETIRED (2026-08-03): it cannot discriminate at "
                "this corpus shape. The cut sat above every observation in both field exports, "
                "and lowering it does not find more broken sources -- at a cut of 20-25 the "
                "'furniture' set becomes world/data/public/state/government/media, i.e. ordinary "
                "journalism, because DF-ubiquity cannot separate publishing furniture from "
                "generic content words. The DF numbers below are still real evidence an analyst "
                "can read; what is withdrawn is the verdict drawn from them. `reachable` says "
                "whether the cut was inside the observed range at all."
            ),
        },
        "pathology_rate_per_source": {
            "max": rate_max, "p90": rate_stats["p90"], "p99": rate_stats["p99"],
            "n_sources": rate_stats["n"],
            "worst_sources": [{"source_id": sid, "pathology_rate": v} for sid, v in worst if v > 0],
            "note": (
                "the per-source fraction of articles with the furniture-repetition conjunction. "
                "This is the ONLY quantity that can disqualify a source, so its observed range "
                "against the audit's absolute floor is what says whether the admission gate can "
                "act on this corpus at all. Zeros are included -- an all-zero distribution is a "
                "finding, not an absence of data."
            ),
        },
    }


def build_baselines(stats: list[ArticleStat], *, floor: int = COHORT_FLOOR) -> dict:
    """Robust baselines per LANGUAGE cohort (the primary cohort — word_count's meaning and the
    keyword-stat shape vary by script/language). The finer ``[, source_type]`` cohort is optional
    and not split here (the corpus thins out fast); source_type rides per_source_summary instead.
    Each metric's baseline is over the cohort's non-None values; a cohort with n < floor is marked
    ``insufficient`` (no baseline, said honestly). Returns ``{language: {metric: robust_stats}}``."""
    by_cohort: dict[str, dict[str, list[float]]] = {}
    for s in stats:
        key = s.language
        c = by_cohort.setdefault(key, {m: [] for m in _METRICS})
        for m in _METRICS:
            v = s.metrics.get(m)
            if v is not None:
                c[m].append(v)
    out: dict[str, dict] = {}
    for key, metrics in by_cohort.items():
        cohort: dict[str, Any] = {"cohort": key}
        for m in _METRICS:
            rs = robust_stats(metrics[m])
            rs["insufficient"] = rs["n"] < floor
            cohort[m] = rs
        out[key] = cohort
    return out


def flag_outliers(
    stats: list[ArticleStat], baselines: dict, *, floor: int = COHORT_FLOOR,
) -> list[dict]:
    """One record per REALLY-flagged article: the dimension(s) whose value sits in its cohort's
    tail, each with value + baseline (median/p10/p90/p99/mad) + n + direction. An article is
    emitted ONLY when it has a real flagged dimension — an article whose metrics are all
    not-applicable (an unsegmented-language article, all four None) produces NO record, so it is
    never counted as "flagged" (the v1 defect: N/A-only records were counted as flags, inflating
    every unsegmented cohort to 100%). The not-applicable status is reported at the LANGUAGE level
    (per_language_health), not per article. The "Share Now ×30" pathology (high mention_density +
    low type_token + high single_kw_dominance) is labelled when all three fire together. No score."""
    records: list[dict] = []
    for s in stats:
        base = baselines.get(s.language)
        if base is None:
            continue
        flagged: list[dict] = []
        dirs: dict[str, str] = {}
        for m in _METRICS:
            v = s.metrics.get(m)
            if v is None:  # not assessable (0-denominator, or an unsegmented language -> all None)
                continue
            bl = base[m]
            if bl["insufficient"] or bl["p90"] is None:
                continue
            # STRICT tail: a value AT the common percentile is not an outlier — so a zero-spread
            # cohort (p90==p10) flags NOTHING, while a genuine value beyond the bulk still flags.
            direction = None
            if v > bl["p90"]:
                direction = "high"
            elif v < bl["p10"]:
                direction = "low"
            if direction:
                dirs[m] = direction
                flagged.append({
                    "dimension": m, "value": v, "direction": direction,
                    "baseline": {"median": bl["median"], "p10": bl["p10"], "p90": bl["p90"],
                                 "p99": bl["p99"], "mad": bl["mad"], "n": bl["n"]},
                })
        if not flagged:
            continue
        pathology = (
            dirs.get("mention_density") == "high"
            and dirs.get("type_token") == "low"
            and dirs.get("single_kw_dominance") == "high"
        )
        records.append({
            "article_id": s.article_id, "source_id": s.source_id, "language": s.language,
            "unsegmented": s.unsegmented, "flagged_dimensions": flagged,
            "pathology_furniture_repetition": bool(pathology),
        })
    return records


# --------------------------------------------------------------------------- #
# Layer B — the text sample from three INDEPENDENT, labelled selectors
# --------------------------------------------------------------------------- #

def select_random_per_source(
    source_to_articles: dict[int, list[int]], *, seed: int = DEFAULT_SEED,
) -> tuple[dict[int, int], int]:
    """ONE FIXED-SEED random article per source — the unbiased CONTROL (NOT median: median avoids
    the weird ones, which is the opposite of what we want). Skips 0-article sources and counts
    them. Deterministic: sources and their ids are sorted, and one seeded RNG drives all picks."""
    rng = random.Random(seed)
    picked: dict[int, int] = {}
    skipped = 0
    for sid in sorted(source_to_articles):
        ids = sorted(source_to_articles[sid])
        if not ids:
            skipped += 1
            continue
        picked[sid] = rng.choice(ids)
    return picked, skipped


def select_keyword_outliers(
    outlier_records: list[dict], *, cap: int = OUTLIER_CAP_PER_DIM_PER_SOURCE,
) -> set[int]:
    """The Layer-A flagged articles, capped at ``cap`` per flagged dimension per source (by how far
    into the tail the value sits) so one noisy source can't flood the zip."""
    buckets: dict[tuple[int | None, str], list[tuple[float, int]]] = {}
    for rec in outlier_records:
        for f in rec["flagged_dimensions"]:
            key = (rec["source_id"], f["dimension"])
            # distance from median (robust), guarding a zero/None mad.
            mad = f["baseline"]["mad"] or 0.0
            med = f["baseline"]["median"] or 0.0
            dist = abs(f["value"] - med) / mad if mad > 0 else abs(f["value"] - med)
            buckets.setdefault(key, []).append((dist, rec["article_id"]))
    chosen: set[int] = set()
    for items in buckets.values():
        for _dist, aid in sorted(items, key=lambda x: (-x[0], x[1]))[:cap]:
            chosen.add(aid)
    return chosen


def select_source_fingerprint(
    flagged_source_ids: set[int], source_to_articles: dict[int, list[int]], *,
    cap: int = FINGERPRINT_CAP_PER_SOURCE, seed: int = DEFAULT_SEED,
) -> set[int]:
    """Articles from Layer-C-flagged sources (``cap`` per source, fixed-seed sample for
    reproducibility) — so the analyst sees the text behind a source flagged as furniture-heavy."""
    rng = random.Random(seed + 1)
    chosen: set[int] = set()
    for sid in sorted(flagged_source_ids):
        ids = sorted(source_to_articles.get(sid, []))
        if not ids:
            continue
        rng.shuffle(ids)
        chosen.update(ids[:cap])
    return chosen


def select_cheap_signals(
    session: Session, audited_ids: set[int], *, cap_per_source: int = CHEAP_SIGNAL_CAP_PER_SOURCE,
) -> set[int]:
    """Articles picked by the METADATA-ONLY signals, promoted to a first-class selector.

    F3, 2026-08-03. Measured against the unbiased ``random_per_source`` control that ships in
    the same export:

        keyword_outlier     3,276 sampled   562 with a pre-label   17.2%
        random_per_source     457 sampled    48 with a pre-label   10.5%

    1.64x enrichment for 90% of the human review budget. And the pre-labels doing the
    discriminating -- ``high_link_density`` (415 of 675 label hits) and ``very_short`` (138) --
    are computed from ``external_link_count / word_count`` and ``word_count`` ALONE: no content
    decrypt, no keyword join. They are nearly free and they out-perform the machinery that costs
    the most.

    So this selects on them DIRECTLY rather than hoping the expensive selector happens to
    surface them. It ADDS a selector; ``keyword_outlier`` is kept (it is the sampling frame for
    the ratios and it does beat chance).

    Thresholds mirror ``_pre_label`` exactly so the selector and the label can never disagree.
    Capped per source so one link-heavy source cannot flood the sample.
    """
    counts: dict[int, int] = {}
    for aid, cnt in (
        session.query(ArticleLink.article_id, func.count())
        .filter(ArticleLink.link_type == "external")
        .group_by(ArticleLink.article_id)
    ):
        counts[int(aid)] = int(cnt)

    per_source: dict[int, list[int]] = {}
    for aid, wc, sid, quarantined in session.query(
        Article.id, Article.word_count, Article.source_id, Article.quarantined
    ).filter(Article.quarantined.isnot(True)):
        if quarantined or sid is None or int(sid) not in audited_ids:
            continue
        wc_i = int(wc) if wc is not None else None
        links = counts.get(int(aid), 0)
        short = wc_i is not None and wc_i < _VERY_SHORT_WORDS
        dense = wc_i is not None and wc_i > 0 and (links / wc_i) >= _HIGH_LINK_DENSITY
        if short or dense:
            per_source.setdefault(int(sid), []).append(int(aid))

    chosen: set[int] = set()
    for sid in sorted(per_source):
        chosen.update(sorted(per_source[sid])[:cap_per_source])
    return chosen


def selector_enrichment(
    sample_records: Sequence[dict], control: str = "random_per_source",
) -> dict[str, dict]:
    """Each selector's own hit-rate against the unbiased control, computed from the export
    the selectors produced.

    The point is that the next export MEASURES its selectors instead of assuming them: a
    selector that costs most of the review budget and barely beats chance should have to say so
    in the artifact that ships it. "Hit" = the article carried at least one heuristic pre-label,
    which is a cheap proxy for "worth a human's attention", never a verdict.

    A selector with no sampled articles reports ``rate: None`` and ``enrichment: None`` -- an
    unmeasured selector must not read as one that scored zero, and dividing by a control that
    sampled nothing would fabricate a ratio.
    """
    per: dict[str, dict] = {}
    for rec in sample_records:
        hit = bool(rec.get("pre_label"))
        for method in rec.get("selection_method", []):
            d = per.setdefault(method, {"n": 0, "with_pre_label": 0})
            d["n"] += 1
            d["with_pre_label"] += int(hit)
    for d in per.values():
        d["rate"] = round(d["with_pre_label"] / d["n"], 4) if d["n"] else None
    base = per.get(control, {}).get("rate")
    for name, d in per.items():
        d["enrichment_over_control"] = (
            None if (name == control or not base or d["rate"] is None)
            else round(d["rate"] / base, 3)
        )
    return per


def build_sample_union(
    random_pick: dict[int, int], outlier_ids: set[int], fingerprint_ids: set[int],
    cheap_ids: set[int] | None = None,
) -> dict[int, list[str]]:
    """Union of the selectors → ``{article_id: [selection_method, ...]}`` (an article can be
    picked by more than one selector — the whole point of independent selectors)."""
    methods: dict[int, list[str]] = {}
    for aid in random_pick.values():
        methods.setdefault(aid, []).append("random_per_source")
    for aid in outlier_ids:
        methods.setdefault(aid, []).append("keyword_outlier")
    for aid in fingerprint_ids:
        methods.setdefault(aid, []).append("source_fingerprint")
    for aid in sorted(cheap_ids or ()):
        methods.setdefault(aid, []).append("cheap_signal")
    return methods


def _pre_label(text_head: str | None, *, word_count: int | None, external_links: int) -> list[str]:
    """A cheap heuristic pre-label (hints, never verdicts): boilerplate phrase hits, a high
    outbound-link density, and a very-short body. Works on metadata alone when the text is gated."""
    labels: list[str] = []
    if text_head:
        low = text_head.lower()
        hits = [p for p in _BOILERPLATE_PHRASES if p in low]
        if hits:
            labels.append("boilerplate_phrase:" + "|".join(sorted(set(hits))[:5]))
    if (word_count is not None and word_count > 0
            and (external_links / word_count) >= _HIGH_LINK_DENSITY):
        labels.append(f"high_link_density:{round(external_links / word_count, 3)}")
    if word_count is not None and word_count < _VERY_SHORT_WORDS:
        labels.append(f"very_short:{word_count}")
    return labels


def build_sample_records(
    session: Session, sample_methods: dict[int, list[str]], newsletter_source_ids: set[int], *,
    include_newsletter_text: bool, max_chars: int = TEXT_HEAD_CHARS,
) -> list[dict]:
    """Per sampled article: metadata + external_link_count + heuristic pre-label + a bounded
    text_head. NEWSLETTER GUARDRAIL: for a private .eml/mailbox source the body is gated behind
    ``include_newsletter_text`` (default off → counts+metadata only, no body leaves); web + wiki
    export normally. Article.content is decrypted ONLY here, only for these ≤N sampled ids."""
    if not sample_methods:
        return []
    ids = sorted(sample_methods)
    # external outbound-link counts (count-only, no content) for the sample. Chunk the IN(...) so a
    # very large sample can never exceed SQLite's variable limit.
    link_counts: dict[int, int] = {}
    for chunk in _chunks(ids):
        for aid, cnt in (
            session.query(ArticleLink.article_id, func.count())
            .filter(ArticleLink.article_id.in_(chunk), ArticleLink.link_type == "external")
            .group_by(ArticleLink.article_id)
        ):
            link_counts[int(aid)] = int(cnt)

    records: list[dict] = []
    arts: list[Article] = []
    for chunk in _chunks(ids):
        arts.extend(session.query(Article).filter(Article.id.in_(chunk)).order_by(Article.id))
    for art in arts:
        is_newsletter = art.source_id in newsletter_source_ids
        gated = is_newsletter and not include_newsletter_text
        text_head = None if gated else (art.get_content() or "")[:max_chars]
        ext_links = link_counts.get(int(art.id), 0)
        records.append({
            "article_id": int(art.id),
            "source_id": int(art.source_id) if art.source_id is not None else None,
            "url": art.url,
            "title": art.title,
            "word_count": int(art.word_count) if art.word_count is not None else None,
            "language": _base_lang(art.language),
            "external_link_count": ext_links,
            "selection_method": sorted(sample_methods[int(art.id)]),
            "is_newsletter": is_newsletter,
            "text_head_gated": gated,
            "pre_label": _pre_label(text_head, word_count=art.word_count, external_links=ext_links),
            "text_head": text_head,
        })
    return records


# --------------------------------------------------------------------------- #
# Layer C — per-source keyword analytics (the per-source verdict view)
# --------------------------------------------------------------------------- #

def compute_cross_source_df(per_source_top: dict[int, list[str]]) -> dict[str, int]:
    """Cross-source document frequency of each top keyword = in how many DISTINCT sources it is a
    top keyword. This is the ``generic_terms`` DF-ubiquity method applied at SOURCE granularity: a
    topical keyword tops a FEW related sources (low DF), furniture ("share now"/"read more") tops
    MANY unrelated sources (high DF) — no hand-denylist, self-normalising."""
    df: dict[str, int] = {}
    for terms in per_source_top.values():
        for term in set(terms):
            df[term] = df.get(term, 0) + 1
    return df


def flag_furniture_sources(
    per_source_top: dict[int, list[str]], cross_source_df: dict[str, int], n_sources: int, *,
    ubiquity_frac: float = FURNITURE_UBIQUITY_FRAC, min_sources: int = FURNITURE_MIN_SOURCES,
    share_threshold: float = FURNITURE_SHARE_THRESHOLD,
) -> tuple[set[int], dict[int, float]]:
    """The cross-source DF-ubiquity share per source. THE SOURCE FLAG IS RETIRED (F2, 2026-08-03)
    — the share is still computed and reported as descriptive evidence, but it no longer flags.

    WHY, and why lowering the cut was the wrong fix. The detector never fired: the cut is
    ``max(min_sources, ubiquity_frac·n_sources)`` = 137 / 142 on the two field corpora, against a
    maximum observed ``cross_source_df`` of 71 / 80 over ~5,500 fingerprint entries. So
    ``furniture_flagged_sources`` was 0 in both runs and this selector had never once selected.

    The tempting fix is to lower the cut. Here is the actual top of the DF distribution::

        71 world   64 data   54 public   48 state   44 government   39 media
        38 company 31 president 31 research 30 down  28 trump      26 global

    At a cut of 20–25 the "furniture" set becomes *world, data, public, state, government, media,
    company, president, research* — ordinary journalism. That is the recorded open-class lesson
    (2026-07-01 #530): DF-ubiquity cannot separate publishing furniture from generic content
    words, because BOTH are ubiquitous. A lower cut would not find more broken sources, it would
    manufacture a furniture verdict over normal reporting.

    The obvious alternative — require corroboration from the closed-class publishing-boilerplate
    channel — was MEASURED before being rejected, and it fails harder than expected: every term in
    ``PLATFORM_STOPWORDS`` and ``PUBLISHING_BOILERPLATE_SCOPED`` is ALREADY a stopword, so none of
    them can ever be extracted as a keyword, so none can ever appear in a source's top-12
    fingerprint. That variant would flag nothing BY CONSTRUCTION rather than merely in practice —
    an inert mechanism that still looks like a working detector, which is worse than no detector.

    So the honest reading is that this signal cannot discriminate at this corpus shape, and the
    report says so (``observed.cross_source_df.reachable``) instead of publishing a zero that
    reads like a clean bill of health. The DF numbers stay in the export because they are real and
    an analyst can use them; what is withdrawn is the verdict drawn from them.

    Returns ``(flagged_source_ids, furniture_share_per_source)`` — the first is always empty.
    """
    ubiquity_cut = max(min_sources, int(round(ubiquity_frac * n_sources)))
    furniture_terms = {t for t, dfc in cross_source_df.items() if dfc >= ubiquity_cut}
    shares: dict[int, float] = {}
    for sid, terms in per_source_top.items():
        if not terms:
            shares[sid] = 0.0
            continue
        shares[sid] = round(sum(1 for t in terms if t in furniture_terms) / len(terms), 4)
    return set(), shares


def source_metric_distributions(stats_by_source: dict[int, list[ArticleStat]]) -> dict[int, dict]:
    """Per source: the median + spread (robust_stats) of each of the 4 Layer-A ratios over the
    source's articles. Count-only; no score."""
    out: dict[int, dict] = {}
    for sid, arts in stats_by_source.items():
        out[sid] = {m: robust_stats([a.metrics.get(m) for a in arts]) for m in _METRICS}
    return out


# --------------------------------------------------------------------------- #
# The ZIP assembler (the single deliverable)
# --------------------------------------------------------------------------- #

def _jsonl(rows: list[dict]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else "")).encode("utf-8")


def _json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def _readme() -> bytes:
    return (
        "# Source & article quality — analyst bundle (TEMPORARY diagnostic)\n\n"
        "Read-only, EXPORT-ONLY, no-score. Every flag is a DEDUCED candidate with its raw value + "
        "the cohort baseline + n — never a verdict. Coverage: whole-corpus COUNT-ONLY; text heads "
        "only for the sampled subset.\n\n"
        "## Files\n"
        "- `manifest.json` — generated_at, corpus totals, sources sampled vs skipped, config flags, "
        "method per metric, provenance (deduced · not a verdict), and `observed`.\n\n"
        "### Read `pathological_articles`, not `outlier_sampling_frame`\n"
        "`pathological_articles` is the finding: the CONJUNCTION (high mention_density AND low "
        "type_token AND high single_kw_dominance) — the nav-DOM 'Share Now ×30' signature, and the "
        "only article-level quantity that feeds an extraction-failure verdict.\n\n"
        "`outlier_sampling_frame` counts articles in the tail of at least ONE of the 4 ratios at "
        "p10/p90. That is ~10% of the corpus per tail BY THE DEFINITION OF A PERCENTILE, so it lands "
        "near the same fraction in every language regardless of quality — it cannot vary with the "
        "data, and it is not a measurement of anything. It is the FRAME the review sample is drawn "
        "from, which is a real and useful job. It was called `flagged_articles` until 2026-08-03, "
        "which read as a finding.\n\n"
        "`observed` prints the range each threshold was meant to cut, beside the threshold: if "
        "`cross_source_df.reachable` is false, no term in this corpus can be classified furniture, "
        "so a zero furniture count means the detector never ran rather than that nothing is wrong. "
        "`pathology_rate_per_source` is the distribution the admission gate actually decides on.\n"
        "- `per_language_health.json` — per language: n, the 4 metric distributions, % flagged, and "
        "whether the language was `assessed`. UNSEGMENTED languages (zh/ja/th) are NOT ASSESSED "
        "(`pct_flagged: null`) — all four keyword-stat metrics are unreliable without a segmenter, "
        "so no article there is flagged (never read that as 'clean'). Doubles as keyword-engine QA "
        "(which languages have broken stats / stoplist gaps).\n"
        "- `per_source_keywords.jsonl` — READ THIS FIRST. Per source: top-12 keywords (the "
        "fingerprint — 'share now / read more / subscribe / cookies' = broken; 'election / "
        "inflation / court' = healthy), source-level stat distributions, furniture share, flagged?\n"
        "- `per_source_summary.jsonl` — per source: article count, outlier rate + dominant outlier "
        "kind, source_type/country/language, the sampled article refs + which selectors fired.\n"
        "- `keyword_outliers.jsonl` — one record per Layer-A flagged article: ids, source, language, "
        "flagged dimension(s) with value + baseline + n.\n"
        "- `sample_articles.jsonl` — the Layer-B UNION: metadata + heuristic pre-label + text_head "
        "(newsletter bodies gated) + selection_method LIST.\n\n"
        "## The selectors (their blind spots don't overlap)\n"
        "1. `random_per_source` — one fixed-seed random article per source = the unbiased CONTROL.\n"
        "2. `keyword_outlier` — the Layer-A stat outliers (finds only what its stats measure).\n"
        "3. `cheap_signal` — high outbound-link density or a very short body. METADATA ONLY: no "
        "content decrypt, no keyword join. On the 2026-08-03 field corpus these signals carried "
        "most of the discriminating power (`high_link_density` 415 of 675 label hits) while the "
        "expensive selector returned 17.2% against the control's 10.5%.\n"
        "4. `source_fingerprint` — RETIRED (see `observed.cross_source_df.source_flag`). It "
        "selected nothing in either field run because the DF cut sat above every observation, and "
        "lowering it would classify `government`/`world`/`data` as furniture. Left in the "
        "vocabulary so its n=0 stays visible in `selector_enrichment` rather than disappearing.\n\n"
        "`selector_enrichment` reports each selector's hit-rate against the control, so a "
        "selector that costs the review budget and barely beats chance has to say so here.\n\n"
        "## The analysis this enables\n"
        "- **Base rate**: read the `random_per_source` articles — what fraction are non-articles? "
        "That is the corpus's true bad-item rate (unbiased).\n"
        "- **Detector precision**: of the `keyword_outlier` articles, what fraction are truly bad? "
        "(false positives = real articles the detector wrongly flagged).\n"
        "- **The RECALL GAP (the new signal)**: bad articles in the RANDOM set that were NOT flagged "
        "as outliers = the detector's blind spot = a new signal to add. This is the whole point of "
        "the random control.\n\n"
        "The 4 metrics (count-only, per article): mention_density = total_keyword_mentions / "
        "word_count; type_token = distinct_keywords / total_mentions; vocab_sparsity = "
        "distinct_keywords / word_count; single_kw_dominance = max_single_keyword_mentions / "
        "total_mentions. The 'Share Now ×30' pathology = HIGH mention_density + LOW type_token + "
        "HIGH single_kw_dominance together. For unsegmented languages (zh/ja/th) ALL FOUR metrics "
        "are not-applicable (word_count is meaningless AND keyword extraction is degenerate without "
        "a segmenter), so those articles are never flagged — the LANGUAGE is marked not-assessed.\n"
    ).encode()


def build_quality_report_files(
    session: Session, *, generated_at: str, seed: int = DEFAULT_SEED,
    include_newsletter_text: bool = False, floor: int = COHORT_FLOOR,
) -> dict[str, bytes]:
    """Assemble the whole bundle → ``{filename: bytes}``. Pure of wall-clock (``generated_at`` is
    injected). Read-only, count-only over the corpus, content decrypted only for the sample."""
    # source metadata (count-only) + newsletter ids
    sources = {int(s.id): s for s in session.query(Source)}
    newsletter_ids = {
        int(sid) for (sid,) in session.query(Source.id).filter(
            Source.domain.in_(NEWSLETTER_SOURCE_DOMAINS)
        )
    }
    # F4 (2026-08-03): the audit's scope, resolved once and applied to EVERY collector below,
    # so the exemption and the quarantine filter cannot drift between layers.
    audited_ids, excluded_by_class = audited_source_ids(sources)

    # article ids per source (count-only group-by, no content). Quarantined articles are
    # excluded for the same reason as in collect_article_stats: an article the article gate
    # condemned must not count toward its source's verdict, nor seed the review sample.
    #
    # Exempt-class sources STAY in this map on purpose. The exemption is from the RATIO
    # COHORTS -- the thing that was measurably distorted -- not from the bundle: the review
    # sample is how an analyst sees what each channel actually looks like, and the random
    # control is only a control if it can reach everything. What changes is that these
    # sources are no longer JUDGED by ratios built for journalism.
    source_to_articles: dict[int, list[int]] = {}
    quarantined_excluded = 0
    for aid, sid, quarantined in session.query(
        Article.id, Article.source_id, Article.quarantined
    ):
        if quarantined:
            quarantined_excluded += 1
            continue
        if sid is not None:
            source_to_articles.setdefault(int(sid), []).append(int(aid))
    audited_to_articles = {
        sid: ids for sid, ids in source_to_articles.items() if sid in audited_ids
    }

    # Layer A — the ratio cohorts, over audited sources only.
    stats = collect_article_stats(session, audited_ids=audited_ids)
    baselines = build_baselines(stats, floor=floor)
    outliers = flag_outliers(stats, baselines, floor=floor)
    stats_by_source: dict[int, list[ArticleStat]] = {}
    for s in stats:
        if s.source_id is not None:
            stats_by_source.setdefault(s.source_id, []).append(s)

    # Layer C — per-source top-12 fingerprints (corpus_keywords, count-only), furniture detection.
    # The IN(...) is bounded by a seeded per-source sample (a top-12 furniture fingerprint is stable
    # over FINGERPRINT_SAMPLE_CAP articles) so a source with tens of thousands of articles can't blow
    # SQLite's variable limit; whether a source was sampled is disclosed per source.
    per_source_top: dict[int, list[str]] = {}
    per_source_top_full: dict[int, list[dict]] = {}
    fingerprint_sampled: dict[int, bool] = {}
    # Audited sources only: a hazard feed's top keywords are legitimately "earthquake,
    # magnitude, region" every time, so letting it into the cross-source DF would teach the
    # furniture detector that real vocabulary is furniture.
    for sid, ids in audited_to_articles.items():
        if len(ids) > FINGERPRINT_SAMPLE_CAP:
            fp_ids = sorted(random.Random(seed + sid).sample(ids, FINGERPRINT_SAMPLE_CAP))
            fingerprint_sampled[sid] = True
        else:
            fp_ids = ids
            fingerprint_sampled[sid] = False
        ck = q.corpus_keywords(session, article_ids=fp_ids, limit=TOP_KEYWORDS)
        terms = ck.get("terms", [])
        per_source_top[sid] = [t["normalized"] for t in terms]
        per_source_top_full[sid] = terms
    cross_df = compute_cross_source_df(per_source_top)
    furniture_ubiquity_cut = max(
        FURNITURE_MIN_SOURCES, int(round(FURNITURE_UBIQUITY_FRAC * len(per_source_top)))
    )
    flagged_sources, furniture_shares = flag_furniture_sources(
        per_source_top, cross_df, n_sources=len(per_source_top)
    )
    src_metric_dists = source_metric_distributions(stats_by_source)

    # Layer B — the three selectors + the union + the text sample
    random_pick, skipped = select_random_per_source(source_to_articles, seed=seed)
    outlier_ids = select_keyword_outliers(outliers)
    # `flagged_sources` is now always empty (the DF source flag is retired, F2), so this
    # contributes nothing. It is kept rather than deleted so the retirement is visible in the
    # sample's own vocabulary: `source_fingerprint` appearing with n=0 in the enrichment table
    # is the honest record of a selector that never selected.
    fingerprint_ids = select_source_fingerprint(flagged_sources, source_to_articles, seed=seed)
    cheap_ids = select_cheap_signals(session, audited_ids)
    sample_methods = build_sample_union(random_pick, outlier_ids, fingerprint_ids, cheap_ids)
    sample_records = build_sample_records(
        session, sample_methods, newsletter_ids, include_newsletter_text=include_newsletter_text
    )

    # --- assemble the files ---
    outliers_by_source: dict[int | None, list[dict]] = {}
    for rec in outliers:
        outliers_by_source.setdefault(rec["source_id"], []).append(rec)

    n_pathological = sum(1 for r in outliers if r["pathology_furniture_repetition"])
    observed = build_observed(
        cross_df=cross_df,
        furniture_ubiquity_cut=furniture_ubiquity_cut,
        outliers=outliers,
        # The rate distribution is over AUDITED sources: an exempt source's 0.0 would pad the
        # distribution with sources that were never eligible to score anything else.
        source_to_articles=audited_to_articles,
    )

    per_source_keywords: list[dict] = []
    per_source_summary: list[dict] = []
    for sid, ids in sorted(source_to_articles.items()):
        src = sources.get(sid)
        src_outliers = outliers_by_source.get(sid, [])
        # dominant outlier kind = the most common flagged dimension for this source
        dim_counts: dict[str, int] = {}
        for r in src_outliers:
            for f in r["flagged_dimensions"]:
                dim_counts[f["dimension"]] = dim_counts.get(f["dimension"], 0) + 1
        dominant = max(dim_counts, key=lambda k: dim_counts[k]) if dim_counts else None
        per_source_keywords.append({
            "source_id": sid,
            "domain": src.domain if src else None,
            "source_type": src.source_type if src else None,
            "top_keywords": [
                {"term": t["term"], "normalized": t["normalized"], "articles": t["articles"],
                 "mentions": t["mentions"],
                 "cross_source_df": cross_df.get(t["normalized"], 0)}
                for t in per_source_top_full.get(sid, [])
            ],
            "metric_distributions": src_metric_dists.get(sid, {}),
            "furniture_share": furniture_shares.get(sid, 0.0),
            "flagged_furniture": sid in flagged_sources,
            "fingerprint_sampled": fingerprint_sampled.get(sid, False),
        })
        per_source_summary.append({
            "source_id": sid,
            "domain": src.domain if src else None,
            "source_type": src.source_type if src else None,
            "country": src.country if src else None,
            "language": src.language if src else None,
            "enabled": bool(src.enabled) if src and src.enabled is not None else None,
            "is_newsletter": sid in newsletter_ids,
            "article_count": len(ids),
            # F4: an exempt source is REPORTED but not ratio-judged, and says which it is.
            # A zero outlier_rate that means "not measured" must not read like a clean bill
            # of health -- that is the same missing-vs-zero confusion the exemption exists to
            # end, so the counts are null rather than 0 when nothing was assessed.
            "ratio_audited": sid in audited_ids,
            "provenance_class": provenance_of(
                src.domain if src else None, src.source_type if src else None
            ),
            "outlier_count": len(src_outliers) if sid in audited_ids else None,
            "outlier_rate": (
                round(len(src_outliers) / len(ids), 4) if (ids and sid in audited_ids) else None
            ),
            "dominant_outlier_kind": dominant,
            "sampled_articles": [
                {"article_id": r["article_id"], "selection_method": r["selection_method"]}
                for r in sample_records if r["source_id"] == sid
            ],
        })

    # per-language health (doubles as keyword-engine QA)
    flagged_ids = {r["article_id"] for r in outliers}
    lang_articles: dict[str, list[ArticleStat]] = {}
    for s in stats:
        lang_articles.setdefault(s.language, []).append(s)
    per_language_health: dict[str, dict] = {}
    for lang, arts in sorted(lang_articles.items()):
        n = len(arts)
        flagged_here = sum(1 for a in arts if a.article_id in flagged_ids)
        unseg = lang in UNSEGMENTED
        per_language_health[lang] = {
            "n": n,
            "unsegmented": unseg,
            "assessed": not unseg,
            # NOT-ASSESSED for an unsegmented language: pct_flagged is null (not 0% and not 100%) —
            # all four keyword-stat metrics are unreliable without a segmenter, so no article here
            # is flagged. This is honest "we can't measure it", never "it's clean" or "it's broken".
            "pct_flagged": None if unseg else (round(100.0 * flagged_here / n, 2) if n else 0.0),
            "metric_distributions": baselines.get(lang, {}),
            "note": ("NOT ASSESSED — all four keyword-stat metrics are unreliable for an "
                     "unsegmented language (word_count is meaningless AND keyword extraction is "
                     "degenerate without a segmenter). Flags are suppressed here; use a segmenter "
                     "to assess zh/ja/th." if unseg else None),
        }

    manifest = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "temporary": True,
        "provenance": "deduced · not a verdict · propose, never auto-apply · EXPORT-ONLY, no writes",
        "corpus_totals": {
            "sources": len(sources),
            "sources_with_articles": len(source_to_articles),
            "sources_sampled_random": len(random_pick),
            "sources_skipped_zero_articles": skipped,
            # `articles` stays the corpus total a reader expects; the ratio audit's own
            # denominator is reported beside it rather than substituted for it. Printing only
            # the audited count under the name "articles" would be the same missing-vs-zero
            # confusion the exemption exists to end -- the reader could not tell a smaller
            # corpus from a narrower audit.
            "articles": sum(len(ids) for ids in source_to_articles.values()),
            "articles_ratio_audited": len(stats),
            # THE FINDING. The conjunction (high mention_density AND low type_token AND high
            # single_kw_dominance) is the actual nav-DOM "Share Now x30" signature, and it is
            # the ONLY article-level quantity that feeds an extraction-failure verdict. On the
            # operator's 2026-08-03 corpus it was 24 of 34,263 -- and it was buried inside the
            # number below rather than reported.
            "pathological_articles": n_pathological,
            # RENAMED 2026-08-03 from `flagged_articles`, which read as a finding and is not one.
            # It counts articles in the tail of at least one of 4 ratios, at p10/p90 -- so ~10%
            # of the corpus per tail BY THE DEFINITION OF A PERCENTILE. Measured across both
            # field exports, all eight buckets landed within 2% of each other and the rate was
            # ~42% in EVERY language from n=270 to n=21,343. A real quality signal varies with
            # the data; this cannot, because it is a restatement of "10% of things are in the
            # top decile". The number is not wrong, it is EMPTY -- and it is genuinely useful
            # as what it actually is: the frame the review sample is drawn from.
            "outlier_sampling_frame": len(outliers),
            "furniture_flagged_sources": len(flagged_sources),
            "sampled_articles": len(sample_records),
        },
        # WHAT THIS AUDIT DELIBERATELY DID NOT JUDGE (F4, 2026-08-03). Counted rather than
        # silently dropped: an exemption nobody can see is indistinguishable from a gap.
        "excluded_from_audit": {
            "sources_by_provenance_class": excluded_by_class,
            "quarantined_articles": quarantined_excluded,
            "note": (
                "sources whose provenance class is not a scraped web article (hazard, law, "
                "wikipedia, newsletter, statistics) are exempt from the keyword-ratio cohorts: "
                "their ratios are legitimately unlike journalism, so measuring them against a "
                "news cohort describes the CHANNEL rather than the extraction, and it distorts "
                "the baseline every other source is judged against. Quarantined articles are "
                "excluded because the article gate already condemned them -- counting them "
                "toward their source's verdict would let one gate's finding bias the other's. "
                "Neither exclusion changes any source's status."
            ),
        },
        # WHAT THE DATA ACTUALLY RANGED OVER (2026-08-03). Every threshold in `config` was
        # printed without the distribution it was meant to cut, so a reader could not tell that
        # `furniture_ubiquity_cut: 137` sits above every observation in the corpus without
        # recomputing it from a 5,484-line file. A threshold no observation can reach should say
        # so in the artifact that reports it -- that is what turns the next export into a
        # measurement rather than a re-run.
        "observed": observed,
        # F3: each selector's own hit-rate against the unbiased control, so the next export
        # MEASURES its selectors instead of assuming them. `keyword_outlier` costs ~90% of the
        # review budget for 1.64x chance on the field corpus; `cheap_signal` selects on the
        # metadata that measurably out-performed it, at no decrypt cost.
        "selector_enrichment": selector_enrichment(sample_records),
        "config": {
            "seed": seed, "cohort_floor": floor, "tail_high_p": TAIL_HIGH_P, "tail_low_p": TAIL_LOW_P,
            "text_head_chars": TEXT_HEAD_CHARS, "top_keywords": TOP_KEYWORDS,
            "outlier_cap_per_dim_per_source": OUTLIER_CAP_PER_DIM_PER_SOURCE,
            "include_newsletter_text": include_newsletter_text,
            "furniture_ubiquity_frac": FURNITURE_UBIQUITY_FRAC,
            "furniture_min_sources": FURNITURE_MIN_SOURCES,
            "furniture_ubiquity_cut": furniture_ubiquity_cut,  # a term topping >= this many sources
            "furniture_share_threshold": FURNITURE_SHARE_THRESHOLD,
            "fingerprint_sample_cap": FINGERPRINT_SAMPLE_CAP,
        },
        "method": {
            "mention_density": "total_keyword_mentions / word_count (count-only)",
            "type_token": "distinct_keywords / total_mentions",
            "vocab_sparsity": "distinct_keywords / word_count",
            "single_kw_dominance": "max_single_keyword_mentions / total_mentions",
            "baselines": "robust median + MAD + p10/p50/p90/p99 per language cohort (n>=floor)",
            "furniture": "cross-source DF-ubiquity of top keywords (no hand-denylist)",
            "sample": "union of random_per_source (control) + keyword_outlier + source_fingerprint",
        },
    }

    return {
        "manifest.json": _json(manifest),
        "per_language_health.json": _json(per_language_health),
        "per_source_keywords.jsonl": _jsonl(per_source_keywords),
        "per_source_summary.jsonl": _jsonl(per_source_summary),
        "keyword_outliers.jsonl": _jsonl(outliers),
        "sample_articles.jsonl": _jsonl(sample_records),
        "README.md": _readme(),
    }
