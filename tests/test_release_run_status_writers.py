"""The two status reads of the release run that take a text it did not build (``release_run.py``: the re-index and quarantine jobs'
``status()["error"]`` in row 5, and the restore child's ``error`` in ``_restore_failure``) are trusted because every WRITER of those fields
makes the text through ``engine_text``/``record_text``. Nothing else pinned that, so a new writer (or a new job kind handed to row 5) that
stored ``str(exc)`` would reach the report and the bundle unseen. This reads the writers."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: module -> how its error field is written: ``self._error = ...`` (a job) or ``result["error"] = ...`` (the restore child).
_WRITERS = {
    "src/analytics/reindex_job.py": "self._error",
    "src/analytics/quarantine_job.py": "self._error",
    "src/monitoring/release_run_fresh_restore.py": 'result["error"]',
}
_SCRUBBING = {"engine_text", "record_text", "_error_text"}


def _target_text(node: ast.AST) -> str | None:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover
        return None


def _bad_writes(source: str, target: str) -> list[str]:
    """Every assignment to ``target`` whose value is not None, a string literal, or a call of a scrubbing helper."""
    out = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            value = n.value
        else:
            continue
        if value is None or not any(_target_text(t) == target for t in targets):
            continue
        ok = (
            (isinstance(value, ast.Constant) and (value.value is None or isinstance(value.value, str)))
            or (isinstance(value, ast.Call) and ast.unparse(value.func).split(".")[-1] in _SCRUBBING)
        )
        if not ok:
            out.append(f"{n.lineno}: {ast.unparse(n)}")
    return out


@pytest.mark.parametrize(("rel", "target"), sorted(_WRITERS.items()))
def test_every_writer_of_a_status_error_the_release_run_reads_scrubs_through_the_helpers(rel, target):
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert target in source, f"{rel} no longer writes {target}: the guard is reading nothing"
    assert _bad_writes(source, target) == []


def test_the_guard_flags_a_writer_that_stores_the_exceptions_words():
    """Negative control: each spelling of a raw text is reported; the helpers and literals are not."""
    for raw in ("str(exc)", "f'{exc}'", "repr(exc)", "exc.args[0]", "type(exc).__name__ + ': ' + str(exc)"):
        assert _bad_writes(f"def f():\n    self._error = {raw}\n", "self._error"), raw
    for fine in ("engine_text(exc)", "record_text(exc, typed=True)", "None", "'stopped'"):
        assert _bad_writes(f"def f():\n    self._error = {fine}\n", "self._error") == [], fine


def test_the_error_text_helper_of_the_restore_child_is_one_call_into_record_text():
    source = (ROOT / "src/monitoring/release_run_fresh_restore.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "_error_text")
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(returns) == 1 and isinstance(returns[0].value, ast.Call) and ast.unparse(returns[0].value.func) == "record_text"


def test_row_5_is_only_ever_handed_the_two_guarded_job_managers():
    """A new job kind given to row 5 has a status() this guard has not read: it must be added to ``_WRITERS`` first."""
    tree = ast.parse((ROOT / "src/monitoring/release_run.py").read_text(encoding="utf-8"))
    calls = sorted(
        (ast.unparse(n.args[2]), ast.unparse(n.args[3]))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_wait_job" and len(n.args) >= 4
    )
    assert calls == [("'quarantine'", "qm"), ("'reindex'", "rm")]
