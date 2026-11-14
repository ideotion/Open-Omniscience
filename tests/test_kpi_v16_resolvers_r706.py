"""R706 (open-on-main row 20, OPEN_QUEUE V1-6): K5, K7 and K8 read the last PERSISTED measurement of their instrument.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP. ``src/monitoring/kpi.py:_RESOLVERS`` held K2, K6 and K11 only, so K5 (keyword noise), K7 (date extraction) and K8
(source health) were structurally "not measurable" even after their diagnostics had run: K7 had a real field figure (51.6%)
the board could not see. PR #1019 built the persisted channel for K6 alone; this is the same channel for the other three.

What these tests pin: each figure comes from a record written where the instrument MEASURES (never by the KPI GET), is shown
with the MEASUREMENT's date (never re-stamped), and where the instrument measured no such figure, or never ran, the metric is
"not measured" with no value and no as_of: never a figure computed or defaulted on the board.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.monitoring import kpi as K

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """Every record lives beside K6's: point that folder at tmp_path (the suite shares one data folder)."""
    monkeypatch.setattr(K, "_coverage_path", lambda: tmp_path / "keyword-coverage.json")
    return tmp_path


def _metric(mid: str) -> dict:
    return next(m for m in K.kpi_snapshot()["metrics"] if m["id"] == mid)


def _age(tmp_path: Path, name: str, days: int = 30) -> str:
    """Age a record so a resolver that re-stamps its as_of with now is told apart from one that does not."""
    path = tmp_path / name
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["measured_at"] = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    path.write_text(json.dumps(rec), encoding="utf-8")
    return rec["measured_at"]


def _assert_not_measured(m: dict) -> None:
    assert m["verdict"] == "not-measurable-here"
    assert m["value"] is None and m["as_of"] is None


# --------------------------------------------------------------------------- K7, date extraction
_DATES = {"corpus": {"articles_total": 9000, "scanned": 1500, "articles_with_extracted_dates": 774, "coverage_pct": 51.6,
                     "articles_with_datelike_text_but_no_extraction": 410}}


def test_k7_shows_the_recorded_whole_corpus_coverage_with_its_date(isolated):
    assert K.record_date_coverage(_DATES, {"scan": 1500, "days": None, "lang": None}) is not None
    then = _age(isolated, "date-extraction-coverage.json")
    m = _metric("K7")
    assert m["value"] == 51.6 and m["n"] == 1500 and m["as_of"] == then
    assert m["verdict"] == "measured-no-bar"
    assert "774 of the 1500" in m["method"] and "30.0 day(s) ago" in m["method"] and "410" in m["method"]
    assert m["source_endpoint"] == "/api/diagnostics/dates"  # the route that exists (it said /datediag)


@pytest.mark.parametrize("query", [{"scan": 1500, "days": 7, "lang": None}, {"scan": 1500, "days": None, "lang": "fr"}])
def test_k7_a_filtered_run_records_nothing(isolated, query):
    assert K.record_date_coverage(_DATES, query) is None
    _assert_not_measured(_metric("K7"))


def test_k7_only_the_standard_scan_is_recorded(isolated):
    """The Opus read of R706: a quick probe (scan=50) measured another population and must not replace the standard record."""
    assert K.record_date_coverage(_DATES, {"scan": 1500}) is not None
    assert K.record_date_coverage({"corpus": {**_DATES["corpus"], "scanned": 50, "coverage_pct": 90.0}}, {"scan": 50}) is None
    assert _metric("K7")["value"] == 51.6
    route = (_ROOT / "src/api/diagnostics/dates.py").read_text(encoding="utf-8")
    assert f"scan: int = Query({K.DATES_STANDARD_SCAN}," in route  # the constant is the route's own default
    bundle = (_ROOT / "src/api/diagnostics/bundle.py").read_text(encoding="utf-8")
    assert f"scan={K.DATES_STANDARD_SCAN}" in bundle  # and the bundle's, so a bundle records it


def test_k7_an_empty_scan_is_not_a_coverage_of_zero(isolated):
    empty = {"corpus": {"articles_total": 0, "scanned": 0, "articles_with_extracted_dates": 0, "coverage_pct": 0.0,
                        "articles_with_datelike_text_but_no_extraction": 0}}
    K.record_date_coverage(empty, {"scan": 1500})
    m = _metric("K7")
    _assert_not_measured(m)
    assert "different fact from a coverage of 0" in m["method"]


# --------------------------------------------------------------------------- K8, source health
_AUDIT = {
    "sources_audited": 40, "min_articles": 20,
    "status_counts": [{"status": "healthy", "n": 31}, {"status": "watch", "n": 5}, {"status": "degraded", "n": 3},
                      {"status": "failing", "n": 1}],
    "region_self_audit": {"by_region": {"europe": {"total": 25, "pct_failing": 0.0, "counts": []},
                                        "africa": {"total": 15, "pct_failing": 6.67, "counts": []}}},
}


def test_k8_shows_the_recorded_healthy_share_with_its_date_and_the_regions_beside_it(isolated):
    rec = K.record_source_audit_status(_AUDIT)
    assert rec is not None and rec["healthy_pct"] == 77.5  # taken where the audit is made
    then = _age(isolated, "source-audit-status.json")
    m = _metric("K8")
    assert m["value"] == 77.5 and m["n"] == 40 and m["as_of"] == then and m["verdict"] == "measured-no-bar"
    assert "31 healthy, 5 watch, 3 degraded, 1 failing" in m["method"]
    assert {r["region"]: r["pct_failing"] for r in m["by_region"]} == {"africa": 6.67, "europe": 0.0}


def test_k8_says_the_share_is_cohort_relative_and_names_the_allowlist(isolated):
    from src.analytics.source_audit import SOURCE_COHORT_FLOOR

    K.record_source_audit_status(_AUDIT, allowlisted=2)
    m = _metric("K8")
    assert "COHORT-RELATIVE" in m["method"] and f"floor ({SOURCE_COHORT_FLOOR} sources)" in m["method"]
    assert "2 allowlisted domain(s) capped at watch" in m["method"]


def test_k8_a_record_without_a_healthy_row_says_so_not_that_none_was_audited(isolated):
    K.record_source_audit_status({**_AUDIT, "status_counts": [{"status": "watch", "n": 40}]})
    m = _metric("K8")
    _assert_not_measured(m)
    assert "no healthy count" in m["method"] and "audited no source" not in m["method"]


@pytest.mark.parametrize(("furniture", "written"), [(False, False), (True, True)])
def test_k8_the_route_records_only_the_full_audit(isolated, monkeypatch, furniture, written):
    """Through the real route function: without the furniture check a failing source can read healthy, so nothing is kept."""
    import src.analytics.source_audit as SA
    from src.api.diagnostics import sources as route

    monkeypatch.setattr(SA, "audit_sources", lambda *_a, **_k: dict(_AUDIT))
    monkeypatch.setenv("OO_SOURCE_AUDIT_ALLOWLIST", "a.example,b.example")
    route.source_audit(download=False, with_furniture=furniture, recency_window=False, db=None)
    rec = K.read_source_audit_status()
    assert (rec is not None) is written
    if written:
        assert rec["allowlisted_domains"] == 2


def test_k8_no_audited_source_is_not_a_share(isolated):
    K.record_source_audit_status({"sources_audited": 0, "min_articles": 20, "status_counts": [
        {"status": "healthy", "n": 0}], "region_self_audit": {"by_region": {}}})
    _assert_not_measured(_metric("K8"))


# --------------------------------------------------------------------------- K5, keyword noise
def test_k5_states_the_last_run_but_shows_no_figure_the_instrument_never_measured(isolated):
    """The keyword-engine report lists generic-term REVIEW candidates; it measures no share of top terms. The board says when
    the list was made and how long it was, and shows no number (R706: never a computed figure)."""
    _assert_not_measured(_metric("K5"))
    K.record_keyword_generic_terms({"generic_terms": {"candidate_terms": 42, "top_per_language": 15,
                                                      "by_language": {"en": [], "fr": [], "de": []}}})
    then = _age(isolated, "keyword-generic-terms.json")
    m = _metric("K5")
    _assert_not_measured(m)
    assert then in m["method"] and "42 generic-term review candidates" in m["method"] and "3 languages" in m["method"]


# --------------------------------------------------------------------------- the channel itself
def test_nothing_recorded_means_not_measured_for_all_three(isolated):
    for mid in ("K5", "K7", "K8"):
        m = _metric(mid)
        _assert_not_measured(m)
        assert "never run on this GET" in m["method"]


def test_a_corrupt_or_foreign_record_is_not_read(isolated):
    (isolated / "date-extraction-coverage.json").write_text("{not json", encoding="utf-8")
    (isolated / "source-audit-status.json").write_text('{"schema": "else", "healthy_pct": 99}', encoding="utf-8")
    _assert_not_measured(_metric("K7"))
    _assert_not_measured(_metric("K8"))


def test_a_failed_write_records_nothing_and_never_raises(monkeypatch):
    monkeypatch.setattr(K, "_coverage_path", lambda: (_ for _ in ()).throw(OSError("nope")))
    assert K.record_date_coverage(_DATES, {"scan": 1500}) is None
    assert K.record_source_audit_status(_AUDIT) is None
    assert K.record_keyword_generic_terms({"generic_terms": {"candidate_terms": 1}}) is None


def test_the_kpi_get_never_writes_a_record(isolated):
    K.kpi_snapshot()
    assert sorted(p.name for p in isolated.iterdir()) == []


def test_the_selftest_and_the_no_composite_rule_still_hold_with_all_three_measured(isolated):
    K.record_date_coverage(_DATES, {"scan": 1500})
    K.record_source_audit_status(_AUDIT)
    K.record_keyword_generic_terms({"generic_terms": {"candidate_terms": 1, "by_language": {}}})
    assert K.run_kpi_selftest()["passed"] is True


def test_each_instrument_writes_its_record_where_it_measures():
    """Wired at the three diagnostic routes, never in kpi_snapshot. (The all-diagnostics bundle calls these route functions;
    the date one's standard scan is pinned in test_k7_only_the_standard_scan_is_recorded.)"""
    corpus = (_ROOT / "src/api/diagnostics/corpus.py").read_text(encoding="utf-8")
    dates = (_ROOT / "src/api/diagnostics/dates.py").read_text(encoding="utf-8")
    sources = (_ROOT / "src/api/diagnostics/sources.py").read_text(encoding="utf-8")
    assert "record_keyword_generic_terms(report)" in corpus
    assert 'record_date_coverage(payload, {"scan": scan, "days": days, "lang": lang})' in dates
    assert "if with_furniture:" in sources and "record_source_audit_status(report, allowlisted=len(allow))" in sources
    snap = (_ROOT / "src/monitoring/kpi.py").read_text(encoding="utf-8")
    body = snap[snap.index("def kpi_snapshot"):snap.index("def run_kpi_selftest")]
    assert "record_" not in body
