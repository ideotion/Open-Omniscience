"""Row 428 (R835 (b)): one safety copy deleted by hand, by one click, only one the app recorded when it made it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, python_function_source
from tests.os_scope import scope_os

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    import src.backup.own_net as own
    import src.backup.sqlite_backup as sb

    data = tmp_path / "data"
    data.mkdir()
    live = data / "corpus.db"
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    monkeypatch.setattr(own, "data_dir", lambda: data)
    monkeypatch.setattr(sb, "live_db_path", lambda: live)
    monkeypatch.setattr(own, "_OWN", {})
    forgotten: list[str] = []
    from src.database import at_rest_state

    monkeypatch.setattr(at_rest_state, "forget_copy", lambda p: forgotten.append(Path(p).name))
    return data, live, forgotten


_n = [0]


def _copy(data: Path, live: Path, *, record: bool = True) -> Path:
    from src.backup import own_net as own

    _n[0] += 1
    net = data / f"pre-restore-20261125T10{_n[0] // 60:02d}{_n[0] % 60:02d}Z.db"
    shutil.copyfile(live, net)
    if record:
        own.note_made(net)
    return net


def _two(folder):
    """An older copy, then an import run that completed and was checked, then a newer copy (a run that did not finish)."""
    from src.backup import own_net as own

    data, live, _f = folder
    old = _copy(data, live)
    own.note_run_verified()
    return old, _copy(data, live)


def test_the_record_holds_the_copy_identity_and_never_a_byte_of_it(folder):
    from src.backup import own_net as own

    data, live, _f = folder
    net = _copy(data, live)
    entry = own.read_record()[net.name]
    st = os.stat(net)
    assert entry["file"] == [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
    assert isinstance(entry["made_ns"], int) and entry["state"] == own.MADE and entry["seq"] == 1
    raw = (data / own.RECORD_NAME).read_bytes()
    assert net.read_bytes()[:16] not in raw
    own.note_activation(net)
    assert own.read_record()[net.name]["file"] == entry["file"], "a later state keeps what identifies the copy"


def test_the_list_offers_recorded_copies_counts_the_others_and_holds_back_the_newest(folder):
    from src.backup import own_net as own

    data, live, _f = folder
    old, new = _two(folder)
    stray = _copy(data, live, record=False)
    got = own.list_copies()
    names = {c["name"]: c for c in got["copies"]}
    assert set(names) == {old.name, new.name} and got["unrecorded"] == 1 and got["count"] == 3
    assert stray.name not in names
    assert names[old.name]["deletable"] and names[old.name]["reason"] is None
    assert not names[new.name]["deletable"] and names[new.name]["reason"] == own.LATEST_UNFINISHED
    assert own.read_record()[own.VERIFIED_KEY] == {"covers": 1}
    assert names[old.name]["plaintext"] is True, "a SQLite header is read as plaintext; nothing is ever called encrypted"
    assert names[old.name]["bytes"] == old.stat().st_size and names[old.name]["made_at"].endswith("+00:00")


def test_the_newest_copy_is_freed_only_by_a_run_that_completed_and_was_checked_after_it(folder):
    from src.backup import own_net as own

    old, new = _two(folder)
    assert own.remove_copy(new.name)["message"] == own.LATEST_UNFINISHED and new.exists()
    own.note_run_verified()
    out = own.remove_copy(new.name)
    assert out["removed"] and out["message"] in (own.DELETED, own.DELETED_FREED) and not new.exists()
    assert old.exists(), "one copy per click"


def test_a_deleted_copy_takes_its_record_and_at_rest_entries_and_measures_what_it_freed(folder, monkeypatch):
    from src.backup import own_net as own

    _data, _live, forgotten = folder
    old, _new = _two(folder)
    reads = iter([1000, 5096])
    monkeypatch.setattr(own, "_free_bytes", lambda dfd: next(reads))
    out = own.remove_copy(old.name)
    assert out["removed"] and not old.exists()
    assert old.name not in own.read_record() and forgotten == [old.name]
    assert out["freed"] == 4096 and out["message"] == own.DELETED_FREED, "the drive's own free space, before and after"


@pytest.mark.parametrize("reads", [[5000, 5000], [5000, 4000], [None, 9000], [9000, None]])
def test_a_delete_that_freed_nothing_measurable_claims_no_figure(folder, monkeypatch, reads):
    """A cloned copy shares blocks with the corpus, another program may hold it, other writes move the drive: no figure is
    made up then (R785)."""
    from src.backup import own_net as own

    old, _new = _two(folder)
    it = iter(reads)
    monkeypatch.setattr(own, "_free_bytes", lambda dfd: next(it))
    out = own.remove_copy(old.name)
    assert out["removed"] and out["freed"] is None and out["message"] == own.DELETED


def test_a_clock_stepped_back_never_frees_a_later_copy(folder, monkeypatch):
    """Serials, not the clock: a copy made after the mark stays held back even when the clock now reads earlier."""
    from src.backup import own_net as own

    data, live, _f = folder
    _copy(data, live)
    own.note_run_verified()
    monkeypatch.setattr(own.time, "time_ns", lambda: 1)  # the clock far in the past
    later = _copy(data, live)
    assert own.remove_copy(later.name)["message"] == own.LATEST_UNFINISHED and later.exists()


def test_a_copy_made_outside_the_queue_never_frees_an_unfinished_runs_copy(folder):
    """A restore outside the import queue never sets the mark: a stopped run's copy and every copy after it stay held."""
    from src.backup import own_net as own

    stopped = _two(folder)[1]
    data, live, _f = folder
    other = _copy(data, live)
    listed = {c["name"]: c["deletable"] for c in own.list_copies()["copies"]}
    assert listed[stopped.name] is False and listed[other.name] is False


def test_an_unreadable_record_is_never_overwritten_by_the_mark_or_a_state(folder):
    from src.backup import own_net as own

    data, live, _f = folder
    old, _new = _two(folder)
    rec = data / own.RECORD_NAME
    rec.write_text("{damaged", encoding="utf-8")
    own.note_run_verified()
    assert rec.read_text(encoding="utf-8") == "{damaged"
    with pytest.raises(OSError):
        own._set_state(old.name, own.ACTIVATED)
    assert rec.read_text(encoding="utf-8") == "{damaged"


def test_what_runs_is_asked_again_under_the_delete_lock(folder):
    from src.backup import own_net as own

    old, _new = _two(folder)
    answers = iter([[], ["a backup"]])
    out = own.remove_copy(old.name, busy=lambda: next(answers))
    assert out["message"] == own.BUSY and old.exists()


def test_a_copy_given_another_name_since_it_was_made_is_not_identified_and_kept(folder):
    """A second name changes the file's change time: it is no longer the file recorded, and nothing is deleted."""
    from src.backup import own_net as own

    old, _new = _two(folder)
    other = old.parent / "kept-by-the-user.db"
    os.link(old, other)
    out = own.remove_copy(old.name)
    assert out["message"] == own.NOT_IDENTIFIED and old.exists() and other.exists()


def test_a_name_swapped_for_a_link_is_not_identified_and_nothing_is_touched(folder, tmp_path):
    from src.backup import own_net as own

    old, _new = _two(folder)
    target = tmp_path / "precious.db"
    target.write_bytes(b"precious")
    old.unlink()
    old.symlink_to(target)
    out = own.remove_copy(old.name)
    assert not out["removed"] and out["message"] == own.NOT_IDENTIFIED
    assert old.is_symlink() and target.read_bytes() == b"precious"


def test_a_replaced_file_is_not_identified_and_kept(folder):
    from src.backup import own_net as own

    data, live, _f = folder
    old, _new = _two(folder)
    old.unlink()
    shutil.copyfile(live, old)  # same name, another file
    out = own.remove_copy(old.name)
    assert out["message"] == own.NOT_IDENTIFIED and old.exists()


@pytest.mark.parametrize("damage", ["missing", "garbage", "no-entry", "no-identity"])
def test_a_missing_or_damaged_record_refuses_and_touches_nothing(folder, damage):
    from src.backup import own_net as own

    data, _live, _f = folder
    old, _new = _two(folder)
    rec = data / own.RECORD_NAME
    if damage == "missing":
        rec.unlink()
    elif damage == "garbage":
        rec.write_text("{not json", encoding="utf-8")
    elif damage == "no-entry":
        rec.write_text("{}", encoding="utf-8")
    else:
        rec.write_text(json.dumps({old.name: {"state": "made"}}), encoding="utf-8")
    out = own.remove_copy(old.name)
    assert out["message"] == own.NOT_IDENTIFIED and old.exists()


@pytest.mark.parametrize("name", ["corpus.db", "../pre-restore-20261125T100001Z.db", "pre-restore-20261125T100001Z.db\n",
                                  "pre-restore-x.db", ""])
def test_only_a_safety_copy_name_is_ever_deleted(folder, name):
    from src.backup import own_net as own

    data, live, _f = folder
    out = own.remove_copy(name)
    assert not out["removed"] and out["message"] == own.NOT_IDENTIFIED and live.exists()


def test_a_running_import_restore_backup_snapshot_or_erase_refuses(folder):
    from src.backup import own_net as own

    old, _new = _two(folder)
    out = own.remove_copy(old.name, busy=["an import"])
    assert out["message"] == own.BUSY and old.exists()


def test_a_failed_delete_says_so_with_the_reason_and_keeps_the_list_accurate(folder, monkeypatch):
    from src.backup import own_net as own

    old, _new = _two(folder)

    def refuse(*a, **k):
        raise PermissionError(13, "Permission denied")

    scope_os(monkeypatch, own, unlink=refuse)
    out = own.remove_copy(old.name)
    assert not out["removed"] and out["message"] == own.NOT_DELETED and out["reason"] == "Permission denied"
    assert old.exists() and old.name in own.read_record()
    assert old.name in {c["name"] for c in own.list_copies()["copies"]}


def test_a_failed_delete_names_the_os_reason_and_never_a_path(folder, monkeypatch):
    """Plan on key 17: {reason} is the OS error text only (strerror), never str(exc), which carries the full path
    (R734: paths stay out of messages and logs). Both failure points are driven: opening the folder and the unlink."""
    import json as _json

    from src.backup import own_net as own

    old, _new = _two(folder)
    data = folder[0]
    where = str(data)

    def refuse_unlink(*a, **k):
        raise PermissionError(13, "Permission denied", str(data / old.name))

    with monkeypatch.context() as m:
        scope_os(m, own, unlink=refuse_unlink)
        out = own.remove_copy(old.name)
    assert out["reason"] == "Permission denied"
    text = _json.dumps(out)
    assert where not in text and "/" not in text.replace(old.name, "")

    def refuse_open():
        raise PermissionError(13, "Permission denied", where)

    monkeypatch.setattr(own, "_open_folder", refuse_open)
    out = own.remove_copy(old.name)
    assert not out["removed"] and out["reason"] == "Permission denied"
    assert where not in _json.dumps(out)
    assert old.exists()


def test_the_words_are_an_ordinary_delete():
    from src.backup import own_net as own

    for msg in (own.DELETED, own.NOT_IDENTIFIED, own.LATEST_UNFINISHED, own.NOT_DELETED, own.BUSY):
        low = msg.lower()
        assert not any(w in low for w in ("erased", "destroy", "securely", "wiped", "shred")), msg


def test_a_panic_wipe_while_it_runs_counts_as_an_erase(monkeypatch):
    import src.api.backup_v2 as bv
    from src.api import safety

    safety._PANIC_RUNNING.set()
    try:
        assert "an erase" in bv._safety_copy_busy()
    finally:
        safety._PANIC_RUNNING.clear()
    src = (_ROOT / "src/api/safety.py").read_text(encoding="utf-8")
    panic = python_function_source(src, "panic")
    assert panic.index("_PANIC_RUNNING.set()") < panic.index("panic_wipe(confirm=True)") < panic.index("_PANIC_RUNNING.clear()")


def test_the_route_needs_a_confirmation_and_names_what_runs(monkeypatch, folder):
    from fastapi import HTTPException

    import src.api.backup_v2 as bv

    with pytest.raises(HTTPException) as e:
        bv.safety_copy_delete(bv.SafetyCopyDeleteBody(name="pre-restore-20261125T100001Z.db"))
    assert e.value.status_code == 400
    old, _new = _two(folder)
    monkeypatch.setattr(bv, "_safety_copy_busy", lambda: ["an erase"])
    out = bv.safety_copy_delete(bv.SafetyCopyDeleteBody(name=old.name, confirm=True))
    assert not out["removed"] and old.exists()
    monkeypatch.setattr(bv, "_safety_copy_busy", lambda: [])
    assert bv.safety_copy_delete(bv.SafetyCopyDeleteBody(name=old.name, confirm=True))["removed"]
    listed = bv.safety_copies_list()
    assert "busy" in listed and all("/" not in c["name"] for c in listed["copies"])


@pytest.mark.parametrize(
    "name",
    [
        "../x",
        "pre-restore-20260101T000000Z.db/..",
        "pre-restore-\u0662\u0660\u0662\u0666\u0661\u0661\u0662\u0665T100001Z.db",  # Arabic-Indic digits
        "pre-restore-20990101T000000Z.db",  # well formed, not in the record
        "~seq",
        "pre-restore-20261125T100001Z.db\x00",
        "p" * 5000,
    ],
)
def test_the_route_refuses_a_forged_name_without_an_error_or_a_path(monkeypatch, folder, name):
    """Final-head read of row 428: a name the record does not hold is refused as "could not be identified" through the
    route itself, never a 500, and neither the data folder's path nor the refused name comes back."""
    import json as _json

    import src.api.backup_v2 as bv
    from src.backup import own_net as own

    data, live, _f = folder
    old, new = _two(folder)
    monkeypatch.setattr(bv, "_safety_copy_busy", lambda: [])
    out = bv.safety_copy_delete(bv.SafetyCopyDeleteBody(name=name, confirm=True))
    assert not out["removed"] and out["message"] == own.NOT_IDENTIFIED
    text = _json.dumps(out)
    assert str(data) not in text
    # Only a well-formed copy name is named back; anything the pattern refuses is never echoed.
    if out["name"] is None:
        assert _json.dumps(name)[1:-1] not in text.replace('"message"', "")
    else:
        assert out["name"] == name and re.fullmatch(own.COPY_NAME, name)
    assert old.exists() and new.exists() and live.exists()


def test_a_record_key_that_names_a_directory_is_refused_and_kept(folder):
    from src.backup import own_net as own

    data, _live, _f = folder
    old, _new = _two(folder)
    old.unlink()
    old.mkdir()  # the record still holds the name; the folder entry is now a directory
    out = own.remove_copy(old.name)
    assert not out["removed"] and out["message"] == own.NOT_IDENTIFIED and old.is_dir()


def test_the_busy_check_counts_an_unreadable_source_as_running(monkeypatch):
    import src.api.backup_v2 as bv
    import src.backup.import_queue as iq

    def broken():
        raise RuntimeError("unreadable")

    monkeypatch.setattr(iq, "get_import_queue", broken)
    assert "an import" in bv._safety_copy_busy()


def test_the_routes_are_post_for_the_delete_and_never_a_bulk_one():
    import src.api.backup_v2 as bv

    routes = {(r.path, tuple(sorted(r.methods))) for r in bv.router.routes}
    assert ("/api/backup/safety-copies/delete", ("POST",)) in routes
    assert ("/api/backup/safety-copies", ("GET",)) in routes
    assert not [p for p, _m in routes if "safety-cop" in p and ("all" in p or "bulk" in p)]


def test_only_a_completed_run_checked_whole_marks_the_run_verified():
    """R843: "done" alone never moves the mark. The end of a run moves it only through _corpus_checked_whole with the
    identity this run recorded after a whole-file check, and otherwise notes the run as unchecked."""
    src = (_ROOT / "src/backup/import_queue.py").read_text(encoding="utf-8")
    body = python_function_source(src, "_drive")
    assert 'completed = self._state == "done"' in body
    tail = body[body.index('completed = self._state == "done"'):]
    assert "if _corpus_checked_whole(self._checked_whole_ident) and self._checked_whole_seq is not None:" in tail
    assert 'self._copy_mark = ("verified", self._checked_whole_seq)' in tail
    assert 'self._copy_mark = ("unchecked", _current_copy_seq())' in tail
    note = python_function_source(src, "_note_safety_copy_mark")
    assert note.index('if kind == "verified":') < note.index("own_net.note_run_verified(covers)") < note.index(
        "own_net.note_run_unchecked(covers)"
    )
    assert src.count("own_net.note_run_verified(") == 1
    run = python_function_source(src, "_run_with_keys")
    assert run.count("mark = self._take_copy_mark()") == 2, "taken after each _drive, while the run still owns it"
    assert run.index("mark = self._take_copy_mark()") < run.index("self._note_safety_copy_mark(mark)")


def test_the_checked_whole_evidence_is_for_the_same_file_state(monkeypatch):
    """R843: positive evidence only. No identity recorded by this run (no whole-file check ran), an identity of an
    earlier file state, an activation record still owed, or a record that cannot be read: none moves the mark."""
    import src.backup.import_queue as iq
    import src.backup.merge as merge

    live = {"ident": (1, 100)}
    monkeypatch.setattr(iq, "_live_corpus_identity", lambda: live["ident"])
    monkeypatch.setattr(merge, "unverified_activation", lambda: None)
    assert iq._corpus_checked_whole((1, 100)) is True
    assert iq._corpus_checked_whole(None) is False, "a done run with no whole-file check leaves the mark"
    assert iq._corpus_checked_whole((1, 99)) is False, "a pass on an earlier file state never counts"
    live["ident"] = None
    assert iq._corpus_checked_whole((1, 100)) is False, "an unreadable live file is no evidence"
    live["ident"] = (1, 100)
    monkeypatch.setattr(merge, "unverified_activation", lambda: {"since": "x", "token": "t"})
    assert iq._corpus_checked_whole((1, 100)) is False, "a check still owed is no evidence"

    def broken():
        raise OSError("unreadable")

    monkeypatch.setattr(merge, "unverified_activation", broken)
    assert iq._corpus_checked_whole((1, 100)) is False


def test_the_evidence_is_recorded_only_after_a_whole_file_check_passed():
    src = (_ROOT / "src/backup/import_queue.py").read_text(encoding="utf-8")
    owed = python_function_source(src, "_check_owed_corpus")
    assert 'if not at_start and got.get("state") == "ok":' in owed
    assert owed.index('got.get("state") == "ok"') < owed.index("self._note_checked_whole()")
    done = python_function_source(src, "_after_item")
    assert 'ver.get("file_check") == "full" and ver.get("file_ok") is True' in done
    assert done.index('if report.get("committed"):') < done.index("self._note_checked_whole()")
    assert src.count("self._note_checked_whole()") == 2
    start = python_function_source(src, "start")
    assert "self._checked_whole_ident = None" in start and "self._checked_whole_seq = None" in start
    drive = python_function_source(src, "_drive")
    void = drive[drive.index('if item.get("kind") != "blobs":'):]
    assert void.index("self._checked_whole_ident = None") < void.index("self._checked_whole_seq = None") < void.index(
        'item["state"] = "running"'
    ), "an item that may write the corpus voids an earlier check before it runs"


def test_the_evidence_keeps_the_serial_read_when_the_check_passed(monkeypatch):
    """R843: identity and serial are read together when the check passes; either unreadable means no evidence."""
    import src.backup.import_queue as iq

    q = iq.ImportQueueManager.__new__(iq.ImportQueueManager)
    monkeypatch.setattr(iq, "_live_corpus_identity", lambda: (1, 100))
    monkeypatch.setattr(iq, "_current_copy_seq", lambda: 7)
    q._note_checked_whole()
    assert (q._checked_whole_ident, q._checked_whole_seq) == ((1, 100), 7)
    monkeypatch.setattr(iq, "_current_copy_seq", lambda: None)
    q._note_checked_whole()
    assert (q._checked_whole_ident, q._checked_whole_seq) == (None, None)
    monkeypatch.setattr(iq, "_current_copy_seq", lambda: 7)
    monkeypatch.setattr(iq, "_live_corpus_identity", lambda: None)
    q._note_checked_whole()
    assert (q._checked_whole_ident, q._checked_whole_seq) == (None, None)


def test_a_copy_made_after_the_check_is_never_covered_and_the_mark_never_goes_back(folder):
    """R843: the mark covers the serial read when the whole-file check passed, so a copy made between that check and
    the run's end stays held; and a later, smaller cover never moves the mark back."""
    from src.backup import own_net as own

    data, live, _f = folder
    old, new = _two(folder)
    at_check = own.current_seq()
    later = _copy(data, live)
    own.note_run_verified(at_check)
    names = {c["name"]: c for c in own.list_copies()["copies"]}
    assert names[new.name]["deletable"] and not names[later.name]["deletable"]
    assert own.read_record()[own.VERIFIED_KEY] == {"covers": at_check}
    own.note_run_verified(at_check - 1)
    assert own.read_record()[own.VERIFIED_KEY] == {"covers": at_check}, "a mark only moves forward"
    own.note_run_verified(10**6)
    assert own.read_record()[own.VERIFIED_KEY] == {"covers": own.current_seq()}, "never above the record's own serial"


def test_the_decided_mark_is_taken_once_and_survives_a_new_start(monkeypatch):
    import src.backup.import_queue as iq

    q = iq.ImportQueueManager.__new__(iq.ImportQueueManager)
    import threading

    q._lock = threading.RLock()
    q._copy_mark = ("verified", 3)
    assert q._take_copy_mark() == ("verified", 3)
    q._copy_mark = None  # what a new start() does
    assert q._take_copy_mark() is None
    wrote = []
    from src.backup import own_net

    monkeypatch.setattr(own_net, "note_run_verified", lambda c: wrote.append(("v", c)))
    monkeypatch.setattr(own_net, "note_run_unchecked", lambda c: wrote.append(("u", c)))
    q._note_safety_copy_mark(("verified", 3))
    q._note_safety_copy_mark(("unchecked", 5))
    q._note_safety_copy_mark(None)
    assert wrote == [("v", 3), ("u", 5)]


def test_a_done_run_without_a_whole_check_keeps_the_copies_and_says_why(folder):
    """R843: the run ended "done" but nothing checked the corpus whole: the mark stays where it was, the copy made since
    stays held, and its row says the corpus has not been checked whole since it was made."""
    from src.backup import own_net as own

    data, live, _f = folder
    old, new = _two(folder)
    before = own.read_record()[own.VERIFIED_KEY]
    third = _copy(data, live)
    own.note_run_unchecked()
    rec = own.read_record()
    assert rec[own.VERIFIED_KEY] == before, "the mark did not move"
    names = {c["name"]: c for c in own.list_copies()["copies"]}
    assert names[old.name]["deletable"]
    for held in (new.name, third.name):
        assert not names[held]["deletable"] and names[held]["reason"] == own.NOT_CHECKED_WHOLE
    out = own.remove_copy(third.name)
    assert not out["removed"] and out["message"] == own.NOT_CHECKED_WHOLE and third.exists()
    fourth = _copy(data, live)
    names = {c["name"]: c for c in own.list_copies()["copies"]}
    assert names[fourth.name]["reason"] == own.LATEST_UNFINISHED, "a copy made after that run is held for its own reason"


def test_the_page_offers_one_delete_per_copy_built_without_markup():
    js = (_ROOT / "src/static/app-backup.js").read_text(encoding="utf-8")
    load = function_body(js, "_uxSafetyCopiesLoad")
    assert "innerHTML" not in load and "textContent" in load
    assert '"/api/backup/safety-copies"' in load
    delete = function_body(js, "_uxSafetyCopyDelete")
    assert "confirm(msg)" in delete and "confirm: true" in delete
    assert "It is the only safety copy of your corpus." in delete
    assert "may remain recoverable on the disk" in delete
    for body in (load, delete):
        assert "all" not in body.lower().replace("call", "").replace("small", ""), "one copy per click, never a bulk delete"
    html = (_ROOT / "src/static/index.html").read_text(encoding="utf-8")
    assert 'id="ux-imp-copies"' in html and 'id="ux-imp-copies-list"' in html
