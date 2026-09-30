"""FD03 option b (2026-09-29, R93): source qualification below the memory floor.

The field report of 2026-09-24 (QUAL-1) measured it and the maintainer reported it again on
2026-09-29 («after 72 hours of scraping on 8 different instances, not a single source has
been added despite seeing >80000 candidates»): every field VM sits at 3.8 GiB, under the
4 GiB floor, and below the floor ``run_qualification_pass`` declined outright on every pass.
One of the maintainer's diagnostics bundles reads ``with_judging_attempt: 0`` over 33,767
sources -- the admission gate had never judged anything on that machine.

What is pinned here:

* below the floor, when a bounded sample fits, the pass JUDGES -- against a cohort built from
  the newest ``QUALIFICATION_SAMPLE_ARTICLES`` articles -- and says so in the result and in
  every attempt row it writes (``CRITERIA_VERSION_SAMPLED``);
* the floor itself stays (FD03 = a): the whole-corpus scan is still never run there, and a
  machine where even the sample does not fit is still refused, naming both needs;
* above the floor nothing changes (the whole-corpus cohort, ``CRITERIA_VERSION``);
* the sampled statistics and the scoped link read give the SAME answers the unbounded reads
  give for the rows they cover -- only what is read changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.config.machine_floor as mf
from src.analytics import source_audit as sa
from src.analytics import source_quality as sq
from src.catalog import qualification as q
from src.database.models import (
    Article,
    ArticleLink,
    Base,
    Source,
    SourceQualificationAttempt,
)
from tests.test_source_qualification import (
    _add_candidate_with_articles,
    _seed_healthy_en_cohort,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def machine(monkeypatch):
    """Pin what the machine measures, through the REAL floor: ``machine(total, avail)``."""
    monkeypatch.delenv("OO_ALLOW_BIG_SCANS", raising=False)

    def _set(total_mb, available_mb):
        monkeypatch.setattr(q, "scan_budget", lambda articles, **k: mf.scan_budget(
            articles, override=False, total_mb=total_mb, available_mb=available_mb))

    return _set


FIELD_VM = (3924.0, 900.0)  # the field's 3.8 GiB Qubes VM, busy collecting
BIG_BOX = (16384.0, 8192.0)


def test_the_field_vm_now_judges_candidates_against_a_sample(machine):
    machine(*FIELD_VM)
    s = _session()
    _seed_healthy_en_cohort(s)
    good = _add_candidate_with_articles(s, domain="good.example", status=q.STATUS_UNQUALIFIED,
                                        pathology=False)

    out = q.run_qualification_pass(s, fetcher=None, per_pass=10)

    assert out.get("skipped") is None, "below the floor the pass must no longer decline"
    assert out["baseline"] == "sample"
    assert out["baseline_sample_articles"] == q.QUALIFICATION_SAMPLE_ARTICLES
    assert out["criteria_version"] == q.CRITERIA_VERSION_SAMPLED
    s.refresh(good)
    assert good.status == q.STATUS_QUALIFIED and good.enabled is True
    assert good.qualification_criteria_version == q.CRITERIA_VERSION_SAMPLED
    versions = {a.criteria_version for a in s.query(SourceQualificationAttempt)}
    assert versions == {q.CRITERIA_VERSION_SAMPLED}


def test_a_sample_is_a_baseline_not_a_free_pass(machine):
    """The gate still refuses a broken scrape when it judges against a sample."""
    machine(*FIELD_VM)
    s = _session()
    _seed_healthy_en_cohort(s)
    bad = _add_candidate_with_articles(s, domain="bad.example", status=q.STATUS_UNQUALIFIED,
                                       pathology=True)
    out = q.run_qualification_pass(s, fetcher=None, per_pass=10)
    assert out["baseline"] == "sample" and out["disqualified"] == 1
    s.refresh(bad)
    assert bad.status == q.STATUS_DISQUALIFIED


def test_the_whole_corpus_scan_is_still_never_run_below_the_floor(machine, monkeypatch):
    """FD03 = a stays: the floor keeps the whole-corpus scan off. Only the bounded one runs."""
    machine(*FIELD_VM)
    s = _session()
    _seed_healthy_en_cohort(s)
    _add_candidate_with_articles(s, domain="good.example", status=q.STATUS_UNQUALIFIED,
                                 pathology=False)
    calls: list[int | None] = []
    real = sq.collect_article_stats

    def spy(session, **kw):
        if kw.get("source_ids") is None:
            calls.append(kw.get("recent_limit"))
        return real(session, **kw)

    monkeypatch.setattr(sq, "collect_article_stats", spy)
    q.run_qualification_pass(s, fetcher=None, per_pass=10)
    assert calls == [q.QUALIFICATION_SAMPLE_ARTICLES], calls


def test_a_machine_where_even_the_sample_does_not_fit_is_refused_by_name(machine):
    machine(3924.0, 100.0)
    s = _session()
    _seed_healthy_en_cohort(s)
    good = _add_candidate_with_articles(s, domain="good.example", status=q.STATUS_UNQUALIFIED,
                                        pathology=False)
    out = q.run_qualification_pass(s, fetcher=None, per_pass=10)
    assert out["evaluated"] == 0 and out["skipped"] == "memory"
    assert out["sample_need_mb"] and out["sample_need_mb"] > 100.0
    assert out["override_env"] == "OO_ALLOW_BIG_SCANS"
    s.refresh(good)
    assert good.status == q.STATUS_UNQUALIFIED
    assert s.query(SourceQualificationAttempt).count() == 0


def test_above_the_floor_nothing_changes(machine):
    machine(*BIG_BOX)
    s = _session()
    _seed_healthy_en_cohort(s)
    good = _add_candidate_with_articles(s, domain="good.example", status=q.STATUS_UNQUALIFIED,
                                        pathology=False)
    out = q.run_qualification_pass(s, fetcher=None, per_pass=10)
    assert out["baseline"] == "whole" and out["baseline_sample_articles"] is None
    s.refresh(good)
    assert good.qualification_criteria_version == q.CRITERIA_VERSION


def test_cohort_plan_names_the_three_modes(machine):
    machine(*BIG_BOX)
    assert q.cohort_plan(None, articles=2_000_000)["mode"] == "whole"
    machine(*FIELD_VM)
    plan = q.cohort_plan(None, articles=2_000_000)
    assert plan["mode"] == "sample" and plan["sample_need_mb"] < 900.0
    machine(3924.0, 100.0)
    assert q.cohort_plan(None, articles=2_000_000)["mode"] == "declined"
    # Unreadable availability never declines -- the floor's own three-state rule.
    machine(3924.0, None)
    assert q.cohort_plan(None, articles=2_000_000)["mode"] == "sample"


def test_the_bulk_job_freezes_the_sample_below_the_floor(machine):
    from src.catalog import qualify_job as qj

    machine(*FIELD_VM)
    s = _session()
    _seed_healthy_en_cohort(s)
    frozen = qj.freeze_cohort(s)
    assert frozen["sample_articles"] == q.QUALIFICATION_SAMPLE_ARTICLES
    assert frozen["furniture_df"] is None, "the per-source furniture layer is not bounded by N"
    machine(*BIG_BOX)
    assert qj.freeze_cohort(s)["sample_articles"] is None


# --------------------------------------------------------------------------- #
# The bounded reads answer exactly what the unbounded ones answer, for their rows
# --------------------------------------------------------------------------- #

def test_recent_limit_reads_the_newest_articles_with_their_own_aggregates():
    s = _session()
    _seed_healthy_en_cohort(s, n_sources=7, n_articles=4)  # 28 articles
    whole = {st.article_id: st for st in sq.collect_article_stats(s)}
    newest = sq.collect_article_stats(s, recent_limit=10)
    assert len(newest) == 10
    assert {st.article_id for st in newest} == set(sorted(whole)[-10:])
    for st in newest:
        w = whole[st.article_id]
        assert (st.total_mentions, st.distinct_keywords, st.max_single_kw, st.word_count) == (
            w.total_mentions, w.distinct_keywords, w.max_single_kw, w.word_count)
    assert sq.collect_article_stats(s, recent_limit=0) == []


def test_recent_limit_skips_quarantined_articles():
    s = _session()
    _seed_healthy_en_cohort(s, n_sources=2, n_articles=3)
    newest = max(a for (a,) in s.query(Article.id))
    s.query(Article).filter(Article.id == newest).update({"quarantined": True})
    s.commit()
    ids = {st.article_id for st in sq.collect_article_stats(s, recent_limit=3)}
    assert newest not in ids and len(ids) == 3


def _links(s, article_id, n):
    for i in range(n):
        s.add(ArticleLink(article_id=article_id, url=f"https://out.example/{article_id}/{i}",
                          normalized_url=f"https://out.example/{article_id}/{i}",
                          link_type="external"))


def test_scoped_link_density_answers_what_the_unscoped_read_answers():
    s = _session()
    _seed_healthy_en_cohort(s, n_sources=3, n_articles=3)
    arts = s.query(Article.id, Article.source_id).order_by(Article.id).all()
    # word_count is 400: 200 links makes an article dense, 2 does not.
    _links(s, arts[0][0], 200)
    _links(s, arts[1][0], 2)
    _links(s, arts[4][0], 200)
    s.commit()
    everything = sq.link_dense_article_ids(s)
    assert everything == {arts[0][0], arts[4][0]}
    src0 = arts[0][1]
    assert sq.link_dense_article_ids(s, source_ids={src0}) == {
        a for a, sid in arts if sid == src0} & everything
    assert sq.link_dense_article_ids(s, source_ids=set()) == set()
    subset = {arts[1][0], arts[4][0]}
    assert sq.link_dense_article_ids(s, article_ids=subset) == {arts[4][0]}
    assert sq.link_dense_article_ids(s, article_ids=set()) == set()


def test_frozen_cohort_says_whether_it_was_sampled():
    s = _session()
    _seed_healthy_en_cohort(s)
    whole = sa.frozen_cohort(s, min_articles=q.TRIAL_MIN_ARTICLES)
    assert whole["sample_articles"] is None
    sampled = sa.frozen_cohort(s, min_articles=q.TRIAL_MIN_ARTICLES, sample_articles=10)
    assert sampled["sample_articles"] == 10 and sampled["articles"] == 10


def test_the_status_route_carries_the_cohort_plan(monkeypatch, tmp_path, machine):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    machine(*FIELD_VM)
    with TestClient(app) as c:
        body = c.get("/api/sources/qualify-bulk/status").json()
    assert body["cohort"]["mode"] == "sample"
    assert body["cohort"]["sample_articles"] == q.QUALIFICATION_SAMPLE_ARTICLES


def test_the_sources_panel_reads_the_plan_not_the_floor_alone():
    from tests.js_source_helper import function_source, read_static

    js = read_static("app-ai-tools.js")
    idle = function_source(js, "loadQualifyBulk")
    assert "st.cohort" in idle and 'co.mode === "declined"' in idle
    assert "instead of the whole corpus" in idle
    start = function_source(js, "qualifyBulkStart")
    assert 'pre.cohort.mode === "declined"' in start


# --------------------------------------------------------------------------- #
# R94 (2026-09-29): re-qualification is ONE QUEUE -- new first, every source quarterly
# --------------------------------------------------------------------------- #

def test_a_qualified_source_rejoins_the_queue_every_quarter():
    assert q.QUALIFIED_RECHECK_MONTHS == 3
    # The disqualified ladder keeps its semester cap (ruling 12 mirrors it for calendars).
    assert [q.backoff_months(n) for n in range(1, 6)] == [1, 2, 4, 6, 6]


def _qualified(s, domain, judged_at):
    src = Source(name=domain, domain=domain, language="en", enabled=True,
                 status=q.STATUS_QUALIFIED, qualified_at=judged_at)
    s.add(src)
    s.flush()
    s.add(SourceQualificationAttempt(source_id=src.id, attempted_at=judged_at,
                                     verdict=q.STATUS_QUALIFIED,
                                     criteria_version=q.CRITERIA_VERSION))
    s.commit()
    return src


def test_unused_new_slots_go_down_the_queue_to_qualified_rechecks(machine):
    """With no new candidates left, the pass re-verifies at its full per-pass rate instead of
    the reserved two -- the queue keeps moving. `recheck_per_pass = 0` still means off."""
    from datetime import UTC, datetime, timedelta

    machine(*BIG_BOX)
    now = datetime(2026, 12, 1, tzinfo=UTC)
    s = _session()
    old = now - timedelta(days=30 * q.QUALIFIED_RECHECK_MONTHS + 5)
    for i in range(6):
        _qualified(s, f"q{i}.example", old)
    out = q.run_qualification_pass(s, fetcher=None, per_pass=5, recheck_per_pass=2, now=now)
    assert out["new_candidates"] == 0 and out["rechecks"] == 6
    off = q.run_qualification_pass(s, fetcher=None, per_pass=5, recheck_per_pass=0, now=now)
    assert off.get("rechecks", 0) == 0


def test_the_queue_view_reads_new_first_then_due_rechecks():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 12, 1, tzinfo=UTC)
    s = _session()
    for d in ("a.example", "b.example"):
        s.add(Source(name=d, domain=d, enabled=False, status=q.STATUS_UNQUALIFIED))
    s.commit()
    tried = s.query(Source).filter_by(domain="a.example").one()
    q.log_no_evidence_attempts(s, [tried], now=now - timedelta(days=1))
    s.commit()
    _qualified(s, "due.example", now - timedelta(days=100))
    _qualified(s, "fresh.example", now - timedelta(days=10))

    view = q.qualification_queue(s, now=now)
    assert view["order"] == ["new", "rechecks"]
    assert view["new"]["total"] == 2 and view["new"]["untried"] == 1
    assert view["new"]["tried_without_evidence"] == 1
    # Never-tried before tried-without-evidence: the pass's own order.
    assert view["new"]["next"] == ["b.example", "a.example"]
    assert view["rechecks"]["qualified_due"] == 1
    assert [r["domain"] for r in view["rechecks"]["next"]] == ["due.example"]
    assert view["waiting"]["qualified"] == 1
    assert view["waiting"]["next_joins_at"].startswith("2027-02-")
    for key in view:
        assert "score" not in key


def test_the_queue_view_lists_no_qualified_source_when_rechecks_are_off():
    """With `recheck_per_pass = 0` the pass takes no qualified source, spill included, so the
    view must not name a line that never moves."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 12, 1, tzinfo=UTC)
    s = _session()
    _qualified(s, "due.example", now - timedelta(days=100))
    view = q.qualification_queue(s, now=now, recheck_per_pass=0)
    assert view["rechecks"]["qualified_rechecks_on"] is False
    assert view["rechecks"]["qualified_due"] == 0 and view["rechecks"]["next"] == []
    on = q.qualification_queue(s, now=now, recheck_per_pass=2)
    assert on["rechecks"]["qualified_due"] == 1 and on["rechecks"]["next"]


def test_the_queue_route_and_panel(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from tests.js_source_helper import function_source, read_static

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as c:
        body = c.get("/api/sources/qualification/queue").json()
    assert body["order"] == ["new", "rechecks"] and "per_pass" in body
    js = read_static("app-ai-tools.js")
    assert "/api/sources/qualification/queue" in function_source(js, "loadQualQueue")
    assert 'id="qual-queue"' in read_static("index.html")


# --------------------------------------------------------------------------- #
# Adaptive per-pass budgets and the bounded candidate read (2026-09-30 follow-up)
# --------------------------------------------------------------------------- #

def test_pass_budgets_follow_the_machine_and_never_drop_below_the_setting():
    small = q.adaptive_pass_budgets(5, 2, available_mb=500.0, cpus=1)
    assert (small["new"], small["rechecks"]) == (5, 2), "a small box keeps today's numbers"
    big = q.adaptive_pass_budgets(5, 2, available_mb=16000.0, cpus=8)
    assert big["new"] == 48 and big["rechecks"] == 24 and big["auto"] is True
    huge = q.adaptive_pass_budgets(5, 2, available_mb=200000.0, cpus=64)
    assert (huge["new"], huge["rechecks"]) == (60, 30), "generous, but not unbounded"
    pinned_up = q.adaptive_pass_budgets(80, 40, available_mb=500.0, cpus=1)
    assert (pinned_up["new"], pinned_up["rechecks"]) == (80, 40), "the setting is a floor"


def test_a_zero_budget_stays_zero_and_an_unreadable_machine_changes_nothing(monkeypatch):
    assert q.adaptive_pass_budgets(0, 2, available_mb=16000.0, cpus=8)["new"] == 0
    assert q.adaptive_pass_budgets(5, 0, available_mb=16000.0, cpus=8)["rechecks"] == 0
    monkeypatch.setattr("src.config.machine_floor._mem_readings", lambda: (None, None))
    out = q.adaptive_pass_budgets(5, 2, cpus=8)
    assert (out["new"], out["rechecks"], out["auto"]) == (5, 2, False)


def test_the_lane_and_the_queue_view_use_the_same_budgets(monkeypatch):
    from src.scheduler.settings import SchedulerSettings

    assert SchedulerSettings().qualification_budget_auto is True
    monkeypatch.setattr(q, "adaptive_pass_budgets", lambda n, r, **k: {
        "new": 33, "rechecks": 11, "auto": True, "available_mb": 1.0, "cpus": 1})
    seen = {}
    import src.catalog.qualification as qmod

    monkeypatch.setattr(qmod, "advance_qualification", lambda session, fetcher, **k: seen.update(k) or {})
    from src.scheduler.runner import _lane_step_qualification

    _lane_step_qualification(None, None, SchedulerSettings())
    assert seen == {"per_pass": 33, "recheck_per_pass": 11}
    seen.clear()
    _lane_step_qualification(None, None, SchedulerSettings(qualification_budget_auto=False))
    assert seen == {"per_pass": 5, "recheck_per_pass": 2}, "off pins the configured numbers"


def _many_articles(s, source_id, n):
    from src.database.models import Article

    for i in range(n):
        s.add(Article(url=f"https://x.example/{source_id}/{i}", canonical_url=f"https://x.example/{source_id}/{i}", hash=f"h{source_id}-{i}", title=f"t{i}", source_id=source_id,
                      word_count=300, language="en", content="c"))
    s.commit()


def test_a_candidates_read_is_its_newest_articles_and_no_more():
    s = _session()
    for d in ("a.example", "b.example"):
        s.add(Source(name=d, domain=d, language="en", enabled=False, status=q.STATUS_UNQUALIFIED))
    s.commit()
    ids = {d: s.query(Source).filter_by(domain=d).one().id for d in ("a.example", "b.example")}
    _many_articles(s, ids["a.example"], 30)
    _many_articles(s, ids["b.example"], 3)
    stats = sq.collect_article_stats(s, source_ids=set(ids.values()), per_source_recent=10)
    by = {}
    for st in stats:
        by.setdefault(st.source_id, []).append(st.article_id)
    assert len(by[ids["a.example"]]) == 10 and len(by[ids["b.example"]]) == 3
    everything = {a for (a,) in s.query(__import__("src.database.models", fromlist=["Article"]).Article.id)
                  .filter_by(source_id=ids["a.example"])}
    assert set(by[ids["a.example"]]) == set(sorted(everything)[-10:]), "the NEWEST ten"
    assert sq.collect_article_stats(s, source_ids=set(ids.values()), per_source_recent=0) == []
    # An unscoped call ignores the per-source bound: there is no candidate read to bound.
    assert len(sq.collect_article_stats(s, per_source_recent=10)) == 33


def test_the_pass_reports_how_many_candidates_hit_the_read_cap(machine, monkeypatch):
    machine(*BIG_BOX)
    monkeypatch.setattr(q, "QUALIFICATION_HISTORY_ARTICLES", 25)
    s = _session()
    _seed_healthy_en_cohort(s)
    cand = _add_candidate_with_articles(s, domain="big.example", status=q.STATUS_UNQUALIFIED,
                                        pathology=False)
    _many_articles(s, cand.id, 40)
    out = q.run_qualification_pass(s, fetcher=None, per_pass=5)
    assert out["history_cap"] == 25 and out["history_capped"] == 1


def test_a_deliberately_lowered_budget_is_kept_even_on_a_big_machine():
    """The low power profile writes 2, an operator may write 1: auto grows, never overrides."""
    out = q.adaptive_pass_budgets(2, 1, available_mb=16000.0, cpus=8)
    assert (out["new"], out["rechecks"]) == (2, 1)


def test_auto_can_be_switched_off_through_the_settings_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as c:
        assert c.get("/api/scheduler/config").json().get("qualification_budget_auto") is True
        r = c.put("/api/scheduler/config", json={"qualification_budget_auto": False})
        assert r.status_code == 200
        assert c.get("/api/scheduler/config").json()["qualification_budget_auto"] is False


def test_every_surface_quotes_the_budgets_the_lane_runs(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.monitoring import activity_ledger as al

    monkeypatch.setattr(q, "adaptive_pass_budgets", lambda n, r, **k: {
        "new": 33, "rechecks": 11, "auto": True, "available_mb": 1.0, "cpus": 1})
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as c:
        pp = c.get("/api/sources/qualification/queue").json()["per_pass"]
        assert (pp["new"], pp["rechecks"], pp["auto"]) == (33, 11, True)
        cfg = c.get("/api/sources/qualification/config").json()
        assert cfg["recheck"]["per_pass"] == 11
    st = SimpleNamespace(qualification_per_pass=5, qualification_recheck_per_pass=2,
                         qualification_budget_auto=True)
    assert al._qualification_budget(st, 0) == 33 and al._qualification_budget(st, 1) == 11


def test_a_source_under_the_cap_draws_the_same_furniture_sample_as_before():
    from src.analytics import source_audit as sa2
    from src.database.models import Article

    s = _session()
    s.add(Source(name="f.example", domain="f.example", language="en", enabled=False,
                 status=q.STATUS_UNQUALIFIED))
    s.commit()
    sid = s.query(Source).one().id
    _many_articles(s, sid, 12)
    unbounded = sa2.sq_source_to_articles(s, source_ids={sid})[sid]
    bounded = sa2.sq_source_to_articles(s, source_ids={sid}, per_source_recent=50)[sid]
    assert bounded == unbounded == sorted(a for (a,) in s.query(Article.id))
