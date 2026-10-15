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
_READ_HEADS = {"SELECT", "PRAGMA", "ATTACH", "DETACH", "BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE", "VACUUM", "ANALYZE"}
_ANY_WRITE = re.compile(r"\b(INSERT|REPLACE|UPDATE|DELETE|DROP|ALTER|CREATE)\b", re.I)
_TEXT_WRAPPERS = {"text", "_text"}
_EXEC_METHODS = {"execute", "executemany", "executescript", "exec_driver_sql"}

#: Statements the scan cannot read to a text, or that name no schema on purpose, each with the reason. Keyed ``function: expression``.
_ALLOWED: dict[str, str] = {
    "_fts_insert_suspended: ddl": "the CREATE TRIGGER text read back from main's own sqlite_master, replayed on the same connection: it creates in main",
    "merge_corpus: fts_trigger_ddl": "the same stored CREATE TRIGGER text, handed to _restore_fts_insert_trigger",
    "_carry_live_settings: CREATE TABLE IF NOT EXISTS app_state": "runs on the working copy's own standalone connection, with nothing attached",
    "merge_custody: CREATE TABLE IF NOT EXISTS custody_imported_entries": "runs on custody_log.db's own standalone connection, with nothing attached",
    "merge_custody: sql": "the two SELECTs appended to `sources` just above (a chain's rows are only fetched by _custody_rows); no write reaches it",
}

_META = {
    "artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}


def _classify(sql: str) -> list[str]:
    """What is wrong with one statement text (``{}`` stands for a piece the source builds at run time): empty when it is a read, a
    temp-table statement, or a write that names ``main``."""
    problems: list[str] = []
    for stmt in (part.strip() for part in sql.split(";")):
        if not stmt:
            continue
        m = _WRITE.match(stmt)
        if m:
            target = m.group(2).strip('"')
            if target.startswith(_EXEMPT):
                continue
            if re.match(r"\s*(CREATE\s+(?:TEMP|TEMPORARY)\b)", stmt, re.I):
                continue
            problems.append(f"{' '.join(m.group(1).split()).upper()} {target}")
            continue
        head = re.match(r"\s*(\w+)", stmt)
        word = head.group(1).upper() if head else ""
        if word in _READ_HEADS:
            continue
        if word in {"CREATE", "WITH"} and re.match(r"\s*CREATE\s+(?:TEMP|TEMPORARY)\b", stmt, re.I):
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
        self.module_assigns = self._assigns(self.tree.body)
        self.passthrough: dict[str, set[int]] = {}
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
        params = {a.arg for a in fn.args.args if a.arg != "self"}
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
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"replace", "strip", "format", "lstrip"}:
            return self._origin_params(node.func.value, fn, seen)
        return None

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
            params = {a.arg for a in fn.args.args} if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) else set()
            if node.id in seen:
                return None
            pool = self._assigns(fn.body).get(node.id) if fn is not None else None  # type: ignore[attr-defined]
            if pool is None and node.id not in params:
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
            for fn in self.defs:
                params = [a.arg for a in fn.args.args if a.arg != "self"]  # type: ignore[attr-defined]
                for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and self._func_of(n) is fn):
                    for arg in self._sql_args(call):
                        origin = self._origin_params(arg, fn)
                        for name in origin or ():
                            idx = params.index(name)
                            if idx not in self.passthrough.setdefault(fn.name, set()):  # type: ignore[attr-defined]
                                self.passthrough[fn.name].add(idx)  # type: ignore[attr-defined]
                                changed = True
        # 2. every SQL-bearing call, read to a text (an argument made only of the caller's own parameters is checked at the caller's callers)
        for call in (n for n in ast.walk(self.tree) if isinstance(n, ast.Call)):
            fn = self._func_of(call)
            for arg in self._sql_args(call):
                if self._origin_params(arg, fn) is None:
                    self._check(call, arg)
        # 3. a string anywhere that starts like a write
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Constant, ast.JoinedStr)):
                text = self._texts(node, None)
                if text and _WRITE.match(text[0]) and not isinstance(self.parent.get(node), ast.Expr):
                    for problem in _classify(text[0]):
                        self._report(node, problem)
        return sorted(set(self.problems))

    def _sql_args(self, call: ast.Call) -> list[ast.expr]:
        """The arguments of ``call`` that are SQL: the first of an execute-like method, and the passed-through parameters of a helper."""
        f = call.func
        if isinstance(f, ast.Attribute) and f.attr in _EXEC_METHODS and call.args:
            return [call.args[0]]
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        return [call.args[i] for i in sorted(self.passthrough.get(name, ())) if i < len(call.args)] if name else []

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
    ],
)
def test_the_scan_passes_the_qualified_and_the_read_shapes(snippet):
    assert _scan(snippet) == [], snippet


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
