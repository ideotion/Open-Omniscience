"""The durable record of the all-diagnostics runs and of the files the page was served (R119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What these pin, each against a way the record could mislead: a run that ended with the app must
read as ended, never as done; no pid, start time or wall clock decides what is this process; a
transfer the page abandoned, or a 100-byte range, must not read as a whole file sent; the file stays
to the last ten runs and never passes its byte ceiling, at the append and not only at a begin; a
torn line costs one line and never the next record; a line that parses but is not ours cannot turn
the recorder off; a failure's words carry no key statement, no passphrase and no person's folder;
the member stays inside its budget and says what it cut; nothing here ever raises into the run it
records.
"""

from __future__ import annotations

import json
import os

import anyio
import pytest

from src.monitoring import diagnostics_runs as r


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    r.reset_for_tests()
    yield tmp_path
    r.reset_for_tests()


def _file(tmp_path):
    return tmp_path / "diagnostics" / "runs.jsonl"


def _lines(tmp_path) -> list[dict]:
    return [json.loads(x) for x in _file(tmp_path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _run(i: int, *, end: bool = True, outcome: str = "done") -> str:
    rid = r.begin_run(f"oo-all-diagnostics-{i:04d}.zip", profile="full")
    if end:
        r.end_run(rid, outcome=outcome, seconds=12.34, size=500 + i, members={"ok": 3})
    return rid


def _foreign(tmp_path, kind: str, **fields) -> None:
    """A line another process (or an older build, or a tool) wrote."""
    rec = {"k": "run", "ev": "begin", "t": "2026-10-05T01:02:03Z", "id": "feedbeef", "file": "old.zip",
           "profile": "full", "pid": os.getpid() + 7, "proc": "another-process", "boot": None, "build": {}}
    rec.update(fields)
    path = _file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------- #
#  Runs
# --------------------------------------------------------------------------- #
def test_a_run_that_began_and_ended_reads_as_how_it_ended_with_its_numbers(_data):
    rid = _run(1)
    (row,) = r.diagnostics_member()["runs"]
    assert row["id"] == rid and row["file"] == "oo-all-diagnostics-0001.zip"
    assert row["state"] == "done" and row["seconds"] == 12.3 and row["bytes"] == 501
    assert row["members"] == {"ok": 3} and row["profile"] == "full"
    assert row["started_at"].endswith("Z") and row["ended_at"].endswith("Z")
    assert "note" not in row


def test_the_begin_line_is_on_disk_before_the_run_does_anything_else(_data):
    rid = r.begin_run("a.zip", profile="light")
    (line,) = _lines(_data)
    assert (line["k"], line["ev"], line["id"], line["file"], line["profile"]) == ("run", "begin", rid, "a.zip", "light")
    assert line["pid"] == os.getpid() and line["proc"] == r._PROCESS
    assert "build" in line, "the build markers ride the begin line"


def test_two_runs_of_one_archive_name_are_two_runs(_data):
    """The archive's name has one-second resolution: two builds begun in one second must not share a
    record, or the second's end would close the first's begin."""
    first = r.begin_run("same.zip", profile="full")
    second = r.begin_run("same.zip", profile="full")
    assert first != second
    r.end_run(first, outcome="done", seconds=1.0)
    rows = {row["id"]: row for row in r.diagnostics_member()["runs"]}
    assert rows[first]["state"] == "done" and rows[second]["state"] == "running"


def test_a_begin_without_an_end_from_a_process_that_is_gone_reads_as_no_end_never_as_a_result(_data):
    _foreign(_data, "run")
    row = r.diagnostics_member()["runs"][0]
    assert row["state"] == "no-end"
    assert "not the process that began it" in row["note"]
    assert "seconds" not in row and "bytes" not in row  # nothing is invented for a run with no result


def test_the_run_this_process_is_running_reads_as_running_until_it_ends(_data):
    rid = r.begin_run("now.zip", profile="full")
    assert r.diagnostics_member()["runs"][0]["state"] == "running"
    r.end_run(rid, outcome="done", seconds=1.0)
    assert r.diagnostics_member()["runs"][0]["state"] == "done"


def test_an_end_that_could_not_be_written_does_not_leave_the_run_running_for_ever(_data, monkeypatch):
    """A full drive refuses the end line. The newest begin of this process must not read "running"
    for the rest of the process's life: that is a build that finished, claimed as one still going."""
    rid = r.begin_run("a.zip", profile="full")
    real_append = r._append
    monkeypatch.setattr(r, "_append", lambda *a, **k: False)
    assert r.end_run(rid, outcome="done", seconds=1.0) is False
    monkeypatch.setattr(r, "_append", real_append)
    row = r.diagnostics_member()["runs"][0]
    assert row["state"] == "no-end" and "no end line was written" in row["note"]


def test_a_pid_the_machine_reused_is_not_the_process_that_began_the_run(_data):
    """The token of the process decides, never the pid: a begin with this very pid from a process of
    another token is another process's, and this process's own begin is its own whatever its pid
    says."""
    _foreign(_data, "run", pid=os.getpid(), proc="the-token-of-another-start")
    assert r.diagnostics_member()["runs"][0]["state"] == "no-end"
    rid = r.begin_run("mine.zip", profile="full")
    rows = {row["id"]: row for row in r.diagnostics_member()["runs"]}
    assert rows[rid]["state"] == "running"


def test_no_clock_and_no_process_start_time_decides_what_is_this_process(_data, monkeypatch):
    """A clock step moves a process's start time as psutil reports it (it is computed from the boot
    time and the wall clock), and the wall clock can read anything: a run begun here still reads as
    running after the clock moved by a day."""
    rid = r.begin_run("a.zip", profile="full")
    monkeypatch.setattr(r, "_now_iso", lambda: "2031-01-01T00:00:00Z")
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    rows = {row["id"]: row for row in r.diagnostics_member()["runs"]}
    assert rows[rid]["state"] == "running"
    assert "psutil" not in r.__dict__ and "_process_start" not in r.__dict__


def test_a_failed_run_keeps_its_reason_as_one_line_cut_to_its_size(_data):
    rid = r.begin_run("f.zip", profile="full")
    r.end_run(rid, outcome="failed", seconds=1.0, error="ValueError: bad\n  thing " + "x" * 1000)
    row = r.diagnostics_member()["runs"][0]
    assert row["state"] == "failed"
    assert "\n" not in row["error"] and len(row["error"]) == r.ERROR_CHARS
    assert row["error"].startswith("ValueError: bad thing ")


def test_a_failure_carries_no_key_statement_and_no_folder_of_the_person(_data):
    data = str(_data)
    text = (
        f"OperationalError: near \"x\": syntax error [SQL: PRAGMA key = 'hunter2''quoted'] "
        f"{data}/diagnostics/x.zip and {os.path.expanduser('~')}/docs and "
        "ATTACH 'file.db' AS d (ENCRYPTION_KEY 'another one') and ATTACH x AS y KEY \"third\""
    )
    rid = r.begin_run("f.zip", profile="full")
    r.end_run(rid, outcome="failed", seconds=1.0, error=text)
    error = r.diagnostics_member()["runs"][0]["error"]
    for leaked in ("hunter2", "quoted", "another one", "third", data):
        assert leaked not in error, leaked
    assert "<data>" in error and "***redacted***" in error


def test_the_cut_is_made_after_the_key_statement_is_taken_out(_data):
    """A cut first would keep the opening of a statement whose literal then lost its closing quote,
    and the literal's start is a piece of the key."""
    padding = "x" * 270
    rid = r.begin_run("f.zip", profile="full")
    r.end_run(rid, outcome="failed", seconds=1.0, error=f"{padding} PRAGMA key = 'abcdefghij1234567890'")
    error = r.diagnostics_member()["runs"][0]["error"]
    assert "abcdef" not in error and len(error) <= r.ERROR_CHARS


SECRET = "correct horse's battery"


def _held(monkeypatch, secret: str = SECRET) -> None:
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", secret)


@pytest.mark.parametrize("carrier", range(8))
def test_every_form_of_the_passphrase_is_taken_out_of_a_failure_before_it_is_cut(_data, monkeypatch, carrier):
    """The text is made free of the passphrase WHOLE and cut last: a form that straddles the cut would
    otherwise leave its first characters behind, which no scrub of the cut text can see."""
    from src.monitoring.secret_scrub import held_shapes

    _held(monkeypatch)
    forms = held_shapes()  # every shape of the held passphrase, longest first
    assert forms is not None and len(forms) >= 8, forms
    form = forms[carrier]
    lead = "RuntimeError: "
    for straddle in (3, 8, len(form) - 2):  # the cut lands this many characters INTO the form
        assert 0 < straddle < len(form)
        # the form starts `straddle` characters before the cut, so a cut made first keeps its opening
        padding = "x" * (r.ERROR_CHARS - straddle - len(lead))
        text = f"{lead}{padding}{form} and then some"
        assert text[r.ERROR_CHARS - straddle :].startswith(form), "the form must start where the cut leaves its opening"
        rid = r.begin_run("f.zip", profile="full")
        r.end_run(rid, outcome="failed", seconds=1.0, error=text)
        error = next(row["error"] for row in r.diagnostics_member()["runs"] if row["id"] == rid)
        assert error != r.WITHHELD, (carrier, straddle)
        assert form[:straddle] not in error and form[:3] not in error, (carrier, straddle)
        assert len(error) <= r.ERROR_CHARS


def test_a_key_statement_across_the_cut_leaves_nothing_of_its_literal(_data):
    """A message past ``ERROR_CHARS`` whose key literal begins before the cut and ends after it. The literal
    starts 30 characters before the cut, so a cut made first keeps its opening (``'k3y-zzzz...``) without
    its closing quote, which the statement's pattern no longer matches."""
    rid = r.begin_run("f.zip", profile="full")
    literal = "'k3y-" + "z" * 60 + "'"
    lead, statement = "OperationalError: ", " PRAGMA key = "
    text = lead + "x" * (r.ERROR_CHARS - 30 - len(lead) - len(statement)) + statement + literal + " then more"
    assert text.index(literal) == r.ERROR_CHARS - 30 and text.index(literal) + len(literal) > r.ERROR_CHARS
    r.end_run(rid, outcome="failed", seconds=1.0, error=text)
    error = r.diagnostics_member()["runs"][0]["error"]
    assert "k3y-" not in error and "zzzz" not in error and len(error) <= r.ERROR_CHARS
    assert "PRAGMA key = '***redacted***'" in error


def test_a_marker_that_rebuilds_the_passphrase_withholds_the_text_instead_of_keeping_it(_data, monkeypatch):
    """The folders are named after the passphrase is taken out, so a held passphrase that IS the name a
    folder is given (``<data>``) is rebuilt by that step: the result is checked again and withheld."""
    _held(monkeypatch, "<data>")
    out = r.tidy_error(f"cannot open {_data}/diagnostics/x.zip")
    assert out == r.WITHHELD and "<data>" not in out


def test_a_text_that_cannot_be_made_free_of_the_passphrase_is_withheld_not_kept(_data, monkeypatch):
    from src.monitoring import secret_scrub

    monkeypatch.setenv("OO_DB_PASSPHRASE", "pa55-phrase")
    monkeypatch.setattr(secret_scrub, "_redacted", lambda text, forms: text)  # the scrub removes nothing
    assert r.tidy_error("context pa55-phrase") == r.WITHHELD, "the check reads the shapes again, not through the scrub"
    assert r.scrubbed_text("context pa55-phrase") is None


def test_a_text_is_withheld_when_what_the_process_holds_cannot_be_read(_data, monkeypatch):
    from src.monitoring import secret_scrub

    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: None)
    assert r.scrubbed_text("anything at all") is None
    assert r.tidy_error("anything at all") == r.WITHHELD
    with pytest.raises(RuntimeError):
        r.held_forms()


def test_a_text_the_recheck_cannot_read_the_shapes_for_is_withheld_though_the_scrub_ran(_data, monkeypatch):
    """The recheck reads the shapes ITSELF (``held_shapes``), so that it shares neither the scrub's matching nor its cache (it does
    share the list of shapes and the held passphrases, so it cannot catch a shape both leave out); when it cannot read them
    (a change of the session's passphrase between the two reads, or a read that failed the second time) the text is not kept
    on the strength of the first read alone."""
    from src.monitoring import secret_scrub

    _held(monkeypatch)
    assert r.scrubbed_text("nothing of the key here") == "nothing of the key here"
    monkeypatch.setattr(secret_scrub, "held_shapes", lambda: None)
    assert r.scrubbed_text("nothing of the key here") is None
    assert r.tidy_error("nothing of the key here") == r.WITHHELD


def test_a_secret_too_short_to_take_out_of_a_text_withholds_the_text_that_holds_it(_data, monkeypatch):
    """``secret_scrub``'s rule (``MIN_SECRET_CHARS``): taking one to three characters out of every text would leave no
    record that says anything, and keeping it would leave the key, so the text that holds it is withheld."""
    _held(monkeypatch, "abc")
    assert r.scrubbed_text("the abc drove") is None
    assert r.scrubbed_text("nothing of the key here") == "nothing of the key here"


def test_the_shapes_of_the_held_passphrase_come_longest_first_whatever_its_length_and_none_when_unreadable(_data, monkeypatch):
    """``held_shapes`` is what a reader of an OLDER writer's log needs (the tail of a shape a cut left at the start of a block): every
    shape, the short secrets' too (``scrubbed`` withholds those texts, it never hands their shapes out), the longest first so
    the longest tail is found first, and ``None`` -- never an empty tuple -- when what the process holds cannot be read."""
    from src.monitoring import secret_scrub
    from src.monitoring.secret_scrub import held_shapes

    _held(monkeypatch, "ab'c")
    shapes = held_shapes()
    assert shapes and shapes == tuple(sorted(set(shapes), key=lambda f: (-len(f), f)))
    assert "ab'c" in shapes and "ab''c" in shapes
    _held(monkeypatch, "abc")
    assert "abc" in held_shapes(), "a secret under the scrub's minimum still has its shapes for a reader that must withhold"
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: ())
    assert held_shapes() == ()
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: None)
    assert held_shapes() is None


def test_the_scrub_leaves_a_text_with_no_secret_as_it_was_apart_from_the_folders_and_whitespace(_data):
    assert r.tidy_error("ValueError:   bad\n  thing") == "ValueError: bad thing"
    assert r.scrubbed_text("line one\nline two", one_line=False) == "line one\nline two"
    assert r.scrubbed_text("a   b", one_line=True) == "a b"


def test_a_passphrase_that_holds_whitespace_is_taken_out_before_the_whitespace_is_collapsed(_data, monkeypatch):
    """A one-line field collapses runs of whitespace; done first, it would turn the passphrase ("two  spaces",
    a tab) into text no form of it matches."""
    _held(monkeypatch, "two  spaces\tand tab")
    out = r.tidy_error("failed on two  spaces\tand tab then")
    assert out != r.WITHHELD and "spaces" not in out and "and tab" not in out and out.endswith(" then")


@pytest.mark.parametrize("secret", ["line one\nline two", "ab\rcd", "ab\r\ncd", "vt\x0bnel\x85ls ps "])
def test_a_passphrase_with_a_line_break_is_found_in_text_a_windows_writer_wrote(_data, monkeypatch, secret):
    """A text-mode writer on Windows turns each LF into CR LF, so the passphrase "line one<LF>line two" is
    on disk as "line one<CR><LF>line two" (and a CR LF in it as CR CR LF). The read of such text says so
    (``file_text``) and the scrub finds the passphrase in both spellings."""
    _held(monkeypatch, secret)
    on_disk = secret.replace("\n", "\r\n")
    out = r.scrubbed_text("before " + on_disk + " after", file_text=True)
    assert out is not None and out != "before " + on_disk + " after"
    assert secret not in out and on_disk not in out and out.startswith("before ") and out.endswith(" after")


def test_the_start_of_a_text_cut_inside_the_passphrase_loses_what_the_cut_left_and_the_torn_line(_data, monkeypatch):
    """An older writer cut a block's text from the FRONT before it took the passphrase out, so the block can
    begin with the tail of a passphrase no scrub of the whole passphrase can see."""
    _held(monkeypatch)
    rest = "\nTraceback (most recent call last):\n  File \"a.py\", line 1, in f\nRuntimeError: x"
    for at in (1, 10, len(SECRET) - 1):  # the cut fell this far into the passphrase
        out = r.without_a_torn_start(SECRET[at:] + " and what else the torn line held" + rest)
        assert out is not None and "torn line held" not in out and out.startswith("Traceback"), (at, out)
    whole = "Traceback (most recent call last):\n  File \"a.py\", line 1, in f\nRuntimeError: x"
    assert r.without_a_torn_start(whole) == whole, "a text that begins whole is kept as it is"


def test_an_lf_passphrase_cut_before_its_lf_is_also_a_torn_start_even_in_a_windows_log(_data, monkeypatch):
    secret = "line one\nline two"
    _held(monkeypatch, secret)
    rest = "\nTraceback (most recent call last):\nRuntimeError: x"
    for text in (secret[8:] + " tail" + rest, secret[8:].replace("\n", "\r\n") + " tail" + rest.replace("\n", "\r\n")):
        out = r.without_a_torn_start(text)
        assert out is not None and "line two" not in out and out.lstrip("\r\n").startswith("Traceback"), repr(out)


def test_a_torn_start_that_cannot_be_checked_is_not_kept(_data, monkeypatch):
    from src.monitoring import secret_scrub

    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: None)
    assert r.without_a_torn_start("xyz\nTraceback (most recent call last):") is None


@pytest.mark.parametrize(
    "statement",
    [
        "cannot ATTACH '/x.db' AS e KEY 'k3y-secret' now",
        "cannot ATTACH '/my key dir/x.db' AS e KEY 'k3y-secret' now",  # a "key" inside the path is not the keyword
        "cannot ATTACH \"/x.db\" AS e KEY \"k3y-secret\" now",
        "cannot ATTACH 'it''s.db' AS e (ENCRYPTION_KEY 'k3y-secret') now",
        "near PRAGMA rekey = 'k3y-secret'",
        "near PRAGMA hexkey = 'k3y-secret'",
    ],
)
def test_a_key_statement_leaves_nothing_of_its_literal_whatever_precedes_the_key(_data, statement):
    out = r.tidy_error(statement)
    assert "k3y-secret" not in out and "'***redacted***'" in out, out


def test_the_rewrite_writes_lf_alone_whatever_the_platform(_data, monkeypatch):
    """Text mode writes each LF as CRLF on Windows, and the trim counts one byte a newline: the file
    would pass the ceiling it is trimmed to."""
    opened: list[object] = []
    real_replace = r.atomic_replace

    def spy(path, data, **kwargs):
        opened.append(kwargs.get("newline", "<the platform's>"))
        return real_replace(path, data, **kwargs)

    monkeypatch.setattr(r, "atomic_replace", spy)
    for i in range(r.KEEP_RUNS + 2):
        _run(i)
    assert opened and set(opened) == {"\n"}, opened
    assert b"\r" not in _file(_data).read_bytes()


def test_a_file_whose_read_end_holds_no_line_of_ours_is_still_rewritten_whole(_data):
    """Only the end of a file past ``READ_MAX_BYTES`` is read. When that end holds nothing the recorder
    wrote, the kept lines equal the lines read (none), and without the read's own word that the front
    was never read the file would only ever be appended to."""
    path = _file(_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    junk = b'{"not":"ours"}\n'
    path.write_bytes(junk * (r.READ_MAX_BYTES * 2 // len(junk)))
    rid = _run(1)
    assert path.stat().st_size <= r.MAX_FILE_BYTES
    assert [row["id"] for row in r.diagnostics_member()["runs"]] == [rid]


def test_a_text_that_would_hold_a_crlf_passphrase_once_read_as_a_files_text_is_withheld(_data, monkeypatch):
    """The result is checked in the file's own spelling as well: a passphrase that holds a CR LF, seen with
    its line end as a text-mode reader gives it (a bare LF), is not shown clean. A text that is not a file's
    is not judged by that spelling."""
    _held(monkeypatch, "cr-lf-one\r\ncr-lf-two")
    text = "x cr-lf-one\ncr-lf-two y"
    assert r.scrubbed_text(text, file_text=True) is None
    assert r.scrubbed_text(text) == text


def test_a_replacement_that_rebuilds_a_key_statement_withholds_the_text_instead_of_keeping_it(_data):
    """Naming the data folder ``<data>`` can bring ``ATTACH`` and ``KEY`` within reach of the statement's
    pattern (its span is at most 200 pieces long, and an unquoted path is a piece a character): the literal
    the pattern could not see before is now one it can, so the result is checked again and withheld."""
    text = f"cannot ATTACH {_data}/" + "d" * 170 + " AS e KEY 'k3y-secret' now"
    assert r._key_literals_out(text) == text, "the folder's own length keeps the statement out of the pattern's reach"
    assert r.tidy_error(text) == r.WITHHELD


def test_the_type_and_message_of_an_exception_are_one_line_even_when_its_text_cannot_be_rendered():
    class Broken(Exception):
        def __str__(self):
            raise RuntimeError("no text")

    assert r.exc_line(ValueError("bad thing")) == "ValueError: bad thing"
    assert r.exc_line(Broken()) == "Broken: its text is withheld"


def test_an_exception_is_written_by_the_one_exception_text_so_a_unicode_error_is_fixed_words(_data, monkeypatch):
    """``secret_scrub.exception_text``: a ``UnicodeError`` in the chain is the class and fixed words (its message names
    a character and its offset, which is a piece of a key), and the passphrase the process holds is out of the rest."""
    from src.monitoring.secret_scrub import UNICODE_WITHHELD

    _held(monkeypatch)
    bad = UnicodeEncodeError("ascii", "caf\u00e9", 3, 4, "ordinal not in range(128)")
    assert "xe9" in str(bad)
    line = r.exc_line(bad)
    assert UNICODE_WITHHELD in line and "xe9" not in line and "position" not in line
    assert "xe9" not in r.tidy_error(bad) and UNICODE_WITHHELD in r.tidy_error(bad)
    assert SECRET not in r.exc_line(RuntimeError(f"failed on {SECRET}"))
    rid = r.begin_run("f.zip", profile="full")
    r.end_run(rid, outcome="failed", seconds=1.0, error=r.exc_line(bad))
    assert "xe9" not in r.diagnostics_member()["runs"][0]["error"]


def test_an_error_that_cannot_be_rendered_is_named_and_the_run_still_ends(_data, monkeypatch):
    class Broken:
        def __str__(self):
            raise RuntimeError("no text")

    assert r.tidy_error(Broken()) == "<unrenderable>"
    rid = r.begin_run("f.zip", profile="full")
    monkeypatch.setattr(r, "tidy_error", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert r.end_run(rid, outcome="failed", seconds=1.0, error="anything") is True
    row = r.diagnostics_member()["runs"][0]
    assert row["state"] == "failed" and row["error"] == r.WITHHELD
    assert rid not in r._RUNNING


def test_a_file_past_what_is_read_is_read_from_its_end_says_so_and_is_rewritten_by_the_next_record(_data):
    path = _file(_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = (json.dumps({"k": "serve", "ev": "begin", "t": "2026-10-01T00:00:00Z", "sid": "x", "file": "old.zip", "bytes": 1}) + "\n")
    with open(path, "w", encoding="utf-8") as fp:
        while fp.tell() < r.READ_MAX_BYTES * 2:
            fp.write(old)
    rid = _run(1)
    # the front was never read, so the file now holds only what the kept counts allow, and it is whole lines
    assert path.stat().st_size <= r.MAX_FILE_BYTES
    assert all(isinstance(x, dict) for x in _lines(_data))
    assert [row["id"] for row in r.diagnostics_member()["runs"]] == [rid]
    # and a member read over a file that is still too big says what it read
    with open(path, "a", encoding="utf-8") as fp:
        while fp.tell() < r.READ_MAX_BYTES * 2:
            fp.write(old)
        fp.write(json.dumps({"k": "run", "ev": "begin", "t": "2026-10-06T00:00:00Z", "id": "feedface", "file": "n.zip", "profile": "full", "proc": "p"}) + "\n")
    doc = r.diagnostics_member()
    assert "file_read_from_its_end" in doc and str(r.READ_MAX_BYTES) in doc["file_read_from_its_end"]
    assert doc["runs"][0]["id"] == "feedface", "the newest line is the one that is read"


def test_the_bytes_read_never_pass_the_bound(_data):
    path = _file(_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not json\n" * (r.READ_MAX_BYTES // 5))
    raw, cut = r._read_tail(path)
    assert cut is True and len(raw) <= r.READ_MAX_BYTES and raw.startswith(b"not json\n")
    small = _file(_data).with_name("small.jsonl")
    small.write_bytes(b"x\n")
    assert r._read_tail(small) == (b"x\n", False)


def test_the_members_outcomes_are_counted_by_name():
    results = [{"outcome": "ok"}, {"outcome": "ok"}, {"outcome": "skipped-deadline"}, {"file": "x"}, "junk"]
    assert r.summarise_members(results) == {"ok": 2, "skipped-deadline": 1, "unknown": 1}
    assert r.summarise_members(None) == {} and r.summarise_members(5) == {}


def test_the_run_names_the_build_the_process_booted_with_not_a_fresh_read(_data, monkeypatch):
    """After a pull without a restart a fresh read would name code that is not the code running: the
    run takes the markers the process took at its boot."""
    from src.monitoring import build_marker as bm

    bm.reset_process_markers_for_tests()
    monkeypatch.setattr(bm, "code_markers", lambda root=None: {"git_head": "a" * 40, "migrations": {"fingerprint": "f1"}})
    first = r.begin_run("a.zip", profile="full")
    monkeypatch.setattr(bm, "code_markers", lambda root=None: {"git_head": "b" * 40, "migrations": {"fingerprint": "f2"}})
    second = r.begin_run("b.zip", profile="full")
    rows = {row["id"]: row for row in r.diagnostics_member()["runs"]}
    assert rows[first]["build"] == rows[second]["build"] == {"git_head": "a" * 40, "migrations": "f1"}
    bm.reset_process_markers_for_tests()


# --------------------------------------------------------------------------- #
#  The file: what stays, what it never passes, what it survives
# --------------------------------------------------------------------------- #
def test_only_the_last_ten_runs_stay_and_the_serves_before_the_oldest_of_them_go(_data):
    r.serve_end(r.serve_begin("before-everything.zip", 1))
    for i in range(14):
        _run(i)
        r.serve_end(r.serve_begin(f"set-{i}.zip", i))
    doc = r.diagnostics_member()
    assert [row["file"] for row in doc["runs"]] == [f"oo-all-diagnostics-{i:04d}.zip" for i in range(13, 3, -1)]
    files = [row["file"] for row in doc["serves"]]
    assert "before-everything.zip" not in files and "set-0.zip" not in files and "set-3.zip" not in files
    assert files[0] == "set-13.zip" and "set-4.zip" in files  # the serves of the kept runs stay


def test_the_serves_are_capped_when_a_run_begins(_data):
    for i in range(r.KEEP_SERVES + 15):
        r.serve_end(r.serve_begin(f"f{i}.zip", 1))
    r.begin_run("go.zip", profile="full")
    files = [row["file"] for row in r.diagnostics_member()["serves"]]
    assert len(files) == r.KEEP_SERVES
    assert files[0] == f"f{r.KEEP_SERVES + 14}.zip" and "f14.zip" not in files


def test_the_file_never_passes_its_byte_ceiling_whatever_is_appended(_data, monkeypatch):
    """Between two builds nothing trims by count, so an endless series of serves (a page that retries
    a download in a loop) is held by the byte ceiling at the append itself."""
    monkeypatch.setattr(r, "MAX_FILE_BYTES", 2_000)
    longest = 0
    for i in range(400):
        r.serve_end(r.serve_begin(f"a-file-with-a-rather-long-name-{i}.zip", i))
        longest = max(longest, _file(_data).stat().st_size)
    assert longest <= 2_000, longest
    assert r.diagnostics_member()["serves"][0]["file"] == "a-file-with-a-rather-long-name-399.zip"
    r.begin_run("go.zip", profile="full")
    assert _file(_data).stat().st_size <= 2_000
    assert _lines(_data)[-1]["k"] == "run"  # what goes is the oldest


def test_a_torn_line_costs_one_line_and_not_the_next_record(_data):
    """A kill in the middle of a write leaves a last line with no newline: the next record must start
    on a line of its own, or the two would read as one and the new record would be lost."""
    _run(1)
    with open(_file(_data), "a", encoding="utf-8") as fp:
        fp.write('{"k":"run","ev":"beg')  # no newline: what a kill leaves
    rid = r.begin_run("after.zip", profile="full")
    ids = [row["id"] for row in r.diagnostics_member()["runs"]]
    assert ids[0] == rid and len(ids) == 2
    r.end_run(rid, outcome="done", seconds=1.0)
    assert r.diagnostics_member()["runs"][0]["state"] == "done"


def test_foreign_lines_and_whole_lines_that_are_not_ours_cost_only_themselves(_data):
    _run(1)
    with open(_file(_data), "a", encoding="utf-8") as fp:
        fp.write('[1,2,3]\n{"k":"other","ev":"begin"}\nnot json\n\n')
        fp.write('{"k":"run","ev":"end","id":["odd"],"t":"x"}\n')       # an id that is not a string
        fp.write('{"k":"run","ev":"begin","id":"no-time"}\n')              # no time
        fp.write('{"k":"serve","ev":"begin","sid":5,"t":"x"}\n')           # a sid that is not a string
        fp.write('{"k":"run","ev":"begin","id":"x","t":"x","file":{"a":1}}\n')  # ours, with a stray value
        fp.write('{"k":["run"],"ev":"begin","id":"x","t":"x"}\n')  # a kind that is a list: not hashable
    rid = _run(2)  # the recorder still works: it was not turned off by any of them
    rows = r.diagnostics_member()["runs"]
    assert rows[0]["id"] == rid and rows[0]["state"] == "done"
    assert {row["id"] for row in rows} >= {rid}


def test_a_run_begun_many_times_over_never_leaves_an_end_without_its_begin(_data):
    first = r.begin_run("run-0.zip", profile="full")
    for i in range(1, r.KEEP_RUNS + 1):  # the first run's begin is trimmed away by the later ones
        r.begin_run(f"run-{i}.zip", profile="full")
    assert not any(x.get("id") == first for x in _lines(_data))
    r.end_run(first, outcome="done", seconds=1.0)  # a slow build that ended after ten newer began
    assert any(x["ev"] == "end" and x["id"] == first for x in _lines(_data))
    r.begin_run("run-next.zip", profile="full")
    assert not any(x.get("id") == first for x in _lines(_data))  # an end with no begin is not kept


def test_every_line_is_synced_to_disk_so_a_kill_cannot_take_the_begin_with_it(_data, monkeypatch):
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: synced.append(fd) or real(fd))
    rid = r.begin_run("a.zip", profile="full")
    assert len(synced) == 1  # the begin line is on disk before the build does anything else
    r.end_run(rid, outcome="done", seconds=1.0)
    assert len(synced) == 2


def test_the_rewrite_is_synced_aside_before_it_replaces_the_file_and_the_folder_after(_data, monkeypatch):
    """A power cut between the rename and the data reaching the disk would leave the old name pointing
    at an empty file: the temporary file is synced before the move, and the folder after it."""
    for i in range(r.KEEP_RUNS + 2):
        _run(i)
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: order.append("fsync") or real_fsync(fd))
    monkeypatch.setattr(os, "replace", lambda a, b: order.append("replace") or real_replace(a, b))
    r.begin_run("go.zip", profile="full")
    # the file synced, the move, the folder synced, then the one appended line synced
    assert order == ["fsync", "replace", "fsync", "fsync"], order


# --------------------------------------------------------------------------- #
#  Serves
# --------------------------------------------------------------------------- #
def test_a_transfer_begins_now_and_ends_when_the_response_is_over(_data):
    sid = r.serve_begin("set.zip", 1234)
    mid = r.diagnostics_member()["serves"][0]
    assert mid["file"] == "set.zip" and mid["bytes"] == 1234
    assert mid["sent_all"] is None and mid["note"] == "being sent now"
    r.serve_end(sid)
    done = r.diagnostics_member()["serves"][0]
    assert done["sent_all"] is True and "note" not in done and done["seconds"] is not None and done["how"] == "complete"


@pytest.mark.parametrize(
    ("how", "sent_all", "word"),
    [
        (r.HOW_RANGE, None, "not a whole download"),
        (r.HOW_ABANDONED, False, "disconnected"),
        (r.HOW_ERROR, False, "raised"),
        (r.HOW_HEAD, None, "no file was sent"),
        (r.HOW_REFUSED, None, "refusal"),
    ],
)
def test_each_way_a_response_can_end_reads_as_what_it_was(_data, how, sent_all, word):
    r.serve_end(r.serve_begin("set.zip", 99), how, 206)
    row = r.diagnostics_member()["serves"][0]
    assert row["how"] == how and row["sent_all"] is sent_all and word in row["note"] and row["status"] == 206


def test_a_transfer_whose_end_was_never_written_and_is_not_in_flight_reads_as_cut_off(_data):
    """What a restart leaves: a begin whose process is gone."""
    _file(_data).parent.mkdir(parents=True, exist_ok=True)
    with open(_file(_data), "a", encoding="utf-8") as fp:
        fp.write(json.dumps({"k": "serve", "ev": "begin", "t": "2026-10-05T01:02:03Z", "sid": "ab12cd34",
                             "file": "set.zip", "bytes": 99}) + "\n")
    row = r.diagnostics_member()["serves"][0]
    assert row["sent_all"] is False and "ended while the file was being sent" in row["note"]


def test_an_end_line_that_does_not_say_how_is_not_read_as_a_success(_data):
    sid = r.serve_begin("set.zip", 1)
    with open(_file(_data), "a", encoding="utf-8") as fp:
        fp.write(json.dumps({"k": "serve", "ev": "end", "t": "2026-10-05T01:02:03Z", "sid": sid, "how": "teleported"}) + "\n")
    row = r.diagnostics_member()["serves"][0]
    assert row["how"] is None and row["sent_all"] is None and "does not say" in row["note"]


def test_a_seconds_figure_is_two_monotonic_readings_not_two_wall_stamps(_data, monkeypatch):
    ticks = iter([100.0, 103.5])
    monkeypatch.setattr(r.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(r, "_now_iso", lambda: "2026-10-05T00:00:00Z")  # the same stamp twice: a wall difference reads 0
    r.serve_end(r.serve_begin("set.zip", 1))
    assert r.diagnostics_member()["serves"][0]["seconds"] == 3.5


# --------------------------------------------------------------------------- #
#  The response, driven the way a server drives it
# --------------------------------------------------------------------------- #
def _drive(path, *, method="GET", headers=(), disconnect_after_chunks=None, send_raises=None, filename="x.zip"):
    """Run ``served_file_response`` through the ASGI interface with a fake server and return what it
    sent. ``disconnect_after_chunks``: the page leaves after that many body messages, and the fake
    server's ``send`` then returns without sending, as uvicorn's does."""
    resp = r.served_file_response(path, filename)
    sent: list[dict] = []
    release = anyio.Event()
    state = {"bodies": 0}

    async def receive():
        await release.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if send_raises is not None and message["type"] == "http.response.body":
            raise send_raises
        if release.is_set():
            return  # the server's send after a disconnect: it returns, it neither sends nor raises
        sent.append(message)
        if message["type"] == "http.response.body":
            state["bodies"] += 1
            if disconnect_after_chunks is not None and state["bodies"] >= disconnect_after_chunks:
                release.set()
                await anyio.sleep(0.05)  # let the response's listener see it

    scope = {
        "type": "http", "method": method, "path": "/f", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers], "extensions": {},
    }
    anyio.run(resp, scope, receive, send)
    return sent


@pytest.fixture
def archive(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"PK" + b"0" * 300_000)  # five 64 KiB chunks
    return p


def _the_serve():
    (row,) = r.diagnostics_member()["serves"]
    return row


def test_a_download_the_page_stayed_for_is_complete(archive):
    sent = _drive(archive)
    assert sent[0]["status"] == 200 and not sent[-1].get("more_body", False)
    row = _the_serve()
    assert row["how"] == "complete" and row["sent_all"] is True and row["status"] == 200


def test_a_download_the_page_walked_away_from_is_abandoned_not_complete(archive):
    """uvicorn's send returns without sending once the page has gone, so the file was read to the end
    and the last body message was 'handed over'. That is not a download."""
    _drive(archive, disconnect_after_chunks=1)
    row = _the_serve()
    assert row["how"] == "abandoned" and row["sent_all"] is False


def test_a_range_of_a_hundred_bytes_is_a_part_not_the_file(archive):
    sent = _drive(archive, headers=[("range", "bytes=0-99")])
    assert sent[0]["status"] == 206
    row = _the_serve()
    assert row["how"] == "range" and row["sent_all"] is None and row["status"] == 206


def test_a_range_the_file_cannot_satisfy_is_a_refusal_not_an_error(archive):
    _drive(archive, headers=[("range", "bytes=999999999-")])
    row = _the_serve()
    assert row["how"] == "refused" and row["status"] == 416 and row["sent_all"] is None


def test_a_head_request_is_not_a_transfer(archive):
    _drive(archive, method="HEAD")
    row = _the_serve()
    assert row["how"] == "head" and row["sent_all"] is None


def test_an_error_while_sending_ends_the_record_and_reaches_the_server_as_itself(archive):
    """The exception goes on as it was raised (not wrapped in the task group's group), and the
    transfer is not left reading 'being sent now' for the rest of the process's life."""
    with pytest.raises(OSError, match="broken pipe"):
        _drive(archive, send_raises=OSError("broken pipe"))
    row = _the_serve()
    assert row["how"] == "error" and row["sent_all"] is False and row["note"] != "being sent now"
    assert not r._ACTIVE


def test_a_server_that_hands_a_file_over_by_path_is_not_an_abandoned_download(archive):
    """``http.response.pathsend`` is the last message of such a response: no body message follows."""
    resp = r.served_file_response(archive, "x.zip")
    sent: list[dict] = []

    async def receive():
        await anyio.sleep_forever()

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/f", "query_string": b"", "headers": [],
             "extensions": {"http.response.pathsend": {}}}
    anyio.run(resp, scope, receive, send)
    assert any(m["type"] == "http.response.pathsend" for m in sent)
    assert _the_serve()["how"] == "complete"


def test_a_served_file_response_records_its_own_sending_through_the_test_client(_data, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    archive = tmp_path / "x.zip"
    archive.write_bytes(b"PK" + b"0" * 5000)
    app = FastAPI()

    @app.get("/f")
    def _f():
        return r.served_file_response(archive, "x.zip")

    body = TestClient(app).get("/f")
    assert body.status_code == 200 and len(body.content) == 5002
    assert body.headers["content-disposition"].endswith('filename="x.zip"')
    row = _the_serve()
    assert row["file"] == "x.zip" and row["bytes"] == 5002 and row["sent_all"] is True


def test_a_response_whose_record_could_not_be_started_is_still_a_file_response(_data, tmp_path):
    (_data / "diagnostics").write_text("blocked", encoding="utf-8")
    archive = tmp_path / "y.zip"
    archive.write_bytes(b"PK")
    resp = r.served_file_response(archive, "y.zip")
    assert resp.status_code == 200 and resp.background is None


# --------------------------------------------------------------------------- #
#  The member
# --------------------------------------------------------------------------- #
def test_the_member_is_held_to_its_budget_the_oldest_rows_go_first_and_the_cut_is_named(_data):
    for i in range(12):
        _run(i)
        for j in range(4):
            r.serve_end(r.serve_begin(f"set-{i}-part-{j}.zip", 1000))
    full = r.diagnostics_member()
    assert "cut" not in full and len(full["runs"]) == 10
    small = r.diagnostics_member(max_bytes=3_000)
    assert len(json.dumps(small, separators=(",", ":"))) <= 3_000
    assert small["cut"]["serves"] > 0 and "held to 3000 bytes" in small["cut"]["why"]
    assert small["serves"][0]["file"] == full["serves"][0]["file"]  # the newest serve is the one kept
    assert small["runs"][0]["id"] == full["runs"][0]["id"]
    tiny = r.diagnostics_member(max_bytes=10)
    assert len(tiny["runs"]) == 1 and tiny["serves"] == []  # never an empty answer about the newest run
    assert "could not be held to 10 bytes" in tiny["cut"]["why"] and tiny["over_budget_bytes"] > 10
    assert "over_budget_bytes" not in small and "over_budget_bytes" not in full


def test_the_budget_is_met_by_measuring_each_row_once_not_the_document_per_row_dropped(monkeypatch):
    """Quadratic once: each dropped row re-encoded the whole document (4 s at 3,000 serves). Counting
    CALLS cannot tell the two apart (one call per dropped row is as many calls as rows); what does is
    the bytes encoded: each row once, the fixed part once and the final check, a few times the document,
    where a re-encode per dropped row is hundreds of times it."""
    runs = [{"id": f"r{i}", "file": "x.zip", "state": "done", "started_at": "2026-10-06T00:00:00Z"} for i in range(5)]
    serves = [
        {"file": f"set-{i}.zip", "bytes": 1000, "started_at": "2026-10-06T00:00:00Z", "how": "complete", "sent_all": True}
        for i in range(800)
    ]
    doc = {"schema": r.SCHEMA, "available": True, "runs": runs, "serves": serves}
    real = r._encoded
    whole = real(doc)
    encoded = {"bytes": 0}

    def counting(d):
        n = real(d)
        encoded["bytes"] += n
        return n

    monkeypatch.setattr(r, "_encoded", counting)
    out = r._fit(doc, max_bytes=whole // 10)
    monkeypatch.setattr(r, "_encoded", real)
    assert real(out) <= whole // 10 and out["cut"]["serves"] > 600
    assert encoded["bytes"] <= 3 * whole, (encoded, whole)


def test_the_member_names_no_path_and_says_what_it_cannot_know(_data):
    _run(1)
    r.serve_end(r.serve_begin("x.zip", 1))
    doc = r.diagnostics_member()
    assert str(_data) not in json.dumps(doc)
    assert "not observable" in doc["caveat"] and doc["schema"] == r.SCHEMA
    for covered in ("background build's download", "numbered volumes", "numbered keyword files"):
        assert covered in doc["method"], covered
    for uncovered in ("synchronous /all route", "keyword log's scratch zip", "source-quality zip"):
        assert uncovered in doc["method"], uncovered


def test_a_record_that_cannot_be_written_never_raises(_data, tmp_path):
    (_data / "diagnostics").write_text("a file where the folder should be", encoding="utf-8")
    rid = r.begin_run("a.zip", profile="full")
    assert isinstance(rid, str)  # the id is returned: the end is still attempted
    assert r.end_run(rid, outcome="done", seconds=1.0) is False
    assert r.end_run(None, outcome="done", seconds=1.0) is False
    assert r.serve_begin("a.zip", 1) is None
    r.serve_end(None)
    doc = r.diagnostics_member()
    assert doc["available"] is True and doc["runs"] == [] and doc["serves"] == []


def test_a_trim_by_one_process_never_loses_a_record_another_process_appends(_data):
    """R176: the size check, the trim and the append are one section under the file's lock, so a second server's record cannot fall between a trim's read and its swap."""
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    root = str(Path(r.__file__).parents[2])
    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {root!r})
        os.environ["OO_DATA_DIR"] = {str(_data)!r}
        from src.monitoring import diagnostics_runs as r
        for i in range(120):
            r._append({{"k": "probe", "n": i}})
        """
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    while child.poll() is None:
        r._append({"k": "probe", "n": -1}, trim_runs=0)
    child.wait()
    got = [json.loads(ln)["n"] for ln in _file(_data).read_text().splitlines() if '"probe"' in ln and '"n":-1' not in ln]
    assert got == list(range(120 - len(got), 120)), "a record written by the other process was lost by a trim"
    assert got
