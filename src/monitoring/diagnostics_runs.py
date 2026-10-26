"""A durable record of every all-diagnostics run and of every file the page was served.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (2026-10-06, R119). The first All diagnostics run on the 17 machines of the
2026-10-05 burst failed on some of them, and the operator had to press the button again. The
evidence of that first run was in no bundle: a run that fails or is killed leaves a journal
next to its half-built archive, the next run folds it into ITS zip, and a run that failed by an
exception left nothing at all. Nothing recorded either how long a run took, which build ran it,
or whether the file the page asked for was ever sent.

WHAT IS KEPT, in ``data/diagnostics/runs.jsonl``, one JSON object a line: names of the files built or
served, counts and times, and -- the one place free text is kept -- a failed run's one-line reason, which is
taken through ``tidy_error`` (the passphrase in every form it is written in, a database key's statement
literal and the person's folders are taken out of the WHOLE text, and only then is it cut). No address and no
search term is ever recorded:

- ``run`` ``begin`` when the build starts (a random record id, the archive's name, the profile,
  the process's pid and a random token of this process, the machine's boot, the build's markers
  as the process booted with them) and ``run`` ``end`` when it finishes (``done``, ``cancelled``
  or ``failed``, its seconds, the archive's bytes, the member outcomes counted, a failure's
  one-line reason). A ``begin`` with no ``end`` is read as one of three things and never as a
  success: this process is still running it, this process began it and its end could not be
  written, or another process began it and is gone (or is another instance using the folder).
- ``serve`` ``begin`` when the server starts sending a file (its name, size and time) and
  ``serve`` ``end`` when the response has finished, with HOW it finished: ``complete`` (a 200 whose
  last byte was handed to the server while the page was still connected), ``range`` (a 206: a
  part of the file, as a browser's resume asks for), ``abandoned`` (the page disconnected first)
  or ``error`` (sending raised).

WHAT IT COVERS: the files served through the background build's download, the numbered volumes of
a split archive and the numbered keyword files. It does not cover the synchronous ``GET /all``
route (a legacy path that builds in the request and answers with the bytes), the keyword log's
scratch zip or the temporary source-quality zip: nothing here is claimed about those.

WHAT IT CANNOT KNOW, said in the member: the browser saving a file is not observable. ``complete``
means the server handed the last byte over while the page was connected, not that the person has
the file.

NO WALL CLOCK DECIDES WHAT IS THIS PROCESS, and none times a transfer. A process is told from its
own random token (a clock step moves a process's start time as psutil reports it, and a reused pid
never carries the token), and a duration is the difference of two monotonic readings in the process
that measured it.

THE LAST TEN RUNS, AND THE SERVES SINCE THE OLDEST OF THEM. Ten is what a series such as
"three failed runs, then one that worked" is read against; the zips of earlier days already
carried what they carried. The file is rewritten aside when a run begins and something has
to go, and also when an append would take it past ``MAX_FILE_BYTES``: the serve lines of a long
series of retries never grow it past that, and the rewrite is synced (the file and the folder).

Every call is best-effort and never raises into its caller: a record about the diagnostics
must not be the thing that fails a diagnostics run. A line is written with one ``write``, flushed
and fsynced: a run takes minutes and a kill is what this exists to read, so it is worth the one
disk sync (the writes are rare: a handful a run).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import UNICODE_WITHHELD, record_text
from src.paths import data_dir
from src.safety.file_lock import atomic_replace, file_lock

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-diagnostics-runs-2"
_FILE = "runs.jsonl"

#: The runs kept (see the module text). What the file protects: it is read by a person asking
#: "did the first run fail, and did the second work", which ten answers; and what it must not
#: become is a log that grows with every press of the button over weeks.
KEEP_RUNS = 10
#: The serve records kept: up to six files a hand-over of the largest set, for the ten runs.
KEEP_SERVES = 60
#: The file's byte ceiling. A run's lines are a few hundred bytes (the failure reason is cut to
#: ``ERROR_CHARS``), so this is far above ten runs and exists so that a bug elsewhere (a loop
#: that begins a run per iteration, a page that retries a download in a loop) cannot fill a disk
#: through here: an append that would pass it rewrites the file to what the kept counts allow.
MAX_FILE_BYTES = 96 * 1024
#: The most of the file that is READ. The file is written by this module and kept to ``MAX_FILE_BYTES``; a
#: larger one was grown by something else (a second writer, a copy of another file, a disk fault), and
#: reading it whole into the build's memory is what this ceiling prevents. Eight times the file's own
#: ceiling holds every line a healthy file can carry with room for a few torn ones. A larger file is read from
#: its END (the newest lines), the member says so, and the next write rewrites it down to what it keeps.
READ_MAX_BYTES = 8 * MAX_FILE_BYTES
#: A failed run's reason as kept. What it protects: the file stays a few hundred bytes a run (the ceiling
#: above), and a reason is read as "what failed", which the type and the first sentence of the engine's text
#: say. It is the LAST step of ``tidy_error``, after the text is made free of the passphrase.
ERROR_CHARS = 300
#: The reason this recorder's own member gives when the file could not be read at all. What it protects: the
#: member stays a few hundred bytes when it has nothing else to say, and a reason is read as "what failed",
#: which the type and the first sentence say; cut AFTER the scrub like every reason here.
MEMBER_REASON_CHARS = 200
#: Said in place of a text that could not be made free of the passphrase (the fail-closed answer).
WITHHELD = "<text withheld, it could not be made free of the passphrase>"
#: The member's own budget (raw JSON): the slot-table figure of the redesign plan. What it protects: the room the
#: other members need in the zip (the file itself is at most 96 KiB, and the member is a view of its newest
#: runs and serves), not a limit of this module's own; a table over it loses its oldest rows first and says so.
MEMBER_MAX_BYTES = 40_000

#: How a transfer ended (the ``how`` of a ``serve`` ``end`` line), and what each says of the page.
HOW_COMPLETE, HOW_RANGE, HOW_ABANDONED, HOW_ERROR = "complete", "range", "abandoned", "error"
#: A HEAD request (headers only, no file) and a request the server answered with a refusal (a range it
#: could not satisfy, a malformed range header): neither sent the file, and neither failed.
HOW_HEAD, HOW_REFUSED = "head", "refused"
_HOWS = (HOW_COMPLETE, HOW_RANGE, HOW_ABANDONED, HOW_ERROR, HOW_HEAD, HOW_REFUSED)

_LOCK = threading.Lock()
#: A random token of THIS process, new at every start. It is what says "this process began that
#: run": not the pid (the machine reuses them) and not the process's start time as psutil reads it
#: (it is computed from the machine's boot time plus the wall clock, so a clock step moves it).
_PROCESS = secrets.token_hex(6)
#: The run ids this process began and has not yet ended, so a ``begin`` without an ``end`` reads as
#: "running" only while the build is in fact running here.
_RUNNING: set[str] = set()
#: The files being sent now by THIS process, ``sid`` -> the monotonic time the sending began.
_ACTIVE: dict[str, float] = {}


def _path() -> Path:
    return data_dir() / "diagnostics" / _FILE


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _boot_id() -> str | None:
    try:
        from src.monitoring.session_history import machine_boot_id

        return machine_boot_id()
    except Exception:  # noqa: BLE001
        return None


def _build_markers() -> dict[str, Any]:
    """The commit and the migration fingerprint the process BOOTED with (``build_marker``'s cache,
    taken at the boot record), not a fresh read: after a ``git pull`` without a restart a fresh
    read would name code that is not the code running."""
    try:
        from src.monitoring.build_marker import process_markers

        marks = process_markers()
        out: dict[str, Any] = {"git_head": marks.get("git_head")}
        migrations = marks.get("migrations")
        fingerprint = migrations.get("fingerprint") if isinstance(migrations, dict) else None
        if fingerprint:
            out["migrations"] = fingerprint
        return out
    except Exception:  # noqa: BLE001
        return {}


#: The statements this code and its drivers write a database key in. Taken out of a failure's text
#: in whatever quoting it comes in (``''`` doubles a quote inside a single-quoted literal). The
#: passphrase itself is taken out first, from the whole text, by ``scrubbed_text``; this is the net for a
#: statement whose literal that cannot name, such as the key DuckDB is attached with. TWO patterns, applied
#: one after the other and not one alternation: an ``ATTACH`` span may run over other text (and over
#: another statement's literal, quoted paths included), and the match keeps that span, so a single pattern
#: that met ``ATTACH 'a.db' AS d (ENCRYPTION_KEY 'k1') ... ATTACH x AS y KEY 'k2'`` kept ``'k1'`` inside the
#: span it matched. Each pass leaves what the other takes out, so either order gives the same text.
_KEY_LITERALS = (
    re.compile(
        r"(?is)(\b(?:pragma\s+(?:hex|re)?key\s*=?\s*|encryption_key\s*=?\s*))"
        r"(?:'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")"
    ),
    re.compile(
        r"(?is)(\battach\b(?:[^;']|'(?:[^']|'')*'){0,200}?\bkey\s+)"
        r"(?:'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")"
    ),
)


def tokenise_paths(text: str) -> str:
    """The data folder and the home folder replaced by ``<data>`` and ``<home>`` (longest first, in
    both slash directions): a failure's text names the file it failed on, and the data folder
    defaults to a path under the person's name."""
    pairs: list[tuple[str, str]] = []
    for label, raw in (("<data>", data_dir), ("<home>", Path.home)):
        try:
            where = raw()
        except Exception:  # noqa: BLE001 - a folder that cannot be named is not replaced
            continue
        for form in {str(where), Path(where).as_posix()}:
            if len(form) > 1:
                pairs.append((form, label))
    for form, label in sorted(pairs, key=lambda pair: -len(pair[0])):
        text = text.replace(form, label)
    return text


def _redact_literal(m: re.Match[str]) -> str:
    return m.group(1) + "'***redacted***'"


def _key_literals_out(text: str) -> str:
    """``text`` with the literal of every key statement ``_KEY_LITERALS`` names replaced."""
    for pattern in _KEY_LITERALS:
        text = pattern.sub(_redact_literal, text)
    return text


#: The words ``scrubbed`` is handed as the text to write when it could not check one, so that a text it kept is told from
#: a text it did not (the marker holds a NUL, which no text this code reads or makes does).
_UNCHECKED = "\x00unchecked\x00"


def _taken_out(text: str) -> str | None:
    """``text`` with every passphrase the process holds taken out of it by the one scrub (``secret_scrub.scrubbed``: every
    shape, the longest first, in one read of the text), or ``None`` when that scrub could not check it (what the process holds
    could not be read, the text holds a secret that is too short to take out of free text, or anything failed)."""
    from src.monitoring.secret_scrub import scrubbed

    out = scrubbed(text, withheld=_UNCHECKED)
    return None if out == _UNCHECKED else out


def _clean(out: str) -> bool:
    """Whether ``out`` holds no shape of a held passphrase and no key statement's literal. The shapes are read here again
    (``secret_scrub.held_shapes``) and not through the scrub that just ran, so a scrub that missed one is caught by a
    check that does not share its matching or its cache. WHAT THIS DOES NOT CATCH: it reads the same list of shapes
    (``secret_scrub._shapes``) and the same held passphrases (``held_passphrases``) as the scrub, so a shape the list
    leaves out, or a passphrase ``held_passphrases`` does not return (``OO_KEY_PASSPHRASE`` forgotten), is missed by both
    together. It catches a regression in ``_redact``/``_redacted``/``_clean``/``_forms_now`` or in the ``_HELD_FORMS`` cache
    (a stale entry after the passphrase changed), and a replacement that rebuilds what an earlier step took out."""
    from src.monitoring.secret_scrub import held_shapes

    forms = held_shapes()
    return forms is not None and not any(form in out for form in forms) and _key_literals_out(out) == out


def scrubbed_text(text: str, *, one_line: bool = False, file_text: bool = False) -> str | None:
    """The ONE whole-text scrub of what this recorder and the crash-trace read keep, or ``None`` when the
    text could not be shown to be clean (the caller then withholds it, never keeps it).

    The order is the reason: (1) the passphrase in every form it is written in, from the WHOLE text and
    before anything shortens it -- a cut that fell inside the passphrase would leave the part it kept, which
    no scrub of the cut text can see, and a collapse of whitespace could split a passphrase that has some;
    (2) a database key's statement literal, in whatever quoting; (3) with ``one_line``, whitespace collapsed;
    (4) the data and home folders named ``<data>`` and ``<home>``; (5) the result checked once more for the
    passphrase and for a key literal, because a replacement can rebuild what an earlier step took out
    (a held passphrase that is ``<data>`` is rebuilt by naming the folder). The caller cuts AFTER this, once, last.

    Step (1) is ``secret_scrub.scrubbed`` (the shapes it takes out are ``secret_scrub._shapes``), the one call every
    handler of this program writes a caught exception's text through; step (5) reads the shapes again through
    ``secret_scrub.held_shapes``. A text that cannot be checked by either is ``None``.

    ``file_text`` is for text read back from a file this program wrote in TEXT MODE: on Windows every LF
    in it was written as CRLF, so a passphrase that holds an LF sits there as CR LF (and one that holds
    CR LF as CR CR LF). The first pass is made on the text exactly as it is, so a form that holds a CR
    is matched as written; a second pass is made on the text with every CR LF turned back into LF, which
    is where those forms are matched; the result is checked in both spellings.

    The net is an exact match of the shapes ``secret_scrub`` lists and of the statements ``_KEY_LITERALS``
    name: a key written some other way is not recognised. The statements that carry the key are written in
    ``src/database/connect.py`` (``PRAGMA key``, ``ATTACH ... KEY``) and ``src/analytics/columnar.py``
    (``ENCRYPTION_KEY``), and a statement added in another shape needs its own pattern here."""
    try:
        out = _taken_out(text)
        if out is None:
            return None
        if file_text and "\r\n" in out:
            out = _taken_out(out.replace("\r\n", "\n"))
            if out is None:
                return None
        out = _key_literals_out(out)
        if one_line:
            out = " ".join(out.split())
        out = tokenise_paths(out)
        if not _clean(out):
            return None
        if file_text and not _clean(out.replace("\n", "\r\n")):
            return None
        return out
    except Exception:  # noqa: BLE001 - failing CLOSED: the caller withholds what it could not scrub
        return None


def held_forms() -> list[str]:
    """Every shape of the passphrases this process holds, longest first (empty when it holds none).
    Raises when they cannot be read, so a caller that needs the forms fails closed."""
    from src.monitoring.secret_scrub import held_shapes

    forms = held_shapes()
    if forms is None:
        raise RuntimeError("the passphrases this process holds could not be read")
    return list(forms)


def without_a_torn_start(text: str) -> str | None:
    """``text`` -- the start of a log entry whose writer cut it from the FRONT before it took anything out
    (``text[-8000:]``) -- without what that cut could have left of the passphrase, or ``None`` when that could
    not be established. A cut that fell inside the passphrase leaves its tail at the start, where no
    scrub of the whole passphrase can see it: the longest tail of any form that the text begins with is
    taken off (in the text as it is, or with CR LF read as LF, which is how a text-mode writer on Windows
    wrote a passphrase that holds an LF), and so is the line it ends in, which is the torn one. A text
    that starts with a whole first line (the traceback's own, or one of the fixed lines ``note_fatal_exception``
    writes in place of a traceback: ``_is_a_written_first_line``) is kept as it is."""
    try:
        forms = held_forms()
    except Exception:  # noqa: BLE001 - failing CLOSED
        return None

    def longest_tail(t: str) -> int:
        return max((len(f) - k for f in forms for k in range(1, len(f)) if t.startswith(f[k:])), default=0)

    plain = text.replace("\r\n", "\n")
    if longest_tail(plain) > longest_tail(text):
        text = plain
    cut = longest_tail(text)
    rest = text[cut:]
    if not cut and _is_a_written_first_line(rest):
        return rest
    _torn, newline, whole_lines = rest.partition("\n")
    return whole_lines if newline else ""


#: The first line of a Python traceback. A text that begins with it was not cut from the front inside a
#: line: a tail of the passphrase cannot be followed by this text without a cut at the line's start.
_WHOLE_FIRST_LINE = "Traceback (most recent call last):"
#: The words ``note_fatal_exception`` writes after a class name in place of a traceback's first line: a ``UnicodeError`` in
#: the chain (``secret_scrub.UNICODE_WITHHELD``, followed by the frames), a text that could not be made free of the
#: passphrase (``WITHHELD``, the whole block) and a scrub that could not run (``secret_scrub._class_only``'s words). They
#: are fixed, so a block that begins with one of them was written whole by this code and cut from nothing: the report
#: keeps the line that says what happened, which is the one thing a reader of the crash needs. What they are not: a
#: passphrase's tail (a class name, a colon and these words are not a piece of any shape, and ``cut`` is zero above).
_CLASS_ONLY_WORDS = "its text is withheld"
_WRITTEN_FIRST_LINE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*: (?:" + "|".join(re.escape(w) for w in (UNICODE_WITHHELD, WITHHELD, _CLASS_ONLY_WORDS)) + r")\Z"
)


def _is_a_written_first_line(text: str) -> bool:
    """Whether ``text`` begins with a first line this code writes whole: a traceback's, or one of the fixed lines above."""
    first = text.partition("\n")[0].rstrip("\r")
    return first.startswith(_WHOLE_FIRST_LINE) or _WRITTEN_FIRST_LINE.match(first) is not None


def exc_line(exc: BaseException) -> str:
    """``Type: message`` for an exception, written by ``secret_scrub.exception_text`` -- the one call every handler of this
    program writes a caught exception through: the passphrases the process holds taken out of the WHOLE text, the class
    and none of its words when the text cannot be checked or its ``__str__`` raises, and fixed words and no text at all
    when a ``UnicodeError`` is reachable from the exception (its message names a character and its offset, which is a piece of
    a key that no scrub of the text can know). Never raises. ``tidy_error`` and the callers' own scrub then take out what
    this does not: a key statement's literal and the person's folders."""
    return record_text(exc, typed=True)


def tidy_error(error: Any, limit: int = ERROR_CHARS) -> str:
    """A failure's one-line reason as it is kept: an exception is written by ``exc_line``, the WHOLE text is taken through
    ``scrubbed_text`` (one line), then cut to ``limit`` -- the cut is last, so it cannot keep the start of something that was
    replaced. Never raises: a text that cannot be rendered, or cannot be made free of the passphrase, is named as such and
    not kept."""
    try:
        text = exc_line(error) if isinstance(error, BaseException) else str(error)
    except Exception:  # noqa: BLE001 - a broken __str__ must still yield a marker
        return "<unrenderable>"
    clean = scrubbed_text(text, one_line=True)
    return WITHHELD if clean is None else clean[:limit]


def _read_tail(target: Path) -> tuple[bytes, bool]:
    """The file's bytes -- or, when it is larger than ``READ_MAX_BYTES``, its last ``READ_MAX_BYTES`` from the
    first whole line on -- and whether the front was left unread. A missing file raises ``OSError``."""
    with open(target, "rb") as fp:
        size = os.fstat(fp.fileno()).st_size
        if size <= READ_MAX_BYTES:
            return fp.read(), False
        fp.seek(size - READ_MAX_BYTES)
        raw = fp.read()
    newline = raw.find(b"\n")
    return (raw[newline + 1 :] if newline >= 0 else b""), True


def _read_lines_marked(path: Path | None = None) -> tuple[list[dict[str, Any]], bool]:
    """Every well-formed line of the file, in order, and whether the file was larger than the read allows
    (``READ_MAX_BYTES``: only its end was read). A line that is not a JSON object, whose kind is
    unknown or whose id is not a string is skipped (a torn last line after a kill is the case this
    is for, and a line that parses but would break the trim or the view is the other); a missing
    file is empty."""
    target = path or _path()
    try:
        raw, cut = _read_tail(target)
    except OSError:
        return [], False
    out: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if not isinstance(doc, dict) or doc.get("ev") not in ("begin", "end"):
            continue
        kind = doc.get("k")  # a line that is valid JSON can hold anything here, a list included
        key = {"run": "id", "serve": "sid"}.get(kind) if isinstance(kind, str) else None
        if key is None or not isinstance(doc.get(key), str) or not isinstance(doc.get("t"), str):
            continue
        out.append(doc)
    return out, cut


def _read_lines(path: Path | None = None) -> list[dict[str, Any]]:
    """The well-formed lines of the file (see ``_read_lines_marked``)."""
    return _read_lines_marked(path)[0]


def _encoded(doc: Any) -> int:
    return len(json.dumps(doc, separators=(",", ":")))


def _trim(lines: list[dict[str, Any]], keep_runs: int, reserve: int = 0) -> list[dict[str, Any]]:
    """The last ``keep_runs`` runs' lines and the serve lines from the oldest of them on, within
    ``KEEP_SERVES`` serves and ``MAX_FILE_BYTES`` with ``reserve`` bytes left for the line about to be
    appended. An ``end`` whose ``begin`` is gone is dropped."""
    begins = [i for i, d in enumerate(lines) if d["k"] == "run" and d["ev"] == "begin"]
    if len(begins) > keep_runs:
        first = begins[len(begins) - keep_runs] if keep_runs > 0 else len(lines)
        lines = lines[first:]
    kept_ids = {d["id"] for d in lines if d["k"] == "run" and d["ev"] == "begin"}
    lines = [d for d in lines if not (d["k"] == "run" and d["ev"] == "end" and d["id"] not in kept_ids)]
    serve_ids = [d["sid"] for d in lines if d["k"] == "serve" and d["ev"] == "begin"]
    if len(serve_ids) > KEEP_SERVES:
        keep = set(serve_ids[-KEEP_SERVES:])
        lines = [d for d in lines if d["k"] != "serve" or d["sid"] in keep]
    sizes = [_encoded(d) + 1 for d in lines]
    total, first = sum(sizes), 0
    while total + reserve > MAX_FILE_BYTES and first < len(lines):
        total -= sizes[first]
        first += 1
    return lines[first:]


def _sync_folder(folder: Path) -> None:
    """Sync the folder entry of a replaced file where the system allows it (POSIX); elsewhere a
    no-op, which is the most the platform lets a program ask."""
    with contextlib.suppress(OSError):
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write_all(lines: list[dict[str, Any]]) -> None:
    """Replace the file with ``lines``: written aside, synced, moved over, and the folder synced,
    so that the begin line of the run that triggered the rewrite is not lost to a power cut that
    left the old name pointing at a half-written file."""
    target = _path()
    text = "".join(json.dumps(d, separators=(",", ":")) + "\n" for d in lines)
    # newline="\n": text mode would write each LF as CRLF on Windows, and ``_trim`` counts one byte a newline,
    # so the file would pass the ceiling it is trimmed to.
    atomic_replace(target, text, newline="\n")
    _sync_folder(target.parent)


def _append(rec: dict[str, Any], *, trim_runs: int | None = None) -> bool:
    """One line appended, flushed and fsynced. The file is first rewritten to what the kept counts
    allow when a run begins (``trim_runs``: keep only that many runs) and when the line would take
    it past ``MAX_FILE_BYTES``. A last line a kill tore (no newline) is ended before the new line
    goes after it, or the two would read as one and the new record would be lost. Never raises."""
    try:
        line = (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8")
        with _LOCK:
            target = _path()
            target.parent.mkdir(parents=True, exist_ok=True)
            with file_lock(target):  # the size check, the trim and the append are one section: another server's trim cannot fall between them
                try:
                    size = target.stat().st_size
                except OSError:
                    size = 0
                if trim_runs is not None or size + len(line) > MAX_FILE_BYTES:
                    lines, cut = _read_lines_marked(target)
                    trimmed = _trim(lines, KEEP_RUNS if trim_runs is None else trim_runs, len(line) + 1)
                    if cut or len(trimmed) != len(lines):  # a file read only from its end is rewritten whole
                        _write_all(trimmed)
                with open(target, "a+b") as fp:
                    fp.seek(0, os.SEEK_END)
                    if fp.tell() > 0:
                        fp.seek(-1, os.SEEK_END)
                        last = fp.read(1)
                        fp.seek(0, os.SEEK_END)
                        if last != b"\n":
                            fp.write(b"\n")
                    fp.write(line)
                    fp.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(fp.fileno())
        return True
    except Exception as err:  # noqa: BLE001 - a record about the diagnostics never fails them
        # The reason, not the traceback: this runs inside the handler of the build's own failure (``end_run`` is called
        # from it), so a logged traceback would print that failure's message through ``__context__``, unscrubbed, to
        # every handler. ``tidy_error`` is the one scrub of what this module keeps, and it cannot raise.
        _LOG.debug("diagnostics runs: could not write the record: %s", tidy_error(err))
        return False


def begin_run(name: str, *, profile: str, mode: str | None = None) -> str:
    """Record that a build has started and return its record id (pass it to :func:`end_run`).

    The id is random: two builds of one name (the archive's name has one-second resolution) are two
    runs. Keeps the file to the ``KEEP_RUNS - 1`` runs before this one. The id is returned whether or
    not the line could be written, so the end is still attempted and the process still knows the
    run is its own. ``mode`` (``quick`` or ``thorough``, R124) is recorded when the caller has one."""
    rid = secrets.token_hex(4)
    with _LOCK:
        _RUNNING.add(rid)
    rec: dict[str, Any] = {
        "k": "run", "ev": "begin", "t": _now_iso(), "id": rid, "file": str(name), "profile": str(profile),
        "pid": os.getpid(), "proc": _PROCESS, "boot": _boot_id(), "build": _build_markers(),
    }
    if mode is not None:
        rec["mode"] = str(mode)
    _append(rec, trim_runs=KEEP_RUNS - 1)
    return rid


def summarise_members(results: Any) -> dict[str, int]:
    """The member outcomes of a finished build, counted (``{"ok": 55, "skipped-deadline": 1}``)."""
    counts: Counter[str] = Counter()
    try:
        for item in results or []:
            if isinstance(item, dict):
                counts[str(item.get("outcome") or "unknown")] += 1
    except Exception:  # noqa: BLE001
        return {}
    return dict(sorted(counts.items()))


def end_run(
    rid: str | None, *, outcome: str, seconds: float, size: int | None = None,
    members: dict[str, int] | None = None, error: str | None = None,
) -> bool:
    """Record how a build ended: ``done``, ``cancelled`` or ``failed``. Whatever the write does, the
    run is no longer this process's running one (a write that fails, on a full drive, must not leave
    the newest ``begin`` reading "running" for the rest of the process's life).

    ``error`` is the failure's text AS RAISED, uncut: this takes the passphrase, a key literal and the person's
    folders out of the whole of it and cuts it last (``tidy_error``). A caller that cut it first would hand
    this half of a passphrase that no scrub can see."""
    if not rid:
        return False
    try:
        rec: dict[str, Any] = {
            "k": "run", "ev": "end", "t": _now_iso(), "id": str(rid), "outcome": str(outcome),
            "seconds": round(float(seconds), 1), "bytes": size, "members": members or {},
        }
        if error:
            try:
                rec["error"] = tidy_error(error)
            except Exception:  # noqa: BLE001 - the reason is withheld; the end of the run is still recorded
                rec["error"] = WITHHELD
        return _append(rec)
    finally:
        with _LOCK:
            _RUNNING.discard(rid)


def serve_begin(name: str, size: int | None) -> str | None:
    """Record that the server is starting to send a file; the id to pass to :func:`serve_end`."""
    sid = secrets.token_hex(4)
    with _LOCK:
        _ACTIVE[sid] = time.monotonic()
    ok = _append({
        "k": "serve", "ev": "begin", "t": _now_iso(), "sid": sid, "file": str(name), "bytes": size,
    })
    if not ok:
        with _LOCK:
            _ACTIVE.pop(sid, None)
        return None
    return sid


def serve_end(sid: str | None, how: str = HOW_COMPLETE, status: int | None = None) -> None:
    """Record that a response has finished, and how (and with which HTTP status, when it got as far as
    one). The transfer is no longer "being sent" whatever the write does; its seconds are the
    difference of two monotonic readings in this process."""
    if not sid:
        return
    with _LOCK:
        began = _ACTIVE.pop(sid, None)
    seconds = round(time.monotonic() - began, 1) if began is not None else None
    _append({
        "k": "serve", "ev": "end", "t": _now_iso(), "sid": sid, "how": how, "status": status, "seconds": seconds,
    })


_RESPONSE_CLASS: Any = None


def _recording_response_class() -> Any:
    """``FileResponse`` that records HOW its response ended. Built on first use (the class needs
    fastapi's, and this module must import without it on the boot path)."""
    global _RESPONSE_CLASS
    if _RESPONSE_CLASS is not None:
        return _RESPONSE_CLASS
    import anyio
    from fastapi.responses import FileResponse

    class RecordedFileResponse(FileResponse):
        """The end line is written when the response is over, from what the server was told.

        ``complete`` only when the last body message of a 200 was handed to ``send`` while the
        page was still connected: a server's ``send`` after a disconnect returns without sending
        and without saying so (the file went on being read into nothing, so "the last byte was
        sent" was recorded for a page that had left), so the connection is watched for
        ``http.disconnect`` beside the response. A 206 is a part of the file (a browser's resume
        asks for one) and is recorded as such; a HEAD request or a refusal (416, 400) is not a
        transfer; and an exception while sending ends the record too, so a transfer never reads
        "being sent now" for the rest of the process's life. The exception itself goes on to the
        server as it was raised."""

        def __init__(self, *args: Any, sid: str | None = None, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._sid = sid

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope.get("type") != "http":
                await super().__call__(scope, receive, send)
                return
            gone = anyio.Event()
            seen: dict[str, Any] = {"status": None, "last": False, "gone_before_last": False}

            async def listen() -> None:
                while True:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        gone.set()
                        return

            async def wait_for_disconnect() -> dict[str, Any]:
                await gone.wait()
                return {"type": "http.disconnect"}

            async def watching_send(message: Any) -> None:
                kind = message.get("type")
                if kind == "http.response.start":
                    seen["status"] = message.get("status")
                elif kind == "http.response.pathsend" or (
                    kind == "http.response.body" and not message.get("more_body", False)
                ):
                    seen["last"] = True
                    seen["gone_before_last"] = gone.is_set()
                await send(message)

            how = HOW_ERROR
            try:
                try:
                    async with anyio.create_task_group() as tasks:
                        tasks.start_soon(listen)
                        await super().__call__(scope, wait_for_disconnect, watching_send)
                        tasks.cancel_scope.cancel()
                except BaseExceptionGroup as group:
                    # anyio wraps what the body raised; the server must see the exception itself
                    if len(group.exceptions) == 1:
                        raise group.exceptions[0] from None
                    raise
                status = seen["status"]
                if str(scope.get("method", "")).upper() == "HEAD":
                    how = HOW_HEAD
                elif not seen["last"] or seen["gone_before_last"]:
                    how = HOW_ABANDONED
                elif status == 200:
                    how = HOW_COMPLETE
                elif status == 206:
                    how = HOW_RANGE
                else:
                    how = HOW_REFUSED
            finally:
                serve_end(self._sid, how, seen["status"])

    _RESPONSE_CLASS = RecordedFileResponse
    return _RESPONSE_CLASS


def served_file_response(path: Any, filename: str, *, media_type: str = "application/zip") -> Any:
    """A ``FileResponse`` that records its own sending: a ``begin`` now and an ``end``, with how the
    response ended, when it is over (see ``RecordedFileResponse``)."""
    size: int | None = None
    with contextlib.suppress(OSError):
        size = os.stat(path).st_size
    sid = serve_begin(filename, size)
    return _recording_response_class()(str(path), media_type=media_type, filename=filename, sid=sid)


def _seconds_between(a: Any, b: Any) -> float | None:
    def parse(text: Any) -> datetime | None:
        try:
            return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            return None

    start, end = parse(a), parse(b)
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 1)


def _runs_view(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The runs, newest first, each with what the file says of how it ended."""
    ends = {d["id"]: d for d in lines if d["k"] == "run" and d["ev"] == "end"}
    runs = []
    for begin in (d for d in lines if d["k"] == "run" and d["ev"] == "begin"):
        end = ends.get(begin["id"])
        row: dict[str, Any] = {
            "id": begin["id"], "file": begin.get("file"), "profile": begin.get("profile"),
            "started_at": begin.get("t"), "build": begin.get("build") or None,
        }
        if begin.get("mode"):
            row["mode"] = begin["mode"]
        if end is not None:
            row.update({
                "state": end.get("outcome"), "ended_at": end.get("t"),
                "seconds": end.get("seconds"), "bytes": end.get("bytes"),
                "members": end.get("members") or {},
            })
            if end.get("error"):
                row["error"] = str(end["error"])
        elif begin["id"] in _RUNNING:
            row["state"] = "running"
            row["note"] = "the build that is running in this process; its own end is written when it finishes"
        elif begin.get("proc") == _PROCESS:
            row["state"] = "no-end"
            row["note"] = (
                "this process began the run and it is no longer running here, but no end line was "
                "written: the write failed (a full or refused drive), so how it ended is not recorded"
            )
        else:
            row["state"] = "no-end"
            row["note"] = (
                "no end line, and this is not the process that began it: the app was stopped or "
                "killed during the run, or the machine ended it, or another instance using the same "
                "data folder is running it"
            )
        runs.append(row)
    runs.reverse()
    return runs


_SERVE_NOTES = {
    HOW_RANGE: "a part of the file was asked for and sent (a range request, as a browser's resume makes): not a whole download",
    HOW_ABANDONED: "the page disconnected before the last byte was handed over",
    HOW_ERROR: "sending the file raised an error",
    HOW_HEAD: "only the headers were asked for (a HEAD request): no file was sent",
    HOW_REFUSED: "the request was answered with a refusal (see status), not with the file",
}


def _serves_view(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ends = {d["sid"]: d for d in lines if d["k"] == "serve" and d["ev"] == "end"}
    out = []
    for begin in (d for d in lines if d["k"] == "serve" and d["ev"] == "begin"):
        end = ends.get(begin["sid"])
        row: dict[str, Any] = {"file": begin.get("file"), "bytes": begin.get("bytes"), "started_at": begin.get("t")}
        if end is not None:
            how = end.get("how")
            row["how"] = how if how in _HOWS else None
            row["seconds"] = end.get("seconds")
            if isinstance(end.get("status"), int):
                row["status"] = end["status"]
            if how == HOW_COMPLETE:
                row["sent_all"] = True
            elif how in _SERVE_NOTES:
                row["sent_all"] = None if how in (HOW_RANGE, HOW_HEAD, HOW_REFUSED) else False
                row["note"] = _SERVE_NOTES[how]
            else:
                row["sent_all"] = None
                row["note"] = "the end line does not say how the response ended"
        elif begin["sid"] in _ACTIVE:
            row["sent_all"] = None
            row["note"] = "being sent now"
        else:
            row["sent_all"] = False
            row["note"] = "no end line: the app ended while the file was being sent"
        out.append(row)
    out.reverse()
    return out


def diagnostics_member(max_bytes: int = MEMBER_MAX_BYTES) -> dict[str, Any]:
    """The runs and the served files as a diagnostics member. Never raises; held to ``max_bytes``
    (the oldest rows go first, and the cut is named)."""
    try:
        lines, read_cut = _read_lines_marked()
        runs, serves = _runs_view(lines), _serves_view(lines)
    except Exception as exc:  # noqa: BLE001 - the member says it could not be read
        return {
            "schema": SCHEMA, "available": False,
            "reason": tidy_error(exc_line(exc), MEMBER_REASON_CHARS),
        }
    doc: dict[str, Any] = {
        "schema": SCHEMA, "available": True, "generated_at": _now_iso(),
        "kept": {"runs": KEEP_RUNS, "serves": KEEP_SERVES},
        "runs": runs, "serves": serves,
        "method": (
            "One line when a build begins and one when it ends, and one when the server starts "
            "sending a file and one when the response has finished (with how), in "
            "data/diagnostics/runs.jsonl; the last ten runs and the files served since the oldest. "
            "Covered: the background build's download, the numbered volumes of a split archive and "
            "the numbered keyword files; not covered: the synchronous /all route, the keyword log's "
            "scratch zip and the temporary source-quality zip. The zip being built is the newest "
            "run here and has no end yet: it appears finished in the next zip."
        ),
        "caveat": (
            "sent_all true means the server handed the last byte of a 200 over while the page was "
            "still connected. The browser saving the file is not observable from here, so a file "
            "with sent_all true can still be missing from the person's folder; a range request is "
            "a part of a file, never a whole one. A run with state no-end ended with the app or the "
            "machine, or its end could not be written; the note says which of those it can tell."
        ),
    }
    if read_cut:
        doc["file_read_from_its_end"] = (
            f"runs.jsonl is larger than the {READ_MAX_BYTES} bytes this reads (it is kept to {MAX_FILE_BYTES}, so "
            "something else wrote to it); only its newest lines are shown, and the next record rewrites it"
        )
    return _fit(doc, max_bytes)


def _fit(doc: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    """Drop the oldest rows of the larger table (never the newest run) until the document, with the
    note that names the cut, fits. A budget that cannot be met is said so, not claimed.

    Each row is measured ONCE and the document's fixed part once: re-encoding the whole document per
    dropped row was quadratic (4 s at 3,000 serves, 35 s at 9,000)."""
    runs, serves = doc["runs"], doc["serves"]
    run_sizes = [_encoded(r) + 1 for r in runs]
    serve_sizes = [_encoded(r) + 1 for r in serves]
    cut = {"runs": 0, "serves": 0}
    note = {"runs": 999_999, "serves": 999_999, "why": f"the member is held to {max_bytes} bytes; the oldest rows went first"}
    fixed = _encoded({**doc, "runs": [], "serves": [], "cut": note})
    total = fixed + sum(run_sizes) + sum(serve_sizes)
    # lists are newest first, so the last row is the oldest; the larger table gives a row first, so
    # neither table is emptied while the other is whole
    while total > max_bytes:
        can_runs, can_serves = len(runs) > 1, bool(serves)
        if can_serves and (not can_runs or sum(serve_sizes) >= sum(run_sizes)):
            total -= serve_sizes.pop()
            serves.pop()
            cut["serves"] += 1
        elif can_runs:
            total -= run_sizes.pop()
            runs.pop()
            cut["runs"] += 1
        else:
            break
    if cut["runs"] or cut["serves"]:
        doc["cut"] = {**cut, "why": note["why"]}
    exact = _encoded(doc)
    if exact <= max_bytes:
        return doc
    # the estimate counted a wider cut note than the one written, so this is only reached when the
    # budget cannot be met: say so with the exact size
    doc["cut"] = {**cut, "why": f"the member could not be held to {max_bytes} bytes: only the newest run is left"}
    doc["over_budget_bytes"] = _encoded(doc)
    return doc


def reset_for_tests() -> None:
    """Forget the in-memory state. Test-only."""
    with _LOCK:
        _ACTIVE.clear()
        _RUNNING.clear()
