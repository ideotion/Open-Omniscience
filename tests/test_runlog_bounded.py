"""The run journal is BOUNDED -- on the write side, the read side, and on disk.

All three guards come from one field failure (2026-08-06). PR #878 added a
per-statement breadcrumb and routed it through ``milestone(durable=False)``, in
the belief that ``durable=False`` meant "cheap, ring-buffered". It does not: the
flag controls only whether ``fsync`` is called, and the FILE is chosen by
``beat=``, which ``milestone()`` hardcodes to False. So every breadcrumb was
appended and flushed to the milestone stream -- the one the module's own
docstring calls "never trimmed".

The measured cost, from the operator's two diagnostics bundles:

    2026-08-05 03:49   run_logs   76 files     11 MB
    2026-08-06 03:26   run_logs   78 files   1615 MB

One 24 h merge added 1.6 GB. Then ``promote_incomplete_runs`` -- which runs at
BOOT, before the unlock screen -- read it back through a ``_read_jsonl`` that
loaded whole files into a list of dicts, on a 12.5 GB machine with 1 GB of swap.
The app was OOM-killed at startup on every attempt, and a reinstall could not fix
it because a reinstall does not touch ``data/``.

Each test below fails against the code as it shipped.
"""

from __future__ import annotations

import json

import pytest

from src.backup import runlog
from src.backup.runlog import (
    _MILESTONE_CAP_BYTES,
    _has_terminal_event,
    _iter_jsonl,
    _read_jsonl,
    prune_run_logs,
)


@pytest.fixture()
def rl(tmp_path, monkeypatch):
    """A RunLog writing into tmp_path, with no sampler thread running."""
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path)
    log = runlog.RunLog("imp-test-0001", "import")
    log._open()
    yield log
    for fp in (log._m_fp, log._b_fp):
        if fp is not None:
            fp.close()


# --------------------------------------------------------------------------- #
#  F1 -- the in-flight statement is a STORE, not a write
# --------------------------------------------------------------------------- #
def test_publishing_a_statement_writes_nothing(rl) -> None:
    """THE regression. 10,000 statements must not add 10,000 journal lines."""
    before = rl.milestone_path.stat().st_size
    for i in range(10_000):
        rl.statement(f"SELECT {i} FROM articles")
    assert rl.milestone_path.stat().st_size == before, (
        "publishing the in-flight statement must not touch the milestone stream"
    )
    assert rl.beat_path.stat().st_size == 0


def test_the_beat_carries_the_statement_in_flight_with_its_age(rl) -> None:
    """Naming it is the whole point -- it just belongs in the capped stream."""
    rl.statement("INSERT INTO articles SELECT * FROM incoming")
    rec = rl._beat({})
    assert rec["sql"] == "INSERT INTO articles SELECT * FROM incoming"
    assert rec["sql_s"] >= 0.0


def test_a_cleared_statement_leaves_the_beat_silent(rl) -> None:
    """A finished step must not keep showing its last statement as in flight.

    The negative-space twin of the test above: without clearing, every beat
    after a step reads as a stall inside a step that already completed.
    """
    rl.statement("SELECT 1")
    assert "sql" in rl._beat({})
    rl.statement(None)
    rec = rl._beat({})
    assert "sql" not in rec and "sql_s" not in rec


# --------------------------------------------------------------------------- #
#  F4 -- the milestone stream is capped, and says so
# --------------------------------------------------------------------------- #
def test_the_milestone_stream_stops_at_its_cap(rl, monkeypatch) -> None:
    monkeypatch.setattr(runlog, "_MILESTONE_CAP_BYTES", 4096)
    for i in range(2000):
        rl.milestone("noisy", i=i, payload="x" * 200)
    size = rl.milestone_path.stat().st_size
    assert size < 20_000, f"milestone stream grew to {size} bytes past a 4 KB cap"

    body = rl.milestone_path.read_text(encoding="utf-8")
    evs = [json.loads(ln)["ev"] for ln in body.splitlines() if ln]
    assert "milestones_capped" in evs, "a truncated journal must SAY it was truncated"


def test_run_end_survives_the_cap(rl, monkeypatch) -> None:
    """The forensic contract outranks the cap.

    A missing ``run_end`` is how a killed run is recognised. If the cap could eat
    it, every capped run would read as a crashed one -- the cap would spend the
    exact signal it exists to protect.
    """
    monkeypatch.setattr(runlog, "_MILESTONE_CAP_BYTES", 2048)
    for i in range(500):
        rl.milestone("noisy", i=i, payload="y" * 200)
    rl.milestone("run_end", outcome="ok", wall_s=1.0)

    body = rl.milestone_path.read_text(encoding="utf-8")
    evs = [json.loads(ln)["ev"] for ln in body.splitlines() if ln]
    assert evs[-1] == "run_end"


def test_the_cap_is_generous_enough_for_an_ordinary_run(rl) -> None:
    """An over-tight cap would truncate healthy runs -- the mirror failure.

    A large import's real milestones are stage/step/resume events: hundreds, not
    millions. They must fit with room to spare, or this guard trades a crash for
    silently losing evidence from runs that were fine.
    """
    for i in range(2000):
        rl.milestone("stage_end", name=f"merge_step:{i}", seconds=1.5)
    assert rl.milestone_path.stat().st_size < _MILESTONE_CAP_BYTES
    body = rl.milestone_path.read_text(encoding="utf-8")
    assert "milestones_capped" not in body


# --------------------------------------------------------------------------- #
#  F2 -- the reader never materialises a journal
#
#  PR #884 (a sibling session, same field report) made every read STREAM, which
#  is strictly better than the head+tail budget this file originally guarded:
#  O(1) memory AND the whole file, so nothing is elided at all. Those tests are
#  gone with the mechanism they described; what remains is the property.
# --------------------------------------------------------------------------- #
def _big_journal(path, *, lines: int, begin=True, end=True) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        if begin:
            fh.write(json.dumps({"ev": "run_begin", "kind": "import", "t": "T0"}) + "\n")
        for i in range(lines):
            fh.write(json.dumps({"ev": "filler", "i": i, "pad": "z" * 400}) + "\n")
        if end:
            fh.write(json.dumps({"ev": "run_end", "outcome": "ok", "wall_s": 9.0}) + "\n")






def test_a_small_journal_is_read_whole_and_unchanged(tmp_path) -> None:
    """The bound must not alter the ordinary case."""
    p = tmp_path / "imp-small.jsonl"
    _big_journal(p, lines=10)
    recs = _read_jsonl(p)
    assert [r["ev"] for r in recs][:1] == ["run_begin"]
    assert len(recs) == 12
    assert not [r for r in recs if r.get("ev") == "_elided"]



# --------------------------------------------------------------------------- #
#  F3 -- boot does not allocate over the journal directory
# --------------------------------------------------------------------------- #
def test_terminal_event_is_answered_from_the_tail(tmp_path) -> None:
    ended = tmp_path / "a.jsonl"
    _big_journal(ended, lines=40_000, end=True)
    assert _has_terminal_event(ended) is True

    killed = tmp_path / "b.jsonl"
    _big_journal(killed, lines=40_000, end=False)
    assert _has_terminal_event(killed) is False


def test_boot_never_reads_a_finished_journal_whole(tmp_path, monkeypatch) -> None:
    """THE boot fix. A completed run must cost a tail read, not a full parse.

    Mutation check: routing this back through the unbounded reader makes the spy
    fire and this fails.
    """
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path)
    _big_journal(tmp_path / "imp-done.jsonl", lines=40_000, end=True)

    read_calls: list = []
    real = runlog._read_jsonl
    monkeypatch.setattr(
        runlog, "_read_jsonl",
        lambda p, **kw: (read_calls.append(p.name), real(p, **kw))[1],
    )
    runlog.promote_incomplete_runs()
    assert read_calls == [], f"boot fully parsed {read_calls} for a completed run"


def test_boot_still_marks_a_killed_run(tmp_path, monkeypatch) -> None:
    """The negative-space twin: bounding it must not stop it working.

    Without this, a `_has_terminal_event` stubbed to always return True would
    pass the test above while silently retiring the whole forensic marker.
    """
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(runlog, "persist_import_report", None, raising=False)
    p = tmp_path / "imp-killed.jsonl"
    _big_journal(p, lines=50, end=False)

    out = runlog.promote_incomplete_runs()
    assert [r["run_id"] for r in out] == ["imp-killed"]
    assert json.loads(p.read_text(encoding="utf-8").splitlines()[-1])["ev"] == "promoted"


# --------------------------------------------------------------------------- #
#  F4 -- retention
# --------------------------------------------------------------------------- #
def test_prune_keeps_the_newest_runs_and_drops_both_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path)
    for i in range(10):
        (tmp_path / f"imp-2026080{i}T000000Z-aaaa.jsonl").write_text('{"ev":"run_begin"}\n', encoding="utf-8")
        (tmp_path / f"imp-2026080{i}T000000Z-aaaa.beat.jsonl").write_text('{"t":"x"}\n', encoding="utf-8")

    removed = prune_run_logs(keep=3)
    assert len(removed) == 7
    left = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert len(left) == 6, left  # 3 runs x 2 files
    assert not list(tmp_path.glob("*20260800*")), "the oldest run's files must be gone"


def test_reading_a_huge_journal_does_not_materialise_it(tmp_path) -> None:
    """The read side is O(1) in memory at ANY journal size (PR #884's property).

    Guarded here because this file is where the 1.6 GB incident is recorded, and
    a future reader reaching for ``_read_jsonl`` in a boot path is exactly how it
    would come back.

    ``tracemalloc``, NOT ``resource.ru_maxrss`` -- and the first draft of this
    test used ru_maxrss, in the same commit that merged the lesson saying not to.
    Peak RSS is a process HIGH-WATER MARK that never falls, so by the time this
    runs the peak is already set by earlier tests and the delta reads 0 whatever
    the code does: mutation-checked, materialising the whole file with ``list()``
    PASSED it. It is also in BYTES on macOS and KILOBYTES on Linux, so the unit
    was wrong on half the fleet. tracemalloc measures allocation inside the
    window, resets, and is portable -- it measures the actual claim.
    """
    import tracemalloc

    p = tmp_path / "imp-big.jsonl"
    _big_journal(p, lines=60_000)             # ~24 MB on disk
    tracemalloc.start()
    try:
        n = sum(1 for _ in _iter_jsonl(p))
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert n == 60_002
    assert peak < 4 * 1024 * 1024, (
        f"streaming a 24 MB journal allocated {peak / 1e6:.1f} MB — it is being held, "
        "not streamed"
    )
