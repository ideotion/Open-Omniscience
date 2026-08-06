"""The run journal: what it must record, and what it must refuse to claim.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field night 2026-07-31 is the spec. A 686,896-article import sat at
``15/19 · 3000/686896`` for seven hours; "stuck or slow?" took manual ``ps``
sampling over several rounds and the first verdict was wrong; and when the run
was killed it left no report at all. These pin the answers.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.backup import runlog


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path / "run_logs")
    monkeypatch.setenv("OO_RUN_JOURNAL", "1")
    monkeypatch.setattr(runlog, "_BEAT_INTERVAL_S", 0.02)
    runlog._CURRENT = None
    yield
    with pytest.MonkeyPatch.context():
        pass
    cur = runlog._CURRENT
    if cur is not None:
        cur.end("test-teardown")
    runlog._CURRENT = None


def _lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _begin_unsampled(**kw):
    """Begin a run with the background sampler stopped, for tests that drive
    ``_beat()`` by hand and assert on beat-COUNTED state.

    ``begin()`` starts a daemon thread looping ``_beat()`` every
    ``_BEAT_INTERVAL_S``, which the autouse fixture above sets to **0.02 s** --
    so the sampler fires ~50x/second throughout every test here. Its beats
    mutate the SAME per-run state, and ``_child_walk_skip`` is a COUNTER
    decremented once per beat. A test that counts its own explicit beats is
    therefore racing the sampler for that counter: it wins whenever its loop
    finishes inside one 20 ms tick, and loses when a tick lands mid-loop --
    the backoff then appears to end early, or a sampler beat that legitimately
    exceeds the 25 ms budget trips a backoff the test never asked for.

    Observed as a macOS "Portability observation" failure at
    ``test_an_expensive_child_walk_backs_off_and_then_COMES_BACK`` on a run
    whose suite took 878 s, GREEN in the sibling lane on the identical SHA --
    and live-reproduced by letting the sampler tick between the explicit
    beats, which ended the backoff at explicit beat 4 of 8.

    Stopping the sampler removes the race; it weakens no assertion. Tests that
    are ABOUT the sampler (see ``test_the_sampler_keeps_writing_...``) keep
    using ``runlog.begin`` directly.
    """
    rl = runlog.begin(**kw)
    if rl is not None:
        rl._stop.set()
        if rl._sampler is not None:
            rl._sampler.join(timeout=5)
            assert not rl._sampler.is_alive(), "the sampler must not outlive this call"
    return rl


# --------------------------------------------------------------------------- #
#  The forensic contract
# --------------------------------------------------------------------------- #
def test_a_killed_run_leaves_the_stage_it_died_in():
    """THE point of the whole module. A run that never returns still names the
    stage it was in -- which is the diagnosis import #14 could not offer."""
    rl = runlog.begin("import", label="big-backup")
    assert rl is not None
    runlog.milestone("stage_begin", name="prepare_staged:validate")
    # ...and the process dies here. No end(), no report, nothing unwinds.

    recs = _lines(rl.milestone_path)
    assert [r["ev"] for r in recs] == ["run_begin", "stage_begin"]
    assert not any(r["ev"] == "run_end" for r in recs)

    info = runlog.summarise(rl.run_id)
    assert info["complete"] is False
    assert info["died_in_stage"] == "prepare_staged:validate"
    assert info["outcome"] == "incomplete"


def test_a_run_that_died_between_stages_reports_the_last_one_that_finished():
    """Not every second of a run is inside a stage. A null with nothing beside
    it is a dead end; the last stage that COMPLETED is a real measured bound on
    how far it got."""
    rl = runlog.begin("import", label="x")
    with runlog.stage("prepare_staged"):
        pass
    # ...and it dies here, between stages.
    info = runlog.summarise(rl.run_id)
    assert info["died_in_stage"] is None
    assert info["died_after_stage"] == "prepare_staged"


def test_promotion_never_synthesises_a_run_end():
    """The absence of ``run_end`` IS the evidence. Writing one at the next boot
    to mark the journal handled would spend that evidence on the first restart
    -- every crashed run would read as finished from then on."""
    rl = runlog.begin("import", label="x")
    runlog.milestone("stage_begin", name="merge")
    rl._stop.set()  # stop sampling; simulate a kill by never calling end()

    promoted = runlog.promote_incomplete_runs()
    assert [p["run_id"] for p in promoted] == [rl.run_id]

    recs = _lines(rl.milestone_path)
    assert not any(r["ev"] == "run_end" for r in recs), (
        "promotion must use a DISTINCT event, never the token whose absence is the signal"
    )
    assert recs[-1]["ev"] == "promoted"
    assert recs[-1]["outcome"] == "incomplete"
    # ...and it is idempotent: a second boot does not append a second marker.
    assert runlog.promote_incomplete_runs() == []
    assert len(_lines(rl.milestone_path)) == len(recs)


def test_promotion_refuses_to_call_it_a_crash():
    """A journal disabled mid-run (ENOSPC on the sidecar's own disk) leaves the
    IDENTICAL signature to a hard kill. Asserting "crashed" would be a
    diagnosis we cannot make from the file."""
    rl = runlog.begin("import", label="x")
    rl._stop.set()
    runlog.promote_incomplete_runs()
    line = _lines(rl.milestone_path)[-1]
    assert "crash" not in json.dumps(line).lower()
    assert "disabled" in line["reason"]


def test_a_run_that_finished_with_a_muted_journal_says_so():
    """The inverse: a run that DID complete while its journal was muted must not
    be retroactively minted a crash by the next boot."""
    rl = runlog.begin("import", label="x")
    rl._disable("beats", OSError("No space left on device"))
    rl.end("ok")
    recs = _lines(rl.milestone_path)
    assert recs[-1]["ev"] == "run_end"
    assert recs[-1]["journal_truncated"] is True
    assert runlog.promote_incomplete_runs() == []


# --------------------------------------------------------------------------- #
#  "Stuck or slow?" -- the signals, and what they refuse to say
# --------------------------------------------------------------------------- #
def test_moving_is_never_emitted_for_a_phase_that_has_no_counter():
    """THE honesty defect this module was reviewed for.

    ``prepare_staged`` is 54% of a large import and publishes a phase and
    nothing else. A rule of "d_done == 0 means not moving" would emit
    ``moving: false`` for ninety minutes of perfectly healthy work -- a
    fabricated stall verdict in the exact field built to answer "stuck?"."""
    rl = runlog.begin("import", label="x")
    rl.progress({"phase": "reassembling"})  # no counter, like the real one
    b1 = rl._beat({})
    b2 = rl._beat(b1)
    for b in (b1, b2):
        assert "moving" not in b
        assert b["counter"] == "none-in-this-phase"
        assert "done" not in b


def test_moving_is_emitted_once_two_samples_read_the_same_real_counter():
    rl = runlog.begin("import", label="x")
    rl.progress({"phase": "reindexing", "reindex_done": 3000, "reindex_total": 686896})
    b1 = rl._beat({})
    assert b1["counter"] == "reindex"
    assert b1["done"] == 3000 and b1["total"] == 686896
    assert "moving" not in b1, "one sample is not a delta"

    b2 = rl._beat(b1)
    assert b2["moving"] is False and b2["d_done"] == 0

    rl.progress({"phase": "reindexing", "reindex_done": 3100, "reindex_total": 686896})
    b3 = rl._beat(b2)
    assert b3["moving"] is True and b3["d_done"] == 100


def test_the_counter_keys_are_the_ones_the_app_actually_publishes():
    """There is no generic done/total anywhere in the tree. Assuming one would
    make every counter read as absent on every path, forever."""
    import inspect

    from src.backup import volume_job

    # ...and they are the ones VolumeBackupManager really publishes, so a rename
    # there reddens here instead of silently blinding every counter.
    src = inspect.getsource(volume_job.VolumeBackupManager._run_restore)
    for _, done_k, total_k in runlog._COUNTER_SOURCES:
        assert f'"{done_k}"' in src and f'"{total_k}"' in src, done_k

    assert runlog._counter_of({"reindex_done": 5, "reindex_total": 9}) == ("reindex", 5, 9)
    assert runlog._counter_of({"merge_step": 3, "merge_steps": 14}) == ("merge", 3, 14)
    assert runlog._counter_of({"done": 5, "total": 9}) == (None, None, None)
    assert runlog._counter_of({"phase": "verifying"}) == (None, None, None)
    assert runlog._counter_of(None) == (None, None, None)


def test_the_beat_carries_child_cpu_because_the_parent_alone_cannot_answer():
    """During the re-index the work runs in a process pool, so a HEALTHY parent
    is also near-idle -- identical to the deadlocked case. Only the children's
    cumulative CPU discriminates, and the delta must be precomputed: making a
    human subtract two of 1,700 lines is the manual ps sampling this replaces."""
    rl = runlog.begin("import", label="x")
    b1 = rl._beat({})
    b2 = rl._beat(b1)
    assert "cpu_s" in b1 and "kids_cpu_s" in b1 and "kids_n" in b1
    assert "d_cpu_s" in b2 and "d_kids_cpu_s" in b2
    assert "bc_ms" in b1, "the beat's own cost is measured, never assumed"


def test_an_unmeasurable_field_is_omitted_with_a_reason_never_zeroed(monkeypatch):
    """``kids_n: 0`` reads as "no worker processes" -- the exact inverse of the
    deadlock evidence it would be standing in for. AccessDenied on a hardened
    kernel, or a racing worker exit, must therefore omit."""
    rl = runlog.begin("import", label="x")

    def _boom(proc, limit=24):
        raise PermissionError("AccessDenied")

    monkeypatch.setattr(runlog, "_sample_children", _boom)
    b = rl._beat({})
    assert "kids_n" not in b and "kids_cpu_s" not in b
    assert any("kids" in u for u in b["unmeasured"])


def test_an_expensive_child_walk_backs_off_and_then_COMES_BACK(monkeypatch):
    """THE FIELD BUG. This used to be a one-way latch, and it was tripped by the
    WHOLE beat's cost -- so in a 19 h import a single 25.9 ms beat during `merging`
    (0.9 ms over budget) blinded every one of the following 1,561 `reindexing`
    beats. That inverts the instrument: the re-index is the phase child CPU exists
    to measure, because a healthy process pool leaves the parent near-idle and
    parent CPU alone cannot tell a working pool from a wedged one."""
    rl = _begin_unsampled(kind="import", label="x")
    real = runlog._sample_children
    slow = {"on": True}

    def _slow(proc, limit=24):
        if slow["on"]:
            time.sleep((runlog._CHILD_WALK_BUDGET_MS + 10) / 1000.0)
        return real(proc, limit)

    monkeypatch.setattr(runlog, "_sample_children", _slow)

    # The expensive walk still REPORTS -- it is stood down after paying, not instead.
    b = rl._beat({})
    assert b["kids_n"] >= 0 and b["child_walk"] == "backoff-cost"
    assert b["kids_ms"] > runlog._CHILD_WALK_BUDGET_MS, "the cost is measured, not assumed"

    # ...then skips a bounded number of beats, saying so rather than going quiet.
    slow["on"] = False
    for _ in range(runlog._CHILD_WALK_BACKOFF_BEATS):
        skipped = rl._beat({})
        assert "kids_n" not in skipped, "a backoff must not fabricate a zero"
        assert skipped["child_walk"] == "backoff"
        assert any("kids" in u for u in skipped["unmeasured"])

    # ...and RESUMES. Without this the run is blind for every later phase.
    back = rl._beat({})
    assert "kids_n" in back and "kids_cpu_s" in back
    assert back.get("child_walk") is None


def test_the_walk_is_charged_for_ITS_cost_not_the_whole_beats(monkeypatch):
    """A beat also reads /proc/meminfo, stats the destination filesystem and sizes
    the WAL. Charging the child walk for a slow disk stat retires the one
    measurement that answers "stuck or slow?" for a reason unrelated to it -- which
    is exactly how the field run lost it during `merging`."""
    rl = _begin_unsampled(kind="import", label="x")

    import psutil as _ps

    _real_vm = _ps.virtual_memory

    def _slow_unrelated():
        time.sleep((runlog._CHILD_WALK_BUDGET_MS + 20) / 1000.0)
        return _real_vm()

    monkeypatch.setattr(_ps, "virtual_memory", _slow_unrelated)

    b = rl._beat({})
    assert b["bc_ms"] > runlog._CHILD_WALK_BUDGET_MS, "the beat really was slow"
    # ...and the walk, which was cheap, is neither disabled nor backed off.
    assert "kids_n" in b and b.get("child_walk") is None
    b2 = rl._beat(b)
    assert "kids_n" in b2, "an unrelated slow probe must not cost the child walk"


def test_a_rate_needs_two_samples_and_a_nonzero_window():
    rl = runlog.begin("import", label="x")
    rl.end("ok")
    info = runlog.summarise(rl.run_id)
    assert "recent" not in info
    assert "needs two" in info["recent_unavailable"]


def test_the_span_is_anchored_on_the_last_observed_beat():
    """Not on "now", and not on a promotion line written at the next boot: a
    40-minute stall must not read as three days because the machine was off."""
    rl = runlog.begin("import", label="x")
    rl.progress({"phase": "merging", "merge_step": 1, "merge_steps": 14})
    deadline = time.monotonic() + 3.0
    while rl._beats_written < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    rl._stop.set()
    beats = _lines(rl.beat_path)
    assert beats, "the sampler must have written at least one beat"
    info = runlog.summarise(rl.run_id)
    assert info["last_seen_at"] == beats[-1]["t"]
    assert info["last_phase"] == "merging"


# --------------------------------------------------------------------------- #
#  Safety: the journal must never break, block, or deadlock the run
# --------------------------------------------------------------------------- #
def test_the_sampler_keeps_writing_while_the_main_thread_is_wedged():
    """The flagship scenario. Tonight the parent blocked in ``pool.map`` with no
    exception to catch; a journal that only writes from the wedged thread would
    have recorded exactly nothing about the seven hours that followed."""
    rl = runlog.begin("import", label="x")
    rl.progress({"phase": "reindexing", "reindex_done": 3000, "reindex_total": 686896})
    wedged = threading.Event()

    def _deadlocked_worker():
        wedged.set()
        time.sleep(1.0)  # stands in for a pool.map that never returns

    t = threading.Thread(target=_deadlocked_worker, daemon=True)
    t.start()
    wedged.wait(2.0)
    deadline = time.monotonic() + 3.0
    while rl._beats_written < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    rl._stop.set()
    assert rl._beats_written >= 2, "the heartbeat must survive a wedged main thread"


def test_beats_and_milestones_do_not_share_a_lock():
    """A blocked write on one stream must not stall the other -- they are
    written by different threads with different failure modes."""
    rl = runlog.begin("import", label="x")
    assert rl._m_lock is not rl._b_lock
    rl._m_lock.acquire()
    try:
        # A beat must still complete while the milestone lock is held.
        done = threading.Event()
        threading.Thread(
            target=lambda: (rl._write({"x": 1}, beat=True, durable=False), done.set()),
            daemon=True,
        ).start()
        assert done.wait(2.0), "a beat blocked on the milestone stream's lock"
    finally:
        rl._m_lock.release()


def test_a_write_failure_disables_the_stream_and_never_raises():
    """A resilience sidecar that can abort a ten-hour import is worse than no
    sidecar."""
    rl = runlog.begin("import", label="x")

    class _Broken:
        def write(self, *_a):
            raise OSError("No space left on device")

        def flush(self):
            pass

        def close(self):
            pass

    rl._m_fp = _Broken()
    rl.milestone("stage_begin", name="merge")  # must not raise
    assert rl._m_off is True
    rl.milestone("stage_end", name="merge")  # a no-op now, still silent
    assert rl._disabled_reasons


def test_the_journal_never_refuses_to_let_a_run_start(monkeypatch):
    """begin() is the first line of a ten-hour import. A sidecar that can stop
    the operation from starting is the worst version of the failure mode this
    whole module is written to avoid."""
    monkeypatch.setattr(
        runlog, "run_logs_dir", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert runlog.begin("import", label="x") is None
    assert runlog.active() is None, "a failed begin must not leave a half-open run"
    runlog.milestone("stage_begin", name="still-runs")  # no-op, no crash
    runlog.progress({"phase": "x"})


def test_a_forked_child_can_never_write_to_the_parents_journal(monkeypatch):
    """The re-index forks a pool. A child writing through an inherited handle
    interleaves garbage; a child BLOCKING on an inherited lock is tonight's
    deadlock, reintroduced by the journal built to diagnose it. The PID guard is
    checked BEFORE the lock for exactly that reason."""
    rl = runlog.begin("import", label="x")
    before = len(_lines(rl.milestone_path))
    monkeypatch.setattr(runlog.os, "getpid", lambda: rl._pid + 1)
    rl._m_lock.acquire()  # as an unrelated thread would have held it across fork
    try:
        rl.milestone("stage_begin", name="in-the-child")  # must return, not block
    finally:
        rl._m_lock.release()
    assert len(_lines(rl.milestone_path)) == before


def test_fork_hooks_leave_the_locks_usable_in_both_processes():
    rl = runlog.begin("import", label="x")
    runlog._before_fork()
    runlog._after_fork_parent()
    assert rl._m_lock.acquire(blocking=False)
    rl._m_lock.release()

    runlog._before_fork()
    runlog._after_fork_child()
    assert rl._m_off and rl._b_off, "the child's journal is disabled outright"
    assert rl._m_lock.acquire(blocking=False)
    rl._m_lock.release()


def test_progress_is_two_stores_on_a_seven_hundred_thousand_call_path():
    """Called once per merged article. It must not lock, allocate, read a clock
    or touch the disk."""
    import inspect

    src = inspect.getsource(runlog.RunLog.progress)
    body = src.split('"""', 2)[-1]
    assert "self._prog = p" in body and "self._prog_seq += 1" in body
    for forbidden in ("lock", "time.", "json", "write", "copy("):
        assert forbidden not in body, f"progress() must not {forbidden}"


def test_a_second_concurrent_run_is_refused_and_logged(caplog):
    """An ambient handle means an implicit singleton. A genuinely concurrent
    second begin must never steal the slot from the run already writing."""
    first = runlog.begin("import", label="a")
    with caplog.at_level("WARNING"):
        second = runlog.begin("import", label="b")
    assert second is None
    assert runlog.active() is first
    assert "refusing a concurrent" in caplog.text


def test_secrets_are_scrubbed_out_of_milestone_fields():
    rl = runlog.begin("import", label="x", passphrase="hunter2", nested={"api_key": "abc"})
    text = rl.milestone_path.read_text(encoding="utf-8")
    assert "hunter2" not in text and "abc" not in text
    assert "***redacted***" in text


def test_journalling_is_on_by_default_with_nothing_configured(monkeypatch):
    """Maintainer ruling 2026-07-31: automated / default.

    An opt-in journal is off precisely on the run worth diagnosing -- nobody
    enables a flight recorder for the flight they expect to be uneventful. So
    the default is ON with no setting touched, and the escape hatch is the
    thing you have to ask for."""
    monkeypatch.delenv("OO_RUN_JOURNAL", raising=False)
    assert runlog.journal_enabled() is True
    rl = runlog.begin("import", label="x")
    assert rl is not None
    rl.end("ok")


def test_journalling_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("OO_RUN_JOURNAL", "0")
    assert runlog.begin("import", label="x") is None
    runlog.milestone("stage_begin", name="nothing")  # no-op, no crash
    runlog.progress({"phase": "x"})


def test_every_import_and_export_opens_a_run_without_being_asked_to():
    """Automated means no button: the two entry points the operator actually
    uses -- and therefore the import QUEUE, which drives start_restore -- open a
    journal themselves."""
    import inspect

    from src.backup import import_queue, volume_job

    for fn in (volume_job.VolumeBackupManager._run_restore,
               volume_job.VolumeBackupManager._run_backup):
        assert 'runlog.begin(' in inspect.getsource(fn), fn.__name__
    # The queue does not need its own call: each item goes through start_restore,
    # so each item gets its OWN run (eight 10-hour imports under one run_id would
    # wrap the beat ring and lose the early hours of all but the last).
    assert "start_restore(" in inspect.getsource(import_queue.ImportQueueManager._run_corpus)


def test_every_long_import_export_worker_journals_no_exceptions():
    """THE ratchet behind "automated / default".

    The first cut covered the volume import/export -- the path the maintainer's
    17 GB actually takes -- and left three others silent: the large-data folder
    backup/restore/verify, the single-shot REST commit (which wires NO progress
    callbacks at all, making it the least observable import path in the app),
    and the .eml folder import. A journal with exceptions is a journal you have
    to remember the shape of, which is the same failure as not having one.

    Listed by hand ON PURPOSE: a new long-running import/export worker should
    have to add itself here, and notice why.
    """
    import inspect

    from src.api import backup_v2
    from src.backup import folder_backup, volume_job
    from src.ingest import import_job

    workers = [
        volume_job.VolumeBackupManager._run_restore,
        volume_job.VolumeBackupManager._run_backup,
        folder_backup.FolderBackupManager._run_backup,
        folder_backup.FolderBackupManager._run_restore,
        folder_backup.FolderBackupManager._run_verify,
        import_job.NewsletterImportManager._run,
        backup_v2._commit_sync,
        backup_v2.restore_legacy_path,
    ]
    for fn in workers:
        src = inspect.getsource(fn)
        assert "runlog.run(" in src or "runlog.begin(" in src, (
            f"{fn.__qualname__} runs an import/export and does not open a run journal"
        )


def test_the_run_contextmanager_closes_the_journal_however_the_block_ends():
    """Hand-wired begin/end means every exit path is a fresh chance to forget --
    and the forgotten ones are the unusual paths, which are exactly the ones
    worth a journal."""
    with runlog.run("verify", label="ok-path"):
        pass
    assert runlog.list_runs()[0]["outcome"] == "ok"

    # Looked up BY LABEL, not by position: these runs all start within the same
    # second, so "newest first" is a genuine tie and asserting an order would
    # pin nothing.
    def _by_label(label):
        return next(r for r in runlog.list_runs() if r["label"] == label)

    with pytest.raises(RuntimeError), runlog.run("verify", label="raising"):
        raise RuntimeError("boom")
    top = _by_label("raising")
    assert top["outcome"] == "error"
    info = runlog.summarise(top["run_id"])
    assert info["errors"] and info["errors"][0]["cls"] == "RuntimeError"

    # An explicit outcome inside the block always wins over the generic one.
    with runlog.run("verify", label="cancelled"):
        runlog.end("cancelled", reason="operator stop")
    assert _by_label("cancelled")["outcome"] == "cancelled"
    assert _by_label("ok-path")["outcome"] == "ok"


def test_every_kind_gets_a_distinguishable_run_id_and_an_unknown_one_still_records():
    """Refusing to record an operation because its name is unfamiliar would be
    the coverage gap the prefix table exists to close."""
    seen = set()
    for kind in runlog._KIND_PREFIX:
        rl = runlog.begin(kind, label="x")
        assert rl is not None
        seen.add(rl.run_id.split("-", 1)[0])
        rl.end("ok")
        runlog._CURRENT = None
    assert len(seen) == len(runlog._KIND_PREFIX), "two kinds share a prefix"

    rl = runlog.begin("some-future-thing", label="x")
    assert rl is not None and rl.run_id.startswith("run-")
    rl.end("ok")


def test_the_journal_rides_the_all_diagnostics_bundle_automatically():
    """The operator's existing one-button download carries it -- no separate
    export step to remember, and no new place to look."""
    import inspect

    from src.api import diagnostics

    src = inspect.getsource(diagnostics._all_diagnostics_members)
    assert '"run-journal.json"' in src and '"run-journal-raw.json"' in src


def test_incomplete_runs_are_marked_at_boot_before_any_unlock():
    """"What happened to last night's import?" is asked on a locked store, by an
    operator who came back to a dead app. Promotion reads only files under
    data_dir(), so it must not sit behind the database."""
    import inspect

    from src.api import main as api_main

    src = inspect.getsource(api_main.lifespan)
    assert "promote_incomplete_runs()" in src, (
        "promotion must run on the lifespan (pre-unlock) path, not in the DB upkeep"
    )
    # ...and BEFORE the lock check, or a locked store never reaches it.
    assert src.index("promote_incomplete_runs()") < src.index("app_lock_state()")
    assert "promote_incomplete_runs()" not in inspect.getsource(api_main._run_startup_upkeep)


# --------------------------------------------------------------------------- #
#  Wiring
# --------------------------------------------------------------------------- #
def test_a_substage_reaches_the_journal_but_never_the_phase_counter():
    """``StageTimings.stage()`` also fires the user-visible phase ping, so a
    sub-stage could not use it (3bd990a) -- and bare ``record()`` is END-only, so
    a run killed inside ``prepare_staged:validate`` left no trace of it. ``sub()``
    is the third option: journal gets the begin, the phase counter does not."""
    from src.backup.timing import StageTimings

    phases: list[str] = []
    events: list[tuple] = []
    t = StageTimings(
        on_start=phases.append, sink=lambda k, n, s: events.append((k, n))
    )
    with t.sub("prepare_staged:validate"):
        pass
    assert phases == [], "a sub-stage must never be pinged as a user-visible phase"
    assert events == [("begin", "prepare_staged:validate"), ("end", "prepare_staged:validate")]

    with t.stage("merge"):
        pass
    assert phases == ["merge"]
    assert events[-2:] == [("begin", "merge"), ("end", "merge")]


def test_a_raising_journal_sink_never_breaks_the_timed_work():
    from src.backup.timing import StageTimings

    def _boom(*_a):
        raise RuntimeError("journal is on fire")

    t = StageTimings(sink=_boom)
    with t.sub("x"):
        pass
    assert t.report()["stages"]["x"] >= 0


def test_the_restore_path_opens_and_closes_a_run(monkeypatch, tmp_path):
    from src.backup.volume_job import VolumeBackupManager

    src = tmp_path / "backup"
    src.mkdir()
    m = VolumeBackupManager()
    m.start_restore(str(src), "pw", _restore_fn=lambda *_a, **_k: {"ok": True})
    m._thread.join(timeout=5)
    runs = runlog.list_runs()
    assert len(runs) == 1
    assert runs[0]["kind"] == "import"
    assert runs[0]["outcome"] == "ok"
    assert runs[0]["complete"] is True


def test_a_failing_restore_records_the_error_and_the_outcome(tmp_path):
    from src.backup.volume_job import VolumeBackupManager

    src = tmp_path / "backup"
    src.mkdir()

    def _boom(*_a, **_k):
        raise RuntimeError("merge exploded")

    m = VolumeBackupManager()
    m.start_restore(str(src), "pw", _restore_fn=_boom)
    m._thread.join(timeout=5)
    info = runlog.summarise(runlog.list_runs()[0]["run_id"])
    assert info["outcome"] == "error"
    assert info["errors"] and info["errors"][0]["cls"] == "RuntimeError"


def test_the_export_path_is_journalled_too(tmp_path):
    """The maintainer's own framing: "export seems to work fine" -- which is
    unfalsifiable while its only two numbers never leave the process."""
    from src.backup.volume_job import VolumeBackupManager

    dest = tmp_path / "out"
    m = VolumeBackupManager()
    m.start_backup(
        str(dest), "pw",
        _backup_fn=lambda *_a, **_k: {"volumes": 3, "wall_s": 1.5, "gate_held_s": 0.2},
    )
    m._thread.join(timeout=5)
    runs = runlog.list_runs()
    assert runs and runs[0]["kind"] == "export" and runs[0]["outcome"] == "ok"
    end = _lines(runlog.run_logs_dir() / f"{runs[0]['run_id']}.jsonl")[-1]
    assert end["volumes"] == 3 and end["gate_held_s"] == 0.2 and end["engine_wall_s"] == 1.5


# --------------------------------------------------------------------------- #
#  A crashed run's persisted report must not read as a successful one
# --------------------------------------------------------------------------- #
def test_an_incomplete_report_never_headlines_a_success():
    """The plan is computed BEFORE the commit point, so an aborted run carries
    one. Headlining it printed "**686,896 new articles**" at the top of a run
    that committed nothing -- on the artefact a human actually opens."""
    from src.backup.import_reports import render_import_report_markdown

    md = render_import_report_markdown({
        "outcome": "incomplete",
        "died_in_stage": "merge",
        "plan": {"articles": {"new": 686896, "duplicate": 0}},
    })
    assert "did not complete" in md
    assert "686,896 new articles**" not in md
    assert "were planned" in md and "NOT merged" in md
    assert md.index("did not complete") < md.index("686,896")


def test_a_committed_report_still_reads_exactly_as_before():
    from src.backup.import_reports import render_import_report_markdown

    md = render_import_report_markdown({"plan": {"articles": {"new": 12, "duplicate": 3}}})
    assert "**12 new articles** (3 duplicates skipped)" in md
    assert "did not complete" not in md


def test_the_listing_surfaces_the_outcome(tmp_path, monkeypatch):
    """``kind`` cannot carry it: "restore-partial-…" splits to kind "restore",
    identical to a fully-committed one."""
    from src.backup import import_reports

    d = tmp_path / "import_reports"
    monkeypatch.setattr(import_reports, "_reports_dir", lambda: d)
    import_reports.persist_import_report("restore", {"plan": {}}, run_id="aaa")
    import_reports.persist_import_report(
        "restore", {"outcome": "incomplete"}, run_id="bbb"
    )
    got = {r["filename"].split("-")[-1]: r["outcome"] for r in import_reports.list_import_reports()}
    assert got == {"aaa.json": "ok", "bbb.json": "incomplete"}


def test_an_unreadable_report_is_unknown_never_ok(tmp_path, monkeypatch):
    from src.backup import import_reports

    d = tmp_path / "import_reports"
    d.mkdir(parents=True)
    monkeypatch.setattr(import_reports, "_reports_dir", lambda: d)
    (d / "restore-20260731T000000Z-zzz.json").write_text("{ torn", encoding="utf-8")
    assert import_reports.list_import_reports()[0]["outcome"] == "unknown"


# --------------------------------------------------------------------------- #
# Reading a journal must not cost what it cost to write one (2026-08-06).
#
# Field report: the app was SIGKILLed between "Waiting for application startup"
# and the unlock page. `promote_incomplete_runs` runs there, on every boot,
# BEFORE unlock -- and it read every journal into a list of dicts. A journal's
# size is proportional to how much there was to diagnose, so the worse the
# incident, the more likely the app died trying to tell you about it. Measured
# on a 28 MB journal: +243 MB of RSS, 9x the file.
# --------------------------------------------------------------------------- #
def _write_journal(d, run_id, *, beats=0, ended=False, stage="merge", milestones=0):
    """``milestones`` pads the MILESTONE file, which is a separate cost from the
    beat file: the field run journal carried a ``merge_sql:`` line per statement,
    so both files grow with the incident and each is read by a different call."""
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{run_id}.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ev": "run_begin", "t": "T0", "kind": "import"}) + "\n")
        fh.write(json.dumps({"ev": "stage_begin", "t": "T1", "name": stage}) + "\n")
        for i in range(milestones):
            # A record type the summary does not AGGREGATE, on purpose: padding with
            # 30,000 distinct stage names would build a genuinely large `stages` dict,
            # and the test would then be measuring an aggregate the summary is supposed
            # to report rather than the cost of reading the file.
            fh.write(json.dumps({
                "ev": "progress", "t": f"T{i}", "i": i, "pad": "x" * 200,
            }, separators=(",", ":")) + "\n")
        if ended:
            fh.write(json.dumps({"ev": "stage_end", "t": "T2", "name": stage,
                                 "seconds": 1.5}) + "\n")
            fh.write(json.dumps({"ev": "run_end", "t": "T3", "outcome": "ok",
                                 "wall_s": 2.0}) + "\n")
    if beats:
        with (d / f"{run_id}.beat.jsonl").open("w", encoding="utf-8") as fh:
            for i in range(beats):
                fh.write(json.dumps({
                    "ev": "beat", "t": f"T{i}", "el_s": float(i), "phase": "reindexing",
                    "done": i * 10, "counter": "reindex_done", "d_cpu_s": 1.0,
                    "kids_cpu_s": [1.0] * 8, "pad": "x" * 200,
                }, separators=(",", ":")) + "\n")


def test_the_boot_pass_does_not_hold_a_journal_in_memory(tmp_path):
    """The property, measured rather than asserted about the code shape.

    tracemalloc, NOT ``ru_maxrss``: the first draft of this test used the latter and
    was VACUOUS -- peak RSS is a process high-water mark that never shrinks, so by
    the time this runs the peak is already set by earlier tests and the delta is 0
    whatever the code does. Reverting the fix left it green. tracemalloc measures
    the allocations made INSIDE the window and resets, which is the actual claim."""
    import tracemalloc

    d = runlog.run_logs_dir()
    # BOTH files large, deliberately: the boot pass reads the milestone file to
    # decide whether the run finished, and summarise reads the beat file. A fixture
    # that only grew one of them leaves the other's whole-file read undetectable.
    _write_journal(d, "imp-20260806T050000Z-big", beats=40000, milestones=30000)
    size = (d / "imp-20260806T050000Z-big.jsonl").stat().st_size
    beats_size = (d / "imp-20260806T050000Z-big.beat.jsonl").stat().st_size
    assert size > 5_000_000, "the milestone file must be big enough for its cost to show"
    assert beats_size > 8_000_000, "the fixture must be big enough for the old cost to show"

    tracemalloc.start()
    try:
        runlog.promote_incomplete_runs()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    # Either file read whole lands far above this; streaming both lands near zero.
    assert peak < 2_000_000, (
        f"boot allocated {peak / 1e6:.1f} MB for a {beats_size / 1e6:.0f} MB journal -- "
        "reading it whole is what let a big incident stop the app from starting"
    )


def test_summarise_reports_the_real_beat_count_not_its_window(tmp_path):
    """The trap in the fix: keeping only the last N beats and then reporting
    `len(beats)` would cap every long run at N and read as a short one."""
    d = runlog.run_logs_dir()
    n = runlog._SUMMARY_BEAT_WINDOW * 7 + 3
    _write_journal(d, "imp-20260806T050000Z-count", beats=n)
    out = runlog.summarise("imp-20260806T050000Z-count")
    assert out["beats"] == n, "the count is the file's, not the retained window's"


def test_summarise_still_names_where_an_incomplete_run_died(tmp_path):
    """The negative-space twin: streaming must not cost the verdicts. A fix that
    simply read less and answered less would pass the memory test above."""
    d = runlog.run_logs_dir()
    _write_journal(d, "imp-20260806T050000Z-dead", beats=25)
    out = runlog.summarise("imp-20260806T050000Z-dead")
    assert out["complete"] is False
    assert out["outcome"] == "incomplete"
    assert out["died_in_stage"] == "merge"
    assert out["last_phase"] == "reindexing", "the last beat still reaches the summary"
    assert out["recent"]["samples"] == runlog._SUMMARY_BEAT_WINDOW


def test_a_completed_run_still_summarises_as_completed(tmp_path):
    d = runlog.run_logs_dir()
    _write_journal(d, "imp-20260806T050000Z-ok", beats=3, ended=True)
    out = runlog.summarise("imp-20260806T050000Z-ok")
    assert out["complete"] is True and out["outcome"] == "ok"
    assert out["stages"] == {"merge": 1.5}
    assert out["wall_s"] == 2.0
    assert "died_in_stage" not in out


def test_a_finished_run_is_never_promoted_and_the_scan_stops_at_the_marker(tmp_path):
    d = runlog.run_logs_dir()
    _write_journal(d, "imp-20260806T050000Z-done", beats=2, ended=True)
    runlog.promote_incomplete_runs()
    evs = [r.get("ev") for r in _lines(d / "imp-20260806T050000Z-done.jsonl")]
    assert "promoted" not in evs


def test_promotion_happens_once_not_on_every_boot(tmp_path):
    d = runlog.run_logs_dir()
    _write_journal(d, "imp-20260806T050000Z-once", beats=2)
    runlog.promote_incomplete_runs()
    runlog.promote_incomplete_runs()
    evs = [r.get("ev") for r in _lines(d / "imp-20260806T050000Z-once.jsonl")]
    assert evs.count("promoted") == 1


def test_raw_runs_bounds_beats_while_reading_and_states_what_it_dropped(tmp_path):
    d = runlog.run_logs_dir()
    _write_journal(d, "imp-20260806T050000Z-raw", beats=500)
    out = runlog.raw_runs(max_runs=4, max_beats=20)
    entry = out["imp-20260806T050000Z-raw"]
    assert len(entry["beats"]) == 20
    assert entry["beats_omitted"] == 480, "the omission counts the FILE, not the window"
    assert entry["beats"][-1]["el_s"] == 499.0, "the retained window is the NEWEST beats"


def test_listing_runs_does_not_hold_every_journal_in_memory(tmp_path):
    """`list_runs` wants three records per file and is not capped at 50 like the
    boot pass, so on a machine with a long history it was the biggest read here."""
    import tracemalloc

    d = runlog.run_logs_dir()
    for i in range(3):
        _write_journal(d, f"imp-20260806T05000{i}Z-list", beats=5,
                       milestones=12000, ended=True)
    total = sum(p.stat().st_size for p in d.glob("*.jsonl")
                if not p.name.endswith(".beat.jsonl"))
    assert total > 5_000_000, "the fixture must be big enough for the old cost to show"

    tracemalloc.start()
    try:
        runs = runlog.list_runs()
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert len(runs) == 3, "and it still lists them"
    assert all(r["complete"] for r in runs)
    assert peak < 2_000_000, (
        f"listing allocated {peak / 1e6:.1f} MB for {total / 1e6:.0f} MB of journals"
    )
