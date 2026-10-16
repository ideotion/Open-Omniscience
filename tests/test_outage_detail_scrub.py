"""``outage_detail`` builds the RETRY line a failed local-model call shows (job status, task manager): an exception handed to it is read through
``record_text``, so a database driver's words and a held passphrase never come out."""

from __future__ import annotations

import sqlite3

from src.database import connect
from src.llm.backend import outage_detail

SECRET = "hunter2" + "Zq8Lm_tbl"


def test_a_drivers_words_and_a_held_passphrase_are_not_in_the_retry_line(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", "kQ7!vLm-held-key")
    for exc in (sqlite3.OperationalError(f"no such table: {SECRET}"), ValueError("failed with kQ7!vLm-held-key inside")):
        out = outage_detail(None, exc)
        assert SECRET not in out and "kQ7!vLm-held-key" not in out, out
    assert "OperationalError" in outage_detail(None, sqlite3.OperationalError("x" * 20))


def test_an_ordinary_failure_keeps_its_words():
    assert "connection refused" in outage_detail(None, ConnectionError("connection refused by the host"))
