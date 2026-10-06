"""The engine's failure text enters a status or a diagnostics member without the passphrase."""

from __future__ import annotations

import ast
import threading
from contextlib import contextmanager
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


def test_the_cleanup_skip_record_and_the_backlog_reason_do_not_carry_the_secret(monkeypatch):
    from src.analytics.store import _skip_error

    assert SECRET not in repr(_skip_error(RuntimeError(f"failed [SQL: PRAGMA key='{SECRET}']")))

    from src.backup import merge

    class _Boom:
        def __enter__(self):
            raise RuntimeError(f"cannot read [SQL: PRAGMA key='{SECRET}']")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("src.database.session.session_scope", lambda *a, **k: _Boom())
    out = merge.reindex_backlog()
    assert out["available"] is False and SECRET not in repr(out)


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


# ---- no raw engine text may come back: an AST check over the two files ----------------------

_FILES = ("src/monitoring/keyword_write_cost.py", "src/analytics/reindex_job.py")
_ALLOWED_HELPERS = {"_cut_reason"}


def _is_call_to(node: ast.AST, names: set[str]) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names


def _uses_of(name: str, body: list[ast.stmt]):
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
                yield node


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


@pytest.mark.parametrize("rel", _FILES)
def test_a_handler_never_uses_its_exception_except_through_engine_text(rel):
    """The bound name of every ``except ... as exc`` appears only as ``engine_text``'s first
    argument, inside ``type()``/``isinstance()``, or handed by name to an allowed helper; no
    ``exc_info`` other than False/None and no ``.exception()`` call (both print the traceback,
    which carries the statement)."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    parent = _parents(tree)
    problems: list[str] = []
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name]
    for h in handlers:
        for use in _uses_of(h.name, h.body):
            call = parent.get(use)
            ok = (
                isinstance(call, ast.Call)
                and (
                    (_is_call_to(call, {"engine_text"}) and call.args and call.args[0] is use)
                    or _is_call_to(call, {"type", "isinstance"} | _ALLOWED_HELPERS)
                )
            )
            if not ok:
                problems.append(f"{rel}:{use.lineno} uses {h.name!r} outside engine_text()")
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "exc_info":
            if not (isinstance(node.value, ast.Constant) and node.value.value in (False, None)):
                problems.append(f"{rel}:{node.value.lineno} logs a traceback (exc_info)")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "exception":
            problems.append(f"{rel}:{node.lineno} calls .exception()")
    assert not problems, "\n".join(problems)


def test_the_helper_is_actually_called_where_the_sinks_are():
    counts = {}
    for rel in _FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        counts[rel] = sum(1 for n in ast.walk(tree) if _is_call_to(n, {"engine_text"}))
    assert counts["src/monitoring/keyword_write_cost.py"] >= 5, counts
    assert counts["src/analytics/reindex_job.py"] >= 1, counts
