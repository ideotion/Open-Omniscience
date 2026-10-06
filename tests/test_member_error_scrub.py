"""The database passphrase never reaches a member's error text in the diagnostics zip.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A member that fails writes the engine's own words into ``<name>.error.txt``, into the manifest's
``error`` and (for a deadline abort) into ``<name>.skipped-deadline.txt``, and those words can carry
the statement the engine failed on. Nothing builds a statement from the passphrase today; these tests
pin the net beneath that, at the one place the text is made (``_all_diag_err_str``):

  * the passphrase the process holds is gone from every place a member's error text enters the zip;
  * the cut to 300 characters happens AFTER the scrub, so a passphrase that straddles the cut is not
    left half-visible (a scrub of the cut text could not see it);
  * the environment's copy is scrubbed too, because an unlock that came by the API and a scripted
    start hold it in different places;
  * a scrub that cannot run withholds the text instead of keeping it (fail closed);
  * an install with no passphrase loses nothing.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from src.api.diagnostics import bundle as _bundle
from src.database import connect as _connect

SECRET = "correct horse battery staple 42"


@pytest.fixture(autouse=True)
def _no_ambient_passphrase(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr(_connect, "_passphrase", None)


def _run(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        _bundle._write_all_diagnostics_zip(members, z, db=None, profile="full")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist()}


def _boom(text):
    def member():
        raise RuntimeError(text)

    return member


def test_the_held_passphrase_is_taken_out_of_the_error_file_and_the_manifest(monkeypatch):
    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    files = _run([("a.json", _boom(f"near '{SECRET}': syntax error [SQL: PRAGMA key = '{SECRET}']"))])
    assert "a.json.error.txt" in files
    everything = "\n".join(files.values())
    assert SECRET not in everything
    assert "***redacted***" in files["a.json.error.txt"]
    entry = next(e for e in json.loads(files["manifest.json"])["members"] if e["file"] == "a.json")
    assert entry["outcome"] == "error" and SECRET not in entry["error"]


def test_the_environments_copy_is_taken_out_too(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", SECRET)
    files = _run([("a.json", _boom(f"unable to open {SECRET}"))])
    assert SECRET not in "\n".join(files.values())


def test_a_deadline_abort_text_is_scrubbed_like_an_error(monkeypatch):
    from src.database.maintenance import StatementTimeout

    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def member():
        raise StatementTimeout(f"aborted while running {SECRET}")

    files = _run([("a.json", member)])
    assert "a.json.skipped-deadline.txt" in files
    assert SECRET not in "\n".join(files.values())


def test_the_cut_comes_after_the_scrub_so_a_passphrase_across_the_cut_is_not_left_half_visible(monkeypatch):
    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    # the passphrase starts 10 characters before the 300th, so a cut first would keep its first ten
    text = "x" * 290 + SECRET + " and more text after it"
    out = _bundle._all_diag_err_str(RuntimeError(text))
    assert SECRET not in out
    assert SECRET[:10] not in out, "no piece of it survives the cut"
    assert len(out) <= 300
    assert out.startswith("x" * 290)


def test_a_scrub_that_cannot_run_withholds_the_text_instead_of_keeping_it(monkeypatch):
    import src.monitoring.secret_scrub as scrub

    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def _fails(text, needle):
        raise RuntimeError("scrub broke")

    monkeypatch.setattr(scrub, "scrub_text", _fails)
    out = _bundle._all_diag_err_str(RuntimeError(f"context {SECRET}"))
    assert SECRET not in out and "withheld" in out and "RuntimeError" in out


def test_an_install_with_no_passphrase_keeps_its_error_text_whole():
    assert _bundle._all_diag_err_str(RuntimeError("no such table: foo")) == "no such table: foo"


def test_an_exception_that_cannot_render_still_yields_a_marker(monkeypatch):
    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    class Unrenderable(Exception):
        def __str__(self):
            raise ValueError("no")

    assert _bundle._all_diag_err_str(Unrenderable()) == "<Unrenderable: unrenderable>"
