"""Row 256 (R702 part 2): each separate store (the lanes: Wikipedia, law, maps, medical papers) can be rebuilt at the current
storage settings, from its own button only.

Plan's three conditions, one group of tests each:

  * the old file is always kept (a dated second name, byte for byte) and never removed by the app on its own;
  * a busy lane is REFUSED with the reason (the Wikipedia stream, an OSM update, a connection still open, a damaged file), never
    paused for the operator, and every file stays as it was;
  * a rebuild starts only from the click: the route is the one caller of ``start`` (nothing schedules one, nothing at boot).

And the switch's own guard (``versioned.store.held_for_swap``): no lane connection is opened while the file is switched, one opened
meanwhile waits and then reads the NEW file, and a connection still open when the switch would begin refuses it.
"""
from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from src.database import rebuild
from src.database.connect import connect, is_encrypted_file, set_passphrase
from src.versioned import store

PASSPHRASE = "a lane shares the corpus passphrase"


class _Ctx:
    stopping = False

    def __init__(self) -> None:
        self.frames: list[str] = []

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail is not None:
            self.frames.append(getattr(detail, "i18n", str(detail)))


@pytest.fixture(autouse=True)
def _reset():
    from src.database import repair

    repair.reset_for_start()
    store.dispose_all()
    rebuild._record({})
    yield
    store.dispose_all()
    repair.reset_for_start()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    set_passphrase(PASSPHRASE)
    monkeypatch.setattr(rebuild, "_others_running", lambda: [])
    try:
        yield tmp_path
    finally:
        store.dispose_all()
        set_passphrase(None)


def _old_lane(kind: str) -> Path:
    """A lane made before DB-10: 4 KiB pages, auto_vacuum NONE, encrypted with the corpus passphrase, with one saved row."""
    path = store.lane_path(kind)
    c = connect(str(path), cipher_page_size=4096, check_same_thread=False)
    c.execute("CREATE TABLE _seed(x)")
    c.commit()
    c.close()
    store.create_lane(kind)
    store.dispose_all()
    c = connect(str(path), cipher_page_size=4096, check_same_thread=False)
    try:
        c.execute("DROP TABLE _seed")
        c.execute("PRAGMA journal_mode = DELETE")
        c.execute("PRAGMA auto_vacuum = 0")
        c.execute("VACUUM")
    finally:
        c.close()
    assert _settings(path)[:2] == (4096, 0)
    return path


def _settings(path: Path) -> tuple[int, int, int, str]:
    c = connect(str(path), check_same_thread=False)  # no page size given: the file must open as it is
    try:
        return (
            int(c.execute("PRAGMA page_size").fetchone()[0]),
            int(c.execute("PRAGMA auto_vacuum").fetchone()[0]),
            int(c.execute("SELECT count(*) FROM lane_meta").fetchone()[0]),
            str(c.execute("PRAGMA quick_check").fetchone()[0]),
        )
    finally:
        c.close()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen(folder: Path) -> dict[str, str]:
    return {p.name: _sha(p) for p in folder.iterdir() if p.is_file() and not p.name.endswith("-shm")}


# --------------------------------------------------------------------------- #
#  the rebuild of each lane: current settings, every row, the old file kept
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["wiki", "law", "osm", "medical"])
def test_a_lane_is_rebuilt_at_the_current_settings_and_its_old_file_is_kept(data_dir, kind):
    path = _old_lane(kind)
    old_sha = _sha(path)
    ctx = _Ctx()

    report = rebuild.run("have_backup", ctx, kind)

    assert report["outcome"] == "rebuilt" and report["store"] == kind, report
    assert _settings(path) == (16384, 2, 1, "ok")
    kept = data_dir / report["kept_file"]
    assert re.fullmatch(re.escape(path.stem) + r"\.pre-rebuild-\d{8}T\d{6}Z" + re.escape(path.suffix), kept.name)
    assert _sha(kept) == old_sha, "the kept file must be the old lane, byte for byte"
    assert is_encrypted_file(path) is True and is_encrypted_file(kept) is True, "encrypted at rest exactly as it was"
    assert not [p for p in data_dir.iterdir() if ".rebuild-" in p.name], "no unfinished copy may stay behind"
    assert ctx.frames == [rebuild.FRAME_COPYING_STORE, rebuild.FRAME_CHECKING, rebuild.FRAME_SWITCHING]
    with store.lane_session(kind) as s:  # the app's own engine opens the new file
        assert s.execute(text("SELECT kind FROM lane_meta")).scalar() == kind
    assert PASSPHRASE not in repr(report) and PASSPHRASE not in repr(rebuild.status_all())


def test_saves_in_the_lane_log_are_in_the_new_file(data_dir):
    path = _old_lane("law")
    with store.lane_session("law") as s:  # WAL mode from the engine's own listener; the saves sit in the log
        s.execute(text("CREATE TABLE IF NOT EXISTS _probe_rows(x INTEGER)"))
        for i in range(50):
            s.execute(text("INSERT INTO _probe_rows VALUES (:i)"), {"i": i})
    assert Path(str(path) + "-wal").exists()

    report = rebuild.run("have_backup", None, "law")

    assert report["outcome"] == "rebuilt", report
    with store.lane_session("law") as s:
        assert s.execute(text("SELECT count(*) FROM _probe_rows")).scalar() == 50


def test_the_kept_file_is_never_removed_on_its_own_and_only_a_listed_name_is(data_dir):
    _old_lane("law")
    report = rebuild.run("have_backup", None, "law")
    kept_name = report["kept_file"]
    st = rebuild.status_all()
    (law,) = [x for x in st["lanes"] if x["store"] == "law"]
    assert [k["name"] for k in law["kept_copies"]] == [kept_name] and law["needed"] is False
    assert st["kept_copies"] == [], "the library's list never offers a lane's kept file"
    rebuild.status_all()  # a status read sweeps unfinished copies, never a kept one
    assert (data_dir / kept_name).exists()
    with pytest.raises(rebuild.Declined):
        rebuild.remove_kept_copy(kept_name)  # asked as the library's: not one of its kept files
    with pytest.raises(rebuild.Declined):
        rebuild.remove_kept_copy("law.db", "law")  # the live lane is never a kept copy
    assert rebuild.remove_kept_copy(kept_name, "law")["removed"] == kept_name
    assert not (data_dir / kept_name).exists()


def test_a_status_never_creates_an_absent_lane(data_dir):
    st = rebuild.status_all()
    assert st["lanes"] == []
    assert rebuild.status("wiki")["supported"] is False
    assert not list(data_dir.glob("*.db")), "a status must never bring a lane file into existence"


# --------------------------------------------------------------------------- #
#  a busy lane is refused with the reason, every file as it was
# --------------------------------------------------------------------------- #
def _refused(data_dir: Path, kind: str, code: str) -> rebuild.Declined:
    frozen = _frozen(data_dir)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.start("have_backup", kind)
    assert caught.value.code == code
    with pytest.raises(rebuild.Declined) as again:
        rebuild.run("have_backup", None, kind)  # the job checks again before it copies
    assert again.value.code == code
    assert _frozen(data_dir) == frozen, "a refusal leaves every file as it was"
    return caught.value


def test_the_wikipedia_stream_running_refuses_the_wiki_lane_and_names_it(data_dir, monkeypatch):
    _old_lane("wiki")

    class _Runner:
        stopped = False

    monkeypatch.setattr("src.wiki.service.lane_runner", lambda: _Runner())
    refusal = _refused(data_dir, "wiki", "busy")
    assert "Wikipedia stream" in refusal.detail


def test_a_stopped_stream_does_not_hold_the_wiki_lane(monkeypatch):
    class _Runner:
        stopped = True

    monkeypatch.setattr("src.wiki.service.lane_runner", lambda: _Runner())
    assert rebuild._lane_busy("wiki") == []


def test_an_osm_update_running_or_queued_refuses_the_maps_lane(data_dir, monkeypatch):
    _old_lane("osm")
    monkeypatch.setattr("src.osm.update_job.jobs", lambda: [{"state": "queued", "alpha3": "FRA"}])
    refusal = _refused(data_dir, "osm", "busy")
    assert "OSM daily update" in refusal.detail


def test_an_open_connection_refuses_the_lane(data_dir):
    _old_lane("law")
    with store.lane_session("law") as s:
        s.execute(text("SELECT 1"))
        refusal = _refused(data_dir, "law", "busy")
    assert "open connection" in refusal.detail
    assert rebuild.run("have_backup", None, "law")["outcome"] == "rebuilt", "closed again, it is rebuilt"


def test_a_damaged_lane_is_not_copied(data_dir, monkeypatch):
    from src.database import damage

    _old_lane("law")
    monkeypatch.setattr(damage.registry, "latched", lambda kind: kind == "law")
    _refused(data_dir, "law", "damaged")


def test_a_save_after_the_copy_was_checked_is_caught_at_the_switch(data_dir, monkeypatch):
    path = _old_lane("law")
    real = rebuild._check_copy

    def check_then_save(copy, target):
        out = real(copy, target)
        c = connect(str(path), check_same_thread=False)  # a writer the copy did not see, after the copy proved itself
        try:
            c.execute("UPDATE lane_meta SET schema_version = schema_version + 1")
            c.commit()
        finally:
            c.close()
        return out

    monkeypatch.setattr(rebuild, "_check_copy", check_then_save)
    with pytest.raises(rebuild.Declined) as caught:
        rebuild.run("have_backup", None, "law")
    assert caught.value.code == "saved-during-the-copy"
    assert _settings(path)[:2] == (4096, 0), "the lane is as it was"
    assert sorted(p.name for p in data_dir.iterdir() if not p.name.endswith(("-wal", "-shm"))) == ["law.db"], (
        "no kept name and no unfinished copy after a refused switch"
    )


def test_an_unknown_store_is_refused_and_never_echoed(data_dir):
    for call in (lambda: rebuild.start("have_backup", "../etc"), lambda: rebuild.run("have_backup", None, "../etc")):
        with pytest.raises(rebuild.Declined) as caught:
            call()
        assert caught.value.code == "unknown-store" and "../etc" not in str(caught.value)


# --------------------------------------------------------------------------- #
#  the switch's hold on the lane
# --------------------------------------------------------------------------- #
def test_a_connection_still_open_refuses_the_hold(data_dir):
    _old_lane("law")
    with store.lane_session("law") as s:
        s.execute(text("SELECT 1"))
        with pytest.raises(store.LaneInUse) as caught:
            with store.held_for_swap("law"):
                pass
        assert caught.value.count == 1
    with store.held_for_swap("law"):
        pass  # nothing open: the hold is given


def test_a_connection_opened_during_the_hold_waits_and_then_opens_the_new_file(data_dir):
    _old_lane("law")
    seen: list[object] = []
    entered = threading.Event()

    def reader() -> None:
        entered.set()
        with store.lane_session("law") as s:
            seen.append(s.execute(text("SELECT count(*) FROM lane_meta")).scalar())

    with store.held_for_swap("law"):
        t = threading.Thread(target=reader)
        t.start()
        entered.wait(5)
        t.join(0.5)
        assert t.is_alive() and seen == [], "no lane connection is opened while the file is switched"
    t.join(10)
    assert seen == [1]


def test_a_connection_waiting_longer_than_the_hold_allows_is_refused_by_name(data_dir, monkeypatch):
    _old_lane("law")
    monkeypatch.setattr(store, "SWAP_WAIT_S", 0.2)
    with store.held_for_swap("law"):
        with pytest.raises(Exception) as caught:
            with store.lane_session("law") as s:
                s.execute(text("SELECT 1"))
    assert store.SWAPPING_WORDS in str(caught.value)


# --------------------------------------------------------------------------- #
#  only the click starts it; the wipe and the data-folder scope know the names
# --------------------------------------------------------------------------- #
def test_the_route_is_the_only_caller_of_start():
    root = Path(__file__).resolve().parents[1] / "src"
    callers = sorted(
        str(p.relative_to(root)) for p in root.rglob("*.py")
        if re.search(r"\brebuild\.start\(|\bREBUILD_JOB\.start\(", p.read_text(encoding="utf-8"))
    )
    assert callers == ["api/database.py", "database/rebuild.py"], callers
    src = (root / "database" / "rebuild.py").read_text(encoding="utf-8")
    assert src.count("REBUILD_JOB.start(") == 1, "only start() starts the job"


def test_the_route_takes_a_store_and_refuses_an_unknown_one(data_dir, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import database as db_api

    app = FastAPI()
    app.include_router(db_api.router)
    prefix = db_api.router.prefix
    client = TestClient(app)
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(rebuild, "start", lambda answer, store="library": asked.append((answer, store)) or {"started": True})
    assert client.post(prefix + "/rebuild", json={"backup_answer": "have_backup", "store": "nowhere"}).status_code == 400
    assert client.post(prefix + "/rebuild", json={"backup_answer": "have_backup", "store": "law"}).status_code == 200
    assert client.post(prefix + "/rebuild", json={"backup_answer": "have_backup"}).status_code == 200
    assert asked == [("have_backup", "law"), ("have_backup", "library")]
    r = client.post(prefix + "/rebuild/remove-kept", json={"name": "x", "store": "nowhere", "confirm": True})
    assert r.status_code == 400 and "nowhere" not in r.text


def test_the_wipe_and_the_data_folder_scope_know_a_lane_rebuild_names(tmp_path):
    from src.safety.crypto_erase import _db_copies
    from src.safety.data_scope import is_app_owned

    lane = tmp_path / "wiki.db"
    lane.write_bytes(b"x")
    names = ["wiki.pre-rebuild-20261121T101010Z.db", "wiki.rebuild-20261121T101010Z.db.partial"]
    for n in names:
        (tmp_path / n).write_bytes(b"y")
    assert {p.name for p in _db_copies(tmp_path, tmp_path, [lane])} == set(names)
    assert all(is_app_owned(n, lanes=("wiki.db",)) for n in names)


def test_the_panel_offers_each_store_its_own_button():
    root = Path(__file__).resolve().parents[1] / "src" / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "app-settings.js").read_text(encoding="utf-8")
    assert 'id="rebuild-lanes"' in html and "This covers the main library only" not in html
    assert "data-rebuild-store" in js and "JSON.stringify({backup_answer: answer, store})" in js
    assert "JSON.stringify({name, store, confirm: true})" in js
