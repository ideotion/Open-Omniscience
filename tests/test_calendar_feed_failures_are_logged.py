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

import pytest

from src.events import feeds as F

CRED_URL = "https://alice:hunter2@calendar.example/feed.ics"


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    yield


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


def test_a_damaged_store_is_on_the_record_and_the_next_save_still_replaces_it(caplog):
    """The reproduction: a torn ``calendar_feed_imports.json`` holding one imported event, then a restore-merge of one new event. The merge stands as before (added 1) and
    the file afterwards holds ONLY the new event: that residual is pinned here so the day the damaged bytes are kept (proposal item 31) this test changes on purpose."""
    p = _store("calendar_feed_imports.json")
    p.write_text('{"fam": {"name": "F", "events": {"fp1": {"title": "kept?"}}}  <-- torn', "utf-8")
    with caplog.at_level("WARNING"):
        out = F.merge_imported_store("calendar_feed_imports.json", {"fam2": {"name": "G", "events": {"fp2": {"title": "new"}}}})
    assert out["added"] == 1, "behaviour unchanged"
    assert "calendar_feed_imports.json exists but could not be read" in caplog.text and "JSONDecodeError" in caplog.text
    assert "kept?" not in caplog.text and "torn" not in caplog.text, "the class only: nothing of the store's content or the parser's words"
    assert list(F._load_json("calendar_feed_imports.json")) == ["fam2"], "the residual: the damaged store is gone after the save"


def test_a_store_that_cannot_be_opened_is_on_the_record(caplog):
    _store("calendar_feed_attempts.json").mkdir()  # a directory where the file belongs: IsADirectoryError on Linux and macOS, PermissionError on Windows
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_attempts.json") == {}
    assert "calendar_feed_attempts.json exists but could not be read" in caplog.text
    assert "IsADirectoryError" in caplog.text or "PermissionError" in caplog.text


def test_an_absent_or_healthy_store_logs_nothing(caplog):
    _store("calendar_autoimport.json").write_text('{"a": "2026-01-01T00:00:00+00:00"}', "utf-8")
    with caplog.at_level("WARNING"):
        assert F._load_json("calendar_feed_imports.json") == {}, "absent"
        assert F._load_json("calendar_autoimport.json") == {"a": "2026-01-01T00:00:00+00:00"}, "healthy"
    assert "could not be read" not in caplog.text
