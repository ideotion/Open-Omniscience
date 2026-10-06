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
    # there is no shortcut: the article whose hidden word sits below its top is READ and found clean
    # like the one a previous run left clean, and the NULL is still left for the index
    assert out["baseline_known"] is False
    assert out["already_clean"] == 2 and out["never_computed"] == 1


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


def test_an_old_format_cursor_row_is_not_resumed(env):
    """A cursor row written before the walk key existed held the bare fingerprint (no plan part); it
    parses as no cursor, so the walk starts from the top rather than from a position that was made
    for a different walk."""
    from src.database.models import DerivedMeta

    fp = sr.current_fingerprint()
    with env.session() as s:
        s.add(DerivedMeta(key=sr.CURSOR_KEY, value=f"{fp}:7:7", updated_at=datetime.now(UTC)))
    with env.session() as s:
        assert sr._cursor_get(s, f"{fp}.0123456789abcdef") == (0, 0)


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


# ----------------------------------------------------------------- the folds of the one read


def test_a_resume_between_two_adjacent_articles_of_one_hidden_word_skips_neither(env, monkeypatch):
    """The cursor names the LAST article handled: a resume starts strictly after it, and a stop that
    lands between two neighbours of the same hidden word must lose neither."""
    with env.session() as s:
        h1, a = _keyword(s, "hid1"), _keyword(s, "aa")
        for i in range(6):
            _article(s, f"adj{i}", {h1: 5, a: 2})
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)  # one (keyword, article) pair a chunk
    calls = {"n": 0}

    def stop_after_two_chunks():
        calls["n"] += 1
        return calls["n"] > 2  # two chunks pass; the third check stops

    first = sr.maybe_recompute_top_keywords(should_stop=stop_after_two_chunks)
    assert first["complete"] is False and first["chunks"] == 2
    second = sr.maybe_recompute_top_keywords()
    assert second["complete"] is True and second["resumed_at"] is not None
    assert {v[:3] for v in _tops(env).values()} == {(a, 2, 1)}, "a neighbour was skipped at the cursor"


def test_a_batch_boundary_in_the_mention_read_drops_no_article(env, monkeypatch):
    w = _world(env)
    before = _tops(env)
    monkeypatch.setattr(sr, "_IN_CHUNK", 2)  # every read and write batch holds two articles
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    _assert_final(_tops(env), before, w)


def test_a_budget_shorter_than_one_chunk_still_makes_progress(env, monkeypatch):
    """A pass that stopped on its budget before its first chunk would record itself without moving
    and the offline timer would loop on it: the budget is read only once a chunk has run."""
    _world(env)
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)
    out = sr.maybe_recompute_top_keywords(budget_s=1e-9)
    assert out["stopped_by"] == "budget" and out["chunks"] == 1 and out["scanned"] >= 1
    with env.session() as s:
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is not None


def test_the_window_timed_is_the_one_held_and_the_longest_is_recorded(env):
    _world(env)
    out = sr.maybe_recompute_top_keywords()
    assert 0 < out["max_window_s"] <= out["write_window_s"] + 1e-6
    assert out["fingerprint"] == sr.current_fingerprint(), "a pass names the list it ran on"
    assert sr.read_state()["last_pass"]["fingerprint"] == sr.current_fingerprint()


def test_a_word_taken_off_the_list_gets_back_into_the_stored_tops(env):
    """The word the last finished run hid and the list no longer holds: the tops made without it are
    recomputed with it, including the articles that never held another hidden word."""
    w = _world(env)
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    assert sr.read_state()["words"] == ["hid1", "hid2"]
    before = _tops(env)
    assert before["lone_top"][:3] == (w["a"], 2, 1)  # made without hid1

    env.set_words(["hid2"])  # hid1 leaves the list
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["restored_keywords"] == 1

    after = _tops(env)
    with env.session() as s:
        mentions: dict[int, dict[int, int]] = {}
        for aid, kid, c in s.execute(select(_MT.c.article_id, _MT.c.keyword_id, _MT.c.count)):
            mentions.setdefault(aid, {})[kid] = c
        by_hash = {a.hash: a.id for a in s.query(Article)}
    for h, aid in by_hash.items():
        visible = {k: c for k, c in mentions[aid].items() if k != w["h2"]}
        assert after[h][:3] == top_keyword_of(visible), h
    assert after["lone_top"][:3] == (w["h1"], 5, 1)
    assert after["only_hidden"][:3] == (w["h1"], 2, 1), "the NULL a hidden-only article was left with"
    assert {v[3] for v in after.values()} == {_STAMP}, "updated_at is never stamped by this pass"
    assert sr.read_state()["words"] == ["hid2"]


def test_a_list_that_only_grew_restores_nothing(env):
    _world(env)
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    env.set_words(["hid1", "hid2", "other"])
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["restored_keywords"] == 0


# ------------------------------------------------- the baseline: pending lists and what travels


def _known_baseline(env, words=None):
    """Make the state file and the database agree that a run finished on ``words`` earlier."""
    words = sorted(env.stoplist if words is None else words)
    (sr._state_path()).write_text(
        __import__("json").dumps({"fingerprint": "earlier", "words": words}), encoding="utf-8"
    )
    with env.session() as s:
        sr._meta_set(s, sr.DONE_KEY, "earlier")


def _oracle(env, hidden_terms):
    """What every stored top must be: the top of the article's mentions minus the hidden words."""
    with env.session() as s:
        hid = {k.id for k in s.query(Keyword) if k.normalized_term in hidden_terms}
        mentions: dict[int, dict[int, int]] = {}
        for aid, kid, c in s.execute(select(_MT.c.article_id, _MT.c.keyword_id, _MT.c.count)):
            mentions.setdefault(aid, {})[kid] = c
        return {
            a.hash: top_keyword_of({k: c for k, c in mentions.get(a.id, {}).items() if k not in hid})
            for a in s.query(Article)
        }


def _assert_tops_equal_oracle(env, hidden_terms):
    want = _oracle(env, hidden_terms)
    got = {h: v[:3] for h, v in _tops(env).items()}
    want.pop("never_computed", None)  # a NULL is left for the index to fill
    got.pop("never_computed", None)
    assert got == want


def test_a_known_baseline_reaches_the_same_tops_as_an_unknown_one(env):
    """The baseline decides which words are restored, never whether an article is read."""
    _world(env)
    _known_baseline(env)
    out = sr.maybe_recompute_top_keywords()
    assert out["baseline_known"] is True and out["already_clean"] == 2 and out["never_computed"] == 1


def test_a_database_that_lost_its_baseline_is_walked_and_its_stale_top_found(env):
    """A restore, a merge swap or a moved database: the state file says current, the data says
    nothing. A stored top that holds a hidden word BELOW a visible one is read like any other."""
    with env.session() as s:
        h1, a = _keyword(s, "hid1"), _keyword(s, "aa")
        _article(s, "stale", {h1: 3, a: 5}, stored=(h1, 3, 1))  # made under a list that did not hide it
    _known_baseline(env)
    with env.session() as s:  # the data came from elsewhere: it carries no finished fingerprint
        s.query(DerivedMeta).filter(DerivedMeta.key == sr.DONE_KEY).delete()
    st = sr.read_state()
    st["fingerprint"] = sr.current_fingerprint()  # the file left behind claims the list is finished
    sr._state_path().write_text(__import__("json").dumps(st), encoding="utf-8")
    out = sr.maybe_recompute_top_keywords()
    assert out["baseline_known"] is False and out["complete"] is True
    assert _tops(env)["stale"][:3] == (a, 5, 1)


def test_a_database_done_record_that_differs_from_the_files_leaves_the_baseline_unknown(env):
    _world(env)
    _known_baseline(env)
    with env.session() as s:
        sr._meta_set(s, sr.DONE_KEY, "some-other-run")
    out = sr.maybe_recompute_top_keywords()
    assert out["baseline_known"] is False and out["complete"] is True


def test_a_lost_baseline_then_a_hide_cannot_leave_a_hidden_word_in_a_top(env):
    """After a lost baseline the first pass finishes and writes its record, so the next pass reads as
    known; an article that first pass never reached must still be found when the next change hides the
    word its top was made with (the old shortcut skipped it: 3 < 4)."""
    with env.session() as s:
        z, a, b, c = (_keyword(s, t) for t in ("hidz", "aa", "bb", "cc"))
        _article(s, "A", {a: 3, b: 3, c: 4}, stored=(a, 3, 2))  # made while cc was hidden
    env.set_words(["hidz"])  # no state file, no record: the baseline is lost
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["baseline_known"] is False
    assert _tops(env)["A"][:3] == (a, 3, 2), "nothing reached it: it holds no hidden word"
    env.set_words(["hidz", "aa"])  # the next change hides the word its top was made with
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["baseline_known"] is True
    assert _tops(env)["A"][:3] == (c, 4, 1)


def test_a_cursor_row_in_the_database_means_a_pass_in_flight_not_a_finished_list(env):
    """An older copy of the database taken mid-pass carries a cursor; with the file's record and the
    finished fingerprint both present it must still not read as current."""
    _world(env)
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    assert sr.maybe_recompute_top_keywords() == {"skipped": "current"}
    with env.session() as s:
        sr._cursor_set(s, sr.current_fingerprint() + ".x", 1, 1)
    out = sr.maybe_recompute_top_keywords()
    assert out != {"skipped": "current"} and out["complete"] is True
    with env.session() as s:
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is None


def test_a_garbled_pending_record_leaves_the_baseline_unknown_for_every_later_attempt(env, monkeypatch):
    _world(env)
    _known_baseline(env)
    st = sr.read_state()
    st["words_pending"] = "garbled"
    sr._state_path().write_text(__import__("json").dumps(st), encoding="utf-8")
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)
    first = sr.maybe_recompute_top_keywords(should_stop=_stop_after(1))
    assert first["complete"] is False and first["baseline_known"] is False
    after = sr.read_state()
    assert "fingerprint" not in after and "words" not in after, "what the record truncated is gone"
    assert isinstance(after["words_pending"], list)
    second = sr.maybe_recompute_top_keywords()
    assert second["complete"] is True and second["baseline_known"] is False


def test_a_crash_between_the_cursor_delete_and_the_done_write_leaves_the_walk_resumable(env, monkeypatch):
    """The two writes are one transaction: if the second fails the first rolls back, the cursor is
    still there, and the next window finishes without walking again."""
    w = _world(env)
    before = _tops(env)
    real = sr._meta_set

    def fail_on_done(session, key, value):
        if key == sr.DONE_KEY:
            raise RuntimeError("disk full")
        return real(session, key, value)

    monkeypatch.setattr(sr, "_meta_set", fail_on_done)
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is False and out["skipped"].startswith("RuntimeError")
    with env.session() as s:
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is not None, "the delete rolled back with the failed write"
        assert sr._done_get(s) is None
    assert sr.needs_run()
    monkeypatch.setattr(sr, "_meta_set", real)
    again = sr.maybe_recompute_top_keywords()
    assert again["complete"] is True and again["chunks"] == 0, "resumed at the end, nothing walked again"
    with env.session() as s:
        assert sr._done_get(s) == sr.current_fingerprint()
    _assert_final(_tops(env), before, w)


def test_the_same_list_walked_with_a_larger_plan_is_not_resumed_past_a_restored_keyword(env, monkeypatch):
    """Ids x < z < h < f. The finished list is {z}. Window 1 (list {z,h}) stops with its cursor at h after
    Y. Window 2 (list {z,h,x}) stops before its first chunk. Window 3 (list {z,h} again) restores x: it must
    not resume at h and skip x, whose article X would keep h in its top."""
    with env.session() as s:
        x, z, h, f = (_keyword(s, t) for t in ("hidx", "hidz", "hidh", "ff"))
        _article(s, "Y", {h: 5, f: 1})
        _article(s, "X", {x: 3, h: 4, f: 1})
    env.set_words(["hidz"])
    _known_baseline(env, ["hidz"])
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)
    env.set_words(["hidz", "hidh"])
    assert sr.maybe_recompute_top_keywords(should_stop=_stop_after(1))["complete"] is False
    with env.session() as s:
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is not None
    env.set_words(["hidz", "hidh", "hidx"])
    assert sr.maybe_recompute_top_keywords(should_stop=_stop_after(0))["complete"] is False
    env.set_words(["hidz", "hidh"])
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["restored_keywords"] == 1
    _assert_tops_equal_oracle(env, {"hidz", "hidh"})
    assert _tops(env)["X"][:3] == (x, 3, 1)


@pytest.mark.parametrize("state", ['{"fingerprint": "earlier", "words": "not-a-list"}', "[1, 2]", "{{{"])
def test_an_unusable_state_file_leaves_the_baseline_unknown(env, state):
    with env.session() as s:
        h1, a = _keyword(s, "hid1"), _keyword(s, "aa")
        _article(s, "stale", {h1: 3, a: 5}, stored=(h1, 3, 1))
        sr._meta_set(s, sr.DONE_KEY, "earlier")
    sr._state_path().write_text(state, encoding="utf-8")
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True and out["baseline_known"] is False
    assert _tops(env)["stale"][:3] == (a, 5, 1)


def test_a_finished_run_writes_its_fingerprint_into_the_database_with_the_cursor_delete(env):
    _world(env)
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    with env.session() as s:
        assert sr._done_get(s) == sr.current_fingerprint()
        assert s.get(DerivedMeta, sr.CURSOR_KEY) is None
    assert sr.read_state().get("words_pending") is None


def test_a_pass_that_cannot_record_its_pending_lists_does_not_start(env, monkeypatch):
    _world(env)
    before = _tops(env)
    monkeypatch.setattr(sr, "_write_state", lambda doc: False)
    out = sr.maybe_recompute_top_keywords()
    assert out == {"skipped": "state_unwritable", "complete": False}
    assert _tops(env) == before


def _stop_after(chunks):
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > chunks

    return stop


def test_a_pass_stopped_on_a_list_that_was_taken_off_is_accounted_for_when_the_list_returns(env, monkeypatch):
    """(b) L1 finishes; L2 takes a word off, the restored walk puts it back where it leads and the pass
    stops; L3 is L1 again, so the fingerprint matches the finished run's: it must NOT skip, and the
    word must leave every top it re-entered. Also pins restore, stop, resume."""
    w = _world(env)
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    fp1 = sr.current_fingerprint()
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)
    env.set_words(["hid2"])  # hid1 leaves the list
    first = sr.maybe_recompute_top_keywords(should_stop=_stop_after(1))
    assert first["complete"] is False
    st = sr.read_state()
    assert st["fingerprint"] == fp1 and st["words"] == ["hid1", "hid2"], "the baseline moves only at the end"
    assert st["words_pending"], "the lists walked since are recorded before the first chunk commits"
    assert _tops(env)["lone_top"][:3] == (w["h1"], 5, 1), "the restored word is back where it leads"

    env.set_words(["hid1", "hid2"])  # L3 = L1
    assert sr.needs_run() and sr.incomplete()
    out = sr.maybe_recompute_top_keywords()
    assert out != {"skipped": "current"} and out["complete"] is True
    _assert_tops_equal_oracle(env, {"hid1", "hid2"})
    assert not sr.needs_run()


def test_a_pass_stopped_on_a_list_that_added_a_word_is_accounted_for_when_the_list_returns(env, monkeypatch):
    """(a) L1 finishes; L2 adds a word and its pass stops after rewriting some tops; L3 is L1: the
    word is visible again and the tops made without it must be recomputed with it."""
    with env.session() as s:
        h1, h2, a = _keyword(s, "hid1"), _keyword(s, "hid2"), _keyword(s, "aa")
        for i in range(4):
            _article(s, f"x{i}", {h1: 2, a: 1})
        for i in range(4):
            _article(s, f"y{i}", {h2: 5, a: 1})
    env.set_words(["hid1"])
    _known_baseline(env, ["hid1"])
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)
    env.set_words(["hid1", "hid2"])  # L2 adds hid2
    assert sr.maybe_recompute_top_keywords(should_stop=_stop_after(6))["complete"] is False
    assert any(_tops(env)[f"y{i}"][:3] == (a, 1, 1) for i in range(4)), "some tops were rewritten"
    env.set_words(["hid1"])  # L3 = L1: hid2 visible again
    out = sr.maybe_recompute_top_keywords()
    assert out != {"skipped": "current"} and out["complete"] is True
    _assert_tops_equal_oracle(env, {"hid1"})


def test_a_swap_of_one_word_for_another_after_a_stopped_pass_leaves_no_hidden_word_in_a_top(env, monkeypatch):
    """(c) L2 adds w2 and its pass rewrites A's top to w3 and stops. L3 swaps w2 for w3: w3 is hidden
    now and w2 visible: A's stored top (w3) is a hidden word. A is reached through hidden w3 either way,
    so this pins the END STATE: no hidden word in any top, and A's top back on w2."""
    with env.session() as s:
        w2, w3, w4, f = (_keyword(s, t) for t in ("hid2", "hid3", "hid4", "ff"))
        _article(s, "A", {w2: 5, w3: 3, f: 1})
        _article(s, "B", {w4: 2, f: 1})
    env.set_words([])
    _known_baseline(env, [])
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, 1)
    env.set_words(["hid2", "hid4"])
    assert sr.maybe_recompute_top_keywords(should_stop=_stop_after(1))["complete"] is False
    assert _tops(env)["A"][:3] == (w3, 3, 1)
    env.set_words(["hid3", "hid4"])
    assert sr.maybe_recompute_top_keywords()["complete"] is True
    _assert_tops_equal_oracle(env, {"hid3", "hid4"})
    assert _tops(env)["A"][:3] == (w2, 5, 1)


@pytest.mark.parametrize("seed", range(40))
def test_no_stream_of_lists_stops_and_returns_leaves_a_hidden_word_in_a_top(env, monkeypatch, seed):
    """Random lists over five words (so a word can leave, return, swap and be stopped on), 14 small
    articles over seven keywords (so ties, lone tops and hidden-only articles all occur), random stops
    and chunk sizes of 1 or 2 (so a stop lands between neighbours and across keywords): after the last
    list finishes, every stored top is the top of the article's mentions minus the list that finished.
    The coordinator's model had 108 of 6,000 streams wrong before the pending record and 113 of 100,000
    wrong before the plan was part of the cursor key: 40 seeds are a smoke test for the class, and the
    deterministic cases above pin the named rare shapes, which a few dozen seeds cannot reliably find."""
    import random

    rnd = random.Random(seed)
    vocab = ["hid1", "hid2", "hid3", "hid4", "hid5"]
    with env.session() as s:
        ids = [_keyword(s, t) for t in vocab] + [_keyword(s, "ff"), _keyword(s, "gg")]
        first = set(rnd.sample(vocab, rnd.randint(0, 3)))
        for i in range(14):
            counts = {k: rnd.randint(1, 5) for k in rnd.sample(ids, rnd.randint(1, 5))}
            hid = {ids[vocab.index(t)] for t in first}
            top = top_keyword_of({k: c for k, c in counts.items() if k not in hid})
            _article(s, f"r{i}", counts, stored=top)
    env.set_words(sorted(first))
    _known_baseline(env, sorted(first))
    for name in ("START_CHUNK", "MIN_CHUNK", "MAX_CHUNK"):
        monkeypatch.setattr(sr, name, rnd.choice([1, 2]))
    last = first
    for _step in range(rnd.randint(2, 6)):
        last = set(rnd.sample(vocab, rnd.randint(0, 4)))
        env.set_words(sorted(last))
        sr.maybe_recompute_top_keywords(should_stop=_stop_after(rnd.randint(0, 3)))
    env.set_words(sorted(last))
    out = sr.maybe_recompute_top_keywords()
    while out.get("complete") is False and out.get("stopped_by"):
        out = sr.maybe_recompute_top_keywords()
    assert sr.maybe_recompute_top_keywords() == {"skipped": "current"}
    _assert_tops_equal_oracle(env, last)


def test_the_window_timed_starts_after_the_gate_and_not_before(env, monkeypatch):
    from types import SimpleNamespace

    import src.database.writer as writer

    _world(env)
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 0.01
        return clock["t"]

    def slow_gate(_session):
        clock["t"] += 10.0  # waiting for the gate is not the window others wait behind

    monkeypatch.setattr(writer, "hold_write_window", slow_gate)
    monkeypatch.setattr(sr, "time", SimpleNamespace(monotonic=tick))
    out = sr.maybe_recompute_top_keywords(budget_s=0)
    assert out["complete"] is True
    assert 0 < out["max_window_s"] < 1.0, out["max_window_s"]
    assert out["write_window_s"] < 1.0 * out["chunks"]


def test_a_duplicate_mention_row_is_summed_the_way_the_index_reads_it(env):
    """Without the unique index two rows of one (keyword, article) are possible in an old store; the
    pass sums them, as ``index_article``'s legacy read does."""
    with env.engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX ix_mention_keyword_article")
    with env.session() as s:
        h1, a = _keyword(s, "hid1"), _keyword(s, "aa")
        aid = _article(s, "dup", {h1: 3, a: 4}, stored=(None, None, None))
        s.execute(_MT.insert().values(keyword_id=h1, article_id=aid, count=2, first_offset=1))
        s.execute(Article.__table__.update().where(Article.__table__.c.id == aid)
                  .values(top_keyword_id=h1, top_keyword_count=3, top_keyword_tied_n=1))
    _known_baseline(env)
    out = sr.maybe_recompute_top_keywords()
    assert out["complete"] is True
    assert _tops(env)["dup"][:3] == (a, 4, 1), "3 + 2 = 5 > 4 would make the hidden word lead; hidden it is not"
