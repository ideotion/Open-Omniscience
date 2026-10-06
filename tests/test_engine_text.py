"""The engine's failure text enters a status or a diagnostics member without the passphrase."""

from __future__ import annotations

import ast
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

from src.monitoring import engine_text as et
from src.monitoring.engine_text import engine_text

SECRET = "correct horse battery staple 7"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", SECRET)
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: None)


def test_the_passphrase_is_taken_out_of_the_whole_text_before_the_cut():
    exc = RuntimeError("x" * 150 + f" [SQL: PRAGMA key='{SECRET}'] " + "y" * 50)
    whole = str(exc)
    limit = whole.index(SECRET) + 10  # the cut falls ten characters INSIDE the secret
    out = engine_text(exc, limit)
    assert SECRET not in out
    assert SECRET[:10] not in out, "a cut made before the scrub would keep the first ten characters"


def test_the_connected_passphrase_is_scrubbed_too(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: SECRET)
    assert SECRET not in engine_text(RuntimeError(f"boom {SECRET} boom"))


def test_an_empty_passphrase_in_the_environment_changes_nothing(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    assert engine_text(RuntimeError("database is locked")) == "database is locked"


def test_a_text_that_cannot_be_checked_is_withheld_not_kept(monkeypatch):
    def broken():
        raise RuntimeError("no passphrase reader")

    monkeypatch.setattr("src.database.connect.get_passphrase", broken)
    assert et._without_the_passphrase("anything") is None
    out = engine_text(ValueError(f"has {SECRET} in it"))
    assert SECRET not in out and "ValueError" in out and "withheld" in out


def test_an_unrenderable_exception_still_gives_a_marker():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError("no")

    assert "Bad" in engine_text(Bad())


def test_a_plain_text_without_the_secret_is_unchanged():
    assert engine_text(RuntimeError("database is locked")) == "database is locked"


# ---- through the sinks: the secret in an engine's words never reaches the record ----------


def test_the_write_cost_member_does_not_carry_the_secret(monkeypatch):
    from src.database.maintenance import StatementTimeout
    from src.monitoring import keyword_write_cost as kwc

    @contextmanager
    def _abort(session, seconds=None):
        raise StatementTimeout(f"slow disk [SQL: PRAGMA key='{SECRET}']")
        yield  # pragma: no cover

    monkeypatch.setattr(kwc, "statement_deadline", _abort)
    out = kwc.keyword_write_cost(_empty_session())
    assert out["available"] is False
    assert "slow disk" in out["reason"] and SECRET not in repr(out)


def test_the_write_rate_reason_does_not_carry_the_secret(monkeypatch):
    from datetime import UTC, datetime

    from src.monitoring import keyword_write_cost as kwc

    class _S:
        def execute(self, *_a, **_k):
            raise RuntimeError(f"disk image is malformed [parameters: ('{SECRET}',)]")

    out = kwc._write_rate(_S(), datetime.now(UTC))
    assert out and all(SECRET not in repr(v) for v in out.values())
    assert any("unreadable" in v.get("reason", "") for v in out.values())


def test_a_failing_reindex_job_keeps_no_secret_in_its_error(tmp_path, monkeypatch):
    from src.analytics.reindex_job import ReindexJobManager

    def _boom(*_a, **_k):
        raise RuntimeError(f"unable to open database [SQL: PRAGMA key='{SECRET}']")

    monkeypatch.setattr("src.analytics.store.reindex_all_batch", _boom)
    mgr = ReindexJobManager(state_path=tmp_path / "state.json")
    sess = _empty_factory()
    mgr.start(_session_factory=sess, _extractor=object())
    t = mgr._thread
    assert isinstance(t, threading.Thread)
    t.join(10)
    st = mgr.status()
    assert st["state"] == "error" and "unable to open database" in st["error"]
    assert SECRET not in repr(st) and SECRET not in (tmp_path / "state.json").read_text(encoding="utf-8")


def _no_secret_anywhere(caplog, *values):
    assert SECRET not in caplog.text, "a log line (or its traceback) carries the passphrase"
    for v in values:
        assert SECRET not in repr(v)


def test_the_backlog_reads_keep_the_secret_out_of_their_reason_and_their_log(monkeypatch, caplog):
    import logging

    from src.backup import merge

    caplog.set_level(logging.DEBUG)

    class _Boom:
        def __enter__(self):
            raise RuntimeError(f"cannot read [SQL: PRAGMA key='{SECRET}']")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("src.database.session.session_scope", lambda *a, **k: _Boom())
    out = merge.reindex_backlog()
    assert out["available"] is False and "cannot read" in out["reason"]
    assert merge.pending_reindex_batches() == []

    def _identity_fails():
        raise RuntimeError(f"no identity [SQL: PRAGMA key='{SECRET}']")

    monkeypatch.setattr("src.analytics.engine_identity.baseline_engine_id", _identity_fails)
    assert merge._backlog_engine() == "<unknown>"
    assert "could not read the re-index backlog" in caplog.text
    _no_secret_anywhere(caplog, out)


def test_the_cleanup_skip_records_and_their_log_lines_keep_the_secret_out(monkeypatch, tmp_path, caplog):
    import logging

    from src.analytics import store

    caplog.set_level(logging.DEBUG)

    def _boom(*_a, **_k):
        raise RuntimeError(f"failed [SQL: PRAGMA key='{SECRET}']")

    monkeypatch.setattr(store, "prune_orphan_keywords", _boom)
    monkeypatch.setattr(store, "reconcile_keyword_language", _boom)
    monkeypatch.setattr(store, "reconcile_keyword_entity_status", _boom)
    monkeypatch.setattr(store, "_cleanup_marker_path", lambda: tmp_path / "keyword_cleanup.json")
    session = _empty_session()
    tally = store.maybe_cleanup_keywords(session)
    for key in ("prune", "language", "entity_status"):
        assert tally[key]["skipped"].startswith("RuntimeError: failed")
    # the resumed-prune arm: a fresh marker whose prune sweep was not complete
    stamp = datetime.now().isoformat(timespec="seconds")
    (tmp_path / "keyword_cleanup.json").write_text(
        f'{{"last_run": "{stamp}", "last_tally": {{"prune": {{"complete": false}}}}}}',
        encoding="utf-8",
    )
    resumed = store.maybe_cleanup_keywords(session)
    assert resumed.get("resumed_prune") is True and "RuntimeError: failed" in resumed["prune"]["skipped"]
    marker = (tmp_path / "keyword_cleanup.json").read_text(encoding="utf-8")
    assert SECRET not in marker
    _no_secret_anywhere(caplog, tally, resumed)


def test_the_unreadable_arm_of_the_write_cost_member_keeps_the_secret_out(monkeypatch, caplog):
    import logging

    from src.monitoring import keyword_write_cost as kwc

    caplog.set_level(logging.DEBUG)

    def _boom(*_a, **_k):
        raise RuntimeError(f"disk image is malformed [SQL: PRAGMA key='{SECRET}']")

    monkeypatch.setattr(kwc, "_sample_rows", _boom)
    out = kwc.keyword_write_cost(_empty_session())
    assert out["available"] is False and "disk image is malformed" in out["reason"]
    _no_secret_anywhere(caplog, out)


def _empty_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.database.models import Base

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True, autoflush=False)


def _empty_session():
    return _empty_factory()()


# ---- no raw engine text may come back: an AST check over the sinks -------------------------

# (file, the functions scanned, or None for the whole file, the least engine_text() calls inside)
_SCOPES = (
    ("src/monitoring/keyword_write_cost.py", None, 5),
    ("src/analytics/reindex_job.py", None, 1),
    ("src/analytics/store.py", ("_skip_error", "maybe_cleanup_keywords"), 1),
    ("src/backup/merge.py", ("reindex_backlog", "pending_reindex_batches", "_backlog_engine"), 3),
)
_ALLOWED_HELPERS = {"_cut_reason", "_skip_error"}  # each routes its argument through engine_text
#: An attribute with one of these names reads or prints the exception's traceback or text.
_TRACEBACK_NAMES = {
    "exception", "format_exc", "print_exc", "exc_info", "format_exception", "print_exception",
}
_LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception", "log", "warn"}


def _is_call_to(node: ast.AST, names: set[str]) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _scope_nodes(tree: ast.AST, functions):
    """The nodes the rules apply to: the whole file, or the named functions' bodies."""
    if functions is None:
        yield tree
        return
    found = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in functions}
    assert found == set(functions), f"a scanned function moved or was renamed: {set(functions) - found}"
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name in functions:
            yield n


def _problems(rel: str, tree: ast.AST, scope: ast.AST, parent) -> list[str]:
    out: list[str] = []
    for h in (n for n in ast.walk(scope) if isinstance(n, ast.ExceptHandler) and n.name):
        for stmt in h.body:
            for use in ast.walk(stmt):
                if not (isinstance(use, ast.Name) and use.id == h.name and isinstance(use.ctx, ast.Load)):
                    continue
                call = parent.get(use)
                ok = isinstance(call, ast.Call) and (
                    (_is_call_to(call, {"engine_text"}) and call.args and call.args[0] is use)
                    or _is_call_to(call, {"type", "isinstance"} | _ALLOWED_HELPERS)
                )
                if not ok:
                    out.append(f"{rel}:{use.lineno} uses {h.name!r} outside engine_text()")
    for node in ast.walk(scope):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "exc_info"
            and not (isinstance(node.value, ast.Constant) and node.value.value in (False, None))
        ):
            out.append(f"{rel}:{node.value.lineno} logs a traceback (exc_info)")
        if isinstance(node, ast.Attribute) and node.attr in _TRACEBACK_NAMES:
            out.append(f"{rel}:{node.lineno} reaches the traceback through .{node.attr}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
            and any(k.arg is None for k in node.keywords)
        ):
            out.append(f"{rel}:{node.lineno} passes ** to a log call (it can carry exc_info)")
        if isinstance(node, ast.Call) and _is_call_to(node, {"getattr"}):
            out.append(f"{rel}:{node.lineno} calls getattr (a logger method can be reached by name)")
    return out


@pytest.mark.parametrize("rel,functions,floor", _SCOPES, ids=[s[0] for s in _SCOPES])
def test_a_handler_never_uses_its_exception_except_through_engine_text(rel, functions, floor):
    """The bound name of every ``except ... as exc`` appears only as ``engine_text``'s first
    argument, inside ``type()``/``isinstance()``, or handed by name to an allowed helper; nothing
    reaches the traceback (``exc_info`` other than False/None, ``.exception``, ``format_exc``,
    ``print_exc``, ``sys.exc_info()`` and the rest, as a call or not), no log call takes ``**``,
    and no ``getattr``. The files bind ``engine_text`` only by importing it, and define nothing
    named ``engine_text``, ``type`` or ``isinstance``. Each scope calls it at least ``floor`` times."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    parent = _parents(tree)
    problems: list[str] = []
    calls = 0
    for scope in _scope_nodes(tree, functions):
        problems += _problems(rel, tree, scope, parent)
        calls += sum(1 for n in ast.walk(scope) if _is_call_to(n, {"engine_text"}))
    assert not problems, "\n".join(problems)
    assert calls >= floor, f"{rel}: {calls} engine_text() calls, expected at least {floor}"

    imports = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "src.monitoring.engine_text"
        and [a.name for a in n.names] == ["engine_text"] and n.names[0].asname is None
    ]
    assert imports, f"{rel} must bind engine_text with `from src.monitoring.engine_text import engine_text`"
    rebound = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in {"engine_text", "type", "isinstance"}:
            rebound.append(f"def {n.name} at {n.lineno}")
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in {"engine_text", "type", "isinstance"}:
            rebound.append(f"assignment to {n.id} at {n.lineno}")
        if isinstance(n, ast.alias) and n.asname in {"engine_text", "type", "isinstance"}:
            rebound.append(f"import as {n.asname}")
    assert not rebound, f"{rel} rebinds a name the ban relies on: {rebound}"
