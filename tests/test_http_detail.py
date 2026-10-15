"""``secret_scrub.http_detail``: the one call every HTTP ``detail`` that carries an exception goes through (R136)."""
from __future__ import annotations

import sqlite3

import pytest

from src.monitoring import secret_scrub
from src.monitoring.secret_scrub import http_detail

PASS = "Zq7!detail-key'Nm4"


@pytest.fixture
def held(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)


class _Wrapper(Exception):
    pass


def test_a_driver_error_is_its_class_with_the_prefix_and_none_of_its_words(held):
    exc = sqlite3.OperationalError(f"near \"PRAGMA key='{PASS}'\": syntax error")
    out = http_detail(exc, "Could not open the corpus: ")
    assert out.startswith("Could not open the corpus: OperationalError")
    assert PASS not in out and "PRAGMA" not in out and "syntax" not in out


def test_a_wrapper_that_quotes_a_driver_is_class_only_even_with_the_passphrase_cut_to_pieces(held):
    driver = sqlite3.OperationalError(f"unable to open database file with key {PASS} at /home/someone/corpus.db")
    try:
        try:
            raise driver
        except sqlite3.Error as inner:
            raise _Wrapper(f"restore failed: {inner}") from inner
    except _Wrapper as exc:
        out = http_detail(exc)
    assert "someone" not in out and PASS not in out and "unable to open" not in out
    assert out.startswith("_Wrapper")


def test_a_chained_driver_cause_decides_for_a_wrapper_whose_own_text_is_clean(held):
    try:
        try:
            raise sqlite3.DatabaseError(f"file is not a database {PASS}")
        except sqlite3.Error as inner:
            raise _Wrapper("the restore stopped") from inner
    except _Wrapper as exc:
        out = http_detail(exc)
    assert PASS not in out
    assert "restore stopped" not in out and "_Wrapper" in out, "the driver in the chain makes it the class only (R136), words included"


def test_any_other_exception_keeps_its_words_with_the_passphrase_taken_out(held):
    out = http_detail(ValueError(f"unknown source 'x' (typed {PASS})"), "Refused: ")
    assert out.startswith("Refused: unknown source 'x'") and PASS not in out


def test_a_secret_handed_in_is_taken_out_as_well(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    out = http_detail(ValueError("bad value other-secret-9"), "", "other-secret-9")
    assert "other-secret-9" not in out


def test_the_limit_cuts_after_the_scrub(held):
    out = http_detail(ValueError("a" * 50 + PASS + "b" * 50), "", limit=60)
    assert len(out) <= 60 and PASS not in out and PASS[:6] not in out


def test_a_unicode_error_is_a_fixed_note(held):
    try:
        "é".encode("ascii")
    except UnicodeError as exc:
        out = http_detail(exc)
    assert "é" not in out and ("offset" in out or "UnicodeEncodeError" in out)


def test_when_the_scrub_cannot_run_the_class_is_all_that_is_written(held, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no holder can be read")

    monkeypatch.setattr(secret_scrub, "record_text", boom)
    out = http_detail(ValueError(f"words {PASS}"), "p: ")
    assert out == "p: ValueError: its text is withheld" and PASS not in out


def test_the_class_only_branch_is_what_keeps_the_drivers_words_out(held, monkeypatch):
    """Fails if the per-link rule goes: with the driver test turned off, a fragment of the driver's text reaches the detail."""
    exc = sqlite3.OperationalError("table secrets_xyz has no column named pw_fragment_7")
    assert "pw_fragment_7" not in http_detail(exc)
    monkeypatch.setattr(secret_scrub, "is_driver_error", lambda e: False)
    monkeypatch.setattr(secret_scrub, "quotes_a_driver", lambda e, chain=None: False)
    assert "pw_fragment_7" in http_detail(exc), "the control: without the rule the words pass"
