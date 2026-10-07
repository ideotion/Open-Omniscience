"""The re-index workers are held to the core guard, where the hard limit is already 0 as well (2026-10-07).

The guard sets ``RLIMIT_CORE`` to 1, which a child inherits. Where the hard limit is already 0 it cannot, and makes the process
non-dumpable instead, a flag that does not survive an ``exec``: the forkserver is started by exec and the keyword workers are
forked from it with the environment, which holds ``OO_DB_PASSPHRASE`` on a scripted or headless start. A piped core handler is
handed a dump at limit 0. So the forkserver engages the guard when it starts (a preload module) and each worker engages it first
in its initializer (``spawn``'s workers are exec'd too).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.analytics import reindex_parallel as R

_ROOT = Path(__file__).resolve().parents[1]
_LINUX = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the forkserver and prctl(PR_SET_DUMPABLE) are Linux's here")


def test_the_forkserver_preload_is_a_module_that_exists_and_engages_the_guard_when_imported():
    """MUTATION TARGET: a wrong name (the forkserver swallows an ``ImportError``, so a typo here is silent) or an import that
    engages nothing."""
    name = R._FORKSERVER_PRELOAD
    spec = importlib.util.find_spec(name)
    assert spec is not None and spec.origin, f"{name} is not importable: the forkserver would skip it without a word"
    tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    calls = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
    assert any(ast.unparse(c.value.func) == "core_guard.engage" for c in calls), "the import itself must engage the guard"


def test_the_forkserver_is_given_the_preload_before_it_starts(monkeypatch):
    """MUTATION TARGET: the preload not set, or set after the probe has started the server."""
    seen: list = []

    class FakeCtx:
        def set_forkserver_preload(self, names):
            seen.append(("preload", list(names)))

    monkeypatch.setattr(R._mp, "get_context", lambda method: FakeCtx())

    class Pool:
        def __init__(self, *a, **k):
            seen.append(("pool",))
            raise OSError("no workers in this test")

    monkeypatch.setattr(R, "ProcessPoolExecutor", Pool)
    assert R._probe_context("forkserver") is None
    assert seen == [("preload", [R._FORKSERVER_PRELOAD]), ("pool",)]
    seen.clear()
    assert R._probe_context("spawn") is None and seen == [("pool",)], "only the forkserver has a preload"


def test_a_worker_engages_the_guard_before_it_does_anything_else(monkeypatch):
    """MUTATION TARGET: the call taken out of ``_worker_init`` or moved after the extractor is built."""
    order: list = []
    from src.analytics import extract
    from src.monitoring import core_guard

    monkeypatch.setattr(core_guard, "engage", lambda *a, **k: order.append("engage"))
    monkeypatch.setattr(extract, "get_extractor", lambda name, gazetteer=None: order.append("extractor"))
    monkeypatch.setattr(R, "_worker_extractor", None)
    R._worker_init("regex", None)
    assert order == ["engage", "extractor"]


@_LINUX
def test_a_worker_forked_from_the_forkserver_is_not_dumpable_where_the_hard_limit_is_zero():
    """THE REAL PROCESSES. A launcher's ``ulimit -c 0`` leaves the guard only the non-dumpable flag, which an exec resets: the
    forkserver is that exec. With NO initializer in the pool (so only the preload can have done it) a worker reads the flag
    as 0. MUTATION TARGET: the preload not set, or its module not engaging."""
    script = textwrap.dedent(
        f"""
        import resource, sys
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        sys.path.insert(0, {str(_ROOT)!r})
        from concurrent.futures import ProcessPoolExecutor
        from src.analytics import reindex_parallel as R
        from src.monitoring import core_guard
        ctx = R._pool_context()
        assert ctx is not None and ctx.get_start_method() == "forkserver", ctx
        with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as pool:
            print(pool.submit(core_guard._held).result()["dumpable"])
        """
    )
    out = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=120, cwd=str(_ROOT))
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "0", out.stdout + out.stderr[-500:]
