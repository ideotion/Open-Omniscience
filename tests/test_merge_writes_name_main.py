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

WHAT IT READS BEYOND ``execute``: PRAGMAs (a bare ``wal_checkpoint`` / ``optimize`` and a bare ``journal_mode`` being set reach every
attached database; a schema other than ``main`` / ``temp`` passes only as a read-only pragma), ``VACUUM <schema>``, a raw ``ATTACH`` (it
creates a file when the path is missing; ``connect.attach`` is the one place that does it), and the constructs that reach an execute
method or a database without a statement it can read: reflection (``getattr`` with a name that is not a literal, ``eval``, ``exec``,
``vars``, ``globals``, ``methodcaller``, ``__getattribute__`` ...), an execute method called on its class, ``backup`` / ``deserialize`` /
``blobopen``, and an ORM session import. Each is a problem for the allowlist to excuse with a reason; each has a planted case that fails
when its clause is removed. The functions in OTHER modules that receive the merge connection are pinned by name with a reason each.

THE SCAN'S STATED BOUNDARY (measured by planting each shape; a shape here is NOT caught, and is kept so it is counted, not forgotten):
 1. ORM session WRITES: ``session.add`` / ``add_all`` / ``delete`` / ``merge`` / ``bulk_*`` / ``query(...).update()`` are method names too
    common to flag. merge.py's sessions come from ``session_scope`` on the APP engine, a separate connection with no backup attached, so they
    cannot write into it; only importing ``sqlalchemy.orm`` / a Session name is a tripwire.
 2. A statement run by an object that is not a ``sqlite3`` / SQLAlchemy connection under another method name (``db.run_sql(...)``): the
    scan recognises the execute family by name only.
 3. A SQL function with a side effect: ``load_extension`` is refused by sqlite3 until ``enable_load_extension(True)`` is called (both are
    tripwires); ``writefile`` is a shell function the Python module does not define (measured: "no such function"), so a ``SELECT`` is read
    as a read.
 4. A cross-module callee reached by an alias (``h = g; h(con)``), by ``getattr(mod, "g")(con)``, as a method on an instance of an imported
    class (``ix.run(con)``), or given a connection under a name other than ``con`` / a ``db_connect`` / ``connect`` binding, or through an
    attribute (``self.con``): the pin below does not see it. The writes INSIDE the pinned callees are read by a person, once.
 5. A tripwire name reached through an alias of the PRIMITIVE: ``g_ = getattr``, ``builtins.getattr`` / ``builtins.eval``,
    ``from operator import methodcaller as mc``, ``inspect.getattr_static``, and an execute method on its class spelled
    ``type(con).execute(con, sql)`` / ``con.__class__.execute(con, sql)`` (only the capitalised spelling ``sqlite3.Connection.execute`` is
    caught).
 6. The lexical shape of a statement, not its meaning, over-reports and never misses: ``WITH ... INSERT`` is flagged even when qualified, a
    quoted ``"main"."t"`` is flagged although it is main, and a prose string that starts with "Update" / "Create table" is read as a
    write. (A ``;`` inside a literal, a quoted name or a comment, and the conflict clause of ``UPDATE OR IGNORE``, used to over-report too: they are
    read as SQLite reads them since ``_statements``; a text that does not close falls back to every ``;``.)
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
    r"\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM|DROP\s+(?:TABLE|INDEX|VIEW|TRIGGER)(?:\s+IF\s+EXISTS)?"
    r"|ALTER\s+TABLE|CREATE\s+(?:TABLE|VIRTUAL\s+TABLE|INDEX|UNIQUE\s+INDEX|TRIGGER|VIEW)(?:\s+IF\s+NOT\s+EXISTS)?)\s+(\"?[\w{}.]+\"?)",
    re.I,
)
_READ_HEADS = {"SELECT", "PRAGMA", "ATTACH", "DETACH", "BEGIN", "COMMIT", "END", "ROLLBACK", "SAVEPOINT", "RELEASE", "VACUUM"}
_ANY_WRITE = re.compile(r"\b(INSERT|REPLACE|UPDATE|DELETE|DROP|ALTER|CREATE)\b", re.I)
_TEXT_WRAPPERS = {"text", "_text"}
_EXEC_METHODS = {"execute", "executemany", "executescript", "exec_driver_sql"}
#: The pragmas that reach EVERY attached schema when none is named AND change a file's content (``wal_checkpoint`` empties the backup's
#: log, ``optimize`` analyses it; ``locking_mode`` / ``secure_delete`` / ``mmap_size`` also reach it but write nothing, so they are not listed),
#: and the ones whose setting form rewrites a file's header or journal; a foreign-schema pragma passes only as one of the READ-ONLY pragmas.
_BARE_REACHES_ALL = {"optimize", "wal_checkpoint"}
_SET_REACHES_ALL = {"journal_mode"}  # `PRAGMA journal_mode = X` with no schema applies to every attached database
_READ_ONLY_PRAGMAS = {
    "table_info", "table_xinfo", "table_list", "index_list", "index_info", "index_xinfo", "foreign_key_list", "foreign_key_check",
    "quick_check", "integrity_check", "database_list", "page_count", "freelist_count", "data_version",
}
_READ_UNLESS_SET = {"user_version", "application_id", "schema_version", "page_size", "auto_vacuum", "journal_mode"}
_PRAGMA = re.compile(r"\s*PRAGMA\s+(?:(\w+|\{\})\s*\.\s*)?(\w+|\{\})\s*([=(])?", re.I)
#: Names that can reach an execute method (or any callable) without the scan being able to read which: a construct using one is a problem.
_REFLECTION_NAMES = {"eval", "exec", "vars", "globals", "locals", "__import__", "methodcaller", "attrgetter"}
_REFLECTION_ATTRS = {"__getattribute__", "__dict__", "methodcaller", "attrgetter"}
#: ``sqlite3.Connection`` methods that move or write a whole database without a statement the scan reads (``backup`` copies a database into a
#: target's ``main``; ``deserialize`` replaces a schema's contents; ``blobopen`` writes a blob), and the one that lets SQL load code.
_FILE_METHODS = {"backup", "deserialize", "blobopen", "enable_load_extension", "load_extension"}
#: An ORM session writes through table names that name no schema (``session.add``). merge.py's sessions come from ``session_scope`` on the
#: APP engine, a separate connection with no backup attached, so they cannot reach it; importing ``sqlalchemy.orm`` here is the tripwire.
_ORM_NAMES = {"Session", "sessionmaker", "scoped_session", "AsyncSession"}

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


def _pragma_problems(stmt: str) -> list[str]:
    """What is wrong with one PRAGMA: it reaches the attached backup (bare ``wal_checkpoint`` / ``optimize``, a bare ``journal_mode`` being
    SET, ``writable_schema`` being set) or it names a schema that is not ``main`` / ``temp`` and is not one of the read-only pragmas."""
    stmt = re.sub(r"/\*.*?\*/|--[^\n]*", " ", stmt, flags=re.S)  # `PRAGMA inc.user_version /*c*/ = 7` still sets it
    m = _PRAGMA.match(stmt)
    if m is None:
        return [f"cannot classify: {stmt[:60]!r}"]
    schema, name, sets = (m.group(1) or "").lower(), m.group(2).lower(), m.group(3) is not None
    if name == "{}":
        return ["PRAGMA with a name the scan cannot read"]
    if not schema and name in _BARE_REACHES_ALL:
        return [f"PRAGMA {name} names no schema"]
    if not schema and sets and name in _SET_REACHES_ALL:
        return [f"PRAGMA {name} is set with no schema (it applies to every attached database)"]
    if name == "writable_schema" and sets:
        return ["PRAGMA writable_schema lets a statement edit any schema's catalogue"]
    if schema and schema not in ("main", "temp"):
        if name in _READ_ONLY_PRAGMAS or (name in _READ_UNLESS_SET and not sets):
            return []
        return [f"PRAGMA {schema}.{name} is not a known read-only pragma on a schema that is not main"]
    return []


def _statements(sql: str) -> list[str]:
    """The statements of one text, split at the ``;`` that SQLite itself would end a statement at: a ``;`` inside a string literal (``'a;b'``),
    a quoted name (``"a;b"``, backtick, ``[a;b]``) or a comment (``-- x;`` / ``/* x; */``) does not end one. A text this reading cannot close
    (an unterminated quote or comment) falls back to splitting at every ``;``, which can only report MORE statements, never hide one."""
    out: list[str] = []
    start = i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"`":
            j = sql.find(c, i + 1)  # a doubled quote (``'it''s'``) reads as two literals side by side, which hides the same ``;``
            if j == -1:
                return sql.split(";")
            i = j + 1
        elif c == "[":
            j = sql.find("]", i + 1)
            if j == -1:
                return sql.split(";")
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j == -1:
                return sql.split(";")
            i = j + 2
        elif c == ";":
            out.append(sql[start:i])
            start = i = i + 1
        else:
            i += 1
    out.append(sql[start:])
    return out


def _classify(sql: str) -> list[str]:
    """What is wrong with one statement text (``{}`` stands for a piece the source builds at run time): empty when it is a read, a
    temp-table statement, or a write that names ``main``. The schema prefix is compared case-insensitively and must be the BARE word:
    a quoted ``"main.t"`` is a table of that odd name, in main."""
    problems: list[str] = []
    for stmt in (_strip_leading_comments(part) for part in _statements(sql)):
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
        if word == "PRAGMA":
            problems.extend(_pragma_problems(stmt))
            continue
        if word == "VACUUM":  # a bare VACUUM and `VACUUM INTO` rewrite main (or write a NEW file); `VACUUM inc` rewrites the backup
            rest = _strip_leading_comments(re.sub(r"(?i)^\s*VACUUM", "", stmt, count=1))
            if rest and not re.match(r"(?i)INTO\b", rest):  # anything else is a schema: bare, quoted, bracketed or built
                vm = re.match(r"(?i)(main|temp)\s*(?:INTO\b.*)?$", rest, re.S)
                into_only = re.match(r"(?i)[^\s]+\s+INTO\b", rest)  # `VACUUM inc INTO 'x'` only READS inc into a new file
                if not vm and not into_only:
                    problems.append(f"VACUUM {rest.split()[0]} rewrites a schema that is not main")
            continue
        if word == "ATTACH":  # an ATTACH of a path that does not exist CREATES a database file: it goes through connect.attach
            problems.append("ATTACH (use connect.attach, which the callers pin)")
            continue
        if word in _READ_HEADS:
            continue
        if word == "CREATE" and re.match(r"\s*CREATE\s+(?:TEMP|TEMPORARY)\s+TRIGGER\b", stmt, re.I):
            # a trigger body cannot qualify its tables, so a TEMP trigger on main.t that runs `DELETE FROM u` deletes from the
            # ATTACHED `u` when main has none: the body is a write the first-piece exemption below would skip
            problems.append("CREATE TEMP TRIGGER (its body names no schema)")
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
        # 5. the ways to reach a write that name neither a statement nor an execute method the scan reads (each is a problem, and the
        #    allowlist can say why one is fine): reflection, a dynamic attribute name, an execute method called on its class, the sqlite3
        #    methods that write a named database, and an ORM session
        self._tripwires()
        return sorted(set(self.problems))

    def _tripwires(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and node.id in _REFLECTION_NAMES and isinstance(node.ctx, ast.Load):
                self._report(node, f"{node.id} can reach an execute method the scan cannot see")
            elif isinstance(node, ast.Attribute) and node.attr in _REFLECTION_ATTRS:
                self._report(node, f"{node.attr} can reach an execute method the scan cannot see")
            elif isinstance(node, ast.Attribute) and node.attr in _FILE_METHODS:  # called, aliased (`bo = con.blobopen`) or mapped
                self._report(node, f"{node.attr} moves or writes a database without a statement the scan reads")
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id == "getattr":
                    arg = node.args[1] if len(node.args) >= 2 else None
                    literal = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
                    if literal is None:
                        self._report(node, "getattr with a name the scan cannot read")
                    elif literal in _FILE_METHODS:
                        self._report(node, f"{literal} reached by getattr")
                elif isinstance(f, ast.Attribute):
                    if f.attr in _EXEC_METHODS:  # `sqlite3.Connection.execute(con, sql)`: the statement is not the first argument
                        owner = f.value.id if isinstance(f.value, ast.Name) else f.value.attr if isinstance(f.value, ast.Attribute) else ""
                        if owner[:1].isupper():
                            self._report(node, f"{f.attr} called on the class {owner}")
            elif isinstance(node, (ast.ImportFrom, ast.Import)):
                modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
                names = {a.name for a in node.names} if isinstance(node, ast.ImportFrom) else set()
                if any(m == "sqlalchemy.orm" or m.startswith("sqlalchemy.orm.") for m in modules) or names & _ORM_NAMES or ("orm" in names and modules == ["sqlalchemy"]):
                    self._report(node, "an ORM session writes through table names that name no schema")

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
        # PRAGMAs that reach the attached backup: bare, naming the backup, or being SET with no schema
        'def f(con):\n    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")',
        'def f(con):\n    con.execute("PRAGMA inc.wal_checkpoint(TRUNCATE)")',
        'def f(con):\n    con.execute("PRAGMA inc.optimize")',
        'def f(con):\n    con.execute("PRAGMA inc.user_version = 3")',
        'def f(con):\n    con.execute("PRAGMA inc.user_version(3)")',
        'def f(con):\n    con.execute("PRAGMA inc.incremental_vacuum")',
        'def f(con):\n    con.execute("PRAGMA inc.journal_mode = DELETE")',
        'def f(con):\n    con.execute("PRAGMA journal_mode = WAL")',
        'def f(con):\n    con.execute("PRAGMA journal_mode=WAL")',
        'def f(con):\n    con.execute("PRAGMA writable_schema = 1")',
        'def f(con, v):\n    con.execute(f"PRAGMA {v}")',
        'def f(con, v):\n    con.execute(f"PRAGMA inc.{v}")',
        # VACUUM of the backup (with or without INTO), built or literal; an ATTACH, which creates a file when the path is missing
        'def f(con):\n    con.execute("VACUUM inc")',
        'def f(con):\n    con.execute(\'VACUUM "inc"\')',
        'def f(con):\n    con.execute("VACUUM [inc]")',
        'def f(con):\n    con.execute("VACUUM main2")',
        'def f(con):\n    con.execute("VACUUM /* c */ inc")',
        'def f(con, s):\n    con.execute(f\'VACUUM "{s}"\')',
        'def f(con, v):\n    con.execute(f"VACUUM {v}")',
        # a TEMP trigger's body cannot qualify its tables: `DELETE FROM u` deletes from the attached `u` when main has none
        'def f(con):\n    con.execute("CREATE TEMP TRIGGER tr AFTER INSERT ON main.t BEGIN DELETE FROM u; END")',
        'def f(con):\n    con.execute("CREATE TEMPORARY TRIGGER tr INSTEAD OF INSERT ON v BEGIN DELETE FROM u; END")',
        # a comment between the pragma name and the `=` still sets it
        'def f(con):\n    con.execute("PRAGMA inc.user_version /* c */ = 7")',
        'def f(con):\n    con.execute("PRAGMA inc.user_version -- c\\n = 7")',
        # the connection-level load of code, a tripwire name reached through an alias, a map or a literal getattr
        'def f(con):\n    con.enable_load_extension(True)',
        'def f(con):\n    con.load_extension("x")',
        'def f(con, v):\n    bo = con.blobopen\n    bo("t", "c", 1)',
        'def f(con, rows):\n    list(map(con.deserialize, rows))',
        'def f(con, b):\n    getattr(con, "deserialize")(b, name="inc")',
        'from sqlalchemy.orm.query import Query',
        'def f(con):\n    con.execute("ATTACH DATABASE \'x.db\' AS bk")',
        'def f(con, v):\n    con.execute(f"ATTACH DATABASE ? AS {v}", ("x.db",))',
        # reflection and dynamic attribute names reach an execute method with a BUILT statement the literal check cannot see
        'def f(con, n, v):\n    getattr(con, n)(f"{v} FROM t")',
        'def f(con, v):\n    getattr(con, "exe" + "cute")(f"{v} FROM t")',
        'def f(con, n, v):\n    ex = getattr(con, n)\n    ex(f"{v} FROM t")',
        'def f(con, v):\n    getattr(con)(f"{v} FROM t")',
        'import operator\ndef f(con, v):\n    operator.methodcaller("execute", f"{v} FROM t")(con)',
        'from operator import methodcaller\ndef f(con, v):\n    methodcaller("execute", f"{v} FROM t")(con)',
        'from operator import attrgetter\ndef f(con, v):\n    attrgetter("execute")(con)(f"{v} FROM t")',
        'import operator\ndef f(con, v):\n    operator.attrgetter("execute")(con)(f"{v} FROM t")',
        'def f(con, v):\n    con.__getattribute__("execute")(f"{v} FROM t")',
        'def f(con, v):\n    vars(type(con))["execute"](con, f"{v} FROM t")',
        'def f(con, v):\n    eval("con.execute")(f"{v} FROM t")',
        'def f(con, v):\n    exec("con.execute(v)")',
        'def f(con, v):\n    globals()["run"](con, f"{v} FROM t")',
        'def f(con, v):\n    locals()["ex"](f"{v} FROM t")',
        'def f(con, v):\n    __import__("sqlite3")',
        'def f(con):\n    con.__dict__["execute"]("SELECT 1")',
        # an execute method called on its class takes the connection first, so the statement is the SECOND argument
        'import sqlite3\ndef f(con, v):\n    sqlite3.Connection.execute(con, f"{v} FROM t")',
        'def f(con, v):\n    Connection.executemany(con, f"{v} FROM t", [])',
        # the sqlite3 methods that write a named database without a statement
        'def f(con, d):\n    con.backup(d, name="inc")',
        'def f(con, b):\n    con.deserialize(b, name="inc")',
        'def f(con):\n    con.blobopen("t", "c", 1, name="inc")',
        # an ORM session names no schema in what it writes
        'from sqlalchemy.orm import Session',
        'from sqlalchemy.orm import sessionmaker',
        'import sqlalchemy.orm',
        'from sqlalchemy import orm',
        'from sqlalchemy import Session',
        'from sqlalchemy import sessionmaker',
        'from sqlalchemy import scoped_session',
        'from sqlalchemy.ext.asyncio import AsyncSession',
        # a PRAGMA the pragma reader cannot parse (a quoted schema) is a problem, not a skip
        'def f(con):\n    con.execute(\'PRAGMA "inc".user_version = 3\')',
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
        # the PRAGMAs the merge reads from the backup, the connection-level ones, and the ones that name main or temp
        'def f(con, t):\n    con.execute(f\'PRAGMA inc.table_info("{t}")\')',
        'def f(con):\n    con.execute("PRAGMA inc.index_list(t)")',
        'def f(con):\n    con.execute("PRAGMA inc.index_info(i)")',
        'def f(con):\n    con.execute("PRAGMA inc.user_version")',
        'def f(con):\n    con.execute("PRAGMA quick_check")',
        'def f(con):\n    con.execute("PRAGMA foreign_key_check")',
        'def f(con):\n    con.execute("PRAGMA foreign_keys=OFF")',
        'def f(con):\n    con.execute("PRAGMA temp_store=2")',
        'def f(con):\n    con.execute("PRAGMA cache_size=-1024")',
        'def f(con):\n    con.execute("PRAGMA main.journal_mode = WAL")',
        'def f(con):\n    con.execute("PRAGMA main.wal_checkpoint(PASSIVE)")',
        'def f(con):\n    con.execute("PRAGMA temp.table_info(t)")',
        'def f(con):\n    con.execute("PRAGMA journal_mode")',
        # VACUUM of main, bare or INTO a new file
        'def f(con):\n    con.execute("VACUUM")',
        'def f(con):\n    con.execute("VACUUM main")',
        'def f(con):\n    con.execute("VACUUM INTO \'x.db\'")',
        'def f(con):\n    con.execute("VACUUM inc INTO \'x.db\'")',  # reads inc into a NEW file; inc is unchanged (measured)
        'def f(con):\n    con.execute("VACUUM temp")',
        'def f(con):\n    con.execute("VACUUM /* c */ main")',
        'def f(con):\n    con.execute("PRAGMA inc.data_version")',
        # a getattr with a literal name, and the names the tripwires leave alone
        'def f(exc):\n    return getattr(exc, "winerror", None)',
        'def f(con):\n    return con.iterdump()',
        'from sqlalchemy import select, text',
        'import sqlite3\ndef f(path):\n    return sqlite3.connect(path)',
        'def f(sql):\n    sql.locals = 1\n    return sql',
    ],
)
def test_the_scan_passes_the_qualified_and_the_read_shapes(snippet):
    assert _scan(snippet) == [], snippet


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("DELETE FROM main.a; DELETE FROM main.b", ["DELETE FROM main.a", " DELETE FROM main.b"]),
        ("SELECT 'a;b'", ["SELECT 'a;b'"]),  # a string literal
        ("SELECT 'it''s;'; SELECT 2", ["SELECT 'it''s;'", " SELECT 2"]),  # a doubled quote stays inside the literal
        ('SELECT "a;b" FROM main.t', ['SELECT "a;b" FROM main.t']),  # a quoted name
        ("SELECT `a;b` FROM main.t", ["SELECT `a;b` FROM main.t"]),
        ("SELECT [a;b] FROM main.t", ["SELECT [a;b] FROM main.t"]),
        ("-- x; DELETE FROM u\nSELECT 1", ["-- x; DELETE FROM u\nSELECT 1"]),  # a line comment, to the end of its line
        ("SELECT 1 -- x\n; SELECT 2", ["SELECT 1 -- x\n", " SELECT 2"]),  # ... and a real ; after the comment still ends the statement
        ("/* x; DELETE FROM u */ SELECT 1", ["/* x; DELETE FROM u */ SELECT 1"]),
        ("SELECT 1; /* x */ SELECT 2", ["SELECT 1", " /* x */ SELECT 2"]),
        # ``*/`` ends a comment at the ``/``: the ``*`` of ``*2`` is not the start of another one
        ("SELECT 1 /*a*/*2; DELETE FROM u /* c */", ["SELECT 1 /*a*/*2", " DELETE FROM u /* c */"]),
        # an apostrophe INSIDE a comment must not open a string that swallows the real ``;`` after it
        ("DELETE FROM main.t -- it's\n; DELETE FROM u -- it's", ["DELETE FROM main.t -- it's\n", " DELETE FROM u -- it's"]),
        # what it cannot close falls back to every ``;`` (more statements, never fewer)
        ("SELECT 'a; DELETE FROM u", ["SELECT 'a", " DELETE FROM u"]),
        ('SELECT "a; DELETE FROM u', ['SELECT "a', " DELETE FROM u"]),
        ("SELECT [a; DELETE FROM u", ["SELECT [a", " DELETE FROM u"]),
        ("SELECT 1 /* a; DELETE FROM u", ["SELECT 1 /* a", " DELETE FROM u"]),
        ("", [""]),
        ("SELECT 1;", ["SELECT 1", ""]),
    ],
)
def test_statements_ends_a_statement_where_sqlite_does(text, expected):
    assert _statements(text) == expected


@pytest.mark.parametrize(
    "snippet",
    [
        # the ``;`` inside a literal / quoted name / comment is not a second statement, and an UPDATE's conflict clause is not its target
        'def f(con):\n    con.execute("INSERT INTO main.t (a) VALUES (\'x;y\')")',
        'def f(con):\n    con.execute("DELETE FROM main.t WHERE a = \'it\'\'s;\'")',
        'def f(con):\n    con.execute("UPDATE main.t SET a = \'x;y\' WHERE b = 1")',
        'def f(con):\n    con.execute("UPDATE OR IGNORE main.t SET a = 1")',
        'def f(con):\n    con.execute("UPDATE OR REPLACE temp.x SET a = 1")',
        'def f(con):\n    con.execute("-- a; b\\nDELETE FROM main.t")',
        'def f(con):\n    con.execute("DELETE FROM main.t /* a; b */")',
    ],
)
def test_a_semicolon_in_a_literal_and_an_update_conflict_clause_are_not_reported(snippet):
    assert _scan(snippet) == [], snippet


@pytest.mark.parametrize(
    "snippet",
    [
        # a real second statement after a literal that holds a ``;`` is still read
        'def f(con):\n    con.execute("DELETE FROM main.t WHERE a = \'x;y\'; DELETE FROM u")',
        'def f(con):\n    con.execute("SELECT \'it\'\'s;\'; DELETE FROM u")',
        'def f(con):\n    con.execute("SELECT 1 -- it\'s\\n; DELETE FROM u -- it\'s")',
        'def f(con):\n    con.execute("SELECT 1 /* a */; DELETE FROM u")',
        # an unclosed quote or comment makes every ``;`` count
        'def f(con):\n    con.execute("SELECT \'a; DELETE FROM u")',
        'def f(con):\n    con.execute("SELECT 1 /* a; DELETE FROM u")',
        # the conflict clause does not hide an unqualified target
        'def f(con):\n    con.execute("UPDATE OR IGNORE t SET a = 1")',
        'def f(con):\n    con.execute("UPDATE OR REPLACE main_t SET a = 1")',
    ],
)
def test_the_scan_still_fails_on_the_shapes_the_semicolon_reading_could_hide(snippet):
    assert _scan(snippet), snippet


#: The functions OUTSIDE ``merge.py`` that receive the merge connection, each with why it is not a way to write unqualified. The scan reads
#: ``merge.py`` only, so a callee in another module is read by a person once, here, and a NEW one fails the test below until it is.
_CROSS_MODULE_CALLEES: dict[str, str] = {
    "src.backup.country_codes.normalise_staged_country_codes": "writes only `{schema}.\"table\"` UPDATEs (schema='inc', the disposable staged copy, on purpose; its docstring says never main) and a SAVEPOINT",
    "src.backup.country_codes.store_form_of": "a read of the country-form marker of one named schema (`read_form_in`: a SELECT on `{schema}.app_state`)",
    "src.database.connect._is_sqlcipher_conn": "reads the connection's type",
    "src.database.connect.attach": "the one ATTACH, with a bound path and a fixed alias",
    "src.database.fts.index_articles": "writes through `_index_rows`, which names `main.` (test_the_fts_bulk_indexer_the_merge_calls_names_main)",
    "src.database.fts.rebuild_index": "names `main.` too (the same test)",
}


def _callees_with_the_connection(source: str) -> set[str]:
    """Dotted names of the imported functions the module calls with one of its connections as an argument: ``con``, and every name
    assigned from ``db_connect(...)`` / ``connect(...)``. A connection under another name, or reached through an attribute, is not seen
    (the boundary in the module docstring)."""
    tree = ast.parse(source)
    imported: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                base = "." * n.level + (n.module or "")
                imported[a.asname or a.name] = f"{base}.{a.name}" if n.module else f"{base}{a.name}"  # `from . import fts` -> `.fts`
        elif isinstance(n, ast.Import):
            for a in n.names:
                imported[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
    conns = {"con"}

    def opens_a_connection(value: ast.AST | None) -> bool:
        if isinstance(value, ast.Tuple):  # `c, n = db_connect(p), 1`
            return any(opens_a_connection(e) for e in value.elts)
        f = value.func if isinstance(value, ast.Call) else None
        return (f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)) in {"db_connect", "connect"}

    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and opens_a_connection(n.value):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            conns |= {x.id for t in targets for x in ast.walk(t) if isinstance(x, ast.Name)}  # tuple unpacking binds each name
        elif isinstance(n, ast.With):
            conns |= {x.id for i in n.items if opens_a_connection(i.context_expr) and i.optional_vars is not None
                      for x in ast.walk(i.optional_vars) if isinstance(x, ast.Name)}
    def carries(node: ast.AST) -> bool:
        """The argument is a connection, or holds one (``[con]``, ``(con,)``, ``*args``, ``{"c": con}``), or is a cursor of one
        (``con.cursor()``). A call nested in an argument is a call of its own, read on its own: ``canonical_country(v, store_form_of(con))``
        hands the connection to ``store_form_of`` and a string to the other."""
        if isinstance(node, ast.Name):
            return node.id in conns
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return any(carries(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return any(carries(v) for v in node.values)
        if isinstance(node, ast.Starred):
            return carries(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            return carries(node.func.value)
        return False

    out: set[str] = set()
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = call.func
        parts: list[str] = []
        root: ast.expr = f
        while isinstance(root, ast.Attribute):  # `a.b.g` is read from its root name outward
            parts.insert(0, root.attr)
            root = root.value
        if not (isinstance(root, ast.Name) and root.id in imported):
            continue
        dotted = ".".join([imported[root.id], *parts])
        if any(carries(a) for a in [*call.args, *(k.value for k in call.keywords)]):
            out.add(dotted)
    return out


def test_the_functions_in_other_modules_that_get_the_merge_connection_are_the_reviewed_ones():
    seen = _callees_with_the_connection(_MERGE.read_text(encoding="utf-8"))
    assert seen == set(_CROSS_MODULE_CALLEES), (
        "a function in another module now receives the merge connection while a backup is attached: read what it writes (every write must "
        "name `main.`, `temp.` or the staged alias on purpose) and add it to _CROSS_MODULE_CALLEES with the reason; or it no longer does, "
        f"so drop it. New: {sorted(seen - set(_CROSS_MODULE_CALLEES))}; gone: {sorted(set(_CROSS_MODULE_CALLEES) - seen)}"
    )
    assert all(why.strip() for why in _CROSS_MODULE_CALLEES.values())


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("from a.b import g\ndef f(con):\n    g(con)", {"a.b.g"}),
        ("from a.b import g\ndef f(con):\n    g(1, conn=con)", {"a.b.g"}),
        ("import a.b\ndef f(con):\n    a.b.g(con)", {"a.b.g"}),
        ("import a.b as ab\ndef f(con):\n    ab.g(con)", {"a.b.g"}),
        ("import a\ndef f(con):\n    a.g(con)", {"a.g"}),
        ("from a import g\nfrom x import db_connect\ndef f(p):\n    c = db_connect(p)\n    g(c)", {"a.g"}),
        ("from a import g as h\ndef f(con):\n    h(con)", {"a.g"}),
        ("import sqlite3\nfrom a import g\ndef f(p):\n    c = sqlite3.connect(p)\n    g(c)", {"a.g"}),
        ("from a import g\ndef f(con):\n    g(1)", set()),
        ("from a import g\ndef f(con):\n    g([con])", {"a.g"}),
        ("from a import g\ndef f(con):\n    g(*[con])", {"a.g"}),
        ("from a import g\ndef f(con):\n    g(x={'c': con})", {"a.g"}),
        ("from a import g\ndef f(con):\n    g(con.cursor())", {"a.g"}),
        ("import threading\nfrom a import g\ndef f(con):\n    threading.Thread(target=g, args=(con,))", {"threading.Thread"}),
        ("from a import g, v\ndef f(con):\n    g(v(1), v(con))", {"a.v"}),  # a call nested in an argument is read on its own
        ("from . import fts\ndef f(con):\n    fts.index(con)", {".fts.index"}),
        ("from .x import g\ndef f(con):\n    g(con)", {".x.g"}),
        ("from a import g\nfrom x import db_connect\ndef f(p):\n    with db_connect(p) as c:\n        g(c)", {"a.g"}),
        ("from a import g\nfrom x import db_connect\ndef f(p):\n    c: object = db_connect(p)\n    g(c)", {"a.g"}),
        ("from a import g\nfrom x import db_connect\ndef f(p):\n    if (c := db_connect(p)):\n        g(c)", {"a.g"}),
        ("from a import g\nfrom x import db_connect\ndef f(p):\n    c, d = db_connect(p), 1\n    g(c)", {"a.g"}),
        ("def f(con):\n    local(con)", set()),
    ],
)
def test_the_cross_module_reader_sees_a_connection_handed_to_an_imported_function(snippet, expected):
    assert _callees_with_the_connection(snippet) == expected


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
