"""What the crash trace's report keeps, whose it is, and what it must not carry (the read of 2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The earlier unclean ends and the previous session's trace come from ``crash_trace.log``, which
faulthandler writes from inside a dying process. Each test below pins one way the report could
mislead or leak:

  * the cut to the first lines must not drop the thread that crashed (faulthandler writes it LAST);
  * a pid is not a session: two sessions of one pid, with the machine's boot unknown, each get
    their own header, and the previous session is told apart from an older one of its pid by the
    moment it began;
  * a session that ended with an error STATUS is not "no exit recorded";
  * the report names no folder of the person, in the frames or in the source, and no line runs on;
  * the exception that ends the server is written without the database passphrase, and an OLDER log
    that holds it (written before that was true) is read without it, whatever the cut falls on.
"""

from __future__ import annotations

import json

import pytest

from src.monitoring import build_marker as bm
from src.monitoring import exit_evidence as ee
from src.monitoring import forensics, session_hwm
from src.monitoring import session_history as sh

BOOT = "11111111-aaaa-bbbb-cccc-000000000001"


@pytest.fixture
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    bm.reset_process_markers_for_tests()
    (tmp_path / "data" / "diagnostics").mkdir(parents=True)
    yield tmp_path / "data"
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    bm.reset_process_markers_for_tests()


def _log(dd, text: str, name: str = "crash_trace.log") -> None:
    (dd / "diagnostics" / name).write_text(text, encoding="utf-8")


def _header(pid: int, at: str, boot: str = "-") -> str:
    return f"=== open-omniscience session pid={pid} boot={boot} started={at} ==="


def _end(sid: str, at: str, **exit_) -> dict:
    rec = {"kind": "end", "session_id": sid, "at": at, "clean": False}
    if exit_:
        rec["exit"] = exit_
    return rec


def _boot(sid: str, at: str, pid: int, boot: str | None = None) -> dict:
    return {"kind": "boot", "session_id": sid, "at": at, "pid": pid, "machine_boot_id": boot}


# --------------------------------------------------------------------------- #
#  the crashing thread survives the cut
# --------------------------------------------------------------------------- #
def _many_threads(n_idle: int) -> list[str]:
    body = ["Fatal Python error: Segmentation fault", ""]
    for i in range(n_idle):
        body += [f"Thread 0x{i:016x} (most recent call first):"]
        body += [f'  File "/usr/lib/python3.13/threading.py", line {j} in idle{i}' for j in range(5)]
        body += [""]
    body += ["Current thread 0x00007fd48ce3c080 (most recent call first):",
             '  File "/usr/lib/python3.13/ctypes/__init__.py", line 546 in string_at',
             '  File "/app/src/where_it_crashed.py", line 6 in <module>']
    return body


def test_the_thread_that_crashed_is_kept_when_forty_idle_threads_come_first():
    body = _many_threads(40)
    assert len(body) > 200
    report = ee._trace_report(body, ee.Path("/home/alice/data/diagnostics/crash_trace.log"), 60)
    lines = report["lines"]
    assert len(lines) == 60 and report["lines_total"] == len(body)
    assert lines[0] == "Fatal Python error: Segmentation fault", "the fatal error stays first"
    current = [i for i, ln in enumerate(lines) if ln.startswith("Current thread")]
    assert current and current[0] < 5, "the crashing thread follows the error, ahead of every idle one"
    assert any("string_at" in ln for ln in lines) and any("in <module>" in ln for ln in lines)
    assert not any(ln.startswith("Thread 0x") and i < current[0] for i, ln in enumerate(lines))


def test_the_other_threads_follow_in_their_own_order_and_nothing_is_lost_when_it_all_fits():
    body = _many_threads(3)
    ordered = ee._crashing_thread_first(body)
    assert sorted(ordered) == sorted(body) and len(ordered) == len(body)
    heads = [ln for ln in ordered if ln.startswith(("Thread 0x", "Current thread"))]
    assert heads[0].startswith("Current thread")
    assert heads[1:] == [f"Thread 0x{i:016x} (most recent call first):" for i in range(3)]


def test_a_trace_with_no_thread_blocks_or_with_the_crashing_thread_first_is_left_as_it_is():
    plain = ["Uncaught exception ended the server at 2026-10-06T10:00:00+00:00:", "Traceback ...", "ValueError: x"]
    assert ee._crashing_thread_first(plain) == plain
    first = ["Fatal Python error: Aborted", "", "Current thread 0x1 (most recent call first):", "  File ...", "",
             "Thread 0x2 (most recent call first):", "  File ..."]
    assert ee._crashing_thread_first(first) == first


def test_the_summary_is_the_fatal_error_line_even_when_it_is_not_the_first_line():
    body = ["", "some preface", "Fatal Python error: Aborted", "", "Thread 0x1 (most recent call first):"]
    assert ee._trace_report(body[1:], ee.Path("x"), 10)["summary"] == "Fatal Python error: Aborted"


# --------------------------------------------------------------------------- #
#  a pid is not a session
# --------------------------------------------------------------------------- #
def _two_sessions_of_one_pid(dd):
    """Pid 500 twice, the machine's boot unknown (a platform with no boot id): the same pid at 02:00
    and again at 14:00, each with its own crash."""
    recs = [
        _boot("early", "2026-09-30T02:00:00Z", 500), _end("early", "2026-09-30T02:30:00Z", signal="SIGABRT"),
        _boot("late", "2026-09-30T14:00:00Z", 500), _end("late", "2026-09-30T14:30:00Z", signal="SIGABRT"),
    ]
    _log(dd, (
        "\n" + _header(500, "2026-09-30T01:59:40+00:00") + "\nFatal Python error: Aborted\n\nThread 0x1:\n  File \"a.py\", line 1 in early_stack\n"
        + "\n" + _header(500, "2026-09-30T13:59:40+00:00") + "\nFatal Python error: Aborted\n\nThread 0x1:\n  File \"a.py\", line 1 in late_stack\n"
    ))
    return recs


def test_two_sessions_of_one_pid_each_get_their_own_trace_where_the_boot_is_unknown(dd):
    out = ee.earlier_unclean_ends(None, records=_two_sessions_of_one_pid(dd))
    by_start = {row["started_at"]: row for row in out["sessions"]}
    assert "early_stack" in "".join(by_start["2026-09-30T02:00:00Z"]["trace"]["lines"])
    assert "late_stack" in "".join(by_start["2026-09-30T14:00:00Z"]["trace"]["lines"])
    assert "late_stack" not in "".join(by_start["2026-09-30T02:00:00Z"]["trace"]["lines"]), (
        "the newest header of the pid is not every session's"
    )


def test_a_session_whose_own_header_is_missing_does_not_take_another_sessions_of_its_pid(dd):
    recs = [_boot("early", "2026-09-30T02:00:00Z", 500), _end("early", "2026-09-30T02:30:00Z", signal="SIGABRT")]
    _log(dd, "\n" + _header(500, "2026-09-30T13:59:40+00:00") + "\nFatal Python error: Aborted\n")  # the later session's
    row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
    assert row["trace"] is None and "no header for this pid and boot" in row["why_no_trace"]


def test_the_header_may_lie_before_the_boot_record_by_the_start_up_and_a_second_after_it(dd):
    recs = [_boot("s", "2026-09-30T10:00:00Z", 77), _end("s", "2026-09-30T10:30:00Z", signal="SIGABRT")]
    for armed, expect in (
        ("2026-09-30T09:45:00+00:00", True),     # a start-up that took quarter of an hour
        ("2026-09-30T10:00:03+00:00", True),     # clocks read at one-second resolution
        ("2026-09-30T10:00:30+00:00", False),    # AFTER the boot record: another session's
        ("2026-09-30T08:00:00+00:00", False),    # far before it: another session's
    ):
        _log(dd, "\n" + _header(77, armed) + "\nFatal Python error: Aborted\n")
        row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
        assert (row["trace"] is not None) is expect, armed


def test_a_header_or_a_boot_with_no_readable_time_falls_back_to_the_pid_and_the_boot(dd):
    recs = [_boot("s", "not a time", 77), _end("s", "2026-09-30T10:30:00Z", signal="SIGABRT")]
    _log(dd, "\n" + _header(77, "2026-09-30T10:00:00+00:00") + "\nFatal Python error: Aborted\n")
    assert ee.earlier_unclean_ends(None, records=recs)["sessions"][0]["trace"] is not None
    assert ee._when("garbage") is None and ee._when(None) is None and ee._when(5) is None
    assert ee._when("2026-09-30T10:00:00Z") == ee._when("2026-09-30T10:00:00+00:00")


def test_the_previous_session_trace_is_found_by_its_start_not_by_the_newest_header_of_its_pid(dd):
    _log(dd, (
        "\n" + _header(500, "2026-09-30T01:59:40+00:00") + "\nFatal Python error: Aborted\n\nThread 0x1:\n  File \"a.py\", line 1 in early_stack\n"
        + "\n" + _header(500, "2026-09-30T13:59:40+00:00") + "\nFatal Python error: Aborted\n\nThread 0x1:\n  File \"a.py\", line 1 in late_stack\n"
    ))
    early = ee.previous_trace(500, None, "2026-09-30T02:00:00Z")
    assert early is not None and "early_stack" in "".join(early["lines"])
    assert "late_stack" in "".join(ee.previous_trace(500, None, "2026-09-30T14:00:00Z")["lines"])
    assert "late_stack" in "".join(ee.previous_trace(500)["lines"]), "no start known: the old rule, the newest header"


def test_the_previous_session_is_told_from_an_older_one_of_its_pid_by_when_it_began(dd):
    """With the boot unknown the pid alone excluded BOTH sessions of pid 500 from the earlier ends:
    the older one's crash was listed nowhere."""
    recs = _two_sessions_of_one_pid(dd)
    prev = {"pid": 500, "started_at": "2026-09-30T14:00:00Z"}
    out = ee.earlier_unclean_ends(prev, records=recs)
    assert [row["started_at"] for row in out["sessions"]] == ["2026-09-30T02:00:00Z"]
    no_start = ee.earlier_unclean_ends({"pid": 500}, records=recs)
    assert no_start["sessions"] == [], "nothing to tell them apart by: the pid rule, as before"


def test_a_boot_of_another_machine_boot_is_not_the_previous_session_even_with_its_pid_and_time(dd):
    recs = [_boot("s", "2026-09-30T14:00:00Z", 500, boot="other"), _end("s", "2026-09-30T14:30:00Z", signal="SIGKILL")]
    prev = {"pid": 500, "boot_id": BOOT, "started_at": "2026-09-30T14:00:00Z"}
    assert len(ee.earlier_unclean_ends(prev, records=recs)["sessions"]) == 1


# --------------------------------------------------------------------------- #
#  what the launcher saw
# --------------------------------------------------------------------------- #
def test_a_session_that_exited_with_an_error_status_is_worded_as_that_not_as_no_exit(dd):
    recs = [_boot("s", "2026-09-30T10:00:00Z", 9), _end("s", "2026-09-30T10:30:00Z", status=1, signal=None, kind="exited")]
    _log(dd, "")
    row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
    assert "launcher saw it exit with status 1" in row["why_no_trace"]
    assert "recorded no exit" not in row["why_no_trace"]
    assert row["status"] == 1 and row["kind"] == "exited" and row["signal"] is None
    text = "\n".join(forensics._render_earlier_ends(ee.earlier_unclean_ends(None, records=recs)))
    assert "exit status 1" in text and "no signal recorded" not in text


def test_a_session_the_launcher_never_saw_says_so_and_a_signal_keeps_its_wording(dd):
    assert "the launcher recorded no exit for this session" in ee._why_no_trace(None, False)
    assert "header with nothing under it" in ee._why_no_trace(None, True)
    assert "the launcher recorded no exit" in ee._why_no_trace({}, False)
    assert "leaves no trace" in ee._why_no_trace({"signal": "SIGKILL"}, True)
    assert "not a fault signal" in ee._why_no_trace({"signal": "SIGTERM", "status": 143}, False)


# --------------------------------------------------------------------------- #
#  what the report carries
# --------------------------------------------------------------------------- #
def test_a_frame_names_the_app_its_package_or_a_bare_file_never_the_persons_folder():
    home = "/home/alice"
    body = [
        "Fatal Python error: Aborted", "", "Current thread 0x1 (most recent call first):",
        f'  File "{session_hwm._APP_SRC}/api/x.py", line 5 in handler',
        f'  File "{home}/.venv/lib/python3.13/site-packages/uvicorn/server.py", line 9 in run',
        f'  File "{home}/projects/private-case/notes.py", line 3 in <module>',
        f"ValueError: cannot open {ee.Path.home()}/oo/data.db",
    ]
    report = ee._trace_report(body, ee.Path(f"{home}/oo/data/diagnostics/crash_trace.log"), 60)
    text = "\n".join(report["lines"])
    assert 'File "src/api/x.py"' in text and 'File "uvicorn/server.py"' in text and 'File "notes.py"' in text
    assert "private-case" not in text and "alice" not in text.replace("<home>", "")
    assert "<home>/oo/data.db" in text
    assert report["source"] == "crash_trace.log"


def test_no_line_of_a_trace_runs_on(dd):
    body = ["Fatal Python error: Aborted", "", "Current thread 0x1:", "RuntimeError: " + "x" * 5000]
    report = ee._trace_report(body, ee.Path("c.log"), 60)
    assert all(len(ln) <= ee._TRACE_LINE_CHARS for ln in report["lines"])
    assert report["lines"][-1].endswith("…") and len(report["lines"][-1]) == ee._TRACE_LINE_CHARS
    assert len(report["summary"]) <= ee._TRACE_LINE_CHARS
    # ASCII lines a character or two past the cut are within the byte bound and are cut by the character one
    for n in (201, 202):
        out = ee._trace_line("y" * n)
        assert len(out) == ee._TRACE_LINE_CHARS and out.endswith("…"), n
    assert ee._trace_line("y" * ee._TRACE_LINE_CHARS) == "y" * ee._TRACE_LINE_CHARS


@pytest.mark.parametrize("letter", ["y", "\u00e9", "\u6f22", "\U0001d518"], ids=["ascii", "accented", "cjk", "astral"])
def test_the_member_of_a_crash_loop_with_long_lines_stays_small_in_any_script(dd, letter):
    """Ten earlier ends of lines of a thousand characters each would be about 1.2 MB. Cut at
    ``_TRACE_LINE_CHARS`` characters AND ``_TRACE_LINE_BYTES`` bytes the worst case is 10 x 60 x 202 =
    121,200 bytes, about 125 KB as the member is WRITTEN (UTF-8, not escaped): at 200 characters alone
    the same ends measured 233 KB in accented text, 346 KB in CJK and 458 KB in astral characters.
    The newest end keeps 400 lines and the others 120, so the worst case is (400 + 9 x 120) x 202 = about 300 KB; 400,000 is the pin (it was 150,000 at 60 lines each)."""
    recs, text = [], ""
    for n in range(1, 40):
        pid = 100 + n
        recs += [_boot(f"s{n}", f"2026-09-30T{n % 24:02d}:00:00Z", pid), _end(f"s{n}", f"2026-09-30T{n % 24:02d}:30:00Z", signal="SIGABRT")]
        text += "\n" + _header(pid, f"2026-09-30T{(n % 24) - 1 if n % 24 else 0:02d}:59:40+00:00") + "\n"
        text += "Fatal Python error: Aborted\n\nCurrent thread 0x1:\n" + "\n".join("  " + letter * 1000 for _ in range(100)) + "\n"
    _log(dd, text)
    out = ee.earlier_unclean_ends(None, records=recs)
    written = json.dumps(out, ensure_ascii=False).encode("utf-8")
    assert out["shown"] == 10 and len(written) < 400_000, len(written)
    lines = [ln for row in out["sessions"] if row.get("trace") for ln in row["trace"]["lines"]]
    assert lines and all(len(ln) <= ee._TRACE_LINE_CHARS and len(ln.encode("utf-8")) <= ee._TRACE_LINE_BYTES for ln in lines)
    assert all(len(row["trace"]["summary"].encode("utf-8")) <= ee._TRACE_LINE_BYTES for row in out["sessions"] if row.get("trace"))


# --------------------------------------------------------------------------- #
#  the exception that ends the server
# --------------------------------------------------------------------------- #
SECRET = "correct horse's battery"


def test_the_exception_that_ends_the_server_is_written_without_the_passphrase(dd, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    try:
        # the passphrase in the engine's words; a key DERIVED from it (DuckDB's), which no form of the
        # passphrase names; and the data folder of the person
        raise RuntimeError(
            f"near \"x\": syntax error [SQL: PRAGMA key = '{SECRET.replace(chr(39), chr(39) * 2)}'] {SECRET!r} "
            f"ATTACH 'x.db' AS d (ENCRYPTION_KEY 'derived-0123-key') in {dd}/diagnostics/x"
        )
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
    written = (dd / "diagnostics" / "crash_trace.log").read_text(encoding="utf-8")
    assert "Uncaught exception ended the server" in written and "RuntimeError" in written
    for leaked in ("correct horse", "battery", "derived-0123-key", str(dd)):
        assert leaked not in written, leaked
    assert "<data>/diagnostics/x" in written


def test_an_exception_whose_text_cannot_be_checked_for_the_passphrase_is_withheld(dd, monkeypatch):
    from src.monitoring import secret_scrub

    monkeypatch.setenv("OO_DB_PASSPHRASE", "pa55-phrase")
    monkeypatch.setattr(secret_scrub, "_redacted", lambda text, forms: text)  # the scrub removes nothing
    try:
        raise RuntimeError("context pa55-phrase")
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
    written = (dd / "diagnostics" / "crash_trace.log").read_text(encoding="utf-8")
    assert "pa55-phrase" not in written and "text withheld" in written


def test_the_exception_is_cut_after_the_passphrase_is_taken_out_not_before(dd, monkeypatch):
    """A cut first could keep the tail of the passphrase (the window of 8,000 characters begins inside
    it), which a scrub of the cut text can no longer see. The window is made to begin ``inside``
    characters into the passphrase, at every depth: the text is the traceback's own lines, the message
    and a newline, so the message's tail is sized to put the window's first character there."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    log = dd / "diagnostics" / "crash_trace.log"
    for inside in range(1, len(SECRET) - 4):
        log.unlink(missing_ok=True)
        try:
            raise RuntimeError(SECRET + "q" * (7999 - len(SECRET) + inside))
        except RuntimeError as exc:
            ee.note_fatal_exception(exc)
        written = log.read_text(encoding="utf-8")
        assert SECRET[inside:] not in written and SECRET not in written, inside
        assert "qqqq" in written, "the text itself was written, cut to its end"


def test_a_key_statement_across_the_cut_of_the_exception_that_ends_the_server_leaves_nothing_of_its_literal(dd):
    """The window of 8,000 characters is made to begin a few characters INTO the literal of a key statement: a cut made before the
    scrub leaves ``3y-zzzz-abcd'`` with no statement in front of it, which no pattern recognises (the passphrase is out of the
    traceback already; the literal is the record's own pass)."""
    from src.monitoring.secret_scrub import traceback_text

    def raised(pad: int) -> RuntimeError:
        try:
            raise RuntimeError("PRAGMA key = 'k3y-zzzz-abcd' " + "p" * pad)
        except RuntimeError as exc:
            return exc

    full = traceback_text(raised(0))
    after = len(full) - full.index("'k3y-")
    exc = raised(ee._FATAL_TEXT_CHARS - 6 - after)  # the window starts at the 6th character of the quoted literal
    assert len(traceback_text(exc)) - traceback_text(exc).index("'k3y-") == ee._FATAL_TEXT_CHARS - 6
    ee.note_fatal_exception(exc)
    written = (dd / "diagnostics" / "crash_trace.log").read_text(encoding="utf-8")
    assert "zzzz" not in written and "abcd" not in written and "k3y-" not in written
    assert "pppp" in written, "the text itself was written, cut to its end"


def test_a_unicode_error_that_ends_the_server_is_written_as_fixed_words(dd):
    from src.monitoring.secret_scrub import UNICODE_WITHHELD

    try:
        raise UnicodeEncodeError("ascii", "caf\u00e9", 3, 4, "ordinal not in range(128)")
    except UnicodeError as exc:
        ee.note_fatal_exception(exc)
    written = (dd / "diagnostics" / "crash_trace.log").read_text(encoding="utf-8")
    assert UNICODE_WITHHELD in written and "UnicodeEncodeError" in written
    assert "xe9" not in written and "position" not in written, "a character and its offset are a piece of a key"


def _written_then_read(dd, exc: BaseException) -> dict:
    """The report ``previous_trace`` makes from a log THIS code wrote: a session's header, then ``note_fatal_exception``'s block."""
    _log(dd, "\n" + _header(900, "2026-09-30T01:00:00+00:00") + "\n")
    ee.note_fatal_exception(exc)
    report = ee.previous_trace(900, None, "2026-09-30T01:00:00Z")
    assert report is not None and not report.get("withheld"), report
    return report


def test_the_report_of_a_unicode_error_that_ended_the_server_keeps_the_line_that_says_what_happened(dd, monkeypatch):
    """The block ``note_fatal_exception`` writes for a ``UnicodeError`` begins with its class and fixed words, not with
    "Traceback (most recent call last):": a reader that took it for a torn start dropped that line, the one thing the block says,
    even with no passphrase held (the fail-safe is for an OLDER writer's log)."""
    from src.monitoring.secret_scrub import UNICODE_WITHHELD

    monkeypatch.setattr("src.database.connect._passphrase", None)
    try:
        raise UnicodeEncodeError("ascii", "caf\u00e9", 3, 4, "ordinal not in range(128)")
    except UnicodeError as exc:
        report = _written_then_read(dd, exc)
    text = "\n".join(report["lines"])
    assert f"UnicodeEncodeError: {UNICODE_WITHHELD}"[:150] in text, text
    assert "test_the_report_of_a_unicode_error" in text, "the frames follow the note"
    assert "xe9" not in text and "position" not in text


def test_the_report_of_a_text_withheld_for_the_passphrase_keeps_its_one_line(dd, monkeypatch):
    from src.monitoring import secret_scrub
    from src.monitoring.diagnostics_runs import WITHHELD

    monkeypatch.setenv("OO_DB_PASSPHRASE", "pa55-phrase")
    monkeypatch.setattr(secret_scrub, "_redacted", lambda text, forms: text)  # the scrub removes nothing: the writer withholds
    try:
        raise RuntimeError("context pa55-phrase")
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
        written = (dd / "diagnostics" / "crash_trace.log").read_text(encoding="utf-8")
    assert f"RuntimeError: {WITHHELD}" in written
    _log(dd, "\n" + _header(900, "2026-09-30T01:00:00+00:00") + "\n" + written)
    report = ee.previous_trace(900, None, "2026-09-30T01:00:00Z")
    assert report is not None and not report.get("withheld")
    assert any(line.startswith("RuntimeError: <text withheld") for line in report["lines"]), report["lines"]
    assert "pa55-phrase" not in json.dumps(report)


def test_only_the_fixed_first_lines_the_writer_makes_count_as_whole_not_any_line_that_looks_like_one(dd, monkeypatch):
    from src.database import connect
    from src.monitoring import diagnostics_runs as dr
    from src.monitoring import secret_scrub
    from src.monitoring.secret_scrub import UNICODE_WITHHELD

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    body = "  File \"a.py\", line 1, in f\n"
    # kept as they are: the traceback's own first line and the three fixed lines (with CR LF ends too)
    for first in (
        "Traceback (most recent call last):",
        f"UnicodeDecodeError: {UNICODE_WITHHELD}",
        f"RuntimeError: {dr.WITHHELD}",
        "RuntimeError: its text is withheld",
        f"KeyError: {dr.WITHHELD}\r",
    ):
        assert dr.without_a_torn_start(first + "\n" + body) == first + "\n" + body, first
    assert secret_scrub._class_only(RuntimeError()).endswith(dr._CLASS_ONLY_WORDS), "the words the scrub writes are the ones kept"
    # dropped, as a torn first line: a name with words after the fixed ones, words that are not the fixed ones, and a half line
    for first in (
        "RuntimeError: its text is withheld by someone",
        "RuntimeError: something else",
        "odd words: " + dr.WITHHELD,
        "tail of a line cut in the middle",
    ):
        assert dr.without_a_torn_start(first + "\n" + body) == body, first


def test_the_previous_sessions_report_names_its_trace_by_its_start(dd):
    """The report on the previous session passes the sentinel's start to the trace lookup: two sessions
    of one pid must not both read the newest header's stack."""
    _log(dd, (
        "\n" + _header(500, "2026-09-30T01:59:40+00:00") + "\nFatal Python error: Aborted\n\nThread 0x1:\n  File \"a.py\", line 1 in early_stack\n"
        + "\n" + _header(500, "2026-09-30T13:59:40+00:00") + "\nFatal Python error: Aborted\n\nThread 0x1:\n  File \"a.py\", line 1 in late_stack\n"
    ))
    report = forensics._exit_evidence_report({"pid": 500, "started_at": "2026-09-30T02:00:00+00:00"})
    assert "early_stack" in "".join(report["crash_trace"]["lines"])


def test_every_boot_of_a_process_names_the_build_it_took_at_its_start_not_a_fresh_read(dd, monkeypatch):
    first = {"git_head": "a" * 40, "migrations": {"count": 1, "fingerprint": "f1"}}
    second = {"git_head": "b" * 40, "migrations": {"count": 2, "fingerprint": "f2"}}
    monkeypatch.setattr(bm, "code_markers", lambda root=None: first)
    rec1 = sh.record_boot(None)
    monkeypatch.setattr(bm, "code_markers", lambda root=None: second)
    sh._reset_for_tests()
    rec2 = sh.record_boot(None)
    assert rec1["code"] == rec2["code"] == first, "a pull without a restart does not change what this process runs"


# --------------------------------------------------------------------------- #
#  the ledger never breaks a boot
# --------------------------------------------------------------------------- #
def test_peaks_that_raise_cost_the_end_its_peaks_and_never_the_boot(dd, monkeypatch):
    import os

    monkeypatch.setattr(sh, "_peaks_of", lambda hwm: (_ for _ in ()).throw(RuntimeError("bad sidecar")))
    monkeypatch.setattr(sh.time, "time", lambda: 1_700_000_000.0)
    sh.record_boot(None)
    sh._reset_for_tests()
    (dd / "session_hwm.json").write_text(json.dumps({"pid": os.getpid(), "rss_max_mb": 9.0}), encoding="utf-8")
    session_hwm.reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: 1_700_000_600.0)
    sh.record_boot({"state": "running", "pid": os.getpid(), "started_at": "2023-11-14T22:13:20Z"})
    end = next(r for r in sh.read_records() if r["kind"] == "end")
    assert end["clean"] is False and "previous_peaks" not in end
    assert any(r["kind"] == "boot" for r in sh.read_records()[1:]), "the second boot was written"


# --------------------------------------------------------------------------- #
#  an older log that holds the passphrase is read without it
# --------------------------------------------------------------------------- #
def _legacy_body(secret: str) -> list[str]:
    """What a log written before ``note_fatal_exception`` scrubbed can hold: the passphrase in every form
    the code writes it in, at the place the 200-character line cut falls on, and in the statement."""
    from src.monitoring.secret_scrub import held_shapes

    body = ["Uncaught exception ended the server at 2026-09-30T01:00:00Z:", "Traceback (most recent call last):"]
    for form in sorted(held_shapes() or ()):
        # the form starts so that the line's cut (at the 200th character) keeps its first nine letters, whatever
        # quoting and backslashes come before them: a cut made first leaves "correct h" and no whole form
        letters = form.index("correct") if "correct" in form else 0
        body.append("x" * max(0, ee._TRACE_LINE_CHARS - 10 - letters) + form + " and the rest of the line")
    body.append(f"RuntimeError: near x [SQL: PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}']")
    return body


FRAGMENTS = ("correc", "horse", "battery", "orse's", "ttery")


def test_an_older_log_that_holds_the_passphrase_is_read_without_it(dd, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    report = ee._trace_report(_legacy_body(SECRET), ee.Path("c.log"), 10_000)
    text = json.dumps(report)
    for fragment in FRAGMENTS:
        assert fragment not in text, fragment
    assert report["lines"] and "withheld" not in report and "***redacted***" in text


def test_the_previous_session_and_the_earlier_ends_are_read_without_the_passphrase(dd, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    _log(dd, "\n" + _header(500, "2026-09-30T00:59:40+00:00") + "\n" + "\n".join(_legacy_body(SECRET)) + "\n")
    previous = ee.previous_trace(500, None, "2026-09-30T01:00:00+00:00")
    recs = [_boot("s1", "2026-09-30T01:00:00Z", 500), _end("s1", "2026-09-30T01:30:00Z", signal="SIGABRT")]
    earlier = ee.earlier_unclean_ends(None, records=recs)
    assert previous is not None and earlier["sessions"][0]["trace"] is not None
    for blob in (json.dumps(previous), json.dumps(earlier)):
        for fragment in FRAGMENTS:
            assert fragment not in blob, fragment


def test_the_scrub_runs_before_the_head_is_chosen_and_the_lines_are_limited(dd, monkeypatch):
    """The head and the first lines are chosen from the CLEAN text: a passphrase in the head line, or
    one that straddles the last line kept, must not survive being the thing the cut keeps."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    body = [f"Fatal Python error: Aborted in {SECRET}", "", "Current thread 0x1:"] + [f"  File \"a.py\", line 1 in {SECRET}"] * 10
    report = ee._trace_report(body, ee.Path("c.log"), 4)
    assert len(report["lines"]) == 4 and report["lines_total"] == len(body)
    for blob in (report["summary"], *report["lines"]):
        assert "horse" not in blob and "correct" not in blob


def test_a_trace_that_cannot_be_made_free_of_the_passphrase_is_withheld_whole(dd, monkeypatch):
    from src.monitoring import secret_scrub

    monkeypatch.setenv("OO_DB_PASSPHRASE", "pa55-phrase")
    monkeypatch.setattr(secret_scrub, "_redacted", lambda text, forms: text)  # the scrub removes nothing
    report = ee._trace_report(["Fatal Python error: Aborted", "context pa55-phrase"], ee.Path("c.log"), 60)
    assert report["withheld"] is True and report["lines"] == [] and report["lines_total"] == 2
    assert "pa55-phrase" not in json.dumps(report) and "withheld" in report["summary"]


def test_every_reason_a_report_gives_is_made_by_the_one_scrub(dd, monkeypatch):
    import shutil

    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    why = forensics._why(RuntimeError(f"cannot read {dd}/x: key '{SECRET}'"))
    assert "horse" not in why and str(dd) not in why and "<data>" in why and len(why) <= forensics._REASON_CHARS
    assert forensics._why(type("Broken", (Exception,), {"__str__": lambda self: 1 / 0})()) == "Broken: its text is withheld"
    # arming the trace fails when the folder cannot be made: the reason names no folder of the person
    monkeypatch.setattr(ee, "_TRACE_HANDLE", None)
    shutil.rmtree(dd / "diagnostics")
    (dd / "diagnostics").write_text("a file where the folder should be", encoding="utf-8")
    out = ee.arm_crash_trace()
    assert out["armed"] is False and str(dd) not in out["reason"] and len(out["reason"]) <= ee._ARM_REASON_CHARS


# --------------------------------------------------------------------------- #
#  the log is read as it was WRITTEN, and a passphrase with a line break in it is still found
# --------------------------------------------------------------------------- #
PID, STARTED = 500, "2026-09-30T01:00:00+00:00"
LINE_BREAKERS = {
    "lf": "line-one-secret\nline-two-secret",
    "cr": "cr-one-secret\rcr-two-secret",
    "crlf": "crlf-one-secret\r\ncrlf-two-secret",
    "vt": "vt-one-secret\x0bvt-two-secret",
    "ff": "ff-one-secret\x0cff-two-secret",
    "nel": "nel-one-secret\x85nel-two-secret",
    "line-separator": "ls-one-secret\u2028ls-two-secret",
    "paragraph-separator": "ps-one-secret\u2029ps-two-secret",
}


def _pieces(secret: str) -> list[str]:
    import re

    return [p for p in re.split(r"[\r\n\x0b\x0c\x1c-\x1e\x85\u2028\u2029]", secret) if p]


def _block(secret: str) -> list[str]:
    q = secret.replace("'", "''")
    return [
        "Uncaught exception ended the server at 2026-09-30T01:00:00Z:",
        "Traceback (most recent call last):",
        '  File "a.py", line 1, in f',
        f"RuntimeError: near x [SQL: PRAGMA key = '{q}'] and {secret!r} and {secret} then more",
        "the line after",
    ]


def _write_log(dd, lines: list[str], *, windows: bool) -> None:
    """The log as bytes: LF ends, or CR LF ends the way a text-mode writer on Windows leaves every LF (an LF
    INSIDE a passphrase included)."""
    text = "\n" + _header(PID, "2026-09-30T00:59:40+00:00") + "\n" + "\n".join(lines) + "\n"
    if windows:
        text = text.replace("\n", "\r\n")
    (dd / "diagnostics" / "crash_trace.log").write_bytes(text.encode("utf-8"))


def _both_readers(dd):
    previous = ee.previous_trace(PID, None, STARTED)
    recs = [_boot("s1", "2026-09-30T01:00:00Z", PID), _end("s1", "2026-09-30T01:30:00Z", signal="SIGABRT")]
    earlier = ee.earlier_unclean_ends(None, records=recs)
    assert previous is not None and earlier["sessions"][0]["trace"] is not None
    return previous, earlier["sessions"][0]["trace"]


@pytest.mark.parametrize("windows", [False, True], ids=["lf-log", "crlf-log"])
@pytest.mark.parametrize("name", sorted(LINE_BREAKERS))
def test_a_passphrase_with_a_line_break_is_read_without_it_from_a_log_by_both_readers(dd, monkeypatch, name, windows):
    """``read_text().splitlines()`` split the log on CR, VT, FF, NEL and the two Unicode separators as well
    as LF, so a passphrase holding one of them came out as two lines that no form of it matches; and a log
    a Windows build wrote has every LF, the passphrase's included, as CR LF."""
    from src.database import connect

    secret = LINE_BREAKERS[name]
    monkeypatch.setattr(connect, "_passphrase", secret)
    _write_log(dd, _block(secret), windows=windows)
    for report in _both_readers(dd):
        blob = json.dumps(report, ensure_ascii=False)
        assert "withheld" not in report and report["lines"], report
        for piece in _pieces(secret):
            assert piece not in blob, (name, windows, piece)
        assert "RuntimeError" in blob, "the rest of the exception is kept"
        assert all(not ln.endswith("\r") for ln in report["lines"]), "a CR LF end is not part of the line"


def test_a_log_is_split_on_lf_alone(dd):
    _log(dd, "a\rb\x0bc\x85d\u2028e\nsecond\r\nthird")
    lines, decoded = ee._read_log(dd / "diagnostics" / "crash_trace.log")
    assert decoded is True and lines == ["a\rb\x0bc\x85d\u2028e", "second\r", "third"]


@pytest.mark.parametrize("windows", [False, True], ids=["lf-log", "crlf-log"])
def test_a_block_an_older_writer_cut_inside_the_passphrase_is_read_without_its_tail(dd, monkeypatch, windows):
    """The older writer cut the exception's text from the FRONT before it took the passphrase out, so a
    block can begin with the tail of a passphrase: no scrub of the whole passphrase can see it."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    block = [
        "Uncaught exception ended the server at 2026-09-30T01:00:00Z:",
        SECRET[10:] + " and the end of that line",
        '  File "a.py", line 1, in f',
        "RuntimeError: boom",
    ]
    _write_log(dd, block, windows=windows)
    for report in _both_readers(dd):
        blob = json.dumps(report)
        assert "horse" not in blob and "battery" not in blob and "RuntimeError: boom" in blob, report


@pytest.mark.parametrize("windows", [False, True], ids=["lf-log", "crlf-log"])
def test_a_block_cut_inside_an_lf_passphrase_before_its_lf_is_read_without_its_tail(dd, monkeypatch, windows):
    from src.database import connect

    secret = LINE_BREAKERS["lf"]
    monkeypatch.setattr(connect, "_passphrase", secret)
    cut = secret.index("\n")  # the window begins at the passphrase's own line break
    block = [
        "Uncaught exception ended the server at 2026-09-30T01:00:00Z:",
        *(secret[cut:] + " and the end of that line").split("\n"),
        '  File "a.py", line 1, in f',
        "RuntimeError: boom",
    ]
    _write_log(dd, block, windows=windows)
    for report in _both_readers(dd):
        blob = json.dumps(report)
        assert "line-two" not in blob and "RuntimeError: boom" in blob, report


def test_a_block_that_begins_whole_is_kept_whole(dd, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    _write_log(dd, _block("no relation to the held one"), windows=False)
    previous, _ = _both_readers(dd)
    assert "Traceback (most recent call last):" in previous["lines"] and "withheld" not in previous


def test_a_log_that_is_not_valid_utf8_is_withheld_whole_by_both_readers(dd, monkeypatch):
    """Decoded with the bad bytes replaced it could hide a passphrase written in another encoding, so it is
    read only to find its header, and no report is made from it."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    head = ("\n" + _header(PID, "2026-09-30T00:59:40+00:00") + "\nFatal Python error: Aborted\nRuntimeError: ").encode()
    (dd / "diagnostics" / "crash_trace.log").write_bytes(head + b"\xff\xfe broken \xc3(\n")
    for report in _both_readers(dd):
        assert report["withheld"] is True and report["lines"] == [] and "UTF-8" in report["summary"], report


def test_a_key_statement_whose_literal_spans_two_lines_is_taken_out_whole(dd):
    body = [
        "Fatal Python error: Aborted", "", "Current thread 0x1:",
        "RuntimeError: near [SQL: PRAGMA key = 'k3y-first-half",
        "k3y-second-half'] then more",
    ]
    report = ee._trace_report(body, ee.Path("c.log"), 60)
    blob = json.dumps(report)
    assert "first-half" not in blob and "second-half" not in blob and "***redacted***" in blob


def test_a_line_that_is_cut_leaves_no_part_of_a_passphrase_in_any_script(dd, monkeypatch):
    from src.database import connect

    secret = "p\u00e4ss-\u6f22\u5b57-secret"
    monkeypatch.setattr(connect, "_passphrase", secret)
    body = ["Fatal Python error: Aborted", "", "Current thread 0x1:", "RuntimeError: " + "\u6f22" * 40 + secret + "\U0001d518" * 400]
    report = ee._trace_report(body, ee.Path("c.log"), 60)
    for line in (report["summary"], *report["lines"]):
        assert "secret" not in line and len(line.encode("utf-8")) <= ee._TRACE_LINE_BYTES and len(line) <= ee._TRACE_LINE_CHARS


def test_a_checkout_inside_the_home_folder_is_still_named_by_its_src_path(dd, monkeypatch):
    """The scrub names the person's folder ``<home>`` before the lines are shortened, so a frame of the app's
    own code under it (a developer's clone, a CI runner's) reads ``<home>/.../src/...`` by then."""
    import pathlib

    app = pathlib.PurePosixPath(session_hwm._APP_SRC)
    assert len(app.parts) > 3, app
    home = str(pathlib.PurePosixPath(*app.parts[:-2]))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: pathlib.Path(home)))
    body = [
        "Fatal Python error: Aborted", "", "Current thread 0x1 (most recent call first):",
        f'  File "{session_hwm._APP_SRC}/api/x.py", line 5 in handler',
        f'  File "{home}/private-case/notes.py", line 3 in <module>',
        f"ValueError: cannot open {home}/oo/data.db",
    ]
    report = ee._trace_report(body, ee.Path("c.log"), 60)
    text = "\n".join(report["lines"])
    assert 'File "src/api/x.py"' in text and 'File "notes.py"' in text, text
    assert "private-case" not in text and home not in text and "<home>/oo/data.db" in text


# --------------------------------------------------------------------------- #
#  the dead session's marks go to its own end, and only to its own
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("state", "marks"),
    [
        ({"pid": 4242, "boot_id": BOOT, "started_at": "2023-11-14T22:13:22+00:00"}, True),  # the same process
        ({"pid": 4242, "boot_id": None, "started_at": "2023-11-14T22:13:20Z"}, True),  # a boot not named on one side
        ({"pid": 4242, "boot_id": "22222222-aaaa-bbbb-cccc-000000000002", "started_at": "2023-11-14T22:13:20Z"}, False),
        ({"pid": 4242, "boot_id": BOOT, "started_at": "2023-11-14T20:00:00Z"}, False),  # the pid again, hours earlier
        ({"pid": 4243, "boot_id": BOOT, "started_at": "2023-11-14T22:13:20Z"}, False),
        ({"pid": None, "boot_id": BOOT, "started_at": "2023-11-14T22:13:20Z"}, False),
    ],
)
def test_the_sidecars_marks_reach_an_end_only_when_it_is_the_same_process(dd, monkeypatch, state, marks):
    sh._append({"kind": "boot", "session_id": "s1", "at": "2023-11-14T22:13:20Z", "pid": 4242, "machine_boot_id": BOOT})
    monkeypatch.setattr(sh, "_hwm_last_seen", lambda prev, sid=None: (None, "no identity") if sid else ({"last_ts": "2023-11-14T22:30:00Z"}, None))
    monkeypatch.setattr(sh, "_peaks_of", lambda hwm: {"rss_max_mb": 9.0})
    end = sh._close_previous({"state": "running", **state}, None)
    assert ("previous_peaks" in end) is marks, end


def test_a_seed_whose_marks_cannot_be_read_still_writes_the_session_it_seeds(dd, monkeypatch):
    monkeypatch.setattr(sh, "_hwm_last_seen", lambda prev, sid=None: ({"last_ts": "2023-11-14T22:30:00Z"}, None))
    monkeypatch.setattr(sh, "_peaks_of", lambda hwm: (_ for _ in ()).throw(RuntimeError("bad sidecar")))
    end = sh._close_previous({"state": "running", "pid": 7, "started_at": "2023-11-14T22:13:20Z"}, None)
    kinds = [r["kind"] for r in sh.read_records()]
    assert kinds == ["boot", "end"] and end["clean"] is False and "previous_peaks" not in end


def test_the_trace_rotation_and_header_run_under_the_files_lock_and_a_fatal_note_is_appended_under_it(dd, monkeypatch):
    """R176: two servers booting on one folder could both rotate the trace, and a header could land in a file the other was renaming."""
    import faulthandler
    import os

    held = []
    real_lock = ee.file_lock

    class Spy:
        def __init__(self, path):
            self.cm = real_lock(path)

        def __enter__(self):
            held.append(True)
            return self.cm.__enter__()

        def __exit__(self, *exc):
            held.pop()
            return self.cm.__exit__(*exc)

    seen_while_held = []
    real_replace = os.replace
    monkeypatch.setattr(ee, "file_lock", Spy)
    monkeypatch.setattr(ee.os, "replace", lambda a, b: (seen_while_held.append(bool(held)), real_replace(a, b))[1])
    monkeypatch.setattr(ee, "_TRACE_HANDLE", None)
    monkeypatch.setattr(faulthandler, "enable", lambda **kw: None)
    ee.crash_trace_path().write_text("x" * (ee._TRACE_MAX_BYTES + 1), encoding="utf-8")
    out = ee.arm_crash_trace()
    try:
        assert out["armed"] is True
        assert seen_while_held == [True], "the trace was rotated outside the file's lock"
        assert (dd / "diagnostics" / "crash_trace.log.1").exists()
    finally:
        if ee._TRACE_HANDLE is not None:
            ee._TRACE_HANDLE.close()
            ee._TRACE_HANDLE = None
    ee.note_fatal_exception(RuntimeError("boom"))
    assert "Uncaught exception ended the server" in ee.crash_trace_path().read_text(encoding="utf-8")
