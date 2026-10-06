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
  * every place a text of that kind enters the zip is covered, not only the three first routed:
    the debug bundle's section errors, the gate's ``estimate_error``, the chronology's ``error``, the
    reasons, a deadline abort chained under a 503, the two journal-read failures, and the error texts
    ``performance.json`` writes (``tests/test_perf_batch.py``); the two warnings for a left-over journal
    log the scrubbed text and no traceback (``tests/test_all_diagnostics_job.py``);
  * a net that lost one carrier fails a test: the passphrases between them write each form unlike every
    other.
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
    assert "could not be made free of the passphrase" in out, "true when the scrub could not run, and when a form was left"


def test_an_install_with_no_passphrase_keeps_its_error_text_whole():
    assert _bundle._all_diag_err_str(RuntimeError("no such table: foo")) == "no such table: foo"


def test_an_exception_that_cannot_render_still_yields_a_marker(monkeypatch):
    monkeypatch.setattr(_connect, "_passphrase", SECRET)

    class Unrenderable(Exception):
        def __str__(self):
            raise ValueError("no")

    assert _bundle._all_diag_err_str(Unrenderable()) == "<Unrenderable: unrenderable>"


# --------------------------------------------------------------------------- #
#  The forms (the coordinator's check: the raw string alone is not enough)
# --------------------------------------------------------------------------- #
#: An apostrophe, a backslash and a letter outside ASCII; a lone apostrophe; one character; a
#: newline; a double quote with an apostrophe (repr picks the other quote style for those); control
#: characters ``repr`` writes as ``\x07`` and JSON as ``\u0007``; and one with BOTH kinds of quote, a
#: letter outside ASCII and a control character, the only kind whose JSON-not-as-ASCII form is unlike
#: every other form (for the others it equals ``repr``'s or JSON-as-ASCII's, so deleting that carrier
#: from the net changed nothing the tests could see).
DIFFERENT = "say \"hi\" \u00e9 bell\x07 it's"
TRICKY = [
    "it's a back\\slash \u00e9", "'", "a", "line one\nline two", "say \"hi\" it's me", "bell\x07 esc\x1b it's",
    DIFFERENT,
]


def _forms_of(secret: str) -> list[str]:
    """The eight forms the real code and the real drivers write ``secret`` in, built from THEIR helpers
    (not from the function under test): ``connect._sql_literal_escape`` for the statements,
    ``repr`` of a parameter tuple for ``[parameters: ...]``, ``json.dumps`` for a JSON body; each of
    the last three of both the raw and the quote-doubled string."""
    doubled = _connect._sql_literal_escape(secret)
    return [
        secret, doubled,
        repr((secret,))[2:-3], repr((doubled,))[2:-3],
        json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1],
        json.dumps(doubled)[1:-1], json.dumps(doubled, ensure_ascii=False)[1:-1],
    ]


def _engine_text(secret: str) -> str:
    """What an engine's failure line looks like with the key in it, in each place it can be: the raw
    and the quote-doubled string, each as a statement carries it, as ``repr`` shows a parameter and as
    JSON writes it (escaped ASCII or not)."""
    doubled = _connect._sql_literal_escape(secret)
    return (
        f"near '{doubled}': syntax error [SQL: PRAGMA key = '{doubled}'] "
        f"[parameters: {(secret,)!r}] [parameters: {(doubled,)!r}] "
        f"{json.dumps({'k': secret})} {json.dumps({'k': secret}, ensure_ascii=False)} "
        f"{json.dumps({'k': doubled})} {json.dumps({'k': doubled}, ensure_ascii=False)}"
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
    assert "could not be made free of the passphrase" in out, "a form that was found again is not 'could not be checked'"


def test_the_forms_are_listed_without_duplicates_or_empties_and_a_plain_key_has_one():
    forms = _bundle._passphrase_forms("it's")
    assert len(forms) == len(set(forms)) and "" not in forms
    assert {"it's", "it''s", "it\\'s", "it\\'\\'s"} <= set(forms), "raw, doubled, and each as repr writes it with both quote kinds in the text"
    assert _bundle._passphrase_forms("plain") == ["plain"], "a passphrase with nothing to escape has one form"
    assert _bundle._passphrase_forms("") == []


def test_every_form_is_scrubbed_longest_first_over_both_secrets(monkeypatch):
    """One ordering for the held passphrase and the environment's: a form that is a piece of another
    must not go first, or it leaves the other's tail behind."""
    import src.monitoring.secret_scrub as scrub

    seen: list[str] = []
    real = scrub.scrub_text
    monkeypatch.setattr(scrub, "scrub_text", lambda text, needle: seen.append(needle) or real(text, needle))
    monkeypatch.setattr(_connect, "_passphrase", "it's")
    monkeypatch.setenv("OO_DB_PASSPHRASE", "it's 2")
    assert _bundle._without_the_passphrase("nothing here") == "nothing here"
    lengths = [len(n) for n in seen]
    assert len(seen) > 8 and lengths == sorted(lengths, reverse=True), seen


#: The carriers an engine's words pass through before they reach a record: the exception's own text, its
#: ``repr``, the ``str`` of one with two arguments, a dict or a list holding it, JSON, JSON again inside a
#: JSON body, and a ``repr`` or JSON around the other. Each is built from the standard library, not from
#: the function under test, and DECODED again to look for the key: a search of the written text can pass
#: for a text that still carries it (the same trap as the encoded file).
def _decode_exception_repr(carried: str):
    import ast

    inner = carried[len("RuntimeError("):-1]
    return ast.literal_eval(inner)


def _lit(text: str):
    import ast

    return ast.literal_eval(text)


#: ``(wrap, unwrap, levels)``: ``levels`` is how many encodings the carrier puts over the text.
CARRIERS = {
    "text": (lambda t: t, lambda c: c, 0),
    "repr-of-exception": (lambda t: repr(RuntimeError(t)), _decode_exception_repr, 1),
    "str-of-two-args": (lambda t: str(RuntimeError("engine said", t)), lambda c: _lit(c)[1], 1),
    "dict": (lambda t: str({"detail": t}), lambda c: _lit(c)["detail"], 1),
    "list": (lambda t: str([t, 1]), lambda c: _lit(c)[0], 1),
    "json": (lambda t: json.dumps({"detail": t}), lambda c: json.loads(c)["detail"], 1),
    "json-ascii-off": (lambda t: json.dumps({"detail": t}, ensure_ascii=False), lambda c: json.loads(c)["detail"], 1),
    "repr-of-repr": (lambda t: repr(repr(t)), lambda c: _lit(_lit(c)), 2),
    "json-in-json": (
        lambda t: json.dumps({"body": json.dumps({"detail": t})}),
        lambda c: json.loads(json.loads(c)["body"])["detail"], 2,
    ),
    # the stacked JSON written NOT as ASCII on the inner level, the outer one, or both: the form a
    # carrier that keeps a letter outside ASCII writes differs from the escaped one only for a key with one
    "json-in-json-inner-ascii-off": (
        lambda t: json.dumps({"body": json.dumps({"detail": t}, ensure_ascii=False)}),
        lambda c: json.loads(json.loads(c)["body"])["detail"], 2,
    ),
    "json-in-json-outer-ascii-off": (
        lambda t: json.dumps({"body": json.dumps({"detail": t})}, ensure_ascii=False),
        lambda c: json.loads(json.loads(c)["body"])["detail"], 2,
    ),
    "json-in-json-both-ascii-off": (
        lambda t: json.dumps({"body": json.dumps({"detail": t}, ensure_ascii=False)}, ensure_ascii=False),
        lambda c: json.loads(json.loads(c)["body"])["detail"], 2,
    ),
    "json-in-repr": (lambda t: repr(json.dumps({"detail": t})), lambda c: json.loads(_lit(c))["detail"], 2),
    "repr-in-json": (lambda t: json.dumps({"detail": repr(t)}), lambda c: _lit(json.loads(c)["detail"]), 2),
    # three levels, the deepest the net covers
    "repr-in-json-in-repr": (
        lambda t: repr(json.dumps({"detail": repr(t)})),
        lambda c: _lit(json.loads(_lit(c))["detail"]), 3,
    ),
    "json-in-repr-in-json": (
        lambda t: json.dumps({"body": repr(json.dumps({"detail": t}))}, ensure_ascii=False),
        lambda c: json.loads(_lit(json.loads(c)["body"]))["detail"], 3,
    ),
    "json-in-json-in-json-ascii-off": (
        lambda t: json.dumps({"a": json.dumps({"b": json.dumps({"c": t}, ensure_ascii=False)}, ensure_ascii=False)}, ensure_ascii=False),
        lambda c: json.loads(json.loads(json.loads(c)["a"])["b"])["c"], 3,
    ),
}

#: Long enough that the quote marks around a literal are not part of the key.
CARRIED = ["it's a back\\slash \u00e9", "say \"hi\" it's me", "line one\nline two", "p4ss'phrase", "bell\x07 esc\x1b it's", DIFFERENT]


@pytest.mark.parametrize("secret", CARRIED)
@pytest.mark.parametrize("carrier", sorted(CARRIERS))
def test_the_key_is_taken_out_through_every_carrier_that_holds_both_kinds_of_quote(monkeypatch, secret, carrier):
    """The key, quote-doubled as ``PRAGMA key`` carries it and raw, inside a text that is itself ``repr``'d
    or JSON-encoded (where the text holds both quote kinds ``repr`` writes each apostrophe as a backslash
    and an apostrophe), and a JSON body inside another, written as ASCII or not.

    THE ORACLE DECODES the carried text and looks for all eight forms of the key a failure line writes
    (``_forms_of``), parameter lists included, not only for the key and its doubled twin: a text that
    carries the ``[parameters: ...]`` of a failed statement is the common shape, and a net that removed
    the two plain forms and left a ``repr``'d one would otherwise pass. (A parameter list is itself one
    level, so it is added for every carrier but the deepest.)"""
    monkeypatch.setattr(_connect, "_passphrase", secret)
    doubled = _connect._sql_literal_escape(secret)
    wrap, unwrap, levels = CARRIERS[carrier]
    text = (
        f"near '{doubled}': syntax error [SQL: PRAGMA key = '{doubled}'] raw {secret} "
        "and a \"quoted\" word and it's here"
    )
    if levels <= _bundle._PASSPHRASE_CARRIER_DEPTH - 1:
        # a parameter list is itself a ``repr`` over the key: it counts as one level, so the deepest
        # carrier cannot also carry it without being a fourth (which is not claimed)
        text += f" [parameters: {(secret,)!r}] [parameters: {(doubled,)!r}]"
    out = _bundle._without_the_passphrase(wrap(text))
    assert out is not None, "the scrub ran: the text is changed, not withheld"
    decoded = unwrap(out)
    assert "syntax error" in decoded, "the text itself is kept"
    for form in _forms_of(secret):
        assert form not in decoded, f"{carrier}: the form {form!r} is still in {decoded!r}"


def test_the_carriers_the_net_covers_include_the_deepest_one_the_tests_build():
    """The deepest carrier above has as many levels as the net applies carriers, so a third level is
    tested and a fourth is not claimed."""
    assert max(levels for _w, _u, levels in CARRIERS.values()) == _bundle._PASSPHRASE_CARRIER_DEPTH


def test_one_secret_writes_the_json_not_as_ascii_form_unlike_every_other_so_deleting_that_carrier_shows():
    """A net with the JSON-not-as-ASCII carrier deleted leaves this form of ``DIFFERENT`` in the text,
    and the oracle above finds it: the tests can tell the carriers apart, which they could not while every
    secret wrote that form the way another carrier does (the mutation the coordinator's check ran)."""
    forms = set(_bundle._passphrase_forms(DIFFERENT))
    for text in (DIFFERENT, _connect._sql_literal_escape(DIFFERENT)):
        assert json.dumps(text, ensure_ascii=False)[1:-1] in forms
        assert json.dumps(text, ensure_ascii=False)[1:-1] not in {
            repr(text)[1:-1], json.dumps(text)[1:-1], _bundle._python_inner(text), text,
        }, "this form differs from every other, so no other carrier writes it for the net"


# --------------------------------------------------------------------------- #
#  Every sink, not only the three first routed
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

    # the estimator takes the memory the gate read (``estimator(db, avail)``): a stub that takes one argument
    # raises TypeError before it reaches the secret, and every assertion below would pass for that reason
    seen: dict = {}

    def boom(_db, _avail=None):
        seen["called"] = True
        # long enough that the reading's own cut (160 characters) falls INSIDE the key statement
        raise RuntimeError("y" * 130 + f" [SQL: PRAGMA key = '{SECRET}']")

    monkeypatch.setitem(_bundle._MEMBER_NEED_ESTIMATORS, name, boom)
    monkeypatch.setitem(_bundle._MEMBER_RSS_NEED_MB, name, 3322.8)
    reading: dict = {}
    with caplog.at_level(logging.DEBUG, logger=_bundle._LOG.name):
        _bundle.ram_declined_reason(name, db=object(), total_mb=4029.0, available_mb=10.0, reading=reading)
    assert seen.get("called") is True
    assert reading["estimate_error"].startswith("RuntimeError: "), reading  # the estimator's own failure, not another's
    assert "y" * 100 in reading["estimate_error"] and len(reading["estimate_error"]) <= len("RuntimeError: ") + 160
    assert SECRET not in json.dumps(reading) and SECRET[:6] not in json.dumps(reading)
    lines = [rec.getMessage() for rec in caplog.records if "need estimate" in rec.getMessage()]
    assert lines and "y" * 100 in lines[0], "the debug line is the scrubbed text, and it was written"
    assert SECRET not in caplog.text and SECRET[:6] not in caplog.text, "the debug line carried the traceback, and the traceback the key"
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
    (tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(type(tmp_path), "stat", boom)
    got = _bundle._read_previous_run_journals(tmp_path, mine)
    assert SECRET not in json.dumps(got, default=str)
    assert got["not_carried"], "the journal that could not be read is named, with a clean reason"


def test_a_journal_that_cannot_be_opened_is_named_with_a_scrubbed_reason(monkeypatch, tmp_path):
    import builtins

    monkeypatch.setattr(_connect, "_passphrase", SECRET)
    (tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl").write_text("{}\n", encoding="utf-8")
    real_open = builtins.open

    def refusing(path, *args, **kwargs):
        if str(path).endswith(".journal.jsonl"):
            raise PermissionError(f"denied {SECRET}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", refusing)
    got = _bundle._read_previous_run_journals(tmp_path, tmp_path / "own.journal.jsonl")
    assert got["carried"] and got["carried"][0]["read_error"].startswith("PermissionError: denied ")
    assert SECRET not in json.dumps(got, default=str)
