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
from src.database.models import Article, ArticleLink, KeywordMention, Source
from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

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


def collect_article_stats(session: Session) -> list[ArticleStat]:
    """Whole-corpus, COUNT-ONLY. One pass over the small article columns (word_count, language,
    source_id — the article_length_report pattern; the codec decrypts each page once, the
    documented diagnostic cost) joined in Python with per-article keyword aggregates from the
    mention tables (SUM(count), COUNT distinct keywords, MAX(count)) — Article.content is NEVER
    read here."""
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
    ):
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


def build_sample_union(
    random_pick: dict[int, int], outlier_ids: set[int], fingerprint_ids: set[int],
) -> dict[int, list[str]]:
    """Union of the three selectors → ``{article_id: [selection_method, ...]}`` (an article can be
    picked by more than one selector — the whole point of independent selectors)."""
    methods: dict[int, list[str]] = {}
    for aid in random_pick.values():
        methods.setdefault(aid, []).append("random_per_source")
    for aid in outlier_ids:
        methods.setdefault(aid, []).append("keyword_outlier")
    for aid in fingerprint_ids:
        methods.setdefault(aid, []).append("source_fingerprint")
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
    if word_count is not None and word_count > 0 and (external_links / word_count) >= 0.05:
        labels.append(f"high_link_density:{round(external_links / word_count, 3)}")
    if word_count is not None and word_count < 40:
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
    """A keyword is FURNITURE (cross-source ubiquitous) when its DF ≥ max(min_sources,
    ubiquity_frac·n_sources). A source is flagged when the FURNITURE SHARE of its top keywords ≥
    share_threshold. Descriptive, propose-don't-auto-apply, no score. Returns (flagged_source_ids,
    furniture_share_per_source)."""
    ubiquity_cut = max(min_sources, int(round(ubiquity_frac * n_sources)))
    furniture_terms = {t for t, dfc in cross_source_df.items() if dfc >= ubiquity_cut}
    flagged: set[int] = set()
    shares: dict[int, float] = {}
    for sid, terms in per_source_top.items():
        if not terms:
            shares[sid] = 0.0
            continue
        share = sum(1 for t in terms if t in furniture_terms) / len(terms)
        shares[sid] = round(share, 4)
        if share >= share_threshold:
            flagged.add(sid)
    return flagged, shares


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
        "method per metric, provenance (deduced · not a verdict).\n"
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
        "## The three selectors (their blind spots don't overlap)\n"
        "1. `random_per_source` — one fixed-seed random article per source = the unbiased CONTROL.\n"
        "2. `keyword_outlier` — the Layer-A stat outliers (finds only what its stats measure).\n"
        "3. `source_fingerprint` — articles from Layer-C furniture-flagged sources.\n\n"
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
    # article ids per source (count-only group-by, no content)
    source_to_articles: dict[int, list[int]] = {}
    for aid, sid in session.query(Article.id, Article.source_id):
        if sid is not None:
            source_to_articles.setdefault(int(sid), []).append(int(aid))

    # Layer A
    stats = collect_article_stats(session)
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
    for sid, ids in source_to_articles.items():
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
    fingerprint_ids = select_source_fingerprint(flagged_sources, source_to_articles, seed=seed)
    sample_methods = build_sample_union(random_pick, outlier_ids, fingerprint_ids)
    sample_records = build_sample_records(
        session, sample_methods, newsletter_ids, include_newsletter_text=include_newsletter_text
    )

    # --- assemble the files ---
    outliers_by_source: dict[int | None, list[dict]] = {}
    for rec in outliers:
        outliers_by_source.setdefault(rec["source_id"], []).append(rec)

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
            "outlier_count": len(src_outliers),
            "outlier_rate": round(len(src_outliers) / len(ids), 4) if ids else 0.0,
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
            "articles": len(stats),
            "flagged_articles": len(outliers),
            "furniture_flagged_sources": len(flagged_sources),
            "sampled_articles": len(sample_records),
        },
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
