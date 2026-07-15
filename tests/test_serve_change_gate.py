"""P1.10 change-gated rollup refresh — the negative-space skeptics, pinned as tests.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 12:14 field logs (2026-07-09) showed the blind 15-min TTL rebuild CHURNING
(trending-windows: 62 calls / 3,286 s over an unchanged corpus). The serve modules now
rebuild on CHANGE — corpus epoch (re-index/prune/restore) OR the append tail (max ids) —
with a long backstop TTL. Each test here pins one failure mode a wrong gate would have:

  * a re-index/prune by ANOTHER connection must be DETECTED (the epoch lives in the
    database, not the process — the two-connection shape, the ALPHA lesson);
  * appends-only growth (epoch unchanged, mentions grew) must be DETECTED — a pure epoch
    gate would freeze the rollup during collection;
  * an UNCHANGED corpus must NOT rebuild (the churn fix itself);
  * the backstop must still rebuild eventually (change classes the cheap token can't see);
  * while a change is pending, the serve keeps answering with the PREVIOUS build's real
    numbers, disclosed stale (never a silent blend, never a silent live-scan fallback).

All tests run over FILE-backed SQLite so the "second connection" is a real second
connection, and monkeypatch ``_trigger_build_async`` so no background build ever runs
against the process store from a test.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, map_serve, rollup_serve, serve_gate
from src.analytics.corpus_epoch import bump_corpus_epoch, get_corpus_epoch
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

pytestmark = pytest.mark.skipif(
    not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)"
)

_WIDE = 100_000  # a window covering the whole fixture (days)


def _mk_sessionmaker(tmp_path, name: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed(Sess) -> None:
    s = Sess()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    texts = [
        "The federal budget dominated the Senate; sanctions loomed.",
        "Climate policy and drought reached the Senate committee.",
    ]
    for i, t in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=t, hash=f"h{i}", country="fr", language="en",
            published_at=datetime(2024, 3, 1 + i, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    s.close()


def _add_article(Sess, i: int) -> None:
    """Ordinary ingest via a FRESH connection: appends mentions, does NOT bump the epoch."""
    s = Sess()
    a = Article(
        url=f"https://x.test/new{i}", canonical_url=f"https://x.test/new{i}", source_id=1,
        title="T", content="A fresh pandemic vaccine budget headline appeared.",
        hash=f"hnew{i}", country="fr", language="en",
        published_at=datetime(2024, 3, 20, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    s.add(a)
    s.commit()
    index_article(s, a, extractor=BaselineExtractor())
    s.close()


def _build_keyword_rollup(Sess) -> None:
    s = Sess()
    con = columnar.connect(passphrase=None)
    token = serve_gate.change_token(s)
    columnar.build_keyword_daily(con, s)
    rollup_serve._STATE.update(
        {"con": con, "bind": s.get_bind(), "built_at": time.time(),
         "token": token, "pending": False, "checked_at": 0.0}
    )
    s.close()


def _build_map_rollup(Sess) -> None:
    s = Sess()
    con = columnar.connect(passphrase=None)
    token = serve_gate.change_token(s, articles=True, sources=True)
    columnar.build_source_coverage(con, s)
    map_serve._STATE.update(
        {"con": con, "bind": s.get_bind(), "built_at": time.time(),
         "token": token, "pending": False, "checked_at": 0.0}
    )
    s.close()


@pytest.fixture(autouse=True)
def _serve_state(monkeypatch):
    """Clean singleton state around each test; gate knobs opened so every serve consults
    the change token (min-rebuild + check-throttle zeroed, backstop huge); triggers are
    RECORDED, never run (no background build against the process store from a test)."""
    for mod in (rollup_serve, map_serve):
        if mod._BUILD_LOCK.acquire(timeout=30):
            mod._BUILD_LOCK.release()
        con = mod._STATE.get("con")
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        mod._STATE.update(
            {"con": None, "built_at": 0.0, "rows": 0, "bind": None,
             "token": None, "pending": False, "checked_at": 0.0}
        )
        # S11: rollup_serve's churn bound is now read per-serve via rollup_serve_ttl_s()
        # (OO_COLUMNAR_SERVE_TTL_S / the active profile) — the _MIN_REBUILD_S CONSTANT was retired
        # there. map_serve still carries its own _MIN_REBUILD_S constant. Zero both (no bound).
        monkeypatch.setenv("OO_COLUMNAR_SERVE_TTL_S", "0")
        if hasattr(mod, "_MIN_REBUILD_S"):  # map_serve only; rollup_serve reads the env above
            monkeypatch.setattr(mod, "_MIN_REBUILD_S", 0)
        monkeypatch.setattr(mod, "_CHECK_EVERY_S", 0.0)
        monkeypatch.setattr(mod, "_BACKSTOP_S", 10_000_000)
    monkeypatch.setenv("OO_COLUMNAR_SERVE", "1")
    monkeypatch.setenv("OO_COLUMNAR_MAP_SERVE", "1")
    triggered: dict[str, int] = {"rollup": 0, "map": 0}
    monkeypatch.setattr(
        rollup_serve, "_trigger_build_async",
        lambda: triggered.__setitem__("rollup", triggered["rollup"] + 1),
    )
    monkeypatch.setattr(
        map_serve, "_trigger_build_async",
        lambda: triggered.__setitem__("map", triggered["map"] + 1),
    )
    yield triggered
    for mod in (rollup_serve, map_serve):
        con = mod._STATE.get("con")
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        mod._STATE.update(
            {"con": None, "built_at": 0.0, "rows": 0, "bind": None,
             "token": None, "pending": False, "checked_at": 0.0}
        )


def test_unchanged_corpus_never_rebuilds_the_churn_fix(tmp_path, _serve_state):
    """THE measured fix: repeated serves over an unchanged corpus trigger ZERO rebuilds
    (the old TTL rebuilt the 20.9 M-mention rollup every 15 min regardless)."""
    Sess = _mk_sessionmaker(tmp_path, "a.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)
    for _ in range(5):
        s = Sess()
        rows = rollup_serve.windowed_rows(s, days=_WIDE)
        assert rows, "the built rollup keeps serving"
        s.close()
    assert _serve_state["rollup"] == 0, "no change -> no rebuild, however often it serves"
    assert rollup_serve._STATE["pending"] is False
    assert rollup_serve.basis(7)["stale"] is False


def test_reindex_or_prune_on_another_connection_is_detected(tmp_path, _serve_state):
    """The two-connection skeptic: a re-index/prune bumps the corpus EPOCH through a
    DIFFERENT connection; the serve's gate must see it (the epoch lives in the database,
    not the process) — and until the rebuild lands, the PREVIOUS build keeps serving,
    disclosed stale (never a silent wrong answer, never a silent live-scan)."""
    Sess = _mk_sessionmaker(tmp_path, "b.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)

    other = Sess()  # a second, independent connection (what a re-index job runs on)
    bump_corpus_epoch(other, reason="test re-index")
    other.close()

    s = Sess()
    rows = rollup_serve.windowed_rows(s, days=_WIDE)
    s.close()
    assert _serve_state["rollup"] >= 1, "the epoch bump by another connection was detected"
    assert rollup_serve._STATE["pending"] is True
    assert rows, "the previous build keeps serving while the rebuild is pending"
    b = rollup_serve.basis(7)
    assert b["stale"] is True, "the pending newer corpus state is DISCLOSED"
    assert b["as_of"], "as_of stays visible so the staleness is honest"


def test_appends_only_growth_is_detected_epoch_unchanged(tmp_path, _serve_state):
    """The freeze-during-collection skeptic: ordinary ingest APPENDS mentions without
    bumping the epoch (by design). A pure epoch gate would serve a frozen rollup for the
    whole collection run — the max-id tail must catch it."""
    Sess = _mk_sessionmaker(tmp_path, "c.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)

    s0 = Sess()
    epoch_before = get_corpus_epoch(s0)
    s0.close()
    _add_article(Sess, 1)  # ingest on its own connection; no epoch bump
    s0 = Sess()
    assert get_corpus_epoch(s0) == epoch_before, "ingest must NOT have bumped the epoch"
    s0.close()

    s = Sess()
    rollup_serve.windowed_rows(s, days=_WIDE)
    s.close()
    assert _serve_state["rollup"] >= 1, "the advanced mention tail was detected"
    assert rollup_serve._STATE["pending"] is True


def test_backstop_rebuilds_even_without_a_visible_change(tmp_path, _serve_state, monkeypatch):
    """Some changes are INVISIBLE to the cheap token (cascade deletes, in-place
    backfills) — the long backstop must still rebuild, or those would go stale forever."""
    Sess = _mk_sessionmaker(tmp_path, "d.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)
    monkeypatch.setattr(rollup_serve, "_BACKSTOP_S", 60)
    rollup_serve._STATE["built_at"] = time.time() - 120  # past the backstop, token unchanged

    s = Sess()
    rollup_serve.windowed_rows(s, days=_WIDE)
    s.close()
    assert _serve_state["rollup"] >= 1, "the backstop fired with an unchanged token"
    assert rollup_serve.basis(7)["stale"] is True


def test_min_rebuild_interval_bounds_churn_under_continuous_change(
    tmp_path, _serve_state, monkeypatch
):
    """Under continuous collection the token changes constantly; the min-rebuild interval
    (the old TTL, repurposed) must bound rebuild frequency or change-gating would rebuild
    back-to-back — WORSE churn than the timer it replaces."""
    Sess = _mk_sessionmaker(tmp_path, "e.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)
    monkeypatch.setenv("OO_COLUMNAR_SERVE_TTL_S", "900")  # S11: freshly built -> inside window
    _add_article(Sess, 2)  # the corpus DID change

    s = Sess()
    rollup_serve.windowed_rows(s, days=_WIDE)
    s.close()
    assert _serve_state["rollup"] == 0, "inside the min-rebuild window: no rebuild yet"
    assert rollup_serve._STATE["pending"] is False


def test_post_pass_refresh_is_change_gated(tmp_path, _serve_state):
    """warm_cache's post-pass refresh() used to rebuild UNCONDITIONALLY after every pass.
    Now: same bind + no change -> no-op; a real change -> rebuild; and with no session to
    check against -> the old rebuild-on-doubt (freshness is the safe direction)."""
    Sess = _mk_sessionmaker(tmp_path, "f.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)

    s = Sess()
    rollup_serve.refresh(s)  # nothing changed since the build
    assert _serve_state["rollup"] == 0, "an empty pass no longer forces a full rebuild"

    bump_corpus_epoch(s, reason="test prune")
    rollup_serve.refresh(s)
    assert _serve_state["rollup"] == 1, "a real change still refreshes after the pass"
    s.close()

    rollup_serve.refresh(None)  # no session -> cannot check -> rebuild-on-doubt
    assert _serve_state["rollup"] == 2


def test_map_gate_detects_epoch_new_source_and_skips_unchanged(tmp_path, _serve_state):
    """The map serve mirrors the gate: unchanged -> no rebuild; a NEW SOURCE (no new
    mentions/articles) -> detected via the source id tail; an epoch bump by another
    connection -> detected; the previous build keeps serving, disclosed stale."""
    Sess = _mk_sessionmaker(tmp_path, "g.db")
    _seed(Sess)
    _build_map_rollup(Sess)

    s = Sess()
    assert map_serve.map_coverage(s) is not None
    assert _serve_state["map"] == 0, "unchanged corpus -> the map rollup is not rebuilt"

    s.add(Source(name="S2", domain="y.test", country="de"))
    s.commit()
    served = map_serve.map_coverage(s)
    assert _serve_state["map"] >= 1, "a new source advanced the source tail -> detected"
    assert served is not None, "the previous build keeps serving while pending"
    assert served["basis"]["stale"] is True, "…and the staleness is DISCLOSED"

    map_serve._STATE["pending"] = False  # as a completed rebuild would leave it
    map_serve._STATE["token"] = serve_gate.change_token(s, articles=True, sources=True)
    before = _serve_state["map"]
    other = Sess()
    bump_corpus_epoch(other, reason="test restore-merge")
    other.close()
    map_serve.map_coverage(s)
    assert _serve_state["map"] > before, "the epoch bump by another connection was detected"
    s.close()


def test_wrong_bind_never_consults_the_gate_or_triggers(tmp_path, _serve_state):
    """A session on ANOTHER database must fall back to live WITHOUT churning this
    rollup's rebuild (its ids would be meaningless against this token)."""
    Sess = _mk_sessionmaker(tmp_path, "h.db")
    _seed(Sess)
    _build_keyword_rollup(Sess)

    Other = _mk_sessionmaker(tmp_path, "other.db")
    _seed(Other)
    o = Other()
    assert rollup_serve.windowed_rows(o, days=_WIDE) is None, "wrong bind -> live fallback"
    o.close()
    assert _serve_state["rollup"] == 0, "a foreign session never churns this rollup"
