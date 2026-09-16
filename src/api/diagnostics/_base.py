"""
The shared router, logger and the one constant two groups read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 51-60 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import logging
import pathlib

from fastapi import APIRouter

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])
_LOG = logging.getLogger("api.diagnostics")

# Bounded scan — PER LANGUAGE (maintainer-ruled 2026-06-11): a single global
# mentions-ranked cap structurally anglicised the export (English keywords
# crowded out every other language, excluding them from the equivalence/family
# analysis). Each keyword counts against the quota of its DOMINANT signature
# language, so French/German/… vocabularies are exported in full alongside
# English. Bounded per language, biased against none.
_MAX_KEYWORDS_PER_LANG = 5000


def package_source() -> str:
    """The whole of ``src/api/diagnostics`` as one string, for the RUNTIME coverage report.

    Before the Q1139 split this was ``pathlib.Path(__file__).read_text()`` on the single
    6,741-line module. A submodule's ``__file__`` is one SLICE of that, so a reader left
    pointed at it would have recomputed the all-diagnostics coverage over the routes of
    one file and reported the other 100-odd as unclassified -- the shrinking-population
    failure, in the one report whose job is to say nothing was lost.

    Reads EVERY ``.py`` in the package, sorted, including one ``__init__`` never imports,
    so a forgotten import line cannot quietly shrink what the comparison runs over. This
    is the runtime twin of ``tests/diagnostics_source.py``; ``test_the_runtime_coverage_
    report_reads_the_whole_package`` pins that the two see the same route set.
    """
    pkg = pathlib.Path(__file__).parent
    parts = sorted(pkg.glob("*.py"))
    if not parts:  # pragma: no cover - the package cannot be empty while this runs
        raise RuntimeError(
            f"{pkg} holds no .py files -- the coverage report would compare against an "
            "empty route set and call the bundle complete"
        )
    return "".join(p.read_text(encoding="utf-8") for p in parts)


def api_dir() -> pathlib.Path:
    """``src/api`` -- where the ``_DIAG_SIBLING_FILES`` routers live.

    ``__file__.parent`` was ``src/api`` before the split and is ``src/api/diagnostics``
    after it, so the sibling read needs the parent of the package, not of the module.
    """
    return pathlib.Path(__file__).parent.parent
