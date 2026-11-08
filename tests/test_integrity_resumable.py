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


def test_only_the_all_diagnostics_build_saves_the_cursor_and_a_get_saves_nothing():
    import inspect

    from src.api.diagnostics import bundle

    src = inspect.getsource(bundle)
    assert "_KvCursorStore() if _RESUME_INTEGRITY.get() else None" in src
    assert "_resuming_integrity(lambda: debug_bundle(db=db, slim=True))" in src
    assert bundle._RESUME_INTEGRITY.get() is False, "a GET of /debug-bundle runs with the flag off"
    seen = []
    bundle._resuming_integrity(lambda: seen.append(bundle._RESUME_INTEGRITY.get()))
    assert seen == [True] and bundle._RESUME_INTEGRITY.get() is False
