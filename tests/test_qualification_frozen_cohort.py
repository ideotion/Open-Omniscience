"""S5.1 + S5.2 (2026-09-02 crash analysis): the qualification scan.

S5.1 -- the COHORT baselines a verdict is measured against were re-read from the whole
corpus once per BATCH OF 20, from both the bulk job and the per-pass ride-along. Measured
at 117,510 articles that is ~131.8 MiB of Python per call (a 17.1 MiB aggregate dict, a
75.0 MiB ``ArticleStat`` list at 669 B each, 39.7 MiB of per-source dicts) plus the
connection's page cache -- and a batch of 20 candidates does not change a corpus-wide
cohort. The cohort is now frozen once per RUN and only the candidates' own metrics are
read per batch, scoped in SQL.

That CHANGES VERDICT SEMANTICS (a batch is judged against a baseline up to a run old),
which is why ``CRITERIA_VERSION`` is bumped and the staleness rides the result. So the
load-bearing guard here is not the statement count -- it is the PARITY twin: on the same
corpus, with a fresh freeze, the new path must stamp the identical statuses for the
identical reasons as the old one. And its ANTI-VACUITY companion, because a fixture where
nothing fails passes for free: a zero-spread cohort makes p90 = 0 and would hide any
baseline change at all.

S5.2 -- the memory guard polled only BETWEEN batches, so the largest transient in the pass
was the one part of it nothing could interrupt. The scan now consults a callback every few
thousand rows of BOTH its loops and raises ``ScanPaused``, which the job records as
``paused`` WITHOUT stamping any verdict. The negative twin is what keeps that honest:
healthy readings must leave the stamped verdicts byte-identical.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from src.analytics import source_audit as sa
from src.analytics import source_quality as sq
from src.catalog.qualification import (
    CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    TRIAL_MIN_ARTICLES,
    run_qualification_pass,
)
from src.database.models import Article, Keyword, KeywordMention, Source
from tests.test_source_qualification import (
    _add_candidate_with_articles,
    _engine_session,
    _seed_healthy_en_cohort,
)


class _JobCtx:
    """The JobContext surface ``run_bulk_qualification`` uses. Pinned to the real class
    below rather than hand-waved, so this double cannot describe a context that could not
    exist."""

    stopping = False

    def set_progress(self, *, done=0, total=0, detail=""):
        pass


def test_the_job_context_double_matches_the_real_one():
    import inspect

    from src.jobs.background import JobContext

    real = inspect.signature(JobContext.set_progress)
    mine = inspect.signature(_JobCtx.set_progress)
    assert set(real.parameters) >= set(mine.parameters) - {"self"}
    for name in set(mine.parameters) - {"self"}:
        assert real.parameters[name].kind == mine.parameters[name].kind
    assert hasattr(JobContext, "stopping")


def _add_cohort_like_candidate(s, *, domain: str, n_articles: int = 3) -> Source:
    """A candidate whose articles look like the healthy cohort's -- several distinct
    keywords with varied counts.

    NOT ``_add_candidate_with_articles(pathology=False)``, and the difference is a finding
    rather than a preference: that helper gives each article ONE keyword at count 3, so
    ``single_kw_dominance`` is 1.0 and ``distinct_keywords`` is 1. Those articles are
    themselves keyword-stat outliers, which lifts the ``en`` cohort's p90 far enough to
    HIDE the pathological candidate entirely -- measured, adding it drops the bad source's
    ``pathology_articles`` from 3 to 0. It is the nearest-rank tail trap in miniature, and
    it would have made the parity twin below pass over a fixture with no spread at all."""
    src = Source(name=domain, domain=domain, source_type="news", language="en",
                 region="gb", enabled=True, status=STATUS_UNQUALIFIED)
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

    for i in range(n_articles):
        art = Article(
            url=f"http://{domain}/{i}", canonical_url=f"http://{domain}/{i}",
            source_id=src.id, title="t", word_count=400, language="en",
            content="A genuine article about the election and the economy. " * 30,
            hash=f"hc{domain}{i}",
        )
        s.add(art)
        s.flush()
        for term, count in {f"e{domain}": 4, f"c{domain}": 3, f"b{domain}": 2,
                            f"s{domain}": 2, f"n{domain}": 1}.items():
            s.add(KeywordMention(keyword_id=kw(term).id, article_id=art.id, count=count))
    s.commit()
    return src


def _mixed_corpus(n_healthy: int = 8):
    """A cohort with REAL spread: n healthy same-language sources plus two candidates, one
    of which MUST be disqualified (the nav-furniture pathology) and one of which MUST
    qualify. Both directions are asserted, or the parity twin proves nothing."""
    s = _engine_session()
    _seed_healthy_en_cohort(s, n_sources=n_healthy)
    bad = _add_candidate_with_articles(
        s, domain="bad.example", status=STATUS_UNQUALIFIED, pathology=True
    )
    good = _add_cohort_like_candidate(s, domain="good.example")
    return s, bad.id, good.id


def _old_path(session, candidate_ids: set[int]) -> dict[int, list[dict]]:
    """Exactly what ``run_qualification_pass`` did before S5.1: whole-corpus metrics, a
    furniture DF derived from every source in them, and cohort cuts derived from the same
    dict. Reproduced here rather than kept behind a flag, so the parity claim is against
    the real prior arithmetic and not against a second implementation of the new one."""
    per = sa.per_source_metrics(session)
    shares = sa._furniture_share_by_source(session, list(per))  # noqa: SLF001 - the old call
    for sid, m in per.items():
        m["furniture_share"] = shares.get(sid, 0.0)
    fails = sa.flag_criteria(per, min_articles=TRIAL_MIN_ARTICLES)
    return {sid: fails.get(sid, []) for sid in candidate_ids if sid in per}


def _new_path(session, candidate_ids: set[int]) -> dict[int, list[dict]]:
    frozen = sa.frozen_cohort(session, min_articles=TRIAL_MIN_ARTICLES)
    per = sa.scoped_metrics(session, candidate_ids, frozen)
    fails = sa.flag_criteria(
        per, min_articles=TRIAL_MIN_ARTICLES, cohort_cut=frozen["cohort_cut"]
    )
    return {sid: fails.get(sid, []) for sid in candidate_ids if sid in per}


# --- S5.1: parity, and the anti-vacuity that makes parity mean something --------------- #


def test_the_frozen_path_stamps_the_same_verdicts_for_the_same_reasons():
    """The parity twin. Same corpus, fresh freeze: identical failing criteria per
    candidate, identical values, identical `flagged_by` reasons."""
    s, bad_id, good_id = _mixed_corpus()
    ids = {bad_id, good_id}

    old = _old_path(s, ids)
    new = _new_path(s, ids)

    assert set(old) == set(new), "the two paths judged a different SET of candidates"

    def _canon(fails):
        return sorted(
            (f["criterion"], round(float(f["value"]), 6), f.get("flagged_by")) for f in fails
        )

    for sid in old:
        assert _canon(old[sid]) == _canon(new[sid]), (
            f"source {sid} was judged differently by the frozen path"
        )


def test_the_parity_fixture_really_disqualifies_one_and_qualifies_the_other():
    """ANTI-VACUITY. A cohort with no spread makes p90 = 0.0, every value ties, and the
    parity test above would pass for a baseline that changed completely. So assert the
    fixture genuinely produces BOTH outcomes -- through the real pass, which is what
    turns failing criteria into a status."""
    s, bad_id, good_id = _mixed_corpus()
    out = run_qualification_pass(s, fetcher=None, per_pass=10)

    assert out["disqualified"] >= 1, "no candidate was disqualified -- the fixture has no spread"
    assert out["qualified"] >= 1, "no candidate qualified -- the fixture cannot show parity"
    assert s.get(Source, bad_id).status == STATUS_DISQUALIFIED
    assert s.get(Source, good_id).status == STATUS_QUALIFIED


def test_the_whole_corpus_group_by_runs_once_per_run_not_once_per_batch():
    """The measured defect: the mention GROUP BY (the expensive half) ran per batch.

    Counted from the statements the REAL path emits, over a fixture needing three
    batches. The unscoped GROUP BY is the one with no ``article_id IN`` filter -- the
    scoped per-batch one is a different, bounded statement and is expected to recur."""
    s, bad_id, good_id = _mixed_corpus()
    extra = [
        _add_candidate_with_articles(
            s, domain=f"c{i}.example", status=STATUS_UNQUALIFIED, pathology=(i % 2 == 0)
        ).id
        for i in range(4)
    ]
    all_ids = {bad_id, good_id, *extra}

    whole_corpus_group_bys: list[str] = []

    def _listen(conn, cursor, statement, params, context, executemany):
        low = " ".join(statement.split()).lower()
        if "group by" in low and "keyword_mentions" in low and "article_id in" not in low:
            whole_corpus_group_bys.append(low)

    eng = s.get_bind()
    event.listen(eng, "before_cursor_execute", _listen)
    try:
        # ONE run, three batches of two, sharing one frozen cohort -- the shape the bulk
        # job drives (a memoised provider), not three independent passes.
        frozen: dict = {}

        def _provider():
            if not frozen:
                frozen.update(sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES))
            return frozen

        for _ in range(3):
            run_qualification_pass(
                s, fetcher=None, per_pass=2, cohort_provider=_provider
            )
    finally:
        event.remove(eng, "before_cursor_execute", _listen)

    assert len(all_ids) == 6
    assert len(whole_corpus_group_bys) == 1, (
        f"the whole-corpus mention GROUP BY ran {len(whole_corpus_group_bys)} times for one "
        "run of three batches"
    )


def test_a_pass_with_no_candidates_never_freezes_a_cohort():
    """The provider is a CALLABLE for this reason: nothing to judge must cost nothing."""
    s = _engine_session()
    _seed_healthy_en_cohort(s, n_sources=8)  # every source already qualified
    calls: list[int] = []

    out = run_qualification_pass(
        s, fetcher=None, per_pass=5, cohort_provider=lambda: calls.append(1) or {}
    )
    assert out["evaluated"] == 0
    assert calls == [], "a pass with no candidates still paid for a whole-corpus freeze"


def test_a_cohort_frozen_at_another_threshold_is_refused_not_answered():
    """``min_articles`` decides WHICH sources form the cohort, so a cut frozen at one
    threshold is a different baseline from a cut frozen at another.

    Refused rather than answered because the failure is invisible: frozen at the report's
    20 against a corpus of 4-article sources the cut comes out EMPTY, three soft criteria
    silently stop being flaggable, and every verdict still looks well-formed. This is the
    defect the parity twin caught on its first run, made loud."""
    s, _bad, _good = _mixed_corpus()
    wrong = sa.frozen_cohort(s, min_articles=sa.MIN_SOURCE_ARTICLES)
    assert wrong["min_articles"] != TRIAL_MIN_ARTICLES

    with pytest.raises(ValueError, match="different baseline"):
        run_qualification_pass(
            s, fetcher=None, per_pass=10, cohort_provider=lambda: wrong
        )

    # ANTI-VACUITY: the SAME call with a correctly-frozen cut is accepted, so the refusal
    # is about the threshold and not about supplying a cohort at all.
    right = sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES)
    out = run_qualification_pass(s, fetcher=None, per_pass=10, cohort_provider=lambda: right)
    assert out["evaluated"] == 2


def test_a_scoped_metrics_call_without_a_cohort_is_refused():
    """Judging a handful of sources against a baseline made of themselves is the
    fabricated-baseline defect, so it raises rather than answering."""
    s, bad_id, _good = _mixed_corpus()
    with pytest.raises(ValueError, match="frozen cohort"):
        sa.per_source_metrics(s, source_ids={bad_id})


def _inject_shared_term(s, term: str, domains: list[str], count: int = 9) -> None:
    """Put ONE term in the top-12 of several sources, which is what makes a cross-source DF
    mean anything. Without it every fixture term is unique per source, every DF is 1, the
    ubiquity cut is never reached, and every share reads 0.0 -- the vacuum this fixture
    exists to leave."""
    kw = s.query(Keyword).filter(Keyword.normalized_term == term).one_or_none()
    if kw is None:
        kw = Keyword(term=term, normalized_term=term)
        s.add(kw)
        s.flush()
    for dom in domains:
        src_row = s.query(Source).filter(Source.domain == dom).one()
        for (aid,) in s.query(Article.id).filter(Article.source_id == src_row.id):
            s.add(KeywordMention(keyword_id=kw.id, article_id=int(aid), count=count))
    s.commit()


def test_the_furniture_share_is_measured_against_the_cohorts_df_not_the_batchs():
    """"How much of this source's top-12 is furniture" is measured against how ubiquitous
    those terms are ACROSS SOURCES. Derived per batch, the same source would get a
    different share in every batch it appeared in.

    The fixture has to EARN that: the ubiquity cut is ``max(5, 0.3*n_sources)``, so with
    every fixture term unique to its source no DF ever reaches it and every share is 0.0 --
    which is what the first version of this test asserted three times over, passing for a
    reason unrelated to its claim (the mutation that derives the DF per batch survived it).
    One term shared across six sources clears the cut in the frozen cohort of ten and
    cannot clear it in a batch of two, which is exactly the difference being claimed."""
    s, bad_id, good_id = _mixed_corpus()
    _inject_shared_term(
        s, "readmore",
        ["bad.example"] + [f"healthy{i}.example" for i in range(5)],
    )
    frozen = sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES)

    # ANTI-VACUITY: the shared term must actually be furniture in the frozen cohort, or
    # every reading below is 0.0 and the equality holds for free.
    assert frozen["furniture_df"].get("readmore", 0) >= 5, frozen["furniture_df"]
    assert frozen["furniture_n_sources"] == 10

    alone = sa.scoped_metrics(s, {bad_id}, frozen)[bad_id]["furniture_share"]
    together = sa.scoped_metrics(s, {bad_id, good_id}, frozen)[bad_id]["furniture_share"]
    assert alone > 0.0, "the frozen DF marked nothing as furniture -- the fixture is vacuous"

    whole = sa.per_source_metrics(s, cohort=frozen["cohort"])
    shares = sa._furniture_share_by_source(  # noqa: SLF001 - the frozen DF, as the pass uses it
        s, list(whole), cross_df=frozen["furniture_df"],
        n_sources=frozen["furniture_n_sources"],
    )
    assert alone == together == shares[bad_id]

    # And the negative half: a DF derived from the batch alone CANNOT see the ubiquity, so
    # it reads 0.0 -- the wrong answer this parameter exists to prevent.
    batch_derived = sa._furniture_share_by_source(s, [bad_id, good_id])  # noqa: SLF001
    assert batch_derived[bad_id] != alone



def test_an_empty_scope_is_an_empty_answer_never_the_whole_corpus():
    s, _bad, _good = _mixed_corpus()
    assert sq.collect_article_stats(s, source_ids=set()) == []
    assert sa.scoped_metrics(s, set(), sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES)) == {}


def test_a_scoped_read_touches_only_the_scoped_sources_articles():
    """The S5.1 scoping win itself, which a verdict-parity test cannot see.

    Found by the mutation matrix: deleting the ``source_id IN`` filter from the article
    query survived all seventeen guards, because the extra sources land in ``per``, the
    caller only ever reads ``s.id in per``, and the baseline is the FROZEN cut either way
    -- so every verdict stays identical while the per-batch read goes back to walking the
    whole corpus, which is the entire defect S5.1 removes.

    So the claim has two halves and both are asserted: the scoped call ANSWERS about only
    the scope, and it is bounded in SQL rather than filtered in Python."""
    s, bad_id, good_id = _mixed_corpus()
    frozen = sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES)
    assert len(frozen["cohort"]["baselines"]) >= 1
    assert frozen["sources"] > 2, "the fixture must hold sources OUTSIDE the scope to bound"

    article_selects: list[str] = []

    def _listen(conn, cursor, statement, params, context, executemany):
        low = " ".join(statement.split()).lower()
        if low.startswith("select") and " from articles" in low and "count(" not in low:
            article_selects.append(low)

    eng = s.get_bind()
    event.listen(eng, "before_cursor_execute", _listen)
    try:
        per = sa.scoped_metrics(s, {bad_id}, frozen)
    finally:
        event.remove(eng, "before_cursor_execute", _listen)

    assert set(per) == {bad_id}, (
        f"a scoped read answered about {sorted(set(per))}, not the scope {[bad_id]}"
    )
    assert article_selects, "no article SELECT was observed -- the guard would pass vacuously"
    unbounded = [q for q in article_selects if "source_id in" not in q]
    assert unbounded == [], (
        f"{len(unbounded)} of {len(article_selects)} article SELECTs walked the whole corpus "
        "instead of being bounded by the scope in SQL"
    )


def test_a_language_the_frozen_cohort_never_saw_gets_no_baseline_never_a_borrowed_one():
    """A candidate in a language absent from the freeze must not be judged against another
    language's tail. An empty robust_stats reads n=0, which is the same honest answer a
    below-floor cohort already gets."""
    s, bad_id, _good = _mixed_corpus()
    frozen = sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES)
    per = sa.scoped_metrics(s, {bad_id}, frozen)
    per[bad_id]["dominant_lang"] = "xx"  # a language the cohort has never seen

    fails = sa.flag_criteria(
        per, min_articles=TRIAL_MIN_ARTICLES, cohort_cut=frozen["cohort_cut"]
    )
    soft = [f for f in fails.get(bad_id, []) if "absolute_floor" not in (f.get("flagged_by") or [])]
    assert soft == [], (
        "a soft criterion was flagged against a cohort the frozen baseline never measured"
    )


def test_the_staleness_rides_the_result_and_the_criteria_version_is_bumped():
    s, _bad, _good = _mixed_corpus()
    out = run_qualification_pass(s, fetcher=None, per_pass=10)
    assert out["baseline_articles"] > 0
    assert out["baseline_sources"] > 0
    assert out["baseline_frozen_by_caller"] is False
    assert CRITERIA_VERSION == "oo-source-qualification-2", (
        "the frozen cohort changes what a verdict was measured against, so an attempt row "
        "must not read as though it were judged the old way"
    )


# --- S5.2: the guard can interrupt the scan it guards ---------------------------------- #


@pytest.fixture()
def eager_pause_checks(monkeypatch):
    """The scan consults its callback every ``_PAUSE_CHECK_EVERY`` (5,000) ROWS, and these
    fixtures hold a few dozen -- so a production tick would never be reached and the guard
    would pass over code that does nothing. Compressed here, per the recorded rule that a
    test which shrinks one dimension of a mechanism must shrink the throttle it is compared
    against; a fixture of 5,000 rows would be slow and prove nothing more.

    ``test_a_small_scan_is_deliberately_not_checked`` pins the uncompressed behaviour, so
    this compression cannot quietly become the claim."""
    monkeypatch.setattr(sq, "_PAUSE_CHECK_EVERY", 1)


def test_the_scan_consults_the_pause_callback_and_raises_scan_paused(eager_pause_checks):
    s, _bad, _good = _mixed_corpus()
    with pytest.raises(sq.ScanPaused):
        sq.collect_article_stats(s, should_pause=lambda: True)


def test_a_small_scan_is_deliberately_not_checked():
    """The uncompressed behaviour, stated rather than left as an accident: a scan smaller
    than one tick is never interrupted. That is the honest trade -- the callback reads
    /proc, and a scan that short is not the multi-minute transient the guard exists for."""
    s, _bad, _good = _mixed_corpus()
    calls: list[int] = []
    out = sq.collect_article_stats(s, should_pause=lambda: calls.append(1) or True)
    assert out, "the fixture produced no rows, so this proves nothing"
    assert calls == [], "a sub-tick scan consulted the callback after all"


def test_the_pause_is_checked_in_both_loops(eager_pause_checks):
    """Both loops, because the mention aggregate and the article pass are separately
    capable of running for minutes on a large corpus.

    Counted EXACTLY, not "at least twice": the first version asserted the callback was
    consulted more than once, which one loop ticking many times satisfies on its own -- so
    deleting either ``_tick()`` survived it. The two loops are given DIFFERENT row counts
    (one article quarantined; the mention GROUP BY has no quarantine filter, so it still
    walks all 38) so the total names which half went missing when it does."""
    s, _bad, _good = _mixed_corpus()
    victim = s.query(Article).first()
    victim.quarantined = True
    s.commit()

    n_articles = s.query(Article).filter(Article.quarantined.isnot(True)).count()
    n_mention_rows = s.query(KeywordMention.article_id).distinct().count()
    assert n_articles and n_mention_rows and n_articles != n_mention_rows, (
        "the two loops must walk different row counts, or the total cannot attribute a loss"
    )

    consults = {"n": 0}

    def _never() -> bool:
        consults["n"] += 1
        return False

    sq.collect_article_stats(s, should_pause=_never)
    assert consults["n"] == n_mention_rows + n_articles, (
        f"consulted {consults['n']} times; the mention loop walks {n_mention_rows} rows and "
        f"the article loop {n_articles} -- a total matching only one of them means the other "
        "loop never consults the callback at all"
    )

    # And it is a real interrupt, not just a callback: the SECOND consult stops the scan.
    calls = {"n": 0}

    def _pause() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(sq.ScanPaused):
        sq.collect_article_stats(s, should_pause=_pause)


def test_the_scoped_read_is_interruptible_in_both_of_its_loops(eager_pause_checks):
    """The SCOPED path is a third and fourth loop, and it is the one the gate runs per
    batch -- so its interruptibility is the S5.2 claim in the case that actually recurs.

    Found by the mutation matrix: deleting the ``_tick()`` from the chunked mention branch
    survived every other guard, because the unscoped test drives a different branch
    entirely. The two loops are given different row counts (one of the candidate's articles
    has its mentions removed) so a missing tick names itself."""
    s, bad_id, _good = _mixed_corpus()
    aids = [
        int(a) for (a,) in s.query(Article.id).filter(
            Article.source_id == bad_id, Article.quarantined.isnot(True)
        )
    ]
    assert len(aids) >= 2
    s.query(KeywordMention).filter(KeywordMention.article_id == aids[0]).delete(
        synchronize_session=False
    )
    s.commit()

    n_articles = len(aids)
    n_mention_rows = (
        s.query(KeywordMention.article_id)
        .filter(KeywordMention.article_id.in_(aids))
        .distinct()
        .count()
    )
    assert n_articles != n_mention_rows, (
        "the two scoped loops must walk different row counts, or a loss cannot be attributed"
    )

    consults = {"n": 0}

    def _never() -> bool:
        consults["n"] += 1
        return False

    sq.collect_article_stats(s, source_ids={bad_id}, should_pause=_never)
    assert consults["n"] == n_mention_rows + n_articles, (
        f"consulted {consults['n']} times; the scoped mention loop walks {n_mention_rows} "
        f"rows and the scoped article loop {n_articles}"
    )

    calls = {"n": 0}

    def _pause() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(sq.ScanPaused):
        sq.collect_article_stats(s, source_ids={bad_id}, should_pause=_pause)


def test_a_paused_scan_stamps_nothing(eager_pause_checks):
    """The whole point of the typed exception: a partial scan must never be read as a
    complete one, and a never-judged candidate keeps ``unqualified``, which is the truth."""
    s, bad_id, good_id = _mixed_corpus()
    out = run_qualification_pass(
        s, fetcher=None, per_pass=10, should_pause=lambda: True,
    )
    assert out["paused"] == "memory"
    assert out["evaluated"] == 0
    assert s.get(Source, bad_id).status == STATUS_UNQUALIFIED
    assert s.get(Source, good_id).status == STATUS_UNQUALIFIED


def test_a_paused_scoped_read_stamps_nothing_either(eager_pause_checks):
    """The pass has TWO whole-corpus scans that can pause -- the freeze and the scoped read
    -- and the freeze always runs first, so a test that simply says "pause always" only ever
    exercises the freeze. Found by the mutation matrix: making the SCOPED handler read a
    partial scan as a complete one survived, because nothing reached it.

    The cohort is supplied (the memoised-provider shape the bulk job drives), so the freeze
    does not scan at all and the pause lands where this test claims it does."""
    s, bad_id, good_id = _mixed_corpus()
    frozen = sa.frozen_cohort(s, min_articles=TRIAL_MIN_ARTICLES)

    out = run_qualification_pass(
        s, fetcher=None, per_pass=10,
        cohort_provider=lambda: frozen, should_pause=lambda: True,
    )
    assert out["paused"] == "memory"
    assert out["evaluated"] == 0
    assert s.get(Source, bad_id).status == STATUS_UNQUALIFIED
    assert s.get(Source, good_id).status == STATUS_UNQUALIFIED
    # and nothing was recorded as examined-and-found-clean either
    assert out.get("no_evidence", 0) == 0


def test_healthy_readings_leave_the_stamped_verdicts_byte_identical(eager_pause_checks):
    """The NEGATIVE TWIN. A pause that fired on a healthy machine would refuse every
    verdict, which looks conservative and is a fabricated refusal.

    Runs with the callback consulted on EVERY row (the fixture), because at production
    granularity a 76-row fixture never reaches the 5,000-row check at all -- so without it
    this passed against a build that ignored the reading entirely and paused regardless."""
    s, bad_id, good_id = _mixed_corpus()
    asked = {"n": 0}

    def _healthy() -> bool:
        asked["n"] += 1
        return False

    out = run_qualification_pass(s, fetcher=None, per_pass=10, should_pause=_healthy)
    assert asked["n"] > 0, "the callback was never consulted -- the twin proves nothing"
    assert "paused" not in out
    assert s.get(Source, bad_id).status == STATUS_DISQUALIFIED
    assert s.get(Source, good_id).status == STATUS_QUALIFIED


def test_the_ride_along_scan_is_interruptible_too(eager_pause_checks, monkeypatch):
    """S5.2 has TWO entry points to the same whole-corpus scan -- the bulk job and the
    per-pass ride-along -- and the brief's own wording ("the whole-corpus scan runs
    unguarded inside a batch") covers both. A fix that reaches one of two callers is the
    recorded gate-every-entry-point defect, so the ride-along gets the guard by default."""
    from src.catalog.qualification import advance_qualification
    from src.scheduler import memguard

    s, bad_id, good_id = _mixed_corpus()
    monkeypatch.setattr(memguard.memory_guard, "poll", lambda: True)

    out = advance_qualification(s, fetcher=None, per_pass=10)
    assert out["paused"] == "memory"
    assert out["evaluated"] == 0
    assert s.get(Source, bad_id).status == STATUS_UNQUALIFIED
    assert s.get(Source, good_id).status == STATUS_UNQUALIFIED


def test_a_healthy_ride_along_stamps_exactly_as_before(eager_pause_checks, monkeypatch):
    """The NEGATIVE TWIN of the ride-along wiring. Reading the guard on every row must not
    change a single verdict on a machine that is fine -- a pause fired on a healthy box is
    a fabricated refusal, and it would silently stop the per-pass gate doing its job."""
    from src.catalog.qualification import advance_qualification
    from src.scheduler import memguard

    s, bad_id, good_id = _mixed_corpus()
    asked = {"n": 0}

    def _healthy() -> bool:
        asked["n"] += 1
        return False

    monkeypatch.setattr(memguard.memory_guard, "poll", _healthy)
    out = advance_qualification(s, fetcher=None, per_pass=10)
    assert asked["n"] > 0, "the guard was never consulted -- the twin proves nothing"
    assert "paused" not in out
    assert s.get(Source, bad_id).status == STATUS_DISQUALIFIED
    assert s.get(Source, good_id).status == STATUS_QUALIFIED


def test_the_bulk_job_records_a_paused_scan_as_paused_and_saves_progress(monkeypatch):
    """End to end through the real job: a scan that pauses is reported as paused with the
    reason, and nothing is stamped. The guard's OWN poll is left healthy, so the only thing
    that can produce this outcome is the in-scan check S5.2 added."""
    from contextlib import contextmanager

    from src.catalog import qualify_job
    from src.scheduler import memguard

    s, bad_id, good_id = _mixed_corpus()

    @contextmanager
    def _scope():
        yield s
        s.commit()

    monkeypatch.setattr(memguard.memory_guard, "poll", lambda: False)  # healthy BETWEEN batches
    monkeypatch.setattr(
        qualify_job, "freeze_cohort",
        lambda db, should_pause=None: (_ for _ in ()).throw(sq.ScanPaused("paused in the freeze")),
    )

    out = qualify_job.run_bulk_qualification(
        _JobCtx(), batch_size=10, fetcher=None, session_factory=_scope, sleep_s=0.0
    )
    assert "paused" in (out.get("paused_reason") or "")
    assert out["complete"] is False
    assert s.get(Source, bad_id).status == STATUS_UNQUALIFIED
    assert s.get(Source, good_id).status == STATUS_UNQUALIFIED


def test_the_bulk_job_freezes_the_cohort_once_across_several_batches():
    """The S5.1 win, at the level the job owns: one freeze per RUN, not per batch."""
    from contextlib import contextmanager

    from src.catalog import qualify_job

    s, _bad, _good = _mixed_corpus()
    for i in range(6):
        _add_candidate_with_articles(
            s, domain=f"j{i}.example", status=STATUS_UNQUALIFIED, pathology=(i % 2 == 0)
        )

    @contextmanager
    def _scope():
        yield s
        s.commit()

    # WRAP the real seam rather than re-implementing it: a double that rebuilt the call
    # would drift from the threshold the seam threads through, which is the very mismatch
    # the guard above refuses.
    freezes: list[int] = []
    import src.catalog.qualify_job as qj

    orig = qj.freeze_cohort

    def _counted(db, **kw):
        freezes.append(1)
        return orig(db, **kw)

    qj.freeze_cohort = _counted
    try:
        out = qualify_job.run_bulk_qualification(
            _JobCtx(), batch_size=2, fetcher=None, session_factory=_scope, sleep_s=0.0
        )
    finally:
        qj.freeze_cohort = orig

    assert out["batches_run"] >= 4, f"the fixture did not need several batches: {out}"
    assert freezes == [1], (
        f"the whole-corpus cohort was frozen {len(freezes)} times for one run of "
        f"{out['batches_run']} batches"
    )
