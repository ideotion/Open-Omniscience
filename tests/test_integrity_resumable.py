"""The corpus-integrity sweep is resumable: its exact scans walk id ranges and keep their place between builds.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

MEASURED (Windows run, 2026-11-07, 4.09 M keywords, 25.4 M mentions): corpus-integrity hit its 60 s budget and
counter_drift_mentions, counter_drift_articles and foreign_key_violations never completed, so its verdict rested on one
check. The sampled counter-drift grouped EVERY keyword before sorting, the foreign-key pragma was one statement over the whole
database, and a bare count over a whole table is ONE progress opcode, which the deadline cannot stop.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.monitoring import integrity


class MemStore:
    def __init__(self):
        self.state: dict = {}
        self.saves = 0

    def load(self):
        import copy

        return copy.deepcopy(self.state)

    def save(self, state):
        import copy

        self.saves += 1
        self.state = copy.deepcopy(state)


@pytest.fixture()
def session():
    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


@pytest.fixture()
def tiny_ranges(monkeypatch):
    monkeypatch.setattr(integrity, "_FIRST_RANGE_ROWS", 2)
    monkeypatch.setattr(integrity, "_RANGE_GROWTH", 1)  # the range stays 2 rows however fast it ran


def _corpus(s: Session, *, keywords=7, orphans=3, dangling=2):
    src = Source(name="S", domain="s.example")
    s.add(src)
    s.flush()
    a = Article(title="A", content="x", url="http://s.example/a", canonical_url="http://s.example/a", source_id=src.id, hash="h1")
    s.add(a)
    s.flush()
    kws = [Keyword(term=f"k{i}", normalized_term=f"k{i}") for i in range(keywords)]
    s.add_all(kws)
    s.flush()
    live = kws[: keywords - orphans]
    for k in live:
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=2))
        k.mention_count, k.article_count = 2, 1
    for i in range(dangling):  # mentions of an article that is not there (foreign keys are not enforced here)
        s.add(KeywordMention(keyword_id=live[i].id, article_id=9_999 + i, count=1))
        live[i].mention_count += 1
        live[i].article_count += 1
    s.commit()


def _budget_for_ranges(monkeypatch, n):
    """A deadline that allows ``n`` range statements, then reads as spent."""
    calls = {"n": 0}
    real = integrity._scalar

    def counted(session, sql, params=None):
        if params is not None and "lo" in params:
            calls["n"] += 1
        return real(session, sql, params)

    monkeypatch.setattr(integrity, "_scalar", counted)
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: calls["n"] >= n)
    return calls


def test_the_ranged_figures_equal_the_whole_table_counts(session, tiny_ranges):
    _corpus(session)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["orphan_keywords"] == 3
    assert r["dangling_mentions_missing_article"] == 2
    assert r["dangling_mentions_missing_keyword"] == 0
    assert r["incomplete_checks"] == [] and r["timed_out"] is False
    assert r["scan_progress"]["orphan_keywords"]["state"] == "complete"
    assert r["verdict"] == "drift" and "dangling_mentions_missing_article" in r["drift_found_in"]


def test_a_cut_check_reads_none_with_its_place_and_the_next_build_finishes_it(session, tiny_ranges, monkeypatch):
    _corpus(session)
    store = MemStore()
    _budget_for_ranges(monkeypatch, 2)
    first = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert first["orphan_keywords"] is None, "a partial tally is never the figure"
    p = first["scan_progress"]["orphan_keywords"]
    assert p["state"] == "partial" and 0 < p["next_id"] < p["through_id"] and "tally_so_far" in p
    assert first["timed_out"] is True and "orphan_keywords" in first["incomplete_checks"]
    assert first["verdict"].startswith("not established")
    monkeypatch.undo()
    monkeypatch.setattr(integrity, "_FIRST_RANGE_ROWS", 2)
    monkeypatch.setattr(integrity, "_RANGE_GROWTH", 1)
    second = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert second["orphan_keywords"] == 3, "the pass resumed from its saved place and the tally carried over"
    assert second["scan_progress"]["orphan_keywords"]["last_complete"]["value"] == 3
    assert second["scan_progress"]["orphan_keywords"]["last_complete"]["at"], "an older figure carries its date"


def test_a_range_the_budget_interrupts_does_not_move_the_cursor(session, tiny_ranges, monkeypatch):
    _corpus(session)
    store = MemStore()
    real = integrity._scalar
    state = {"n": 0}

    def interrupting(session_, sql, params=None):
        if params is not None and "lo" in params:
            state["n"] += 1
            if state["n"] == 3:
                raise integrity.StatementTimeout("the budget ran out")
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", interrupting)
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert r["timed_out"] is True
    pending = store.state["orphan_keywords"]["pending"]
    assert pending["next_id"] == 4, "two ranges of two rows were counted; the interrupted third was not"


def test_without_a_cursor_store_each_build_starts_over_as_before(session):
    _corpus(session)
    r = integrity.corpus_integrity(session, sample=100)
    assert r["orphan_keywords"] == 3 and r["incomplete_checks"] == []


def test_a_new_pass_starts_after_a_completed_one(session, tiny_ranges):
    _corpus(session)
    store = MemStore()
    integrity.corpus_integrity(session, sample=100, cursor=store)
    assert "pending" not in store.state["orphan_keywords"], "a finished pass leaves no place to resume"
    session.add(Keyword(term="late", normalized_term="late"))
    session.commit()
    again = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert again["orphan_keywords"] == 4, "the next pass counts from the start and sees the new row"


def test_the_foreign_key_check_is_a_table_at_a_time_and_names_what_it_left_to_other_checks(session, tiny_ranges):
    _corpus(session)
    session.add(Article(title="B", content="y", url="http://s.example/b", canonical_url="http://s.example/b", source_id=4_242, hash="h2"))
    session.commit()
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["foreign_key_violations"] >= 1
    assert "articles" in r["foreign_key_violation_tables"]
    fk = r["scan_progress"]["foreign_key_violations"]
    assert fk["state"] == "complete" and fk["left_to_the_mention_checks"] == ["keyword_mentions"]


def test_a_foreign_key_check_the_budget_cuts_resumes_at_the_next_table(session, tiny_ranges, monkeypatch):
    _corpus(session)
    store = MemStore()
    seen = {"n": 0}
    real = integrity.deadline_expired

    def after_two_tables(_s):
        return seen["n"] >= 2

    real_exec = session.execute

    def counting(stmt, *a, **k):
        if "foreign_key_check" in str(stmt):
            seen["n"] += 1
        return real_exec(stmt, *a, **k)

    monkeypatch.setattr(session, "execute", counting)
    monkeypatch.setattr(integrity, "deadline_expired", after_two_tables)
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    fk = r["scan_progress"]["foreign_key_violations"]
    assert r["foreign_key_violations"] is None and fk["state"] == "partial" and fk["tables_checked"] == 2
    monkeypatch.setattr(integrity, "deadline_expired", real)
    monkeypatch.setattr(session, "execute", real_exec)
    r2 = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert r2["scan_progress"]["foreign_key_violations"]["state"] == "complete"
    assert r2["foreign_key_violations"] is not None


def test_the_sampled_drift_reads_the_same_rows_as_the_old_whole_table_grouping(session):
    _corpus(session)
    sampled = integrity.corpus_integrity(session, sample=100)["counter_drift"]
    full = integrity.corpus_integrity(session, full=True)["counter_drift"]
    assert sampled["checked"] == full["checked"] == 7
    assert sampled["keywords_with_mention_drift"] == full["keywords_with_mention_drift"] == 0


def test_the_sampled_drift_statement_no_longer_groups_every_keyword(session):
    import inspect

    src = inspect.getsource(integrity.corpus_integrity)
    assert "(SELECT id, term, mention_count, article_count FROM keywords" in src, "the top keywords are picked first, then joined"
    assert "{scope}" not in src


def test_the_verdict_names_which_checks_completed(session, tiny_ranges, monkeypatch):
    _corpus(session)
    _budget_for_ranges(monkeypatch, 1)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["complete_checks"] and "orphan_keywords" in r["incomplete_checks"]
    assert set(r["complete_checks"]).isdisjoint(r["incomplete_checks"])
    assert r["verdict"].startswith("not established: ") and " did" in r["verdict"]


def test_the_kv_store_holds_the_cursor_and_an_unreadable_one_is_an_absent_one(monkeypatch):
    store = integrity.KvCursorStore()
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda _k: (_ for _ in ()).throw(RuntimeError("locked")))
    assert store.load() == {}
    monkeypatch.setattr("src.config.kv_store.kv_get_json", lambda _k: ["not", "a", "dict"])
    assert store.load() == {}
    saved = {}
    monkeypatch.setattr("src.config.kv_store.kv_set_json", lambda k, v: saved.update({k: v}))
    store.save({"x": 1})
    assert saved == {integrity._CURSOR_KEY: {"x": 1}}


def test_one_long_walk_cannot_starve_the_drift_read_and_the_foreign_key_check(session, tiny_ranges, monkeypatch):
    """The 2026-11-07 shape: the range walks never finish inside the budget. The one-statement drift read runs first and
    each resumable check gets an equal share of what is left, so the foreign-key check is still reached."""
    _corpus(session, keywords=40, orphans=30)
    clock = {"t": 0.0}
    monkeypatch.setattr(integrity, "deadline_left_s", lambda _s: 100.0 - clock["t"])
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: clock["t"] >= 100.0)
    import types

    monkeypatch.setattr(integrity, "time", types.SimpleNamespace(monotonic=lambda: clock["t"]))  # integrity's clock only
    real = integrity._scalar

    def slow_range(session_, sql, params=None):
        if params is not None and "lo" in params:
            clock["t"] += 5.0  # every range costs 5 s of the 100 s budget
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", slow_range)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["counter_drift"]["count_status"] == "ok", "the sampled drift read ran"
    assert r["scan_progress"]["foreign_key_violations"]["state"] == "complete", "the last check still got its share"
    assert r["scan_progress"]["orphan_keywords"]["state"] == "partial", "the long walk stopped at its share"


def test_a_check_cut_mid_range_and_the_checks_after_it_still_say_where_they_stand(session, tiny_ranges, monkeypatch):
    _corpus(session)
    real = integrity._scalar
    state = {"n": 0}

    def interrupting(session_, sql, params=None):
        if params is not None and "lo" in params:
            state["n"] += 1
            if state["n"] == 2:
                raise integrity.StatementTimeout("the budget ran out")
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", interrupting)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["scan_progress"]["orphan_keywords"]["state"] == "partial"
    assert r["scan_progress"]["dangling_mentions_missing_keyword"] == {"state": "not reached"}
    assert r["scan_progress"]["foreign_key_violations"] == {"state": "not reached"}


def test_a_completed_figure_says_when_its_pass_began_as_well_as_when_it_ended(session, tiny_ranges):
    _corpus(session)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    lc = r["scan_progress"]["orphan_keywords"]["last_complete"]
    assert lc["started_at"] and lc["at"] and lc["started_at"] <= lc["at"]


def test_the_all_diagnostics_job_keeps_the_place_in_the_kv_store_through_its_real_member(monkeypatch, tmp_path):
    """Steward 1's M1, end to end: the JOB builds the archive's real corpus-integrity.json member with the flag on, and the cursor
    lands in the app-state store under its key. (The slim debug bundle names that section as a member of its own, so the cursor
    wired there never ran.)"""
    from src.api.diagnostics import bundle
    from src.config.kv_store import kv_get_json, kv_set_json

    kv_set_json(integrity._CURSOR_KEY, {})
    real_members = bundle._all_diagnostics_members
    monkeypatch.setattr(bundle, "_all_diagnostics_members", lambda db: [m for m in real_members(db) if m[0] == "corpus-integrity.json"])
    monkeypatch.setattr(bundle, "_all_diagnostics_dir", lambda: tmp_path)

    class _Ctx:
        stopping = False

        def set_progress(self, **_k):
            pass

    res = bundle._all_diagnostics_worker(_Ctx())
    assert res.get("path"), res
    kept = kv_get_json(integrity._CURSOR_KEY)
    assert isinstance(kept, dict) and kept.get("foreign_key_violations"), "the job's member saved its place under the key"


def test_the_same_member_saves_nothing_outside_the_job(session, monkeypatch):
    """The synchronous GET /all and a plain GET build the member with the flag off: no store is even made."""
    from src.api.diagnostics import bundle

    _corpus(session)
    made = []

    class _Recording(MemStore):
        def __init__(self):
            super().__init__()
            made.append(self)

    monkeypatch.setattr(integrity, "KvCursorStore", _Recording)
    member = dict(bundle._all_diagnostics_members(session))["corpus-integrity.json"]
    out = member()
    assert out["orphan_keywords"] == 3 and made == [], "outside the job: the real member makes no cursor store, saves nothing"
    bundle._resuming_integrity(member)
    assert len(made) == 1 and made[0].saves == 1, "inside the job's flag: the place is saved once"
    assert bundle._RESUME_INTEGRITY.get() is False


def test_budget_a_quick_check_leaves_goes_back_to_a_check_still_partial(session, tiny_ranges, monkeypatch):
    """Steward 1's M2: one long walk and three quick checks. The long walk's first share runs out, the quick ones finish with
    most of the budget unused, and a second round gives it back: the figure is established, as main's single COUNT gave it."""
    _corpus(session, keywords=40, orphans=30)
    clock = {"t": 0.0}
    monkeypatch.setattr(integrity, "deadline_left_s", lambda _s: 100.0 - clock["t"])
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: clock["t"] >= 100.0)
    import types

    monkeypatch.setattr(integrity, "time", types.SimpleNamespace(monotonic=lambda: clock["t"]))
    real = integrity._scalar

    def costly(session_, sql, params=None):
        if params is not None and "lo" in params and sql.startswith("SELECT COUNT(*) FROM keywords k WHERE k.id > :lo"):
            clock["t"] += 2.0  # the orphan walk: about 40 one-row ranges x 2 s = 80 s, far more than its first share of 25 s
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", costly)
    r = integrity.corpus_integrity(session, sample=100)  # no cursor store: GET /integrity
    assert r["orphan_keywords"] == 30, r["scan_progress"]["orphan_keywords"]
    assert r["incomplete_checks"] == [] and r["timed_out"] is False
    assert "assembled_across_builds" not in r["scan_progress"]["orphan_keywords"], "continued in the same build, not across builds"


def test_a_partial_foreign_key_pass_lists_no_violating_tables_beside_its_none(session, tiny_ranges, monkeypatch):
    _corpus(session)
    session.add(Article(title="B", content="y", url="http://s.example/b", canonical_url="http://s.example/b", source_id=4_242, hash="h2"))
    session.commit()
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: False)
    real = integrity._fk_scan

    def cut(session_, saved, progress, stop_at=None, gens=None, begun=None):
        return real(session_, saved, progress, -1.0, gens, begun)  # a share already spent: the walk stops at once

    import types

    monkeypatch.setattr(integrity, "time", types.SimpleNamespace(monotonic=lambda: 0.0))
    monkeypatch.setattr(integrity, "_fk_scan", cut)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["foreign_key_violations"] is None and r["foreign_key_violation_tables"] == []


def test_a_completed_pass_takes_no_row_counts_for_its_marker(session, tiny_ranges, monkeypatch):
    """Steward 1's S2: the marker's row counts are taken only for a pass saved unfinished, never from a budget a finished pass used."""
    _corpus(session)
    seen: list[str] = []
    real = integrity._scalar

    def watching(session_, sql, params=None):
        seen.append(sql)
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", watching)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["incomplete_checks"] == []
    assert not [q for q in seen if "WHERE id <= :top" in q], "a pass that finished paid for no marker counts"


# --------------------------------------------------------------------------- #
#  A saved pass is resumed only while the corpus below its place is unchanged, and only when it is well formed (Steward 3's read)
# --------------------------------------------------------------------------- #
_DANGLING_ARTICLE = next(r for r in integrity._RANGE_SCANS if r[0] == "dangling_mentions_missing_article")


def _cut_dangling_pass(session, monkeypatch, saved):
    """Walk the missing-article check for ONE two-row range and stop, as a build whose budget ran out would."""
    calls = _budget_for_ranges(monkeypatch, 1)
    progress: dict = {}
    assert integrity._range_scan(session, *_DANGLING_ARTICLE, saved, progress) is None
    assert progress[_DANGLING_ARTICLE[0]]["next_id"] == 2 and calls["n"] == 1
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: False)
    monkeypatch.setattr(integrity, "_scalar", _REAL_SCALAR)


_REAL_SCALAR = integrity._scalar


def test_a_delete_below_the_place_restarts_the_pass_instead_of_reading_clean(session, tiny_ranges, monkeypatch):
    """False clean: an article deleted between builds leaves mentions dangling BELOW the cursor. Resumed, the pass never sees
    them (4 of 6); restarted, it counts all six."""
    _corpus(session, keywords=7, orphans=3, dangling=2)
    saved: dict = {}
    _cut_dangling_pass(session, monkeypatch, saved)
    session.query(Article).delete()
    session.commit()
    progress: dict = {}
    got = integrity._range_scan(session, *_DANGLING_ARTICLE, saved, progress)
    assert got == 6, progress
    assert progress[_DANGLING_ARTICLE[0]]["cursor"] == "restarted"
    assert "assembled_across_builds" not in progress[_DANGLING_ARTICLE[0]]


def test_a_corpus_epoch_bump_restarts_the_pass(session, tiny_ranges, monkeypatch):
    from datetime import UTC, datetime

    from src.database.models import DerivedMeta

    _corpus(session)
    saved: dict = {}
    _cut_dangling_pass(session, monkeypatch, saved)
    session.add(DerivedMeta(key="corpus_epoch", value="7", updated_at=datetime.now(UTC)))  # a re-index, prune, fold or restore
    session.commit()
    progress: dict = {}
    assert integrity._range_scan(session, *_DANGLING_ARTICLE, saved, progress) == 2
    assert progress[_DANGLING_ARTICLE[0]]["cursor"] == "restarted"


def test_rows_added_above_the_place_keep_the_pass_and_the_figure_says_it_spans_builds(session, tiny_ranges, monkeypatch):
    _corpus(session)
    store = MemStore()
    _budget_for_ranges(monkeypatch, 2)
    integrity.corpus_integrity(session, sample=100, cursor=store)
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: False)
    monkeypatch.setattr(integrity, "_scalar", _REAL_SCALAR)
    session.add(Article(title="C", content="z", url="http://s.example/c", canonical_url="http://s.example/c", source_id=1, hash="h3"))
    session.add(Keyword(term="late", normalized_term="late"))  # ingest between builds: above the pass's place
    session.commit()
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    p = r["scan_progress"]["orphan_keywords"]
    assert r["orphan_keywords"] == 3, "the pass walks to the id it began with; the new keyword is the next pass's"
    assert "cursor" not in p and p["assembled_across_builds"] is True
    assert p["last_complete"]["assembled_across_builds"] is True
    assert "orphan_keywords" in r["assembled_across_builds"]
    assert "assembled across builds: " in r["verdict"]
    assert "are exact" not in r["method"] and "assembled_across_builds" in r["method"]


def test_a_figure_from_one_build_does_not_say_it_spans_builds(session, tiny_ranges):
    _corpus(session)
    r = integrity.corpus_integrity(session, sample=100, cursor=MemStore())
    assert r["assembled_across_builds"] == [] and "assembled" not in r["verdict"]
    assert "assembled_across_builds" not in r["scan_progress"]["orphan_keywords"]


_GOOD = {"through_id": 7, "next_id": 4, "tally": 0, "step": 2, "started_at": "2026-11-08T00:00:00+00:00"}


@pytest.mark.parametrize(
    "pending",
    [
        {**_GOOD, "through_id": None},
        {**_GOOD, "next_id": "4"},
        {**_GOOD, "tally": 0.5},
        {**_GOOD, "tally": True},
        {**_GOOD, "started_at": "yesterday"},
        {**_GOOD, "through_id": 5, "next_id": 10},  # past its own end: would read complete having scanned nothing
        {**_GOOD, "next_id": 7},  # at its end: a finished pass is saved complete, never pending
        {**_GOOD, "through_id": 100},  # beyond the table's largest id
        {**_GOOD, "tally": -1},
        {**_GOOD, "next_id": -1},
        {**_GOOD, "tally": 5},  # more breaking rows than rows walked
        ["not", "a", "dict"],
    ],
)
def test_a_malformed_or_inconsistent_place_is_discarded_and_a_fresh_pass_counts(session, tiny_ranges, pending):
    _corpus(session)
    store = MemStore()
    store.state = {"orphan_keywords": {"pending": pending}}
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    p = r["scan_progress"]["orphan_keywords"]
    assert r["orphan_keywords"] == 3 and p["state"] == "complete", p
    assert p["cursor"] == "discarded" and "assembled_across_builds" not in p


@pytest.mark.parametrize(
    "pending",
    [
        {"tables": ["articles"], "started_at": "2026-11-08T00:00:00+00:00"},
        {"tables": {"articles": "0"}, "started_at": "2026-11-08T00:00:00+00:00"},
        {"tables": {"articles": -2}, "started_at": "2026-11-08T00:00:00+00:00"},
        {"tables": {"articles": 0}, "violating_tables": ["articles"], "started_at": "2026-11-08T00:00:00+00:00"},
        {"tables": {"articles": 0}, "violating_tables": "articles", "started_at": "2026-11-08T00:00:00+00:00"},
        {"tables": {"articles": 0}},
    ],
)
def test_a_malformed_foreign_key_place_is_discarded_not_a_crash(session, tiny_ranges, pending):
    _corpus(session)
    store = MemStore()
    store.state = {"foreign_key_violations": {"pending": pending}}
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    p = r["scan_progress"]["foreign_key_violations"]
    assert p["state"] == "complete" and p["cursor"] == "discarded", p
    assert r["foreign_key_violations"] is not None


def test_a_table_whose_foreign_key_check_fails_is_named_with_its_error_and_the_others_still_run(session, tiny_ranges, monkeypatch):
    from sqlalchemy.exc import OperationalError

    _corpus(session)
    real = session.execute

    def failing(stmt, *a, **k):
        if 'foreign_key_check("articles")' in str(stmt):
            raise OperationalError("PRAGMA", {}, Exception("database disk image is malformed"))
        return real(stmt, *a, **k)

    monkeypatch.setattr(session, "execute", failing)
    store = MemStore()
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    p = r["scan_progress"]["foreign_key_violations"]
    assert r["foreign_key_violations"] is None and "foreign_key_violations" in r["incomplete_checks"]
    assert p["state"] == "partial" and p["errors"] == [{"name": "articles", "error": "OperationalError"}]
    assert p["tables_checked"] == p["tables_total"] - 1, "every other table was still checked"
    assert "articles" not in store.state["foreign_key_violations"]["pending"]["tables"], "the failed table is tried again next build"


def test_an_already_counted_orphan_that_gains_a_mention_restarts_the_orphan_pass(session, tiny_ranges, monkeypatch):
    """False drift: keyword 5 is counted an orphan in build 1; ingest gives it a mention before build 2. The orphan pass watches the
    largest mention id, so it starts over and counts 2, not the resumed 3."""
    _corpus(session)
    store = MemStore()
    _budget_for_ranges(monkeypatch, 3)  # ranges of two: ids 1-2, 3-4, 5-6 -> keywords 5 and 6 counted as orphans
    first = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert first["scan_progress"]["orphan_keywords"]["tally_so_far"] == 2
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: False)
    monkeypatch.setattr(integrity, "_scalar", _REAL_SCALAR)
    session.add(KeywordMention(keyword_id=5, article_id=1, count=1))
    session.commit()
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    p = r["scan_progress"]["orphan_keywords"]
    assert r["orphan_keywords"] == 2 and p["cursor"] == "restarted", p
    assert "assembled_across_builds" not in p


def test_without_a_cursor_store_no_generation_marker_is_read(session, tiny_ranges, monkeypatch):
    """A plain GET keeps no pass, so it spends none of its budget counting rows for a marker it would throw away."""
    _corpus(session)
    seen: list[str] = []
    real = integrity._scalar

    def watching(session_, sql, params=None):
        seen.append(sql)
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", watching)
    integrity.corpus_integrity(session, sample=100)
    assert not [q for q in seen if "WHERE id <= :top" in q], seen


# --------------------------------------------------------------------------- #
#  The markers of the passes saved unfinished share ONE short deadline after the main budget (Steward 1's should-fix)
# --------------------------------------------------------------------------- #
def test_the_markers_of_every_unfinished_pass_share_one_deadline_and_a_cut_leaves_none(session, tiny_ranges, monkeypatch):
    """This runs inside the exclusive window after the 60 s budget, so collection is still paused: a 15 s deadline per pending
    pass would hold it 15 s more for each one. One deadline covers them all; the first count it cuts ends the loop, and every
    pass not finalized keeps no marker, so the next build starts it over."""
    import contextlib
    import types

    _corpus(session, keywords=40, orphans=30)
    clock = {"t": 0.0}
    monkeypatch.setattr(integrity, "deadline_left_s", lambda _s: 100.0 - clock["t"])
    monkeypatch.setattr(integrity, "deadline_expired", lambda _s: clock["t"] >= 100.0)
    monkeypatch.setattr(integrity, "time", types.SimpleNamespace(monotonic=lambda: clock["t"]))
    real = integrity._scalar

    def costly(session_, sql, params=None):
        if params is not None and "lo" in params:
            clock["t"] += 10.0  # every range of every walk: none of the three finishes inside the budget
        return real(session_, sql, params)

    monkeypatch.setattr(integrity, "_scalar", costly)
    deadlines: list = []
    real_deadline = integrity.statement_deadline

    @contextlib.contextmanager
    def recording(session_, seconds=None):
        deadlines.append(seconds)
        with real_deadline(session_, seconds=seconds):
            yield

    monkeypatch.setattr(integrity, "statement_deadline", recording)
    calls = {"n": 0}

    def cut(self, seed):
        calls["n"] += 1
        raise RuntimeError("interrupted")  # the 15 s ran out on the first pass's counts

    monkeypatch.setattr(integrity._Generations, "finalize", cut)
    store = MemStore()
    integrity.corpus_integrity(session, sample=100, cursor=store)
    pending = [e["pending"] for e in store.state.values() if isinstance(e, dict) and isinstance(e.get("pending"), dict)]
    assert len(pending) >= 2, store.state
    assert deadlines[-1] == 15 and deadlines.count(15) == 2, deadlines  # the FTS article count's own, and ONE for the markers
    assert calls["n"] == 1, "the passes after the cut were not tried under a fresh deadline each"
    assert all(p["generation"] is None for p in pending), "a pass without a finished marker is started over"


def test_a_count_the_deadline_cuts_is_not_tried_again_in_the_same_build(session, monkeypatch):
    _corpus(session)
    calls = {"n": 0}

    def cut(session_, sql, params=None):
        calls["n"] += 1
        raise RuntimeError("interrupted")

    gens = integrity._Generations(session)
    monkeypatch.setattr(integrity, "_scalar", cut)
    with pytest.raises(RuntimeError):
        gens._read({"articles": 1, "keywords": 7})
    assert gens._read({"articles": 1, "keywords": 7}) is None and calls["n"] == 1


def test_a_pass_stamped_later_than_this_build_still_has_its_corpus_checked(session, tiny_ranges, monkeypatch):
    """Steward 1's nit: "began in this build" is the in-memory record of the passes this build started, never a clock compare.
    A pass an earlier build saved with a timestamp ahead of this build's clock (a clock set back between builds) is checked
    against its marker like any other, and an article deleted below its place restarts it."""
    _corpus(session, keywords=7, orphans=3, dangling=2)
    saved: dict = {}
    _cut_dangling_pass(session, monkeypatch, saved)
    pend = saved[_DANGLING_ARTICLE[0]]["pending"]
    pend["generation"] = integrity._Generations(session).finalize(pend["generation"])
    pend["started_at"] = "2999-01-01T00:00:00+00:00"
    session.query(Article).delete()
    session.commit()
    store = MemStore()
    store.state = saved
    r = integrity.corpus_integrity(session, sample=100, cursor=store)
    assert r[_DANGLING_ARTICLE[0]] == 6, r["scan_progress"][_DANGLING_ARTICLE[0]]
    assert r["scan_progress"][_DANGLING_ARTICLE[0]]["cursor"] == "restarted"
