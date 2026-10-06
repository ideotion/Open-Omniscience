"""The engine's failure text enters a status or a diagnostics member without the passphrase."""

from __future__ import annotations

import pytest

from src.monitoring.engine_text import engine_text, without_the_passphrase

SECRET = "correct horse battery staple 7"


def test_the_passphrase_is_taken_out_of_the_whole_text_before_any_cut(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", SECRET)
    exc = RuntimeError("x" * 150 + f" [SQL: PRAGMA key='{SECRET}'] " + "y" * 50)
    text = engine_text(exc, 170)
    assert SECRET not in text
    assert SECRET[:10] not in text, "a cut that lands inside the passphrase must not keep its first half"
    assert "***redacted***" in text or len(text) <= 170


def test_the_connected_passphrase_is_scrubbed_too(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: SECRET)
    assert SECRET not in engine_text(RuntimeError(f"boom {SECRET} boom"))


def test_a_text_that_cannot_be_checked_is_withheld_not_kept(monkeypatch):
    def broken():
        raise RuntimeError("no passphrase reader")

    monkeypatch.setattr("src.database.connect.get_passphrase", broken)
    assert without_the_passphrase("anything") is None
    out = engine_text(ValueError(f"has {SECRET} in it"))
    assert SECRET not in out and "ValueError" in out and "withheld" in out


def test_an_unrenderable_exception_still_gives_a_marker():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError("no")

    assert "Bad" in engine_text(Bad())


def test_a_plain_text_without_the_secret_is_unchanged(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: None)
    assert engine_text(RuntimeError("database is locked")) == "database is locked"


@pytest.mark.parametrize(
    "path",
    ["src/monitoring/keyword_write_cost.py", "src/analytics/reindex_job.py"],
)
def test_the_two_status_texts_go_through_the_scrub(path):
    """The two places that kept raw engine text in a status or a member read it through
    ``engine_text`` now; a ``str(exc)`` coming back is caught here."""
    import re

    src = open(path, encoding="utf-8").read()
    assert "engine_text" in src
    assert not re.search(r"str\(exc\)", src), f"{path} keeps raw engine text again"
