"""The engine's failure text enters a status or a diagnostics member without the passphrase."""

from __future__ import annotations

import ast
import json
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest

from src.monitoring.engine_text import engine_text

SECRET = "correct horse battery staple 7"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", SECRET)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", None)


def test_the_passphrase_is_taken_out_of_the_whole_text_before_the_cut():
    exc = RuntimeError("x" * 150 + f" [SQL: PRAGMA key='{SECRET}'] " + "y" * 50)
    whole = str(exc)
    limit = whole.index(SECRET) + 10  # the cut falls ten characters INSIDE the secret
    out = engine_text(exc, limit)
    assert SECRET not in out
    assert SECRET[:10] not in out, "a cut made before the scrub would keep the first ten characters"


def test_the_connected_passphrase_is_scrubbed_too(monkeypatch):
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.setattr("src.database.connect._passphrase", SECRET)
    assert SECRET not in engine_text(RuntimeError(f"boom {SECRET} boom"))


def test_the_key_passphrase_is_scrubbed_too(monkeypatch):
    """The one that wraps the signing keys is a passphrase the process holds like the others."""
    monkeypatch.setenv("OO_KEY_PASSPHRASE", "signing key pass 99")
    assert "signing key pass 99" not in engine_text(RuntimeError("near 'signing key pass 99'"))


def test_an_empty_passphrase_in_the_environment_changes_nothing(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    assert engine_text(RuntimeError("database is locked")) == "database is locked"


def test_a_text_that_cannot_be_checked_is_withheld_not_kept(monkeypatch):
    monkeypatch.setattr("src.monitoring.secret_scrub.held_passphrases", lambda: None)
    out = engine_text(ValueError(f"has {SECRET} in it"))
    assert SECRET not in out and "ValueError" in out and "withheld" in out


def test_a_scrub_that_cannot_be_loaded_withholds_the_text(monkeypatch):
    import builtins

    real = builtins.__import__

    def _no_scrub(name, *a, **k):
        if name == "src.monitoring.secret_scrub":
            raise ImportError("gone")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_scrub)
    out = engine_text(ValueError(f"has {SECRET} in it"))
    assert SECRET not in out and "ValueError" in out and "withheld" in out


def test_a_passphrase_under_the_floor_withholds_the_text_it_is_in(monkeypatch):
    """One to three characters cannot be taken out of a text without taking the text out."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "ab")
    out = engine_text(RuntimeError("has ab in it"))
    assert "withheld" in out and "RuntimeError" in out


def test_a_unicode_error_is_the_class_and_none_of_its_words():
    out = engine_text(UnicodeDecodeError("utf-8", b"\xff", 0, 1, f"bad {SECRET}"))
    assert SECRET not in out and "withheld" in out


# ---- every shape the passphrase takes x every form an engine writes it in -----------------

#: independent writers (not the scrub's own carrier list). Each form is ``(encode, build)``: ``encode`` is how the
#: form writes the secret INSIDE the text (repr escapes a quote, JSON escapes a non-ASCII letter, SQL doubles an
#: apostrophe ...) and ``build`` makes the exception around it. The assertions are about the ENCODED stretch,
#: because that is what is in the text: a test that looks only for the secret as typed passes on every escaping
#: form with no scrub at all.
_SECRETS = (
    SECRET,
    "it's a \"quoted\" back\\slash pass",
    "pässwörd ünïcode 123",
    "o'brien''s pass ok",
)


def _sql(s: str) -> str:
    return s.replace("'", "''")


_FORMS = {
    "plain": (lambda s: s, lambda s, e: RuntimeError(f"near {e} here")),
    "sql-quoted": (_sql, lambda s, e: RuntimeError(f"[SQL: PRAGMA key = '{e}']")),
    "parameters": (lambda s: repr(s)[1:-1], lambda s, e: RuntimeError(f"[parameters: ({s!r},)]")),
    "two-arguments": (lambda s: repr(s)[1:-1], lambda s, e: RuntimeError("could not open", s)),
    "repr-of-the-exception": (lambda s: repr(s)[1:-1], lambda s, e: RuntimeError(repr(RuntimeError(s)))),
    "json-body-escaped": (lambda s: json.dumps(s)[1:-1], lambda s, e: RuntimeError(json.dumps({"detail": s}))),
    "json-body-unicode": (
        lambda s: json.dumps(s, ensure_ascii=False)[1:-1],
        lambda s, e: RuntimeError(json.dumps({"detail": s}, ensure_ascii=False)),
    ),
    "bytes-repr": (lambda s: repr(s.encode("utf-8"))[2:-1], lambda s, e: RuntimeError(repr(s.encode("utf-8")))),
    "sql-in-json-in-repr": (
        # the whole string holds both kinds of quote, so repr single-quotes it and escapes each apostrophe
        lambda s: repr(json.dumps(_sql(s))[1:-1] + "'\"")[1:-4],
        lambda s, e: RuntimeError(repr(json.dumps({"detail": f"PRAGMA key = '{_sql(s)}'"}))),
    ),
}


@pytest.mark.parametrize("form", sorted(_FORMS))
@pytest.mark.parametrize("secret", _SECRETS, ids=["plain", "quotes", "unicode", "sql-quote"])
def test_no_shape_in_no_form_survives_engine_text(monkeypatch, secret, form):
    monkeypatch.setenv("OO_DB_PASSPHRASE", secret)
    encode, build = _FORMS[form]
    stretch = encode(secret)
    exc = build(secret, stretch)
    whole = str(exc)
    # the fixture must carry the secret the way the form writes it, or the cell proves nothing
    assert stretch in whole, f"{form}: the form does not carry the encoded secret {stretch!r} in {whole!r}"
    for limit in (None, 40, 200):
        out = engine_text(exc, limit)
        assert stretch not in out and secret not in out
        assert stretch[:12] not in out, f"{form}: a prefix of the passphrase survived (limit {limit})"
    # a cut made INSIDE the encoded stretch, where the form put it
    spot = whole.index(stretch)
    for inside in (6, min(len(stretch) - 1, 12)):
        out = engine_text(exc, spot + inside)
        assert stretch[: min(inside, 6)] not in out, f"{form}: a cut inside the passphrase kept its start"


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
    assert "could not compute the engine identity for the backlog" in caplog.text
    assert "RuntimeError" in caplog.text, "a line names the class beside the words (an empty message logs blank)"
    _no_secret_anywhere(caplog, out)


def test_a_backlog_failure_with_an_empty_message_still_names_its_class(monkeypatch, caplog):
    import logging

    from src.backup import merge

    caplog.set_level(logging.DEBUG)

    class _Boom:
        def __enter__(self):
            raise KeyError()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("src.database.session.session_scope", lambda *a, **k: _Boom())
    out = merge.reindex_backlog()
    assert out["available"] is False and out["reason"] == ""
    assert merge.pending_reindex_batches() == []
    assert caplog.text.count("KeyError") >= 2, "both reads name the class, whatever the message holds"
    monkeypatch.setattr(
        "src.analytics.engine_identity.baseline_engine_id", lambda: (_ for _ in ()).throw(KeyError())
    )
    assert merge._backlog_engine() == "<unknown>"
    assert caplog.text.count("KeyError") >= 3


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
    for line in (
        "automatic orphan-keyword prune failed",
        "automatic keyword-language reconcile failed",
        "automatic keyword-entity-status reconcile failed",
    ):
        assert line in caplog.text, f"the handler's own log line is gone: {line}"
    # the resumed-prune arm: a fresh marker whose prune sweep was not complete
    stamp = datetime.now().isoformat(timespec="seconds")
    (tmp_path / "keyword_cleanup.json").write_text(
        f'{{"last_run": "{stamp}", "last_tally": {{"prune": {{"complete": false}}}}}}',
        encoding="utf-8",
    )
    resumed = store.maybe_cleanup_keywords(session)
    assert resumed.get("resumed_prune") is True and "RuntimeError: failed" in resumed["prune"]["skipped"]
    assert "automatic orphan-keyword prune resume failed" in caplog.text
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
    assert "keyword write cost unavailable" in caplog.text
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
    # src/backup/merge.py's three backlog handlers left this list on 2026-10-13: they write through log_failure and record_text (a
    # database driver is its class only), which tests/test_sink_sweep_records.py reads more strictly than this scan did.
    ("src/analytics/stoplist_recompute.py", ("maybe_recompute_top_keywords",), 1),
)
_ALLOWED_HELPERS = {"_cut_reason", "_skip_error"}  # each routes its argument through engine_text
#: Names the ban relies on: each may be bound only the one way (engine_text) or never (type, isinstance).
_BAN_NAMES = {"engine_text", "type", "isinstance"}
#: A name that reads or prints the exception's traceback or text, as an attribute OR bare (after an import).
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


def _bindings(tree: ast.AST, name: str) -> list[ast.AST]:
    """Every way ``name`` is bound anywhere in the file: a def or class, an assignment or loop target, an import
    (with or without ``as``), a parameter, an ``except ... as``, a ``match`` capture."""
    out: list[ast.AST] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            bound = n.id if isinstance(n.ctx, ast.Store) else None
        elif isinstance(n, ast.alias):
            bound = n.asname or n.name.split(".")[-1]
        elif isinstance(n, ast.arg):
            bound = n.arg
        elif isinstance(n, ast.MatchMapping):
            bound = n.rest
        else:  # def, class, `except ... as`, a match capture: each names what it binds as ``.name``
            bound = getattr(n, "name", None) if isinstance(
                n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar)
            ) else None
        if bound == name:
            out.append(n)
    return out


def _uses_outside(rel: str, name: str, nodes, parent, *, helpers: bool) -> list[str]:
    """Every load of ``name`` in ``nodes`` that is not engine_text's FIRST argument, inside type() or
    isinstance(), or (where ``helpers``) the FIRST argument of an allowed helper."""
    out: list[str] = []
    for stmt in nodes:
        for use in ast.walk(stmt):
            if not (isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load)):
                continue
            call = parent.get(use)
            first = isinstance(call, ast.Call) and bool(call.args) and call.args[0] is use
            ok = isinstance(call, ast.Call) and (
                (_is_call_to(call, {"engine_text"} | (_ALLOWED_HELPERS if helpers else set())) and first)
                or _is_call_to(call, {"type", "isinstance"})
            )
            if not ok:
                out.append(f"{rel}:{use.lineno} uses {name!r} outside engine_text()")
    return out


def _helper_problems(rel: str, tree: ast.AST, parent) -> list[str]:
    """A helper the handlers may hand their exception to is trusted only as far as its own body: its first
    parameter is used as engine_text's first argument or inside type()/isinstance(), and nothing else. A helper
    is also defined exactly once, by a plain ``def``: a lambda, an import, an ``async def`` or a second
    definition would change what the handlers' trust points at."""
    out: list[str] = []
    for name in sorted(_ALLOWED_HELPERS):
        bound = _bindings(tree, name)
        if not bound:
            continue
        if len(bound) != 1 or not isinstance(bound[0], ast.FunctionDef):
            out.append(f"{rel}: the helper {name} is bound {len(bound)} times or not by a plain def")
            continue
        fn = bound[0]
        out += _uses_outside(rel, fn.args.args[0].arg, fn.body, parent, helpers=False)
    return out


def _problems(rel: str, tree: ast.AST, scope: ast.AST, parent) -> list[str]:
    out: list[str] = []
    for h in (n for n in ast.walk(scope) if isinstance(n, ast.ExceptHandler) and n.name):
        out += _uses_outside(rel, h.name, h.body, parent, helpers=True)
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and node.id in _TRACEBACK_NAMES:
            out.append(f"{rel}:{node.lineno} reaches the traceback through the bare name {node.id}")
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


def _file_problems(rel: str, source: str, functions) -> tuple[list[str], int]:
    """Everything the guard refuses in one file, and how many engine_text() calls the scanned scopes hold."""
    tree = ast.parse(source)
    parent = _parents(tree)
    problems: list[str] = []
    calls = 0
    for scope in _scope_nodes(tree, functions) if functions is not None else [tree]:
        problems += _problems(rel, tree, scope, parent)
        calls += sum(1 for n in ast.walk(scope) if _is_call_to(n, {"engine_text"}))
    problems += _helper_problems(rel, tree, parent)
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in {"traceback", "sys", "logging"}:
            problems += [
                f"{rel}:{n.lineno} imports {a.name} from {n.module} (a traceback reader under another name)"
                for a in n.names
                if a.name in _TRACEBACK_NAMES
            ]
    # engine_text is bound exactly once, by the import from its module; type and isinstance never
    et = _bindings(tree, "engine_text")
    canonical = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "src.monitoring.engine_text"
        and [a.name for a in n.names] == ["engine_text"] and n.names[0].asname is None
    ]
    if len(et) != 1 or len(canonical) != 1:
        problems.append(
            f"{rel} must bind engine_text exactly once, with `from src.monitoring.engine_text import "
            f"engine_text`; found {len(et)} binding(s) and {len(canonical)} such import(s)"
        )
    problems += [
        f"{rel}:{getattr(n, 'lineno', 0)} rebinds {name!r}, a name the ban relies on"
        for name in ("type", "isinstance")
        for n in _bindings(tree, name)
    ]
    return problems, calls


@pytest.mark.parametrize("rel,functions,floor", _SCOPES, ids=[s[0] for s in _SCOPES])
def test_a_handler_never_uses_its_exception_except_through_engine_text(rel, functions, floor):
    """The bound name of every ``except ... as exc`` appears only as ``engine_text``'s FIRST argument, inside
    ``type()``/``isinstance()``, or as the first argument of an allowed helper whose own body obeys the same
    rule; nothing reaches the traceback (``exc_info`` other than False/None, ``.exception``, ``format_exc``,
    ``print_exc``, ``sys.exc_info()`` and the rest, as an attribute, a bare name or an import under another
    name), no log call takes ``**``, and no ``getattr``. The file binds ``engine_text`` once, by importing it,
    and never rebinds ``type`` or ``isinstance``. Each scope calls it at least ``floor`` times."""
    problems, calls = _file_problems(rel, (ROOT / rel).read_text(encoding="utf-8"), functions)
    assert not problems, "\n".join(problems)
    assert calls >= floor, f"{rel}: {calls} engine_text() calls, expected at least {floor}"


# ---- the scan itself: each way round it is refused (a guard that cannot fail guards nothing) ----

_HEAD = "from src.monitoring.engine_text import engine_text\n"
_HANDLER = "try:\n    pass\nexcept Exception as exc:\n    {}\n"


@pytest.mark.parametrize(
    "body",
    [
        _HANDLER.format("log(str(exc))"),
        _HANDLER.format("log(f'{exc}')"),
        _HANDLER.format("log(repr(exc))"),
        _HANDLER.format("log(key=exc)"),
        _HANDLER.format("log(engine_text(x, exc))"),
        _HANDLER.format("raise RuntimeError('x') from exc"),
        _HANDLER.format("format_exc()"),
        _HANDLER.format("log(exc_info=True)"),
        _HANDLER.format("log.exception('x')"),
        _HANDLER.format("log(**kw)").replace("log(", "log.warning("),
        _HANDLER.format("getattr(log, 'warn')('x')"),
        _HANDLER.format("_skip_error(None, exc)") + "def _skip_error(e):\n    return engine_text(e)\n",
        "from traceback import format_exc as fe\n",
        "from sys import exc_info\n",
        "from logging import exception\n",
        "from elsewhere import engine_text\n",
        "import engine_text\n",
        "engine_text = lambda e: str(e)\n",
        "def engine_text(e):\n    return str(e)\n",
        "type = lambda x: x\n",
        "def f(isinstance):\n    pass\n",
        "def _skip_error(exc):\n    return {'skipped': str(exc)}\n",
        "def _cut_reason(exc):\n    return repr(exc)\n",
        "_cut_reason = lambda exc: repr(exc)\n",
        "from x import _skip_error\n",
        "async def _skip_error(exc):\n    return engine_text(exc)\n",
        "def _skip_error(exc):\n    return engine_text(exc)\ndef _skip_error(exc):\n    return str(exc)\n",
        # every way a name is bound is read, not only def/assign/import: a class, an except-as, a match capture
        "class engine_text:\n    pass\n",
        "class isinstance:\n    pass\n",
        "try:\n    pass\nexcept Exception as engine_text:\n    pass\n",
        "try:\n    pass\nexcept Exception as type:\n    pass\n",
        "match x:\n    case engine_text:\n        pass\n",
        "match x:\n    case [*engine_text]:\n        pass\n",
        "match x:\n    case {**engine_text}:\n        pass\n",
        "import src.monitoring.engine_text as engine_text\n",
        "for engine_text in range(3):\n    pass\n",
    ],
)
def test_the_scan_refuses_each_bypass(body):
    problems, _calls = _file_problems("x.py", _HEAD + body, None)
    assert problems, f"the scan let this through:\n{body}"


@pytest.mark.parametrize(
    "source",
    [
        "x = 1\n",  # no import at all
        "import src.monitoring.engine_text as engine_text\n",  # a binding, but not the canonical import
        "from src.monitoring.engine_text import engine_text as et\n",  # imports it under another name
        "from src.monitoring.engine_text import engine_text, other\n",  # not the one-name canonical form
        "from elsewhere import engine_text\n",  # the only import is from another module
    ],
)
def test_the_scan_requires_the_canonical_import_exactly_once(source):
    problems, _calls = _file_problems("x.py", source, None)
    assert any("must bind engine_text exactly once" in p for p in problems), problems


def test_the_scan_accepts_the_shapes_the_files_use():
    ok = (
        _HEAD
        + "def _skip_error(exc):\n    return {'s': engine_text(exc, 200, typed=True), 'c': type(exc).__name__}\n"
        + _HANDLER.format("log(engine_text(exc), type(exc).__name__, _skip_error(exc))")
    )
    problems, calls = _file_problems("x.py", ok, None)
    assert problems == [] and calls == 2



# ---- typed=True: the class once, in front --------------------------------------------------


def test_typed_writes_the_class_once_in_front_of_the_words():
    assert engine_text(RuntimeError("database is locked"), typed=True) == "RuntimeError: database is locked"
    assert engine_text(RuntimeError(f"near {SECRET}"), typed=True) == "RuntimeError: near ***redacted***"


def test_typed_names_the_class_once_when_the_text_is_withheld(monkeypatch):
    monkeypatch.setattr("src.monitoring.secret_scrub.held_passphrases", lambda: None)
    out = engine_text(ValueError("whatever"), typed=True)
    assert out.count("ValueError") == 1 and "withheld" in out, out


def test_typed_gives_a_unicode_error_by_class_only():
    out = engine_text(UnicodeDecodeError("utf-8", b"\\xff", 0, 1, f"bad {SECRET}"), typed=True)
    assert SECRET not in out and "withheld" in out


def test_typed_is_cut_after_the_scrub():
    exc = RuntimeError("x" * 30 + SECRET)
    # "RuntimeError: " (14) + 30 letters = 44, so a cut at 54 lands ten characters inside the secret: cut
    # BEFORE the scrub it would print "correct ho"; cut after, the marker's first ten characters
    out = engine_text(exc, 54, typed=True)
    assert out.endswith("***redacte") and "correct ho" not in out


def test_the_fallback_when_the_scrub_cannot_be_loaded_is_cut_too(monkeypatch):
    import builtins

    real = builtins.__import__

    def _no_scrub(name, *a, **k):
        if name == "src.monitoring.secret_scrub":
            raise ImportError("gone")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_scrub)
    out = engine_text(ValueError("x"), 20, typed=True)
    assert len(out) == 20 and "ValueError" in out
