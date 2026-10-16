"""The run journal writes the error that ended a run with the passphrase taken out (2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``runlog.run`` is a place every exception of its block passes through: it writes the class, the first 2,000 characters of the
message and the last 8,000 of the traceback into a journal file, and the debug bundle carries that file. An engine's error can
quote the statement that held a key, so the text is scrubbed of every passphrase the process holds and of every one the
caller names (``run(secrets=...)``) BEFORE it is cut, and when the scrub cannot run the class is written and none of the
words. The handler that guards the callers (``tests/test_p0_validation.py``) cannot see this one: the exception is caught
inside ``run``, not inside the function that holds the passphrase. So the second half of this file reads every function that
holds one and opens a run, and requires the secrets to be handed over, every one.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.backup import runlog
from src.monitoring import secret_scrub as S
from tests.test_p0_validation import _Held

PASS = "Qv9#k'L-72mZpx"
HELD = "env-held-Zr4!tw"
SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path / "run_logs")
    monkeypatch.setenv("OO_RUN_JOURNAL", "1")
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", None)
    runlog._CURRENT = None
    yield
    cur = runlog._CURRENT
    if cur is not None:
        cur.end("test-teardown")
    runlog._CURRENT = None


def _journal(tmp_path) -> str:
    """Every file of the run journal as one text: where a passphrase that got out would be."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted((tmp_path / "run_logs").glob("*.jsonl")))


def _error(tmp_path) -> dict:
    """The one ``error`` milestone the run wrote."""
    lines = [json.loads(line) for line in _journal(tmp_path).splitlines() if line.strip()]
    errors = [rec for rec in lines if rec.get("ev") == "error"]
    assert len(errors) == 1, errors
    return errors[0]


def _no_shape_of(secret: str, text: str) -> None:
    for shape in S._forms(secret):
        assert shape not in text, f"{shape!r} is in the journal"


def _fails(message: str, **kwargs) -> None:
    with pytest.raises(RuntimeError), runlog.run("verify", label="failing", **kwargs):
        raise RuntimeError(message)


# --------------------------------------------------------------------------- #
#  What the journal writes
# --------------------------------------------------------------------------- #
def test_the_error_that_ends_a_run_is_written_without_the_passphrase_the_caller_names(tmp_path):
    """MUTATION TARGET: ``secrets`` left out of the scrub. The words are the engine's: the statement it quotes, and the
    tuple a handler's ``args`` print."""
    sql = PASS.replace("'", "''")
    _fails(f"near \"PRAGMA key = '{sql}'\": syntax error ({(PASS,)!r})", secrets=(PASS,))
    _no_shape_of(PASS, _journal(tmp_path))
    err = _error(tmp_path)
    assert err["cls"] == "RuntimeError"
    assert err["msg"].startswith("near \"PRAGMA key = '***redacted***'\": syntax error (")
    assert S.REDACTED in err["traceback"] and "RuntimeError: near" in err["traceback"], "the frames and the line survive"


def test_it_is_written_without_the_passphrase_the_process_holds_though_the_caller_names_none(tmp_path, monkeypatch):
    """MUTATION TARGET: ``held_passphrases()`` left out. The environment's passphrase stays in it after a lock, and an
    engine's error quotes the key it was given, whoever's run it ends."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", HELD)
    _fails(f"the store refused the key {HELD}")
    assert HELD not in _journal(tmp_path)
    assert _error(tmp_path)["msg"] == f"the store refused the key {S.REDACTED}"


def test_the_message_is_scrubbed_before_it_is_cut(tmp_path):
    """MUTATION TARGET: the cut of the message before the scrub. A text cut through the passphrase keeps its start, which
    is no shape of it and which no scrub then recognises."""
    _fails("x" * 1996 + PASS, secrets=(PASS,))
    journal = _journal(tmp_path)
    assert PASS[:4] not in journal and PASS not in journal
    assert _error(tmp_path)["msg"] == "x" * 1996 + S.REDACTED[:4]


def test_the_traceback_is_scrubbed_before_it_is_cut(tmp_path):
    """MUTATION TARGET: the cut of the traceback before the scrub. The cut keeps the END of a traceback, so the part of the
    passphrase after the cut is what a cut-first journal holds: the message here runs from the passphrase to the cut."""
    cut_at = 4
    _fails(PASS + "z" * (7999 - len(PASS) + cut_at), secrets=(PASS,))
    journal = _journal(tmp_path)
    assert PASS[cut_at:] not in journal and PASS not in journal
    tail = _error(tmp_path)["traceback"]
    assert len(tail) == 8000 and tail.endswith("z\n")


def test_a_scrub_that_cannot_run_writes_the_class_and_none_of_the_words(tmp_path, monkeypatch):
    """MUTATION TARGET: ``runlog.run`` writing the message or the traceback when the scrub could not be checked. The journal never
    fails the block it observes and never writes a text it could not check: the block's own error still propagates, and the record
    is the class, a fixed line and a class-only traceback. The contract lives in ``secret_scrub``; this runs ``run`` with it broken."""

    def broken(secrets):
        raise RuntimeError("the scrub broke")

    monkeypatch.setattr(S, "_forms_now", broken)
    with pytest.raises(ValueError, match="the engine said"), runlog.run("verify", label="unscrubbable", secrets=(PASS,)):
        raise ValueError(f"the engine said {PASS}")
    assert PASS not in _journal(tmp_path)
    err = _error(tmp_path)
    assert err["cls"] == "ValueError" and err["msg"] == "ValueError: its text is withheld"
    assert "the engine said" not in err["traceback"] and "ValueError" in err["traceback"]


def _unicode_cause():
    """The ``UnicodeEncodeError`` a passphrase with a lone surrogate raises: its text names the character and its offset."""
    try:
        ("pass" + chr(0xD800) + "word").encode()
    except UnicodeEncodeError as exc:
        return exc


def _no_codec_words(tmp_path) -> None:
    journal = _journal(tmp_path)
    assert "ud800" not in journal.lower() and "position" not in journal and "surrogate" not in journal, journal


def test_an_error_that_has_a_unicode_error_behind_it_is_written_by_its_class_only(tmp_path):
    """MUTATION TARGET: ``runlog.run`` handing the text to ``scrubbed(str(exc))`` again. A ``UnicodeError``'s words name a
    character of the passphrase and its place in it, which no scrub knows; the record names the class and a fixed note."""
    cause = _unicode_cause()
    with pytest.raises(RuntimeError), runlog.run("verify", label="unicode", secrets=(PASS,)):
        raise RuntimeError("could not encode") from cause
    err = _error(tmp_path)
    assert err["msg"].startswith("UnicodeEncodeError: ") and "could not encode" not in err["msg"], err["msg"]
    _no_codec_words(tmp_path)


def test_the_same_when_the_unicode_error_is_a_member_of_an_exception_group(tmp_path):
    """MUTATION TARGET: the walk that does not enter ``ExceptionGroup`` members."""
    group = ExceptionGroup("several", [ValueError("fine"), _unicode_cause()])
    with pytest.raises(ExceptionGroup), runlog.run("verify", label="group", secrets=(PASS,)):
        raise group
    err = _error(tmp_path)
    assert err["msg"].startswith("UnicodeEncodeError: "), err["msg"]
    _no_codec_words(tmp_path)


def test_a_run_that_holds_no_passphrase_writes_the_error_as_it_was(tmp_path):
    _fails("boom")
    err = _error(tmp_path)
    assert err["cls"] == "RuntimeError" and err["msg"] == "boom"
    assert "RuntimeError: boom" in err["traceback"] and S.REDACTED not in _journal(tmp_path)


# --------------------------------------------------------------------------- #
#  The route that holds a typed passphrase and opens a run
# --------------------------------------------------------------------------- #
def test_the_single_file_restore_journals_its_failure_without_the_passphrase_it_was_typed(tmp_path, monkeypatch):
    """The one caller of ``runlog.run`` that holds a passphrase. MUTATION TARGET: ``secrets=`` left out of its call: the
    process holds no passphrase here, so the journal would carry the one that was typed."""
    from src.api import backup_v2 as r

    monkeypatch.setattr(r, "read_artifact", lambda data, passphrase=None: SimpleNamespace(corpus_path=tmp_path / "c.db"))
    monkeypatch.setattr(r, "cleanup_staging", lambda staged: None)
    monkeypatch.setattr(r, "check_memory_before_staging", lambda: None)

    def boom(*a, **k):
        raise RuntimeError(f"the merge could not open the corpus with {PASS}")

    monkeypatch.setattr(r, "run_restore", boom)
    legacy = tmp_path / "old.bak"
    legacy.write_bytes(b"read_artifact is stubbed")
    with pytest.raises(HTTPException) as caught:
        r.restore_legacy_path(str(legacy), PASS)
    assert caught.value.status_code == 500
    _no_shape_of(PASS, _journal(tmp_path))
    assert _error(tmp_path)["msg"] == f"the merge could not open the corpus with {S.REDACTED}"


# --------------------------------------------------------------------------- #
#  The guard: a run opened where a passphrase is held names every secret held
# --------------------------------------------------------------------------- #
def _is_a_run(call: ast.Call) -> bool:
    """Whether ``call`` is ``runlog.run(...)`` (or ``_runlog.run(...)`` where the module is imported under that name)."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "run"
        and isinstance(func.value, ast.Name)
        and func.value.id in ("runlog", "_runlog")
    )


def _runs_that_keep_a_secret_from_the_journal(source: str) -> tuple[list[str], list[str]]:
    """``(opened, offenders)`` for ``source``: the functions that hold a secret and open a run, and the places among them
    where the run is not handed every secret the function holds as ``secrets=(...)`` or ``secrets=[...]``: the arguments
    must be the secrets themselves (a name or an attribute of the tables in ``tests/test_p0_validation.py``), and a bare
    name, a constant, a call or an empty tuple hands over none."""
    opened: list[str] = []
    offenders: dict[int, str] = {}
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        held = _Held(fn)
        if not held.keys:
            continue
        for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and _is_a_run(n)):
            opened.append(fn.name)
            given = next((kw.value for kw in call.keywords if kw.arg == "secrets"), None)
            if not (isinstance(given, (ast.Tuple, ast.List)) and held.covered_by(list(given.elts))):
                offenders.setdefault(id(call), f"{fn.name}, line {call.lineno}")
    return opened, sorted(offenders.values())


def test_every_run_opened_where_a_passphrase_is_held_hands_the_journal_every_secret_it_holds():
    """The sites there are today are pinned by the behaviour above; the next ``runlog.run`` in a function that takes a
    passphrase is how the next leak is made, and the guard on caught exceptions cannot see it (the exception is caught
    inside ``run``). The walk reads every module of ``src/`` that names the run journal."""
    opened_anywhere: list[str] = []
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "runlog" not in text:
            continue
        opened, bad = _runs_that_keep_a_secret_from_the_journal(text)
        opened_anywhere += opened
        offenders += [f"{path.relative_to(SRC).as_posix()}: {where}" for where in bad]
    assert "restore_legacy_path" in opened_anywhere, "the walk must find the route's run, not nothing"
    assert not offenders, f"a run is opened where a passphrase is held without handing it to the journal: {offenders}"


_RUN = "with runlog.run('import', dest=p{}):\n        go()\n"


@pytest.mark.parametrize(
    ("head", "args", "flagged"),
    [
        ("def restore(path, passphrase):", ", secrets=(passphrase,)", False),
        ("def restore(path, passphrase):", ", secrets=[passphrase]", False),
        ("def restore(path, passphrase):", "", True),
        ("def restore(path, passphrase):", ", secrets=()", True),
        ("def restore(path, passphrase):", ", secrets=passphrase", True),
        ("def restore(path, passphrase):", ", secrets=('hunter2',)", True),
        ("def restore(path, passphrase):", ", secrets=(str(passphrase),)", True),
        ("def restore(path, passphrase, corpus_passphrase):", ", secrets=(passphrase,)", True),
        ("def restore(path, passphrase, corpus_passphrase):", ", secrets=(passphrase, corpus_passphrase)", False),
        ("def restore(path, passphrase, corpus_passphrase):", ", secrets=(corpus_passphrase, passphrase)", False),
        ("def restore(self, path):\n    key = self._passphrase", ", secrets=(self._passphrase,)", False),
        ("def restore(self, path):\n    key = self._passphrase", "", True),
        ("async def restore(path, passphrase):", "", True),
        ("def restore(path):", "", False),
    ],
)
def test_the_walk_flags_a_run_that_keeps_a_secret_from_the_journal(head, args, flagged):
    source = f"{head}\n    {_RUN.format(args)}"
    opened, offenders = _runs_that_keep_a_secret_from_the_journal(source)
    assert bool(offenders) is flagged, (source, offenders)
    assert (opened == []) is (head == "def restore(path):"), "a function with no secret is not looked at"


def test_the_walk_reads_a_run_opened_in_a_closure_against_the_secrets_of_the_function_around_it():
    source = (
        "def restore(path, passphrase):\n"
        "    def inner():\n"
        "        with runlog.run('import'):\n"
        "            go()\n"
        "    return inner()\n"
    )
    assert _runs_that_keep_a_secret_from_the_journal(source)[1], "the inner run is the outer function's to hand over"


# ---- the reader: a journal an older build wrote raw is checked when it is read (2026-10-16) -------------------------------------


def _older_files(tmp_path, key: str) -> str:
    """A journal and a beat file as an older build left them: the held passphrase raw, JSON-escaped and percent-encoded."""
    d = tmp_path / "run_logs"
    d.mkdir(exist_ok=True)
    from urllib.parse import quote

    rid = "20260101T000000Z-old"
    rows = [
        {"ev": "run_begin", "t": "2026-01-01T00:00:00Z", "run": "old", "note": f"key {key}"},
        {"ev": "error", "t": "2026-01-01T00:00:01Z", "message": f"near '{key}' syntax", "url": f"http://x/?k={quote(key, safe='')}"},
        {"ev": "run_end", "t": "2026-01-01T00:00:02Z", "outcome": "error"},
    ]
    (d / f"{rid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (d / f"{rid}.beat.jsonl").write_text(json.dumps({"ev": "beat", "t": "x", "detail": key}) + "\n", encoding="utf-8")
    return rid


def test_older_journal_is_checked_when_read(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", PASS)
    S.forget_held()
    rid = _older_files(tmp_path, PASS)
    out = json.dumps([runlog.raw_runs(), runlog.summarise(rid), runlog.list_runs()])

    for form in (PASS, json.dumps(PASS)[1:-1]):
        assert form not in out, form


def test_unparseable_older_journal_is_withheld_with_a_reason(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", PASS)
    S.forget_held()
    rid = _older_files(tmp_path, PASS)
    p = tmp_path / "run_logs" / f"{rid}.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + '{"ev":"error","message":"' + PASS + "\n", encoding="utf-8")  # torn
    entry = runlog.raw_runs()[rid]
    assert PASS not in json.dumps(entry)
    assert entry["milestones_not_read"]["lines_not_read"] == 1


def test_non_utf8_older_journal_is_withheld_with_a_reason(tmp_path, monkeypatch):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", PASS)
    S.forget_held()
    rid = _older_files(tmp_path, PASS)
    p = tmp_path / "run_logs" / f"{rid}.jsonl"
    p.write_bytes(p.read_bytes() + b'\xff\xfe{"ev":"x","m":"' + PASS.encode() + b'"}\n')
    entry = runlog.raw_runs()[rid]
    assert PASS not in json.dumps(entry)
    assert entry["milestones_not_read"]["file_not_utf8"] is True
    assert [r["outcome"] for r in runlog.list_runs()] == ["unreadable: not valid UTF-8"]
