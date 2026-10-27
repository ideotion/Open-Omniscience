"""What a repair that is cut short leaves the full-text search index as: named, never assumed (0.5.1 item 29, the settle-it check).

The repair copies a damaged library file into a new one and REBUILDS the article search index in that copy (``salvage``'s
``search-index`` phase, ``fts.rebuild_index``, one batch of 500 documents at a time) before the copy is checked, given a sidecar and
swapped in. The question this file settles over REAL stores and the real salvage is: if the repair is interrupted at the worst
place, inside that rebuild, what state is the index in, and does anything in the app say so or assume it?

  * a STOP that lands inside the rebuild ends the repair ``stopped``: the live file is byte for byte what it was, its index still
    holds every document it held, the half-built index in the copy goes with the copy, and the record claims no index at all (no
    ``search_index`` figure for an index that was thrown away);
  * a PROCESS KILLED inside the rebuild (a real SIGKILL of a real child) leaves the live file alone and a scratch copy whose index
    is not complete and which has no sidecar, so it can never be swapped in; the next start makes a fresh copy, and the repaired
    file's index holds exactly as many documents as the file has articles, and as many as the report counted;
  * a cut AFTER the copy is whole (its index built and counted) but before the swap carries the index figure through the sidecar,
    and the file the resume swaps in has an index holding exactly the figure the record states.

THE INDEX'S SIZE IS READ FROM ITS OWN SHADOW TABLE (``article_fts_docsize``), never from ``fts.fts_status``: the article index is an
external-content FTS5 table, so ``fts_status``'s probe and its ``rows`` are answered from the ``articles`` table and read healthy
and full over an index that was emptied (measured: after ``delete-all``, docsize 0, status "healthy", ``rows`` = the article count).
``fts_status`` is still compared before and after a stop, as the app's own probe, but it cannot be the evidence of the index's size.

How soon a stop is noticed INSIDE the rebuild is a measurement, not a pinned constant: the copy's progress handler fires every 100,000
virtual-machine steps of one prepared statement, and a small store's rebuild never takes that many (the stop is then honoured when the
rebuild has finished, at the copy's check). ``test_a_stop_inside_the_rebuild...`` runs both ends: the copy's own handler (the stop is
noticed after the rebuild) and a finer one of the same shape set by the test on the same connection (noticed inside it);
``test_the_copys_connection_hears_the_stop_it_was_given`` pins that the copy's own connection does poll the stop it was handed.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import damage, fts, repair, salvage, verify
from src.database.damage import FILE_CORPUS, DamageRegistry
from src.database.models import Article, Base, Source

from . import damaged_store_helpers as H

REPO = Path(__file__).resolve().parents[1]
UNCLEAN = {"clean": False, "at": "2026-10-06T01:00:00+00:00", "basis": "the liveness file"}
#: Three batches of 500 after the two damaged pages are lost: a stop in the second one has a third to NOT run.
ARTICLES = 1300


# --------------------------------------------------------------------------- #
#  a process of the test's own: its registry, its marker, its recorded engine
# --------------------------------------------------------------------------- #
def new_process(folder: Path, monkeypatch) -> DamageRegistry:
    """What a fresh start has: an empty in-memory registry over the folder's record file, and no check run yet."""
    registry = DamageRegistry(path_fn=lambda: folder / "database-damage.json")
    monkeypatch.setattr(damage, "registry", registry)
    monkeypatch.setattr(repair, "_marker_path", lambda: folder / repair.ATTEMPT_FILE)
    verify._reset_for_tests()
    repair._reset_for_tests()
    return registry


def recorded_engine(monkeypatch) -> list[str]:
    """The running app's engine is a recorder: what is asserted is the repair's file work (as ``test_repair`` does)."""
    from src.database import session

    calls: list[str] = []
    monkeypatch.setattr(session, "dispose_engine", lambda: calls.append("dispose"))
    monkeypatch.setattr(session, "init_db", lambda: calls.append("init_db"))
    monkeypatch.setattr(repair, "_after_the_swap", lambda: calls.append("after") or {"corpus_epoch": 1, "source_counts_cleared": 0})
    monkeypatch.setattr(repair, "_empty_the_log", lambda target, watch: None)
    return calls


def measure(live: Path, monkeypatch) -> None:
    """The start-up check reads the file and measures it ``damaged`` in THIS process (what a repair acts on, R100)."""
    monkeypatch.setattr(damage, "_file_paths", lambda key: (live, live.name) if key == FILE_CORPUS else (None, None))
    monkeypatch.setattr(damage, "_previous_end", lambda: UNCLEAN)
    assert verify.arm_at_boot() is True
    assert verify.run_armed() is True


def damaged_live(folder: Path) -> Path:
    live = folder / "live.db"
    H.build_app_store(live, articles=ARTICLES)
    leaves = H.leaf_pages(live, "articles")
    step = max(1, len(leaves) // 3)
    H.overwrite_pages(live, [leaves[step], leaves[2 * step]], H.PLAIN_PAGE)
    return live


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    registry = new_process(tmp_path, monkeypatch)
    yield registry
    verify._reset_for_tests()
    repair._reset_for_tests()


# --------------------------------------------------------------------------- #
#  reading the index the way the app does
# --------------------------------------------------------------------------- #
def index_state(path: Path) -> dict:
    """``fts.fts_status`` over a plain engine on ``path``: the app's own probe. For this external-content index it reads the ``articles``
    table, so it cannot say how many documents the index holds (see the module docstring): use :func:`documents_indexed_in`."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(f"sqlite:///{path}")
    try:
        with Session(engine) as session:
            return fts.fts_status(session)
    finally:
        engine.dispose()


def articles_in(path: Path) -> int:
    con = sqlite3.connect(path)
    try:
        return int(con.execute("SELECT count(*) FROM articles").fetchone()[0])
    finally:
        con.close()


def documents_indexed_in(path: Path) -> int | None:
    """The documents a scratch copy's index holds, or ``None`` when the copy cannot say (a file cut mid-write may not open): a copy that
    cannot say is a copy whose index is not known to be complete, which is the same answer for the purpose of a swap."""
    try:
        con = sqlite3.connect(path)
        try:
            return int(con.execute("SELECT count(*) FROM article_fts_docsize").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return None


def folder_files(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir() if not p.name.endswith(("-wal", "-shm"))}


# --------------------------------------------------------------------------- #
#  a stop inside the rebuild
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("noticed", ["after the rebuild (the copy's own handler)", "inside the rebuild (a finer handler of the same shape)"])
def test_a_stop_inside_the_rebuild_ends_the_repair_stopped_and_the_live_index_reads_as_it_did(tmp_path, monkeypatch, reg, noticed):
    recorded = recorded_engine(monkeypatch)
    live = damaged_live(tmp_path)
    measure(live, monkeypatch)
    before_bytes = H.sha(live)
    before_index = index_state(live)
    # The app's own probe reads the index as present and healthy (what it reads is the content table: see the module docstring); the
    # index's own size is the shadow table's.
    assert before_index["present"] is True and before_index["healthy"] is True, before_index
    assert documents_indexed_in(live) == ARTICLES, "the fixture's live index must be whole for the comparison to mean anything"

    inside = noticed.startswith("inside")
    batches: list[int] = []
    copies: list[salvage.Salvage] = []
    real_rows, real_phase = fts._index_rows, salvage.Salvage._rebuild_search_index

    def the_copy(self, tables):
        copies.append(self)
        return real_phase(self, tables)

    def stopping(con, rows, caps):
        batches.append(len(rows))
        if len(batches) == 2:
            if inside:
                # The copy's handler fires every 100,000 steps of ONE statement, which no statement of a store this small reaches; the
                # same handler (it returns 1 once the stop the COPY was handed is asked) at every 100th step is what a big store's own does.
                con.set_progress_handler(lambda: 1 if copies[0].cancel.is_set() else 0, 100)
            repair.stop()
        return real_rows(con, rows, caps)

    monkeypatch.setattr(salvage.Salvage, "_rebuild_search_index", the_copy)
    monkeypatch.setattr(fts, "_index_rows", stopping)
    work = repair.plan()
    assert work is not None and work["kind"] == "repair"
    report = repair.run(work)

    assert len(copies) == 1 and copies[0].cancel is repair._CANCEL, "the copy was not handed the repair's stop"
    assert len(batches) >= 2, "the stop was never asked inside the rebuild"
    if inside:
        assert len(batches) == 2, f"the third batch ran after a stop that landed inside the second: {batches}"
    else:
        assert len(batches) == 3, f"the copy's own handler interrupted the rebuild of a store this small (the case is the other one now): {batches}"
    assert report["outcome"] == "stopped", report
    assert recorded == [], "the engine was touched by a repair that never swapped"
    assert H.sha(live) == before_bytes, "the live file changed under a repair that was stopped"
    assert index_state(live) == before_index, "the live file's full-text index reads differently after a stopped repair"
    assert documents_indexed_in(live) == ARTICLES, "the live file's index lost documents under a stopped repair"
    assert not list(tmp_path.glob("live.salvage-*")), "the half-built copy or its side files outlived the stop"
    assert not list(tmp_path.glob("live.damaged-*")), "a kept file exists though no swap ran"
    record = reg.repairs()[-1]
    assert record["state"] == "stopped"
    assert "search_index" not in record and "search_index" not in report, (
        "a stopped repair states a search-index figure for an index it threw away"
    )
    assert "kept_rows" not in record and "kept_file" not in record, record


def test_the_copys_connection_hears_the_stop_it_was_given(tmp_path, monkeypatch):
    """The copy's own connection carries a progress handler on the stop it was handed: a statement that runs past the handler's
    interval while the stop is clear is left alone, and one that does while it is set is interrupted by SQLite itself. (The rebuild's
    own statements are too short for this to fire in a store a test can afford: the figure is in the shipped log.)"""
    import threading

    store = tmp_path / "small.db"
    H.build_app_store(store, articles=30)
    stop = threading.Event()
    heard: dict[str, object] = {}
    # a recursive query of a few million steps in ONE statement: past the handler's interval many times over
    longer = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < {n}) SELECT count(*) FROM c"

    def at_the_rebuild(self, tables):
        heard["clear"] = self.dst.execute(longer.format(n=300_000)).fetchone()[0]
        stop.set()
        try:
            self.dst.execute(longer.format(n=20_000_000)).fetchone()
        except sqlite3.OperationalError as exc:
            heard["set"] = str(exc)

    monkeypatch.setattr(salvage.Salvage, "_rebuild_search_index", at_the_rebuild)
    salvage.Salvage(store, tmp_path / "out.partial", cancel=stop).run()
    assert heard.get("clear") == 300_000, heard
    assert str(heard.get("set", "")).startswith("interrupted"), heard


# --------------------------------------------------------------------------- #
#  a process killed inside the rebuild
# --------------------------------------------------------------------------- #
#: The child is the next-best thing to a power cut the suite can run: a real process that dies by SIGKILL on the second batch of the
#: rebuild, with no handler, no ``finally`` and no atexit hook given a chance (``tests/test_db_reliability_torture.py`` does the same).
_CHILD = """
import os, signal, sys
from pathlib import Path
import pytest
from tests import test_repair_search_index as T
from src.database import fts, repair

folder = Path(sys.argv[1])
mp = pytest.MonkeyPatch()
T.new_process(folder, mp)
T.recorded_engine(mp)
T.measure(folder / "live.db", mp)
real, seen = fts._index_rows, []

def dies(con, rows, caps):
    seen.append(len(rows))
    if len(seen) == 2:
        os.kill(os.getpid(), signal.SIGKILL)
    return real(con, rows, caps)

mp.setattr(fts, "_index_rows", dies)
work = repair.plan()
assert work is not None and work["kind"] == "repair", work
repair.run(work)
sys.exit(3)  # the repair came back: the kill was never reached
"""


@pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL crash injection is POSIX-only")
def test_a_process_killed_inside_the_rebuild_leaves_the_live_file_alone_and_a_copy_that_is_never_swapped_in(tmp_path, monkeypatch, reg):
    recorded_engine(monkeypatch)
    live = damaged_live(tmp_path)
    before_bytes = H.sha(live)
    assert documents_indexed_in(live) == ARTICLES

    env = dict(os.environ, OO_DATA_DIR=str(tmp_path / "data"), OO_NO_SCHEDULER="1")
    proc = subprocess.run([sys.executable, "-c", _CHILD, str(tmp_path)], capture_output=True, text=True, cwd=str(REPO), env=env, timeout=180)
    assert proc.returncode == -signal.SIGKILL, f"the child did not die inside the rebuild: rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"

    # what the kill left: the library untouched, one scratch copy, and nothing that names that copy as finished
    assert H.sha(live) == before_bytes, "the live file changed under a repair that was killed"
    partials = sorted(tmp_path.glob("live.salvage-*.db.partial"))
    assert len(partials) == 1, folder_files(tmp_path)
    assert not list(tmp_path.glob("live.salvage-*.json")), "a sidecar names a copy whose index was never finished"
    assert not list(tmp_path.glob("live.salvage-*.db")), "a copy was given its final name"
    assert not list(tmp_path.glob("live.damaged-*")), "the kept file exists though no swap ran"
    # ...whose rows are all there and whose index is not: measured, the killed copy reads clean to ``quick_check`` with every article
    # copied and an index holding none of them (the rebuild's inserts were one uncommitted transaction), so only the missing sidecar and
    # the scratch name keep it from being swapped in as a healthy file
    copied, indexed = articles_in(partials[0]), documents_indexed_in(partials[0])
    assert copied > ARTICLES - 200, "the fixture's copy had not finished its rows when the kill came"
    assert indexed is not None and indexed < copied, f"the killed copy's index holds {indexed} of {copied} articles: it claims to be complete"

    # the next start: this process measures the damage itself, the unfinished start is counted, a fresh copy is made and swapped in
    new_process(tmp_path, monkeypatch)
    recorded = recorded_engine(monkeypatch)
    measure(live, monkeypatch)
    work = repair.plan()
    assert work is not None and work["kind"] == "repair", "a killed start must not be mistaken for a copy to resume"
    report = repair.run(work)
    assert report["outcome"] == "repaired", report
    assert report["unfinished_starts"] == 1, "the killed start was not counted"
    assert not list(tmp_path.glob("live.salvage-*")), folder_files(tmp_path)
    kept = sorted(tmp_path.glob("live.damaged-*.db"))
    assert len(kept) == 1 and H.sha(kept[0]) == before_bytes, "the damaged file was not kept byte for byte"
    assert index_state(live)["healthy"] is True
    assert documents_indexed_in(live) == articles_in(live) == report["search_index"]["documents"], (
        "the repaired file's index does not hold exactly its articles and the documents the report counted"
    )
    assert recorded[0] == "dispose" and recorded[-2:] == ["init_db", "after"], recorded


# --------------------------------------------------------------------------- #
#  a cut after the copy is whole
# --------------------------------------------------------------------------- #
def test_a_cut_before_the_swap_carries_the_index_figure_and_the_resumed_file_has_exactly_that_index(tmp_path, monkeypatch, reg):
    from src.backup import merge

    recorded_engine(monkeypatch)
    live = damaged_live(tmp_path)
    measure(live, monkeypatch)
    real_replace = merge._replace_live_corpus

    def cut(*a, **kw):
        raise OSError(5, "the power went out")

    monkeypatch.setattr(merge, "_replace_live_corpus", cut)
    before_bytes = H.sha(live)
    with pytest.raises(OSError):
        repair.run(repair.plan())
    assert H.sha(live) == before_bytes, "the live file changed before the replace"

    sidecars = list(tmp_path.glob("live.salvage-*.db.json"))
    finished = list(tmp_path.glob("live.salvage-*.db"))
    assert len(sidecars) == 1 and len(finished) == 1, folder_files(tmp_path)
    doc = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert doc["search_index"]["documents"] == articles_in(finished[0]) == documents_indexed_in(finished[0]), (
        "the sidecar's figure for the index is not what the finished copy holds"
    )
    assert articles_in(finished[0]) < ARTICLES, "the fixture lost no rows, so the figure cannot be told from the live file's"

    monkeypatch.setattr(merge, "_replace_live_corpus", real_replace)
    work = repair.plan()
    assert work["kind"] == "resume"
    report = repair.run(work)
    assert report["outcome"] == "repaired" and report["resumed"] is True, report
    assert report["search_index"] == doc["search_index"], "the resume lost the first start's figure for the index"
    assert index_state(live)["healthy"] is True
    assert documents_indexed_in(live) == articles_in(live) == report["search_index"]["documents"], (
        "the file swapped in does not hold an index of exactly its articles and the documents the record counted"
    )
    assert reg.repairs()[-1]["search_index"] == doc["search_index"], "the record does not state the index the file was swapped in with"


# --------------------------------------------------------------------------- #
#  The Export lane's check of the same question, in-process (its draft: export-lane/fts-settle, 2026-10-27)
# --------------------------------------------------------------------------- #
# The tests above kill or stop a repair; these die INSIDE ``rebuild_index`` of the live file's own paths (the "always" rebuild and the
# empty-heal), after the 'delete-all' and after batches have been written (``_index_rows`` raises on its third call; the raise stands for
# the kill, and the same states were measured with 14 real SIGKILLs on a 40,000-article store). The two existing tests of a rebuild that
# dies (test_fts_tokenizer_rebuild.py) raise BEFORE ``rebuild_index`` writes anything, so a ``rebuild_index`` that committed per batch
# passes them; it fails these. Mutant, measured: ``commit()`` after each ``_index_rows`` call leaves the index at 10 of 40 in both.
_EXPORT_ARTICLES = 40


def _export_store():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    fts.ensure_fts(eng)
    with sessionmaker(bind=eng, future=True)() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        for i in range(_EXPORT_ARTICLES):
            s.add(Article(url=f"u{i}", canonical_url=f"u{i}", source_id=1, title=f"Story {i}", content=f"election token{i}x", hash=f"h{i}", language="en"))
        s.commit()
    return eng


def _export_indexed(eng) -> int:
    with eng.connect() as c:
        return c.execute(text("SELECT count(*) FROM article_fts_docsize")).scalar()


def _export_findable(eng) -> int:
    with eng.connect() as c:
        return sum(
            1 for i in range(_EXPORT_ARTICLES)
            if c.execute(text("SELECT rowid FROM article_fts WHERE article_fts MATCH :q"), {"q": f"token{i}x"}).fetchall()
        )


def _die_on_the_third_batch(monkeypatch):
    monkeypatch.setattr(fts, "_REBUILD_BATCH", 5)
    real, calls = fts._index_rows, {"n": 0}

    def dying(con, rows, caps):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("the process died here")
        return real(con, rows, caps)

    monkeypatch.setattr(fts, "_index_rows", dying)
    return real


def _prefix_index(eng) -> None:
    """The state no app writer leaves (measured) but a torn file copy or a hand-made restore can: the first half of the articles indexed."""
    with eng.begin() as c:
        c.execute(text("INSERT INTO article_fts(article_fts) VALUES ('delete-all')"))
        c.execute(text("DELETE FROM article_fts_norm"))
        fts.index_articles(c, list(range(1, _EXPORT_ARTICLES // 2 + 1)))


def test_a_full_rebuild_that_dies_after_some_batches_leaves_the_whole_old_index(monkeypatch):
    eng = _export_store()
    assert _export_indexed(eng) == _EXPORT_ARTICLES
    real = _die_on_the_third_batch(monkeypatch)
    with pytest.raises(RuntimeError):
        fts.ensure_fts(eng, rebuild="always")
    monkeypatch.setattr(fts, "_index_rows", real)
    assert (_export_indexed(eng), _export_findable(eng)) == (_EXPORT_ARTICLES, _EXPORT_ARTICLES), "neither a prefix of the rebuild nor an empty index"
    assert fts.ensure_fts(eng) == "skipped"


def test_an_emptied_index_whose_rebuild_dies_after_some_batches_is_empty_and_the_next_boot_fills_it(monkeypatch):
    eng = _export_store()
    with eng.begin() as c:
        c.execute(text("INSERT INTO article_fts(article_fts) VALUES ('delete-all')"))  # the "rare interrupted past rebuild" state
    real = _die_on_the_third_batch(monkeypatch)
    with pytest.raises(RuntimeError):
        fts.ensure_fts(eng)  # auto: an empty index while articles exist -> a rebuild, which dies
    monkeypatch.setattr(fts, "_index_rows", real)
    assert (_export_indexed(eng), _export_findable(eng)) == (0, 0), "the rebuild's own writes were rolled back with it: no prefix is left"
    assert fts.ensure_fts(eng) == "rebuilt"
    assert (_export_indexed(eng), _export_findable(eng)) == (_EXPORT_ARTICLES, _EXPORT_ARTICLES)


@pytest.mark.xfail(
    strict=True,
    reason="a boot reads ANY docsize row as 'settled' (the boot compares no counts: see the SCOPE paragraph of ensure_fts), so a prefix "
    "index (some rows, not all) is skipped and nothing repairs it; fts_status names it instead (the next test). Flips when a boot repairs one.",
)
def test_a_prefix_index_is_not_read_as_settled_by_a_boot():
    eng = _export_store()
    _prefix_index(eng)
    assert _export_indexed(eng) == _EXPORT_ARTICLES // 2
    assert fts.ensure_fts(eng) == "rebuilt"


def test_a_prefix_index_that_a_boot_reads_as_settled_is_named_partial_inferred_by_fts_status():
    """What the xfail above cannot say: the diagnostic does. The ends (the highest document id against the highest article id) differ, so the
    state is named and refuses the healthy verdict; nothing is counted or repaired, and the boot still skips it."""
    eng = _export_store()
    _prefix_index(eng)
    with sessionmaker(bind=eng, future=True)() as s:
        st = fts.fts_status(s)
    assert st["indexed_documents"] == _EXPORT_ARTICLES // 2 and st["rows"] == _EXPORT_ARTICLES, "rows reads the content table: it cannot show it"
    assert st["index_state"] == "partial (inferred)" and st["healthy"] is False and st["error"] == "PartialIndex"
    assert fts.ensure_fts(eng) == "skipped", "the boot's refusal to count the articles stands"
