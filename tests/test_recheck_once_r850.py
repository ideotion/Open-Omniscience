"""R850 / R851 (row 449, amending R844): one re-check for each source that link density alone disqualified.

Nothing stored says why a source was disqualified, so the sources are CHOSEN BY RECOMPUTING the criteria, read-only, from
their stored articles with the same ``flag_criteria`` call a re-check runs. Too few stored articles to recompute is "not
determined": the source stays on its ladder. A chosen source is made due ONCE through ``select_due_disqualified``, so it is
judged in an ordinary pass (that pass's consent, transport, pacing and per-host limits; nothing while qualification is off),
and the selection itself runs inside a pass from the cohort the pass froze, once per install.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from src.analytics import source_audit as sa
from src.catalog import qualification as q
from src.database.models import Base, Source, SourceQualificationAttempt
from tests._app_engine import app_sqlite_engine

NOW = datetime(2026, 11, 28, tzinfo=UTC)
JUDGED = NOW - timedelta(days=3)          # well inside the first ladder step: not due on its own


@pytest.fixture(autouse=True)
def _no_pause_memory(monkeypatch):
    monkeypatch.setattr(q, "_recheck_once_paused_at", None)


@pytest.fixture()
def db():
    engine = app_sqlite_engine(":memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def store(monkeypatch):
    data: dict[str, dict] = {}
    import src.config.kv_store as kv

    monkeypatch.setattr(kv, "kv_get_json", lambda key: copy.deepcopy(data.get(key)))
    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: copy.deepcopy(data.get(key)))
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: data.__setitem__(key, copy.deepcopy(obj)))
    return data


def _disqualified(db, domain):
    s = Source(name=domain, domain=domain, status=q.STATUS_DISQUALIFIED, enabled=True)
    db.add(s)
    db.commit()
    db.add(SourceQualificationAttempt(source_id=s.id, attempted_at=JUDGED, verdict=q.STATUS_DISQUALIFIED,
                                      criteria_version="oo-source-qualification-3"))
    db.commit()
    return s


def _m(sid, *, n=200, link=0.0, path=0.0, short=0.1):
    return {"domain": f"s{sid}.example", "language": "en", "region": "gb", "article_count": n, "dominant_lang": "en",
            "outlier_rate": 0.1, "pathology_rate": path, "pathology_articles": round(path * n), "link_density_rate": link,
            "link_dense_articles": round(link * n), "language_mismatch_rate": 0.0, "short_article_rate": short,
            "furniture_share": 0.1}


def _frozen():
    return {"min_articles": 1, "cohort_cut": None, "cohort": {"baselines": {}, "lang_short_cut": {}},
            "token": "t", "articles": 0, "sources": 0, "furniture_df": None}


@pytest.fixture()
def four(db, monkeypatch):
    """Four disqualified sources: link density only, pathology too, nothing flagged now, and one with 3 articles."""
    link, both, clean, thin = (_disqualified(db, d) for d in ("link.example", "both.example", "clean.example", "thin.example"))
    cohort = {1000 + i: _m(1000 + i) for i in range(40)}  # large enough that two link-dense sources stay in the tail

    def fake_scoped(session, ids, frozen, **_kw):
        per = {link.id: _m(link.id, link=0.6), both.id: _m(both.id, link=0.6, path=0.6),
               clean.id: _m(clean.id), thin.id: _m(thin.id, n=3, link=1.0)}
        return {sid: m for sid, m in {**per, **cohort}.items() if sid in ids or sid in cohort}

    real_flag = sa.flag_criteria
    monkeypatch.setattr(sa, "scoped_metrics", fake_scoped)
    # the cohort rides along so the tail has something to compare with, as it does in a real pass
    monkeypatch.setattr(sa, "flag_criteria", lambda per, **kw: real_flag({**cohort, **per}, cohort_floor=8, min_articles=20))
    return link, both, clean, thin


def test_the_selection_chooses_link_density_alone_and_counts_the_thin_as_not_determined(db, four):
    link, both, clean, thin = four
    sel = q.select_link_density_only(db, _frozen())
    assert sel["chosen"] == [link.id], "only the source whose ONLY extraction-failure criterion is link density"
    assert sel["not_determined"] == [thin.id], "too few stored articles to recompute: stays on its ladder"


def test_the_selection_writes_nothing(db, four):
    writes: list[str] = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _watch(conn, cursor, statement, *_a):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
            writes.append(statement)

    before = [(s.id, s.status, s.enabled, s.qualified_at) for s in db.query(Source).order_by(Source.id)]
    attempts = db.query(SourceQualificationAttempt).count()
    q.select_link_density_only(db, _frozen())
    db.commit()
    assert writes == [], "no article, attempt row or stamp is written by the recompute"
    assert [(s.id, s.status, s.enabled, s.qualified_at) for s in db.query(Source).order_by(Source.id)] == before
    assert db.query(SourceQualificationAttempt).count() == attempts


def test_a_chosen_source_is_due_once_ahead_of_its_ladder_then_back_on_it(db, store, four):
    link, both, clean, thin = four
    assert q.select_due_disqualified(db, now=NOW, limit=10) == [], "nothing is due on its ladder yet"
    q.store_recheck_once(q.select_link_density_only(db, _frozen()), now=NOW)
    assert [s.id for s in q.select_due_disqualified(db, now=NOW, limit=10)] == [link.id]
    q.record_recheck_once_tries({link.id}, now=NOW)
    assert q.select_due_disqualified(db, now=NOW, limit=10) == [], "once: after its re-check it is on its ladder again"
    assert q.recheck_once_counts() == {
        "selected": True, "selection": q.RECHECK_ONCE_SELECTION, "label": "chosen by recomputing from stored articles",
        "selected_at": "2026-11-28T00:00:00", "chosen": 1, "rechecked": 1, "not_determined": 1,
    }


def test_the_same_rule_never_chooses_again_and_a_requalified_source_is_not_forced(db, store, four):
    link = four[0]
    q.store_recheck_once(q.select_link_density_only(db, _frozen()), now=NOW)
    q.record_recheck_once_tries({link.id}, now=NOW)
    stored = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW + timedelta(days=1))
    assert stored["chosen"] == 1 and stored["rechecked"] == 1, "a stored selection by today's rule is not run again"
    # a chosen source that is no longer disqualified (re-qualified some other way) is not made due
    store[q.RECHECK_ONCE_KEY]["entries"][str(link.id)]["tried_at"] = None
    link.status = q.STATUS_QUALIFIED
    db.commit()
    assert q.pending_recheck_once(db) == []


def test_an_unreadable_selection_makes_nothing_due(db, monkeypatch, four):
    import src.config.kv_store as kv

    def boom(_key):
        raise RuntimeError("locked")

    monkeypatch.setattr(kv, "kv_get_json", boom)
    assert q.pending_recheck_once(db) == []
    assert q.select_due_disqualified(db, now=NOW, limit=10) == []


def test_a_paused_selection_stores_nothing_and_is_tried_again_later(db, store, monkeypatch, four):
    from src.analytics import source_quality as sq

    def paused(*_a, **_kw):
        raise sq.ScanPaused("memory")

    monkeypatch.setattr(sa, "scoped_metrics", paused)
    out = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    assert out["selected"] is False and q.RECHECK_ONCE_KEY not in store


def test_an_idle_install_chooses_and_judges_within_one_pass(db, store, four):
    """The case R850 exists for: no new candidates and nothing due on the ladder. One ordinary pass (no fetcher here, so
    no network; the cohort injected) makes the choice and judges the chosen source within its own re-check budget."""
    link = four[0]
    assert q.select_unqualified(db, limit=10) == [] and q.select_due_disqualified(db, now=NOW, limit=10) == []
    out = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    assert out["evaluated"] == 1
    tried = db.query(SourceQualificationAttempt).filter(SourceQualificationAttempt.source_id == link.id).count()
    assert tried == 2, "its one re-check was judged in this pass"
    assert out["recheck_once"]["chosen"] == 1 and out["recheck_once"]["rechecked"] == 1
    again = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    assert again == {"enabled": True, "evaluated": 0}, "once: the next pass has nothing to take"


def test_the_real_recompute_reads_and_writes_nothing():
    """The same, with nothing faked: the real cohort freeze and the real scoped read over stored articles."""
    from tests.test_source_qualification import (
        _add_candidate_with_articles,
        _engine_session,
        _seed_healthy_en_cohort,
    )

    s = _engine_session()
    _seed_healthy_en_cohort(s)
    thin = _add_candidate_with_articles(s, domain="thin.example", status=q.STATUS_DISQUALIFIED, pathology=False)
    frozen = sa.frozen_cohort(s, min_articles=q.TRIAL_MIN_ARTICLES)
    s.commit()
    writes: list[str] = []

    @event.listens_for(s.get_bind(), "before_cursor_execute")
    def _watch(conn, cursor, statement, *_a):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP"):
            writes.append(statement)

    sel = q.select_link_density_only(s, frozen)
    s.commit()
    assert writes == []
    assert sel == {"chosen": [], "not_determined": [thin.id]}, "three stored articles are too few to recompute"


def _choose(store, *sources):
    store[q.RECHECK_ONCE_KEY] = {"selection": q.RECHECK_ONCE_SELECTION, "label": q.RECHECK_ONCE_LABEL,
                                 "selected_at": "2026-11-28T00:00:00", "chosen": len(sources), "not_determined": 0,
                                 "entries": {str(s.id): {"tried_at": None} for s in sources}}


def test_the_chosen_go_first_only_within_the_pass_s_own_re_check_budget(db, store):
    """Never on top of qualification_recheck_per_pass: with one re-check slot a pass judges one chosen source, and the
    other stays chosen for the next pass."""
    a, b = _disqualified(db, "a.example"), _disqualified(db, "b.example")
    _choose(store, a, b)
    one = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=1, now=NOW, cohort_provider=_frozen)
    assert one["evaluated"] == 1
    assert q.pending_recheck_once(db) != [] and len(q.pending_recheck_once(db)) == 1, "the one not reached stays chosen"
    two = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=1, now=NOW, cohort_provider=_frozen)
    assert two["evaluated"] == 1 and q.pending_recheck_once(db) == []
    assert q.recheck_once_counts()["rechecked"] == 2


def test_nothing_is_taken_while_qualification_is_off(db, store):
    a = _disqualified(db, "a.example")
    _choose(store, a)
    out = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=0, now=NOW, cohort_provider=_frozen)
    assert out == {"enabled": False}
    assert q.pending_recheck_once(db) == [a.id]
    assert db.query(SourceQualificationAttempt).filter(SourceQualificationAttempt.source_id == a.id).count() == 1


def test_a_paused_selection_waits_before_it_is_asked_again(db, store, monkeypatch, four):
    from src.analytics import source_quality as sq

    calls = []

    def paused(*_a, **_kw):
        calls.append(1)
        raise sq.ScanPaused("memory")

    monkeypatch.setattr(sa, "scoped_metrics", paused)
    q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    again = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    assert len(calls) == 1 and again["selected"] is False, "the same read is not asked for on the next pass"


def test_the_recompute_reads_in_chunks_of_a_pass_s_own_size(db, monkeypatch):
    for i in range(q._RECHECK_ONCE_CHUNK * 2 + 1):
        db.add(Source(name=f"d{i}.example", domain=f"d{i}.example", status=q.STATUS_DISQUALIFIED, enabled=True))
    db.commit()
    sizes = []
    monkeypatch.setattr(sa, "scoped_metrics", lambda session, ids, frozen, **kw: sizes.append(len(ids)) or {})
    out = q.select_link_density_only(db, _frozen())
    assert sizes == [q._RECHECK_ONCE_CHUNK, q._RECHECK_ONCE_CHUNK, 1]
    assert len(out["not_determined"]) == q._RECHECK_ONCE_CHUNK * 2 + 1


def test_the_queue_view_carries_the_counts_the_summary_shows(db, store):
    a = _disqualified(db, "a.example")
    _choose(store, a)
    rc = q.qualification_queue(db, now=NOW)["rechecks"]
    assert rc["recheck_once"]["selected"] is True and rc["recheck_once"]["chosen"] == 1
    assert rc["recheck_once"]["rechecked"] == 0 and rc["recheck_once"]["not_determined"] == 0


def test_a_restore_never_brings_another_install_s_marker():
    """The marker lives in app_state, which a merge restore never adopts (local wins entirely) and which is not one of the
    settings carried over the swap, so a backup from another install cannot mark this one's selection done."""
    from src.backup import merge

    assert "app_state" in merge._MERGE_IGNORED
    assert not q.RECHECK_ONCE_KEY.startswith(merge._CARRIED_SETTINGS_KEYS)


def test_the_summary_says_both_counts_in_every_language():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "src" / "static" / "app-ai-tools.js").read_text(encoding="utf-8")
    frame = ("{rechecked} of {chosen} sources that link density alone disqualified have been re-checked once; "
             "{undetermined} could not be determined (too few stored articles).")
    assert frame in js and "rc.recheck_once.not_determined" in js
    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        d = json.loads((root / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for var in ("{rechecked}", "{chosen}", "{undetermined}"):
            assert var in d[frame], (lang, var)


def test_an_odd_stored_key_never_breaks_the_pass(db, store):
    a = _disqualified(db, "a.example")
    _choose(store, a)
    store[q.RECHECK_ONCE_KEY]["entries"]["²"] = {"tried_at": None}  # passes str.isdigit(), fails int()
    store[q.RECHECK_ONCE_KEY]["entries"]["x"] = "junk"
    assert q.pending_recheck_once(db) == [a.id]


def test_an_unreadable_list_is_never_taken_for_none_stored(db, store, monkeypatch, four):
    """A read that fails must not rerun the selection, which would rebuild the list and drop its tried stamps."""
    import src.config.kv_store as kv

    def locked(_key):
        raise RuntimeError("database is locked")

    ran = []
    monkeypatch.setattr(kv, "kv_get_json_strict", locked)
    monkeypatch.setattr(q, "select_link_density_only", lambda *a, **k: ran.append(1) or {"chosen": [], "not_determined": []})
    out = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    assert ran == [] and out["selected"] is False


def test_a_source_held_off_site_is_never_chosen(db, four):
    from src.catalog import off_site

    link = four[0]
    db.add(SourceQualificationAttempt(source_id=link.id, attempted_at=NOW, verdict=q.STATUS_DISQUALIFIED,
                                      criteria_version=off_site.CRITERIA_VERSION))
    db.commit()
    assert q.select_link_density_only(db, _frozen())["chosen"] == []


def test_any_failed_selection_waits_not_only_a_pause(db, monkeypatch, four):
    """A store that keeps refusing the write must not make every pass pay the freeze and the read again."""
    import src.config.kv_store as kv

    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: None)
    writes = []

    def refuse(key, obj):
        writes.append(key)
        raise OSError("settings cannot be saved in this session")

    monkeypatch.setattr(kv, "kv_set_json", refuse)
    first = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    assert first["selected"] is False and len(writes) == 1
    assert q._recheck_once_owed() is False, "the next pass waits"
    again = q._select_recheck_once_if_owed(db, _frozen(), should_pause=None, now=NOW)
    assert again["selected"] is False and len(writes) == 1


def test_a_cut_frozen_at_another_threshold_stores_no_choice(db, store, four):
    wrong = lambda: {**_frozen(), "min_articles": 20}  # noqa: E731
    q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=wrong)
    assert q.RECHECK_ONCE_KEY not in store, "no choice from another baseline (that cut is refused once a pass judges)"


def test_the_pass_that_chose_reports_it_even_when_it_returns_early(db, store, monkeypatch, four):
    monkeypatch.setattr(q, "select_due_disqualified", lambda *a, **kw: [])  # nothing to judge: the early return
    out = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    assert out["evaluated"] == 0 and out["recheck_once"]["chosen"] == 1
    again = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_frozen)
    assert again == {"enabled": True, "evaluated": 0}, "any other pass keeps its old result shape"


def test_the_ride_along_still_freezes_after_its_trial_fetches(db, store, monkeypatch, four):
    """Without a provider the baseline judged against is frozen after the trial fetches, as before R850; the early freeze
    serves only the one-time choice, so verdicts on that pass are the ones the old order gave."""
    freezes = []
    monkeypatch.setattr(sa, "frozen_cohort", lambda session, **kw: freezes.append(kw) or _frozen())
    out = q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW)
    assert out["evaluated"] == 1 and out["recheck_once"]["rechecked"] == 1
    assert len(freezes) == 2, "one for the choice, one after the trial fetches"


def test_a_freeze_that_fails_never_fails_a_pass_with_nothing_to_judge(db, store, monkeypatch, four):
    """Before R850 a pass with no candidates never froze the cohort; the extra freeze for the one-time choice
    must not turn any failure of its own into a failed pass. It waits, like a pause."""
    def broken(*_a, **_kw):
        raise RuntimeError("the freeze could not read the corpus")

    monkeypatch.setattr(sa, "frozen_cohort", broken)
    out = q.run_qualification_pass(db, None, per_pass=1, recheck_per_pass=1, now=NOW)
    assert out == {"enabled": True, "evaluated": 0}
    assert q._recheck_once_owed() is False and q.RECHECK_ONCE_KEY not in store


def test_nothing_disqualified_never_freezes_for_the_choice(db, store, monkeypatch):
    """A pass with nothing to judge never paid for a whole-corpus freeze before R850; with nothing disqualified there
    is nothing to choose either, so it still does not, and no wait is set (the next pass looks again)."""
    freezes = []
    monkeypatch.setattr(sa, "frozen_cohort", lambda session, **kw: freezes.append(kw) or _frozen())
    q.run_qualification_pass(db, None, per_pass=1, recheck_per_pass=1, now=NOW)
    assert freezes == [] and q._recheck_once_owed() is True and q.RECHECK_ONCE_KEY not in store


def test_a_cut_this_choice_cannot_use_waits_instead_of_freezing_every_pass(db, store, four):
    calls = []
    wrong = lambda: calls.append(1) or {**_frozen(), "min_articles": 20}  # noqa: E731
    for _ in range(3):
        q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=wrong)
    assert calls == [1], "the unusable cut is asked for once, then the choice waits"
    assert q._recheck_once_owed() is False and q.RECHECK_ONCE_KEY not in store
