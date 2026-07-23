"""Tests for the source QUALIFICATION lifecycle (0.3 CLOSE GATE ruling,
src/catalog/qualification.py + the Source.status admission gate + the append-only
SourceQualificationAttempt history).

In-memory SQLite, no network (fetcher=None or a scripted stub) -- covers: the boot
self-heal (schema present + idempotent + the "already scraped" backfill), the
admission gate (select_sources excludes not-yet-qualified/disqualified sources), the
background qualification pass (bounded, best-effort, airplane-gated), and the
re-qualification ladder's exact backoff sequence (1 -> 2 -> 4 -> 6, capped, reset on
success). Reuses the SAME corpus-building idiom as tests/test_source_audit.py so the
extraction-validity judging under test is the real, reused source_audit machinery,
never a re-implementation.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.catalog.qualification import (
    CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    advance_qualification,
    backoff_months,
    consecutive_disqualifications,
    consecutive_disqualifications_from_verdicts,
    decide_verdict,
    reattempt_due_at,
    run_qualification_pass,
    select_due_disqualified,
    select_unqualified,
)
from src.database.maintenance import ensure_source_qualification_columns
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    Source,
    SourceQualificationAttempt,
)
from src.ingest import activate_kill_switch, clear_kill_switch
from src.scheduler.runner import select_sources
from src.scheduler.settings import SchedulerSettings


def _engine_session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --------------------------------------------------------------------------- #
# Pure functions: the re-qualification ladder's exact backoff sequence
# --------------------------------------------------------------------------- #

def test_backoff_months_exact_ladder():
    # 1st disqualification -> 1 month, doubling -> 2 -> 4 -> capped at 6 (never 8).
    assert [backoff_months(n) for n in range(1, 8)] == [1, 2, 4, 6, 6, 6, 6]


def test_backoff_months_treats_zero_or_negative_as_first():
    assert backoff_months(0) == 1
    assert backoff_months(-3) == 1


def test_reattempt_due_at_uses_the_ladder_month_count():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert reattempt_due_at(t0, 1) == t0 + timedelta(days=30)
    assert reattempt_due_at(t0, 2) == t0 + timedelta(days=60)
    assert reattempt_due_at(t0, 3) == t0 + timedelta(days=120)
    assert reattempt_due_at(t0, 4) == t0 + timedelta(days=180)
    assert reattempt_due_at(t0, 9) == t0 + timedelta(days=180)  # capped


def test_consecutive_disqualifications_counts_only_the_trailing_run():
    D, Q = STATUS_DISQUALIFIED, STATUS_QUALIFIED
    assert consecutive_disqualifications_from_verdicts([]) == 0
    assert consecutive_disqualifications_from_verdicts([D]) == 1
    assert consecutive_disqualifications_from_verdicts([D, D, D]) == 3
    # newest-first: a QUALIFIED anywhere in the run stops the count immediately
    assert consecutive_disqualifications_from_verdicts([Q, D, D]) == 0
    assert consecutive_disqualifications_from_verdicts([D, Q, D, D]) == 1


def test_decide_verdict_disqualifies_only_the_extraction_failure_signature():
    ef = {"criterion": "pathology_rate", "value": 0.9, "extraction_failure": True}
    soft = {"criterion": "short_article_rate", "value": 0.9, "extraction_failure": False}
    assert decide_verdict([]) == STATUS_QUALIFIED  # healthy
    assert decide_verdict([soft]) == STATUS_QUALIFIED  # watch (soft-only) -- never disqualified
    assert decide_verdict([ef]) == STATUS_DISQUALIFIED  # degraded (signature alone)
    assert decide_verdict([ef, soft]) == STATUS_DISQUALIFIED  # failing (corroborated)


# --------------------------------------------------------------------------- #
# Migration / boot self-heal
# --------------------------------------------------------------------------- #

def _make_legacy_sqlite_db(path: str) -> None:
    """A minimal pre-qualification ``sources`` + ``articles`` schema, matching the
    real column set the self-heal must ADD to (no status/qualified_at/criteria_version)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT, domain TEXT UNIQUE)"
    )
    conn.execute(
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER, "
        "url TEXT, canonical_url TEXT, hash TEXT)"
    )
    conn.execute("INSERT INTO sources (id, name, domain) VALUES (1, 'Already Scraped', 'a.example')")
    conn.execute("INSERT INTO sources (id, name, domain) VALUES (2, 'Never Scraped', 'b.example')")
    conn.execute("INSERT INTO articles (id, source_id, url, canonical_url, hash) "
                 "VALUES (1, 1, 'http://a/1', 'http://a/1', 'h1')")
    conn.commit()
    conn.close()


def test_ensure_source_qualification_columns_adds_schema_and_backfills(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_sqlite_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    added = ensure_source_qualification_columns(engine)
    assert set(added) == {
        "sources.status", "sources.qualified_at", "sources.qualification_criteria_version",
    }

    with engine.connect() as conn:
        rows = {
            r[0]: (r[1], r[2], r[3])
            for r in conn.exec_driver_sql(
                "SELECT id, status, qualified_at, qualification_criteria_version FROM sources"
            )
        }
    # already-scraped source: "the first collect pass IS its qualification pass"
    status, qualified_at, version = rows[1]
    assert status == STATUS_QUALIFIED
    assert qualified_at is not None
    assert version == CRITERIA_VERSION
    # never-scraped source: stays honestly unqualified, no stamp
    status2, qualified_at2, version2 = rows[2]
    assert status2 == STATUS_UNQUALIFIED
    assert qualified_at2 is None
    assert version2 is None


def test_ensure_source_qualification_columns_idempotent(tmp_path):
    db_path = str(tmp_path / "legacy2.db")
    _make_legacy_sqlite_db(db_path)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    first = ensure_source_qualification_columns(engine)
    assert first  # columns were added the first time
    second = ensure_source_qualification_columns(engine)
    assert second == []  # nothing to add the second time -- no error, no re-add

    # A later, real disqualification must SURVIVE re-running the self-heal (the
    # backfill must never re-fire and clobber a real verdict written since).
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"UPDATE sources SET status = '{STATUS_DISQUALIFIED}', qualified_at = NULL "
            "WHERE id = 1"
        )
    ensure_source_qualification_columns(engine)
    with engine.connect() as conn:
        status = conn.exec_driver_sql(
            "SELECT status FROM sources WHERE id = 1"
        ).scalar()
    assert status == STATUS_DISQUALIFIED


# --------------------------------------------------------------------------- #
# Admission gate: only a QUALIFIED (+ enabled) source feeds regular collection
# --------------------------------------------------------------------------- #

def test_select_sources_excludes_not_yet_qualified_and_disqualified():
    s = _engine_session()
    q = Source(name="Q", domain="q.example", enabled=True, status=STATUS_QUALIFIED, rss_url="http://q/feed")
    u = Source(name="U", domain="u.example", enabled=True, status=STATUS_UNQUALIFIED, rss_url="http://u/feed")
    d = Source(name="D", domain="d.example", enabled=True, status=STATUS_DISQUALIFIED, rss_url="http://d/feed")
    s.add_all([q, u, d])
    s.commit()

    rows = select_sources(s, SchedulerSettings()).all()
    domains = {r.domain for r in rows}
    assert domains == {"q.example"}


def test_select_sources_still_respects_enabled_false():
    s = _engine_session()
    q_disabled = Source(name="QD", domain="qd.example", enabled=False, status=STATUS_QUALIFIED)
    s.add(q_disabled)
    s.commit()
    rows = select_sources(s, SchedulerSettings()).all()
    assert rows == []


def test_new_source_defaults_to_unqualified():
    # ORM-level default -- a freshly-created Source (as discovery/import channels do)
    # is admitted-gated by default; nothing pre-qualifies it.
    s = _engine_session()
    src = Source(name="New", domain="new.example", enabled=True)
    s.add(src)
    s.commit()
    s.refresh(src)
    assert src.status == STATUS_UNQUALIFIED


# --------------------------------------------------------------------------- #
# The background qualification pass: bounded, best-effort, judges via the REUSED
# source_audit criteria (never a re-implementation, never a score)
# --------------------------------------------------------------------------- #

def _seed_healthy_en_cohort(s: Session, n_sources: int = 7, n_articles: int = 4) -> None:
    """Enough DISTINCT-vocabulary 'en' articles that the language-level article
    baseline (source_quality.COHORT_FLOOR=30) exists, so a trial candidate's own
    pathology (or lack of it) is actually detectable -- mirrors test_source_audit's
    ``_corpus()`` fixture."""
    kw_cache: dict[str, Keyword] = {}

    def kw(term):
        if term not in kw_cache:
            k = Keyword(term=term, normalized_term=term.lower())
            s.add(k)
            s.flush()
            kw_cache[term] = k
        return kw_cache[term]

    aid = [1000]

    def add(src, *, content, word_count, mentions):
        aid[0] += 1
        art = Article(url=f"http://x/{aid[0]}", canonical_url=f"http://x/{aid[0]}",
                      source_id=src.id, content=content, hash=f"h{aid[0]}",
                      word_count=word_count, language="en", title=f"t{aid[0]}")
        s.add(art)
        s.flush()
        for term, count in mentions.items():
            s.add(KeywordMention(keyword_id=kw(term).id, article_id=art.id, count=count))

    for i in range(n_sources):
        src = Source(name=f"H{i}", domain=f"healthy{i}.example", source_type="news",
                     language="en", region="gb", enabled=True, status=STATUS_QUALIFIED)
        s.add(src)
        s.flush()
        for _ in range(n_articles):
            add(src, content="A genuine article about the election and the economy. " * 30,
                word_count=400, mentions={f"e{i}": 4, f"c{i}": 3, f"b{i}": 2, f"s{i}": 2, f"n{i}": 1})
    s.commit()


def _add_candidate_with_articles(s: Session, *, domain: str, status: str, pathology: bool) -> Source:
    src = Source(name=domain, domain=domain, source_type="news", language="en", region="gb",
                enabled=True, status=status)
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

    for i in range(3):
        if pathology:
            art = Article(url=f"http://{domain}/{i}", canonical_url=f"http://{domain}/{i}",
                          source_id=src.id, content="Share Now Share Now Read More",
                          hash=f"hp{domain}{i}", word_count=8, language="en", title="t")
            s.add(art)
            s.flush()
            s.add(KeywordMention(keyword_id=kw("share now").id, article_id=art.id, count=20))
            s.add(KeywordMention(keyword_id=kw("read more").id, article_id=art.id, count=6))
        else:
            art = Article(url=f"http://{domain}/{i}", canonical_url=f"http://{domain}/{i}",
                          source_id=src.id, content="A genuine article about markets. " * 30,
                          hash=f"hg{domain}{i}", word_count=400, language="en", title="t")
            s.add(art)
            s.flush()
            s.add(KeywordMention(keyword_id=kw(f"topic{domain}").id, article_id=art.id, count=3))
    s.commit()
    return src


def test_run_qualification_pass_disqualifies_the_extraction_failure_candidate():
    s = _engine_session()
    _seed_healthy_en_cohort(s)
    bad = _add_candidate_with_articles(s, domain="bad.example", status=STATUS_UNQUALIFIED, pathology=True)

    out = run_qualification_pass(s, fetcher=None, per_pass=10)
    assert out["enabled"] is True
    assert out["disqualified"] >= 1

    s.refresh(bad)
    assert bad.status == STATUS_DISQUALIFIED
    assert bad.qualified_at is None
    assert bad.qualification_criteria_version is None

    attempts = s.query(SourceQualificationAttempt).filter_by(source_id=bad.id).all()
    assert len(attempts) == 1
    assert attempts[0].verdict == STATUS_DISQUALIFIED
    assert attempts[0].criteria_version == CRITERIA_VERSION


def test_run_qualification_pass_qualifies_a_healthy_candidate():
    s = _engine_session()
    _seed_healthy_en_cohort(s)
    good = _add_candidate_with_articles(s, domain="good.example", status=STATUS_UNQUALIFIED, pathology=False)

    out = run_qualification_pass(s, fetcher=None, per_pass=10)
    assert out["qualified"] >= 1

    s.refresh(good)
    assert good.status == STATUS_QUALIFIED
    assert good.qualified_at is not None
    assert good.qualification_criteria_version == CRITERIA_VERSION


def test_run_qualification_pass_never_a_score_key():
    s = _engine_session()
    _seed_healthy_en_cohort(s)
    _add_candidate_with_articles(s, domain="bad2.example", status=STATUS_UNQUALIFIED, pathology=True)
    out = run_qualification_pass(s, fetcher=None, per_pass=10)
    banned = ("score", "ranking", "rating", "grade")
    for k in out:
        assert not any(b in k.lower() for b in banned), k


def test_run_qualification_pass_is_bounded_by_per_pass():
    s = _engine_session()
    # Seeded WITH real articles (a healthy cohort) so these candidates carry actual
    # evidence and get STAMPED — isolates the per_pass ceiling from the no-evidence
    # path (covered separately below).
    _seed_healthy_en_cohort(s)
    for i in range(5):
        _add_candidate_with_articles(s, domain=f"c{i}.example", status=STATUS_UNQUALIFIED, pathology=False)

    out = run_qualification_pass(s, fetcher=None, per_pass=2)
    assert out["evaluated"] == 2
    assert out["no_evidence"] == 0
    remaining_unqualified = s.query(Source).filter_by(status=STATUS_UNQUALIFIED).count()
    assert remaining_unqualified == 3  # only 2 of 5 were touched this pass


def test_run_qualification_pass_never_qualifies_on_zero_evidence():
    """2026-07-23 field-diagnostics fix: a candidate that produced ZERO stored articles
    (a totally-failed trial fetch, or no rss_url and nothing collected by other means)
    must NEVER be silently stamped ``qualified`` on an empty fails list — it stays
    ``unqualified`` (no attempt row, no stamp) and is re-offered on a later pass."""
    s = _engine_session()
    bare = Source(name="No Evidence", domain="noevidence.example", rss_url="https://noevidence.example/rss",
                  enabled=True, status=STATUS_UNQUALIFIED)
    s.add(bare)
    s.commit()
    bare_id = bare.id

    def failing_fetch(session, source, fetcher, **kw):
        raise RuntimeError("simulated transport failure")

    import src.catalog.qualification as qmod

    orig = qmod.trial_fetch
    qmod.trial_fetch = failing_fetch
    try:
        out = run_qualification_pass(s, fetcher=object(), per_pass=5)
    finally:
        qmod.trial_fetch = orig

    assert out["evaluated"] == 1
    assert out["no_evidence"] == 1
    assert out["qualified"] == 0
    assert out["disqualified"] == 0
    s.refresh(bare)
    assert bare.status == STATUS_UNQUALIFIED
    assert bare.qualified_at is None
    assert s.query(SourceQualificationAttempt).filter_by(source_id=bare_id).count() == 0

    # Re-offered next pass — never permanently stuck, never silently dropped.
    still = select_unqualified(s, limit=5)
    assert any(c.id == bare_id for c in still)


def test_run_qualification_pass_no_rss_url_and_no_prior_articles_stays_unqualified():
    """The documented scope limit ("judged on whatever it has already collected by
    other means, if anything") must not silently resolve to a free pass when there is
    NO other means either — a feed-less, evidence-less candidate stays unqualified."""
    s = _engine_session()
    s.add(Source(name="No Feed", domain="nofeed.example", rss_url=None,
                 enabled=True, status=STATUS_UNQUALIFIED))
    s.commit()

    out = run_qualification_pass(s, fetcher=object(), per_pass=5)
    assert out["no_evidence"] == 1
    assert out["qualified"] == 0
    src = s.query(Source).filter_by(domain="nofeed.example").one()
    assert src.status == STATUS_UNQUALIFIED


def test_run_qualification_pass_still_judges_evidence_from_prior_articles():
    """A source whose TRIAL fetch fails this round but already carries real articles
    from earlier (legacy/imported) ingestion is judged on that EXISTING evidence, not
    treated as no-evidence — the fix only withholds a stamp when there is truly nothing
    to judge."""
    s = _engine_session()
    _seed_healthy_en_cohort(s)
    good = _add_candidate_with_articles(s, domain="already-has-articles.example",
                                         status=STATUS_UNQUALIFIED, pathology=False)

    def failing_fetch(session, source, fetcher, **kw):
        raise RuntimeError("simulated transport failure")

    import src.catalog.qualification as qmod

    orig = qmod.trial_fetch
    qmod.trial_fetch = failing_fetch
    try:
        out = run_qualification_pass(s, fetcher=object(), per_pass=10)
    finally:
        qmod.trial_fetch = orig

    assert out["trial_fetch_errors"] >= 1
    s.refresh(good)
    assert good.status == STATUS_QUALIFIED  # judged on its EXISTING articles, not skipped


def test_run_qualification_pass_per_pass_zero_disables():
    s = _engine_session()
    s.add(Source(name="x", domain="x.example", enabled=True, status=STATUS_UNQUALIFIED))
    s.commit()
    out = run_qualification_pass(s, fetcher=None, per_pass=0)
    assert out == {"enabled": False}
    assert s.query(Source).filter_by(status=STATUS_UNQUALIFIED).count() == 1


def test_run_qualification_pass_no_candidates_is_a_clean_noop():
    s = _engine_session()
    out = run_qualification_pass(s, fetcher=None, per_pass=5)
    assert out == {"enabled": True, "evaluated": 0}


def test_advance_qualification_skips_under_airplane_mode():
    s = _engine_session()
    s.add(Source(name="x", domain="x.example", enabled=True, status=STATUS_UNQUALIFIED, rss_url="http://x/feed"))
    s.commit()
    activate_kill_switch()
    try:
        out = advance_qualification(s, fetcher=None, per_pass=5)
    finally:
        clear_kill_switch()
    assert out == {"enabled": True, "skipped": "airplane mode engaged"}
    assert s.query(Source).filter_by(status=STATUS_UNQUALIFIED).count() == 1  # untouched


def test_advance_qualification_per_pass_zero_disables():
    s = _engine_session()
    out = advance_qualification(s, fetcher=None, per_pass=0)
    assert out == {"enabled": False}


# --------------------------------------------------------------------------- #
# Re-qualification ladder, end to end (DB-backed selection)
# --------------------------------------------------------------------------- #

def test_select_due_disqualified_respects_the_backoff_ladder():
    s = _engine_session()
    src = Source(name="D", domain="d.example", enabled=True, status=STATUS_DISQUALIFIED)
    s.add(src)
    s.flush()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    s.add(SourceQualificationAttempt(
        source_id=src.id, attempted_at=t0, verdict=STATUS_DISQUALIFIED,
        criteria_version=CRITERIA_VERSION,
    ))
    s.commit()

    # 1st disqualification -> due in 1 month: not yet due at +20 days, due at +31 days
    assert select_due_disqualified(s, now=t0 + timedelta(days=20), limit=10) == []
    due = select_due_disqualified(s, now=t0 + timedelta(days=31), limit=10)
    assert [d.domain for d in due] == ["d.example"]


def test_select_due_disqualified_ladder_advances_on_repeated_failure():
    s = _engine_session()
    src = Source(name="D2", domain="d2.example", enabled=True, status=STATUS_DISQUALIFIED)
    s.add(src)
    s.flush()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = t0 + timedelta(days=31)  # the re-check that ran and disqualified it AGAIN
    s.add(SourceQualificationAttempt(source_id=src.id, attempted_at=t0,
                                     verdict=STATUS_DISQUALIFIED, criteria_version=CRITERIA_VERSION))
    s.add(SourceQualificationAttempt(source_id=src.id, attempted_at=t1,
                                     verdict=STATUS_DISQUALIFIED, criteria_version=CRITERIA_VERSION))
    s.commit()

    assert consecutive_disqualifications(s, src.id) == 2
    # 2nd consecutive disqualification -> next check due 2 months after the LAST attempt
    assert select_due_disqualified(s, now=t1 + timedelta(days=45), limit=10) == []
    due = select_due_disqualified(s, now=t1 + timedelta(days=61), limit=10)
    assert [d.domain for d in due] == ["d2.example"]


def test_qualification_attempts_are_append_only_never_overwritten():
    """The vintage convention: a re-attempt is a NEW row -- the full history survives."""
    s = _engine_session()
    _seed_healthy_en_cohort(s)
    bad = _add_candidate_with_articles(s, domain="repeat.example", status=STATUS_UNQUALIFIED, pathology=True)

    run_qualification_pass(s, fetcher=None, per_pass=10,
                            now=datetime(2026, 1, 1, tzinfo=UTC))
    s.refresh(bad)
    assert bad.status == STATUS_DISQUALIFIED
    # force it due again and re-run
    bad_id = bad.id
    run_qualification_pass(
        s, fetcher=None, per_pass=10, now=datetime(2026, 2, 5, tzinfo=UTC),
    )
    attempts = (
        s.query(SourceQualificationAttempt)
        .filter_by(source_id=bad_id)
        .order_by(SourceQualificationAttempt.attempted_at.asc())
        .all()
    )
    assert len(attempts) == 2  # both attempts recorded, neither overwritten
    assert [a.verdict for a in attempts] == [STATUS_DISQUALIFIED, STATUS_DISQUALIFIED]
