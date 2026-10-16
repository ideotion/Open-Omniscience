"""Every place the code counts distinct sources is classified, and a new one fails until it is (row J, R146 (b)).

Once a source is keyed on (domain, feed) one outlet can hold several sources, so "N distinct sources" has two honest
readings: N feeds (a registry fact, the size of the sources list) or N outlets (the number of voices). A gate that
STATES independence reads outlets (``src.database.outlet``); a count that is only the size of the list says it counts
feeds wherever a user can read it.

SCOPE, stated because absence is weaker evidence than presence: the scan finds ``distinct(<x>.source_id)`` calls and
``len()`` of a set/set-comprehension built from ``source_id``. A distinct count written some other way is invisible
to it; the per-gate sibling tests in ``tests/test_outlet_independence.py`` are what pin the gates themselves.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Raw SQL distinct on source_id that is mapped to outlets in Python before any threshold or finding reads it.
OUTLET_MAPPED = {
    ("src/analytics/story_propagation.py", "find_story_propagation"):
        "the active-source list is mapped to each outlet's oldest source before the language ubiquity ratio reads it",
}

# Feed-level counts, each with why a feed is the right unit. "caveat" = a user-visible count that carries
# FEEDS_NOT_OUTLETS (pinned per surface below); "registry" = a count of rows of the sources list, never a voice claim;
# "per_feed" = a per-feed behaviour measure whose numerator and denominator are both feed counts.
FEED_LEVEL = {
    ("src/analytics/passport.py", "corpus_passport"): ("caveat", "a descriptive size of the selection"),
    ("src/api/reporting.py", "plan_evidence"): ("caveat", "what the bundle holds: one item per article, its source named"),
    ("src/timemap/datestore.py", "upcoming_deduced"): ("caveat", "breadth of a mentioned date, descriptive"),
    ("src/catalog/qualification.py", "admission_audit"): ("registry", "sources collection can reach vs sources the audit accounts for"),
    ("src/analytics/concentration.py", "find_flooded_topics"): ("per_feed", "a flood is one feed's share; the ubiquity ratio compares feeds with feeds"),
    ("src/analytics/concentration.py", "find_buried_topics"): ("per_feed", "breadth gate on per-feed shares, feeds on both sides"),
}

# Modules whose gates state independence, coordination or convergence: each reads the outlet key.
OUTLET_GATES = [
    "src/analytics/laundering.py", "src/integrity/actors.py", "src/integrity/collapse.py", "src/bulletin/stories.py",
    "src/analytics/copypasta.py", "src/analytics/recycled_claim.py", "src/analytics/convergence.py",
    "src/analytics/story_propagation.py", "src/api/link_analysis.py", "src/analytics/emergence.py",
    "src/analytics/supergroup_rising.py", "src/discovery/cited_sources.py", "src/analytics/supply_chain_ripple.py",
    "src/analytics/claim_workspace.py",
]


class _Sites(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path, self.stack, self.found = path, [], set()

    def _scope(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    @staticmethod
    def _mentions_source_id(node: ast.AST) -> bool:
        return any(isinstance(n, ast.Attribute) and n.attr == "source_id" for n in ast.walk(node))

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        scope = ".".join(self.stack)
        if name == "distinct" and any(isinstance(a, ast.Attribute) and a.attr == "source_id" for a in node.args):
            self.found.add((self.path, scope))
        if name == "len" and node.args:
            arg = node.args[0]
            built = isinstance(arg, (ast.Set, ast.SetComp)) or (
                isinstance(arg, ast.Call) and getattr(arg.func, "id", None) == "set")
            if built and self._mentions_source_id(arg):
                self.found.add((self.path, scope))
        self.generic_visit(node)


def _sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for p in sorted((ROOT / "src").rglob("*.py")):
        v = _Sites(p.relative_to(ROOT).as_posix())
        v.visit(ast.parse(p.read_text(encoding="utf-8")))
        found |= v.found
    return found


def test_every_distinct_source_count_is_classified_and_nothing_stale_is_listed():
    classified = set(OUTLET_MAPPED) | set(FEED_LEVEL)
    found = _sites()
    assert not found - classified, (
        f"a distinct-source count the classification does not know: {sorted(found - classified)} -- count outlets "
        "(src.database.outlet.outlet_expr / OutletMap) if it states independence, else add it to FEED_LEVEL with a "
        "reason and, where a user can read it, the FEEDS_NOT_OUTLETS sentence")
    assert not classified - found, f"classified but no longer in the code (stale): {sorted(classified - found)}"
    assert all(reason.strip() for reason in OUTLET_MAPPED.values())
    assert all(kind in {"caveat", "registry", "per_feed"} and why.strip() for kind, why in FEED_LEVEL.values())


@pytest.mark.parametrize("path", OUTLET_GATES)
def test_a_gate_that_states_independence_reads_the_outlet_key(path):
    assert "src.database.outlet" in (ROOT / path).read_text(encoding="utf-8"), path


def test_the_scan_sees_a_raw_count_and_a_set_count(tmp_path):
    """The guard fails when the guard goes: both detectable shapes are found in a synthetic module."""
    tree = ast.parse(
        "def a(q, func, Article):\n    return func.count(func.distinct(Article.source_id))\n"
        "def b(rows):\n    return len({r.source_id for r in rows})\n")
    v = _Sites("x.py")
    v.visit(tree)
    assert v.found == {("x.py", "a"), ("x.py", "b")}


def test_every_caveat_classified_count_carries_the_sentence_on_its_surface():
    """Static half: the module that builds the count names the sentence. The runtime half is per surface, below."""
    from src.database.outlet import FEEDS_NOT_OUTLETS

    assert "not outlets" in FEEDS_NOT_OUTLETS and "several" in FEEDS_NOT_OUTLETS
    for (path, _fn), (kind, _why) in FEED_LEVEL.items():
        if kind == "caveat":
            assert "FEEDS_NOT_OUTLETS" in (ROOT / path).read_text(encoding="utf-8"), path
