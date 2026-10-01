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
text it cannot parse is scrubbed for the secret as typed and as JSON writes it.

WHAT IT GUARANTEES, and the two things a naive ``str.replace`` does not:

  * The output never contains the secret. A replacement can itself recreate the secret, either
    from the text beside it (a passphrase ending in ``*`` and the marker's own asterisks) or
    because the secret is a piece of the marker (a passphrase ``red`` and ``***redacted***``), so
    the result is CHECKED, and a marker that would leave the secret in is replaced by one that
    does not. The ordinary case keeps the readable ``***redacted***`` word.
  * KEYS are never touched. A key is a field name the code defines and its readers look up
    (``ok``, ``restore``, ``committed``), and the child builds none from what it is handed; a
    passphrase that is a piece of one (``ok``, ``store``, ``e``) used to rename it, which turned a
    good restore into an error. A passphrase carries nothing a record needs under its keys.
    :func:`without_secret` walks what JSON produces (dicts, lists, tuples, strings); bytes, sets
    and other objects pass through as they are, so a caller round-trips through JSON first when
    it holds anything else (the child's ``_result_text`` does).

Stdlib only, so the restore child can import it wherever it is -- after a failed boot included.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

#: What stands in for the secret -- the word ``src/safety/scrub.py`` uses for a secret-named key.
REDACTED = "***redacted***"
#: Tried in turn when ``REDACTED`` would leave the secret in the output (see the module docstring).
_FALLBACK_MARKERS: tuple[str, ...] = ("###", "~~~", "???", "@@@")


def scrub_text(text: str, secret: str) -> str:
    """``text`` with every occurrence of ``secret`` replaced, and the secret in no part of what is
    returned. An empty ``secret`` is no needle (it would match between every character)."""
    if not secret or secret not in text:
        return text
    for marker in (REDACTED, *_FALLBACK_MARKERS):
        out = text.replace(secret, marker)
        if secret not in out:
            return out
    # Not reachable for a passphrase a person types (it would have to contain every marker's
    # characters and be rebuilt by each replacement); here so the guarantee holds for any input.
    # Each pass shortens the text, so the loop ends.
    while secret in text:
        text = text.replace(secret, "")
    return text


def without_secret(value: Any, secret: str) -> Any:
    """``value`` with ``secret`` taken out of every string in it, through lists, tuples and dicts. Keys
    are kept as they are (see the module docstring); numbers, booleans and None pass through."""
    if not secret:
        return value
    if isinstance(value, str):
        return scrub_text(value, secret)
    if isinstance(value, dict):
        return {k: without_secret(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [without_secret(v, secret) for v in value]
    if isinstance(value, tuple):
        return tuple(without_secret(v, secret) for v in value)
    return value


def _scrub_cut_text(text: str, secret: str) -> str:
    """Text that does not parse as JSON (a line a killed process left unfinished, a document too deep to
    read) with the secret taken out in every form a journal writes it: as typed, and as JSON escapes it
    (a quote, a backslash or a letter outside ASCII becomes an escape sequence), with the non-ASCII
    letters escaped or not. A secret that needs no escaping has one form."""
    for form in dict.fromkeys((secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1])):
        text = scrub_text(text, form)
    return text


def _scrub_record(line: str, secret: str) -> str:
    """One line of a JSON-lines file: the line as it was when its values hold no secret, else the
    record with the secret taken out of them, written in the compact form the journals use (and with the
    carriage return a Windows writer ended it with, if it had one). A line that does not parse (the last
    one of a process that was killed mid-write) or is nested past what the interpreter can walk is
    scrubbed as text."""
    if not line.strip():
        return line
    try:
        record = json.loads(line)
        clean = without_secret(record, secret)
        if clean == record:
            return line
        return json.dumps(clean, separators=(",", ":"), default=str) + ("\r" if line.endswith("\r") else "")
    except (ValueError, RecursionError):  # every step of a walk can run out of depth
        return _scrub_cut_text(line, secret)


def _scrub_document(text: str, secret: str) -> str:
    """A whole JSON document: as it was when its values hold no secret, else rewritten indented. A document
    that does not parse, or is nested past what the interpreter can walk, is scrubbed as text."""
    try:
        doc = json.loads(text)
        clean = without_secret(doc, secret)
        return text if clean == doc else json.dumps(clean, indent=2, default=str)
    except (ValueError, RecursionError):  # every step of a walk can run out of depth
        return _scrub_cut_text(text, secret)


def scrub_file(path: Path, secret: str) -> bool:
    """Take ``secret`` out of the file at ``path``, in place, and say whether the file was rewritten.

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
    not UTF-8 text); an empty ``secret`` rewrites nothing."""
    if not secret:
        return False
    text = path.read_bytes().decode("utf-8")
    if path.suffix == ".jsonl":
        new = "\n".join(_scrub_record(line, secret) for line in text.split("\n"))
    elif path.suffix == ".json":
        new = _scrub_document(text, secret)
    else:
        new = _scrub_cut_text(text, secret)
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
