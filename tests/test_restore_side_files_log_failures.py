"""A log the restore cannot read or cannot write is REPORTED, and the side-files stage goes on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT. In ``merge_side_files`` the logs loop opened the live log with ``open(local, "a")`` and wrote the merged lines with nothing around it: an
``OSError`` (the file cannot be opened for appending, the disk is full) left the stage, and the whole import ended as a failure before the live corpus
was touched, for a diagnostics file. Its sibling steps in the same function (the bulletin and import-report documents, the rings) already catch
``OSError`` per file, report what was refused through ``exception_text`` and go on. The read of the staged member just above it was the other half:
``except OSError: continue`` skipped the log without a word, so the restore report held no entry for it.

WHAT THE STAGE DOES NOW. A log it cannot write has an entry in the report that says so (``write_failed``, with the exception's words, scrubbed) and
counts nothing as appended; a member it cannot read has an entry that says so (``read_failed``). The other logs, and every step after the logs, run
as before. The report of a log that WAS written is unchanged.

The live-log failure is made with a DIRECTORY at the log's path: ``open(dir, "a")`` raises on every platform (``IsADirectoryError`` or
``PermissionError``, both ``OSError``), and unlike ``chmod`` it also fails for the root user a container's test run may be.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.database import connect
from src.monitoring import secret_scrub as ss
from tests.backup_helper import staged_artifact

_KEY = "hunter2-correct-horse-9f3a"


def _stage(tmp_path: Path, members: list[tuple[str, str, bytes]]):
    """A real ``StagedArtifact`` whose members are ``(name, role, bytes)``, written under the staging dir; the live data dir is ``tmp_path/live``."""
    staging = tmp_path / "staging"
    for name, _role, body in members:
        p = staging / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    live = tmp_path / "live"
    live.mkdir(exist_ok=True)
    return staged_artifact(
        staging,
        members=[{"name": name, "role": role} for name, role, _b in members],
        origin_fingerprint="ab" * 32,
    ), live


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))


@pytest.fixture(autouse=True)
def _held(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", _KEY, raising=False)
    ss.forget_held()
    yield
    ss.forget_held()


def test_a_live_log_that_cannot_be_written_is_reported_not_fatal(tmp_path):
    from src.backup.merge import merge_side_files

    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n{"at": 2}\n')])
    (live / "app_errors.jsonl").mkdir()  # a directory where the log should be: it cannot be opened for appending
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["appended"] == 0, "nothing was confirmed written, so nothing is called appended"
    assert entry["duplicate"] == 0
    assert entry["write_failed"], entry


def test_the_stage_goes_on_after_a_log_it_could_not_write(tmp_path):
    from src.backup.merge import merge_side_files

    staged, live = _stage(
        tmp_path,
        [
            ("logs/app_errors.jsonl", "logs", b'{"at": 1}\n'),
            ("logs/runs.jsonl", "logs", b'{"run": 7}\n'),
        ],
    )
    (live / "app_errors.jsonl").mkdir()
    report = merge_side_files(staged)
    assert "write_failed" in report["logs"]["app_errors.jsonl"]
    assert report["logs"]["runs.jsonl"] == {"appended": 1, "duplicate": 0}, "the next log is merged as if nothing had happened"
    assert '{"run": 7}' in (live / "runs.jsonl").read_text("utf-8")
    assert "documents" in report and "keys" in report and "rings" in report, "the steps after the logs ran"


def test_a_full_disk_is_reported_and_duplicate_still_counts_the_lines_the_log_held(tmp_path, monkeypatch):
    """``duplicate`` is a fact about the lines, whatever happened to the write: a member of three lines, one of them already in a live log that then
    cannot be appended to (``ENOSPC``, made by shadowing ``open`` in the module, so the test needs no particular user or file system)."""
    import errno

    from src.backup import merge

    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n{"at": 2}\n{"at": 3}\n')])
    log = live / "app_errors.jsonl"
    log.write_text('{"at": 2}\n', "utf-8")
    real_open = open

    def full(file, mode="r", *args, **kwargs):
        if Path(file) == log and "a" in mode:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(merge, "open", full, raising=False)
    entry = merge.merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["duplicate"] == 1 and entry["appended"] == 0, entry
    assert "No space left on device" in entry["write_failed"], entry
    assert log.read_text("utf-8") == '{"at": 2}\n', "nothing was added to the live log"


class _FailsInside:
    """The live log opens fine; the failure comes while writing, or when the buffer is flushed at close, which is where a full disk really fails."""

    def __init__(self, fh, where):
        self._fh, self._where = fh, where

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        if self._where == "close":
            import errno

            raise OSError(errno.ENOSPC, "No space left on device")
        return False

    def write(self, text):
        if self._where == "write":
            import errno

            raise OSError(errno.ENOSPC, "No space left on device")
        return self._fh.write(text)


@pytest.mark.parametrize("where", ["write", "close"])
def test_a_failure_while_writing_or_flushing_is_reported_too(tmp_path, monkeypatch, where):
    """Not only an ``open`` that fails: a full disk fails in ``write`` or in the flush at close, and the ``try`` must wrap the whole ``with``."""
    from src.backup import merge

    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n{"at": 2}\n')])
    log = live / "app_errors.jsonl"
    log.write_text('{"at": 2}\n', "utf-8")
    real_open = open

    def opens_then_fails(file, mode="r", *args, **kwargs):
        fh = real_open(file, mode, *args, **kwargs)
        return _FailsInside(fh, where) if Path(file) == log and "a" in mode else fh

    monkeypatch.setattr(merge, "open", opens_then_fails, raising=False)
    entry = merge.merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["appended"] == 0 and entry["duplicate"] == 1, entry
    assert "No space left on device" in entry["write_failed"], entry


def test_an_error_with_no_words_still_reads_as_a_failure(tmp_path, monkeypatch):
    """``str(OSError())`` is empty, and an empty ``write_failed`` would be falsy: the entry would read as a log that was written. The class names it."""
    from src.backup import merge

    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n')])
    log = live / "app_errors.jsonl"
    real_open = open

    def wordless(file, mode="r", *args, **kwargs):
        if Path(file) == log and "a" in mode:
            raise OSError()
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(merge, "open", wordless, raising=False)
    entry = merge.merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["write_failed"] == "OSError" and entry["appended"] == 0, entry


def test_a_read_error_with_no_words_still_reads_as_a_failure(tmp_path, monkeypatch):
    from src.backup import merge

    staged, _live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n')])

    def wordless(_path):
        raise OSError()

    monkeypatch.setattr(merge, "_log_lines", wordless)
    entry = merge.merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["read_failed"] == "OSError" and entry["appended"] == 0, entry


def test_the_failure_text_has_a_held_passphrase_taken_out(tmp_path):
    """Written through ``exception_text`` like its siblings: an exception's words can carry a path, and a path can carry anything the file was
    named. The held key is in the log's NAME here, which the exception repeats. What this pins is the TEXT of ``write_failed``; the report's dict KEY is
    the log's file name and is not scrubbed here (it is the same key the happy path has always used, and a real artifact's log names are fixed)."""
    from src.backup.merge import merge_side_files

    fname = f"{_KEY}.jsonl"
    staged, live = _stage(tmp_path, [(f"logs/{fname}", "logs", b'{"at": 1}\n')])
    (live / fname).mkdir()
    logs = merge_side_files(staged)["logs"]
    (entry,) = logs.values()
    assert entry["write_failed"] and _KEY not in entry["write_failed"], entry
    assert "***" in entry["write_failed"], "taken out, not dropped: the words say something was removed"


def test_a_member_that_cannot_be_read_is_reported_not_skipped_in_silence(tmp_path):
    from src.backup.merge import merge_side_files

    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n'), ("logs/runs.jsonl", "logs", b'{"run": 7}\n')])
    member = tmp_path / "staging" / "logs" / "app_errors.jsonl"
    member.unlink()
    member.mkdir()  # a directory where the staged file was: reading it raises an OSError
    report = merge_side_files(staged)
    assert report["logs"]["app_errors.jsonl"]["read_failed"], report["logs"]
    assert report["logs"]["app_errors.jsonl"]["appended"] == 0
    assert report["logs"]["app_errors.jsonl"]["duplicate"] is None, "a log that was never read has no duplicate count, not a zero"
    assert report["logs"]["runs.jsonl"] == {"appended": 1, "duplicate": 0}, "the next log is merged as if nothing had happened"
    assert not (live / "app_errors.jsonl").exists(), "a log that could not be read left nothing behind"


def test_the_read_failure_text_has_a_held_passphrase_taken_out(tmp_path):
    """The same rule for the other half: the words of a read that failed are written through ``exception_text`` too."""
    from src.backup.merge import merge_side_files

    fname = f"{_KEY}.jsonl"
    staged, _live = _stage(tmp_path, [(f"logs/{fname}", "logs", b'{"at": 1}\n')])
    member = tmp_path / "staging" / "logs" / fname
    member.unlink()
    member.mkdir()
    (entry,) = merge_side_files(staged)["logs"].values()
    assert entry["read_failed"] and _KEY not in entry["read_failed"] and "***" in entry["read_failed"], entry


def test_a_log_that_is_written_reports_exactly_what_it_did_before(tmp_path):
    """Control: the shape of a good log's entry did not move (no ``write_failed`` or ``read_failed`` key on the happy path)."""
    from src.backup.merge import merge_side_files

    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1}\n{"at": 2}\n')])
    (live / "app_errors.jsonl").write_text('{"at": 2}\n', "utf-8")
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry == {"appended": 1, "duplicate": 1}, entry
    assert '{"at": 1}' in (live / "app_errors.jsonl").read_text("utf-8")
