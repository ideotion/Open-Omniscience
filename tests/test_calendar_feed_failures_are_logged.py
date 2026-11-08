"""The calendar feed store no longer drops an exception without a record (R386; the same class as the import-all route in #1621).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three sites in ``src/events/feeds.py`` swallowed an exception and left NO trace:

* ``_save_json``: the mirror into the event_imports table (``sync_imports``) was wrapped in a bare ``pass``. ``sync_imports`` logs its own database errors; what reached
  the ``pass`` is everything that fails BEFORE it can (the call itself, building the rows), so a stale mirror had no record anywhere.
* ``verify_due_feeds``: a feed whose verification raised was counted failed with no word about why, and the attempt that moves it up the re-check ladder was written
  under ``suppress(Exception)``: if THAT write failed too, the feed never advanced its rung and was re-picked on every pass, silently.
* ``auto_import_due_feeds``: ``failed += 1`` with nothing about the failure.

A feed URL could carry credentials (the bundled catalogue has none today: this is defence in depth), and the exception text of a fetch failure quotes the URL, so every line is checked to carry neither the URL nor
the credentials in it. Behaviour and tallies are unchanged: these tests pin only that the failure is now on the record, and the "never advances" consequence.
"""

from __future__ import annotations

import json

import pytest

from src.events import feeds as F
from tests.os_scope import scope_os

CRED_URL = "https://alice:hunter2@calendar.example/feed.ics"


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    yield
    F._READ_AS_DAMAGED.clear()  # the marks of a test's own folder go with it


def _first_feed_ids(n: int) -> list[str]:
    return [f["id"] for fam in F.load_families() for f in fam["feeds"]][:n]


def _hold_credentials_in(monkeypatch) -> None:
    """Make every feed one whose URL carries credentials (whichever feed a pass picks first, its URL is the credentialed one)."""
    monkeypatch.setattr(F, "feed_by_id", lambda feed_id: ({"name": "x"}, {"id": feed_id, "url": CRED_URL}))


def _fetch_error() -> RuntimeError:
    return RuntimeError(f"request error for {CRED_URL}: ('Connection aborted.', RemoteDisconnected('x'))")


def _assert_clean(text: str) -> None:
    assert CRED_URL not in text and "hunter2" not in text, "the feed's URL and the credentials in it never reach a log line"


def test_a_mirror_failure_before_sync_imports_can_start_is_on_the_record(monkeypatch, caplog):
    def _boom(data):
        raise RuntimeError("mirror boom")

    monkeypatch.setattr("src.events.event_store.sync_imports", _boom)
    with caplog.at_level("WARNING"):
        F._save_json("calendar_feed_imports.json", {"fam": {"events": {}}})
    assert "event_imports mirror could not be synced" in caplog.text
    assert "RuntimeError" in caplog.text
    assert F._load_json("calendar_feed_imports.json") == {"fam": {"events": {}}}, "the JSON write, which is authoritative, is untouched"


def test_a_verification_that_raises_is_counted_failed_and_now_logged_without_its_url(monkeypatch, caplog):
    _hold_credentials_in(monkeypatch)
    seen: list[str] = []

    def _verify(fetcher, feed_id):
        seen.append(feed_id)
        raise _fetch_error()

    monkeypatch.setattr(F, "verify_feed", _verify)
    with caplog.at_level("WARNING"):
        out = F.verify_due_feeds(object(), batch=1)
    (fid,) = seen
    assert out["failed"] == 1 and out["checked"] == 1, "the tally is unchanged"
    assert fid in caplog.text and "RuntimeError" in caplog.text, "the feed id and the exception class are on the record"
    _assert_clean(caplog.text)


def test_a_failed_attempt_write_is_logged_and_the_feed_is_repicked_the_next_pass(monkeypatch, caplog):
    """The consequence, reproduced: if the attempt that advances a feed's rung cannot be written, the feed is picked again by the next pass; with a working write it is not."""
    (fid,) = _first_feed_ids(1)
    picked: list[str] = []

    def _verify(fetcher, feed_id):
        picked.append(feed_id)
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(F, "verify_feed", _verify)

    def _no_write(feed_id, status, *, at=None):
        raise OSError("disk full")

    monkeypatch.setattr(F, "record_attempt", _no_write)
    with caplog.at_level("WARNING"):
        F.verify_due_feeds(object(), batch=1)
        F.verify_due_feeds(object(), batch=1)
    assert picked == [fid, fid], "no attempt recorded, so the same never-checked feed is first in line again"
    assert caplog.text.count("could not be written") == 2, "the failed ladder write is no longer silent, on both passes"


def test_with_the_attempt_written_the_next_pass_moves_on_to_another_feed(monkeypatch):
    """The control of the test above: a working ladder write advances the feed, so the second pass picks a different one."""
    picked: list[str] = []

    def _verify(fetcher, feed_id):
        picked.append(feed_id)
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(F, "verify_feed", _verify)
    F.verify_due_feeds(object(), batch=1)
    F.verify_due_feeds(object(), batch=1)
    assert len(picked) == 2 and picked[0] != picked[1]


def test_an_auto_import_failure_is_counted_and_now_logged_without_its_url(monkeypatch, caplog):
    _hold_credentials_in(monkeypatch)
    seen: list[str] = []

    def _import(fetcher, feed_id):
        seen.append(feed_id)
        raise _fetch_error()

    monkeypatch.setattr(F, "import_feed", _import)
    with caplog.at_level("WARNING"):
        out = F.auto_import_due_feeds(object(), batch=1)
    (fid,) = seen
    assert out["failed"] == 1 and out["imported"] == 0, "the tally is unchanged"
    assert fid in caplog.text and "RuntimeError" in caplog.text
    _assert_clean(caplog.text)
    assert fid in F._load_json("calendar_autoimport.json"), "the attempt is still stamped so a failing feed backs off"


def test_when_the_feed_cannot_be_looked_up_the_line_carries_the_class_only_never_the_message(monkeypatch, caplog):
    """Fail closed: with nothing known to take out, the exception's text (which quotes the URL) is not logged at all, at either site that holds a fetch error."""

    def _lookup_fails(feed_id):
        raise OSError("catalogue unreadable")

    monkeypatch.setattr(F, "feed_by_id", _lookup_fails)
    monkeypatch.setattr(F, "verify_feed", lambda fetcher, feed_id: (_ for _ in ()).throw(_fetch_error()))
    monkeypatch.setattr(F, "import_feed", lambda fetcher, feed_id: (_ for _ in ()).throw(_fetch_error()))
    with caplog.at_level("WARNING"):
        v = F.verify_due_feeds(object(), batch=1)
        a = F.auto_import_due_feeds(object(), batch=1)
    assert v["failed"] == 1 and a["failed"] == 1, "tallies unchanged"
    assert caplog.text.count("RuntimeError") >= 2 and "its text is withheld" in caplog.text, "the class is on the record"
    _assert_clean(caplog.text)
    assert "request error" not in caplog.text and "Connection aborted" not in caplog.text, "none of the exception's words are kept"
    assert "Traceback" not in caplog.text, "nor a traceback, whose last line is the message"


def test_a_feed_the_catalogue_does_not_know_is_also_class_only(monkeypatch, caplog):
    monkeypatch.setattr(F, "feed_by_id", lambda feed_id: None)
    monkeypatch.setattr(F, "verify_feed", lambda fetcher, feed_id: (_ for _ in ()).throw(_fetch_error()))
    with caplog.at_level("WARNING"):
        F.verify_due_feeds(object(), batch=1)
    _assert_clean(caplog.text)
    assert "RuntimeError" in caplog.text


def _fail_both(monkeypatch):
    monkeypatch.setattr(F, "verify_feed", lambda fetcher, feed_id: (_ for _ in ()).throw(_fetch_error()))

    def _no_write(feed_id, status, *, at=None):
        raise OSError("disk full")

    monkeypatch.setattr(F, "record_attempt", _no_write)


def test_a_failed_attempt_write_does_not_carry_the_fetch_failures_text_by_chaining(monkeypatch, caplog):
    """The write fails INSIDE the verification's handler, so it is chained to the fetch failure and its traceback prints that failure's text and URL as well. The write's
    own line is scrubbed with the same secrets."""
    _hold_credentials_in(monkeypatch)
    _fail_both(monkeypatch)
    with caplog.at_level("WARNING"):
        F.verify_due_feeds(object(), batch=1)
    assert "could not be written" in caplog.text and "OSError" in caplog.text
    _assert_clean(caplog.text)


def test_a_failed_attempt_write_is_class_only_when_the_feed_cannot_be_looked_up(monkeypatch, caplog):
    monkeypatch.setattr(F, "feed_by_id", lambda feed_id: None)
    _fail_both(monkeypatch)
    with caplog.at_level("WARNING"):
        F.verify_due_feeds(object(), batch=1)
    assert caplog.text.count("its text is withheld") == 2, "both lines, the verification's and the write's, are class only"
    assert "OSError" in caplog.text and "RuntimeError" in caplog.text
    _assert_clean(caplog.text)
    assert "request error" not in caplog.text and "Traceback" not in caplog.text


# ---- a store that exists but cannot be read (R397) -----------------------------------------------------------------------------------------------------------


def _store(name: str):
    return F._store_path(name)


_TORN = '{"fam": {"name": "F", "events": {"fp1": {"title": "kept?"}}}  <-- torn'
_NEW = {"fam2": {"name": "G", "events": {"fp2": {"title": "new"}}}}


def _kept(name: str):
    return _store(name + ".damaged")


def test_a_damaged_store_is_on_the_record_and_its_bytes_are_kept_before_the_next_save_replaces_it(caplog):
    """The reproduction: a torn ``calendar_feed_imports.json`` holding one imported event, then a restore-merge of one new event. The merge stands as before (added 1)
    and the store holds the new event; since R397 (b) (item 31) the damaged bytes are kept, byte for byte, as ``calendar_feed_imports.json.damaged``."""
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    with caplog.at_level("WARNING"):
        out = F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert out["added"] == 1, "behaviour unchanged"
    assert "calendar_feed_imports.json exists but could not be read" in caplog.text and "JSONDecodeError" in caplog.text
    assert "kept as calendar_feed_imports.json.damaged" in caplog.text
    assert "kept?" not in caplog.text and "torn" not in caplog.text, "the class only: nothing of the store's content or the parser's words"
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam2"], "the save still writes the new store"
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == _TORN, "the damaged bytes survive, unchanged"


def test_an_earlier_kept_copy_is_never_overwritten_by_a_second_damage(caplog):
    _kept("calendar_feed_imports.json").write_text("first evidence", "utf-8")
    _store("calendar_feed_imports.json").write_text(_TORN, "utf-8")
    with caplog.at_level("WARNING"):
        F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == "first evidence"
    assert "an earlier copy is already kept as calendar_feed_imports.json.damaged" in caplog.text
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam2"], "the save goes on, as it did before"


def test_the_copy_is_made_once_and_a_later_healthy_save_moves_nothing():
    _store("calendar_feed_imports.json").write_text(_TORN, "utf-8")
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    F.merge_imported_store("calendar_feed_imports.json", {"fam3": {"name": "H", "events": {"fp3": {"title": "later"}}}})
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == _TORN
    assert sorted(F._load_json("calendar_feed_imports.json")) == ["fam2", "fam3"], "the second save read a healthy store and replaced it as usual"


def test_a_store_repaired_between_the_damaged_read_and_the_save_is_not_moved():
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    p.write_text(json.dumps({"fam": {"name": "F", "events": {"fp1": {"title": "repaired"}}}}), "utf-8")
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam"]
    assert p not in F._READ_AS_DAMAGED, "the healthy read cleared the mark"
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert not _kept("calendar_feed_imports.json").exists(), "the healthy read cleared the mark"
    assert sorted(F._load_json("calendar_feed_imports.json")) == ["fam", "fam2"]


@pytest.mark.parametrize("body", ["[1]", "null", '{"fam": "not a family"}'])
def test_an_imports_store_that_parses_but_reads_as_empty_is_kept_too(body):
    _store("calendar_feed_imports.json").write_text(body, "utf-8")
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == body


@pytest.mark.parametrize("body", [None, "{}"])
def test_an_absent_or_empty_imports_store_leaves_no_copy(body):
    if body is not None:
        _store("calendar_feed_imports.json").write_text(body, "utf-8")
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert not _kept("calendar_feed_imports.json").exists()


def test_the_stores_the_next_pass_rebuilds_are_replaced_as_before_with_no_copy():
    """Only the imported-events store holds the user's own imports; the re-check ladder is rebuilt by the next pass (the proposal's scope)."""
    _store("calendar_feed_attempts.json").write_text("{torn", "utf-8")
    F.record_attempt(_first_feed_ids(1)[0], "ok")
    assert not _kept("calendar_feed_attempts.json").exists()
    assert _first_feed_ids(1)[0] in F.load_attempts()


def test_a_read_under_one_data_folder_never_moves_a_store_under_another(monkeypatch, tmp_path):
    _store("calendar_feed_imports.json").write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    other = tmp_path / "other"
    other.mkdir()
    (other / "calendar_feed_imports.json").write_text(json.dumps(_NEW), "utf-8")  # a healthy store there, so only the PATH key keeps it in place
    monkeypatch.setenv("OO_DATA_DIR", str(other))
    F._save_json("calendar_feed_imports.json", {"fam3": {"name": "H", "events": {}}}, mirror=False)
    assert not (other / "calendar_feed_imports.json.damaged").exists()


def test_a_passing_read_error_does_not_mark_a_healthy_store(monkeypatch):
    """EMFILE, or a Windows sharing violation while another thread replaces the file, is not damage: marking it would spend the one copy on healthy bytes."""
    import errno
    import pathlib

    p = _store("calendar_feed_imports.json")
    p.write_text(json.dumps(_NEW), "utf-8")
    real = pathlib.Path.read_text

    def flaky(self, *a, **k):
        if self == p:
            raise OSError(errno.EMFILE, "too many open files")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", flaky)
    assert F._load_json("calendar_feed_imports.json") == {}
    monkeypatch.setattr(pathlib.Path, "read_text", real)
    F._save_json("calendar_feed_imports.json", {"fam3": {"name": "H", "events": {}}}, mirror=False)
    assert not _kept("calendar_feed_imports.json").exists()


def test_an_io_error_in_the_file_marks_it(monkeypatch):
    import errno
    import pathlib

    p = _store("calendar_feed_imports.json")
    p.write_text("bytes on a bad sector", "utf-8")
    real = pathlib.Path.read_text

    def eio(self, *a, **k):
        if self == p:
            raise OSError(errno.EIO, "input/output error")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", eio)
    assert F._load_json("calendar_feed_imports.json") == {}
    monkeypatch.setattr(pathlib.Path, "read_text", real)
    F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == "bytes on a bad sector"


def test_a_copy_that_cannot_be_made_never_blocks_the_save_and_leaves_no_mark_on_the_new_store(monkeypatch, caplog):
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    real = F.os.replace
    calls = {"n": 0}

    def refuse_the_copy(src, dst):
        if str(dst).endswith(".damaged") and calls["n"] == 0:
            calls["n"] += 1
            raise PermissionError("held open")
        return real(src, dst)

    scope_os(monkeypatch, F, replace=refuse_the_copy, link=_no_links)  # the move path: a drive with no second names, and the move refused
    with caplog.at_level("WARNING"):
        F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert p not in F._READ_AS_DAMAGED, "the new store is healthy: a mark left on it would move it at the next save"
    assert "could not be kept as calendar_feed_imports.json.damaged" in caplog.text and "PermissionError" in caplog.text
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam2"], "the save went on"


def test_a_store_that_cannot_be_opened_is_on_the_record(caplog):
    _store("calendar_feed_attempts.json").mkdir()  # a directory where the file belongs: IsADirectoryError on Linux and macOS, PermissionError on Windows
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_attempts.json") == {}
    assert "calendar_feed_attempts.json exists but could not be read" in caplog.text
    assert "IsADirectoryError" in caplog.text or "PermissionError" in caplog.text
    assert "replaces" not in caplog.text, "the line makes no claim about a save, which cannot succeed where the store is a directory"


def test_an_absent_or_healthy_store_logs_nothing(caplog):
    _store("calendar_autoimport.json").write_text('{"a": "2026-01-01T00:00:00+00:00"}', "utf-8")
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_imports.json") == {}, "absent"
        assert F._load_json("calendar_autoimport.json") == {"a": "2026-01-01T00:00:00+00:00"}, "healthy"
    assert "could not be read" not in caplog.text


def _cut_mid_character(p) -> None:
    """A store cut right after the first byte of a two-byte character: the shape of a torn write of ``ensure_ascii=False`` JSON holding "Noël"."""
    whole = json.dumps({"fam": {"name": "F", "events": {"fp1": {"title": "Noël"}}}}, ensure_ascii=False).encode("utf-8")
    p.write_bytes(whole[: whole.index("ë".encode()) + 1])


def test_a_store_cut_mid_character_reads_as_empty_and_is_on_the_record_instead_of_raising(caplog):
    """``read_text("utf-8")`` raises UnicodeDecodeError (a ValueError, not a JSONDecodeError) on such a file; that used to escape ``_load_json`` and fail the readers."""
    _cut_mid_character(_store("calendar_feed_imports.json"))
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_imports.json") == {}
        assert F.load_imports() == {}, "the reader the API serves from reads it as empty too"
    assert "calendar_feed_imports.json exists but could not be read" in caplog.text and "UnicodeDecodeError" in caplog.text
    assert "No" + "ël" not in caplog.text and "fp1" not in caplog.text, "no fragment of the store's text"


def test_a_store_cut_mid_character_is_kept_byte_for_byte_before_the_next_save():
    p = _store("calendar_feed_imports.json")
    _cut_mid_character(p)
    cut = p.read_bytes()
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_bytes() == cut


def test_a_restore_merge_over_a_store_cut_mid_character_merges_instead_of_raising():
    _cut_mid_character(_store("calendar_feed_imports.json"))
    out = F.merge_imported_store("calendar_feed_imports.json", {"fam2": {"name": "G", "events": {"fp2": {"title": "new"}}}})
    assert out["added"] == 1
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam2"]


# --- a store that parses but cannot be walked or written (R397; the restore stage that ends on it) ------------------------------------
_LONE = '"\\ud800"'  # the JSON text of a lone surrogate escape: ``json`` parses it, and no file can hold it as UTF-8


@pytest.mark.parametrize("body", ["[1]", '"x"', "3", "null"])
def test_a_store_that_is_not_a_json_object_reads_as_empty_and_names_its_type_only(body, caplog):
    """Before: ``_load_json`` handed the list (or string, number, None) to its caller, whose first ``.items()`` / ``.get()`` raised AttributeError."""
    _store("calendar_feed_imports.json").write_text(body, "utf-8")
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_imports.json") == {}
        assert F.load_imports() == {}
    assert "calendar_feed_imports.json holds JSON that is not an object" in caplog.text
    assert "(list)" in caplog.text or "(str)" in caplog.text or "(int)" in caplog.text or "(NoneType)" in caplog.text, "the type of the document is named"


@pytest.mark.parametrize("incoming", [[1], "x", 3, None])
def test_a_restore_merge_of_an_artifact_store_that_is_not_an_object_merges_nothing_instead_of_raising(incoming, caplog):
    for name in ("calendar_feed_imports.json", "calendar_feed_checks.json"):
        with caplog.at_level("WARNING"):
            out = F.merge_imported_store(name, incoming)
        assert out == {"action": "merged", "added": 0, "enriched": 0, "kept_local": 0}, name


def test_a_lone_surrogate_in_the_store_is_replaced_so_that_reading_and_every_later_save_work(caplog):
    """Before: the store parsed, and ``_save_json``'s ``write_text`` raised UnicodeEncodeError on it, on every save from then on."""
    _store("calendar_feed_imports.json").write_text(
        '{"fam": {"name": LONE, "events": {"fp1": {"title": LONE, "sources": ["a"]}}}}'.replace("LONE", _LONE), "utf-8"
    )
    with caplog.at_level("WARNING"):
        data = F._load_json("calendar_feed_imports.json")
    assert data["fam"]["name"] == "�" and data["fam"]["events"]["fp1"]["title"] == "�"
    assert data["fam"]["events"]["fp1"]["sources"] == ["a"], "everything else is untouched"
    assert "2 text(s) held a lone surrogate escape" in caplog.text
    assert "ud800" not in caplog.text.lower() and "\ud800" not in caplog.text, "a count, never the text"
    F._save_json("calendar_feed_imports.json", data, mirror=False)  # raised UnicodeEncodeError before
    assert _store("calendar_feed_imports.json").read_bytes().decode("utf-8")


def test_a_restore_merge_of_an_artifact_store_holding_a_lone_surrogate_merges_instead_of_ending_the_restore():
    incoming = json.loads('{"fam2": {"name": LONE, "events": {"fp2": {"title": LONE, "sources": ["b"]}}}}'.replace("LONE", _LONE))
    out = F.merge_imported_store("calendar_feed_imports.json", incoming)  # raised UnicodeEncodeError at the save
    assert out["added"] == 1
    stored = json.loads(_store("calendar_feed_imports.json").read_text("utf-8"))
    assert stored["fam2"]["events"]["fp2"]["title"] == "�"
    verdicts = F.merge_imported_store("calendar_feed_checks.json", {"feed-1": {"status": json.loads(_LONE)}})
    assert verdicts["added"] == 1 and json.loads(_store("calendar_feed_checks.json").read_text("utf-8"))["feed-1"]["status"] == "�"


_GOOD = {"name": "F", "events": {"fpok": {"title": "ok", "sources": ["a"], "uids": ["u"]}}}


@pytest.mark.parametrize(
    "wrong",
    [
        {"fam": 3},
        {"fam": {"name": "F", "events": [1]}},
        {"fam": {"name": "F", "events": {"fp": 3}}},
        {"fam": {"name": "F", "events": {"fp": {"sources": "a", "uids": 7}}}},
    ],
)
def test_valid_json_of_the_wrong_shape_is_left_out_and_counted_not_raised_on(wrong, caplog):
    """Before: AttributeError at the first ``.items()`` / ``.get()`` / ``.setdefault`` on the wrong piece, in the reader or in the restore merge."""
    local = {"keep": _GOOD, **wrong}
    _store("calendar_feed_imports.json").write_text(json.dumps(local), "utf-8")
    with caplog.at_level("WARNING"):
        read = F._load_json("calendar_feed_imports.json")
    assert read["keep"] == _GOOD, "a well-formed family beside it is untouched"
    assert "of the wrong shape were left out of what is read" in caplog.text
    out = F.merge_imported_store("calendar_feed_imports.json", {"new": _GOOD, **wrong})  # as an artifact's store, over the same local store
    assert out["added"] == 1, "the one well-formed incoming event is merged"
    after = json.loads(_store("calendar_feed_imports.json").read_text("utf-8"))
    assert after["keep"]["events"] == _GOOD["events"] and after["new"]["events"] == _GOOD["events"]
    assert not any(isinstance(b, dict) and b.get("events") in ([1],) for b in after.values())


# --- the Opus read of the boundary above (what it must not cost, and what it must not leave) -----------------------------------------
def test_a_deeply_nested_healthy_store_still_reads_and_merges_as_it_did_before(caplog):
    """The surrogate walk recurses once per level; a healthy store of 3000 levels read cleanly before the boundary and must not raise RecursionError now."""
    deep = '{"f":' * 3000 + "1" + "}" * 3000
    _store("calendar_feed_checks.json").write_text(deep, "utf-8")
    with caplog.at_level("WARNING"):
        assert "f" in F._load_json("calendar_feed_checks.json")
        out = F.merge_imported_store("calendar_feed_checks.json", json.loads(deep))
    assert out["kept_local"] == 1 and "nested too deeply" not in caplog.text


def test_a_store_nested_too_deeply_to_check_for_a_surrogate_reads_as_empty_and_says_so(caplog):
    deep = '{"f":' * 3000 + '"\\ud800"' + "}" * 3000
    _store("calendar_feed_checks.json").write_text(deep, "utf-8")
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_checks.json") == {}
    assert "is nested too deeply to check for lone surrogate escapes" in caplog.text


def test_a_non_text_item_in_sources_is_left_out_so_the_reader_does_not_raise_on_it(caplog):
    """``load_imports`` tests ``s not in _REDUNDANT_DEFAULT_FEEDS``: an object in the list raised TypeError (unhashable)."""
    store = {"f": {"name": "F", "events": {"a": {"sources": [{"z": 1}, "feed-1", 7], "uids": ["u", None, ["x"]]}}}}
    _store("calendar_feed_imports.json").write_text(json.dumps(store), "utf-8")
    with caplog.at_level("WARNING"):
        got = F.load_imports()
    assert got["f"]["events"]["a"]["sources"] == ["feed-1"]
    assert "3 piece(s) of the wrong shape" in caplog.text or "4 piece(s) of the wrong shape" in caplog.text


def test_two_keys_that_become_one_once_their_surrogates_are_replaced_are_counted_not_lost_silently(caplog):
    _store("calendar_feed_checks.json").write_text('{"\\ud800": {"t": 1}, "\\udfff": {"t": 2}, "ok": {"t": 3}}', "utf-8")
    with caplog.at_level("WARNING"):
        got = F._load_json("calendar_feed_checks.json")
    assert sorted(got) == ["ok", "�"]
    assert "1 entry(ies) shared a key" in caplog.text


def test_a_healthy_imports_store_comes_back_exactly_as_it_was_written_key_order_included():
    healthy = {"f": {"events": {"a": {"sources": ["s"], "x": 1}}, "name": "F", "x": 2}, "g": {"name": "G", "events": {}}}
    _store("calendar_feed_imports.json").write_text(json.dumps(healthy), "utf-8")
    got = F._load_json("calendar_feed_imports.json")
    assert got == healthy and list(got["f"]) == ["events", "name", "x"], "no key moved"
    assert list(got["g"]) == ["name", "events"], "the order of a family that had both keys is kept"


_ICS = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:u1\nSUMMARY:Day\nDTSTART;VALUE=DATE:20270101\nEND:VEVENT\nEND:VCALENDAR\n"


@pytest.mark.parametrize("local", [{"name": "F"}, {"name": "F", "events": None}])
def test_a_family_with_no_events_or_a_null_one_reads_as_an_empty_dict_so_no_reader_or_merge_raises(local, caplog):
    """Before the fold: ``events`` stayed missing/None, and the merge (``.items()``), ``imported_agenda`` and the importers raised on it."""
    _store("calendar_feed_imports.json").write_text(json.dumps({"f": dict(local)}), "utf-8")
    assert F._load_json("calendar_feed_imports.json")["f"]["events"] == {}
    out = F.merge_imported_store("calendar_feed_imports.json", {"f": {"name": "F", "events": {"a": {"title": "t", "date": "2027-01-01", "sources": ["s"], "uids": []}}}})
    assert out["added"] == 1
    after = json.loads(_store("calendar_feed_imports.json").read_text("utf-8"))
    assert list(after["f"]["events"]) == ["a"]


@pytest.mark.parametrize("local", [{"name": "F"}, {"name": "F", "events": None}])
def test_the_agenda_and_the_ics_import_walk_a_family_with_no_events(local):
    _store("calendar_feed_imports.json").write_text(json.dumps({"user-f": dict(local)}), "utf-8")
    assert F.imported_agenda() == []
    got = F.import_ics_text("F", _ICS)
    assert got["added"] == 1 and got["family_total"] == 1


@pytest.mark.parametrize("field", ["sources", "uids"])
def test_a_null_sources_or_uids_reads_as_an_empty_list_so_the_restore_merge_does_not_raise(field):
    """``le.setdefault(field, [])`` hands back a stored None, and the ``in`` test that follows raised TypeError."""
    local = {"user-f": {"name": "F", "events": {"x|2026-12-01": {"title": "X", field: None}}}}
    _store("calendar_feed_imports.json").write_text(json.dumps(local), "utf-8")
    assert F._load_json("calendar_feed_imports.json")["user-f"]["events"]["x|2026-12-01"][field] == []
    incoming = {"user-f": {"events": {"x|2026-12-01": {"sources": ["b"], "uids": ["u"]}}}}
    F.merge_imported_store("calendar_feed_imports.json", incoming)
    after = json.loads(_store("calendar_feed_imports.json").read_text("utf-8"))
    entry = after["user-f"]["events"]["x|2026-12-01"]
    assert entry["sources"] == ["b"] and entry["uids"] == ["u"]


def test_a_store_replaced_after_the_damaged_read_is_not_moved():
    """A reader that read the torn file can note its mark after another writer has already kept the bytes and written a healthy store: the
    mark carries the identity of the file READ, so the healthy file that replaced it is never moved into the one ``.damaged`` slot."""
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    fresh = p.with_name("fresh.json")
    fresh.write_text(json.dumps({"fam": {"name": "F", "events": {"fp1": {"title": "a later, healthy store"}}}}), "utf-8")
    F.os.replace(fresh, p)  # what another writer's save does: a new file under the store's name
    F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert not _kept("calendar_feed_imports.json").exists()
    assert p not in F._READ_AS_DAMAGED


def test_on_windows_a_read_error_carries_no_winerror_and_does_not_mark_the_store(monkeypatch):
    """What ``Path.read_text`` raises on Windows comes from the C runtime's errno alone (a bad sector reads as EACCES or EINVAL, as a sharing
    violation does), so nothing tells damage from a passing lock there and the store is not marked: the residual R397 (b) states."""
    import errno
    import pathlib

    p = _store("calendar_feed_imports.json")
    p.write_text("bytes on a bad sector", "utf-8")
    real = pathlib.Path.read_text

    def crt_error(self, *a, **k):
        if self == p:
            raise PermissionError(errno.EACCES, "permission denied")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", crt_error)
    assert F._load_json("calendar_feed_imports.json") == {}
    monkeypatch.setattr(pathlib.Path, "read_text", real)
    F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert not _kept("calendar_feed_imports.json").exists()


def test_a_passing_read_error_after_a_damaged_read_keeps_the_mark(monkeypatch):
    """The Agenda reads the torn store (marked), a second read hits EMFILE: that says nothing about the file, so the next save still keeps it."""
    import errno
    import pathlib

    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    real = pathlib.Path.read_text

    def emfile(self, *a, **k):
        if self == p:
            raise OSError(errno.EMFILE, "too many open files")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", emfile)
    assert F._load_json("calendar_feed_imports.json") == {}
    monkeypatch.setattr(pathlib.Path, "read_text", real)
    F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == _TORN


@pytest.mark.parametrize("body", ["", "  \n"])
def test_an_empty_store_does_not_spend_the_one_copy(body):
    """A file left empty (a power cut before the data reached the disk) holds nothing to recover; a later real damage must still find the slot free."""
    p = _store("calendar_feed_imports.json")
    p.write_text(body, "utf-8")
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    if body == "":
        assert not _kept("calendar_feed_imports.json").exists()
    else:
        assert _kept("calendar_feed_imports.json").read_text("utf-8") == body, "whitespace is kept: a few bytes, and not the common case"


def test_the_identity_is_the_file_read_not_the_file_found_after_the_read(monkeypatch):
    """The store is replaced by a healthy one WHILE the torn one is being read: the mark carries the torn file's identity, so the save moves nothing."""
    import pathlib

    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    real = pathlib.Path.read_text

    def read_then_replaced(self, *a, **k):
        text = real(self, *a, **k)
        if self == p:
            fresh = p.with_name("fresh.json")
            fresh.write_text(json.dumps({"fam": {"name": "F", "events": {}}}), "utf-8")
            F.os.replace(fresh, p)
        return text

    monkeypatch.setattr(pathlib.Path, "read_text", read_then_replaced)
    assert F._load_json("calendar_feed_imports.json") == {}
    monkeypatch.setattr(pathlib.Path, "read_text", real)
    F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert not _kept("calendar_feed_imports.json").exists()


def test_without_a_second_name_the_copy_is_still_made_by_a_move(monkeypatch):
    """A FAT or exFAT data folder cannot hard-link: the copy falls back to the check-then-move, and the bytes survive the same way."""
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")

    scope_os(monkeypatch, F, link=_no_links)
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == _TORN
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam2"]


def _no_links(src, dst):
    raise OSError(1, "operation not permitted")


def test_without_a_second_name_an_earlier_copy_is_still_never_overwritten(monkeypatch):
    _kept("calendar_feed_imports.json").write_text("first evidence", "utf-8")
    _store("calendar_feed_imports.json").write_text(_TORN, "utf-8")
    scope_os(monkeypatch, F, link=_no_links)
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == "first evidence"


def test_a_failed_write_leaves_the_damaged_store_where_it_was_and_makes_no_copy(monkeypatch):
    import pathlib

    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    real = pathlib.Path.write_text

    def disk_full(self, *a, **k):
        if self.name.endswith(".tmp"):
            raise OSError(28, "no space left on device")
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", disk_full)
    with pytest.raises(OSError):
        F._save_json("calendar_feed_imports.json", _NEW, mirror=False)
    assert p.read_text("utf-8") == _TORN and not _kept("calendar_feed_imports.json").exists()


@pytest.mark.parametrize("links", [True, False])
def test_a_store_replaced_between_the_check_and_the_copy_is_given_back(monkeypatch, links):
    """Two saves race: this one passed the identity check, and another writer's new store lands under the name before the copy is made.
    The copy's identity is checked after it is made, so the new store is not taken into the one slot."""
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    assert F._load_json("calendar_feed_imports.json") == {}
    healthy = json.dumps({"fam": {"name": "F", "events": {}}})
    real_identity = F._identity
    swapped = {"done": False}

    def identity_then_swap(path):
        out = real_identity(path)
        if path == p and not swapped["done"]:
            swapped["done"] = True
            fresh = p.with_name("fresh.json")
            fresh.write_text(healthy, "utf-8")
            F.os.replace(fresh, p)  # lands right after the check
        return out

    monkeypatch.setattr(F, "_identity", identity_then_swap)
    if not links:
        scope_os(monkeypatch, F, link=_no_links)
    F._keep_damaged_bytes("calendar_feed_imports.json", p)
    assert not _kept("calendar_feed_imports.json").exists(), "the slot stays free"
    assert p.read_text("utf-8") == healthy, "the other writer's store is where it was"


def test_json_nested_too_deeply_for_the_parser_reads_as_empty_and_is_kept(caplog):
    p = _store("calendar_feed_imports.json")
    p.write_text("[" * 200000, "utf-8")
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_imports.json") == {}
    assert "RecursionError" in caplog.text
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == "[" * 200000


def test_a_move_that_changes_only_the_file_index_still_keeps_the_copy(monkeypatch):
    """Windows on FAT or exFAT (no hard links, so the move path) gives a renamed file a new index: the copy is still kept, by mtime and size."""
    p = _store("calendar_feed_imports.json")
    p.write_text(_TORN, "utf-8")
    real_identity = F._identity

    def new_index_after_a_rename(path):
        out = real_identity(path)
        return (out[0] + 1, out[1], out[2]) if out is not None and path.name.endswith(".damaged") else out

    monkeypatch.setattr(F, "_identity", new_index_after_a_rename)
    scope_os(monkeypatch, F, link=_no_links)
    F.merge_imported_store("calendar_feed_imports.json", _NEW)
    assert _kept("calendar_feed_imports.json").read_text("utf-8") == _TORN
