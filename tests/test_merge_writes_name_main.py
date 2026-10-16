"""Every write in ``merge.py`` names the schema it writes to.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

While a backup is attached, an unqualified table name falls through to the ATTACHED file when ``main`` lacks the table, so a write that
names no schema can land in the incoming backup (the measured case: the keyword thread's DELETE; ``tests/test_merge_main_schema.py``).
``init_db`` gives ``main`` every ``models.py`` table, so nothing reaches this in production; this file keeps it that way. The scan reads
the SQL the module can send (statement strings, the arguments of ``execute`` / ``executemany`` / ``executescript`` and of the helpers that
hand a parameter to them, built by f-string, concatenation, ``%`` or ``.format``) and FAILS on a write that names neither ``main.`` nor
``temp.``, and on a statement it cannot read; the planted cases show each shape is caught, and the behavioural case shows the failure the
scan prevents. Docstrings and comments are not statements and are not read.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402

_MERGE = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"

_EXEMPT = ("main.", "temp.")
#: A statement's HEAD, with its target: the writes the module sends. The target is read up to the next space or bracket.
_WRITE = re.compile(
    r"\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|DROP\s+(?:TABLE|INDEX|VIEW|TRIGGER)(?:\s+IF\s+EXISTS)?"
    r"|ALTER\s+TABLE|CREATE\s+(?:TABLE|VIRTUAL\s+TABLE|INDEX|UNIQUE\s+INDEX|TRIGGER|VIEW)(?:\s+IF\s+NOT\s+EXISTS)?)\s+(\"?[\w{}.]+\"?)",
    re.I,
)
_READ_HEADS = {"SELECT", "PRAGMA", "ATTACH", "DETACH", "BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE", "VACUUM"}
_ANY_WRITE = re.compile(r"\b(INSERT|REPLACE|UPDATE|DELETE|DROP|ALTER|CREATE)\b", re.I)
_TEXT_WRAPPERS = {"text", "_text"}
_EXEC_METHODS = {"execute", "executemany", "executescript", "exec_driver_sql"}

#: Statements the scan cannot read to a text, or that name no schema on purpose, each with the reason. Keyed ``function: expression``.
_ALLOWED: dict[str, str] = {
    "_fts_insert_suspended: ddl": "the CREATE TRIGGER text read back from main's own sqlite_master, replayed on the same connection: it creates in main",
    "merge_corpus: fts_trigger_ddl": "the same stored CREATE TRIGGER text, handed to _restore_fts_insert_trigger",
    "_carry_live_settings: CREATE TABLE IF NOT EXISTS app_state": "an unqualified CREATE always creates in main and IF NOT EXISTS looks at main only; it also runs on the working copy's own standalone connection",
    "merge_custody: CREATE TABLE IF NOT EXISTS custody_imported_entries": "an unqualified CREATE always creates in main and IF NOT EXISTS looks at main only; it also runs on custody_log.db's own standalone connection",
    "merge_custody: sql": "the two SELECTs appended to `sources` just above (a chain's rows are only fetched by _custody_rows); no write reaches it",
}

_META = {
    "artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}


_LEADING_COMMENT = re.compile(r"\s*(?:--[^\n]*(?:\n|$)|/\*.*?\*/)", re.S)


def _strip_leading_comments(sql: str) -> str:
    """A leading ``--`` or ``/* */`` comment is not part of the statement's head (and a write must not hide behind one)."""
    while m := _LEADING_COMMENT.match(sql):
        sql = sql[m.end():]
    return sql.lstrip()


def _looks_like_write(sql: str) -> bool:
    sql = _strip_leading_comments(sql)
    return bool(_WRITE.match(sql)) or (sql[:4].upper() == "WITH" and bool(_ANY_WRITE.search(sql)))


def _classify(sql: str) -> list[str]:
    """What is wrong with one statement text (``{}`` stands for a piece the source builds at run time): empty when it is a read, a
    temp-table statement, or a write that names ``main``. The schema prefix is compared case-insensitively and must be the BARE word:
    a quoted ``"main.t"`` is a table of that odd name, in main."""
    problems: list[str] = []
    for stmt in (_strip_leading_comments(part) for part in sql.split(";")):
        if not stmt:
            continue
        m = _WRITE.match(stmt)
        if m:
            raw = m.group(2)
            if raw.lower().startswith(_EXEMPT):
                continue
            if re.match(r"\s*(CREATE\s+(?:TEMP|TEMPORARY)\b)", stmt, re.I):
                continue
            problems.append(f"{' '.join(m.group(1).split()).upper()} {raw.strip(chr(34))}")
            continue
        head = re.match(r"\s*(\w+)", stmt)
        word = head.group(1).upper() if head else ""
        if word == "ANALYZE":  # an unqualified ANALYZE writes sqlite_stat1 into EVERY attached schema
            if not re.match(r"\s*ANALYZE\s+(?:main|temp)\.", stmt, re.I):
                problems.append("ANALYZE names no schema")
            continue
        if word == "PRAGMA":  # `PRAGMA optimize` (like ANALYZE) reaches every attached schema unless it names one
            if re.match(r"\s*PRAGMA\s+optimize\b", stmt, re.I):
                problems.append("PRAGMA optimize names no schema")
            continue
        if word in _READ_HEADS:
            continue
        if word == "CREATE" and re.match(r"\s*CREATE\s+(?:TEMP|TEMPORARY)\b", stmt, re.I):
            continue
        if word == "WITH" and not _ANY_WRITE.search(stmt):
            continue
        problems.append(f"cannot classify: {stmt[:60]!r}")
    return problems


class _Scan:
    """Walks one module and reports every statement that could write without naming its schema, from the SQL it can read to a text:
    string constants anywhere, and the first argument of ``execute`` / ``executemany`` / ``executescript`` / ``exec_driver_sql`` (resolved
    through ``text()``, concatenation, ``%`` and ``.format``, f-strings, and the assignments of a name in its function), and of every
    function that hands one of its parameters to one of those. A statement it cannot read is a problem, not a skip."""

    def __init__(self, source: str):
        self.tree = ast.parse(source)
        self.defs: list[ast.AST] = [n for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.parent: dict[ast.AST, ast.AST] = {c: p for p in ast.walk(self.tree) for c in ast.iter_child_nodes(p)}
        self.module_assigns = self._assigns([n for n in self.tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))])
        #: helper name -> {parameter name: its positional index, or None when keyword-only}: the parameters that reach an execute call
        self.passthrough: dict[str, dict[str, int | None]] = {}
        #: a name bound to an execute method (``<exec>``) or to a pass-through helper: ``ex = con.execute`` / ``ex = run``
        self.aliases: dict[str, str] = {}
        self.problems: list[str] = []
        self.allowed_used: set[str] = set()

    @staticmethod
    def _assigns(body: list[ast.stmt]) -> dict[str, list[ast.expr]]:
        out: dict[str, list[ast.expr]] = {}
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            out.setdefault(t.id, []).append(node.value)
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and isinstance(node.target, ast.Name) and node.value is not None:
                    out.setdefault(node.target.id, []).append(node.value)
        return out

    def _origin_params(self, node: ast.expr, fn: ast.AST | None, seen: frozenset[str] = frozenset()) -> set[str] | None:
        """The parameters of ``fn`` that ``node`` is made of (the name itself, a string method on it, or a local assigned from those), or
        ``None`` when it is made of anything else."""
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        params = {name for name, _ in self._params(fn)}
        if isinstance(node, ast.Name):
            if node.id in params:
                return {node.id}
            if node.id in seen:
                return None
            pool = self._assigns(fn.body).get(node.id)
            if not pool:
                return None
            out: set[str] = set()
            for value in pool:
                got = self._origin_params(value, fn, seen | {node.id})
                if got is None:
                    return None
                out |= got
            return out
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"replace", "strip", "format", "lstrip", "rstrip"}:
            # `.replace` can take the schema prefix OFF (`sql.replace("main.", "")`), so it passes only when what it replaces is a plain
            # string that is not one; anything else makes the text unreadable at the helper, which is a problem
            if node.func.attr == "replace":
                gone = self._texts(node.args[0], fn) if node.args else None
                # a fragment of the prefix is as good as the prefix: `.replace("ma", "").replace("in.", "")` strips `main.`
                if gone is None or any(w in t.lower() or t.lower() in prefix for t in gone for w in ("main", "temp") for prefix in ("main.", "temp.")):
                    return None
            return self._origin_params(node.func.value, fn, seen)
        return None

    @staticmethod
    def _params(fn: ast.AST) -> list[tuple[str, int | None]]:
        """``(name, positional index as a caller counts it)`` for every parameter of ``fn``: a leading ``self`` / ``cls`` is not passed by a
        caller, and a keyword-only parameter has no index."""
        a = fn.args  # type: ignore[attr-defined]
        positional = [*a.posonlyargs, *a.args]
        if positional and positional[0].arg in {"self", "cls"}:
            positional = positional[1:]
        return [(p.arg, i) for i, p in enumerate(positional)] + [(p.arg, None) for p in a.kwonlyargs]

    def _func_of(self, node: ast.AST) -> ast.AST | None:
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def _texts(self, node: ast.expr, fn: ast.AST | None, seen: frozenset[str] = frozenset()) -> list[str] | None:
        """Every text ``node`` can be (``{}`` for run-time pieces), or ``None`` when it cannot be read."""
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else None
        if isinstance(node, ast.JoinedStr):
            return ["".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            left = self._texts(node.left, fn, seen)
            if left is None:
                return None
            if isinstance(node.op, ast.Mod):
                return left
            right = self._texts(node.right, fn, seen) or ["{}"]
            return [a + b for a in left for b in right]
        if isinstance(node, ast.IfExp):
            a, b = self._texts(node.body, fn, seen), self._texts(node.orelse, fn, seen)
            return None if a is None or b is None else a + b
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in _TEXT_WRAPPERS and node.args:
                return self._texts(node.args[0], fn, seen)
            if isinstance(f, ast.Attribute) and f.attr == "bindparams":
                return self._texts(f.value, fn, seen)
            if isinstance(f, ast.Attribute) and f.attr in {"format", "join"} and isinstance(f.value, ast.Constant):
                return [f.value.value] if f.attr == "format" else ["{}"]
            root: ast.expr = f
            while isinstance(root, (ast.Attribute, ast.Call)):
                root = root.func if isinstance(root, ast.Call) else root.value
            if isinstance(root, ast.Name) and root.id == "select":  # a SQLAlchemy select(...) chain: a read
                return ["SELECT"]
            return None
        if isinstance(node, ast.Name):
            params = {name for name, _ in self._params(fn)} if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) else set()
            if node.id in seen:
                return None
            pool = self._assigns(fn.body).get(node.id) if fn is not None else None  # type: ignore[attr-defined]
            scope = fn
            while pool is None and node.id not in params and scope is not None:  # a closure reads the enclosing functions, then the module
                scope = self._func_of(scope)
                pool = self._assigns(scope.body).get(node.id) if scope is not None else self.module_assigns.get(node.id)  # type: ignore[attr-defined]
            if pool is None and fn is None:
                pool = self.module_assigns.get(node.id)
            if not pool:
                return None
            out: list[str] = []
            for value in pool:
                got = self._texts(value, fn, seen | {node.id})
                if got is None:
                    return None
                out.extend(got)
            return out
        return None

    def run(self) -> list[str]:
        # 1. which functions hand a parameter to an execute call (or to another such function): their callers' arguments are SQL too
        changed = True
        while changed:
            changed = False
            for node in ast.walk(self.tree):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    kind = self._callable_kind(node.value)
                    if kind is not None and self.aliases.get(node.targets[0].id) != kind:
                        self.aliases[node.targets[0].id] = kind
                        changed = True
            for fn in self.defs:
                index = dict(self._params(fn))
                for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and self._func_of(n) is fn):
                    for arg in self._sql_args(call):
                        for name in self._origin_params(arg, fn) or ():
                            if name not in self.passthrough.setdefault(fn.name, {}):  # type: ignore[attr-defined]
                                self.passthrough[fn.name][name] = index[name]  # type: ignore[attr-defined]
                                changed = True
        # 2. every SQL-bearing call, read to a text (an argument made only of the caller's own parameters is checked at the caller's callers)
        for call in (n for n in ast.walk(self.tree) if isinstance(n, ast.Call)):
            fn = self._func_of(call)
            for arg in self._sql_args(call):
                origin = self._origin_params(arg, fn)
                # a parameter the body REASSIGNS (`sql = sql.replace(...)`, `if flag: sql = "SELECT 1"`, one inside a nested def) is still what
                # the caller passed, on some path, so it stays a pass-through; AND the helper's own assignments are read at the helper
                if origin is None or (fn is not None and any(n in self._assigns(fn.body) for n in origin)):
                    self._check(call, arg)
        # 3. a string anywhere that starts like a write
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Constant, ast.JoinedStr)):
                text = self._texts(node, None)
                if text and _looks_like_write(text[0]) and not isinstance(self.parent.get(node), ast.Expr):
                    for problem in _classify(text[0]):
                        self._report(node, problem)
        # 4. an execute method or a helper used as a VALUE other than the right side of a plain `name = ...` (an alias, followed above):
        #    `partial(run, con)`, `map(con.execute, rows)`: the scan cannot see which SQL reaches it, so that is a problem
        for node in ast.walk(self.tree):
            kind = self._callable_kind(node) if isinstance(node, (ast.Attribute, ast.Name)) else None
            if kind is None or isinstance(getattr(node, "ctx", None), ast.Store):
                continue
            parent = self.parent.get(node)
            if isinstance(parent, ast.Call) and parent.func is node:
                continue
            if isinstance(parent, ast.Attribute):  # `con` in `con.execute`, `a` in `a.run`: not a use of the callable
                continue
            if isinstance(parent, ast.Assign) and parent.value is node and all(isinstance(t, ast.Name) for t in parent.targets):
                continue
            if isinstance(node, ast.Name) and node.id not in self.passthrough and node.id not in self.aliases:
                continue
            self._report(node, f"{ 'an execute method' if kind == '<exec>' else kind} used as a value")
        return sorted(set(self.problems))

    def _callable_kind(self, node: ast.expr) -> str | None:
        """``"<exec>"`` for an execute method taken as a value (``con.execute``, ``getattr(con, "execute")``), the helper's name for a
        pass-through helper or an alias of one, else ``None``."""
        if isinstance(node, ast.Attribute) and node.attr in _EXEC_METHODS:
            return "<exec>"
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value in _EXEC_METHODS):
            return "<exec>"
        name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", None) if isinstance(node, ast.Attribute) else None
        if name is None:
            return None
        if name in self.aliases:
            return self.aliases[name]
        return name if name in self.passthrough else None

    def _sql_args(self, call: ast.Call) -> list[ast.expr]:
        """The arguments of ``call`` that are SQL: the statement of an execute-like method (positional or by keyword), and the passed-through
        parameters of a helper (positional or by keyword). A ``*args`` / ``**kwargs`` that could carry one is returned as it stands, which
        the reader cannot resolve: a problem, not a skip."""
        f = call.func
        if (isinstance(f, ast.Call) and isinstance(f.func, ast.Name) and f.func.id == "getattr" and len(f.args) >= 2
                and isinstance(f.args[1], ast.Constant) and f.args[1].value in _EXEC_METHODS):  # getattr(con, "execute")(...)
            f = ast.Attribute(value=f.args[0], attr=f.args[1].value)
        if isinstance(f, ast.Name) and f.id in self.aliases:  # `ex = con.execute; ex(...)` and `ex = run; ex(...)`
            f = ast.Attribute(value=f, attr="execute") if self.aliases[f.id] == "<exec>" else ast.Name(id=self.aliases[f.id])
        keywords = {k.arg: k.value for k in call.keywords if k.arg is not None}
        spread = [ast.Starred(value=k.value) for k in call.keywords if k.arg is None]  # a Starred is never a readable text
        starred = next((a for a in call.args if isinstance(a, ast.Starred)), None)
        if isinstance(f, ast.Attribute) and f.attr in _EXEC_METHODS:
            if call.args and not isinstance(call.args[0], ast.Starred):
                return [call.args[0]]
            found = [keywords[k] for k in ("statement", "sql", "operation") if k in keywords]
            return found or ([starred] if starred is not None else spread[:1])
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        out: list[ast.expr] = []
        for param, idx in (self.passthrough.get(name) or {}).items() if name else ():
            if idx is not None and idx < len(call.args) and not any(isinstance(a, ast.Starred) for a in call.args[: idx + 1]):
                out.append(call.args[idx])
            elif param in keywords:
                out.append(keywords[param])
            elif starred is not None:
                out.append(starred)
            elif spread:
                out.append(spread[0])
        return out

    def _report(self, node: ast.AST, problem: str) -> None:
        fn = self._func_of(node)
        where = fn.name if fn is not None else "<module>"  # type: ignore[attr-defined]
        if f"{where}: {problem}" in _ALLOWED:
            self.allowed_used.add(f"{where}: {problem}")
            return
        self.problems.append(f"line {getattr(node, 'lineno', '?')} in {where}: {problem}")

    def _check(self, call: ast.Call, arg: ast.expr) -> None:
        fn = self._func_of(call)
        texts = self._texts(arg, fn)
        where = fn.name if fn is not None else "<module>"  # type: ignore[attr-defined]
        if texts is None:
            expr = ast.unparse(arg)
            if f"{where}: {expr}" in _ALLOWED:
                self.allowed_used.add(f"{where}: {expr}")
            else:
                self.problems.append(f"line {call.lineno} in {where}: cannot read the SQL of {expr[:70]!r}")
            return
        for text in texts:
            for problem in _classify(text):
                self._report(call, problem)


def _scan(source: str) -> list[str]:
    return _Scan(source).run()


def test_the_real_module_has_no_write_that_names_no_schema():
    problems = _scan(_MERGE.read_text(encoding="utf-8"))
    assert not problems, (
        "a write that names no schema falls through to the attached backup when main lacks the table; qualify it with `main.` "
        "(or, for a statement the scan cannot read, say why in _ALLOWED):\n" + "\n".join(problems)
    )


def test_the_allowlist_has_no_dead_entries():
    scan = _Scan(_MERGE.read_text(encoding="utf-8"))
    scan.run()
    assert set(_ALLOWED) == scan.allowed_used, set(_ALLOWED) ^ scan.allowed_used
    assert all(why.strip() for why in _ALLOWED.values())


def test_the_scan_sees_the_real_module_s_writes():
    """A scan that matches nothing proves nothing: count what it reads in the real module."""
    scan = _Scan(_MERGE.read_text(encoding="utf-8"))
    scan.run()
    texts = [t for node in ast.walk(scan.tree) if isinstance(node, (ast.Constant, ast.JoinedStr)) for t in (scan._texts(node, None) or [])]
    heads = [m.group(2).strip('"') for t in texts if (m := _WRITE.match(t))]
    assert len(heads) >= 60, len(heads)
    assert sum(h.startswith("main.") for h in heads) >= 60
    assert any(h.startswith("temp.") for h in heads), "temp tables are the exempt kind and must be seen to be exempt"
    assert any(h.startswith("main.{") for h in heads), "a table named by an f-string placeholder is qualified inside it"
    assert {"_q", "_count", "_custody_rows"} <= set(scan.passthrough), scan.passthrough


@pytest.mark.parametrize(
    "snippet",
    [
        'def f(con):\n    con.execute("INSERT INTO t (a) VALUES (1)")',
        # UPSERT: the ON CONFLICT clause does not make it a statement the head check can skip
        'def f(con):\n    con.execute("INSERT INTO t (a) VALUES (1) ON CONFLICT(a) DO UPDATE SET a = 2")',
        'def f(con):\n    con.execute("INSERT INTO t (a) VALUES (1) ON CONFLICT DO NOTHING")',
        # REPLACE INTO, and the INSERT OR REPLACE spelling
        'def f(con):\n    con.execute("REPLACE INTO t (a) VALUES (1)")',
        'def f(con):\n    con.execute("INSERT OR REPLACE INTO t (a) VALUES (1)")',
        'def f(con):\n    con.execute("UPDATE t SET a = 1")',
        'def f(con):\n    con.execute("DELETE FROM t")',
        'def f(con):\n    con.execute("DROP TABLE IF EXISTS t")',
        'def f(con):\n    con.execute("DROP TRIGGER trg")',
        'def f(con):\n    con.execute("ALTER TABLE t ADD COLUMN c TEXT")',
        # executemany and executescript, a variable that holds the statement, and a second statement in a script
        'def f(con):\n    sql = "INSERT INTO t (a) VALUES (?)"\n    con.executemany(sql, [(1,)])',
        'def f(con):\n    con.executescript("DELETE FROM temp.x; DELETE FROM t")',
        # built by concatenation, % and .format and f-strings
        'def f(con, where):\n    con.execute("UPDATE t SET a = 1 " + where)',
        'def f(con):\n    con.execute("UPDATE t SET a = %s" % 1)',
        'def f(con):\n    con.execute("DELETE FROM {}".format("t"))',
        'def f(con, t):\n    con.execute(f"DELETE FROM {t}")',
        # a conditional that has one unqualified arm, and a WITH that ends in a write
        'def f(con, x):\n    con.execute("UPDATE main.t SET a = 1" if x else "UPDATE t SET a = 1")',
        'def f(con):\n    con.execute("WITH w AS (SELECT 1) INSERT INTO t SELECT * FROM w")',
        # SQLAlchemy text(), including a bindparams chain
        'from sqlalchemy import text\ndef f(s):\n    s.execute(text("UPDATE t SET a = 1"))',
        'from sqlalchemy import text\ndef f(s):\n    s.execute(text("UPDATE t SET a = :a").bindparams(a=1))',
        # a helper that hands its parameter to execute: its callers' statements are read too
        'def run(con, sql):\n    con.execute(sql)\ndef f(con):\n    run(con, "INSERT INTO t (a) VALUES (1)")',
        # a statement it cannot read is a problem, not a skip
        'def f(con):\n    con.execute(build_sql())',
        'def f(con, verb):\n    con.execute(f"{verb} INTO main.t (a) VALUES (1)")',
        # a string that is a write but sits in a variable nothing executes in this function
        'SQL = "INSERT INTO t (a) VALUES (1)"',
        # a WITH-led or comment-led string is still a write
        'SQL = "WITH w AS (SELECT 1) INSERT INTO t SELECT * FROM w"',
        'SQL = "-- note\\nDELETE FROM t"',
        'def f(con):\n    con.execute("/* note */ DELETE FROM t")',
        # SQL handed over BY KEYWORD: to execute, to text(), to a helper (a positional, a keyword-only and a classmethod parameter)
        'from sqlalchemy import text\ndef f(s):\n    s.execute(statement=text("UPDATE t SET a = 1"))',
        'def f(con, v):\n    con.execute(statement=f"{v} FROM t")',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con):\n    run(con, sql="WITH w AS (SELECT 1) INSERT INTO t SELECT * FROM w")',
        'def run(con, *, sql):\n    con.execute(sql)\ndef f(con):\n    run(con, sql="DELETE FROM t")',
        'def run(con, sql, /):\n    con.execute(sql)\ndef f(con):\n    run(con, "DELETE FROM t")',
        'class A:\n    @classmethod\n    def run(cls, con, sql):\n        con.execute(sql)\ndef f(con):\n    A.run(con, "DELETE FROM t")',
        'class A:\n    def run(self, con, sql):\n        con.execute(sql)\ndef f(con, a):\n    a.run(con, sql="DELETE FROM t")',
        # each clause of the reader on its own, with a BUILT statement (an f-string starting with a placeholder, which no literal-write
        # check can see), so that removing the clause is seen: the helper by keyword, by position, keyword-only, positional-only,
        # classmethod and self-method; the aliases of the execute family; the wrappers and conditionals around the text
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, v):\n    run(con, sql=f"{v} FROM t")',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, v):\n    run(con, f"{v} FROM t")',
        'def run(con, *, sql):\n    con.execute(sql)\ndef f(con, v):\n    run(con, sql=f"{v} FROM t")',
        'def run(con, sql, /):\n    con.execute(sql)\ndef f(con, v):\n    run(con, f"{v} FROM t")',
        'class A:\n    @classmethod\n    def run(cls, con, sql):\n        con.execute(sql)\ndef f(con, v):\n    A.run(con, f"{v} FROM t")',
        'class A:\n    def run(self, con, sql):\n        con.execute(sql)\ndef f(con, a, v):\n    a.run(con, f"{v} FROM t")',
        'def f(con, v):\n    getattr(con, "execute")(f"{v} FROM t")',
        'def f(con, v):\n    con.exec_driver_sql(f"{v} FROM t")',
        'def f(con, v):\n    con.executemany(f"{v} FROM t", [])',
        'def f(con, v):\n    con.executescript(f"{v} FROM t")',
        'from sqlalchemy import text\ndef f(s, v):\n    s.execute(text(f"{v} FROM t"))',
        'from sqlalchemy import text\ndef f(s, v):\n    s.execute(text(f"{v} FROM t").bindparams(a=1))',
        'def f(con, v, x):\n    con.execute(f"{v} FROM t" if x else "SELECT 1")',
        'def f(con, v):\n    sql = f"{v} FROM t"\n    con.execute(sql)',
        'def f(con, v):\n    con.execute("SELECT 1; " + f"{v} FROM t")',
        # a helper that REASSIGNS the parameter it executes is no pass-through
        'def run(con, sql):\n    sql = sql.replace("main.", "")\n    con.execute(sql)\ndef f(con):\n    run(con, "DELETE FROM main.t")',
        'def run(con, t):\n    sql = "DELETE FROM " + t\n    con.execute(sql)\ndef f(con):\n    run(con, "SELECT 1")',
        # a parameter reassigned on SOME path stays a pass-through: the caller's text can still reach execute
        'def run(con, sql, flag):\n    if flag:\n        sql = "SELECT 1"\n    con.execute(sql)\ndef f(con, v):\n    run(con, f"{v} FROM t", False)',
        'def run(con, sql):\n    def g():\n        sql = "SELECT 1"\n        return sql\n    g()\n    con.execute(sql)\ndef f(con, v):\n    run(con, f"{v} FROM t")',
        # fragments of the prefix: stripping `ma` then `in.` strips `main.`
        'def run(con, sql):\n    con.execute(sql.replace("ma", "").replace("in.", ""))\ndef f(con):\n    run(con, "DELETE FROM main.t")',
        'def run(con, sql):\n    con.execute(sql.replace(".", ""))\ndef f(con):\n    run(con, "DELETE FROM main.t")',
        'def run(con, sql):\n    con.execute(sql.replace("n.", ""))\ndef f(con):\n    run(con, "DELETE FROM main.t")',
        # aliases of execute and of a helper, with a BUILT statement
        'def f(con, v):\n    ex = con.execute\n    ex(f"{v} FROM t")',
        'def f(con, v):\n    ex = getattr(con, "executemany")\n    ex(f"{v} FROM t", [])',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, v):\n    ex = run\n    ex(con, f"{v} FROM t")',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, v):\n    ex = run\n    ey = ex\n    ey(con, f"{v} FROM t")',
        # a callable used as a value the scan cannot follow
        'from functools import partial\ndef run(con, sql):\n    con.execute(sql)\ndef f(con, v):\n    partial(run, con)(f"{v} FROM t")',
        'def f(con, rows):\n    list(map(con.execute, rows))',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, rows):\n    list(map(run, rows))',
        # *args and **kwargs that could carry the statement are not resolvable
        'def f(con, args):\n    con.execute(*args)',
        'def f(con, kw):\n    con.execute(**kw)',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, a):\n    run(*a)',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con, kw):\n    run(con, **kw)',
        # a string method that takes the schema prefix OFF the text the helper executes
        'def run(con, sql):\n    con.execute(sql.replace("main.", ""))\ndef f(con):\n    run(con, "DELETE FROM main.t")',
        'def run(con, sql, x):\n    con.execute(sql.replace(x, ""))\ndef f(con):\n    run(con, "DELETE FROM main.t", "main.")',
        'def run(con, sql):\n    con.execute(sql.replace("MAIN.", ""))\ndef f(con):\n    run(con, "DELETE FROM main.t")',
        # a quoted `"main.t"` is a table of that odd name, not the schema
        'def f(con):\n    con.execute(\'DELETE FROM "main.t"\')',
        # ANALYZE and PRAGMA optimize write into every attached schema unless one is named
        'def f(con):\n    con.execute("ANALYZE")',
        'def f(con):\n    con.execute("ANALYZE t")',
        'def f(con):\n    con.execute("PRAGMA optimize")',
        # a method fetched by name is still the execute method
        'def f(con):\n    getattr(con, "execute")("DELETE FROM t")',
    ],
)
def test_the_scan_fails_on_every_unqualified_write_shape(snippet):
    assert _scan(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        'def f(con):\n    con.execute("INSERT INTO main.t (a) VALUES (1) ON CONFLICT(a) DO UPDATE SET a = 2")',
        'def f(con):\n    con.execute("REPLACE INTO main.t (a) VALUES (1)")',
        'def f(con):\n    con.execute("INSERT OR REPLACE INTO temp.merge_options (key, value) VALUES (?, ?)")',
        'def f(con):\n    con.executescript("DELETE FROM temp.x; DELETE FROM main.t")',
        'def f(con, t):\n    con.execute(f"DELETE FROM main.{t}")',
        'def f(con):\n    con.execute("SELECT * FROM t")',
        'def f(con):\n    con.execute("CREATE TEMP TABLE x (a INTEGER)")',
        'def f(con):\n    con.execute("DROP TABLE IF EXISTS temp.x")',
        'def f(con):\n    con.execute("PRAGMA main.table_info(t)")',
        'def f(con):\n    sql = "INSERT INTO main.t (a) VALUES (?)"\n    con.executemany(sql, [(1,)])',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con):\n    run(con, "SELECT 1")',
        'def f(con):\n    """UPDATE afterwards would rewrite every row."""\n    return 1',
        # the prefix in any case; a keyword spelling of a read; a comment in front of a qualified write
        'def f(con):\n    con.execute("DELETE FROM MAIN.t")',
        'def f(con):\n    con.execute("-- note\\nDELETE FROM main.t")',
        'def f(con):\n    con.execute(statement="SELECT 1")',
        'def run(con, *, sql):\n    con.execute(sql)\ndef f(con):\n    run(con, sql="SELECT 1")',
        'class A:\n    @classmethod\n    def run(cls, con, sql):\n        con.execute(sql)\ndef f(con):\n    A.run(con, "SELECT 1")',
        'def run(con, sql):\n    con.execute(sql.replace("{x}", "1"))\ndef f(con):\n    run(con, "SELECT {x}")',
        'def f(con):\n    con.execute("ANALYZE main.t")',
        'def f(con):\n    con.execute("PRAGMA main.optimize")',
        'def f(con):\n    getattr(con, "execute")("DELETE FROM main.t")',
        # aliases of readable calls, and a `.replace` that strips something else
        'def f(con):\n    ex = con.execute\n    ex("SELECT 1")',
        'def run(con, sql):\n    con.execute(sql)\ndef f(con):\n    ex = run\n    ex(con, "SELECT 1")',
        'def f(con):\n    ex = getattr(con, "execute")\n    ex("DELETE FROM main.t")',
        'def run(con, sql):\n    con.execute(sql.replace("{cols}", "a, b"))\ndef f(con):\n    run(con, "SELECT {cols} FROM t")',
        # readable shapes that a clause removed from the reader would turn into a failure (positional-only parameter, conditional)
        'def run(con, sql, /):\n    con.execute(sql)\ndef f(con):\n    run(con, "SELECT 1")',
        'def f(con, x):\n    con.execute("DELETE FROM main.t" if x else "DELETE FROM temp.t")',
        'def f(con):\n    con.executescript("SELECT 1; " + "DELETE FROM main.t")',
        # each wrapper the reader sees through, with a statement that is a read: removing the clause makes it unreadable
        'from sqlalchemy import text\ndef f(s):\n    s.execute(text("SELECT 1"))',
        'from sqlalchemy import text\ndef f(s):\n    s.execute(text("SELECT :a").bindparams(a=1))',
        'def f(con):\n    con.execute("SELECT %s" % 1)',
        'def f(con):\n    sql = "SELECT 1"\n    con.execute(sql)',
        'def f(con):\n    sql = "SELECT 1"\n    def g():\n        con.execute(sql)\n    g()',
        'SQL = "SELECT 1"\ndef f(con):\n    con.execute(SQL)',
        'def run(con, sql, flag):\n    if flag:\n        sql = "SELECT 1"\n    con.execute(sql)\ndef f(con):\n    run(con, "SELECT 2", False)',
    ],
)
def test_the_scan_passes_the_qualified_and_the_read_shapes(snippet):
    assert _scan(snippet) == [], snippet


def test_the_fts_bulk_indexer_the_merge_calls_names_main():
    """``fts.index_articles`` runs on the merge connection while the backup is attached and writes through ``_index_rows``: the scan reads
    ``merge.py`` only, so the one function in another module that writes there is read here."""
    import inspect
    import textwrap

    from src.database import fts

    source = textwrap.dedent(inspect.getsource(fts._index_rows))
    assert source.count("main.article_fts") >= 2 and "main.article_fts_norm" in source
    assert _scan(source) == []
    # `rebuild_index` runs on a fresh connection BEFORE the attach today; it names main too, so moving the attach earlier stays safe
    rebuild = textwrap.dedent(inspect.getsource(fts.rebuild_index))
    assert "main.article_fts_norm" in rebuild and _scan(rebuild) == []
    assert _classify(fts.REBUILD_MARK) == [] and fts.REBUILD_MARK.startswith("INSERT INTO main.article_fts")


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_bookkeeping_table_only_the_backup_has_is_never_written_to(tmp_path):
    """``merge_batches`` is created by the migrations, so every backup carries one. A corpus without it (``init_db`` makes that impossible,
    the test drops it on purpose) must make the merge FAIL, not record its batch in the incoming file."""
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        s.add(Article(url="https://s.example/1", canonical_url="https://s.example/1", source_id=src.id, title="T", content="c", hash="h1"))
        s.commit()
    with _corpus(live)() as s:
        s.commit()
    con = sqlite3.connect(live)
    try:
        con.execute("DROP TABLE merge_batches")
        con.commit()
    finally:
        con.close()
    before = _sha(inc)

    with pytest.raises(sqlite3.Error):
        merge_corpus(inc, live, _META)

    assert _sha(inc) == before, "the merge wrote into the attached backup"
