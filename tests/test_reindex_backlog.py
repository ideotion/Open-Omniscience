"""The durable re-index backlog — the guard the option-(a) ruling requires.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-07-29 (option (a)): the merge no longer copies the incoming
corpus's ``keyword_mentions``; the post-swap re-index produces them. That makes "not yet
re-indexed" mean "has no keywords", which every analytics path already honours by
construction — but it also trades a bounded STALENESS for an unbounded INVISIBILITY if
the re-index can ever be lost. So the work is tracked twice, with different jobs:

  * ``merge_batches.status`` — durable, in the corpus, the source of truth for "is there
    a backlog". Only a batch that reached the end is stamped ``reindexed``.
  * a marker file — the resume WATERMARK. Losing it costs time, never correctness.

These tests pin the asymmetry, and especially the failure directions: a watermark that
belongs to a DIFFERENT batch must never be honoured (it would skip real articles and
leave them permanently keyword-less), and a torn or absent one must start from the top
rather than guess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.backup.merge as merge_mod
from src.backup.merge import (
    DomainResult,
    _load_reindex_cursor,
    _save_reindex_cursor,
    clear_reindex_cursor,
)


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_mod, "data_dir", lambda: tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
#  the watermark
# --------------------------------------------------------------------------- #
def test_the_watermark_round_trips(state_dir):
    _save_reindex_cursor(7, last_id=420, done=3, total=10)
    assert _load_reindex_cursor(7) == 420


def test_a_watermark_from_a_DIFFERENT_batch_is_ignored(state_dir):
    """The load-bearing safety property. Honouring batch 7's watermark while re-indexing
    batch 8 would skip every article below it — and under option (a) those articles have
    no keywords at all, so they would be permanently invisible to analytics rather than
    merely stale."""
    _save_reindex_cursor(7, last_id=999_999, done=5, total=5)
    assert _load_reindex_cursor(8) is None, "a foreign watermark must never be trusted"


def test_an_absent_watermark_starts_from_the_top(state_dir):
    assert _load_reindex_cursor(1) is None


def test_a_torn_watermark_starts_from_the_top_rather_than_guessing(state_dir):
    (state_dir / "reindex_backlog.json").write_text("{not json", encoding="utf-8")
    assert _load_reindex_cursor(1) is None


def test_the_watermark_write_is_atomic(state_dir):
    """os.replace, so a crash mid-write can never leave a half-written file that parses
    into a plausible-but-wrong position."""
    _save_reindex_cursor(3, last_id=10, done=1, total=2)
    _save_reindex_cursor(3, last_id=20, done=2, total=2)
    raw = json.loads((state_dir / "reindex_backlog.json").read_text(encoding="utf-8"))
    assert raw["last_id"] == 20
    assert not list(state_dir.glob("*.tmp")), "no temp file is left behind"


def test_a_write_failure_is_survivable(monkeypatch, tmp_path):
    """The watermark is a resilience sidecar. One that can itself break the operation it
    protects is worse than none at all (this project's recorded crash-journal lesson)."""

    class _Boom:
        def __truediv__(self, other):
            raise OSError("disk full")

    monkeypatch.setattr(merge_mod, "data_dir", lambda: _Boom())
    _save_reindex_cursor(1, last_id=1, done=1, total=1)  # must not raise
    assert _load_reindex_cursor(1) is None


def test_clearing_is_idempotent(state_dir):
    clear_reindex_cursor()  # nothing there yet
    _save_reindex_cursor(1, last_id=5, done=1, total=1)
    clear_reindex_cursor()
    clear_reindex_cursor()
    assert _load_reindex_cursor(1) is None


# --------------------------------------------------------------------------- #
#  the deferral is reported, never silent
# --------------------------------------------------------------------------- #
def test_a_deferred_domain_reports_its_count_and_reason():
    r = DomainResult()
    r.deferred = 9_843_212
    r.note = "recomputed by the re-index"
    d = r.as_dict()
    assert d["deferred"] == 9_843_212
    assert d["note"] == "recomputed by the re-index"


def test_an_ordinary_domain_report_is_byte_unchanged():
    """`deferred`/`note` are additive: a domain that defers nothing must serialise
    exactly as it did before, or every existing report-shape assertion breaks."""
    r = DomainResult()
    r.new, r.duplicate, r.conflict = 3, 2, 1
    assert r.as_dict() == {"new": 3, "duplicate": 2, "conflict": 1}


def test_the_merge_no_longer_copies_mentions_but_still_handles_the_table():
    """The step stays in the pipeline. Dropping it instead would make keyword_mentions
    show up as an UNMERGED table in the report — technically honest, but it would read as
    an oversight rather than the deliberate policy it is."""
    import inspect

    src = inspect.getsource(merge_mod._merge_keyword_mentions)
    # Anchored to the CALL, not to the word "insert" — the docstring legitimately
    # discusses the old INSERT, and a whole-body substring search would match that prose
    # and pass against code it means to reject.
    assert "_insert_tracked" not in src, (
        "the mention copy must be gone, not merely guarded"
    )
    assert "r.deferred" in src, "and the skip must be quantified"
    assert "keyword_mentions" in merge_mod._MERGE_HANDLED


# --------------------------------------------------------------------------- #
#  the backlog must be VISIBLE, and "could not read" must not pass for "empty"
# --------------------------------------------------------------------------- #
def test_the_backlog_distinguishes_measured_empty_from_could_not_read(monkeypatch):
    """THE mandatory guard on the option-(a) ruling. The merge no longer copies the
    incoming corpus's derived rows, so an un-re-indexed import has NO keywords -- a
    bounded staleness traded for an UNBOUNDED invisibility if the backlog is ever
    lost. The durable cursor makes it resumable; this makes it visible.

    ``pending_reindex_batches`` returns [] for BOTH outcomes, which is why the wrapper
    exists: a diagnostic that cannot read must never report the reassurance it did not
    measure (the project's own degrade-sentinel lesson)."""
    from src.backup import merge as M

    class _Boom:
        def __enter__(self):
            raise RuntimeError("database is locked")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("src.database.session.session_scope", lambda: _Boom())
    out = M.reindex_backlog()
    assert out["available"] is False
    assert "locked" in out["reason"]
    assert "articles_pending" not in out, (
        "a failed read must not publish a count key at all — a 0 there would read as "
        "'nothing pending', the exact fabricated reassurance this guard prevents"
    )


def test_the_boot_path_states_the_backlog_out_loud():
    """A backlog nobody can see is the failure mode option (a) trades for. Pinned at
    the boot call site, scoped to the upkeep function's own body."""
    src = (
        Path(__file__).resolve().parents[1] / "src" / "api" / "main.py"
    ).read_text(encoding="utf-8")
    body = src.split("def _run_startup_upkeep(", 1)[1].split("\ndef ", 1)[0]
    assert "reindex_backlog" in body
    assert "could not read the re-index backlog" in body, (
        "a read failure must be reported too, never left to pass for 'nothing pending'"
    )
