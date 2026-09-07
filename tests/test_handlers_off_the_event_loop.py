"""S3.6 — a DB-touching request handler must never run ON the single event loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS FILE EXISTS. FastAPI dispatches a plain ``def`` path operation into
Starlette's threadpool and an ``async def`` one onto the process's single event
loop. Every handler here does synchronous DB work through the SQLCipher codec, so
an ``async def`` one freezes the WHOLE server for its duration -- every other
request stalls, the task manager included, and the app looks hung. It is the same
family as the unlock freeze and the restore-preview freeze, and the crash brief
measured it in the field: ``async def list_sources`` materialising 68,409 rows took
**12.6 s**, during which ``GET /api/scheduler/status`` -- a pure in-memory dict read
-- took 41.7 s.

The count was **56** on 2026-09-06 (50 of them in ``source_management.py``) with no
guard preventing the fifty-seventh. This file is that guard.

MEASURED HERE, with the real stack (slowapi limiter + ``Depends(get_db)``), by
issuing a trivial second request while a 1.5 s handler is in flight:

    async def (the defect) -> the trivial request took 1,159.6 ms  [stalled behind it]
    plain def (the fix)    -> the trivial request took     4.8 ms  [served immediately]

The property is that the SECOND REQUEST IS SERVED -- not that the first is faster.
Nothing here makes any handler faster.

THE TWO MECHANISMS, guarded separately because each can regress without the other:

1. :func:`test_no_db_handler_runs_on_the_event_loop` -- the census. An ``async def``
   handler taking ``Depends(get_db)`` must be one of the four in :data:`_ASYNC_OK`.
2. :func:`test_the_allowlist_cannot_become_a_parking_lot` -- the allowlist is not a
   place to park a handler. An allowlisted one must (a) genuinely await something
   OTHER than ``run_in_threadpool`` -- i.e. have a real reason to be on the loop --
   and (b) never touch its session there.

Mechanism 2(a) is what stops the obvious evasion: wrapping a handler's body in
``run_in_threadpool`` and adding it to the list, when making it ``def`` was the
whole fix. ``import_pdf_folder`` was exactly that shape and became a plain ``def``.
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time

# Module scope, not function scope, and that is load-bearing: this file uses
# `from __future__ import annotations`, so every annotation is a STRING that FastAPI
# resolves against the MODULE globals. With `Request` imported inside the test, FastAPI
# cannot resolve it, silently demotes `request` to a query parameter and answers 422 --
# the handler never runs at all, which from the harness looks exactly like the freeze it
# is trying to measure. (Caught here by the "never started" assertion, which is why that
# assertion exists.) fastapi and sqlalchemy are core dependencies, never extras.
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_API = pathlib.Path(__file__).resolve().parents[1] / "src" / "api"

#: The ONLY handlers that may stay ``async def`` while taking ``Depends(get_db)``.
#: Each awaits the REQUEST STREAM itself, which is reachable only from the loop --
#: an upload's ``await file.read()`` / ``await request.form(...)``. Their DB halves
#: run through ``run_in_threadpool``, which mechanism 2 checks rather than trusts.
#: A new entry here needs a reason of the same kind; anything else is a plain ``def``.
_ASYNC_OK = {
    "import_prices_csv": "awaits the uploaded CSV stream (commodity prices)",
    "import_csv": "awaits the uploaded CSV stream (sources)",
    "import_newsletters": "awaits request.form() with a raised max_files, then each .eml",
    "upload_pdfs": "awaits request.form() with a raised max_files, then each PDF",
}

#: How the session reaches a handler, in both spellings FastAPI accepts.
_DB_DEP = "get_db"


def _takes_db(node: ast.AsyncFunctionDef | ast.FunctionDef) -> str | None:
    """The name of the parameter carrying ``Depends(get_db)``, or None."""
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    # `db: Session = Depends(get_db)` -- defaults align with the TAIL of the params.
    defaults = list(args.defaults)
    for arg, default in zip(positional[len(positional) - len(defaults) :], defaults, strict=True):
        if _is_db_depends(default):
            return arg.arg
    for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if default is not None and _is_db_depends(default):
            return arg.arg
    # `db: Annotated[Session, Depends(get_db)]`
    for arg in positional + list(args.kwonlyargs):
        if arg.annotation is not None and _DB_DEP in ast.unparse(arg.annotation):
            return arg.arg
    return None


def _is_db_depends(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = getattr(func, "id", None) or getattr(func, "attr", None)
    if name != "Depends":
        return False
    return any(_DB_DEP in ast.unparse(a) for a in node.args)


def _async_db_handlers() -> dict[str, tuple[str, ast.AsyncFunctionDef]]:
    """Every ``async def`` in ``src/api/`` that takes ``Depends(get_db)``."""
    found: dict[str, tuple[str, ast.AsyncFunctionDef]] = {}
    for path in sorted(_API.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and _takes_db(node):
                rel = str(path.relative_to(_API.parents[1]))
                found[node.name] = (f"{rel}:{node.lineno}", node)
    return found


def test_no_db_handler_runs_on_the_event_loop():
    """Mechanism 1 -- the census, and the ratchet that stops the fifty-seventh.

    A DB-touching ``async def`` handler blocks the whole process while it runs. The
    only ones allowed are those that must read the request stream, and they are named
    with their reason in ``_ASYNC_OK``.
    """
    offenders = {
        name: where for name, (where, _) in _async_db_handlers().items() if name not in _ASYNC_OK
    }
    assert not offenders, (
        "async def handler(s) taking Depends(get_db) -- their synchronous DB work would "
        "run ON the single event loop and freeze every other request (measured: a 12.6 s "
        f"handler made a trivial poll take 41.7 s in the field): {offenders}. Make each a "
        "plain `def` (Starlette then runs it in its threadpool; @limiter.limit works on a "
        "sync def), or -- only if it must await the request stream itself -- add it to "
        "_ASYNC_OK with its reason and route its DB work through run_in_threadpool."
    )


def test_the_allowlist_cannot_become_a_parking_lot():
    """Mechanism 2 -- an allowlisted handler earns its place, and keeps the loop clean.

    (a) It must await something OTHER than ``run_in_threadpool``. A handler whose only
        await is the threadpool hop does not need the loop at all -- ``def`` is the
        simpler and equivalent shape, and wrapping a body in ``run_in_threadpool`` to
        qualify for this list is the evasion this half exists to refuse.
    (b) It must never touch its session on the loop. Every use of the session parameter
        has to be an argument to ``run_in_threadpool`` -- including the small ones: a
        one-row get-or-create COMMITS, and a commit waits on the single-writer gate like
        any other (6,236 s of wait was measured in the field), so "it is only one row"
        is not a reason for it to happen on the loop.
    """
    handlers = _async_db_handlers()
    missing = set(_ASYNC_OK) - set(handlers)
    assert not missing, (
        f"_ASYNC_OK names handler(s) that are no longer async def with a DB session: "
        f"{sorted(missing)}. Remove them from the allowlist -- a stale entry silently "
        "widens what mechanism 1 permits."
    )

    for name, reason in _ASYNC_OK.items():
        where, node = handlers[name]
        db_param = _takes_db(node)

        awaited = [
            ast.unparse(sub.value)
            for sub in ast.walk(node)
            if isinstance(sub, ast.Await)
        ]
        real = [a for a in awaited if not a.startswith("run_in_threadpool")]
        assert real, (
            f"{name} ({where}) is on _ASYNC_OK for {reason!r}, but the only thing it "
            "awaits is the run_in_threadpool hop -- so it never needs the event loop. "
            "Make it a plain `def` and call the work directly (Starlette already runs a "
            "sync handler in the threadpool); that is one hop fewer and the same thread."
        )

        # Every load of the session name must sit inside a run_in_threadpool call.
        offending: list[int] = []
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and _callee(sub) == "run_in_threadpool"):
                continue
            for arg in sub.args + [kw.value for kw in sub.keywords]:
                for inner in ast.walk(arg):
                    if isinstance(inner, ast.Name) and inner.id == db_param:
                        offending.append(inner.lineno)
        handed_off = set(offending)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == db_param and sub.lineno not in handed_off:
                offending_line = sub.lineno
                raise AssertionError(
                    f"{name} ({where}) touches its session `{db_param}` on the event loop "
                    f"at line {offending_line}. Every use must be an argument to "
                    "run_in_threadpool -- the small ones too: a get-or-create commits, and "
                    "a commit on the loop waits for the single-writer gate while every "
                    "other request in the process waits for it."
                )


def _callee(call: ast.Call) -> str:
    return getattr(call.func, "id", None) or getattr(call.func, "attr", "") or ""


def test_the_measured_freeze_family_stays_fixed_where_it_was_first_found():
    """The three handlers the 2026-07 fix named are still plain ``def``.

    ``tests/test_articles_snappy.py`` pins these by source-slicing ``src.api.main``;
    this re-derives the same fact from the AST, so a rename or a reformat cannot make
    that guard pass vacuously while the handler goes back onto the loop.
    """
    main = ast.parse((_API / "main.py").read_text(encoding="utf-8"))
    by_name = {
        n.name: n
        for n in ast.walk(main)
        if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    for name in ("search_articles", "export_articles", "view_article", "list_sources"):
        node = by_name.get(name)
        assert node is not None, f"{name} is gone from src/api/main.py -- update this guard"
        assert isinstance(node, ast.FunctionDef), (
            f"{name} is an async def again -- its blocking codec work would run on the "
            "event loop. list_sources was measured at 12.6 s over 68,409 rows."
        )


# --------------------------------------------------------------------------- #
# The behavioural half: the property is that the SECOND request is SERVED.
# --------------------------------------------------------------------------- #
def test_a_slow_sync_handler_does_not_stall_a_concurrent_request():
    """A ``def`` handler doing slow synchronous work must not block a second request.

    This drives the REAL dispatch stack -- FastAPI's sync/async routing and the real
    slowapi ``@limiter.limit`` decorator, which wraps a sync ``def`` in its own
    ``sync_wrapper`` -- on a miniature app, because the property under test is the
    DISPATCH, not any one endpoint's SQL. The AST guard above is what holds the line
    on the 400-odd real handlers.

    Determinism: the slow handler blocks on an Event that is set only AFTER the second
    request has come back, so the outcome does not depend on machine speed. On the
    threadpool the second request returns in milliseconds; on the event loop it CANNOT
    return until the gate times out. The assertion is far below that timeout, so a slow
    CI box changes the margin and never the verdict.
    """
    from src.api.ratelimit import limiter

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine)

    def _get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    gate = threading.Event()
    entered = threading.Event()
    router = APIRouter()

    @router.get("/slow")
    @limiter.limit("1000/hour")
    def slow(request: Request, db: Session = Depends(_get_db)) -> dict:
        entered.set()
        gate.wait(timeout=3.0)  # stands in for synchronous DB work through the codec
        return {"ok": True}

    @router.get("/trivial")
    def trivial() -> dict:  # the shape of /api/scheduler/status: an in-memory read
        return {"ok": True}

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router)

    with TestClient(app) as client:
        finished = threading.Event()

        def fire_slow():
            try:
                client.get("/slow")
            finally:
                finished.set()

        worker = threading.Thread(target=fire_slow, daemon=True)
        worker.start()
        assert entered.wait(timeout=5.0), "/slow never started -- the harness is broken"

        started = time.perf_counter()
        resp = client.get("/trivial")
        elapsed = time.perf_counter() - started

        gate.set()
        finished.wait(timeout=5.0)
        worker.join(timeout=5.0)

    assert resp.status_code == 200
    assert elapsed < 1.0, (
        f"the concurrent trivial request took {elapsed * 1000:.0f} ms while a slow "
        "handler was in flight -- it was stalled behind it, which is what an `async def` "
        "handler doing synchronous DB work does to EVERY other request in this "
        "single-worker server (measured in the field: a 12.6 s handler made a pure "
        "in-memory /api/scheduler/status read take 41.7 s)."
    )


def test_the_census_does_not_over_reach():
    """Negative space: the guard flags DB-touching async handlers and nothing else.

    An instrument that named every ``async def`` in ``src/api/`` would be a fabricated
    failure -- 24 of the 28 legitimately have no session (the lock middleware, the
    metrics middleware, the unlock page, the SSE and streaming routes). Equally, the
    283 plain ``def`` handlers that DO take a session must not be flagged: ``def`` is
    the shape this slice is asking for, so flagging it would invert the guard.

    Pinned as counts-with-a-floor rather than exact numbers: the point is that the
    census discriminates, and an exact total would redden on any unrelated new route.
    """
    all_async, sync_with_db = 0, 0
    for path in sorted(_API.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                all_async += 1
            elif isinstance(node, ast.FunctionDef) and _takes_db(node):
                sync_with_db += 1

    flagged = set(_async_db_handlers())
    assert all_async > len(flagged), (
        "every async def in src/api/ takes a DB session -- either the tree changed "
        "shape or _takes_db has started matching everything; check it before trusting "
        "the census."
    )
    assert sync_with_db > 100, (
        f"only {sync_with_db} plain `def` handlers take a session -- the conversion "
        "this guard protects has been undone wholesale."
    )
    assert not (flagged & {"_lock_gate", "monitor_requests", "unlock_page"}), (
        "the census is naming middleware/page handlers that hold no session"
    )
