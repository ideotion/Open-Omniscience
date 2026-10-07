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
writes a secret in (:func:`_forms`: as typed and as an SQL literal holds it, each as ``repr`` writes it, as JSON
writes it and as the ``repr`` of its UTF-8 bytes writes it, and every one of those written again by the same writers, up to three deep); a copy made any other way (a
re-encoding, a hash, a piece of it, a text cut through it) is not recognised in free text. The JSON files :func:`scrub_file`
reads are parsed first, so the secret is found in the form their READER sees, and text it cannot parse is scrubbed in every
one of those shapes. The P0 check, which is handed the same passphrase, writes the exception texts of its report
(``p0_validation._exception_text``), where each is made, and the failure lines the engine hands back as data (``problems``),
where it copies them, through :func:`scrubbed` and :func:`scrubbed_value`, which also take out what the process holds.

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

EVERY ONE OF THOSE ALSO TAKES OUT WHAT THE PROCESS HOLDS (:func:`held_passphrases`: the unlocked session's passphrase,
``OO_DB_PASSPHRASE`` and the signing keys' ``OO_KEY_PASSPHRASE``), read when the text is written and never handed in. A handler cannot know which key a callee used: the
volume restore's handler holds the backup's passphrase and the corpus's, and the engine under it opened the store with the
session's. When what the process holds cannot be read the text is WITHHELD, never kept on the chance that it holds none.

THE PLACES EVERY MODULE'S EXCEPTION PASSES THROUGH (2026-10-06) are handed no secret at all: the global exception handler
(``src/api/main.py``), the error journal (``src/monitoring/errorlog.py``, every record that is logged and the browser's and the
responses' texts it keeps) and a failed background job's error line (``src/jobs/background.py``, which also takes out the
passphrase and password its own arguments carry). Each cuts AFTER the scrub, and when the scrub cannot run writes the
exception's class and none of its words where it knows one (a log record, ``traceback_text``, a background job's error line, the
global handler's log line) and the fixed words of :data:`UNREADABLE_TEXT` where it does not (the error journal's entries, a
route's ``detail``); the global handler's response says only that the error is internal and its text is withheld.

A SECRET UNDER THE FLOOR (2026-10-06, :data:`MIN_SECRET_CHARS`) is not taken out of a text, because taking one to three
characters out of every text would leave no record that says anything, and it is not passed through either: a text that holds
one of ITS shapes is WITHHELD whole (the helpers above write ``withheld`` where the text was: the exception's class where the
caller knows it), and a text that holds none is kept as it was. :func:`scrub_text` and :func:`scrub_value` take ONE
needle the caller hands in (the release run's passphrase, which the operator typed) and leave a needle under the floor in the text;
:func:`scrub_file` REFUSES a file that holds one (it raises, and the caller removes the file).

A KEY THE PROCESS DOES NOT HOLD (2026-10-06): the one typed into a request being served (the lock screen's, a backup's, a
mailbox's) is in no place the nets above can read until it is accepted. A route that takes one wraps its work in
:func:`scrub_and_reraise`: whatever comes out of the block is a ``RuntimeError`` carrying the scrubbed text, raised
``from None``, and the record of the failure is written with the key out of it.

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
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, TypeGuard

#: What stands in for the secret -- the word ``src/safety/scrub.py`` uses for a secret-named key.
REDACTED = "***redacted***"
#: Tried in turn when ``REDACTED`` would leave the secret in the output (see the module docstring).
_FALLBACK_MARKERS: tuple[str, ...] = ("###", "~~~", "???", "@@@")
#: The attribute of a record :func:`log_failure` writes that holds the traceback with the secrets out of it, for the error
#: journal of the debug bundle, which keeps the tail of a traceback and cannot read one from a record with no ``exc_info``.
TRACEBACK_ATTRIBUTE = "scrubbed_traceback"
#: What a text becomes when the passphrases the process holds could not be read (:func:`held_passphrases`), or when it holds a
#: secret that is under the floor (:data:`MIN_SECRET_CHARS`): with the secrets unknown, no part of it can be ruled out as one, and
#: one that cannot be taken out of the text takes the text with it. A caller that knows the exception's class writes it beside
#: "its text is withheld" instead (``withheld=``).
UNREADABLE_TEXT = "(text withheld: the passphrases this process holds could not be read, or one of them is too short to take out of a text)"

#: The fewest characters, not counting whitespace, a secret has to have to be taken out of free text. WHAT IT PROTECTS is the
#: readability of every record the nets write: a secret of one to three characters is a piece of nearly every text (one letter
#: is in every word) and a whitespace secret is the indentation of every traceback, so taking it out would leave no record that
#: says anything, which costs as much as the leak it prevents. A secret under it is therefore WITHHELD instead of taken out: a
#: text that holds one of its shapes (:func:`_short_shapes`) is not kept, in any of the helpers that hold the passphrase
#: (:func:`scrubbed` and what is built on it: the nets, the log filter, the journal), and a text that holds none is kept as it
#: was. WHAT IT COSTS: such a secret turns the records that hold it into the exception's class (or the fixed words of
#: :data:`UNREADABLE_TEXT`), and the shorter it is the more records that is (a one-letter passphrase leaves almost no word of
#: any error record), which is what the passphrase rule asks for over a record that says something. WHO HAS ONE: the app refuses
#: a passphrase under eight characters when it creates or encrypts a store (``src/api/unlock.py``) and COUNTS WHITESPACE, so a
#: short secret is an older store's passphrase (the unlock accepts any that opens the file, and holds it), eight spaces, a wrong
#: attempt typed at the lock screen, a backup's (which has no minimum of its own) or a variable set by hand. The per-needle
#: helpers :func:`scrub_text` and :func:`scrub_value` know one needle the caller hands in and leave a needle under the floor in
#: the text; :func:`scrub_file` raises for a file that holds one, so that a kept install does not keep it.
MIN_SECRET_CHARS = 4

#: How many times the carriers (:func:`_carried`) are applied to a secret's two bases. WHAT IT PROTECTS: the text this code
#: makes passes through at most two carriers (an engine's words held in an exception's arguments, which the exception's ``repr``,
#: a dict or a JSON body then carries again), and a third is the margin; the cost of the margin is at most 518 forms for one
#: secret, each a substring scan of a text of a few hundred characters to a few kilobytes. A fourth level is not covered.
CARRIER_DEPTH = 3


def held_passphrases() -> tuple[str, ...] | None:
    """Every passphrase this process holds right now, for a scrub made where a text is written (a log record, the error
    journal, a job's error line, a response): the one the unlocked session keeps (``src.database.connect._passphrase``), the
    one the environment hands the app (``OO_DB_PASSPHRASE``, which stays in the environment after a lock) and the one that wraps
    the signing keys (``OO_KEY_PASSPHRASE``, ``src/custody/signing.py``: a passphrase the process holds like the others). Read
    when asked and never kept: the shapes the scrub made of them (:func:`_held_forms`) stay in ONE cache entry, which clearing the
    session's passphrase empties (a failed unlock or create, the crypto-erase: :func:`forget_held`, called by
    ``connect.set_passphrase``), and a scrub that was in flight at that moment can put its entry back until the next scrub
    replaces it; an empty one is not one. ``None`` when what the process
    holds could not be read: a caller treats that as "withhold the text", never as "holds nothing" (every helper of this module
    does).

    The session's is read off the store module's own global WITHOUT its lock (``connect.get_passphrase`` takes it, and a log
    record written by a thread that holds it would wait on itself), and the store module is looked up among the modules already
    imported and never imported from here: a handler runs inside whatever failed (an import in progress among it), and a store
    that was never imported holds no session passphrase. So this module stays importable on its own (the restore child imports
    it after a failed boot), and a scrub cannot wait on an import lock or fail on one."""
    try:
        store = sys.modules.get("src.database.connect")
        session = None if store is None else vars(store).get("_passphrase")
        found = tuple(
            dict.fromkeys(
                p for p in (session, os.environ.get("OO_DB_PASSPHRASE"), os.environ.get("OO_KEY_PASSPHRASE")) if p
            )
        )
        return found if all(isinstance(p, str) for p in found) else None
    except Exception:  # noqa: BLE001 - what is held could not be read: the callers withhold
        return None


def _scrubbable(secret: object) -> TypeGuard[str]:
    """Whether ``secret`` is long enough to take out of free text (:data:`MIN_SECRET_CHARS`)."""
    return isinstance(secret, str) and sum(1 for ch in secret if not ch.isspace()) >= MIN_SECRET_CHARS


def _python_inner(text: str) -> str:
    """``text`` as ``repr`` writes it between single quotes: the backslash doubled, the controls escaped and each apostrophe as
    a backslash and an apostrophe. ``repr`` picks its quote by what the text holds (double quotes when there is an apostrophe and
    no double quote, and then the apostrophes are plain), so the same key reads two ways depending on the text around it: a
    carrier that is itself repr'd (an exception's ``repr``, the ``str`` of a multi-argument exception, a dict or a list holding
    the message) writes a text that holds BOTH kinds of quote single-quoted, with every apostrophe escaped. ``repr`` of the key
    alone shows the plain form; this is the other."""
    return repr(text + "'\"")[1:-4]  # both kinds present: single-quoted, the apostrophes escaped


def _bytes_inner(text: str) -> tuple[str, str]:
    """``text`` as the ``repr`` of its UTF-8 bytes writes it between single quotes (a letter outside ASCII is its ``\\xNN`` bytes), in
    the two readings :func:`_python_inner` explains. A library hands a message over as ``bytes`` (``imaplib`` and ``poplib`` keep
    the server's words and the command's as bytes), and an exception that holds one prints its ``repr``. A lone surrogate is
    written as the escape ``backslashreplace`` makes of it, never an error."""
    raw = text.encode("utf-8", "backslashreplace")
    return repr(raw)[2:-1], repr(raw + b"'\"")[2:-4]


def _carried(text: str) -> tuple[str, ...]:
    """The six ways a writer puts ``text`` inside another text: ``repr`` as it writes it alone, ``repr`` with the apostrophes
    escaped (:func:`_python_inner`), the two inner forms JSON writes it in (escaped ASCII or not) and the two the ``repr`` of its
    UTF-8 bytes writes (:func:`_bytes_inner`)."""
    return (
        repr(text)[1:-1],
        _python_inner(text),
        json.dumps(text)[1:-1],
        json.dumps(text, ensure_ascii=False)[1:-1],
        *_bytes_inner(text),
    )


def _shapes(secret: object) -> tuple[str, ...]:
    """The shapes ``secret`` takes in text the code writes, each once and none empty, WHATEVER ITS LENGTH. TWO BASES: as typed, and as an SQL string
    literal holds it (every ``'`` doubled, which is how ``PRAGMA key = '...'`` and ``ATTACH '...'`` carry it, and an engine's
    error can quote the statement). SIX CARRIERS of a base (:func:`_carried`), applied up to :data:`CARRIER_DEPTH` times: a
    statement an engine quotes into an error is written again by ``str()`` of an exception that holds it, by the ``repr`` of that
    exception, by a dict or a list that holds the message, by the JSON body that carries the dict and by the ``repr`` of the bytes
    a library keeps the message as. A secret with no quote, no backslash, no control and no letter outside ASCII has one shape;
    the most one has is 518 (2 + 12 + 72 + 432). A missing or empty one has none."""
    if not isinstance(secret, str) or not secret:
        return ()
    layer = list(dict.fromkeys((secret, secret.replace("'", "''"))))
    forms = list(layer)
    for _ in range(CARRIER_DEPTH):
        layer = list(dict.fromkeys(form for text in layer for form in _carried(text)))
        forms += layer
    return tuple(dict.fromkeys(form for form in forms if form))


def _forms(secret: str | None) -> tuple[str, ...]:
    """The shapes of ``secret`` (:func:`_shapes`) when it is long enough to be taken out of free text, else none: a secret under
    :data:`MIN_SECRET_CHARS` matches nothing here (replacing it would put the marker between every character), and
    :func:`_short_shapes` names what holds it instead."""
    return _shapes(secret) if _scrubbable(secret) else ()


def _short_shapes(secret: str | None) -> tuple[str, ...]:
    """The shapes of ``secret`` when it is UNDER the floor (:data:`MIN_SECRET_CHARS`), else none: a text that holds one of them
    cannot have the secret taken out and is withheld whole (:func:`_clean`)."""
    return () if _scrubbable(secret) else _shapes(secret)


#: The shapes of the passphrases the process held at the last read, as ``(the passphrases, the shapes of those long enough to
#: take out, the shapes of those under the floor)``: ONE entry that the next read replaces when what is held has changed and that
#: :func:`forget_held` empties on EVERY ``connect.set_passphrase`` (a new passphrase, a failed unlock or create, the
#: crypto-erase) and the next read rebuilds, because the entry holds the passphrases themselves and a core dump is in the rule.
#: WHAT IT PROTECTS is the cost of the nets: they run on every record of every logger, and building the shapes of a passphrase
#: with quotes in it is up to 518 strings. A secret a caller hands in (a typed key, a backup's) is never kept.
_HELD_FORMS: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] = ((), (), ())


def forget_held() -> None:
    """Empty the one cache entry (:data:`_HELD_FORMS`): no passphrase and no shape of one stays in this module past a change of
    the session's passphrase (``connect.set_passphrase`` calls this for every set, a clear included). Cheap, lock-free (one
    assignment) and never raises; the next scrub rebuilds what is still held."""
    global _HELD_FORMS
    _HELD_FORMS = ((), (), ())


def _held_forms(held: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    global _HELD_FORMS
    seen, forms, short = _HELD_FORMS
    if seen != held:
        forms = tuple(dict.fromkeys(form for secret in held for form in _forms(secret)))
        short = tuple(dict.fromkeys(form for secret in held for form in _short_shapes(secret)))
        _HELD_FORMS = (held, forms, short)
    return forms, short


def _forms_now(secrets: tuple[str | None, ...]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """``(the shapes to take out, the shapes that withhold a text)`` of every secret handed in AND of every passphrase the process
    holds: a secret long enough to be taken out of free text has the first, one under the floor (:data:`MIN_SECRET_CHARS`) the
    second. ``None`` when what the process holds could not be read."""
    held = held_passphrases()
    if held is None:
        return None
    forms, short = _held_forms(held)
    extra = [s for s in dict.fromkeys(secrets) if s and s not in held]
    if not extra:
        return forms, short
    return (
        tuple(dict.fromkeys((*forms, *(form for secret in extra for form in _forms(secret))))),
        tuple(dict.fromkeys((*short, *(form for secret in extra for form in _short_shapes(secret))))),
    )


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
    returned. An empty ``needle`` matches nothing, so the text comes back as it was, and so does a needle under the floor
    (:data:`MIN_SECRET_CHARS`). THE PER-NEEDLE HELPERS (this, :func:`scrub_value`, :func:`scrub_file`) know ONE needle the caller
    hands in and nothing the process holds: a handler that writes a caught exception uses :func:`scrubbed`, which does."""
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


def _clean(text: str, forms: tuple[str, ...], short: tuple[str, ...]) -> str | None:
    """``text`` with the shapes in ``forms`` taken out, as it was when it holds none, or ``None`` when it holds a shape of a
    secret that is under the floor (``short``): that secret cannot be taken out, so the text is not kept."""
    if any(form in text for form in short):
        return None
    if not any(form in text for form in forms):
        return text
    out = _redacted(text, forms)
    if out is not None:
        return out
    for marker in (REDACTED, *_FALLBACK_MARKERS):  # no marker can stand in without giving a secret back
        if not any(form in marker for form in forms):
            return marker
    return ""


def _checked(text: str, secrets: tuple[str | None, ...]) -> str | None:
    """``text`` with EVERY secret taken out, in every shape (:func:`_forms`): the ones handed in and the passphrases the
    process holds. ``None`` when that could not be done (what the process holds could not be read, the text holds a secret that
    is under the floor (:data:`MIN_SECRET_CHARS`) and so cannot have it taken out, or anything failed on the way): a caller
    never keeps a text it could not check, and what is not a text (``None``, bytes) is not one."""
    try:
        if not isinstance(text, str):
            return None
        shapes = _forms_now(secrets)
        return None if shapes is None else _clean(text, *shapes)
    except Exception:  # noqa: BLE001 - the scrub could not run: the text is not kept
        return None


def scrubbed(text: str, *secrets: str | None, withheld: str = UNREADABLE_TEXT) -> str:
    """``text`` with EVERY secret taken out, in every shape (:func:`_forms`), for a function that holds more than one (a
    restore holds the backup's passphrase and the corpus's) or may hold none (a missing or empty secret matches nothing). The
    passphrases the process holds (:func:`held_passphrases`) are taken out too, whether or not they are handed in: a handler
    cannot know which key a callee used.

    This is the call a handler writes a caught exception's text through where the text is made: the status an
    endpoint serves, a log line, a journal record. Every cut (``[:2000]``) comes AFTER it, never before: a cut text
    can split a secret and leave half of it behind. All the shapes of all the secrets are taken out in ONE read of the
    text, so a secret that holds another (a held ``pass`` and an environment's ``pass2``) leaves nothing of the longer
    one behind. A marker can in principle rebuild a secret out of its own characters and the text beside it (no typed
    passphrase does), so the result is checked, another marker is tried, and if none can be put in without giving a
    secret back the text is WITHHELD: replaced by a marker that holds none of them. A caller that hands over only some
    of the secrets it holds gets only those (and the process's) taken out, which is why ``tests/test_p0_validation.py``
    reads the call and requires every one.

    It NEVER RAISES, and it never returns a text it could not check: when the passphrases the process holds cannot be read, when
    the text holds a secret that is under the floor (:data:`MIN_SECRET_CHARS`: one to three characters cannot be taken out of a
    text without taking the text out, so it is withheld whole) or anything fails, it returns ``withheld`` (a caller that knows the
    exception's class passes ``"Name: its text is withheld"``)."""
    out = _checked(text, secrets)
    return withheld if out is None else out


def scrubbed_value(value: Any, *secrets: str | None, withheld: str = UNREADABLE_TEXT) -> Any:
    """``value`` with EVERY string in it passed through :func:`scrubbed` (the secrets handed in, the passphrases the process
    holds, a secret under the floor withholding the string that holds it), through dicts, lists and tuples. KEYS are kept as they
    are (a field name the code defines; a passphrase that is a piece of one must not rename it), numbers, booleans and ``None``
    pass through, and any other leaf (bytes, a set, a path, an exception, any object) is written as ``str()`` writes it and that
    text is checked like a string, which is what ``json.dumps(default=str)`` would have made of it: a text the leaf carried does
    not pass because it was not a ``str``. The shapes are worked out ONCE for the whole walk. A string that cannot be
    checked is replaced by ``withheld``, and a value that cannot be walked (nested past what the interpreter can read) is
    replaced by ``withheld`` itself: it never raises and never returns a text it did not check. This is the call for the
    structured results a report carries (a child's result, the engine's failure lines); :func:`scrub_value` is the per-needle
    helper for a needle the caller made itself."""
    try:
        shapes = _forms_now(secrets)
        return _walk_checked(value, shapes, withheld)
    except Exception:  # noqa: BLE001 - a value too deep to walk, or any other failure: nothing of it is kept
        return withheld


def _walk_checked(value: Any, shapes: tuple[tuple[str, ...], tuple[str, ...]] | None, withheld: str) -> Any:
    if isinstance(value, str):
        out = None if shapes is None else _clean(value, *shapes)
        return withheld if out is None else out
    if isinstance(value, dict):
        return {k: _walk_checked(v, shapes, withheld) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_checked(v, shapes, withheld) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk_checked(v, shapes, withheld) for v in value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 - a ``str()`` that raises: nothing of the object is kept
        return withheld
    out = None if shapes is None else _clean(text, *shapes)
    return withheld if out is None else out


def _class_only(exc: BaseException) -> str:
    return f"{type(exc).__name__}: its text is withheld"


UNICODE_WITHHELD = "a character the text codec cannot handle (its text is withheld: it names the character and its offset)"


def _reachable(exc: BaseException | None) -> Iterator[BaseException]:
    """``exc`` and every exception a traceback print can reach from it: its cause, its context (the walk ignores
    ``__suppress_context__``, which only stops the print and not a reader of the attribute: fail closed) and the members of an
    exception group (``traceback.format_exception`` prints each of them)."""
    work: list[BaseException] = [] if exc is None else [exc]
    seen: set[int] = set()
    while work:
        cur = work.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur
        for nxt in (cur.__cause__, cur.__context__):
            if nxt is not None:
                work.append(nxt)
        if isinstance(cur, BaseExceptionGroup):
            work.extend(cur.exceptions)


def unicode_error_in(exc: BaseException | None) -> UnicodeError | None:
    """The first ``UnicodeError`` among ``exc``, its causes, its contexts and the members of an exception group, or ``None``. Its
    text names a character and its offset, which is a piece of a key that no scrub knows (one character matches no held
    shape), so a record of any exception that has one in its chain or group carries the class and a fixed note, never the text."""
    for cur in _reachable(exc):
        if isinstance(cur, UnicodeError):
            return cur
    return None


def _unicode_withheld(exc: BaseException) -> str | None:
    """The fixed record of an exception whose chain or group holds a ``UnicodeError`` (``None`` when it holds none)."""
    bad = unicode_error_in(exc)
    return None if bad is None else f"{type(bad).__name__}: {UNICODE_WITHHELD}"


def unicode_note(exc: BaseException) -> str | None:
    """The fixed words a handler that builds its own text writes for ``exc`` when a ``UnicodeError`` is reachable from it
    (``Name: the note``), else ``None``; an exception that cannot be read is its class and none of its words. Never raises."""
    try:
        return _unicode_withheld(exc)
    except Exception:  # noqa: BLE001 - an exception that cannot be read is withheld whole
        return _class_only(exc)


def _withheld_traceback(exc: BaseException, note: str) -> str:
    """The fixed ``note`` and the frames of ``exc``'s traceback (the file, the line and the code of each: no message), so that a
    record that withholds the text still says where the error happened."""
    try:
        frames = "".join(traceback.format_tb(exc.__traceback__))
    except Exception:  # noqa: BLE001 - frames that cannot be made are not kept
        frames = ""
    return f"{note}\n{frames}" if frames else note


def unicode_withheld_traceback(exc: BaseException | None) -> str | None:
    """What a record keeps instead of the traceback of ``exc`` when a ``UnicodeError`` is reachable from it (the class, the fixed
    note and the frames), else ``None``. Never raises."""
    try:
        if exc is None:
            return None
        fixed = _unicode_withheld(exc)
        return None if fixed is None else _withheld_traceback(exc, fixed)
    except Exception:  # noqa: BLE001 - an exception that cannot be read is withheld whole
        return None if exc is None else _class_only(exc)


def _defang(exc: BaseException | None) -> None:
    """Take the character and the offset out of every ``UnicodeError`` reachable from ``exc``, in place, so that a consumer that
    reads ``__context__`` (the interpreter sets it when a handler raises another error) finds the fixed words and no piece
    of a key. Best effort, one field at a time: an error whose fields cannot be set keeps them, and the records never read them."""
    for cur in _reachable(exc):
        if not isinstance(cur, UnicodeError):
            continue
        with contextlib.suppress(Exception):
            cur.args = (UNICODE_WITHHELD,)
        with contextlib.suppress(Exception):
            cur.object = b"" if isinstance(getattr(cur, "object", None), bytes) else ""  # type: ignore[attr-defined]
        with contextlib.suppress(Exception):
            cur.start = cur.end = 0  # type: ignore[attr-defined]
        with contextlib.suppress(Exception):
            cur.reason = "withheld"  # type: ignore[attr-defined]


def exception_text(exc: BaseException, *secrets: str | None, limit: int | None = None, typed: bool = True) -> str:
    """What a handler writes for a caught exception: ``Name: its words`` (``typed=False``: the words alone, where the class is
    named elsewhere in the record) with every secret handed in AND every passphrase the process holds taken out of it
    (:func:`scrubbed`), and THEN cut to ``limit`` characters when one is given (a cut text can split a secret; the cut comes
    after). A text that cannot be checked, or whose ``str()`` raises, is the class and none of its words (``Name: its text is
    withheld``). It never raises. THE ONE CALL every handler of the release run, the P0 check and the restore child writes a
    caught exception through, so that no handler is a place that makes the text by hand; ``tests/test_p0_validation.py`` reads
    those modules for any handler that does."""
    withheld = _class_only(exc)
    try:
        fixed = _unicode_withheld(exc)
        if fixed is not None:
            return fixed if limit is None else fixed[:limit]
        text = f"{type(exc).__name__}: {exc}" if typed else f"{exc}"
    except Exception:  # noqa: BLE001 - a ``str()`` that raises: the class is all there is to write
        return withheld if limit is None else withheld[:limit]
    out = scrubbed(text, *secrets, withheld=withheld)
    return out if limit is None else out[:limit]


def traceback_text(exc: BaseException, *secrets: str | None) -> str:
    """The traceback of ``exc``, its causes and contexts included, as text with every secret taken out (:func:`scrubbed`: the
    ones handed in and the ones the process holds): what ``logging``'s ``exc_info`` and ``Logger.exception`` write, without the
    message that names the secret. Scrubbed as ONE text, so a secret that an exception's message and its cause's message split
    between them is still found (it is in the text as written), and any cut the caller makes (``[-8000:]``) comes after. When
    the scrub cannot run it is the exception's class and none of its words."""
    try:
        fixed = _unicode_withheld(exc)
        if fixed is not None:
            return _withheld_traceback(exc, fixed)
        text = "".join(traceback.format_exception(exc))
    except Exception:  # noqa: BLE001 - a traceback that cannot be made is not kept
        return _class_only(exc)
    return scrubbed(text, *secrets, withheld=_class_only(exc))


def log_failure(
    log: logging.Logger, what: str, exc: BaseException, *secrets: str | None, level: int = logging.ERROR
) -> None:
    """Log ``what`` and the failure ``exc`` with every secret taken out (the ones handed in and the ones the process holds): the
    exception's own line first, then the traceback.

    ``Logger.exception`` and ``exc_info=`` write the exception as it made its message, which is the one thing a
    handler that holds a passphrase may not do, and the record then carries no ``exc_info``: the error log the
    debug bundle keeps (``src/monitoring/errorlog.py``) cuts a message at 500 characters, so the line that names the
    failure (``ValueError: ...``) leads the message and is what survives the cut. That log also keeps the tail of a
    traceback, which it can read only from ``exc_info``; the scrubbed traceback therefore rides on the record as
    :data:`TRACEBACK_ATTRIBUTE`, and the log takes its tail from there (the frames that say WHERE the failure
    happened are the part a developer reads the bundle for). ``what`` is the code's own words, never built from
    the exception. When the scrub cannot run the record carries the exception's class and none of its words."""
    head: str | None
    tb: str | None
    try:
        fixed = _unicode_withheld(exc)
        if fixed is not None:
            head, tb = fixed, _withheld_traceback(exc, fixed)
        else:
            head = _checked("".join(traceback.format_exception_only(exc)).strip(), secrets)
            tb = _checked("".join(traceback.format_exception(exc)), secrets)
    except Exception:  # noqa: BLE001 - the text could not be made: the class says what failed
        head = tb = None
    if head is None or tb is None:
        head = tb = _class_only(exc)
    log.log(level, "%s: %s\n%s", what, head[:300], tb, extra={TRACEBACK_ATTRIBUTE: tb})


def _framework_responses() -> tuple[type[BaseException], ...]:
    """The framework's own answers (``HTTPException``: a 4xx or 5xx a route raises on purpose), found among the modules already
    imported so that this module stays stdlib-only."""
    cls = getattr(sys.modules.get("starlette.exceptions"), "HTTPException", None)
    return (cls,) if isinstance(cls, type) else ()


class scrub_and_reraise:  # noqa: N801 - read as a statement: ``with scrub_and_reraise(...)``
    """A ``with`` block that lets nothing out of it but the framework's own answers and a text with the secrets taken out.

    FOR A ROUTE THAT TAKES A KEY the process does not hold yet: the lock screen's passphrase, a backup's, a mailbox's. Every net
    that reads what the process holds (:func:`held_passphrases`) is blind to it, and the exception an engine raises under the
    route can quote the statement that carried it ("near PRAGMA key = '...'"). What escapes unconverted goes to the global
    handler, to the server's own log of the exception and to the error journal, each of which knows only what is held. So
    whatever the block raises that is an ``Exception`` and is not one of ``passthrough`` (default: the framework's
    ``HTTPException``, an answer the code wrote, whose text its writer scrubs) is written to ``log`` with the secrets out
    (:func:`log_failure`) and raised again as a ``RuntimeError`` whose text is the class and message scrubbed (:func:`scrubbed`:
    ``secrets`` and what the process holds), ``from None``, so that the exception as it made its message is in no traceback a
    consumer prints. A ``BaseException`` that is not an ``Exception`` (an interrupt, an exit, a cancellation) passes as it is.

    WHAT IT DOES NOT DO: it does not hide the original from a consumer that reads ``__context__`` itself (the interpreter sets
    it when this raises; ``from None`` only stops the traceback module printing it), and it does not scrub an answer the
    block's own code builds (``HTTPException(detail=...)``): that is the writer's, which ``tests/test_p0_validation.py`` reads."""

    def __init__(
        self,
        log: logging.Logger,
        what: str,
        *secrets: str | None,
        passthrough: tuple[type[BaseException], ...] | None = None,
    ) -> None:
        self._log = log
        self._what = what
        self._secrets = secrets
        self._passthrough = _framework_responses() if passthrough is None else tuple(passthrough)

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> Literal[False]:
        if exc is None or not isinstance(exc, Exception) or isinstance(exc, self._passthrough):
            return False
        with contextlib.suppress(Exception):  # a log that cannot be written must not replace the conversion
            log_failure(self._log, self._what, exc, *self._secrets)
        try:
            fixed = _unicode_withheld(exc)
        except Exception:  # noqa: BLE001 - an exception that cannot be read is withheld whole
            fixed = _class_only(exc)
        if fixed is not None:
            # A UnicodeError's text names a character and its offset, a piece of a key that no held shape matches: the
            # class and a fixed note are all that is kept, and the error itself (which the interpreter sets as the new
            # error's ``__context__``) is emptied of them.
            with contextlib.suppress(Exception):  # a walk that fails must not let the original out as the context
                _defang(exc)
            raise RuntimeError(fixed) from None
        try:
            text = f"{type(exc).__name__}: {exc}"
        except Exception:  # noqa: BLE001 - an exception whose text cannot be made: its class says what failed
            text = _class_only(exc)
        raise RuntimeError(scrubbed(text, *self._secrets, withheld=_class_only(exc))) from None


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

    A NEEDLE UNDER THE FLOOR (:data:`MIN_SECRET_CHARS`) cannot be taken out of a file (one to three characters are a piece of
    nearly every line), and a file that holds one of its shapes is not left as it is: this RAISES ``ValueError`` before the file
    is touched, which a caller that keeps a file the secret may not be in (the release run's kept install) answers by removing
    it. A file that holds none is left as it was.

    The rewrite goes to ``<name>.part`` and is moved over the original, so a failure part of the way
    leaves the old file whole -- and still holding the secret, which is the CALLER's to decide about.
    Raises ``OSError`` (the file is missing, unreadable, or cannot be replaced) or ``ValueError`` (it is
    not UTF-8 text, or it holds a needle too short to take out of it); an empty ``needle`` rewrites nothing."""
    if not needle:
        return False
    text = path.read_bytes().decode("utf-8")
    if any(form in text for form in _short_shapes(needle)):
        raise ValueError("the file holds a passphrase too short to take out of a text")
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
