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
  * an install with no passphrase loses nothing;
  * the passphrase is taken out in every FORM the code and its drivers write it in, not only as typed:
    ``PRAGMA key`` and ``ATTACH ... KEY`` carry it with its single quotes doubled, SQLAlchemy's
    ``[parameters: ...]`` shows its ``repr``, and JSON escapes it again; the longest form goes first;
  * every place a text of that kind enters the zip is covered, not only the three of the first fold:
    the debug bundle's section errors, the gate's ``estimate_error``, the chronology's ``error``, the
    reasons, a deadline abort chained under a 503, and the two journal-read failures.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi import HTTPException

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


# --------------------------------------------------------------------------- #
#  The forms (coordinator's check of the second fold: the raw string alone is not enough)
# --------------------------------------------------------------------------- #
#: An apostrophe, a backslash and a letter outside ASCII; a lone apostrophe; one character; a
#: newline; a double quote with an apostrophe (repr picks the other quote style for those).
TRICKY = ["it's a back\\slash \u00e9", "'", "a", "line one\nline two", "say \"hi\" it's me"]


def _forms_of(secret: str) -> list[str]:
    """The forms the real code and the real drivers write ``secret`` in, built from THEIR helpers
    (not from the function under test): ``connect._sql_literal_escape`` for the statements,
    ``repr`` of a parameter tuple for ``[parameters: ...]``, ``json.dumps`` for a JSON body."""
    doubled = _connect._sql_literal_escape(secret)
    return [
        secret, doubled, repr((secret,))[2:-3], json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1], json.dumps(doubled)[1:-1],
    ]


def _engine_text(secret: str) -> str:
    """What an engine's failure line looks like with the key in it, in each place it can be."""
    doubled = _connect._sql_literal_escape(secret)
    return (
        f"near '{doubled}': syntax error [SQL: PRAGMA key = '{doubled}'] "
        f"[parameters: {(secret,)!r}] {json.dumps({'k': secret})} {json.dumps({'k': secret}, ensure_ascii=False)}"
    )


@pytest.mark.parametrize("secret", TRICKY)
def test_every_form_the_passphrase_is_written_in_is_taken_out(monkeypatch, secret):
    monkeypatch.setattr(_connect, "_passphrase", secret)
    out = _bundle._all_diag_err_str(RuntimeError(_engine_text(secret)))
    for form in _forms_of(secret):
        assert form not in out, f"the form {form!r} is still in {out!r}"
    assert "withheld" not in out, "the scrub ran: the text is changed, not withheld"


@pytest.mark.parametrize("secret", TRICKY)
def test_the_environments_copy_is_taken_out_in_every_form_too(monkeypatch, secret):
    monkeypatch.setenv("OO_DB_PASSPHRASE", secret)
    out = _bundle._all_diag_err_str(RuntimeError(_engine_text(secret)))
    for form in _forms_of(secret):
        assert form not in out


def test_the_longest_form_goes_first_so_a_passphrase_inside_another_leaves_no_tail(monkeypatch):
    monkeypatch.setattr(_connect, "_passphrase", "pass")
    monkeypatch.setenv("OO_DB_PASSPHRASE", "pass2")
    out = _bundle._all_diag_err_str(RuntimeError("held pass and environment pass2 end"))
    assert "pass" not in out
    assert "***redacted***2" not in out and not out.endswith("2 end")
    assert out == "held ***redacted*** and environment ***redacted*** end"


def test_an_empty_environment_value_is_ignored_not_replaced_between_every_character(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    assert _bundle._all_diag_err_str(RuntimeError("no such table: foo")) == "no such table: foo"


def test_a_form_that_a_marker_rebuilds_withholds_the_text(monkeypatch):
    """The scrub is checked once more over every form: if a replacement left one in (the helper is
    forced to), the text is withheld, never kept."""
    import src.monitoring.secret_scrub as scrub

    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    monkeypatch.setattr(scrub, "scrub_text", lambda text, needle: text)  # removes nothing
    out = _bundle._all_diag_err_str(RuntimeError(f"context {SECRET}"))
    assert SECRET not in out and "withheld" in out


def test_the_forms_are_listed_longest_first_and_without_duplicates_or_empties():
    forms = _bundle._passphrase_forms("it's")
    assert len(forms) == len(set(forms)) and "" not in forms
    assert "it's" in forms and "it''s" in forms
    assert _bundle._passphrase_forms("plain") == ["plain"], "a passphrase with nothing to escape has one form"
    assert _bundle._passphrase_forms("") == []


# --------------------------------------------------------------------------- #
#  Every sink, not only the three of the first fold
# --------------------------------------------------------------------------- #
def test_a_deadline_abort_chained_under_a_503_is_scrubbed_like_an_error(monkeypatch):
    from src.database.maintenance import StatementTimeout

    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def member():
        try:
            raise StatementTimeout(f"aborted while running {SECRET}")
        except StatementTimeout as cause:
            raise HTTPException(status_code=503, detail="deadline") from cause

    files = _run([("a.json", member)])
    assert "a.json.skipped-deadline.txt" in files
    assert SECRET not in "\n".join(files.values())


def test_the_fixity_member_reason_is_scrubbed(monkeypatch):
    import src.api.integrity as integrity

    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def boom(**_kw):
        raise RuntimeError(f"[SQL: PRAGMA key = '{SECRET}']")

    monkeypatch.setattr(integrity, "get_fixity", boom)
    got = _bundle._fixity_bundle_member(db=None)
    assert got["available"] is False and SECRET not in json.dumps(got)


def test_the_corpus_counters_reason_is_scrubbed(monkeypatch):
    import contextlib

    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    monkeypatch.setattr(_bundle, "statement_deadline", lambda *_a, **_k: contextlib.nullcontext())

    class Db:
        def query(self, *_a, **_k):
            raise RuntimeError(f"no key {SECRET}")

    got = _bundle._corpus_counters_safe(Db())
    assert got["available"] is False and SECRET not in json.dumps(got)


def test_the_coverage_report_reason_is_scrubbed(monkeypatch):
    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def boom(*_a, **_k):
        raise RuntimeError(f"cannot read {SECRET}")

    monkeypatch.setattr(_bundle, "diagnostics_source", boom, raising=False)
    import re

    monkeypatch.setattr(re, "findall", boom)
    got = _bundle._diagnostics_coverage_report()
    assert got["available"] is False and SECRET not in json.dumps(got)


def test_the_gates_estimate_error_is_scrubbed_and_so_is_its_log_line(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    name = "keyword-log-digest.json"

    def boom(_db):
        raise RuntimeError(f"[SQL: PRAGMA key = '{SECRET}']")

    monkeypatch.setitem(_bundle._MEMBER_NEED_ESTIMATORS, name, boom)
    monkeypatch.setitem(_bundle._MEMBER_RSS_NEED_MB, name, 3322.8)
    reading: dict = {}
    with caplog.at_level(logging.DEBUG, logger=_bundle._LOG.name):
        _bundle.ram_declined_reason(name, db=object(), total_mb=4029.0, available_mb=10.0, reading=reading)
    assert reading.get("estimate_error"), "the estimator failed, so the reading names the failure"
    assert SECRET not in json.dumps(reading)
    assert SECRET not in caplog.text, "the debug line carried the traceback, and the traceback the key"
    assert all(rec.exc_info is None for rec in caplog.records if "need estimate" in rec.getMessage())


def test_the_chronology_member_error_is_scrubbed(monkeypatch):
    import src.monitoring.chronology as chronology

    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def boom(**_kw):
        raise RuntimeError(f"[SQL: PRAGMA key = '{SECRET}']")

    monkeypatch.setattr(chronology, "chronology", boom)
    got = _bundle._chronology_member()
    assert got["available"] is False and SECRET not in json.dumps(got)
    assert got["error"].startswith("RuntimeError: ")


def test_the_debug_bundles_section_errors_are_scrubbed(monkeypatch):
    from fastapi.testclient import TestClient

    import src.monitoring.latency as latency
    from src.api.main import app

    def boom(*_a, **_k):
        raise RuntimeError(f"near '{SECRET}': syntax error")

    monkeypatch.setattr(latency, "summary", boom)  # -> the request_latency section

    def ollama_boom(self):
        raise RuntimeError(f"cannot reach the model with {SECRET}")

    import src.llm.ollama as ollama

    monkeypatch.setattr(ollama.OllamaClient, "is_available", ollama_boom)  # -> runtime.llm.error
    with TestClient(app) as client:
        # held only once the app is up, so the boot itself is not asked to unlock with it
        monkeypatch.setattr(_connect, "_passphrase", SECRET)
        response = client.get("/api/diagnostics/debug-bundle")
    assert response.status_code == 200
    assert SECRET not in response.text
    section = response.json()["data"]["request_latency"]
    assert "error" in section and "syntax error" in section["error"], "the text is changed, not dropped"
    assert response.json()["data"]["runtime"]["llm"]["error"].startswith("cannot reach the model")


def test_the_journal_read_failures_are_scrubbed(monkeypatch, tmp_path):
    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    def boom(self):
        raise PermissionError(f"denied {SECRET}")

    mine = tmp_path / "own.journal.jsonl"
    (tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl").write_text("{}\n")
    monkeypatch.setattr(type(tmp_path), "stat", boom)
    got = _bundle._read_previous_run_journals(tmp_path, mine)
    assert SECRET not in json.dumps(got, default=str)
    assert got["not_carried"], "the journal that could not be read is named, with a clean reason"


def test_a_journal_that_cannot_be_opened_is_named_with_a_scrubbed_reason(monkeypatch, tmp_path):
    import builtins

    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    (tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl").write_text("{}\n")
    real_open = builtins.open

    def refusing(path, *args, **kwargs):
        if str(path).endswith(".journal.jsonl"):
            raise PermissionError(f"denied {SECRET}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", refusing)
    got = _bundle._read_previous_run_journals(tmp_path, tmp_path / "own.journal.jsonl")
    assert got["carried"] and got["carried"][0]["read_error"].startswith("PermissionError: denied ")
    assert SECRET not in json.dumps(got, default=str)

