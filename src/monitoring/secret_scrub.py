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
is known to print the passphrase, and this is the net beneath that. Exact match only: a
transformed copy (an escaped quote, a re-encoding) is not recognised in free text; the JSON files
:func:`scrub_file` reads are parsed first, so the secret is found in the form their READER sees, and
text it cannot parse is scrubbed for the secret as typed and as JSON writes it. The P0 check, which is
handed the same passphrase, uses :func:`scrub_text` on the exception texts it writes into its report
(``p0_validation._exception_text``), where each is made, and :func:`scrub_value` on the failure lines the
engine hands back as data (``problems``), where it copies them.

WHAT IT GUARANTEES, and the two things a naive ``str.replace`` does not:

  * No VALUE of the output contains the secret (a KEY can: the next point). A replacement can itself
    recreate the secret, either from the text beside it (a passphrase ending in ``*`` and the marker's
    own asterisks) or because the secret is a piece of the marker (a passphrase ``red`` and
    ``***redacted***``), so the result is CHECKED, and a marker that would leave the secret in is
    replaced by one that does not. The ordinary case keeps the readable ``***redacted***`` word.
  * KEYS are never touched. A key is a field name the code defines and its readers look up
    (``ok``, ``restore``, ``committed``), and the child builds none from what it is handed; a
    passphrase that is a piece of one (``ok``, ``store``, ``e``) used to rename it, which turned a
    good restore into an error. A passphrase carries nothing a record needs under its keys.
    :func:`scrub_value` walks what JSON produces (dicts, lists, tuples, strings); bytes, sets
    and other objects pass through as they are, so a caller round-trips through JSON first when
    it holds anything else (the child's ``_result_text`` does).

WHAT A HANDLER THAT HOLDS A PASSPHRASE CALLS (2026-10-06). The volume job's runners, the single-file restore's route
and the import queue catch ``Exception`` with the passphrase in scope and write what they caught as a status, a log
record or a journal line. They do it through :func:`scrubbed` (a text), :func:`traceback_text` (a traceback) and
:func:`log_failure` (a log record), each handed EVERY secret the function holds; ``tests/test_p0_validation.py``
reads the modules that hold one and fails on any other way a caught exception reaches a text.

Stdlib only, so the restore child can import it wherever it is -- after a failed boot included.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import traceback
from pathlib import Path
from typing import Any

#: What stands in for the secret -- the word ``src/safety/scrub.py`` uses for a secret-named key.
REDACTED = "***redacted***"
#: Tried in turn when ``REDACTED`` would leave the secret in the output (see the module docstring).
_FALLBACK_MARKERS: tuple[str, ...] = ("###", "~~~", "???", "@@@")


def scrub_text(text: str, needle: str) -> str:
    """``text`` with every occurrence of ``needle`` replaced, and the needle in no part of what is
    returned. An empty ``needle`` matches nothing (replacing it would put the marker between every
    character), so the text comes back as it was. Written as ``split`` and ``join``, which give the text
    ``str.replace`` would for a needle that is not empty."""
    if not needle or needle not in text:
        return text
    for marker in (REDACTED, *_FALLBACK_MARKERS):
        out = marker.join(text.split(needle))
        if needle not in out:
            return out
    # Not reachable for a passphrase a person types (it would have to contain every marker's
    # characters and be rebuilt by each replacement); here so the guarantee holds for any input.
    # Each pass shortens the text, so the loop ends.
    while needle in text:
        text = "".join(text.split(needle))
    return text


def scrub_value(value: Any, needle: str) -> Any:
    """``value`` with ``needle`` taken out of every string in it, through lists, tuples and dicts. Keys
    are kept as they are (see the module docstring); numbers, booleans and None pass through."""
    if not needle:
        return value
    if isinstance(value, str):
        return scrub_text(value, needle)
    if isinstance(value, dict):
        return {k: scrub_value(v, needle) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_value(v, needle) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub_value(v, needle) for v in value)
    return value


def scrubbed(text: str, *secrets: str | None) -> str:
    """``text`` with EVERY secret taken out, for a function that holds more than one (a restore holds the backup's
    passphrase and the corpus's) or may hold none (a missing or empty secret matches nothing).

    This is the call a handler writes a caught exception's text through where the text is made: the status an
    endpoint serves, a log line, a journal record. Every cut (``[:2000]``) comes AFTER it, never before: a cut text
    can split a secret and leave half of it behind. Each secret goes through :func:`scrub_text`, whose output holds
    none of its needle, but a LATER secret's marker can in principle rebuild an EARLIER secret out of its own
    characters and its neighbours (no typed passphrase does), so the result is checked and, if any secret is back,
    the text is WITHHELD: replaced by a marker that holds none of them. A caller that hands over only some of the
    secrets it holds gets only those taken out, which is why ``tests/test_p0_validation.py`` reads the call and
    requires every one."""
    held = [secret for secret in secrets if secret]
    for secret in held:
        text = scrub_text(text, secret)
    if not any(secret in text for secret in held):
        return text
    for marker in (REDACTED, *_FALLBACK_MARKERS):
        if not any(secret in marker for secret in held):
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
    debug bundle keeps (``src/monitoring/errorlog.py``) cuts a message at 500 characters and keeps a traceback tail
    only for a record WITH ``exc_info``, so the line that names the failure (``ValueError: ...``) leads the message
    and is what survives the cut. ``what`` is the code's own words, never built from the exception."""
    head = scrubbed("".join(traceback.format_exception_only(exc)).strip(), *secrets)[:300]
    log.log(level, "%s: %s\n%s", what, head, traceback_text(exc, *secrets))


def _scrub_cut_text(text: str, needle: str) -> str:
    """Text that does not parse as JSON (a line a killed process left unfinished, a document too deep to
    read) with the secret taken out in every form a journal writes it: as typed, and as JSON escapes it
    (a quote, a backslash or a letter outside ASCII becomes an escape sequence), with the non-ASCII
    letters escaped or not. A secret that needs no escaping has one form.

    No form is in what is returned. Each form is replaced in turn, and the marker that stands in for a
    LATER one can rebuild an EARLIER one out of its own characters and the text beside it (a secret of
    star and quote, in its escaped form followed by the closing quote of its string: ``*\\"`` + ``"``
    becomes ``***redacted***"``, which ends in the secret as typed). So the result is checked, and when
    a form is left the whole text is redone with ONE marker for every form, each of the markers in turn,
    and with the forms taken out whole if none of them stays out. An empty ``needle`` matches nothing, so the
    text comes back as it was."""
    if not needle:
        return text
    forms = tuple(dict.fromkeys((needle, json.dumps(needle)[1:-1], json.dumps(needle, ensure_ascii=False)[1:-1])))
    out = text
    for form in forms:
        out = scrub_text(out, form)
    if not any(form in out for form in forms):
        return out
    for marker in (REDACTED, *_FALLBACK_MARKERS):
        out = text
        for form in forms:
            out = marker.join(out.split(form))
        if not any(form in out for form in forms):
            return out
    # Not reachable for a passphrase a person types; here so the guarantee holds for any input. Each pass
    # shortens the text, so the loop ends.
    out = text
    while any(form in out for form in forms):
        for form in forms:
            out = "".join(out.split(form))
    return out


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
