"""
Source & article quality diagnostic — pure cores + one DB integration (TEMPORARY diagnostic).

Honesty guards asserted: no composite score anywhere; the "Share Now" pathology is FLAGGED and a
normal article is NOT (the negative-space case); unsegmented-language density/sparsity is
not-applicable (the language is flagged, never its article); the random selector is fixed-seed
deterministic and skips 0-article sources; the outlier cap; source_fingerprint pulls a flagged
source's articles; the DF-ubiquity furniture detector; and the newsletter text-gate (default off →
no body leaves).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics import source_quality as sq
from src.analytics.source_quality import (
    ArticleStat,
    build_baselines,
    build_quality_report_files,
    build_sample_union,
    compute_cross_source_df,
    compute_metrics,
    flag_furniture_sources,
    flag_outliers,
    robust_stats,
    select_keyword_outliers,
    select_random_per_source,
    select_source_fingerprint,
)
from src.database.models import Article, ArticleLink, Base, Keyword, KeywordMention, Source

# --------------------------------------------------------------------------- #
# Layer A — metrics + robust baselines + flagging
# --------------------------------------------------------------------------- #

def test_metrics_and_unsegmented_not_applicable():
    normal = compute_metrics(word_count=500, total_mentions=80, distinct_keywords=50,
                             max_single_kw=5, unsegmented=False)
    assert normal["mention_density"] == 0.16 and normal["type_token"] == 0.625
    # unsegmented: the word_count metrics become None (not a fabricated 0); the others survive
    unseg = compute_metrics(word_count=500, total_mentions=80, distinct_keywords=50,
                            max_single_kw=5, unsegmented=True)
    assert unseg["mention_density"] is None and unseg["vocab_sparsity"] is None
    assert unseg["type_token"] == 0.625 and unseg["single_kw_dominance"] == 0.0625
    # zero denominators degrade to None, never a crash
    z = compute_metrics(word_count=0, total_mentions=0, distinct_keywords=0, max_single_kw=0, unsegmented=False)
    assert all(v is None for v in z.values())


def test_robust_stats_uses_median_and_mad_not_mean():
    rs = robust_stats([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100])  # heavy tail
    assert rs["median"] == 6  # the outlier 100 doesn't move the median (a mean would be ~14)
    assert rs["n"] == 11 and rs["p90"] == 10 and rs["p99"] == 100
    assert robust_stats([])["n"] == 0  # honest empty


def _stat(aid, sid, lang, metrics, unseg=False):
    return ArticleStat(article_id=aid, source_id=sid, language=lang, word_count=100,
                       total_mentions=0, distinct_keywords=0, max_single_kw=0,
                       unsegmented=unseg, metrics=metrics)


def _en_cohort():
    # 12 spread-out normal "en" articles + 1 Share-Now pathology.
    stats = []
    for i in range(12):
        d = 0.10 + i * 0.01  # density 0.10..0.21
        stats.append(_stat(i + 1, 100, "en", {
            "mention_density": d, "type_token": 0.6 + i * 0.01,
            "vocab_sparsity": 0.10 + i * 0.005, "single_kw_dominance": 0.05 + i * 0.005,
        }))
    pathology = _stat(999, 200, "en", {
        "mention_density": 2.0, "type_token": 0.03, "vocab_sparsity": 0.06, "single_kw_dominance": 0.85,
    })
    stats.append(pathology)
    return stats


def test_share_now_pathology_is_flagged_and_a_normal_article_is_not():
    stats = _en_cohort()
    baselines = build_baselines(stats, floor=3)
    records = flag_outliers(stats, baselines, floor=3)
    by_id = {r["article_id"]: r for r in records}
    # the pathology fires all three: high density, low type_token, high single_kw_dominance
    assert 999 in by_id and by_id[999]["pathology_furniture_repetition"] is True
    dims = {f["dimension"]: f["direction"] for f in by_id[999]["flagged_dimensions"]}
    assert dims["mention_density"] == "high" and dims["type_token"] == "low"
    assert dims["single_kw_dominance"] == "high"
    # a MID normal article (index 6, density ~0.16) is in no tail -> NOT flagged
    assert 7 not in by_id or not by_id[7]["flagged_dimensions"]


def test_zero_spread_cohort_flags_nothing_but_a_real_outlier_still_flags():
    # Skeptic HIGH regression: a healthy UNIFORM cohort (every value identical, mad=0, p90==p10)
    # must flag NOTHING — a value AT the common percentile is not an outlier. The old `>=` tail
    # flagged 100% of such a cohort.
    uniform = [_stat(i, 1, "en", dict.fromkeys(("mention_density", "type_token", "vocab_sparsity", "single_kw_dominance"), 0.5))
               for i in range(40)]
    assert flag_outliers(uniform, build_baselines(uniform, floor=3), floor=3) == []
    # ...but a genuine outlier ABOVE the uniform bulk still flags (only it)
    uniform.append(_stat(999, 2, "en", {"mention_density": 5.0, "type_token": 0.5,
                                        "vocab_sparsity": 0.5, "single_kw_dominance": 0.5}))
    recs = flag_outliers(uniform, build_baselines(uniform, floor=3), floor=3)
    assert [r["article_id"] for r in recs] == [999]


def test_flag_records_carry_value_baseline_and_n_never_a_verdict():
    stats = _en_cohort()
    baselines = build_baselines(stats, floor=3)
    rec = next(r for r in flag_outliers(stats, baselines, floor=3) if r["article_id"] == 999)
    f = rec["flagged_dimensions"][0]
    assert "value" in f and "baseline" in f and f["baseline"]["n"] >= 3
    assert set(f["baseline"]) >= {"median", "p10", "p90", "p99", "mad", "n"}


def test_small_cohort_gets_no_baseline_said_honestly():
    stats = [_stat(1, 1, "sw", {"mention_density": 0.5, "type_token": 0.5, "vocab_sparsity": 0.5,
                                "single_kw_dominance": 0.5})]
    baselines = build_baselines(stats, floor=30)
    assert baselines["sw"]["mention_density"]["insufficient"] is True
    # a cohort with no baseline flags nothing
    assert flag_outliers(stats, baselines, floor=30) == []


def test_unsegmented_word_count_metrics_are_not_applicable_not_flagged():
    # a big zh cohort so a baseline exists; density/sparsity must be N/A (the language flag), and
    # the article must NOT be flagged on those dimensions.
    stats = [_stat(i, 1, "zh", {"mention_density": None, "type_token": 0.5 + i * 0.001,
                                "vocab_sparsity": None, "single_kw_dominance": 0.5}, unseg=True)
             for i in range(40)]
    # add one zh article with an extreme type_token (a real, segmentation-independent signal)
    stats.append(_stat(999, 1, "zh", {"mention_density": None, "type_token": 0.01,
                                      "vocab_sparsity": None, "single_kw_dominance": 0.5}, unseg=True))
    records = flag_outliers(stats, build_baselines(stats, floor=3), floor=3)
    r999 = next(r for r in records if r["article_id"] == 999)
    assert "mention_density" in r999["not_applicable"] and "vocab_sparsity" in r999["not_applicable"]
    assert all(f["dimension"] not in ("mention_density", "vocab_sparsity")
               for f in r999["flagged_dimensions"])


# --------------------------------------------------------------------------- #
# Layer B — the three selectors
# --------------------------------------------------------------------------- #

def test_random_selector_is_fixed_seed_deterministic_and_skips_empty_sources():
    s2a = {1: [10, 11, 12], 2: [20, 21], 3: []}  # source 3 has 0 articles
    a, skipped_a = select_random_per_source(s2a, seed=42)
    b, skipped_b = select_random_per_source(s2a, seed=42)
    assert a == b  # deterministic
    assert 3 not in a and skipped_a == 1  # 0-article source skipped + counted
    assert a[1] in s2a[1] and a[2] in s2a[2]
    # a different seed can pick differently (not guaranteed, but the picks stay in-range)
    c, _ = select_random_per_source(s2a, seed=7)
    assert c[1] in s2a[1]


def test_keyword_outlier_selector_caps_per_dimension_per_source():
    # 5 flagged articles on the SAME (source, dimension) -> capped at OUTLIER_CAP
    records = [{
        "source_id": 1, "article_id": aid, "flagged_dimensions": [
            {"dimension": "mention_density", "value": 1.0 + aid,
             "baseline": {"median": 0.1, "mad": 0.05, "p90": 0.3}}],
    } for aid in range(5)]
    chosen = select_keyword_outliers(records, cap=3)
    assert len(chosen) == 3  # capped


def test_source_fingerprint_selector_pulls_a_flagged_sources_articles():
    s2a = {1: [10, 11, 12, 13], 2: [20]}
    chosen = select_source_fingerprint({1}, s2a, cap=2)
    assert chosen and chosen.issubset(set(s2a[1]))  # only the flagged source's articles
    assert 20 not in chosen


def test_sample_union_labels_every_selector_that_fired():
    methods = build_sample_union({1: 10, 2: 20}, {10, 30}, {30, 40})
    assert methods[10] == ["random_per_source", "keyword_outlier"]  # picked twice
    assert methods[30] == ["keyword_outlier", "source_fingerprint"]
    assert methods[40] == ["source_fingerprint"]


# --------------------------------------------------------------------------- #
# Layer C — cross-source DF furniture detection
# --------------------------------------------------------------------------- #

def test_furniture_is_high_cross_source_df_no_denylist():
    top = {
        1: ["election", "court", "share now"],
        2: ["inflation", "share now", "read more"],
        3: ["share now", "read more", "cookie"],
        4: ["share now", "read more", "cookie"],
        5: ["share now", "read more", "cookie"],
        6: ["election", "budget", "senate"],  # a healthy topical source
    }
    df = compute_cross_source_df(top)
    assert df["share now"] == 5 and df["senate"] == 1  # furniture is ubiquitous, topic is rare
    flagged, shares = flag_furniture_sources(top, df, n_sources=6, min_sources=3, share_threshold=0.6)
    assert 6 not in flagged and shares[6] == 0.0  # the healthy topical source is NOT flagged
    assert {3, 4, 5} <= flagged  # the furniture-dominated sources are flagged


# --------------------------------------------------------------------------- #
# Integration — build the whole ZIP over an in-memory fixture corpus
# --------------------------------------------------------------------------- #

def _corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    sources = {
        "healthy": Source(name="Healthy", domain="healthy.example", source_type="news", language="en", enabled=True),
        "furniture": Source(name="Furniture", domain="furni.example", source_type="news", language="en", enabled=True),
        "news_letter": Source(name="NL", domain="newsletters.import.local", source_type="newsletter", language="en", enabled=True),
        "empty": Source(name="Empty", domain="empty.example", source_type="news", language="en", enabled=True),
    }
    for src in sources.values():
        s.add(src)
    s.flush()
    kw_cache: dict[str, Keyword] = {}

    def kw(term):
        if term not in kw_cache:
            k = Keyword(term=term, normalized_term=term.lower())
            s.add(k)
            s.flush()
            kw_cache[term] = k
        return kw_cache[term]

    aid = [0]

    def add_article(src, *, content, word_count, lang, mentions, links=0):
        aid[0] += 1
        art = Article(url=f"http://x/{aid[0]}", canonical_url=f"http://x/{aid[0]}",
                      source_id=src.id, content=content, hash=f"h{aid[0]}",
                      word_count=word_count, language=lang, title=f"t{aid[0]}")
        s.add(art)
        s.flush()
        for term, count in mentions.items():
            s.add(KeywordMention(keyword_id=kw(term).id, article_id=art.id, count=count))
        for i in range(links):
            s.add(ArticleLink(article_id=art.id, url=f"http://o/{i}", normalized_url=f"http://o/{i}", link_type="external"))
        return art

    # healthy source: topical keywords, normal shape
    for _ in range(6):
        add_article(sources["healthy"], content="A genuine article about the election and the economy. " * 30,
                    word_count=400, lang="en", mentions={"election": 4, "economy": 3, "court": 2, "budget": 2, "senate": 1})
    # furniture source: the Share-Now pathology (few distinct, one dominates, short)
    for _ in range(4):
        add_article(sources["furniture"], content="Share Now Share Now Share Now Read More Read More",
                    word_count=8, lang="en", mentions={"share now": 20, "read more": 6}, links=12)
    # newsletter source: one article (will be the random-per-source pick) — body must be gated
    add_article(sources["news_letter"], content="PRIVATE newsletter body that must not leak by default.",
                word_count=200, lang="en", mentions={"election": 3, "policy": 2})
    s.commit()
    return s


def test_build_report_end_to_end_and_newsletter_text_gate():
    s = _corpus()
    files = build_quality_report_files(s, generated_at="2026-07-13T12:00:00", seed=20260713, floor=3)
    assert set(files) == {"manifest.json", "per_language_health.json", "per_source_keywords.jsonl",
                          "per_source_summary.jsonl", "keyword_outliers.jsonl", "sample_articles.jsonl",
                          "README.md"}
    manifest = json.loads(files["manifest.json"])
    assert manifest["schema"] == sq.SCHEMA and manifest["temporary"] is True
    assert manifest["corpus_totals"]["articles"] == 11

    # per-source keyword fingerprints parse and carry cross_source_df, no score
    psk = [json.loads(ln) for ln in files["per_source_keywords.jsonl"].decode().splitlines() if ln]
    assert any(row["top_keywords"] for row in psk)

    # the newsletter article was sampled (random-per-source) but its body is GATED (default off)
    samples = [json.loads(ln) for ln in files["sample_articles.jsonl"].decode().splitlines() if ln]
    nl = [r for r in samples if r["is_newsletter"]]
    assert nl, "the newsletter source's article should be sampled by random_per_source"
    assert all(r["text_head"] is None and r["text_head_gated"] is True for r in nl)
    # ...but a web/healthy article DOES carry its text head
    web = [r for r in samples if not r["is_newsletter"] and r["text_head"]]
    assert web, "web articles should export a text head"

    # with the gate ON, the newsletter body is exported
    files_on = build_quality_report_files(s, generated_at="2026-07-13T12:00:00", seed=20260713,
                                          floor=3, include_newsletter_text=True)
    samples_on = [json.loads(ln) for ln in files_on["sample_articles.jsonl"].decode().splitlines() if ln]
    nl_on = [r for r in samples_on if r["is_newsletter"]]
    assert nl_on and any(r["text_head"] for r in nl_on)


def test_fingerprint_sample_is_bounded_and_disclosed(monkeypatch):
    # Skeptic MED regression: a source with more than the cap gets a bounded, seeded fingerprint
    # sample (so the corpus_keywords IN(...) can't blow SQLite's variable limit), and it is
    # DISCLOSED per source. Lower the cap so the fixture's 6-article healthy source trips it.
    monkeypatch.setattr(sq, "FINGERPRINT_SAMPLE_CAP", 2)
    s = _corpus()
    files = build_quality_report_files(s, generated_at="2026-07-13T12:00:00", floor=3)
    psk = [json.loads(ln) for ln in files["per_source_keywords.jsonl"].decode().splitlines() if ln]
    healthy = next(r for r in psk if r["domain"] == "healthy.example")  # 6 articles > cap 2
    assert healthy["fingerprint_sampled"] is True
    small = next(r for r in psk if r["domain"] == "newsletters.import.local")  # 1 article <= cap
    assert small["fingerprint_sampled"] is False
    manifest = json.loads(files["manifest.json"])
    assert manifest["config"]["fingerprint_sample_cap"] == 2
    assert "furniture_min_sources" in manifest["config"] and "furniture_ubiquity_cut" in manifest["config"]


def test_no_score_field_anywhere_in_the_bundle():
    s = _corpus()
    files = build_quality_report_files(s, generated_at="2026-07-13T12:00:00", floor=3)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade")), k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for name, data in files.items():
        if name.endswith(".json"):
            walk(json.loads(data))
        elif name.endswith(".jsonl"):
            for ln in data.decode().splitlines():
                if ln:
                    walk(json.loads(ln))


def test_read_only_the_report_writes_no_rows():
    s = _corpus()
    before_articles = s.query(Article).count()
    before_keywords = s.query(Keyword).count()
    build_quality_report_files(s, generated_at="2026-07-13T12:00:00", floor=3)
    assert s.query(Article).count() == before_articles
    assert s.query(Keyword).count() == before_keywords
    assert not s.dirty and not s.new  # the diagnostic added/changed nothing
