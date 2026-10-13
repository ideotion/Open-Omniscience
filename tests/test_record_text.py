"""``record_text`` / ``record_traceback``: what a record (a run journal, a queue's state) keeps for a caught exception.

A database driver's exception is its class name only, on the exception itself and on every link of its chain, because engine text
can quote a fragment of a statement that no scrub of the whole string finds; any other link keeps its scrubbed words; the traceback
keeps its frames. Each test plants a passphrase FRAGMENT in the driver's text, so dropping the rule shows as the fragment in the record.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.monitoring.secret_scrub import is_driver_error, record_text, record_traceback

PASS = "correct-horse-battery-staple-1234"
FRAGMENT = "horse-battery"  # a piece of the passphrase, not the whole string: the held-passphrase scrub does not know it


def _driver_under_oserror():
    try:
        try:
            raise sqlite3.OperationalError(f'near "{FRAGMENT}": syntax error')
        except sqlite3.OperationalError as driver:
            raise OSError("the disk said no to /data/corpus.db") from driver
    except OSError as exc:
        return exc


def test_a_driver_error_chained_under_an_oserror_is_class_and_frames_with_the_fragment_absent_and_the_oserror_words_kept():
    exc = _driver_under_oserror()
    text = record_traceback(exc, PASS)
    assert FRAGMENT not in text, text
    assert "OperationalError" in text and "its text is withheld" in text
    assert "the disk said no to /data/corpus.db" in text, text  # the other link keeps its words
    assert "test_record_text.py" in text and "_driver_under_oserror" in text, "the frames are kept"
    assert FRAGMENT not in record_text(exc, PASS)
    assert record_text(exc, PASS) == "the disk said no to /data/corpus.db"


def test_the_implicit_context_link_is_read_like_the_cause():
    try:
        try:
            raise sqlite3.DatabaseError(f"file is not a database {FRAGMENT}")
        except sqlite3.DatabaseError:
            raise ValueError("could not read the backup") from None
    except ValueError as exc:
        hidden = exc
    # ``from None`` suppresses the context in a print, so the driver text is not printed; nothing leaks either way.
    assert FRAGMENT not in record_traceback(hidden, PASS)
    try:
        try:
            raise sqlite3.DatabaseError(f"file is not a database {FRAGMENT}")
        except sqlite3.DatabaseError:
            raise ValueError("could not read the backup")  # noqa: B904 - the implicit context is the case under test
    except ValueError as exc:
        implicit = exc
    text = record_traceback(implicit, PASS)
    assert FRAGMENT not in text and "DatabaseError" in text and "could not read the backup" in text, text


def test_a_driver_error_on_its_own_is_its_class_only():
    exc = sqlite3.OperationalError(f'near "{FRAGMENT}": syntax error')
    assert record_text(exc, PASS) == "OperationalError (a database driver's text is withheld)"
    assert FRAGMENT not in record_text(exc, PASS, typed=True)
    assert FRAGMENT not in record_traceback(exc, PASS)


def test_a_subclass_of_a_driver_error_raised_from_our_code_is_still_one():
    class OurLockError(sqlite3.OperationalError):
        pass

    assert is_driver_error(OurLockError(f"locked {FRAGMENT}"))
    assert FRAGMENT not in record_text(OurLockError(f"locked {FRAGMENT}"), PASS)


def test_a_sqlalchemy_wrapper_that_carries_the_statement_is_a_driver_error():
    from sqlalchemy.exc import OperationalError

    exc = OperationalError("SELECT 1 WHERE k = ?", (FRAGMENT,), sqlite3.OperationalError("x"))
    assert is_driver_error(exc)
    assert FRAGMENT not in record_text(exc, PASS) and FRAGMENT not in record_traceback(exc, PASS)


def test_any_other_exception_keeps_its_words_with_the_passphrase_taken_out():
    exc = OSError(f"cannot open /data/x with {PASS}")
    out = record_text(exc, PASS)
    assert PASS not in out and "cannot open /data/x with" in out
    assert PASS not in record_traceback(exc, PASS)


def test_it_never_raises_and_a_str_that_raises_is_the_class():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError("no")

    assert "Bad" in record_text(Bad())
    assert "Bad" in record_traceback(Bad())


@pytest.mark.parametrize("module", ["sqlite3", "sqlcipher3.dbapi2"])
def test_both_engines_hierarchies_are_recognised(module):
    mod = pytest.importorskip(module)
    assert is_driver_error(mod.OperationalError("x"))


def test_a_message_that_repeats_a_chained_drivers_text_is_withheld_whatever_its_own_class():
    try:
        try:
            raise sqlite3.OperationalError(f'near "{FRAGMENT}": syntax error')
        except sqlite3.OperationalError as driver:
            raise OSError(f"could not read: {driver}") from driver
    except OSError as exc:
        wrapped = exc
    assert FRAGMENT not in record_text(wrapped, PASS)
    assert record_text(wrapped, PASS) == "OSError (a database driver's text is withheld)"
