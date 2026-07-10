"""P1.12 — soft deadline + resumable watermark for the background maintenance passes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 12:14 field logs (2026-07-09) measured the counter reconcile at 86–104 s/pass and the
orphan-prune scan at 32 s on the live 3.06 M-keyword corpus. Both passes now run in
id-ordered slices under a soft budget, persisting a resume watermark in ``derived_meta``.
The negative-space skeptic this file pins: **a deadline'd reconcile must never leave
counters SILENTLY half-reconciled** — only verified keywords get stamped, so the honesty
envelope keeps disclosing ``estimated`` until a sweep completes, the tally says
``complete: false``, and the next pass RESUMES from the persisted cursor.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from src.analytics import store as store_mod
from src.analytics.corpus_epoch import get_corpus_epoch
from src.analytics.store import (
    PRUNE_CURSOR_KEY,
    RECONCILE_CURSOR_KEY,
    _cursor_get,
    counter_envelope,
    prune_orphan_keywords,
    reconcile_keyword_counters,
)
from src.database.models import Article, Base, Keyword, KeywordMention, Source


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _seed_keywords(db, n: int, *, mentioned: bool = True) -> list[int]:
    """``n`` keywords, each (optionally) with one mention on a shared article."""
    a = Article(
        url="https://x.test/a", canonical_url="https://x.test/a", source_id=1,
        title="T", content="x", hash="a" * 16, language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    db.add(a)
    db.flush()
    ids = []
    for i in range(n):
        kw = Keyword(term=f"kw{i}", normalized_term=f"kw{i}", language="en",
                     mention_count=1 if mentioned else 0,
                     article_count=1 if mentioned else 0)
        db.add(kw)
        db.flush()
        ids.append(kw.id)
        if mentioned:
            db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1))
    db.commit()
    return ids


# ------------------------------- reconcile ---------------------------------- #


def test_partial_reconcile_is_disclosed_never_silently_exact(db, monkeypatch):
    """THE skeptic: a budget-stopped reconcile fixed only the FIRST slice — drift in a
    later slice is still wrong, so the envelope MUST stay `estimated` and the tally MUST
    say so; a silently-`exact` half-reconcile would be a fabricated verification."""
    monkeypatch.setattr(store_mod, "_RECONCILE_SCAN_CHUNK", 3)
    ids = _seed_keywords(db, 9)

    # Drift injected in the LAST slice (a cascade delete the hook can't see).
    late = db.get(Keyword, ids[-1])
    late.mention_count = 999
    db.commit()

    res = reconcile_keyword_counters(db, budget_s=1e-9)  # stops after slice 1
    assert res["complete"] is False, "the budget stop is DISCLOSED"
    assert res["keywords"] == 3, "exactly one slice was scanned"
    assert res["cursor_id"] > 0
    assert _cursor_get(db, RECONCILE_CURSOR_KEY) == res["cursor_id"], "watermark persisted"

    db.expire_all()
    assert db.get(Keyword, ids[-1]).mention_count == 999, "the late drift is NOT yet fixed…"
    env = counter_envelope(db)
    assert env.basis == "estimated", "…so the envelope must NOT claim exact"

    # Resume passes: each continues from the persisted cursor until the sweep completes.
    total_scanned = res["keywords"]
    for _ in range(10):
        res = reconcile_keyword_counters(db, budget_s=1e-9)
        assert res["resumed_from_id"] > 0, "resumed from the watermark, not from zero"
        total_scanned += res["keywords"]
        if res["complete"]:
            break
    assert res["complete"] is True
    assert total_scanned == len(ids), "every keyword scanned exactly once across the sweep"
    assert _cursor_get(db, RECONCILE_CURSOR_KEY) == 0, "a finished sweep clears the cursor"

    db.expire_all()
    assert db.get(Keyword, ids[-1]).mention_count == 1, "the late drift was repaired"
    assert counter_envelope(db).basis == "exact", "a COMPLETE sweep restores exact"


def test_unbounded_budget_completes_in_one_pass(db, monkeypatch):
    monkeypatch.setattr(store_mod, "_RECONCILE_SCAN_CHUNK", 4)
    ids = _seed_keywords(db, 10)
    res = reconcile_keyword_counters(db, budget_s=0)  # <= 0 = unbounded
    assert res["complete"] is True
    assert res["keywords"] == len(ids)
    assert res["drift_repaired"] == 0
    assert counter_envelope(db).basis == "exact"


def test_reconcile_tally_has_no_score_shaped_key(db):
    _seed_keywords(db, 2)
    res = reconcile_keyword_counters(db)
    assert not any(
        bad in k.lower() for k in res for bad in ("score", "trust", "rank", "rating", "verdict")
    )


# --------------------------------- prune ------------------------------------ #


def test_partial_prune_resumes_from_the_persisted_cursor(db, monkeypatch):
    """A budget-stopped prune removed only the first slice's orphans; the cursor is
    persisted, the tally honest, and resume passes finish the sweep."""
    monkeypatch.setattr(store_mod, "_PRUNE_SCAN_CHUNK", 3)
    _seed_keywords(db, 3, mentioned=True)  # keepers
    for i in range(6):  # orphans across two later slices
        db.add(Keyword(term=f"orph{i}", normalized_term=f"orph{i}", language="en"))
    db.commit()

    res = prune_orphan_keywords(db, budget_s=1e-9)  # stops after slice 1
    assert res["complete"] is False
    assert _cursor_get(db, PRUNE_CURSOR_KEY) == res["cursor_id"] > 0

    pruned_total = res["pruned"]
    for _ in range(10):
        res = prune_orphan_keywords(db, budget_s=1e-9)
        pruned_total += res["pruned"]
        if res["complete"]:
            break
    assert res["complete"] is True
    assert pruned_total == 6, "every orphan pruned across the resumed sweep"
    assert _cursor_get(db, PRUNE_CURSOR_KEY) == 0
    db.expire_all()
    assert db.query(func.count(Keyword.id)).scalar() == 3, "keepers survive"
    assert (
        db.query(Keyword).filter(Keyword.normalized_term.like("orph%")).count() == 0
    )


def test_prune_bumps_epoch_at_most_once_per_pass(db, monkeypatch):
    """The D3 guard stays: a pruning pass bumps the corpus epoch ONCE (not per slice),
    and a pass that prunes nothing bumps nothing."""
    monkeypatch.setattr(store_mod, "_PRUNE_SCAN_CHUNK", 2)
    _seed_keywords(db, 2, mentioned=True)
    for i in range(5):
        db.add(Keyword(term=f"orph{i}", normalized_term=f"orph{i}", language="en"))
    db.commit()

    before = get_corpus_epoch(db)
    res = prune_orphan_keywords(db, budget_s=0)  # unbounded: several slices, one pass
    assert res["pruned"] == 5 and res["complete"] is True
    assert get_corpus_epoch(db) == before + 1, "exactly ONE bump for the whole pass"

    res2 = prune_orphan_keywords(db, budget_s=0)
    assert res2["pruned"] == 0
    assert get_corpus_epoch(db) == before + 1, "a no-op pass never bumps"


def test_maybe_cleanup_resumes_an_incomplete_prune_inside_the_freshness_window(
    db, monkeypatch, tmp_path
):
    """The 12 h gate must not strand a budget-stopped prune at its cursor: while the last
    prune reports complete=false, the next call resumes it (prune ONLY — the language
    reconcile already ran this cycle) without sliding the 12 h clock."""
    from src.analytics.store import maybe_cleanup_keywords

    monkeypatch.setattr(store_mod, "_PRUNE_SCAN_CHUNK", 3)
    monkeypatch.setattr(store_mod, "_cleanup_marker_path", lambda: tmp_path / "cleanup.json")
    monkeypatch.setenv("OO_PRUNE_BUDGET_S", "0.000000001")
    _seed_keywords(db, 3, mentioned=True)
    for i in range(6):
        db.add(Keyword(term=f"orph{i}", normalized_term=f"orph{i}", language="en"))
    db.commit()

    first = maybe_cleanup_keywords(db)
    assert first["prune"]["complete"] is False
    first_run = store_mod.keyword_cleanup_state()["last_run"]

    second = maybe_cleanup_keywords(db)  # inside the 12 h window, but the sweep resumes
    assert second.get("resumed_prune") is True
    assert second["language"] == {"skipped": "ran this cycle"}, "language not re-paid"
    assert store_mod.keyword_cleanup_state()["last_run"] == first_run, "clock anchored"

    for _ in range(10):
        st = store_mod.keyword_cleanup_state()["last_tally"]["prune"]
        if st.get("complete"):
            break
        maybe_cleanup_keywords(db)
    assert store_mod.keyword_cleanup_state()["last_tally"]["prune"]["complete"] is True
    assert db.query(Keyword).filter(Keyword.normalized_term.like("orph%")).count() == 0

    done = maybe_cleanup_keywords(db)
    assert done == {"skipped": "fresh", "last_run": first_run}, "gate holds once complete"
