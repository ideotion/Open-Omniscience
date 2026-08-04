"""Every ``search_ids`` call site is triaged: it either excludes quarantined
articles or is registered as deliberately raw, with a reason.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Quarantine is the app's own "this is a list, not an article"
verdict. It was applied where it was remembered and forgotten where it was not:
the omnibar (the primary search surface) and the Watch engine (which raises Lead
cards) both served quarantined rows, and the omnibar's disclosed ``total``
counted a different set than its own items. Fixing the four known sites does not
stop a fifth appearing -- so this guard makes "a new search path silently skips
the filter" impossible to add quietly.

Shape borrowed from ``merge.py``'s ``_MERGE_HANDLED`` / ``_MERGE_NOT_CARRIED``
pair, which exists for exactly this failure mode one subsystem over: a thing in
NEITHER registry is the bug, so membership of one of them is mandatory and the
reason is part of the record.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"

#: Call sites that MUST see the raw match set, each with the reason. A site here
#: is a deliberate decision, not an oversight -- that is the whole point of
#: naming it.
_RAW_BY_DESIGN: dict[str, str] = {
    "api/main.py": (
        "_query_articles filters Article.quarantined.isnot(True) downstream, per chunk, "
        "as an always-on condition -- filtering twice would be redundant, not safer."
    ),
    "api/reporting.py": (
        "signed-evidence export of articles the USER selected. Silently dropping a member "
        "of an evidence bundle would be worse than including one: the export must be "
        "exactly what was chosen, and the manifest is what makes it checkable."
    ),
    "analytics/ir_eval.py": (
        "retrieval-quality harness: it measures the index as it is. Filtering here would "
        "change the denominator and make the metric describe a different corpus."
    ),
    "analytics/gold_builder.py": (
        "samples real queries to build a gold set for the harness above; it must draw from "
        "the same raw population the harness scores."
    ),
    "monitoring/benchmark.py": (
        "measures FTS latency over the raw index; a filter would benchmark a different query."
    ),
}


def _call_sites() -> list[tuple[str, int, bool]]:
    """(relative path, line, excludes_quarantined) for every search_ids(...) call."""
    out: list[tuple[str, int, bool]] = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a parse error is another test's job
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name != "search_ids":
                continue
            excludes = any(
                kw.arg == "exclude_quarantined"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            )
            out.append((path.relative_to(_SRC).as_posix(), node.lineno, excludes))
    return out


def test_every_search_ids_call_site_is_triaged() -> None:
    untriaged = [
        f"{rel}:{line}"
        for rel, line, excludes in _call_sites()
        if not excludes and rel not in _RAW_BY_DESIGN
    ]
    assert not untriaged, (
        "these search_ids call sites neither exclude quarantined articles nor are "
        "registered in _RAW_BY_DESIGN with a reason: " + ", ".join(untriaged)
    )


def test_the_raw_by_design_registry_only_names_real_call_sites() -> None:
    """A stale exemption is how a registry rots into a rubber stamp: it keeps
    granting a pass to a file that no longer calls search_ids at all, and the next
    real call site in that file inherits the pass without anyone deciding."""
    have = {rel for rel, _line, _ex in _call_sites()}
    stale = sorted(set(_RAW_BY_DESIGN) - have)
    assert not stale, f"_RAW_BY_DESIGN names files with no search_ids call: {stale}"


def test_every_exemption_states_a_reason() -> None:
    thin = [k for k, v in _RAW_BY_DESIGN.items() if len(v.strip()) < 40]
    assert not thin, f"an exemption without a real reason is not a decision: {thin}"


def test_the_user_facing_surfaces_are_actually_filtered() -> None:
    """Belt and braces: name the four surfaces the field reported, so a refactor
    that moved one into _RAW_BY_DESIGN would have to argue with this list."""
    filtered = {rel for rel, _line, ex in _call_sites() if ex}
    for surface in (
        "api/search_omni.py",  # the omnibar
        "analytics/watches.py",  # the Lead-raising watch engine
        "api/framing.py",  # cross-outlet framing comparison
        "api/llm.py",  # bulk summarize / translate
    ):
        assert surface in filtered, f"{surface} must exclude quarantined articles"
