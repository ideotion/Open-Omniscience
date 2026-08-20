"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The import-graph ratchet (ROADMAP structural-debt row S-2's named unblock).

``scripts/import_graph_probe.py`` builds the intra-src import graph and reports
TRUE import-time cycles (module-level SCCs) apart from cycle-free lazy imports.
The ratchet here pins the true-cycle count at its measured floor — ZERO as of
2026-08-20 (see docs/audit/raw/IMPORT_GRAPH_PROBE_2026-08-20.md) — so a
module-level import cycle can never be introduced silently.

A zero floor asserted against a live tree is satisfied for free by a broken
detector (the empty-X trap), so every mechanism the ratchet relies on is first
proven against SYNTHETIC trees where the property is violated: a planted
module-level cycle IS detected, a cycle-breaking lazy import IS classified as
such, and the exclusions (TYPE_CHECKING / __main__) genuinely exclude.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# The probe lives in scripts/ (not a package) — spec-load it, the house pattern
# for script-under-test modules (cf. tests/test_kpi_diff.py). It must be
# REGISTERED in sys.modules before exec: the module defines dataclasses, and
# the dataclass machinery resolves cls.__module__ through sys.modules.
_spec = importlib.util.spec_from_file_location(
    "import_graph_probe", _ROOT / "scripts" / "import_graph_probe.py"
)
probe = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["import_graph_probe"] = probe
_spec.loader.exec_module(probe)


# --------------------------------------------------------------------------- #
# Synthetic-tree helpers (anti-vacuity: prove the detector detects)
# --------------------------------------------------------------------------- #


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a synthetic ``src/`` tree under tmp_path and return the root."""
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    (tmp_path / "src" / "__init__.py").touch()
    return tmp_path


def test_probe_detects_a_planted_module_level_cycle(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/a.py": "from src.b import x\n",
            "src/b.py": "from src.a import y\n",
        },
    )
    result = probe.collect(root)
    assert result.true_cycles() == [["src.a", "src.b"]]


def test_lazy_import_that_holds_a_cycle_open_is_cycle_breaking(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/a.py": "from src.b import x\n",
            "src/b.py": "def f():\n    from src.a import y\n    return y\n",
        },
    )
    result = probe.collect(root)
    assert result.true_cycles() == []  # the lazy import is what keeps it open
    classes = result.classify_lazy()
    assert [(s.importer, s.target) for s in classes["cycle-breaking"]] == [("src.b", "src.a")]
    assert classes["hoistable"] == []


def test_independent_lazy_import_is_hoistable_and_redundant_is_flagged(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/c.py": (
                "from src.d import z\n"
                "def f():\n"
                "    from src.d import z2\n"  # same edge exists at module level
                "    from src.e import w\n"  # independent: no cycle either way
                "    return z2, w\n"
            ),
            "src/d.py": "z = z2 = 1\n",
            "src/e.py": "w = 1\n",
        },
    )
    classes = probe.collect(root).classify_lazy()
    assert [(s.importer, s.target) for s in classes["redundant"]] == [("src.c", "src.d")]
    assert [(s.importer, s.target) for s in classes["hoistable"]] == [("src.c", "src.e")]
    assert classes["cycle-breaking"] == []


def test_type_checking_and_main_blocks_are_not_import_time_edges(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/f.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n"
                "    from src.g import x\n"
                'if __name__ == "__main__":\n'
                "    from src.h import y\n"
            ),
            "src/g.py": "x = 1\n",
            "src/h.py": "y = 1\n",
        },
    )
    result = probe.collect(root)
    assert result.module_edges() == set()
    kinds = {(s.kind, s.target) for s in result.sites}
    assert ("type-checking", "src.g") in kinds
    assert ("main", "src.h") in kinds


def test_multi_alias_statement_is_one_site_and_claims_are_per_site(tmp_path):
    root = _tree(
        tmp_path,
        {
            "src/i.py": (
                "def f():\n"
                "    # imported here to avoid a circular import\n"
                "    from src.j import a, b, c\n"
                "    from src.k import d\n"
                "    return a, b, c, d\n"
            ),
            "src/j.py": "a = b = c = 1\n",
            "src/k.py": "d = 1\n",
        },
    )
    lazy = probe.collect(root).lazy_sites()
    assert len(lazy) == 2  # one site per statement/target, not per alias
    claims = {s.target: s.claim for s in lazy}
    assert claims["src.j"] == "cycle-claim"
    assert claims["src.k"] == ""  # the comment above src.j does not leak downward


# --------------------------------------------------------------------------- #
# The ratchet over the real tree
# --------------------------------------------------------------------------- #

# RATCHET — may only fall (it is already at the floor). Measured 0 on 2026-08-20
# over 475 modules / 486 module-level edges; every cycle in the tree is held
# open by lazy imports (6 cycle-breaking sites, listed in the probe artifact).
# If this test reddens, you introduced a module-level import cycle: keep the
# import lazy (with a circular-import comment) or break the cycle — never raise
# this number.
TRUE_CYCLE_CEILING = 0


def test_no_module_level_import_cycles_in_src():
    result = probe.collect(_ROOT)
    assert not result.parse_failures, result.parse_failures
    cycles = result.true_cycles()
    assert len(cycles) <= TRUE_CYCLE_CEILING, (
        f"module-level import cycle(s) introduced: {cycles} — keep one edge lazy "
        f"(with a circular-import comment) or break the cycle; never raise the ceiling"
    )
    # Anti-vacuity for the zero floor: the same collector must be seeing a real
    # tree (the empty-X trap — a collector that finds no modules also finds no
    # cycles). Floors far below today's measurements, not pins.
    assert len(result.modules) > 300
    assert len(result.module_edges()) > 200
    assert len(result.lazy_sites()) > 1000


def test_known_cycle_breaking_sites_stay_lazy():
    """The 6 measured cycle-breaking edges must remain function-level.

    These lazy imports are the ONLY thing keeping their cycles open (probe
    artifact, 2026-08-20). If one moves to module level, the true-cycle ratchet
    above fires — this companion names the load-bearing edges so the failure is
    actionable, and reddens earlier if the module-level half of a pair is ever
    dropped (which would silently legalise hoisting the lazy half).
    """
    result = probe.collect(_ROOT)
    module_edges = result.module_edges()
    # The module-level halves of the known cycles (spot-verified 2026-08-20):
    for importer, target in [
        ("src.database.models", "src.database.session"),
        ("src.safety.fetcher", "src.ingest"),
        ("src.backup.parity", "src.backup.volumes"),
    ]:
        assert (importer, target) in module_edges, (
            f"{importer} no longer imports {target} at module level — re-run "
            f"scripts/import_graph_probe.py and refresh the cycle-breaking worklist"
        )
    lazy_edges = {(s.importer, s.target) for s in result.classify_lazy()["cycle-breaking"]}
    for importer, target in [
        ("src.database.session", "src.database.models"),
        ("src.ingest", "src.safety.fetcher"),
        ("src.backup.volumes", "src.backup.parity"),
    ]:
        assert (importer, target) in lazy_edges, (
            f"the lazy {importer} → {target} import is no longer classified "
            f"cycle-breaking — if it was hoisted, the cycle ratchet should have "
            f"fired; if the cycle was genuinely broken, update this list"
        )
