"""A start that cannot make its worker thread leaves no claimed slot, no queued model and no running import with nothing behind it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. ``threading.Thread.start()`` raises ``RuntimeError("can't start new thread")`` when the process or the machine is out of
threads. ``tests/test_failed_thread_start_leaves_no_phantom_job.py`` pins the managers whose start sets "running" and then starts the
thread. This file pins the five that were left (the WAL lane's sweep, ``wal-lane/measure-start-failure-sweep-2026-10-29.md``):

- the Wikipedia dump manager and the OSM region manager CLAIM A SLOT first (status "downloading", saved) and launch after it, outside
  the lock. A launch that fails left a "downloading" row with no worker that counted against ``max_concurrent`` (3 dumps, the Optimized
  profile's default; 2 OSM regions) until the entry was retried or deleted or the process restarted, the other entries queued behind
  it, and a retry at capacity was itself queued with nothing to launch it. ``_pump`` launched every entry it had claimed in a row, so
  the first launch that raised also left the entries claimed after it with no thread (and the exception escaped the pump's own thread);
- the newsletter folder import said "running" in memory and in its saved file with ``running`` false in its status;
- the dump index build said "running" with no worker;
- the model pull queue kept the model queued, so enqueueing the same model again returned at "already queued" and started no pump
  (another model's enqueue would have started one, which drains both).

What it pins, per manager: the start that fails raises what ``start()`` raised, the job is not running afterwards, what was saved says so
(or, for the pull queue, what the history says), and the next start is accepted and runs. For the two downloaders also that the put-back
touches only what the failed launch registered (a second start of the same key that took the entry over keeps its thread, its stop event
and its status; one that queued the entry keeps it queued; one that has claimed the entry but not yet registered keeps the stop event it
then registers), and that a save that fails during the put-back does not hide the start's own error. Only an ``Exception`` is caught
(R393): an interrupt that lands while ``start()`` waits for the new thread leaves the OS thread created and about to run the worker, so
calling the job an error, or freeing its slot, would let a second start run a second worker beside it.

The failure is injected in the module under test (its ``threading`` is replaced by one whose ``Thread`` refuses to start), never on the
process-wide ``threading.Thread``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base
from src.geo import osm_downloads
from src.ingest import import_job
from src.llm import pull_queue
from src.wiki import dump_index
from src.wiki import dumps as wiki_dumps
from tests.wallclock_helpers import wait_until

_CANNOT_START = "can't start new thread"
#: What a job that could not start says about itself: the exception's class and nothing it said.
_ERROR = "RuntimeError: could not start the worker thread"


class _Threading:
    """What a module sees as ``threading``: the real one, except that the first ``fail_first`` threads it makes refuse to start."""

    def __init__(self, fail_first: int = 1, error: BaseException | None = None, on_refuse=None, on_construct=None) -> None:
        self.refusals_left = fail_first
        self.error = error
        outer = self

        class Thread(threading.Thread):
            def __init__(self, *args, **kwargs) -> None:
                if on_construct is not None:
                    on_construct()  # a start() that is between claiming the entry and registering its thread stops here
                super().__init__(*args, **kwargs)

            def start(self) -> None:
                if outer.refusals_left > 0:
                    outer.refusals_left -= 1
                    if on_refuse is not None:
                        on_refuse()  # what happens in the window between the machine's refusal and the caller seeing it
                    raise outer.error or RuntimeError(_CANNOT_START)
                super().start()

        self.Thread = Thread

    def __getattr__(self, name: str):
        return getattr(threading, name)


def _cannot_start(
    monkeypatch, module, fail_first: int = 1, error: BaseException | None = None, on_refuse=None, on_construct=None
) -> _Threading:
    shim = _Threading(fail_first, error, on_refuse, on_construct)
    monkeypatch.setattr(module, "threading", shim)
    return shim


# --------------------------------------------------------------------------- #
#  the two download managers: a claimed slot is given back
# --------------------------------------------------------------------------- #
class _Resp:
    status_code = 200

    def __init__(self) -> None:
        self.headers = {"Content-Length": "10"}

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, _chunk):
        yield b"0123456789"


def _wiki_entry(mgr, code):
    return mgr._entry_for(code, "pages-articles")


def _osm_entry(mgr, code):
    return mgr._entry_for(code)


#: (module, manager class, three codes, how a code becomes an entry, the key it is stored under)
_DOWNLOADERS = [
    pytest.param(
        wiki_dumps, wiki_dumps.DumpDownloadManager, ("en", "fr", "de"), _wiki_entry, lambda c: f"{c}:pages-articles", id="wiki-dumps"
    ),
    pytest.param(osm_downloads, osm_downloads.OsmDownloadManager, ("europe", "africa", "asia"), _osm_entry, lambda c: c, id="osm"),
]


@pytest.fixture(autouse=True)
def _online(monkeypatch):
    # The managers refuse to start while airplane mode is engaged; this file is about what happens after they decide to.
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)


def _status_of(mgr, key):
    return next(e["status"] for e in mgr.list() if e["key"] == key)


def _saved_status(mgr, key):
    return json.loads(Path(mgr.state_path).read_text("utf-8"))["entries"][key]["status"]


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_launch_that_cannot_start_gives_the_slot_back(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=1)
    code, k = codes[0], key(codes[0])
    _cannot_start(monkeypatch, module)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start(code)
    row = next(e for e in mgr.list() if e["key"] == k)
    assert row["status"] == "error"
    assert row["error"] == _ERROR
    assert mgr._downloading_now() == 0
    assert k not in mgr._stops, "a stop event left behind would make pause() answer True for a download that is not running"
    assert not mgr._threads[k].is_alive()
    assert mgr.pause(k) is False, "there is no worker to pause"
    # What was saved says so too: a restart must not read a slot it never held back as a download that was interrupted.
    assert _saved_status(mgr, k) == "error"
    assert cls(base_dir=tmp_path, http_get=None, max_concurrent=1).list()[0]["status"] == "error"
    # The retry takes the slot (capacity is ONE: a leaked slot would have queued it) and runs to the end.
    mgr.start(code)
    assert wait_until(lambda: _status_of(mgr, k) == "done"), "the retry should reach the fetch and finish"


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_pump_goes_on_past_a_launch_that_cannot_start(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=3)
    for code in codes:
        entry = entry_for(mgr, code)
        entry.status = "queued"
        mgr._order.append(entry.key)
    _cannot_start(monkeypatch, module, fail_first=1)
    mgr._pump()  # must not raise: it runs on the thread of a download that has just finished
    first, rest = key(codes[0]), [key(c) for c in codes[1:]]
    assert _status_of(mgr, first) == "error"
    for k in rest:
        assert wait_until(lambda k=k: _status_of(mgr, k) == "done"), f"{k} was claimed and must have been launched"
    assert mgr._downloading_now() == 0


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_pump_whose_every_launch_fails_leaves_nothing_downloading(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=3)
    for code in codes:
        entry = entry_for(mgr, code)
        entry.status = "queued"
        mgr._order.append(entry.key)
    _cannot_start(monkeypatch, module, fail_first=3)
    mgr._pump()
    assert {_status_of(mgr, key(c)) for c in codes} == {"error"}
    assert mgr._downloading_now() == 0
    assert {_saved_status(mgr, key(c)) for c in codes} == {"error"}


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_second_start_that_took_the_entry_over_keeps_its_worker(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    # Between the machine's refusal and the failed launch looking at the entry, another start() of the same key finds a thread that is
    # not alive and a status of "downloading", registers its own thread and stop event and starts a worker that DOES run. The failed
    # launch must then leave all of it alone: calling the entry "error" or dropping the stop event would leave a live download that
    # pause() cannot reach.
    gate = threading.Event()

    def gated_get(_url, _headers):
        gate.wait(20)
        return _Resp()

    mgr = cls(base_dir=tmp_path, http_get=gated_get, max_concurrent=3)
    code, k = codes[0], key(codes[0])
    _cannot_start(monkeypatch, module, on_refuse=lambda: mgr.start(code))
    try:
        with pytest.raises(RuntimeError, match=_CANNOT_START):
            mgr.start(code)
        assert _status_of(mgr, k) == "downloading"
        assert k in mgr._stops, "the second start's stop event is what pause() reaches"
        assert mgr._threads[k].is_alive()
    finally:
        gate.set()
    assert wait_until(lambda: _status_of(mgr, k) == "done"), "the second start's worker should run to the end"


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_second_start_that_queued_the_entry_keeps_it_queued(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    # At capacity the second start() of the key answers "queued" to its caller and puts the key in the queue. The failed launch must not
    # overwrite that with "error": it gives back the stop event it registered and leaves the status alone.
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=1)
    code, k = codes[0], key(codes[0])
    _cannot_start(monkeypatch, module, on_refuse=lambda: mgr.start(code))
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start(code)
    assert _status_of(mgr, k) == "queued"
    assert k in mgr._order
    assert k not in mgr._stops


#: How long the put-back may hold the lock against a second start that is waiting for it. The fixed code always waits this long (the
#: second start cannot finish while the put-back holds the lock); only a put-back that does NOT hold the lock lets it finish sooner.
_LOCK_WAIT = 1.0


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_second_start_between_its_claim_and_its_registration_keeps_its_stop_event(
    monkeypatch, tmp_path, module, cls, codes, entry_for, key
):
    # The window the lock closes. A second start() has claimed the entry (it found a thread that is not alive) and is about to register
    # its stop event and its thread. The failed launch has read its own stop event as still registered and is about to drop it. If the
    # second start's registration could land between that read and the drop, the drop would remove the SECOND start's stop event and
    # leave a live download that pause() cannot reach. The registration and the put-back take the same lock, so it lands after.
    gate = threading.Event()  # holds the second start's worker in its fetch

    def gated_get(_url, _headers):
        gate.wait(20)
        return _Resp()

    mgr = cls(base_dir=tmp_path, http_get=gated_get, max_concurrent=3)
    code, k = codes[0], key(codes[0])
    armed, in_ctor, go = threading.Event(), threading.Event(), threading.Event()
    second: list[threading.Thread] = []

    class _Stops(dict):
        def __delitem__(self, item) -> None:
            # The failed launch is about to drop its stop event: let the second start go on to register its own.
            go.set()
            second[0].join(_LOCK_WAIT)
            super().__delitem__(item)

    mgr._stops = _Stops()

    def on_construct() -> None:
        if armed.is_set() and threading.current_thread() is second[0]:
            in_ctor.set()
            assert go.wait(5)

    def on_refuse() -> None:
        second.append(threading.Thread(target=lambda: mgr.start(code), name="second-start", daemon=True))
        armed.set()
        second[0].start()
        assert in_ctor.wait(5), "the second start should have claimed the entry and reached its thread"

    _cannot_start(monkeypatch, module, on_refuse=on_refuse, on_construct=on_construct)
    try:
        with pytest.raises(RuntimeError, match=_CANNOT_START):
            mgr.start(code)
        second[0].join(20)
        assert not second[0].is_alive()
        assert k in mgr._stops, "the second start's stop event must survive the failed launch's put-back"
        assert mgr._threads[k].is_alive()
    finally:
        gate.set()
    assert wait_until(lambda: _status_of(mgr, k) == "done"), "the second start's worker should run to the end"


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_save_that_fails_while_the_slot_is_given_back_does_not_hide_the_starts_own_error(
    monkeypatch, tmp_path, module, cls, codes, entry_for, key
):
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=1)
    real_save = mgr._save

    def save() -> None:
        if any(e.status == "error" for e in mgr._entries.values()):
            raise OSError("disk full")  # only the put-back's save sees an entry in "error"
        real_save()

    mgr._save = save
    _cannot_start(monkeypatch, module)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start(codes[0])
    assert _status_of(mgr, key(codes[0])) == "error"
    assert mgr._downloading_now() == 0


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_an_interrupt_from_the_launch_keeps_the_slot_claimed(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    # R393: an interrupt that lands inside start() leaves the OS thread created and about to run the worker; freeing the slot
    # would let a second start run a second worker for the same file. Pinned so the catch stays an ``Exception``.
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=1)
    _cannot_start(monkeypatch, module, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        mgr.start(codes[0])
    assert _status_of(mgr, key(codes[0])) == "downloading"
    assert mgr._downloading_now() == 1


@pytest.mark.parametrize(("module", "cls", "codes", "entry_for", "key"), _DOWNLOADERS)
def test_a_pump_does_not_swallow_an_interrupt(monkeypatch, tmp_path, module, cls, codes, entry_for, key):
    # The pump takes an Exception from a launch so that one entry cannot strand the rest; an interrupt is not an entry's failure.
    mgr = cls(base_dir=tmp_path, http_get=lambda u, h: _Resp(), max_concurrent=3)
    for code in codes:
        entry = entry_for(mgr, code)
        entry.status = "queued"
        mgr._order.append(entry.key)
    _cannot_start(monkeypatch, module, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        mgr._pump()


# --------------------------------------------------------------------------- #
#  the newsletter folder import
# --------------------------------------------------------------------------- #
def _eml(folder: Path, n: int) -> None:
    (folder / f"{n}.eml").write_bytes(
        (
            f"From: N <n@x.test>\nSubject: S{n}\nMessage-ID: <m{n}@x.test>\n"
            f"Date: Mon, 05 Jan 2026 18:00:00 +0000\nContent-Type: text/plain; charset=utf-8\n\n"
            f"a unique newsletter body number {n} about elections\n"
        ).encode()
    )


@pytest.fixture()
def newsletter(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    folder = tmp_path / "nl"
    folder.mkdir()
    for i in range(3):
        _eml(folder, i)
    state = tmp_path / "import_state.json"
    mgr = import_job.NewsletterImportManager(state_path=state)
    return mgr, sessionmaker(bind=engine, future=True, autoflush=False), folder, state


def test_a_fresh_import_that_cannot_start_is_an_error_not_a_running_import(monkeypatch, newsletter):
    mgr, session, folder, state = newsletter
    _cannot_start(monkeypatch, import_job)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start(str(folder), _session_factory=session)
    st = mgr.status()
    assert st["state"] == "error" and st["error"] == _ERROR
    assert st["running"] is False
    assert json.loads(state.read_text("utf-8"))["state"] == "error"
    # The retry runs the whole folder.
    mgr.start(str(folder), _session_factory=session)
    assert wait_until(lambda: mgr.status()["state"] == "done")
    assert mgr.status()["files_done"] == 3


def test_a_resume_that_cannot_start_keeps_its_place(monkeypatch, newsletter):
    mgr, session, folder, state = newsletter
    mgr._folder, mgr._files, mgr._cursor, mgr._state = str(folder), sorted(folder.glob("*.eml")), 1, "paused"
    mgr._session_factory = session
    _cannot_start(monkeypatch, import_job)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.resume()
    st = mgr.status()
    assert st["state"] == "error" and st["running"] is False
    assert st["files_done"] == 1, "a start that never began must not move the cursor"
    # An error is a state resume() accepts: the next resume continues from the file it stopped at.
    mgr.resume()
    assert wait_until(lambda: mgr.status()["state"] == "done")
    assert mgr.status()["files_done"] == 3
    with session() as db:
        assert db.query(Article).count() == 2, "it continued from the file it stopped at (1), not from the first"


def test_an_interrupt_from_the_import_start_leaves_it_running(monkeypatch, newsletter):
    mgr, session, folder, _state = newsletter
    _cannot_start(monkeypatch, import_job, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        mgr.start(str(folder), _session_factory=session)
    assert mgr.status()["state"] == "running"


# --------------------------------------------------------------------------- #
#  the dump index build
# --------------------------------------------------------------------------- #
@pytest.fixture()
def index_build(monkeypatch, tmp_path):
    monkeypatch.setattr(dump_index, "build_index", lambda wiki, **kw: {"pages": 3, "cancelled": False})
    return dump_index.DumpIndexManager(), tmp_path


def test_an_index_build_that_cannot_start_is_an_error_not_a_running_build(monkeypatch, index_build):
    mgr, base = index_build
    _cannot_start(monkeypatch, dump_index)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.start("en", base_dir=base)
    build = mgr.status(base_dir=base)["build"]
    assert build["state"] == "error" and build["error"] == _ERROR
    assert build["running"] is False
    # The retry is accepted and the build runs.
    mgr.start("en", base_dir=base)
    assert wait_until(lambda: mgr.status(base_dir=base)["build"]["state"] == "done")
    assert mgr.status(base_dir=base)["build"]["pages"] == 3


def test_an_interrupt_from_the_index_start_leaves_it_running(monkeypatch, index_build):
    mgr, base = index_build
    _cannot_start(monkeypatch, dump_index, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        mgr.start("en", base_dir=base)
    assert mgr.status(base_dir=base)["build"]["state"] == "running"


# --------------------------------------------------------------------------- #
#  the model pull queue
# --------------------------------------------------------------------------- #
def test_a_pull_that_cannot_start_does_not_stay_queued(monkeypatch):
    mgr = pull_queue.ModelPullManager()
    pumps: list[str] = []
    mgr._pump = lambda: pumps.append("ran")  # the pump itself is not under test: it would ask a daemon where the model lands
    _cannot_start(monkeypatch, pull_queue)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.enqueue("tiny:1b")
    st = mgr.status()
    assert st["queue"] == [], "a model whose pump never ran must not sit in the queue"
    assert [(h["model"], h["status"], h["error"]) for h in st["history"]] == [("tiny:1b", "error", _ERROR)]
    # The same model again is accepted (it used to return at 'already queued') and a pump runs.
    mgr.enqueue("tiny:1b")
    mgr._thread.join(5)
    assert pumps == ["ran"]


def test_a_pull_that_cannot_start_leaves_the_other_queued_models_alone(monkeypatch):
    mgr = pull_queue.ModelPullManager()
    mgr._pump = lambda: None
    mgr._queue.append("other:1b")  # queued by an earlier enqueue whose pump has since ended
    _cannot_start(monkeypatch, pull_queue)
    with pytest.raises(RuntimeError, match=_CANNOT_START):
        mgr.enqueue("tiny:1b")
    assert mgr.status()["queue"] == ["other:1b"]


def test_an_interrupt_from_the_pull_start_keeps_the_model_queued(monkeypatch):
    mgr = pull_queue.ModelPullManager()
    mgr._pump = lambda: None
    _cannot_start(monkeypatch, pull_queue, error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        mgr.enqueue("tiny:1b")
    assert mgr.status()["queue"] == ["tiny:1b"]
