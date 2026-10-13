"""A record the scheduler or the wiki lane keeps, serves or hands to the diagnostics bundle names the failure's CLASS and nothing
else; the words go to the ``log_failure`` line every handler already has.

The log guard (``test_no_raw_exc_info``) reads log calls. This is the stored half: it reuses the strict AST reading of
``tests/test_runs_log_sinks.py::_leaks`` (a handler's bound exception may only reach ``type()``, ``isinstance()`` or ``log_failure``
as its third argument) over the whole of ``src/scheduler``, ``src/wiki`` and the unlock module, so ``f"{exc}"``, ``repr``,
``.format``, a dict value, ``.append`` and ``exception_text`` in a record all fail. The few lines that tell the person who just
asked the failure's words (a response that is not stored) are the table below, counted like ``_BUNDLE_ALLOWED``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_runs_log_sinks import _leaks

ROOT = Path(__file__).resolve().parents[1]
#: The calls that may be handed a caught exception: the class, and the scrubbing line. ``note_error``/``log_failure_once`` are the
#: storage guard's own entry points (they log through ``log_failure`` and keep a per-path dedupe key in memory only);
#: ``refusal_text``/``is_damaged`` are the settings store's class-only refusal and its damaged-value test; ``refusal_token``/
#: ``refusal_detail``/``retry_after_of`` are the wiki walk's class (and HTTP status) classifiers, which never read the message.
CALLS = {"type", "isinstance", "log_failure", "note_error", "log_failure_once", "refusal_text", "is_damaged", "refusal_token", "refusal_detail", "retry_after_of"}
MODULES = sorted(
    p.relative_to(ROOT).as_posix()
    for entry in ("src/scheduler", "src/wiki")
    for p in (ROOT / entry).rglob("*.py")
) + ["src/api/unlock.py"]

#: Pre-existing constructs the reading reports that are not records: a non-constant ``getattr`` name on a settings object, and the
#: storage guard's choice of ``_LOG.warning`` or ``_LOG.info`` for one summary line. Matched by exact message and COUNTED, so a
#: second one in the same file is reported.
NOT_RECORDS: dict[str, dict[str, int]] = {
    "src/scheduler/settings.py": {"getattr reaches key, a way round the scan of the log calls": 1},
    "src/scheduler/storage_guard.py": {"_LOG.warning is kept as a name, a log call the scan cannot read": 1,
                                       "_LOG.info is kept as a name, a log call the scan cannot read": 1},
    "src/wiki/lane_search.py": {"getattr reaches how, a way round the scan of the log calls": 1},
}

#: Functions that take a caught exception to CLASSIFY it (a bool, an enum, an int, a class name) or to build an in-memory dedupe
#: key, and return no record text: read by name, so a new function is held to the rule. Each reason was read in the code.
CLASSIFIERS: dict[str, frozenset[str]] = {
    # ``err`` is the refresh-error DICT (class only), not an exception.
    "src/scheduler/plan_cache.py": frozenset({"_label"}),
    # disk-full / I/O classification (bool, kind) and the per-path dedupe key kept in memory; the words go to log_failure.
    "src/scheduler/storage_guard.py": frozenset({
        "_dbapi_cause", "_disk_full_detail", "_first_line_detail", "_io_error_detail", "_os_error_behind", "_text_head",
        "is_disk_full", "is_io_error", "log_failure_once", "note_error", "note_io_error",
    }),
    "src/wiki/history.py": frozenset({"retry_after_of"}),  # an int, capped
    "src/wiki/walk.py": frozenset({"_http_status", "_is_json_error", "refusal_detail", "refusal_token"}),  # constants and the class
}

#: Operator-facing text that nothing stores: the unlock answer and the start-up status the lock screen shows, a dump lookup's HTTP
#: answer, a tracker error that only reaches ``log_failure``, a malformed-query refusal. The words are scrubbed (``exception_text``);
#: a record written from the same function is not in this table.
_UNLOCK_DETAIL = "detail=exception_text("
KEPT: dict[str, dict[tuple[str, str], int]] = {
    "src/api/unlock.py": {
        # One WARNING line (the class and the scrubbed FIRST line, never the statement or a trailing line): the log, not a record.
        ("_close_after_checkpoint", 'said = exception_text(exc, passphrase, typed=False, withheld="its text is withheld")'): 1,
        ("_finish_unlock", 'set_startup("ready", "", error=exception_text(exc, typed=False))'): 1,
        ("_upkeep", 'set_startup("ready", "", error=exception_text(exc, typed=False))'): 1,
        ("_file_opens_with", _UNLOCK_DETAIL): 1,
        ("_unlock_locked", _UNLOCK_DETAIL): 1,
        (
            "encrypt_db",
            "raise HTTPException(status_code=400, detail=exception_text(exc, body.passphrase, typed=False, withheld=UNREADABLE_TEXT)) from None",
        ): 1,
    },
    "src/wiki/dumpread.py": {
        ("find_page", 'return {"found": False, "reason": "block-unreadable", "error": exception_text(exc, typed=False),'): 1,
    },
    "src/wiki/lane_search.py": {
        ("_run", "raise _TrackerUnavailable(exception_text(exc)) from None"): 1,
        ("search", 'return {**base, "total": None, "items": [], "error": "query_invalid", "detail": exception_text(exc, typed=False)}'): 1,
    },
}


def _spans(source: str, names: frozenset[str]) -> list[tuple[int, int]]:
    return [
        (n.lineno, n.end_lineno)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
    ]


def _found(rel: str, source: str) -> list[str]:
    table = {k: v for k, v in KEPT.get(rel, {}).items() if v}
    spans = _spans(source, CLASSIFIERS.get(rel, frozenset()))
    out = []
    seen: dict[str, int] = {}
    for finding in _leaks(source, only_scrubbing=CALLS, words_kept=table or None, params=True):
        line, _, message = finding.partition(": ")
        if line.isdigit() and any(lo <= int(line) <= hi for lo, hi in spans):
            continue
        if message in NOT_RECORDS.get(rel, {}):
            seen[message] = seen.get(message, 0) + 1
            if seen[message] <= NOT_RECORDS[rel][message]:
                continue
        out.append(finding)
    out += [f"0: {m!r} expected {n} time(s), found {seen.get(m, 0)}" for m, n in NOT_RECORDS.get(rel, {}).items() if seen.get(m, 0) < n]
    return out


@pytest.mark.parametrize("rel", MODULES)
def test_a_stored_or_served_record_names_the_class_and_not_the_words(rel):
    found = _found(rel, (ROOT / rel).read_text(encoding="utf-8"))
    assert found == [], f"{rel}: {found}"


def test_the_sweep_reads_the_whole_scheduler_and_wiki_trees():
    on_disk = {p.relative_to(ROOT).as_posix() for entry in ("src/scheduler", "src/wiki") for p in (ROOT / entry).rglob("*.py")}
    assert on_disk <= set(MODULES)
    assert len(on_disk) >= 20, "the directory glob found no module: the test would pass over nothing"


_HANDLER = "def f():\n    try:\n        pass\n    except Exception as exc:\n        {body}\n"


@pytest.mark.parametrize(
    "body",
    [
        "return {'reason': str(exc)}",
        "report.errors.append(str(exc))",
        "self._note('x', str(exc))",
        "msg = f'failed: {exc}'",
        "msg = f'{exc!s}'",
        "return repr(exc)",
        "return f'{type(exc).__name__}: {exc}'",
        "return '{}'.format(exc)",
        "return exception_text(exc)",
        "return {'e': exc}",
        "return str(getattr(exc, 'orig', exc))",
        "return exc.args[0]",
    ],
)
def test_the_strict_reading_flags_each_spelling_a_record_must_not_carry(body):
    assert _leaks(_HANDLER.format(body=body), only_scrubbing=CALLS), body


@pytest.mark.parametrize(
    "body",
    ["log_failure(_LOG, 'x', exc)", "return {'error': type(exc).__name__}", "return isinstance(exc, OSError)"],
)
def test_the_strict_reading_passes_the_class_and_the_log_failure_line(body):
    assert _leaks(_HANDLER.format(body=body), only_scrubbing=CALLS) == [], body
