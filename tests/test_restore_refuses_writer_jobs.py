"""A committing restore refuses while a registered background job that commits to the corpus is running (R659, queue item 21 option B
reduced).

Everything such a job commits between the restore's working copy and the swap is discarded by the swap, so the restore refuses and names
the job instead of losing what it writes. ONE list: the registry's own ``is_writer`` flags, read by both the restore and the task manager's
"another job is writing" ask (``db_writers_busy`` in ``api/jobs.py``), never a second hand-kept copy. A job whose stop loses nothing
(``stops_for_restore``: the re-index drain, which resumes from its watermark and which the import starts again) is STOPPED by the restore,
with one bounded wait, and named only if it is still running after it. The check runs before the backup is staged (the volume restore and
the single-file restore), before ``run_restore`` prepares anything, and again at the working copy; the import page asks the same question
(``import_refused`` on ``/api/jobs``) before it offers to start.
"""

from __future__ import annotations

import ast
import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.jobs import background as bg
from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    """The real registry, emptied for the test and given back afterwards; the restore's set of stopped kinds starts and ends empty."""
    from src.backup import merge

    with bg._REG_LOCK:
        saved = dict(bg._REGISTRY)
        bg._REGISTRY.clear()
    with merge._STOPPED_LOCK:
        merge._STOPPED_FOR_RESTORE.clear()
    yield
    with merge._STOPPED_LOCK:
        merge._STOPPED_FOR_RESTORE.clear()
    with bg._REG_LOCK:
        bg._REGISTRY.clear()
        bg._REGISTRY.update(saved)
        bg._STOPS_SEEN_AT_YIELD.clear()


def _running(kind: str, label: str, *, is_writer: bool = True, stops: bool = False):
    """A registered job whose worker runs until the returned event is set, or, when it is stoppable, until it is asked to stop."""
    release = threading.Event()
    started = threading.Event()

    def worker(ctx):
        started.set()
        while not release.wait(0.01):
            if stops and (ctx.stopping or ctx.yielding):
                return

    job = bg.register_job(bg.BackgroundJob(kind, label, worker, is_writer=is_writer, cancellable=stops, stops_for_restore=stops))
    job.start()
    assert started.wait(5)
    return job, release


def test_the_list_is_the_registry_flags_and_names_only_what_runs(registry):
    writer, r1 = _running("w", "Writing things")
    reader, r2 = _running("r", "Reading things", is_writer=False)
    stoppable, r3 = _running("s", "Stoppable writer", stops=True)
    try:
        assert bg.running_writer_jobs() == [("w", "Writing things"), ("s", "Stoppable writer")]
        # what a restore would still refuse for, read without stopping anything (the import page's question)
        assert bg.running_writer_jobs(include_stoppable=False) == [("w", "Writing things")]
        assert stoppable._alive(), "reading the list stops nothing"
    finally:
        for ev in (r1, r2, r3):
            ev.set()
        for job in (writer, reader, stoppable):
            job.join(5)
    assert bg.running_writer_jobs() == [], "a job that has ended is not named"


def test_stops_for_restore_needs_a_cancellable_job():
    """A job that cannot be asked to stop is never treated as one the restore stops: it would wait out the bound and then refuse anyway."""
    job = bg.BackgroundJob("x", "x", lambda ctx: None, is_writer=True, cancellable=False, stops_for_restore=True)
    assert job.stops_for_restore is False


def _refused(monkeypatch, *, commit: bool):
    """Run ``run_restore`` far enough to see whether it refuses; the first real step is replaced by a sentinel."""
    from src.backup import merge

    class Reached(Exception):
        pass

    def reached(*a, **k):
        raise Reached

    monkeypatch.setattr(merge, "prepare_staged_corpus", reached)
    monkeypatch.setattr(merge, "_STOP_FOR_RESTORE_S", 5.0)
    staged = SimpleNamespace(stage_a_timings={}, staging_dir=Path("/nonexistent"), kind="volume", manifest={})
    try:
        merge.run_restore(staged, commit=commit)
    except merge.RestoreRefused as exc:
        assert isinstance(exc, merge.WriterJobsRefused), "the journal tells this refusal from the swap barrier's by its class"
        return str(exc)
    except Reached:
        return None
    raise AssertionError("run_restore neither refused nor reached its first step")


def test_a_committing_restore_refuses_and_names_the_running_writer(registry, monkeypatch):
    job, release = _running("governments", "Loading government data")
    try:
        text = _refused(monkeypatch, commit=True)
        assert text is not None, "the restore went ahead while a corpus writer was running"
        assert "(Loading government data)" in text and "nothing was imported" in text
        # a preview writes nothing to the corpus: it is never refused
        assert _refused(monkeypatch, commit=False) is None
    finally:
        release.set()
        job.join(5)
    assert _refused(monkeypatch, commit=True) is None, "with the writer gone the restore goes ahead"


def test_a_job_the_restore_may_stop_is_stopped_and_the_restore_goes_ahead(registry, monkeypatch):
    """The re-index drain: stopping it loses nothing (its watermark), so the restore stops it rather than refusing because of it. A plain
    writer running beside it is still named, and the stoppable one is not."""
    drain, r1 = _running("reindex-resume", "finishing the re-index of imported articles", stops=True)
    try:
        assert _refused(monkeypatch, commit=True) is None, "the restore refused for a job it may stop"
        assert drain.join(1), "the drain was not asked to stop"
    finally:
        r1.set()
        drain.join(5)
    drain2, r2 = _running("reindex-resume", "finishing the re-index of imported articles", stops=True)
    writer, r3 = _running("governments", "Loading government data")
    try:
        text = _refused(monkeypatch, commit=True)
        assert text is not None and "(Loading government data)" in text and "re-index" not in text, text
        # a writer it may not stop runs: the restore refuses BEFORE it stops anything (the delta reads of a18a7d01)
        assert drain2._alive(), "a restore that was going to refuse anyway stopped the re-index"
    finally:
        for ev in (r2, r3):
            ev.set()
        for job in (drain2, writer):
            job.join(5)


def test_a_job_the_restore_stopped_yields_rather_than_cancels_and_is_started_again_when_the_restore_ends(registry, monkeypatch):
    """The restore asks the drain to step aside (``ctx.yielding``), never the operator's cancel: the task manager must not show a stop nobody
    asked for. Whatever the restore's outcome, its end starts the drain again (``start_jobs_stopped_for_restore``, called in the volume and
    single-file restores' ``finally``); a successful deferred import has started it already, so that start finds it running."""
    from src.backup import merge

    drain, release = _running("reindex-resume", "finishing the re-index of imported articles", stops=True)
    try:
        monkeypatch.setattr(merge, "_STOP_FOR_RESTORE_S", 5.0)
        merge.refuse_while_writer_jobs_run()  # nothing blocks: the drain is stopped and the restore goes ahead
        assert drain.join(1) and drain.status()["state"] == "done", drain.status()["state"]
        assert merge.start_jobs_stopped_for_restore() == ["reindex-resume"], "the restore ended and nothing started the drain again"
        assert drain._alive()
        assert merge.start_jobs_stopped_for_restore() == [], "started once"
    finally:
        release.set()
        drain.join(5)


def test_the_restores_start_the_stopped_jobs_again_in_their_finally():
    vj = (ROOT / "src/backup/volume_job.py").read_text("utf-8")
    fin = vj[vj.index("refuse_while_writer_jobs_run()") :]
    assert "start_jobs_stopped_for_restore()" in fin[: fin.index("resume_after_exclusive_operation(was_paused")], "volume restore's finally"
    legacy = (ROOT / "src/api/backup_v2.py").read_text("utf-8")
    body = python_function_source(legacy, "restore_legacy_path")
    assert body.count("start_jobs_stopped_for_restore()") == 2, "the staging failure and the finally"


def test_a_stoppable_job_that_does_not_stop_in_time_is_named(registry, monkeypatch):
    from src.backup import merge

    release = threading.Event()
    started = threading.Event()

    def stubborn(ctx):
        started.set()
        release.wait(10)  # never reads ctx.stopping

    job = bg.register_job(bg.BackgroundJob("slow", "A slow writer", stubborn, is_writer=True, cancellable=True, stops_for_restore=True))
    job.start()
    assert started.wait(5)
    try:
        monkeypatch.setattr(merge, "_STOP_FOR_RESTORE_S", 0.05)
        with pytest.raises(merge.WriterJobsRefused, match=r"\(A slow writer\)"):
            merge.refuse_while_writer_jobs_run()
    finally:
        release.set()
        job.join(5)


def test_a_job_whose_safe_point_comes_after_the_wait_is_not_left_to_stop_for_an_import_that_never_happens(registry, monkeypatch):
    """The ask is withdrawn when the wait ends: otherwise the job stops at its next safe point after the refusal, and nothing starts it."""
    from src.backup import merge

    release = threading.Event()
    started = threading.Event()
    reached = threading.Event()

    def late(ctx):
        started.set()
        time.sleep(0.3)  # the safe point is further away than the restore waits
        reached.set()
        while not release.wait(0.01):
            if ctx.stopping or ctx.yielding:
                return

    job = bg.register_job(bg.BackgroundJob("late", "A late writer", late, is_writer=True, cancellable=True, stops_for_restore=True))
    job.start()
    assert started.wait(5)
    try:
        monkeypatch.setattr(merge, "_STOP_FOR_RESTORE_S", 0.05)
        with pytest.raises(merge.WriterJobsRefused, match=r"\(A late writer\)"):
            merge.refuse_while_writer_jobs_run()
        assert reached.wait(5)
        time.sleep(0.1)
        assert job._alive(), "a restore that refused leaves the job running"
        assert not merge._STOPPED_FOR_RESTORE
    finally:
        release.set()
        job.join(5)


def test_a_restore_ending_inside_a_window_forgets_what_it_stopped(registry, monkeypatch):
    """The import run starts the drain when it ends; a stale entry would let a later restore start a drain the operator cancelled."""
    from src.backup import merge
    from src.scheduler import runner

    merge._remember_stopped(["reindex-resume"])
    monkeypatch.setattr(runner, "exclusive_window_open", lambda: True)
    assert merge.start_jobs_stopped_for_restore() == []
    assert not merge._STOPPED_FOR_RESTORE


def test_a_job_the_operator_cancelled_is_never_started_again_by_a_restore(registry):
    from src.backup import merge

    release = threading.Event()

    def worker(ctx):
        while not release.wait(0.01):
            if ctx.stopping:
                return

    job = bg.register_job(bg.BackgroundJob("c", "Cancelled", worker, is_writer=True, cancellable=True, stops_for_restore=True))
    job.start()
    job.cancel()
    assert job.join(5)
    assert job.status()["state"] == "cancelled"
    merge._remember_stopped(["c"])
    try:
        assert merge.start_jobs_stopped_for_restore() == []
        assert not job._alive()
    finally:
        release.set()
        job.join(5)


def test_a_cancel_pressed_after_the_job_yielded_is_not_overridden_either(registry):
    from src.backup import merge

    job = bg.register_job(bg.BackgroundJob("y", "Yielded", lambda ctx: None, is_writer=True, cancellable=True, stops_for_restore=True))
    job.start()
    assert job.join(5)
    assert job.status()["state"] == "done"
    job.cancel()  # on a job that is no longer running: the state stays 'done'
    merge._remember_stopped(["y"])
    assert merge.start_jobs_stopped_for_restore() == []


def test_run_restore_asks_before_preparing_and_again_at_the_working_copy():
    """A job started while the backup was being prepared is caught by the second ask, at the working copy (read from source: driving a
    real restore to that point needs a staged corpus)."""
    src = (ROOT / "src/backup/merge.py").read_text("utf-8")
    body = python_function_source(src, "run_restore")
    first = body.index("refuse_while_writer_jobs_run()")
    second = body.index("refuse_while_writer_jobs_run()", first + 1)
    assert "refuse_while_writer_jobs_run()" not in body[second + 1 :], "two asks, no more"
    assert first < body.index("prepare_staged_corpus(") < second, "the first ask comes before anything is prepared, the second after"
    assert "snapshot" in body[second : second + 2000], "the second ask sits at the working copy"


def test_the_staging_paths_ask_before_a_byte_is_decrypted():
    """The volume restore asks before ``read_volume_backup`` and the single-file restore before ``_stage_upload`` (after the file is read,
    before it is decrypted): a refusal costs no decryption and no staging."""
    vj = (ROOT / "src/backup/volume_job.py").read_text("utf-8")
    assert vj.index("refuse_while_writer_jobs_run()") < vj.index("staged = read_volume_backup(")
    legacy = (ROOT / "src/api/backup_v2.py").read_text("utf-8")
    assert legacy.index("data = p.read_bytes()") < legacy.index("refuse_while_writer_jobs_run()") < legacy.index("staged = _stage_upload(")
    assert 'reason="writer-jobs"' in legacy


def test_the_journal_names_the_writer_jobs_refusal():
    from src.monitoring import storage_events as se

    assert "writer-jobs" in se.RUN_REFUSALS and "barrier" in se.RUN_REFUSALS
    vj = (ROOT / "src/backup/volume_job.py").read_text("utf-8")
    branch = vj[vj.index("if issubclass(type(exc), WriterJobsRefused):") :][:300]
    assert 'reason="writer-jobs"' in branch and 'reason="barrier"' in branch


def test_only_the_reindex_drain_is_marked_as_stopped_by_the_restore():
    """``stops_for_restore=True`` means the restore stops the job: set only where a stop loses nothing (the re-index drain resumes from its
    per-article watermark, and the import starts it again)."""
    marked = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "BackgroundJob":
                for kw in node.keywords:
                    if kw.arg == "stops_for_restore" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        first = node.args[0] if node.args else None
                        marked.append((path.relative_to(ROOT).as_posix(), getattr(first, "value", None)))
    assert marked == [("src/api/backup_v2.py", "reindex-resume")], marked


def test_the_task_manager_ask_reads_the_same_flags(registry, monkeypatch):
    from src.api import jobs as jobs_api

    job, release = _running("some-new-writer", "A writer no hand-kept list names")
    try:
        assert "some-new-writer" not in jobs_api._DB_WRITER_KINDS
        out = jobs_api.list_jobs()
        assert out["db_writers_busy"] is True, out["busy_with"]
        assert "some-new-writer: A writer no hand-kept list names" in out["busy_with"]
        # the import page's question: the refusal the server would raise now, read without stopping anything
        assert out["import_refused"] and "(A writer no hand-kept list names)" in out["import_refused"]
    finally:
        release.set()
        job.join(5)
    drain, r2 = _running("reindex-resume", "finishing the re-index of imported articles", stops=True)
    try:
        out = jobs_api.list_jobs()
        assert out["import_refused"] is None, "the import stops the drain itself: the page must not refuse for it"
        assert drain._alive(), "the page's question stopped a job"
    finally:
        r2.set()
        drain.join(5)


def test_the_page_reads_the_refusal_back_in_the_operator_language():
    """The real refusal, through the real page code, with a translator stub that marks what it was handed (with the identity function the
    output would equal the input whether the pattern matched or not). The key exists in all 12 locales."""
    import re

    from src.backup.merge import _WRITER_JOBS_REFUSAL
    from tests.test_clickthrough_b13_leftovers import (
        app_js,
        array_literal,
        function_source,
        object_literal,
    )

    message = _WRITER_JOBS_REFUSAL.format(jobs="Loading government data; finishing the re-index of imported articles")
    js = app_js()
    size_re = re.search(r'const _OO_SIZE_RE = "[^"\n]*";', js)
    assert size_re
    prog = "\n".join([
        "const OOI18N = { t: (x) => 'T:' + x, tf: (x, v) => 'FRAME<' + x + '>' + JSON.stringify(v) };",
        "const window = { OOI18N };",
        function_source(js, "_sizeText"),
        "const _OO_SPACE_WHAT = " + object_literal(js, "_OO_SPACE_WHAT") + ";",
        size_re.group(0),
        "const _OO_SPACE_RES = " + array_literal(js, "_OO_SPACE_RES") + ";",
        function_source(js, "ooServerText"),
        "process.stdout.write(JSON.stringify(ooServerText(" + json.dumps(message) + ")));",
    ])
    proc = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    frame, _, rest = out.partition(">")
    key = (
        "A background job is writing to your corpus ({jobs}). Nothing was imported and nothing in your corpus changed: what it writes "
        "during an import would be lost when your corpus is switched. Let it finish, or stop it if it can be stopped, then import again."
    )
    assert frame == "FRAME<" + key, out
    assert json.loads(rest) == {"jobs": "T:Loading government data; T:finishing the re-index of imported articles"}
    for path in sorted((ROOT / "src/static/locales").glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        assert key in table and "{jobs}" in table[key], path.name


def test_a_shutdown_after_the_stop_is_never_undone_by_the_restart(registry, monkeypatch):
    """R689: the app began shutting down after the restore stopped the drain. The shutdown's stop-all did not see the drain (it had
    already ended), so the restore's end must not start a writer the shutdown is about to close the database under."""
    from src.backup import merge

    drain, release = _running("reindex-resume", "finishing the re-index of imported articles", stops=True)
    try:
        monkeypatch.setattr(merge, "_STOP_FOR_RESTORE_S", 5.0)
        merge.refuse_while_writer_jobs_run()
        assert drain.join(1)
        bg.stop_all_jobs(0.1)
        assert merge.start_jobs_stopped_for_restore() == []
        assert not drain._alive()
    finally:
        release.set()
        drain.join(5)


def test_a_job_still_on_its_way_out_is_started_again_once_it_is_out(registry, monkeypatch):
    """The drain met the yield after the restore's wait and was still in its own finally when the restore refused and started it again:
    the start must wait for it to be out, not be refused as 'already running' and leave it paused for an import that never happened."""
    from src.backup import merge

    runs = []
    release = threading.Event()

    def worker(ctx):
        runs.append(1)
        if len(runs) > 1:  # the second run: an ordinary drain
            while not release.wait(0.01):
                if ctx.stopping:
                    return
            return
        try:
            while not release.wait(0.01):
                if ctx.yielding:
                    return
        finally:
            time.sleep(0.3)  # its way out takes longer than the restore waits

    drain = bg.register_job(bg.BackgroundJob("reindex-resume", "Drain", worker, is_writer=True, cancellable=True, stops_for_restore=True))
    drain.start()
    try:
        monkeypatch.setattr(merge, "_STOP_FOR_RESTORE_S", 0.05)
        with pytest.raises(merge.WriterJobsRefused):
            merge.refuse_while_writer_jobs_run()
        assert drain._alive() and len(runs) == 2, "the drain was not started again after its way out"
    finally:
        release.set()
        drain.join(5)
