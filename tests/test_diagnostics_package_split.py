"""The Q1139 split's own guards: routes unchanged, names still reachable, patches still bite.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/api/diagnostics.py`` (6,741 lines, 131 routes) became ``src/api/diagnostics/`` on
2026-09-16 under Q1139 = a, "the mechanical split into a package, routes unchanged". Each
of the four guards here pins one thing that split could have broken silently.

The route table is read from the ROUTER's own definitions, never from
``src.api.main.app.routes`` -- the recorded lesson that a test must not assert positive
facts against that shared mutable singleton, which made an additive-restore guard flaky in
CI for reasons no local run could reproduce.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PKG = _ROOT / "src" / "api" / "diagnostics"
_SNAPSHOT = pathlib.Path(__file__).resolve().parent / "data" / "diagnostics_routes_at_split.json"


def _live_table() -> list[dict]:
    from src.api.diagnostics import router

    return [
        {
            "path": r.path,
            "methods": sorted(r.methods or []),
            "name": r.name,
            "endpoint": getattr(r.endpoint, "__name__", None),
        }
        for r in router.routes
    ]


#: Routes registered AFTER the Q1139 split, in registration order. Each is appended by a
#: slice imported last in ``__init__.py``, so none of them moves a position the snapshot
#: pins. Declared rather than folded into the snapshot: the snapshot's whole value is
#: that it is the pre-split table and has never been retouched.
_ADDED_AFTER_THE_SPLIT: tuple[str, ...] = (
    # 2026-09-16, gate row K / Q310 = a: the country-code duplicate-key scan.
    "country_code_duplicates",
)


def test_diagnostics_split_is_route_neutral():
    """Every path, method, name AND POSITION is what the pre-split module registered.

    The snapshot was taken from `src/api/diagnostics.py` at its last commit before the
    split, by importing it and reading `router.routes`. ORDER is asserted, not just
    membership: `@router.<verb>` fires at import time, so `__init__.py`'s import order IS
    the route order, and an alphabetical tidy-up of those imports would reorder the table
    without changing a single route. That is why `__init__.py` carries `# ruff: noqa: I001`.

    IF YOU LEGITIMATELY ADD A ROUTE: do NOT edit the snapshot. Import the new slice LAST
    in ``__init__.py`` so the route lands at the END, and name it in
    :data:`_ADDED_AFTER_THE_SPLIT` below. The snapshot then goes on meaning exactly what
    it meant the day it was taken -- "this is the pre-split table, in order" -- which is
    the claim this file exists to make, and which folding a new route into it would
    quietly retire. A route that has to be inserted in the MIDDLE is the case to bring
    to review: it moves positions the snapshot pins, and there is no honest way to
    record that except by editing the snapshot and saying why.

    Removing a route genuinely does need the snapshot edited, and that is the right
    friction: it is the only change that can make the split lossy after the fact.
    """
    expected = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    live = _live_table()
    head, tail = live[: len(expected)], live[len(expected):]
    assert head == expected, (
        "the diagnostics route table moved. Compare element by element: a changed ORDER "
        "means the submodule import order in src/api/diagnostics/__init__.py was sorted; "
        "a changed set means a route was removed, renamed, or added somewhere other than "
        "the end (import the new slice LAST)."
    )
    assert [r["endpoint"] for r in tail] == list(_ADDED_AFTER_THE_SPLIT), (
        "a route was added after the split without being declared. Add its endpoint name "
        "to _ADDED_AFTER_THE_SPLIT, in the order the routes register: "
        f"live tail = {[r['endpoint'] for r in tail]}"
    )


def test_every_submodule_contributes_routes_or_says_why():
    """Anti-vacuity: the snapshot comparison is worthless if a slice stopped being imported.

    A submodule dropped from ``__init__.py`` takes its routes with it, which the snapshot
    WOULD catch -- but a submodule that legitimately registers none (``_base``) must not be
    mistaken for one that went missing. So assert the population directly: every ``.py`` on
    disk is imported by the package, and the decorators the files carry add up to the live
    table."""
    on_disk = {p.stem for p in _PKG.glob("*.py")} - {"__init__"}
    init_src = (_PKG / "__init__.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^from \.(\w+) import", init_src, re.M))
    assert on_disk == imported, (
        f"submodules on disk but not imported by __init__: {sorted(on_disk - imported)}; "
        f"imported but absent: {sorted(imported - on_disk)}"
    )
    decorated = sum(
        len(re.findall(r"@router\.(?:get|post|put|patch|delete)\(", p.read_text(encoding="utf-8")))
        for p in _PKG.glob("*.py")
    )
    assert decorated == len(_live_table()), (
        f"{decorated} route decorators across the package but {len(_live_table())} routes "
        "registered -- a decorator is not reaching the shared router"
    )


def test_the_package_reexports_every_name_its_submodules_define():
    """``src.api.main``, ``src/backup/runlog.py`` and thirty test files import names from
    ``src.api.diagnostics``. Before the split those were module globals; now they are
    re-exports, and a name added to a slice is NOT automatically one of them.

    Asserted against the submodules themselves rather than a hand-kept list, so the next
    name added to any slice either gets re-exported or reddens here by name."""
    import src.api.diagnostics as pkg

    defined: dict[str, str] = {}
    for f in sorted(_PKG.glob("*.py")):
        if f.name == "__init__.py":
            continue
        for node in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                defined.setdefault(node.name, f.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        defined.setdefault(t.id, f.name)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined.setdefault(node.target.id, f.name)

    assert defined, "no names parsed out of the package -- this guard would pass vacuously"
    missing = sorted(f"{n} ({defined[n]})" for n in defined if not hasattr(pkg, n))
    assert not missing, (
        "these names are defined in a diagnostics submodule but are not re-exported from "
        f"src/api/diagnostics/__init__.py: {missing}"
    )


def test_no_test_monkeypatches_the_diagnostics_package_itself():
    """A ``setattr`` on the PACKAGE is a silent no-op, so it may never come back.

    ``monkeypatch.setattr(<package>, "X", ...)`` rebinds the package's re-exported copy.
    The submodule that reads X keeps its own global and never sees the double -- the test
    then passes or fails for a reason unrelated to its claim. This is the 2026-08-20
    ``app.js``-split lesson (a split turns assertions vacuous at every site at once) in its
    fixture form, and it is exactly what 38 sites did before the split was migrated.

    Patch the submodule that OWNS the name -- and where a submodule imported it from a
    sibling (``from .evals import merge_diag``), patch the module whose code READS it, since
    a from-import binds a copy."""
    offenders: list[str] = []
    alias_re = re.compile(
        r"from src\.api import diagnostics as (\w+)|import src\.api\.diagnostics as (\w+)"
    )
    for p in sorted((_ROOT / "tests").glob("*.py")):
        txt = p.read_text(encoding="utf-8")
        if "diagnostics" not in txt:
            continue
        aliases = {m.group(1) or m.group(2) for m in alias_re.finditer(txt)}
        for a in sorted(aliases):
            for m in re.finditer(rf"monkeypatch\.setattr\(\s*{re.escape(a)}\s*,", txt):
                offenders.append(f"{p.name}:{txt[: m.start()].count(chr(10)) + 1} setattr({a}, ...)")
        for m in re.finditer(r"""monkeypatch\.setattr\(\s*["']src\.api\.diagnostics\.(\w+)["']""", txt):
            name = m.group(1)
            if not (_PKG / f"{name}.py").is_file():  # a submodule path is the CORRECT form
                offenders.append(
                    f"{p.name}:{txt[: m.start()].count(chr(10)) + 1} "
                    f'setattr("src.api.diagnostics.{name}", ...)'
                )
    assert not offenders, (
        "these patch the diagnostics PACKAGE, which the reading submodule never sees:\n  "
        + "\n  ".join(offenders)
        + "\nPatch the submodule that owns the name (src.api.diagnostics.<slice>) instead."
    )


def test_no_test_reads_the_diagnostics_module_file_directly():
    """The reader exists so no test has to know whether diagnostics is a file or a package.

    Two sites reached the file through the MODULE OBJECT -- `Path(diag.__file__).read_text()`
    -- rather than through the literal path, so the pre-split migration sweep (which grepped
    for the path) could not see them, and after the split they silently read the package's
    `__init__.py`: a few hundred lines of re-exports in which every `assert X in source`
    fails loudly and, worse, every `assert X not in source` passes. Caught by the full suite,
    not by the targeted one.

    PARSED, NEVER GREPPED. The first cut of this guard was a line scan and it fired on two
    innocent lines: a comment explaining the fix and a docstring quoting the old path -- the
    recorded trap that a source guard is satisfied by the prose explaining the thing it
    guards, and that the repair is to strip them rather than to reword them. `ast` cannot
    see a comment at all, and docstrings are excluded explicitly."""
    offenders: list[str] = []
    for p in sorted((_ROOT / "tests").glob("*.py")):
        if p.name in ("diagnostics_source.py", pathlib.Path(__file__).name):
            continue
        txt = p.read_text(encoding="utf-8")
        if "diagnostics" not in txt:
            continue
        tree = ast.parse(txt)
        # every docstring node, so a doc that merely NAMES the old path is not a violation
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        # which local names are bound to the diagnostics module in this file?
        mods = set(re.findall(r"(?:import src\.api\.diagnostics as|from src\.api import diagnostics as) (\w+)", txt))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "__file__"
                and isinstance(node.value, ast.Name)
                and node.value.id in mods
            ):
                offenders.append(f"{p.name}:{node.lineno}  {node.value.id}.__file__")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and "api/diagnostics.py" in node.value
            ):
                offenders.append(f"{p.name}:{node.lineno}  literal {node.value!r}")
    assert not offenders, (
        "read src/api/diagnostics through tests/diagnostics_source.py, never through the "
        "module's own __file__ or a literal path -- after the package split both give you "
        "one slice, and a negative assertion over one slice passes for free:\n  "
        + "\n  ".join(offenders)
    )


def test_the_runtime_coverage_report_reads_the_whole_package():
    """The regression the split introduced and the suite caught -- pinned so it cannot return.

    ``_diagnostics_coverage_report`` recomputed route-vs-member coverage from
    ``pathlib.Path(__file__).read_text()``. After the split that is ONE SLICE, so the report
    saw ~28 of 131 routes and called the other hundred unclassified -- in the one report
    whose entire job is to say the bundle lost nothing. It now reads ``package_source()``.

    Asserts the VALUE, not the shape: a report that degraded would still have all the right
    keys (`available: False` plus a reason), which is the recorded "the better your degrade
    discipline, the weaker a shape assertion is" trap."""
    from src.api.diagnostics import router
    from src.api.diagnostics.bundle import _diagnostics_coverage_report

    rep = _diagnostics_coverage_report()
    assert rep["available"] is True, rep
    gets_live = sum(1 for r in router.routes if "GET" in (r.methods or []))
    assert rep["total_get_routes"] >= gets_live, (
        f"the report saw {rep['total_get_routes']} GET routes but the router registered "
        f"{gets_live} -- it is reading a slice, not the package"
    )
    assert rep["unclassified"] == [], rep["unclassified"]
    assert rep["stale_classifications"] == [], rep["stale_classifications"]
