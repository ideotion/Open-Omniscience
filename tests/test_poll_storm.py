"""
S3.1 + S3.3 + S3.6 (2026-09-02 crash analysis): the request storm.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three separate ways a poll paid for work it should never have paid for:

* a COLD alert cache computed the 23.7 s convergence scan on the request thread,
  once per concurrent poll, because the build lock only ever stopped a second
  BACKGROUND build;
* every warmed insights key was a hand-written near-miss of the key the request
  actually builds, so ``warm_cache`` reported success while warming nothing any
  caller could read;
* the lock middleware read the store's header off disk on EVERY request,
  including every static asset, on the event loop.

Each guard has its negative twin, because all three fixes have a failure
direction that looks like the fix: refusing to compute for a caller who really
needed it, warming a key nobody asked for, and answering a lock question from a
cache that has gone stale.
"""

from __future__ import annotations

import threading
import time

import pytest


# --- S3.1: the cold cache stops computing on the request thread ------------ #


@pytest.fixture(autouse=True)
def _clean_poll_cache():
    from src.analytics import poll_cache

    poll_cache.clear()
    yield
    poll_cache.clear()


def test_a_cold_cache_on_the_polled_params_reports_building_instead_of_scanning(monkeypatch):
    from src.analytics import poll_cache

    computed: list[int] = []
    monkeypatch.setattr(
        poll_cache, "_compute", lambda *a, **k: computed.append(1) or {"total": 7}
    )
    kicked: list[tuple] = []
    monkeypatch.setattr(
        poll_cache, "_kick_background_refresh", lambda *a: kicked.append(a)
    )

    out = poll_cache.get_alerts(object())

    assert computed == [], "the request thread ran the convergence scan"
    assert len(kicked) == 1, "nothing was asked to build it either"
    assert out["building"] is True
    # The measured fields are ABSENT, never zeroed: the strip's own guard is
    # `if (!d.total) hide`, so a 0 here would turn a running scan into an
    # empty panel -- a quiet corpus, which is not what was measured.
    assert "total" not in out
    assert "tiers" not in out
    assert out["as_of"] is None and out["cached"] is False
    assert out["reason"]


def test_a_non_default_window_still_computes_live(monkeypatch):
    """The negative twin. A one-off question nobody polls must still be answered
    -- a blanket refusal would trade a slow endpoint for a useless one."""
    from src.analytics import poll_cache

    computed: list[int] = []
    monkeypatch.setattr(
        poll_cache, "_compute", lambda *a, **k: computed.append(1) or {"total": 3}
    )
    monkeypatch.setattr(poll_cache, "_store", lambda *a, **k: time.time())
    monkeypatch.setattr(poll_cache, "_bind_of", lambda _s: None)

    out = poll_cache.get_alerts(
        object(), convergence_lookback_days=poll_cache.DEFAULT_CONVERGENCE_LOOKBACK_DAYS + 1
    )

    assert computed == [1], "a bespoke window was refused an answer it alone can get"
    assert out.get("building") is not True
    assert out["total"] == 3


def test_concurrent_cold_polls_start_no_scans_at_all(monkeypatch):
    """The measured spiral: N polls arriving during the first build each started
    their OWN scan, since the build lock only ever excluded a second BACKGROUND
    build."""
    from src.analytics import poll_cache

    computed: list[int] = []
    monkeypatch.setattr(
        poll_cache, "_compute", lambda *a, **k: computed.append(1) or {"total": 1}
    )
    monkeypatch.setattr(poll_cache, "_kick_background_refresh", lambda *a: None)

    outs: list[dict] = []
    threads = [
        threading.Thread(target=lambda: outs.append(poll_cache.get_alerts(object())))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)

    assert computed == []
    assert len(outs) == 8 and all(o["building"] is True for o in outs)


# --- S3.3: the warm keys are the request keys ------------------------------ #


def test_the_key_the_endpoint_builds_is_the_key_the_warmer_warms(monkeypatch):
    """It was not, for either warmed spec, and warm_cache reported success anyway.

    trending-windows warmed ``tl=None`` while the UI ALWAYS sends target_lang, so
    it missed for every language -- English included, despite the comment claiming
    the English path was warm. Asserted against the key the ENDPOINT actually
    builds, in every language, rather than against a second hand-written copy of
    it (which is how the two drifted apart in the first place)."""
    from src.api import insights as ins

    lim, st = ins.WARM_TRENDING_HOME
    warm = ins.trending_windows_key(country=None, kind=None, limit=lim, series_top=st)

    seen: list[str] = []
    monkeypatch.setattr(ins, "_deadlined", lambda db, key, compute, **kw: seen.append(key) or {})
    monkeypatch.setattr(ins.rm, "trending_windows", lambda *a, **k: {})
    for lang in (None, "en", "fr", "ar", "zh"):
        ins.insights_trending_windows(limit=lim, series_top=st, target_lang=lang, db=object())

    assert seen == [warm] * 5, (
        "the endpoint's key still varies by language (or differs from the warm key), "
        "so one warmed aggregation cannot serve twelve UI languages"
    )


def test_the_top_warm_key_matches_the_endpoints_own_builder():
    """The /top warm omitted the `tl` COMPONENT entirely, so it missed even the
    caller that sends no target_lang -- dead for every possible reader."""
    from src.api import insights as ins

    assert ins.top_key(
        days=None, country=None, kind=None, limit=20, group=True, tl=None
    ) == ins.top_key(days=None, country=None, kind=None, limit=20, group=True, tl=ins._tlang(None))


def test_a_warmed_aggregation_is_read_by_a_translated_request(monkeypatch):
    """End to end: warm once, then ask in a language, and the heavy aggregation
    must NOT run again."""
    from src.api import insights as ins

    calls: list[dict] = []

    def _fake(db, **kw):
        calls.append(kw)
        return {
            "windows": [
                {"label": "7d", "terms": [{"term": "x", "normalized": "x", "language": "fr"}]}
            ]
        }

    monkeypatch.setattr(ins.rm, "trending_windows", _fake)
    monkeypatch.setattr(ins, "_deadlined", lambda db, key, compute, **kw: compute())

    ins.insights_trending_windows(limit=4, series_top=4, target_lang="en", db=object())
    assert len(calls) == 1
    assert calls[0]["target_lang"] is None, (
        "the aggregation was still computed per language, so one entry cannot serve twelve"
    )


def test_annotating_a_served_payload_never_mutates_the_cached_one():
    """``_cached`` copies only the TOP level, so the term dicts a request
    annotates are the very objects the next request is served.

    THE FIXTURE IS THE TEST. The first version used normalized="election", which
    is ALSO the English translation of its own term -- so _annotate_translations
    took its self-identical skip, nothing was ever annotated, and the guard
    passed whether the deep copy was there or not. It was caught by the mutation
    that replaces the copy with the payload itself reddening NOTHING. So the row
    below is one that genuinely resolves (fr guerre -> en war), and the
    assertions check BOTH halves: the cached object is untouched AND the returned
    one really was annotated -- without the second, an _annotate_windows that
    silently did nothing would satisfy the first perfectly.
    """
    from src.analytics import equivalence
    from src.api.insights import _annotate_windows

    if equivalence.translate_term("fr", "guerre", "en") != "war":
        pytest.skip("the ring catalogue no longer resolves the fixture's term")

    cached = {"windows": [{"terms": [{"term": "guerre", "normalized": "guerre",
                                      "language": "fr", "ring_id": None}]}]}
    before = repr(cached)
    out = _annotate_windows(cached, "en")

    assert repr(cached) == before, "the shared cached payload was annotated in place"
    assert out["windows"][0]["terms"][0]["translation"] == "war", (
        "nothing was annotated at all, so 'the cached copy is untouched' proves nothing"
    )


def test_no_target_language_returns_the_payload_untouched():
    """The negative twin: the no-translation path must stay byte-identical, and
    must not pay for a deep copy it does not need."""
    from src.api.insights import _annotate_windows

    payload = {"windows": [{"terms": [{"term": "x"}]}]}
    assert _annotate_windows(payload, None) is payload


# --- S3.6: the header read leaves the request path ------------------------- #


def test_the_lock_middleware_reads_the_store_header_once_not_per_request(monkeypatch):
    from src.database import connect

    connect.invalidate_header_cache()
    reads: list[int] = []
    monkeypatch.setattr(
        connect, "is_encrypted_file", lambda p: reads.append(1) or False
    )
    for _ in range(20):
        connect.main_header_state("/tmp/oo-nonexistent.db")
    assert reads == [1], f"the header was read {len(reads)} times for 20 requests"


def test_the_cached_header_is_dropped_the_moment_the_store_changes(monkeypatch):
    """The negative twin, and the one that matters: a cache that outlived a
    create / restore-swap / wipe would answer a lock question about a file that
    no longer exists."""
    from src.database import connect

    connect.invalidate_header_cache()
    state = [False]
    monkeypatch.setattr(connect, "is_encrypted_file", lambda p: state[0])

    assert connect.main_header_state("/tmp/oo-x.db") is False
    state[0] = True
    assert connect.main_header_state("/tmp/oo-x.db") is False  # still cached
    connect.invalidate_header_cache()
    assert connect.main_header_state("/tmp/oo-x.db") is True


def test_the_passphrase_half_is_never_cached(monkeypatch):
    """Only the FILE read is cached. Unlocking must be visible immediately, or
    the operator types the right passphrase and the app keeps refusing."""
    from src.database import connect

    monkeypatch.setattr(connect, "get_passphrase", lambda: None)
    assert connect.state_for_header(True) == "locked"
    monkeypatch.setattr(connect, "get_passphrase", lambda: "s3cret")
    assert connect.state_for_header(True) == "unlocked-encrypted"


def _binds_here(scope, name: str) -> bool:
    """Is ``name`` bound in THIS scope's own body -- an import, an assignment, a
    ``def``, a parameter -- without descending into nested scopes, which have
    their own?"""
    import ast

    args = getattr(scope, "args", None)
    if args is not None:
        for a in (
            list(args.posonlyargs)
            + list(args.args)
            + list(args.kwonlyargs)
            + [args.vararg, args.kwarg]
        ):
            if a is not None and a.arg == name:
                return True

    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
            continue  # a different scope
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == name:
                    return True
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id == name:
                return True
        elif isinstance(node, ast.Global) and name in node.names:
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def test_every_path_that_replaces_the_store_drops_the_cached_header():
    """Enumerated, per the brief: a TTL alone would leave a window in which the
    app answers for a store that is no longer there.

    This RESOLVES the binding rather than finding the call. The first cut of
    this guard asserted only that ``invalidate_header_cache`` appeared as a
    call somewhere in the file -- which it did, in a function whose scope had
    no import for it, so the endpoint would have raised NameError on the very
    path the guard existed to protect. Only ruff's F821 caught that; a test
    that walks the enclosing scopes catches it here, where the reason is
    written down."""
    import ast
    import pathlib

    NAME = "invalidate_header_cache"
    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("src/api/unlock.py", "src/backup/merge.py", "src/safety/panic.py"):
        src = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)

        parent = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parent[child] = node

        sites = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == NAME
        ]
        assert sites, f"{rel} changes the store file but never drops the cached header"

        for call in sites:
            # Every scope the call can see a name from: its own function, each
            # enclosing function, and the module. A class body is skipped --
            # its names are NOT visible to functions nested inside it.
            scopes, node, first = [], parent.get(call), True
            while node is not None:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    scopes.append(node)
                elif isinstance(node, ast.ClassDef):
                    if first:
                        scopes.append(node)
                elif isinstance(node, ast.Module):
                    scopes.append(node)
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
                ):
                    first = False
                node = parent.get(node)

            assert any(_binds_here(s, NAME) for s in scopes), (
                f"{rel}:{call.lineno} calls {NAME}() but no enclosing scope binds "
                f"that name -- the call raises NameError when the path is taken"
            )
