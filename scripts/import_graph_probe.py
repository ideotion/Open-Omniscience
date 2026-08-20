#!/usr/bin/env python3
"""Import-graph probe for ``src/`` — the S-2 unblock (docs/ROADMAP.md, structural debt).

The S-2 row records ~1,865 function-level ``from src.…`` imports and says the tree
cannot distinguish deliberate lazy-loading from undocumented cycle-breaking "without
resolving each. An import-graph probe reporting true cycles" is the named unblock.
This is that probe. It HOISTS NOTHING — it measures and classifies.

Method (stated so every number carries it):

* The module set is every ``src/**/*.py`` file, named ``src.foo.bar``
  (``__init__.py`` names its package).
* Edges are DIRECT: an import statement adds an edge importer -> named target only
  when the target resolves to a module in the set. ``from src.a import b`` resolves
  to ``src.a.b`` when that module exists, else to ``src.a`` (an attribute import).
  Relative imports are resolved against the importer's package. Package-prefix
  execution (importing ``src.a.b`` also runs ``src/a/__init__``) is deliberately NOT
  modelled as an edge — stating it would drown the report in benign package-init
  cycles Python resolves via ``sys.modules``; the limitation is stated in the
  rendered report.
* An import is MODULE-LEVEL (an import-time edge) unless it sits inside a function
  body, inside an ``if TYPE_CHECKING:`` block (no runtime edge), or inside an
  ``if __name__ == "__main__":`` block (runs only as a script). Class bodies execute
  at import time, so class-level imports count as module-level.
* TRUE CYCLES are the strongly connected components of size > 1 (plus self-loops)
  in the module-level graph — the only cycles that exist at import time.
* Each function-level (lazy) edge u -> v is classified:
    - ``cycle-breaking``  hoisting it would close a cycle (v reaches u through
      module-level edges), so the import MUST stay lazy;
    - ``redundant``       u already imports v at module level, so the lazy import
      adds nothing (trivially hoistable/deletable);
    - ``hoistable``       hoisting cannot create a cycle against today's graph.
  A ``hoistable`` verdict is about CYCLES ONLY — a lazy import may still be
  deliberate (deferring a heavy optional dependency serves the lean-boot goal), so
  the worklist is input for annotation, never a licence to hoist mechanically.
* One import STATEMENT is one site per distinct target (``from x import a, b``
  is a single site; a statement naming two different modules is two).
* A lazy import site counts as SELF-DOCUMENTED when its own line or the comment
  block immediately above it (up to 5 consecutive ``#`` lines) states a reason
  — per-site evidence only; an enclosing docstring is deliberately NOT used
  (one function's circular-import sentence would taint every other lazy import
  in that function). Two claim kinds are distinguished:
  ``cycle-claim`` (mentions circular/cycle — checkable against the graph) and
  ``lazy-claim`` (lazy/defer/avoid-import — deliberate deferral, claims nothing
  about cycles, nothing to confirm). NOTE this is a different instrument from the
  S-2 row's "49 carry a circular-import comment" grep (whose exact pattern was not
  recorded); both numbers are stated in the report, each with its method.

Run:  python scripts/import_graph_probe.py [--root .] [--out report.md]
The ratchet test (tests/test_import_graph.py) imports these functions and pins the
true-cycle count so it can only fall.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_CYCLE_CLAIM = re.compile(r"circular|circ\.|\bcycle\b|\bcyclic\b")
_LAZY_CLAIM = re.compile(r"\blazy\b|\blazily\b|\bdefer|avoid[^\n]{0,40}import|import[^\n]{0,40}avoid")


def classify_claim(text: str) -> str:
    """'cycle-claim' | 'lazy-claim' | '' for a lowercased comment/docstring blob."""
    if _CYCLE_CLAIM.search(text):
        return "cycle-claim"
    if _LAZY_CLAIM.search(text):
        return "lazy-claim"
    return ""


@dataclass
class ImportSite:
    """One import statement that resolved to an intra-src module."""

    importer: str
    target: str
    path: str  # repo-relative posix path of the importing file
    lineno: int
    kind: str  # "module" | "function" | "main" | "type-checking"
    context: str  # enclosing function name, or "<module>"
    claim: str = ""  # "cycle-claim" | "lazy-claim" | "" (lazy sites only)


@dataclass
class ProbeResult:
    modules: set[str] = field(default_factory=set)
    sites: list[ImportSite] = field(default_factory=list)
    parse_failures: list[str] = field(default_factory=list)

    # ---- derived views -------------------------------------------------- #
    def module_edges(self) -> set[tuple[str, str]]:
        return {
            (s.importer, s.target)
            for s in self.sites
            if s.kind == "module" and s.importer != s.target
        }

    def lazy_sites(self) -> list[ImportSite]:
        return [s for s in self.sites if s.kind == "function"]

    def main_block_sites(self) -> list[ImportSite]:
        return [s for s in self.sites if s.kind == "main"]

    def graph(self) -> dict[str, set[str]]:
        g: dict[str, set[str]] = {m: set() for m in self.modules}
        for a, b in self.module_edges():
            g.setdefault(a, set()).add(b)
        return g

    def true_cycles(self) -> list[list[str]]:
        """SCCs of size > 1 (plus self-loops) in the module-level graph, sorted."""
        g = self.graph()
        sccs = _tarjan(g)
        self_loops = [
            [s.importer] for s in self.sites if s.kind == "module" and s.importer == s.target
        ]
        cycles = [sorted(c) for c in sccs if len(c) > 1] + self_loops
        return sorted(cycles)

    def classify_lazy(self) -> dict[str, list[ImportSite]]:
        g = self.graph()
        module_edges = self.module_edges()
        reach = _Reachability(g)
        out: dict[str, list[ImportSite]] = {
            "cycle-breaking": [],
            "redundant": [],
            "hoistable": [],
        }
        for s in self.lazy_sites():
            if (s.importer, s.target) in module_edges:
                out["redundant"].append(s)
            elif reach.reaches(s.target, s.importer):
                out["cycle-breaking"].append(s)
            else:
                out["hoistable"].append(s)
        return out


class _Reachability:
    """Memoised directed reachability over the module-level graph."""

    def __init__(self, graph: dict[str, set[str]]) -> None:
        self._graph = graph
        self._descendants: dict[str, set[str]] = {}

    def reaches(self, start: str, goal: str) -> bool:
        if start not in self._graph:
            return False
        if start not in self._descendants:
            seen: set[str] = set()
            stack = [start]
            while stack:
                node = stack.pop()
                for nxt in self._graph.get(node, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            self._descendants[start] = seen
        return goal in self._descendants[start]


def _tarjan(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan SCC (recursion-free: the graph is ~450 nodes but deep)."""
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = 0
    for root in graph:
        if root in index:
            continue
        work: list[tuple[str, iter]] = [(root, iter(graph.get(root, ())))]  # type: ignore[valid-type]
        index[root] = lowlink[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in graph:
                    continue
                if nxt not in index:
                    index[nxt] = lowlink[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(graph.get(nxt, ()))))
                    advanced = True
                    break
                if nxt in on_stack:
                    lowlink[node] = min(lowlink[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
            if lowlink[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == node:
                        break
                sccs.append(scc)
    return sccs


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #


def _module_name(path: Path, src_root: Path) -> str:
    rel = path.relative_to(src_root.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
    )


def _is_main_test(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    names = set()
    for node in (left, right):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Constant):
            names.add(node.value)
    return "__name__" in names and "__main__" in names


def _resolve_from(module: str, is_package: bool, node: ast.ImportFrom) -> list[str]:
    """Absolute dotted base(s) a ``from X import a, b`` statement names."""
    if node.level == 0:
        base = node.module or ""
    else:
        parts = module.split(".")
        keep = len(parts) - node.level + (1 if is_package else 0)
        if keep < 0:
            return []
        base = ".".join(parts[:keep])
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
    if not base:
        # ``from . import x`` at the top of the tree resolves per-alias below.
        return [alias.name for alias in node.names]
    return [f"{base}.{alias.name}" for alias in node.names]


def collect(root: Path) -> ProbeResult:
    src_root = root / "src"
    files = sorted(p for p in src_root.rglob("*.py"))
    result = ProbeResult()
    names: dict[Path, str] = {}
    packages: set[str] = set()
    for path in files:
        name = _module_name(path, src_root)
        names[path] = name
        result.modules.add(name)
        if path.name == "__init__.py":
            packages.add(name)

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover - none today
            result.parse_failures.append(f"{path}: {exc}")
            continue
        _scan_file(
            module=names[path],
            is_package=path.name == "__init__.py",
            rel=path.relative_to(root).as_posix(),
            tree=tree,
            lines=text.splitlines(),
            result=result,
        )
    return result


def _scan_file(
    *,
    module: str,
    is_package: bool,
    rel: str,
    tree: ast.Module,
    lines: list[str],
    result: ProbeResult,
) -> None:
    """Record every intra-src import site of one parsed file into ``result``."""

    def visit(node: ast.AST, kind: str, context: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_kind, child_ctx = kind, context
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child_kind = "function" if kind in ("module", "main") else kind
                child_ctx = child.name
            elif isinstance(child, ast.If) and kind == "module":
                if _is_type_checking_test(child.test):
                    # Only the body is guarded; the else branch runs at import.
                    for sub in child.body:
                        visit_stmt(sub, "type-checking", context)
                    for sub in child.orelse:
                        visit_stmt(sub, "module", context)
                    continue
                if _is_main_test(child.test):
                    for sub in child.body:
                        visit_stmt(sub, "main", context)
                    for sub in child.orelse:
                        visit_stmt(sub, "module", context)
                    continue
            visit_stmt(child, child_kind, child_ctx)

    def visit_stmt(node: ast.AST, kind: str, context: str) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            record(node, kind, context)
        visit(node, kind, context)

    def record(node: ast.Import | ast.ImportFrom, kind: str, context: str) -> None:
        if isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        else:
            candidates = _resolve_from(module, is_package, node)
        for cand in candidates:
            target = None
            if cand in result.modules:
                target = cand
            elif "." in cand and cand.rsplit(".", 1)[0] in result.modules:
                # ``from src.a import attr`` — the edge is to src.a itself.
                target = cand.rsplit(".", 1)[0]
            if target is None:
                continue
            key = (node.lineno, target, kind)
            if key in seen_sites:  # one statement = one site per distinct target
                continue
            seen_sites.add(key)
            claim = ""
            if kind == "function":
                blob: list[str] = []
                own = lines[node.lineno - 1] if node.lineno - 1 < len(lines) else ""
                if "#" in own:
                    blob.append(own[own.index("#") :].lower())
                # The comment block immediately above (<=5 consecutive # lines).
                ln = node.lineno - 2
                steps = 0
                while ln >= 0 and steps < 5 and lines[ln].lstrip().startswith("#"):
                    blob.append(lines[ln].lower())
                    ln -= 1
                    steps += 1
                claim = classify_claim("\n".join(blob))
            result.sites.append(
                ImportSite(module, target, rel, node.lineno, kind, context, claim)
            )

    seen_sites: set[tuple[int, str, str]] = set()
    visit(tree, "module", "<module>")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_markdown(result: ProbeResult, today: str) -> str:
    cycles = result.true_cycles()
    classes = result.classify_lazy()
    lazy = result.lazy_sites()
    breakers = {id(s) for s in classes["cycle-breaking"]}
    cycle_claims = [s for s in lazy if s.claim == "cycle-claim"]
    lazy_claims = [s for s in lazy if s.claim == "lazy-claim"]
    confirmed = [s for s in cycle_claims if id(s) in breakers]
    unconfirmed = [s for s in cycle_claims if id(s) not in breakers]
    unannotated_breakers = [s for s in classes["cycle-breaking"] if s.claim != "cycle-claim"]

    out: list[str] = []
    out.append(f"# Import-graph probe — src/ — {today}")
    out.append("")
    out.append(
        "Raw probe output for the ROADMAP structural-debt row S-2 (the named unblock: a probe\n"
        "reporting true cycles so legitimate lazy imports can be annotated and the rest hoisted).\n"
        "Generated by `scripts/import_graph_probe.py`; the method — including the deliberate\n"
        "direct-edge model that omits package-`__init__` prefix execution — is in that script's\n"
        "docstring. NOTHING was hoisted to produce this report."
    )
    out.append("")
    out.append("## Headline numbers")
    out.append("")
    out.append(f"- modules scanned: **{len(result.modules)}**")
    out.append(f"- module-level (import-time) intra-src edges: **{len(result.module_edges())}**")
    out.append(
        f"- function-level (lazy) intra-src import sites: **{len(lazy)}** "
        f"(distinct edges: {len({(s.importer, s.target) for s in lazy})})"
    )
    out.append(f"- `__main__`-block import sites (script-only, no runtime edge): {len(result.main_block_sites())}")
    out.append(f"- parse failures: {len(result.parse_failures)}")
    out.append("")
    out.append(f"## True import-time cycles: **{len(cycles)}**")
    out.append("")
    if not cycles:
        out.append(
            "None. Every cycle in this codebase is currently held open by lazy imports —\n"
            "which is exactly why the cycle-breaking sites below must stay lazy."
        )
    for cyc in cycles:
        out.append(f"- {' ↔ '.join(cyc)}")
    out.append("")
    out.append("## Lazy-import classification")
    out.append("")
    out.append(f"- **cycle-breaking** (must stay lazy): {len(classes['cycle-breaking'])}")
    out.append(f"- **redundant** (same edge already at module level): {len(classes['redundant'])}")
    out.append(f"- **hoistable** (no cycle would result — may still be deliberate lazy-loading): {len(classes['hoistable'])}")
    out.append("")
    out.append("### Self-documented sites (cf. the S-2 row's “49 carry a circular-import comment”)")
    out.append("")
    out.append(
        f"- **cycle-claim** comments (say circular/cycle — checkable): {len(cycle_claims)}\n"
        f"  - probe-CONFIRMED cycle-breaking: {len(confirmed)}\n"
        f"  - NOT confirmed by the module-level graph (stale, prophylactic, or a path this\n"
        f"    probe's direct-edge model cannot see): {len(unconfirmed)} — listed below, NOT edited"
    )
    for s in sorted(unconfirmed, key=lambda s: (s.path, s.lineno)):
        out.append(f"  - UNCONFIRMED {s.path}:{s.lineno} — {s.importer} → {s.target} (in {s.context})")
    out.append(
        f"- **lazy-claim** comments (say lazy/defer/avoid-import — deliberate deferral,\n"
        f"  nothing to confirm): {len(lazy_claims)}"
    )
    out.append("")
    out.append("### Relation to the S-2 row's own figures")
    out.append("")
    out.append(
        "S-2 (measured 2026-08-04) counted “1,865 function-level `from src.…` imports” by a\n"
        "grep of imports indented ≥4 spaces, and said “only 49 carry a circular-import\n"
        "comment” by an unrecorded pattern. This probe counts by AST (per statement per\n"
        "distinct target, `import src.x` forms included, TYPE_CHECKING/`__main__` blocks\n"
        "excluded), so the totals differ by construction — neither replaces the other, and\n"
        "the discrepancy in the self-documented count is a FINDING: under the strict per-site\n"
        "definition above, almost no lazy import in the tree says why it is lazy, which is\n"
        "stronger, not weaker, than the S-2 sentence. One function-LEVEL note exists that\n"
        "per-site detection deliberately ignores: `init_db`'s docstring circular-import\n"
        "sentence (src/database/session.py), whose models import also carries its own\n"
        "trailing comment and is counted."
    )
    out.append("")
    out.append("## Annotate worklist — cycle-breaking sites with NO comment")
    out.append("")
    out.append(
        "These imports hold a cycle open and nothing says so; each should gain a circular-import\n"
        "comment before anyone “tidies” it to module level."
    )
    for s in sorted(unannotated_breakers, key=lambda s: (s.path, s.lineno)):
        out.append(f"- {s.path}:{s.lineno} — {s.importer} → {s.target} (in {s.context})")
    out.append("")
    out.append("## Hoist-candidate worklist (cycle-safe today; deliberateness NOT judged here)")
    out.append("")
    for s in sorted(classes["hoistable"], key=lambda s: (s.path, s.lineno)):
        out.append(f"- {s.path}:{s.lineno} — → {s.target} (in {s.context})")
    out.append("")
    out.append("## Redundant lazy imports (edge already exists at module level)")
    out.append("")
    for s in sorted(classes["redundant"], key=lambda s: (s.path, s.lineno)):
        out.append(f"- {s.path}:{s.lineno} — → {s.target} (in {s.context})")
    if result.parse_failures:
        out.append("")
        out.append("## Parse failures")
        for f in result.parse_failures:
            out.append(f"- {f}")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repo root (containing src/)")
    parser.add_argument("--out", default=None, help="write the markdown report here")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = collect(root)
    today = _dt.date.today().isoformat()
    report = render_markdown(result, today)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    cycles = result.true_cycles()
    classes = result.classify_lazy()
    print(
        f"modules={len(result.modules)} module_edges={len(result.module_edges())} "
        f"lazy_sites={len(result.lazy_sites())} true_cycles={len(cycles)} "
        f"cycle_breaking={len(classes['cycle-breaking'])} "
        f"redundant={len(classes['redundant'])} hoistable={len(classes['hoistable'])}"
    )
    for cyc in cycles:
        print("CYCLE: " + " <-> ".join(cyc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
