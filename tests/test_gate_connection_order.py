"""Connection first, then the gate, at EVERY place that takes both (the read of the follow-on, finding M1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULE. A writer that holds a pooled connection while it queues for the write gate is safe only if EVERY other taker of both asks for the
connection first. ``before_flush`` and ``do_orm_execute`` now check the connection out before they ask for the gate (so a gate holder never
waits out the pool's timeout with the whole write queue behind it); a raw ``with write_lock(), engine.connect()`` still took the gate FIRST, so
the two orders met: the queued ORM writers held the pool's connections, the gate holder waited for one, and every one of them stood for the
pool timeout (reproduced with a pool of two: the holder failed with ``TimeoutError`` after 3.3 s where it took 0.3 s before).

Three kinds of test, none of which reads a count of lines:
  * the scan: no ``with write_lock(...)`` in ``src/`` asks for a pooled connection AFTER the gate (in a later item of the same ``with``, or in
    its body), and the scan itself is proved on snippets of every wrong and every right shape;
  * the probe: for each site that was wrong, the pool has a connection out of it when the gate is first asked for;
  * the headline: with the pool's only connection out, a site waits for the pool WITHOUT the gate held.
What this does not see: a connection checked out deeper in a call made under the gate (a function the body calls). The scan is syntactic; a
checkout under the gate that it cannot see shows in a bundle as a pool timeout while the gate is held.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from src.database import writer

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
#  the scan
# --------------------------------------------------------------------------- #
_NOT_A_POOL = {"sqlite3", "duckdb", "apsw", "socket", "psycopg", "psycopg2"}


def _is_write_lock(item: ast.withitem) -> bool:
    e = item.context_expr
    return isinstance(e, ast.Call) and (
        (isinstance(e.func, ast.Name) and e.func.id == "write_lock") or (isinstance(e.func, ast.Attribute) and e.func.attr == "write_lock")
    )


def _kind(call: ast.Call) -> str | None:
    """What a call asks the pool for: ``hard`` (an engine's connect, raw_connection or begin: always a checkout), ``session`` (a session's
    connection(): a checkout unless it already holds one) or ``nested`` (begin_nested: a checkout unless it already holds a connection)."""
    f = call.func
    if not isinstance(f, ast.Attribute):
        return None
    receiver = ast.unparse(f.value)
    if receiver.split(".")[0] in _NOT_A_POOL:
        return None
    if f.attr in ("connect", "raw_connection"):
        return "hard"
    if f.attr == "begin" and receiver.split(".")[-1] in ("engine", "eng", "_engine"):
        return "hard"
    if f.attr == "connection":
        return "session"
    if f.attr == "begin_nested":
        return "nested"
    return None


def _calls(nodes: list[ast.AST]) -> list[ast.Call]:
    return [c for n in nodes for c in ast.walk(n) if isinstance(c, ast.Call)]


def _function_asks_for_a_connection_before(func: ast.AST | None, line: int) -> bool:
    """Whether the function that holds the ``with`` calls ``connection_first(...)`` or ``<session>.connection()`` on an earlier line."""
    if func is None:
        return False
    for call in _calls([func]):
        if call.lineno >= line:
            continue
        f = call.func
        if (isinstance(f, ast.Name) and f.id == "connection_first") or (isinstance(f, ast.Attribute) and f.attr in ("connection_first", "connection")):
            return True
    return False


def offenders(source: str) -> list[tuple[int, str]]:
    """The ``(line, call)`` of every pooled-connection checkout that comes AFTER a ``write_lock()`` in the same ``with`` or in its body."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def function_of(node: ast.AST) -> ast.AST | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    found: list[tuple[int, str]] = []
    for w in ast.walk(tree):
        if not isinstance(w, (ast.With, ast.AsyncWith)):
            continue
        for i, item in enumerate(w.items):
            if not _is_write_lock(item):
                continue
            after = [it.context_expr for it in w.items[i + 1 :]] + list(w.body)
            for call in _calls(after):
                kind = _kind(call)
                if kind is None:
                    continue
                if kind == "nested" and _function_asks_for_a_connection_before(function_of(w), w.lineno):
                    continue
                found.append((call.lineno, ast.unparse(call)[:60]))
    return sorted(set(found))


def test_no_with_write_lock_in_src_asks_for_a_pooled_connection_after_the_gate():
    bad: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for line, call in offenders(path.read_text(encoding="utf-8")):
            bad.append(f"{path.relative_to(ROOT)}:{line}  {call}")
    assert not bad, "the connection first, then the gate (src/database/writer.py connection_first):\n  " + "\n  ".join(bad)


@pytest.mark.parametrize(
    "source",
    [
        "def f(engine):\n    with write_lock(), engine.connect() as c:\n        pass\n",
        "def f(engine):\n    with write_lock(), engine.connect().execution_options(isolation_level='AUTOCOMMIT') as c:\n        pass\n",
        "def f(engine):\n    with write_lock(), engine.begin() as c:\n        pass\n",
        "def f(engine):\n    with write_lock():\n        with engine.begin() as c:\n            pass\n",
        "def f(engine):\n    with write_lock():\n        raw = engine.raw_connection()\n",
        "def f(session):\n    with write_lock():\n        conn = session.connection()\n",
        "def f(session):\n    with write_lock(timeout=3), session.begin_nested():\n        pass\n",
        "def f(self):\n    with corpus_lease('x'), write_lock():\n        conn = self.session.connection()\n",
        "def f(session):\n    session.add(1)\n    with write_lock(), session.begin_nested():\n        pass\n",
        "def f(session):\n    with write_lock(), session.begin_nested():\n        pass\n    session.connection()\n",
    ],
    ids=[
        "connect", "connect-autocommit", "begin", "begin-nested-in-body", "raw", "session-connection", "begin_nested-unconnected", "after-a-lease",
        "unrelated-line-before", "connection-only-after-the-gate",
    ],
)
def test_the_scan_sees_every_wrong_shape(source):
    assert offenders(source), source


@pytest.mark.parametrize(
    "source",
    [
        "def f(engine):\n    with engine.connect() as c, write_lock():\n        c.execute(1)\n",
        "def f(engine):\n    with engine.connect() as c:\n        with write_lock():\n            c.execute(1)\n            c.commit()\n",
        "def f(session):\n    conn = session.connection()\n    with write_lock():\n        conn.execute(1)\n",
        "def f(session):\n    connection_first(session)\n    with write_lock(), session.begin_nested():\n        pass\n",
        "def f(session):\n    session.connection()\n    with write_lock(), session.begin_nested():\n        pass\n",
        "def f(path):\n    with write_lock():\n        c = sqlite3.connect(path)\n",
        "def f(conn):\n    with write_lock():\n        conn.execute(1)\n",
    ],
    ids=["connect-first", "gate-inside", "hoisted-session-connection", "connection_first", "session-connection-first", "not-a-pool", "no-checkout"],
)
def test_the_scan_passes_every_right_shape(source):
    assert offenders(source) == [], source


# --------------------------------------------------------------------------- #
#  the probe and the headline, on the real sites
# --------------------------------------------------------------------------- #
@pytest.fixture
def pool(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_WRITE_GATE_WATCHDOG", "0")
    eng = create_engine(f"sqlite:///{tmp_path / 'order.db'}", poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=5)
    yield eng
    eng.dispose()


def _factory(eng):
    """A session factory wired with the writer's own hooks, as ``src.database.session`` wires the real one."""
    factory = sessionmaker(bind=eng, autoflush=False)
    event.listen(factory, "before_flush", writer._on_before_flush)
    event.listen(factory, "do_orm_execute", writer._on_orm_execute)
    event.listen(factory, "after_transaction_end", writer._on_after_transaction_end)
    return factory


class GateProbe:
    """Records how many connections the pool had out when the gate was FIRST asked for (not a re-entry), on any thread."""

    def __init__(self, monkeypatch, eng):
        self.out_at_first_ask: list[int] = []
        real = writer.write_gate.acquire

        def acquire(*args, **kwargs):
            if not writer.write_gate.held_by_current_thread():
                self.out_at_first_ask.append(eng.pool.checkedout())
            return real(*args, **kwargs)

        monkeypatch.setattr(writer.write_gate, "acquire", acquire)


def _sites():
    """``(id, call)``: each site that used to take the gate first, driven the cheapest way that reaches its gate."""
    from src.analytics import bulk_build
    from src.database import article_indexes, maintenance

    def refresh_stats(eng):
        article_indexes._refresh_stats(eng, [article_indexes.NAMES[0]])

    def incremental_vacuum(eng):
        maintenance.maybe_incremental_vacuum(eng)

    def vacuum(eng):
        maintenance.vacuum_database(eng)

    def drop(eng):
        s = _factory(eng)()
        try:
            bulk_build._drop(s, [])
        finally:
            s.close()

    def discovery(eng):
        from src.database.models import Base
        from src.discovery import channels

        Base.metadata.create_all(eng)
        s = _factory(eng)()
        try:
            assert not s.in_transaction(), "the fresh-session path: the decide phase reads, then rolls back"
            channels.run_discovery(s, per_run=3)
        finally:
            s.close()

    return [
        ("article_indexes._refresh_stats", refresh_stats),
        ("channels.run_discovery", discovery),
        ("maintenance.maybe_incremental_vacuum", incremental_vacuum),
        ("maintenance.vacuum_database", vacuum),
        ("bulk_build._drop", drop),
    ]


@pytest.mark.parametrize("site", [s for s, _ in _sites()])
def test_the_pool_has_a_connection_out_when_the_gate_is_first_asked_for(pool, monkeypatch, site):
    call = dict(_sites())[site]
    probe = GateProbe(monkeypatch, pool)
    call(pool)
    assert probe.out_at_first_ask, f"{site} never asked for the gate: the probe did not reach it"
    assert probe.out_at_first_ask[0] >= 1, f"{site} asked for the gate with no connection out: the gate first, then the pool"


def test_with_the_pools_only_connection_out_a_site_waits_for_the_pool_without_the_gate(pool):
    """The headline, on a real site: ``_refresh_stats`` waits for the connection, and nobody holds the gate while it waits."""
    from src.database import article_indexes

    hog = pool.connect()
    outcome: dict[str, object] = {}

    def run():
        try:
            article_indexes._refresh_stats(pool, [article_indexes.NAMES[0]])
            outcome["ok"] = True
        except Exception as exc:  # noqa: BLE001 - the test reads the class
            outcome["error"] = type(exc)

    t = threading.Thread(target=run, name="oo-site")
    t.start()
    time.sleep(0.4)
    seen = writer.write_gate.stats()
    hog.close()
    t.join(10)
    assert not t.is_alive()
    assert seen["held"] is False and seen["holder"] is None, f"the site held the gate while it waited for the pool: {seen}"
    assert outcome == {"ok": True}
