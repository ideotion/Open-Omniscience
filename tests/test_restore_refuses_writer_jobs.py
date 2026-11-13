"""A committing restore refuses while a registered background job that commits to the corpus is running (R659, queue item 21 option B
reduced).

Everything such a job commits between the restore's working copy and the swap is discarded by the swap, so the restore refuses and names
the job instead of losing what it writes. ONE list: the registry's own ``is_writer`` flags, read by both the restore and the task manager's
"another job is writing" ask (``db_writers_busy`` in ``api/jobs.py``), never a second hand-kept copy. A job that stops itself inside the
exclusive window (``yields_to_exclusive``: the re-index drain, which the import queue restarts after every item) is not named while that
window is open, or a queued import would refuse its own second item.
"""

from __future__ import annotations

import ast
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.jobs import background as bg

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    """The real registry, emptied for the test and given back afterwards."""
    with bg._REG_LOCK:
        saved = dict(bg._REGISTRY)
        bg._REGISTRY.clear()
    yield
    with bg._REG_LOCK:
        bg._REGISTRY.clear()
        bg._REGISTRY.update(saved)


def _running(kind: str, label: str, *, is_writer: bool = True, yields: bool = False):
    """A registered job whose worker blocks until the returned event is set."""
    release = threading.Event()
    started = threading.Event()

    def worker(ctx):
        started.set()
        release.wait(10)

    job = bg.register_job(bg.BackgroundJob(kind, label, worker, is_writer=is_writer, yields_to_exclusive=yields))
    job.start()
    assert started.wait(5)
    return job, release


def test_the_list_is_the_registry_flags_and_names_only_what_runs(registry):
    writer, r1 = _running("w", "Writing things")
    reader, r2 = _running("r", "Reading things", is_writer=False)
    yielder, r3 = _running("y", "Yielding writer", yields=True)
    try:
        assert bg.running_writer_jobs() == [("w", "Writing things"), ("y", "Yielding writer")]
        # inside the exclusive window, a job that stops itself there commits nothing during it
        assert bg.running_writer_jobs(window_open=True) == [("w", "Writing things")]
    finally:
        for ev in (r1, r2, r3):
            ev.set()
        for job in (writer, reader, yielder):
            job.join(5)
    assert bg.running_writer_jobs() == [], "a job that has ended is not named"


def _refused(monkeypatch, *, commit: bool):
    """Run ``run_restore`` far enough to see whether it refuses; the first real step is replaced by a sentinel."""
    from src.backup import merge

    class Reached(Exception):
        pass

    def reached(*a, **k):
        raise Reached

    monkeypatch.setattr(merge, "prepare_staged_corpus", reached)
    staged = SimpleNamespace(stage_a_timings={}, staging_dir=Path("/nonexistent"), kind="volume", manifest={})
    try:
        merge.run_restore(staged, commit=commit)
    except merge.RestoreRefused as exc:
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


def test_a_job_that_yields_to_the_window_does_not_refuse_a_queued_import(registry, monkeypatch):
    import src.scheduler.runner as runner

    job, release = _running("reindex-resume", "finishing the re-index of imported articles", yields=True)
    try:
        monkeypatch.setattr(runner, "exclusive_window_open", lambda: True)
        assert _refused(monkeypatch, commit=True) is None
        monkeypatch.setattr(runner, "exclusive_window_open", lambda: False)
        assert _refused(monkeypatch, commit=True) is not None, "outside the window the drain does not stop, so it is named"
    finally:
        release.set()
        job.join(5)


def test_only_a_worker_that_reads_the_window_is_marked_as_yielding():
    """``yields_to_exclusive=True`` takes a writer out of the restore's list: it is set only on the re-index drain, whose worker stops in
    its article loop once the window is open (``_yield_to_import`` in api/backup_v2.py)."""
    marked = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "BackgroundJob":
                for kw in node.keywords:
                    if kw.arg == "yields_to_exclusive" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        first = node.args[0] if node.args else None
                        marked.append((path.relative_to(ROOT).as_posix(), getattr(first, "value", None)))
    assert marked == [("src/api/backup_v2.py", "reindex-resume")], marked
    src = (ROOT / "src/api/backup_v2.py").read_text("utf-8")
    assert "def _yield_to_import() -> bool:\n        return exclusive_window_open()" in src


def test_the_task_manager_ask_reads_the_same_flags(registry, monkeypatch):
    from src.api import jobs as jobs_api

    job, release = _running("some-new-writer", "A writer no hand-kept list names")
    try:
        assert "some-new-writer" not in jobs_api._DB_WRITER_KINDS
        out = jobs_api.list_jobs()
        assert out["db_writers_busy"] is True, out["busy_with"]
        assert "some-new-writer: A writer no hand-kept list names" in out["busy_with"]
    finally:
        release.set()
        job.join(5)


def test_the_page_reads_the_refusal_back_in_the_operator_language():
    """The real refusal, through the real page code, with a translator stub that marks what it was handed (with the identity function the
    output would equal the input whether the pattern matched or not). The key exists in all 12 locales."""
    from src.backup.merge import _WRITER_JOBS_REFUSAL
    from tests.test_clickthrough_b13_leftovers import app_js, array_literal, function_source, object_literal

    import re

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
        "during an import would be lost when your corpus is switched. Stop it, or let it finish, then import again."
    )
    assert frame == "FRAME<" + key, out
    assert json.loads(rest) == {"jobs": "T:Loading government data; T:finishing the re-index of imported articles"}
    for path in sorted((ROOT / "src/static/locales").glob("*.json")):
        table = json.loads(path.read_text("utf-8"))
        assert key in table and "{jobs}" in table[key], path.name
