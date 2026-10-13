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

from tests.test_runs_log_sinks import _enclosing_function, _leaks

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
#: key, and return no record text. Allowed LINE BY LINE (function plus exact line text, counted), never by function name, so a new
#: line in one of them, or a same-named method elsewhere, is read like any other code. Each line was read in the code.
CLASSIFIED: dict[str, dict[tuple[str, str], int]] = {
    "src/scheduler/plan_cache.py": {
        ('PlanPreviewCache._label', 'if err is not None:'): 1,
        ('PlanPreviewCache._label', 'out["refresh_error"] = err'): 1,
    },
    "src/scheduler/storage_guard.py": {
        ('_text_head', 'return str(exc).split("\\n[SQL:", 1)[0]'): 1,
        ('is_disk_full', 'cur = exc'): 1,
        ('_dbapi_cause', 'cur = exc'): 1,
        ('is_io_error', 'cur = exc'): 1,
        ('_os_error_behind', 'cur = exc'): 1,
        ('_first_line_detail', 'if exc is None:'): 1,
        ('_first_line_detail', 'orig = _dbapi_cause(exc)'): 1,
        ('_first_line_detail', 'os_error = _os_error_behind(exc)'): 1,
        ('_first_line_detail', 'shown, text = exc, quoted'): 1,
        ('_first_line_detail', 'quoted = _text_head(exc).rpartition("Original exception was: ")[2]'): 1,
        ('_io_error_detail', 'return _first_line_detail(exc)'): 1,
        ('_disk_full_detail', 'return _first_line_detail(exc, quote_head=True)'): 1,
        ('StorageGuard.note_error', 'if is_disk_full(exc):'): 1,
        ('StorageGuard.note_error', 'return self.note_io_error(exc, where)'): 1,
        ('StorageGuard.note_error', 'self.note_disk_full(f"{where + \': \' if where else \'\'}{_disk_full_detail(exc)}")'): 1,
        ('StorageGuard.note_io_error', 'if not is_io_error(exc):'): 1,
        ('StorageGuard.note_io_error', '"detail": _io_error_detail(exc),'): 1,
        ('StorageGuard.log_failure_once', 'first = (str(exc).splitlines() or [""])[0][:80]'): 1,
    },
    "src/wiki/history.py": {
        ('retry_after_of', 'response = getattr(exc, "response", None)'): 1,
    },
    "src/wiki/walk.py": {
        ('_http_status', 'status = getattr(getattr(exc, "response", None), "status_code", None)'): 1,
        ('_is_json_error', 'return isinstance(exc, json.JSONDecodeError) or (hasattr(exc, "doc") and hasattr(exc, "pos"))'): 2,
        ('refusal_token', 'status = _http_status(exc)'): 1,
        ('refusal_token', 'if isinstance(exc, ValueError) and (not isinstance(exc, OSError) or _is_json_error(exc)):'): 1,
        ('refusal_token', 'raise exc'): 1,
        ('refusal_detail', 'status = _http_status(exc)'): 1,
    },
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
        ("_finish_unlock._upkeep", 'set_startup("ready", "", error=exception_text(exc, typed=False))'): 1,
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
        ("_TrackerReader._run", "raise _TrackerUnavailable(exception_text(exc)) from None"): 1,
        ("search", 'return {**base, "total": None, "items": [], "error": "query_invalid", "detail": exception_text(exc, typed=False)}'): 1,
    },
}


def _found(rel: str, source: str) -> list[str]:
    table = {k: v for k, v in KEPT.get(rel, {}).items() if v}
    lines = source.splitlines()
    tree = ast.parse(source)
    parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    nodes_by_line = {}
    for n in ast.walk(tree):
        if hasattr(n, 'lineno'):
            nodes_by_line.setdefault(n.lineno, n)
    allowed = dict(CLASSIFIED.get(rel, {}))
    out = []
    seen: dict[str, int] = {}
    for finding in _leaks(source, only_scrubbing=CALLS, words_kept=table or None, params=True):
        line, _, message = finding.partition(": ")
        if line.isdigit():
            key = (_enclosing_function(nodes_by_line[int(line)], parent) if int(line) in nodes_by_line else "", lines[int(line) - 1].strip())
            if allowed.get(key, 0) > 0:
                allowed[key] -= 1
                continue
        if message in NOT_RECORDS.get(rel, {}):
            seen[message] = seen.get(message, 0) + 1
            if seen[message] <= NOT_RECORDS[rel][message]:
                continue
        out.append(finding)
    out += [f"0: {m!r} expected {n} time(s), found {seen.get(m, 0)}" for m, n in NOT_RECORDS.get(rel, {}).items() if seen.get(m, 0) < n]
    out += [f"0: classifier line {k!r} expected but not found ({n} left)" for k, n in allowed.items() if n > 0]
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
