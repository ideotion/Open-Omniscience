"""
Take a KNOWN secret out of text a child process said -- one helper for the parent that records
it, for the child that writes it, and for the files the child leaves behind.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS (release run, 2026-10-01). The 0.4 release run hands its backup passphrase to the
restore child, and what the child SAYS (its result file and its stderr) then enters the state
file, the report, a phase's detail and the log beside it, while what it WRITES (its run journal,
its import reports) stays on the drive in an install the run keeps. The two scrubbers the run
already had redact by KEY name -- ``_p0_scrub`` in ``src/api/diagnostics/p0.py`` on the way out of
an endpoint, ``src/safety/scrub.py`` for the run journal's own notes -- so a passphrase sitting
inside a VALUE rides straight through both; this helper is told the passphrase and takes it out
of every value. It is DEFENCE IN DEPTH, never the primary guarantee: no path on the child's side
is known to print the passphrase, and this is the net beneath that. Exact match, in the shapes the code
writes a secret in (:func:`_forms`: as typed, as an SQL literal holds it, as ``repr`` and as JSON write it); a
copy made any other way (a re-encoding, a hash, a piece of it, a text cut through it) is not recognised in free
text. The JSON files :func:`scrub_file` reads are parsed first, so the secret is found in the form their READER
sees, and text it cannot parse is scrubbed in every one of those shapes. The P0 check, which is
handed the same passphrase, uses :func:`scrub_text` on the exception texts it writes into its report
(``p0_validation._exception_text``), where each is made, and :func:`scrub_value` on the failure lines the
engine hands back as data (``problems``), where it copies them.

WHAT IT GUARANTEES, and the three things a naive ``str.replace`` does not:

  * No VALUE of the output contains the secret, in any of its shapes (a KEY can: the second point). A
    replacement can itself recreate the secret, either from the text beside it (a passphrase ending in
    ``*`` and the marker's own asterisks) or because the secret is a piece of the marker (a passphrase
    ``red`` and ``***redacted***``), so the result is CHECKED, and a marker that would leave the secret in
    is replaced by one that does not. The ordinary case keeps the readable ``***redacted***`` word.
  * KEYS are never touched. A key is a field name the code defines and its readers look up
    (``ok``, ``restore``, ``committed``), and the child builds none from what it is handed; a
    passphrase that is a piece of one (``ok``, ``store``, ``e``) used to rename it, which turned a
    good restore into an error. A passphrase carries nothing a record needs under its keys.
    :func:`scrub_value` walks what JSON produces (dicts, lists, tuples, strings); bytes, sets
    and other objects pass through as they are, so a caller round-trips through JSON first when
    it holds anything else (the child's ``_result_text`` does).
  * EVERY shape of EVERY secret goes in ONE read of the text: each stretch that is part of an occurrence of any of
    them is replaced, so a held ``pass`` inside an environment's ``pass2`` leaves no ``2`` behind and two secrets that
    overlap in the text leave no tail; and what is put in is never searched again, so one replacement is not taken
    for another's occurrence and a secret is not taken out in pieces.

WHAT A HANDLER THAT HOLDS A PASSPHRASE CALLS (2026-10-06). The volume job's runners, the single-file restore's route
and the import queue catch ``Exception`` with the passphrase in scope and write what they caught as a status, a log
record or a journal line. They do it through :func:`scrubbed` (a text), :func:`traceback_text` (a traceback) and
:func:`log_failure` (a log record), each handed EVERY secret the function holds; ``tests/test_p0_validation.py``
reads the modules that hold one and fails on any other way a caught exception reaches a text.

THE PLACES EVERY MODULE'S EXCEPTION PASSES THROUGH (2026-10-06) are handed no secret, so they scrub what the process holds
(:func:`held_passphrases`: the unlocked session's passphrase and ``OO_DB_PASSPHRASE``, read when the error happens and never
kept): the global exception handler (``src/api/main.py``), the error journal (``src/monitoring/errorlog.py``, every record
that is logged and the browser's and the responses' texts it keeps) and a failed background job's error line
(``src/jobs/background.py``). Each cuts AFTER the scrub, and when the scrub cannot run writes the exception's class and none of
its words.

Stdlib only, so the restore child can import it wherever it is -- after a failed boot included.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

#: What stands in for the secret -- the word ``src/safety/scrub.py`` uses for a secret-named key.
REDACTED = "***redacted***"
#: Tried in turn when ``REDACTED`` would leave the secret in the output (see the module docstring).
_FALLBACK_MARKERS: tuple[str, ...] = ("###", "~~~", "???", "@@@")
#: The attribute of a record :func:`log_failure` writes that holds the traceback with the secrets out of it, for the error
#: journal of the debug bundle, which keeps the tail of a traceback and cannot read one from a record with no ``exc_info``.
TRACEBACK_ATTRIBUTE = "scrubbed_traceback"


def held_passphrases() -> tuple[str, ...]:
    """Every passphrase this process holds right now, for a scrub made where a text is written (a log record, the error
    journal, a job's error line, a response): the one the unlocked session keeps (``src.database.connect.get_passphrase``)
    and the one the environment hands the app (``OO_DB_PASSPHRASE``, which stays in the environment after a lock). Read when
    asked and never kept, so a lock or an erase leaves no copy; an empty one is not one.

    The store module is looked up among the modules already imported and never imported from here: a handler runs inside
    whatever failed (an import in progress among it), and a store that was never imported holds no session passphrase. So this
    module stays importable on its own (the restore child imports it after a failed boot), and a scrub cannot wait on an import
    lock or fail on one. Whatever goes wrong reading the session's is not allowed to stop the environment's from being read."""
    session = None
    store = sys.modules.get("src.database.connect")
    if store is not None:
        try:
            session = store.get_passphrase()
        except Exception:  # noqa: BLE001 - a store that is half imported or broken holds nothing a text can be scrubbed of
            session = None
    return tuple(p for p in (session, os.environ.get("OO_DB_PASSPHRASE")) if p)


def _forms(secret: str | None) -> tuple[str, ...]:
    """The shapes ``secret`` takes in text the code writes, each once and none empty: as typed; as an SQL string
    literal holds it (every ``'`` doubled, which is how ``PRAGMA key = '...'`` and ``ATTACH '...'`` carry it, and an
    engine's error can quote the statement); as ``repr`` writes it (the text of a tuple, a list or a dict that holds
    it), on its own and inside a longer text that has both kinds of quote mark in it, where a ``'`` is written
    ``\\'``; and as JSON writes it, with the letters outside ASCII escaped or kept. The SQL shape is also written the
    ways the typed one is, because a statement an engine quotes into an error is then written again as text. A
    missing or empty secret has no shape, so it matches nothing (replacing it would put the marker between every
    character)."""
    if not secret:
        return ()
    shapes: list[str] = []
    for typed in (secret, secret.replace("'", "''")):
        shapes += [
            typed,
            repr(typed)[1:-1],
            repr("'\"" + typed)[4:-1],
            json.dumps(typed)[1:-1],
            json.dumps(typed, ensure_ascii=False)[1:-1],
        ]
    return tuple(dict.fromkeys(shape for shape in shapes if shape))


def _all_forms(secrets: tuple[str | None, ...]) -> tuple[str, ...]:
    """The shapes (:func:`_forms`) of every secret, each once. The order does not matter: :func:`_redact` takes the union."""
    return tuple(dict.fromkeys(shape for secret in secrets for shape in _forms(secret)))


def _redact(text: str, forms: tuple[str, ...], marker: str) -> str:
    """``text`` with every stretch that is part of an occurrence of any of ``forms`` replaced by ``marker``: one marker for a
    run of occurrences that overlap or hold one another (``pass`` inside ``pass2``, two shapes of one secret). The text is
    read once, left to right, so what is put in is never searched again. The result is NOT checked (:func:`_redacted`)."""
    out: list[str] = []
    done = 0
    nxt = [text.find(form) for form in forms]  # where each form next occurs, at or after ``done``; -1 when it does not
    while True:
        start = min((at for at in nxt if at != -1), default=-1)
        if start == -1:
            break
        end = start
        growing = True
        while growing:  # take in every occurrence that starts inside the stretch, and the stretch each one reaches
            growing = False
            for i, form in enumerate(forms):
                while nxt[i] != -1 and (nxt[i] < end or nxt[i] == start):
                    if nxt[i] + len(form) > end:
                        end = nxt[i] + len(form)
                        growing = True
                    nxt[i] = text.find(form, nxt[i] + 1)
        out.append(text[done:start])
        out.append(marker)
        done = end
    out.append(text[done:])
    return "".join(out)


def _redacted(text: str, forms: tuple[str, ...]) -> str | None:
    """``text`` with every form replaced by the first marker that leaves none of them in the result (the readable one, or
    a fallback when it would give one back with the text beside it), or ``None`` when no marker does. A replacement
    can recreate a form: a secret ending in ``*`` and the marker's own asterisks, a secret that is a piece of the marker."""
    for marker in (REDACTED, *_FALLBACK_MARKERS):
        out = _redact(text, forms, marker)
        if not any(form in out for form in forms):
            return out
    return None


def _stripped(text: str, forms: tuple[str, ...]) -> str:
    """The last resort: the forms taken out whole, until none is left (taking one out can join what was on either side of it
    into another). Not reachable for a passphrase a person types; here so the guarantee holds for any input. Each pass
    shortens the text, so the loop ends."""
    while any(form in text for form in forms):
        for form in forms:
            text = "".join(text.split(form))
    return text


def _scrub(text: str, forms: tuple[str, ...]) -> str:
    """``text`` as it was when it holds no form, else with them replaced (:func:`_redacted`), else with them taken out."""
    if not any(form in text for form in forms):
        return text
    out = _redacted(text, forms)
    return _stripped(text, forms) if out is None else out


def scrub_text(text: str, needle: str) -> str:
    """``text`` with the secret ``needle`` taken out in every shape :func:`_forms` lists, and none of them in what is
    returned. An empty ``needle`` matches nothing, so the text comes back as it was."""
    return _scrub(text, _forms(needle))


def scrub_value(value: Any, needle: str) -> Any:
    """``value`` with ``needle`` taken out of every string in it, through lists, tuples and dicts. Keys
    are kept as they are (see the module docstring); numbers, booleans and None pass through."""
    forms = _forms(needle)
    return _walk(value, forms) if forms else value


def _walk(value: Any, forms: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return _scrub(value, forms)
    if isinstance(value, dict):
        return {k: _walk(v, forms) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, forms) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk(v, forms) for v in value)
    return value


def scrubbed(text: str, *secrets: str | None) -> str:
    """``text`` with EVERY secret taken out, in every shape (:func:`_forms`), for a function that holds more than one (a
    restore holds the backup's passphrase and the corpus's) or may hold none (a missing or empty secret matches nothing).

    This is the call a handler writes a caught exception's text through where the text is made: the status an
    endpoint serves, a log line, a journal record. Every cut (``[:2000]``) comes AFTER it, never before: a cut text
    can split a secret and leave half of it behind. All the shapes of all the secrets are taken out in ONE read of the
    text, so a secret that holds another (a held ``pass`` and an environment's ``pass2``) leaves nothing of the longer
    one behind. A marker can in principle rebuild a secret out of its own characters and the text beside it (no typed
    passphrase does), so the result is checked, another marker is tried, and if none can be put in without giving a
    secret back the text is WITHHELD: replaced by a marker that holds none of them. A caller that hands over only some
    of the secrets it holds gets only those taken out, which is why ``tests/test_p0_validation.py`` reads the call and
    requires every one."""
    forms = _all_forms(secrets)
    if not any(form in text for form in forms):
        return text
    out = _redacted(text, forms)
    if out is not None:
        return out
    for marker in (REDACTED, *_FALLBACK_MARKERS):
        if not any(form in marker for form in forms):
            return marker
    return ""


def traceback_text(exc: BaseException, *secrets: str | None) -> str:
    """The traceback of ``exc``, its causes and contexts included, as text with every secret taken out: what
    ``logging``'s ``exc_info`` and ``Logger.exception`` write, without the message that names the secret. Scrubbed
    as ONE text, so a secret that an exception's message and its cause's message split between them is still found
    (it is in the text as written), and any cut the caller makes (``[-8000:]``) comes after."""
    return scrubbed("".join(traceback.format_exception(exc)), *secrets)


def log_failure(
    log: logging.Logger, what: str, exc: BaseException, *secrets: str | None, level: int = logging.ERROR
) -> None:
    """Log ``what`` and the failure ``exc`` with every secret taken out: the exception's own line first, then the
    traceback.

    ``Logger.exception`` and ``exc_info=`` write the exception as it made its message, which is the one thing a
    handler that holds a passphrase may not do, and the record then carries no ``exc_info``: the error log the
    debug bundle keeps (``src/monitoring/errorlog.py``) cuts a message at 500 characters, so the line that names the
    failure (``ValueError: ...``) leads the message and is what survives the cut. That log also keeps the tail of a
    traceback, which it can read only from ``exc_info``; the scrubbed traceback therefore rides on the record as
    :data:`TRACEBACK_ATTRIBUTE`, and the log takes its tail from there (the frames that say WHERE the failure
    happened are the part a developer reads the bundle for). ``what`` is the code's own words, never built from
    the exception."""
    head = scrubbed("".join(traceback.format_exception_only(exc)).strip(), *secrets)[:300]
    tb = traceback_text(exc, *secrets)
    log.log(level, "%s: %s\n%s", what, head, tb, extra={TRACEBACK_ATTRIBUTE: tb})


def _scrub_cut_text(text: str, needle: str) -> str:
    """Text that does not parse as JSON (a line a killed process left unfinished, a document too deep to read) with the
    secret taken out in every shape :func:`scrub_text` knows, among them the two a journal writes it in: as JSON escapes it
    (a quote, a backslash or a letter outside ASCII becomes an escape sequence), with the non-ASCII letters escaped or not.
    A secret that needs no escaping has one shape. An empty ``needle`` matches nothing, so the text comes back as it was.

    No shape is in what is returned, whichever of them a marker rebuilt: a secret of a star and a quote, in its escaped
    shape followed by the closing quote of its string, is ``*\\"`` + ``"``, which a marker ending in a star turns into the
    secret as typed again (:func:`_redacted` checks the result and uses the next marker; the first one that gives nothing
    back, and the shapes taken out whole when none does)."""
    return scrub_text(text, needle)


def _scrub_record(line: str, needle: str) -> str:
    """One line of a JSON-lines file: the line as it was when its values hold no secret, else the
    record with the secret taken out of them, written in the compact form the journals use (and with the
    carriage return a Windows writer ended it with, if it had one). A line that does not parse (the last
    one of a process that was killed mid-write) or is nested past what the interpreter can walk is
    scrubbed as text."""
    if not line.strip():
        return line
    try:
        record = json.loads(line)
        clean = scrub_value(record, needle)
        if clean == record:
            return line
        return json.dumps(clean, separators=(",", ":"), default=str) + ("\r" if line.endswith("\r") else "")
    except (ValueError, RecursionError):  # every step of a walk can run out of depth
        return _scrub_cut_text(line, needle)


def _scrub_document(text: str, needle: str) -> str:
    """A whole JSON document: as it was when its values hold no secret, else rewritten indented. A document
    that does not parse, or is nested past what the interpreter can walk, is scrubbed as text."""
    try:
        doc = json.loads(text)
        clean = scrub_value(doc, needle)
        return text if clean == doc else json.dumps(clean, indent=2, default=str)
    except (ValueError, RecursionError):  # every step of a walk can run out of depth
        return _scrub_cut_text(text, needle)


def scrub_file(path: Path, needle: str) -> bool:
    """Take ``needle`` out of the file at ``path``, in place, and say whether the file was rewritten.

    By what the file IS, never by a blind text replace -- which renames a key the secret is a piece of
    and cannot see the secret in the form JSON escapes it to (a quote, a backslash, a letter outside
    ASCII):

      * ``.jsonl``: one record per line. A line that parses has the secret taken out of its VALUES;
        a line without it is not touched.
      * ``.json``: one document, scrubbed the same way.
      * anything else: as text.

    The bytes of every line that is not rewritten are kept as they were (line endings included).

    THE LIMITS, stated. Text that was cut BEFORE this saw it -- a line a killed process left
    unfinished, a field its writer shortened (the run journal keeps the first 2,000 characters of an
    exception's message and the last 8,000 of its traceback) -- is matched whole or not at all, so a cut
    that falls INSIDE the secret leaves the part of it the cut kept: the start of it at the end of a
    field, the end of it at the start of a traceback. A key repeated inside one JSON object is read as
    its last value, so the secret in an earlier copy is not seen; no writer here produces one. Nothing
    known puts the passphrase in such a field; this says what the net does not catch.

    The rewrite goes to ``<name>.part`` and is moved over the original, so a failure part of the way
    leaves the old file whole -- and still holding the secret, which is the CALLER's to decide about.
    Raises ``OSError`` (the file is missing, unreadable, or cannot be replaced) or ``ValueError`` (it is
    not UTF-8 text); an empty ``needle`` rewrites nothing."""
    if not needle:
        return False
    text = path.read_bytes().decode("utf-8")
    if path.suffix == ".jsonl":
        new = "\n".join(_scrub_record(line, needle) for line in text.split("\n"))
    elif path.suffix == ".json":
        new = _scrub_document(text, needle)
    else:
        new = _scrub_cut_text(text, needle)
    if new == text:
        return False
    part = path.with_name(path.name + ".part")
    try:
        part.write_bytes(new.encode("utf-8"))
        with contextlib.suppress(OSError):
            shutil.copymode(path, part)
        os.replace(part, path)
    finally:
        with contextlib.suppress(OSError):
            part.unlink()  # the copy of a failed replace; after a good one there is nothing to remove
    return True
