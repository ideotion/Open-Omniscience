"""A shipped stoplist change reaches the stored top keywords (R111 step T3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What must hold, and is pinned here:

* the fingerprint of the shipped list is stable across order and moves with one word;
* a recompute rewrites the three ``top_keyword_*`` columns of exactly the articles whose top set held
  a hidden word, including a hidden word that is a NON-lowest member of a tie, and leaves every
  other article, every mention row and every ``updated_at`` alone;
* an article is handled once however many hidden words it holds, an article whose columns already
  equal the recomputed ones is not written, and a NULL (never computed) stays NULL;
* the fingerprint is recorded only after the last chunk; a stop, a guard or a failure leaves it
  unrecorded and the next pass resumes from the cursor to the same end state;
* a cursor made under another list is never resumed;
* the failure text goes through ``engine_text`` and no traceback is logged;
* the chunk size moves with the measured write-window hold and stays inside its bounds;
* the Home cache goes stale on a different list and not on an equal one, under the marker
  repair's throttle.
"""

from __future__ import annotations

import ast
import contextlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.analytics.stoplist_recompute as sr
from src.analytics.store import top_keyword_of
from src.database.models import Article, Base, DerivedMeta, Keyword, KeywordMention, Source

_MT = KeywordMention.__table__
_STAMP = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture
def env(monkeypatch, tmp_path):
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, future=True)

    @contextlib.contextmanager
    def scope():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr("src.database.session.session_scope", scope)
    monkeypatch.setattr(sr, "_state_path", lambda: tmp_path / "stoplist_recompute.json")
    monkeypatch.setattr(sr, "_guard_reason", lambda: None)
    monkeypatch.setattr(sr, "_fp_memo", None)
    words = frozenset({"hid1", "hid2"})
    monkeypatch.setattr("src.analytics.extract.global_stopwords", lambda: words)
    with scope() as s:
        s.add(Source(name="S", domain="s.test"))

    class E:
        engine = eng
        session = staticmethod(scope)
        stoplist = words

        @staticmethod
        def set_words(new):
            monkeypatch.setattr("src.analytics.extract.global_stopwords", lambda: frozenset(new))
            monkeypatch.setattr(sr, "_fp_memo", None)

    return E


def _keyword(s, term):
    k = Keyword(term=term, normalized_term=term, language="en")
    s.add(k)
    s.flush()
    return k.id


def _article(s, h, counts, *, stored="auto"):
    """An article with ``counts`` {keyword_id: count} and stored top columns (``auto`` = what
    ``index_article`` stored from ALL its mentions, ``None`` = never computed)."""
    top = top_keyword_of(counts) if stored == "auto" else (stored or (None, None, None))
    a = Article(url=f"https://s.test/{h}", canonical_url=f"https://s.test/{h}", source_id=1,
                title="T", content="body", hash=h, language="en",
                created_at=datetime.now(UTC), updated_at=_STAMP,
                top_keyword_id=top[0], top_keyword_count=top[1], top_keyword_tied_n=top[2])
    s.add(a)
    s.flush()
    for kid, c in counts.items():
        s.execute(_MT.insert().values(keyword_id=kid, article_id=a.id, count=c, first_offset=0))
    return a.id


def _tops(env):
    with env.session() as s:
        return {
            a.hash: (a.top_keyword_id, a.top_keyword_count, a.top_keyword_tied_n, a.updated_at)
            for a in s.query(Article)
        }


def _mentions(env):
    with env.session() as s:
        return sorted(tuple(r) for r in s.execute(select(_MT.c.article_id, _MT.c.keyword_id, _MT.c.count)))


def _world(env):
    """Keyword ids: h1 < a < h2 < b < c, plus one article per shape."""
    with env.session() as s:
        h1, a, h2, b, c = (_keyword(s, t) for t in ("hid1", "aa", "hid2", "bb", "cc"))
        ids = {
            "lone_top": _article(s, "lone_top", {h1: 5, a: 2}),
            "tie_nonlowest": _article(s, "tie_nonlowest", {a: 3, h2: 3}),
            "tie_lowest": _article(s, "tie_lowest", {h1: 3, b: 3}),
            "only_hidden": _article(s, "only_hidden", {h1: 2}),
            "no_hidden": _article(s, "no_hidden", {a: 4, b: 1}),
            "hidden_below": _article(s, "hidden_below", {a: 5, h1: 1}),
            "never_computed": _article(s, "never_computed", {h1: 4, a: 1}, stored=None),
            "both_hidden": _article(s, "both_hidden", {h1: 6, h2: 6, c: 2}),
            "already_clean": _article(s, "already_clean", {h1: 4, a: 4, b: 1}, stored=(None, None, None)),
        }
    # `already_clean`: a state a previous run left (the hidden word already out of the columns)
    with env.session() as s:
        s.execute(
            Article.__table__.update()
            .where(Article.__table__.c.id == ids["already_clean"])
            .values(top_keyword_id=a, top_keyword_count=4, top_keyword_tied_n=1,
                    updated_at=_STAMP)
        )
    return {"h1": h1, "a": a, "h2": h2, "b": b, "c": c, **ids}


def _assert_final(after, before, w):
    """The end state every walk of the shipped list must reach, whatever its chunking."""
    assert after["lone_top"][:3] == (w["a"], 2, 1)  # the next best, the tie is gone
    assert after["tie_nonlowest"][:3] == (w["a"], 3, 1)  # a NON-lowest hidden tie member: tied_n drops
    assert after["tie_lowest"][:3] == (w["b"], 3, 1)  # the representative was hidden: the other takes over
    assert after["only_hidden"][:3] == (None, None, None)  # no top keyword, as an empty map answers
    assert after["both_hidden"][:3] == (w["c"], 2, 1)
    for h in ("no_hidden", "hidden_below", "never_computed", "already_clean"):
        assert after[h] == before[h], h
    assert {v[3] for v in after.values()} == {_STAMP}, "updated_at is never stamped by this pass"


# ---------------------------------------------------------------------------------- fingerprint


def test_the_fingerprint_is_stable_across_order_and_moves_with_one_word(env):
    one = sr.current_fingerprint()
    env.set_words(["hid2", "hid1"])
    assert sr.current_fingerprint() == one
    env.set_words(["hid1", "hid2", "hid3"])
    assert sr.current_fingerprint() != one
    assert len(one) == 64


def test_a_fresh_install_records_the_fingerprint_after_a_run_that_finds_nothing(env):
    assert sr.needs_run()
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["updated"] == 0 and out["scanned"] == 0
    assert not sr.needs_run()
    assert sr.maybe_recompute_top_keywords() == {"skipped": "current"}


# ------------------------------------------------------------------------------- what it writes


def test_the_top_columns_follow_the_shipped_list_and_nothing_else_moves(env):
    w = _world(env)
    mentions_before = _mentions(env)
    before = _tops(env)
    assert before["tie_nonlowest"][:3] == (w["a"], 3, 2)

    out = sr.maybe_recompute_top_keywords()

    assert out["complete"] is True
    _assert_final(_tops(env), before, w)
    assert _mentions(env) == mentions_before, "the raw counts every other reader uses are untouched"
    assert out["updated"] == 5 and out["to_none"] == 1
    assert out["already_clean"] == 1 and out["never_computed"] == 1 and out["top_unaffected"] == 1


def test_an_article_with_two_hidden_words_is_handled_once(env):
    _world(env)
    out = sr.maybe_recompute_top_keywords()
    # both_hidden is reached from hid1 and from hid2; only the walk of its lowest one handles it
    assert out["handled_later"] >= 1
    assert out["updated"] == 5


def test_a_second_run_on_the_same_list_does_nothing_and_a_grown_list_hides_the_new_word(env):
    w = _world(env)
    sr.maybe_recompute_top_keywords()
    assert sr.maybe_recompute_top_keywords() == {"skipped": "current"}
    env.set_words(["hid1", "hid2", "aa"])  # the next update hides aa too
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True
    tops = _tops(env)
    assert tops["no_hidden"][:3] == (w["b"], 1, 1), "aa was this article's top word"
    assert tops["lone_top"][:3] == (None, None, None), "nothing but hidden words is left"


@pytest.mark.parametrize("chunk", [1, 2, 1000])
def test_the_chunk_size_changes_the_walk_not_the_answer(env, monkeypatch, chunk):
    w = _world(env)
    before = _tops(env)
    monkeypatch.setattr(sr, "START_CHUNK", chunk)
    monkeypatch.setattr(sr, "MIN_CHUNK", chunk)
    monkeypatch.setattr(sr, "MAX_CHUNK", chunk)
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True
    _assert_final(_tops(env), before, w)
    assert (out["chunks"] > 3) if chunk == 1 else (out["chunks"] >= 1)


# ----------------------------------------------------------------------- resumption and its guard


def test_the_fingerprint_is_recorded_last_and_a_resume_reaches_the_same_end_state(env, monkeypatch):
    w = _world(env)
    before = _tops(env)
    monkeypatch.setattr(sr, "START_CHUNK", 1)
    monkeypatch.setattr(sr, "MIN_CHUNK", 1)
    monkeypatch.setattr(sr, "MAX_CHUNK", 1)
    calls = {"n": 0}

    def stop_after_three():
        calls["n"] += 1
        return calls["n"] > 3

    first = sr.maybe_recompute_top_keywords(should_stop=stop_after_three)
    assert first["complete"] is False and first["stopped_by"] == "stop"
    assert sr.needs_run(), "a stopped pass must not record the fingerprint"
    assert sr.incomplete()
    with env.session() as s:
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is not None
    assert _tops(env) != before, "the first chunks were committed"

    second = sr.maybe_recompute_top_keywords()
    assert second["complete"] is True and second["resumed_at"] is not None
    assert not sr.needs_run() and not sr.incomplete()
    with env.session() as s:
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is None, "a finished walk leaves no cursor behind"
    _assert_final(_tops(env), before, w)


def test_a_cursor_made_under_another_list_is_not_resumed(env):
    with env.session() as s:
        _cursor = sr._cursor_set
        _cursor(s, "older-list", 99, 99)
    with env.session() as s:
        assert sr._cursor_get(s, sr.current_fingerprint()) == (0, 0)
        assert sr._cursor_get(s, "older-list") == (99, 99)


def test_a_guard_keeps_a_chunk_from_starting_and_nothing_is_written(env, monkeypatch):
    _world(env)
    before = _tops(env)
    monkeypatch.setattr(sr, "_guard_reason", lambda: "storage_pressure")
    out = sr.maybe_recompute_top_keywords()
    assert out == {"skipped": "storage_pressure", "complete": False}
    assert _tops(env) == before and sr.needs_run()


def test_a_guard_that_engages_mid_walk_stops_at_a_chunk_boundary(env, monkeypatch):
    _world(env)
    monkeypatch.setattr(sr, "START_CHUNK", 1)
    monkeypatch.setattr(sr, "MIN_CHUNK", 1)
    monkeypatch.setattr(sr, "MAX_CHUNK", 1)
    seen = {"n": 0}

    def guard():
        seen["n"] += 1
        return "memory_pressure" if seen["n"] > 3 else None

    monkeypatch.setattr(sr, "_guard_reason", guard)
    # the entry check is call 1; the loop's checks follow
    out = sr.maybe_recompute_top_keywords()
    assert out["stopped_by"] == "memory_pressure" and out["complete"] is False
    assert sr.needs_run()


def test_the_soft_budget_stops_the_pass_and_the_next_one_finishes(env, monkeypatch):
    from types import SimpleNamespace

    w = _world(env)
    before = _tops(env)
    monkeypatch.setattr(sr, "START_CHUNK", 1)
    monkeypatch.setattr(sr, "MIN_CHUNK", 1)
    monkeypatch.setattr(sr, "MAX_CHUNK", 1)
    ticks = iter(range(0, 10_000, 5))
    monkeypatch.setattr(sr, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    first = sr.maybe_recompute_top_keywords(budget_s=8)
    assert first["stopped_by"] == "budget" and first["complete"] is False
    second = sr.maybe_recompute_top_keywords(budget_s=0)  # 0 = unbounded
    assert second["complete"] is True
    _assert_final(_tops(env), before, w)


# --------------------------------------------------------------------------------- failure text


def test_a_failure_is_recorded_without_the_passphrase_and_without_a_traceback(env, monkeypatch, caplog):
    secret = "hunter2-s3cret"
    monkeypatch.setenv("OO_DB_PASSPHRASE", secret)

    def boom(*_a, **_k):
        raise RuntimeError(f"[SQL: PRAGMA key = '{secret}'] failed")

    monkeypatch.setattr(sr, "_run", boom)
    with caplog.at_level(logging.DEBUG, logger="analytics.stoplist_recompute"):
        out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is False
    assert secret not in out["skipped"] and out["skipped"].startswith("RuntimeError:")
    assert sr.needs_run(), "a failed pass records nothing"
    for rec in caplog.records:
        assert secret not in rec.getMessage()
        assert rec.exc_info is None


def test_the_module_never_logs_a_traceback_and_names_no_write_model_of_the_mentions():
    tree = ast.parse(Path(sr.__file__).read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "exc_info":
            pytest.fail("an exc_info log carries engine text past the passphrase scrub")
        if isinstance(node, ast.Name) and node.id == "KeywordMention":
            pytest.fail("the mentions are read through the read seam only")


# ------------------------------------------------------------------------------------ chunk size


def test_the_chunk_size_follows_the_measured_write_window_hold():
    target = sr.TARGET_HOLD_S
    assert sr.next_chunk_size(200, target * 2) == 100, "held too long: halve"
    assert sr.next_chunk_size(200, target * 0.1) == 400, "held far under: double"
    assert sr.next_chunk_size(200, target * 0.75) == 200, "near the target: keep"
    assert sr.next_chunk_size(sr.MIN_CHUNK, target * 9) == sr.MIN_CHUNK
    assert sr.next_chunk_size(sr.MAX_CHUNK, target * 0.01) == sr.MAX_CHUNK


# -------------------------------------------------------------------------------- the Home cache


@pytest.fixture
def home(monkeypatch):
    from src.briefing import service

    monkeypatch.setattr(service, "_has_headroom_for_a_repair", lambda: True)
    monkeypatch.setattr(service, "_scheduler_is_busy_with_the_whole_corpus", lambda: False)
    monkeypatch.setitem(service._marker_retry, "at", None)
    monkeypatch.setattr(service, "_stoplist_fingerprint", lambda: "list-now")
    return service


def test_a_cache_made_under_another_list_is_stale_and_one_made_under_this_list_is_not(home):
    assert home._stoplist_wants_refresh({"stoplist": "list-before"}) is True
    assert home._stoplist_wants_refresh({}) is True, "a cache written before the field is refreshed once"
    assert home._stoplist_wants_refresh({"stoplist": "list-now"}) is False


def test_the_refresh_for_a_new_list_is_throttled_like_the_marker_repair(home, monkeypatch):
    monkeypatch.setitem(home._marker_retry, "at", 1000.0)
    monkeypatch.setattr(home, "_monotonic", lambda: 1000.0 + home._MARKER_RETRY_S - 1)
    assert home._stoplist_wants_refresh({"stoplist": "list-before"}) is False, "a refresh just ended"
    monkeypatch.setattr(home, "_monotonic", lambda: 1000.0 + home._MARKER_RETRY_S)
    assert home._stoplist_wants_refresh({"stoplist": "list-before"}) is True


def test_an_unreadable_list_never_makes_the_feed_stale(home, monkeypatch):
    monkeypatch.setattr(home, "_stoplist_fingerprint", lambda: None)
    assert home._stoplist_wants_refresh({"stoplist": "anything"}) is False


# ------------------------------------------------------------------------------ the maintenance


def test_the_idle_window_runs_the_recompute_after_its_session_and_never_on_a_stop(monkeypatch):
    from src.scheduler import maintenance

    calls: list[str] = []
    monkeypatch.setattr(
        "src.analytics.stoplist_recompute.maybe_recompute_top_keywords",
        lambda **_kw: calls.append("recompute") or {"skipped": "current"},
    )
    assert maintenance._stoplist_recompute(lambda: False) == {"skipped": "current"}
    assert calls == ["recompute"]

    def boom(**_kw):
        raise RuntimeError("x")

    monkeypatch.setattr("src.analytics.stoplist_recompute.maybe_recompute_top_keywords", boom)
    assert maintenance._stoplist_recompute(lambda: False) == {"skipped": "error"}


def test_both_maintenance_entry_points_call_the_recompute():
    src = (Path(__file__).resolve().parents[1] / "src" / "scheduler" / "maintenance.py").read_text("utf-8")
    assert src.count("_stoplist_recompute(stop)") == 2, "the window and its continuation both run it"


def test_an_article_met_again_in_the_walk_is_not_read_again(env, monkeypatch):
    """An article with two hidden words is reached under both; its mentions are read once."""
    from sqlalchemy import event

    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 2)  # small chunks, so the meetings fall in different chunks
    _world(env)
    reads = {"n": 0}

    @event.listens_for(env.engine, "before_cursor_execute")
    def _count(_conn, _cur, statement, _params, _ctx, _many):
        if "article_id IN" in statement and "keyword_mentions" in statement:
            reads["n"] += 1

    assert sr.maybe_recompute_top_keywords()["complete"] is True
    reads_with = reads["n"]

    reads["n"] = 0
    env.set_words(["hid1", "hid2", "other"])  # a new list: the walk runs again
    monkeypatch.setattr(sr, "SEEN_CAP", 0)  # remembers nothing: every meeting reads
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    assert reads["n"] > reads_with, "without the memory every meeting read the article again"
