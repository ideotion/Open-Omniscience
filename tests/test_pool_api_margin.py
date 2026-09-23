"""The collector may never hold every connection (finding F1, ruling R26).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT THESE PIN, and it was made of two correct numbers. ``memory_budget._SMALL``
gave the small tier 6 + 2 = 8 connections; ``machine_floor.FLOOR_MAX_WORKERS`` allowed 8
collector workers, and its docstring said 8 *because* the pool was 6 + 2. Each was
defensible on its own and together they meant the collector could hold the entire pool.
A collector thread takes the single-writer gate INSIDE ``before_flush``, on a session
that already holds its connection, so every thread queued on a gate held for up to
1,329 s pinned one. API handlers then waited the 30 s ``pool_timeout`` and returned 500:
**153 stalls measured at exactly 30.0 s**, 160 of 332 calls failed, and three
diagnostics-bundle members died on the same error (F1, F9).

WHAT IS DELIBERATELY *NOT* ASSERTED HERE: that the medium tier is safe. It is not, and
the last test says so out loud. R26 raised the pool and forbade lowering the worker cap;
those two together cannot bound a `collect_parallelism` of 50 on a machine that can only
afford 24 connections. A test that quietly skipped that would be the ledger's own
"fabricated security" shape -- a guard whose green tells you something it never checked.
"""

from __future__ import annotations

import pytest

from src.config import memory_budget as mb
from src.config.machine_floor import FLOOR_MAX_WORKERS


@pytest.fixture(autouse=True)
def _fresh():
    mb.reset_for_tests()
    yield
    mb.reset_for_tests()


# --------------------------------------------------------------------------- #
# The invariant, derived from BOTH constants so neither can move alone         #
# --------------------------------------------------------------------------- #


def test_the_small_tiers_pool_exceeds_the_floors_worker_cap_by_the_margin():
    """THE GUARD THAT WAS MISSING. Written against the two live constants rather than
    against the numbers 12 and 8, so it reddens whether someone shrinks the pool or
    raises the cap -- the two ways this defect can come back."""
    small = mb.resolve_for(3296)
    assert small["tier"] == "small"

    headroom = mb.api_headroom_for(FLOOR_MAX_WORKERS, pool_total=small["pool_total"])
    assert headroom["sufficient"], (
        f"the collector's {FLOOR_MAX_WORKERS} workers leave {headroom['headroom']} of "
        f"{small['pool_total']} connections; the API needs {mb._API_MARGIN}"
    )
    assert headroom["headroom"] >= mb._API_MARGIN


def test_the_margin_costs_no_RESIDENT_memory_on_either_narrowed_tier():
    """THE TRADE, and the reason the four slots are overflow rather than pool_size.

    Overflow connections are CLOSED when returned, so ``pool_size x sqlite_cache_mb`` is
    what the machine pays all the time and it did not move: 48 MiB on small, 64 on
    medium, before R26 and after. Putting the slots in ``pool_size`` would have bought a
    faster re-acquire and charged 32 MiB of permanent floor to the machines least able
    to pay -- and the medium tier's twin reshape was already measured and rejected for
    exactly that."""
    assert mb.resolve_for(3296)["db_pool_size"] * mb.resolve_for(3296)["sqlite_cache_mb"] == 48
    assert mb.resolve_for(6000)["db_pool_size"] * mb.resolve_for(6000)["sqlite_cache_mb"] == 64


def test_the_worst_case_rose_by_exactly_the_rulings_stated_arithmetic():
    """R26's rationale: "8 MB x 4 more connections is 32 MB". That is the WORST CASE,
    not the floor, and the difference is the whole design -- so it is pinned as the
    number the ruling actually names."""
    small = mb.resolve_for(3296)
    assert small["worst_case_pool_cache_mb"] == 96  # was 64
    assert 96 - 64 == mb._API_MARGIN * small["sqlite_cache_mb"] == 32


def test_a_large_machine_is_untouched():
    """The negative twin: a slice about small machines must not move a big one."""
    large = mb.resolve_for(16384)
    assert (large["db_pool_size"], large["db_max_overflow"]) == (8, 64)
    assert large["pool_total"] == 72


# --------------------------------------------------------------------------- #
# The residual, reported rather than hidden                                   #
# --------------------------------------------------------------------------- #


def test_the_medium_tier_is_still_exhaustible_and_says_so():
    """R26 CANNOT FIX MEDIUM, and this is the test that keeps that visible.

    `collect_parallelism` ships at 50; the floor's worker cap applies only BELOW the
    floor, so nothing caps a medium machine's fan-out. Sizing a pool to 54 connections
    at 16 MiB each is 864 MiB of worst-case page cache on an 8 GB box -- not a fix. The
    only two ways out are a reservation at checkout or a cap on the fan-out, and R26
    forbids the second. So this asserts the HONEST answer rather than a green one."""
    medium = mb.resolve_for(6000)
    assert medium["tier"] == "medium"

    shipped_parallelism = 50  # src/scheduler/settings.py: collect_parallelism
    verdict = mb.api_headroom_for(shipped_parallelism, pool_total=medium["pool_total"])
    assert verdict["sufficient"] is False
    assert verdict["headroom"] < 0
    # ...and the margin still helped: 24 connections instead of 20 is four more calls
    # that get served before the pool empties.
    assert medium["pool_total"] == 24


def test_api_headroom_takes_the_fan_out_as_a_PARAMETER_not_from_a_constant():
    """The coupling that caused this is not allowed to re-form in the other direction.

    ``memory_budget`` must not learn the live worker cap: two modules each deriving
    from the other is how 8 met 8. The caller that knows the fan-out passes it."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(mb))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    # THE AST, NOT A SUBSTRING. The first cut grepped the source for the two names and
    # failed on this module's OWN COMMENTS explaining the coupling -- which is the
    # documentation the defect most needs. What must not exist is a read, not a mention.
    assert not any("machine_floor" in m or "scheduler" in m for m in imported), imported

    # ...and the parameter really is one: the signature takes the fan-out.
    assert "workers" in inspect.signature(mb.api_headroom_for).parameters


@pytest.mark.parametrize(
    "workers,total,ok",
    [
        (0, 12, True),   # nothing running
        (8, 12, True),   # the small tier's cap, exactly at the margin
        (9, 12, False),  # one worker past it
        (50, 24, False),  # the medium tier as shipped
        (68, 72, True),   # the large tier, exactly at the margin
        (69, 72, False),  # ...and one past it
    ],
)
def test_the_headroom_arithmetic_is_plain_subtraction(workers, total, ok):
    assert mb.api_headroom_for(workers, pool_total=total)["sufficient"] is ok


# --------------------------------------------------------------------------- #
# The stale comment that would re-teach the defect                            #
# --------------------------------------------------------------------------- #


def test_the_worker_caps_docstring_no_longer_claims_it_derives_from_the_pool():
    """A comment asserting a derivation that no longer holds is how a later session
    re-creates the coupling in good faith -- the recorded `page_size=16384` trap, where
    a stale comment cost one of the maintainer's decisions. FLOOR_MAX_WORKERS is 8 for
    its own reason now, and its docstring has to say so."""
    from pathlib import Path

    src = Path("src/config/machine_floor.py").read_text(encoding="utf-8")
    doc = src.split("FLOOR_MAX_WORKERS = 8", 1)[1].split('"""', 2)[1]

    assert "no longer derived" in doc.lower()
    assert "api_headroom_for" in doc, "it must point at the live check"
    assert "is 8 because it is the small tier's own pool bound" not in doc


def test_the_pass_summary_publishes_the_comparison_that_was_never_made(monkeypatch):
    """THE READER. The pool bound and the fan-out were ALREADY side by side in this
    block and nothing subtracted one from the other, so a collector that could hold
    every connection looked exactly like one that could not. A number with no reader is
    a dead end -- the recorded shape -- so the verdict ships in every pass summary."""
    monkeypatch.setattr(mb, "total_ram_mb", lambda: 3296.0)
    mb.reset_for_tests()

    from src.monitoring.collect_perf import CollectionMonitor

    class _Gov:
        w_max = 50
        permits = 1
        active = 0

    block = CollectionMonitor(governor=_Gov(), pass_id="p", mode="rss")._db_memory()

    assert block["pool_bound"] == 12 and block["w_max"] == 50
    assert block["api_headroom"]["sufficient"] is False
    assert block["api_headroom"]["headroom"] == 12 - 50
    assert block["api_headroom"]["api_margin"] == mb._API_MARGIN


def test_the_headroom_is_absent_rather_than_guessed_without_a_governor():
    """Omitted, never zeroed: "no fan-out to compare against" and "the collector holds
    nothing" are different facts, and this block's own docstring already says so."""
    from src.monitoring.collect_perf import CollectionMonitor

    class _NoMax:
        w_max = 0
        permits = 1
        active = 0

    block = CollectionMonitor(governor=_NoMax(), pass_id="p", mode="rss")._db_memory()
    assert "api_headroom" not in block
    assert "page_cache_ceiling_mb_unavailable" in block
