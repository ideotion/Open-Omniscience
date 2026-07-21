"""
Standing source AUDITOR (Part-1 Phase 1) — pure mechanism + one DB integration.

The load-bearing honesty properties are asserted here (the negative-space lens is mandatory for a
flag/matcher): the EXTRACTION-FAILURE signature (pathology = furniture repetition) is what reaches
degraded/failing, while a source that is merely TERSE or ATYPICAL (short articles / outlier keyword
stats — legitimate variety) NEVER exceeds ``watch``; auto-demote is DEFAULT-OFF and fires only on a
failing source and NEVER on an allowlisted one; a language cohort below the floor gets NO baseline
(said honestly, never a fabricated flag); a zero-spread cohort flags NOTHING; and no score-like key
appears anywhere in the audit (status names ride as VALUES, never keys — "degraded" contains
"grade").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics.source_audit import (
    CRITERIA,
    SourceAudit,
    audit_sources,
    derive_status,
    flag_criteria,
    per_source_metrics,
    region_self_audit,
    run_source_audit_selftest,
    should_auto_demote,
)
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_BANNED = ("score", "ranking", "rating", "grade")


def _walk_no_score(o, path="") -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            assert not any(b in str(k).lower() for b in _BANNED), f"score-like key: {path}.{k}"
            _walk_no_score(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _walk_no_score(v, f"{path}[{i}]")


# --------------------------------------------------------------------------- #
# PURE — derive_status honours the reframe (soft signals never exceed watch)
# --------------------------------------------------------------------------- #

def _crit(name, ef):
    return {"criterion": name, "value": 0.9, "direction": "high", "extraction_failure": ef,
            "baseline": {"median": 0.1, "p10": 0.0, "p90": 0.2, "mad": 0.05, "n": 12}}


def test_derive_status_soft_signals_never_exceed_watch():
    # terse prose: short_article_rate alone (SOFT) -> watch, NEVER degraded/failing
    assert derive_status([_crit("short_article_rate", False)]) == "watch"
    # terse AND atypical keyword stats: two SOFT signals still only watch (legitimate variety)
    assert derive_status([_crit("short_article_rate", False),
                          _crit("outlier_rate", False)]) == "watch"
    # the extraction-failure signature ALONE (pathology) -> degraded (worth review, not auto-acted)
    assert derive_status([_crit("pathology_rate", True)]) == "degraded"
    # pathology CORROBORATED by a second symptom -> failing (systematically non-usable)
    assert derive_status([_crit("pathology_rate", True),
                          _crit("short_article_rate", False)]) == "failing"
    assert derive_status([]) == "healthy"


def test_only_pathology_is_an_extraction_failure_criterion():
    # the design contract: exactly one EF criterion (the furniture-repetition / nav-DOM signature),
    # so a 'failing' verdict can only be built on an actual extraction-failure signal.
    ef = {c["name"] for c in CRITERIA if c["extraction_failure"]}
    assert ef == {"pathology_rate"}


# --------------------------------------------------------------------------- #
# PURE — flag_criteria: cohort-relative tails, baselines, and honest gaps
# --------------------------------------------------------------------------- #

def _m(sid, *, lang="en", region="gb", n=100, outlier=0.1, path=0.02, mism=0.0, short=0.1, furn=0.1):
    return {"domain": f"s{sid}.example", "language": lang, "region": region, "article_count": n,
            "dominant_lang": lang, "outlier_rate": outlier, "pathology_rate": path,
            "language_mismatch_rate": mism, "short_article_rate": short, "furniture_share": furn}


def test_flag_criteria_flags_bad_tail_and_carries_value_baseline_n():
    per = {i: _m(i) for i in range(10)}
    per[99] = _m(99, path=0.9, short=0.85, outlier=0.9, furn=0.6)
    fails = flag_criteria(per, cohort_floor=8, min_articles=20)
    names = {f["criterion"] for f in fails[99]}
    assert "pathology_rate" in names  # the EF signature is caught
    for f in fails[99]:
        assert "value" in f and "baseline" in f and f["flagged_by"]  # value + baseline + why
        if f["baseline"] is not None:  # a cohort-tail flag carries the baseline + n
            assert f["baseline"]["n"] >= 8 and f["baseline"]["p90"] is not None
    assert fails.get(0, []) == []  # a mid/typical source is in no tail


def test_flag_criteria_small_cohort_no_baseline_for_soft_criteria():
    # a language cohort below the floor cannot judge the SOFT (style-ambiguous) criteria -> NO flags
    # (honest gap, never fabricated). short/outlier/furniture require a cohort to compare against.
    per = {i: _m(i) for i in range(3)}
    per[9] = _m(9, short=0.99, outlier=0.99, furn=0.99, path=0.0)
    assert flag_criteria(per, cohort_floor=8, min_articles=20).get(9) == []


def test_absolute_pathology_floor_catches_a_broken_source_when_the_cohort_cannot():
    # H1 regression (the nearest-rank tail trap): the EXTRACTION-FAILURE signature (pathology) has an
    # absolute floor, so a broken scrape stays visible (a) with no usable cohort, and (b) when its
    # whole cohort is degrading — the exact cases where the robust p90 lands ON a bad value.
    # (a) no cohort:
    tiny = {i: _m(i) for i in range(3)}
    tiny[9] = _m(9, path=0.9)
    tiny_flags = [f["criterion"] for f in flag_criteria(tiny, cohort_floor=8, min_articles=20).get(9, [])]
    assert tiny_flags == ["pathology_rate"]  # only the absolute EF signal (no soft flags w/o cohort)
    # (b) a degraded cohort where the bad sources are a large fraction (2 of 8):
    cohort = {i: _m(i) for i in range(6)}
    cohort[97] = _m(97, path=0.95, short=0.9, outlier=0.9)
    cohort[98] = _m(98, path=0.95, short=0.9, outlier=0.9)
    dc = flag_criteria(cohort, cohort_floor=8, min_articles=20)
    worst = dc.get(97, [])
    assert any(f["criterion"] == "pathology_rate" for f in worst)     # caught despite p90 escape
    assert derive_status(worst) != "healthy"                          # NEVER reads healthy
    # the pathology flag records it was the absolute floor, not the tail, that caught it
    pf = next(f for f in worst if f["criterion"] == "pathology_rate")
    assert "absolute_floor" in pf["flagged_by"]


def test_flag_criteria_zero_spread_cohort_flags_nothing():
    # NEGATIVE SPACE: every source identical -> no tail exists -> nothing flags (the source_quality
    # zero-spread lesson: strict '>' so a flat cohort is never 100%-flagged).
    per = {i: _m(i, outlier=0.3, path=0.3, short=0.3, furn=0.3) for i in range(12)}
    fails = flag_criteria(per, cohort_floor=8, min_articles=20)
    assert all(v == [] for v in fails.values())


def test_flag_criteria_min_articles_gate_excludes_thin_sources():
    per = {i: _m(i) for i in range(10)}
    per[99] = _m(99, n=5, path=0.9, short=0.9)  # below min_articles -> not auditable
    fails = flag_criteria(per, cohort_floor=8, min_articles=20)
    assert 99 not in fails


# --------------------------------------------------------------------------- #
# PURE — auto-demote is default-off, failing-only, allowlist-safe
# --------------------------------------------------------------------------- #

def _audit(status, *, allowlisted=False, failing=None):
    return SourceAudit(source_id=1, domain="s.example", language="en", region="gb",
                       article_count=100, failing_criteria=failing or [], status=status,
                       allowlisted=allowlisted)


def test_should_auto_demote_is_default_off():
    a = _audit("failing", failing=[_crit("pathology_rate", True), _crit("short_article_rate", False)])
    assert should_auto_demote(a) == (False, None)          # default enabled=False
    assert should_auto_demote(a, enabled=False) == (False, None)


def test_should_auto_demote_fires_only_when_enabled_on_failing():
    fc = [_crit("pathology_rate", True), _crit("short_article_rate", False)]
    fire, reason = should_auto_demote(_audit("failing", failing=fc), enabled=True)
    assert fire is True and reason and "pathology_rate" in reason
    # never on a lesser status
    assert should_auto_demote(_audit("degraded", failing=fc), enabled=True)[0] is False
    assert should_auto_demote(_audit("watch"), enabled=True)[0] is False


def test_allowlisted_source_is_never_auto_demoted():
    fc = [_crit("pathology_rate", True), _crit("short_article_rate", False)]
    a = _audit("failing", allowlisted=True, failing=fc)
    assert should_auto_demote(a, enabled=True)[0] is False


# --------------------------------------------------------------------------- #
# PURE — region self-audit + no-score
# --------------------------------------------------------------------------- #

def test_region_self_audit_counts_without_status_keys():
    ra = region_self_audit([
        SourceAudit(1, "a", "en", "gb", 100, status="failing"),
        SourceAudit(2, "b", "en", "gb", 100, status="healthy"),
        SourceAudit(3, "c", "fr", "fr", 100, status="healthy"),
    ])
    gb = ra["by_region"]["gb"]
    # status names ride as VALUES in a list, never as keys (no "grade"/"degraded" key)
    assert isinstance(gb["counts"], list)
    assert next(c["n"] for c in gb["counts"] if c["status"] == "failing") == 1
    assert gb["total"] == 2 and gb["pct_failing"] == 50.0
    _walk_no_score(ra)


def test_no_score_key_in_criteria_or_selftest():
    _walk_no_score({"criteria": list(CRITERIA)})
    _walk_no_score(run_source_audit_selftest())


def test_selftest_passes_with_the_load_bearing_checks():
    out = run_source_audit_selftest()
    assert out["passed"] is True and out["failed_count"] == 0
    names = {c["check"] for c in out["checks"]}
    assert {"extraction_failure_source_is_failing", "terse_prose_source_not_failing",
            "auto_demote_off_by_default", "allowlisted_never_auto_demoted",
            "small_cohort_no_baseline", "no_score_field"} <= names


# --------------------------------------------------------------------------- #
# INTEGRATION — the whole audit over an in-memory fixture corpus (count-only, no decrypt)
# --------------------------------------------------------------------------- #

def _corpus() -> Session:
    """8 en sources (7 healthy w/ distinct topical vocab + 1 furniture-pathology minority) so the
    en cohort clears the article floor and the pathology source sits in the tail; plus 1 fr source
    whose cohort is below the floor (no baseline). The furniture source is a MINORITY of the article
    cohort so the robust p90 lands in the healthy bulk (real corpora look like this)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    kw_cache: dict[str, Keyword] = {}

    def kw(term):
        if term not in kw_cache:
            k = Keyword(term=term, normalized_term=term.lower())
            s.add(k)
            s.flush()
            kw_cache[term] = k
        return kw_cache[term]

    aid = [0]

    def add(src, *, content, word_count, lang, mentions):
        aid[0] += 1
        art = Article(url=f"http://x/{aid[0]}", canonical_url=f"http://x/{aid[0]}",
                      source_id=src.id, content=content, hash=f"h{aid[0]}",
                      word_count=word_count, language=lang, title=f"t{aid[0]}")
        s.add(art)
        s.flush()
        for term, count in mentions.items():
            s.add(KeywordMention(keyword_id=kw(term).id, article_id=art.id, count=count))
        return art

    healthy_srcs = []
    for i in range(7):  # 7 healthy en sources, DISTINCT vocab (so nobody looks like cross-source furniture)
        src = Source(name=f"H{i}", domain=f"healthy{i}.example", source_type="news",
                     language="en", region="gb", enabled=True)
        s.add(src)
        s.flush()
        healthy_srcs.append(src)
        for _ in range(4):  # 4 normal articles each = 28 healthy en articles
            add(src, content="A genuine article about the election and the economy. " * 30,
                word_count=400, lang="en",
                mentions={f"e{i}": 4, f"c{i}": 3, f"b{i}": 2, f"s{i}": 2, f"n{i}": 1})

    furni = Source(name="Furniture", domain="furni.example", source_type="news",
                   language="en", region="gb", enabled=True)
    s.add(furni)
    s.flush()
    for _ in range(3):  # 3 Share-Now pathology stubs (minority of the 31-article en cohort)
        add(furni, content="Share Now Share Now Read More", word_count=8, lang="en",
            mentions={"share now": 20, "read more": 6})

    fr = Source(name="FR", domain="french.example", source_type="news",
                language="fr", region="fr", enabled=True)
    s.add(fr)
    s.flush()
    for _ in range(3):  # a lone fr source: pathology-shaped but its cohort is below the floor
        add(fr, content="Partager Partager Lire plus", word_count=8, lang="fr",
            mentions={"partager": 20, "lire plus": 6})

    s.commit()
    return s, {"healthy": healthy_srcs, "furni": furni, "fr": fr}


def test_audit_flags_the_extraction_failure_source_and_leaves_the_healthy_ones():
    s, srcs = _corpus()
    out = audit_sources(s, min_articles=3, cohort_floor=8)
    by_domain = {r["domain"]: r for r in out["sources"]}

    # the furniture (extraction-failure) source is FAILING via the pathology signature + corroboration
    furni = by_domain["furni.example"]
    assert furni["status"] == "failing", furni["failing_criteria"]
    crits = {f["criterion"] for f in furni["failing_criteria"]}
    assert "pathology_rate" in crits
    assert furni["auto_demote_candidate"] is False  # flag-only: default-off, computed enabled=False

    # every healthy source stays HEALTHY (distinct topical vocab, normal shape)
    for src in srcs["healthy"]:
        assert by_domain[src.domain]["status"] == "healthy", by_domain[src.domain]["failing_criteria"]

    # shape + honesty: status_counts is a list of {status,n}, no score-like key ANYWHERE
    assert isinstance(out["status_counts"], list)
    assert {c["status"] for c in out["status_counts"]} == {"healthy", "watch", "degraded", "failing"}
    assert next(c["n"] for c in out["status_counts"] if c["status"] == "failing") >= 1
    _walk_no_score(out)


def test_small_language_cohort_is_never_flagged():
    # the lone fr source has pathology-shaped articles but its language cohort is below the floor,
    # so it gets NO baseline and is reported healthy — an honest "can't judge", never a fabricated flag.
    s, srcs = _corpus()
    out = audit_sources(s, min_articles=3, cohort_floor=8)
    fr = {r["domain"]: r for r in out["sources"]}["french.example"]
    assert fr["status"] == "healthy" and fr["failing_criteria"] == []


def test_allowlisted_source_is_capped_at_watch_and_never_auto_demoted():
    s, _ = _corpus()
    out = audit_sources(s, allowlist={"furni.example"}, min_articles=3, cohort_floor=8)
    furni = {r["domain"]: r for r in out["sources"]}["furni.example"]
    assert furni["allowlisted"] is True
    assert furni["status"] == "watch"  # a would-be-failing source is capped at watch by the guardrail
    assert furni["auto_demote_candidate"] is False


def test_per_source_metrics_are_count_only_and_shaped():
    s, srcs = _corpus()
    per = per_source_metrics(s)
    furni = per[srcs["furni"].id]
    # count-only extraction-validity rates, no content decrypt, no score
    for key in ("outlier_rate", "pathology_rate", "language_mismatch_rate", "short_article_rate"):
        assert isinstance(furni[key], float)
    assert furni["article_count"] == 3 and furni["pathology_rate"] > 0.0


# --------------------------------------------------------------------------- #
# WIRING — the diagnostics routes exist and (pre-2026-07-20) composed to exactly what
# the Settings button called (the 404-drift lesson: compose prefix+decorator, match the
# caller; text-level so it runs without the crypto/ORM import the endpoint test would
# need). DIAGNOSE-THE-DIAGNOSTICS ruling #7 (2026-07-20) removed the standalone
# source-audit/source-audit-selftest download buttons -- the all-diagnostics bundle
# already carries both (source-audit.json, source-audit-selftest.json; the ratchet in
# tests/test_repo_invariants.py guarantees it), so only the ROUTES stay pinned here.
# --------------------------------------------------------------------------- #

_ROOT = Path(__file__).resolve().parent.parent


def test_source_audit_endpoint_wired_to_the_settings_button():
    diag = (_ROOT / "src/api/diagnostics.py").read_text(encoding="utf-8")
    html = (_ROOT / "src/static/index.html").read_text(encoding="utf-8")
    prefix = re.search(r'APIRouter\(prefix="([^"]+)"', diag).group(1)
    assert prefix == "/api/diagnostics"
    for path in ("/source-audit", "/source-audit-selftest"):
        assert f'@router.get("{path}")' in diag, f"route {path} not registered"
        # the standalone per-report download button is gone (bundle carries it instead)
        assert f"{prefix}{path}?download=1" not in html, (
            f"a removed per-report download button survived for {prefix}{path}"
        )
