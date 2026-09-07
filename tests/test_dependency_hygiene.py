"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

J2 (ruled 2026-09-07, recommended default "drop"): ``structlog`` was a CORE
dependency with **zero** call sites -- declared in ``pyproject.toml`` since before
the ledger records, against ~612 stdlib ``logging`` sites. Every install paid for
it; nothing imported it. PARKED.md's MAINT-04 entry had it as the migration
TARGET for the remaining ``print()`` calls, which is how an orphan survives: it
looks like a plan rather than an omission.

THIS GUARD IS WRITTEN TO BE SUPERSEDED. If structlog is ever genuinely adopted,
this test is what will redden -- update it deliberately, in the PR that adds the
first real call site, rather than by reflex. What it must never allow is the state
it was written for: the dependency back in the manifest with nothing using it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"


def _core_dependencies() -> list[str]:
    """The ``[project] dependencies`` list, read as text rather than through a TOML
    parser: tomllib would also fold in the optional extras' own lists, and the claim
    here is specifically about what a CORE install is made to download."""
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"\ndependencies\s*=\s*\[(.*?)\n\]", text, re.S)
    assert block, "could not find the [project] dependencies array in pyproject.toml"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_the_core_dependency_list_was_found_and_is_not_empty():
    """Anti-vacuity: every assertion below is over this list, so an extraction that
    silently matched nothing would make them all pass."""
    deps = _core_dependencies()
    assert len(deps) > 10, deps
    assert any(d.startswith("fastapi") for d in deps), "sanity: fastapi is a core dep"


def test_structlog_is_not_a_declared_dependency():
    deps = _core_dependencies()
    assert not [d for d in deps if d.lower().startswith("structlog")], (
        "structlog is declared again. It was dropped (J2, 2026-09-07) because it had "
        "ZERO call sites while the codebase logs through stdlib `logging`. If it is "
        "being adopted for real, this test and its sibling below are the deliberate "
        "update -- land them in the PR that adds the first call site."
    )


def test_no_module_imports_structlog():
    """The other half: a dependency with no importer is the defect, and an importer
    with no dependency is a broken install. Parsed with ``ast`` rather than grepped so
    the sentence you are reading -- which necessarily contains the word -- cannot
    satisfy it (the recorded comment-satisfied-guard trap)."""
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a syntax error is another test's job
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            if "structlog" in roots:
                offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    assert not offenders, (
        f"structlog is imported at {offenders} but is no longer a declared dependency "
        "-- either declare it (and update the sibling test) or use stdlib logging"
    )


def test_the_ast_walk_can_actually_see_an_import():
    """Anti-vacuity for the walk above: a detector that resolves nothing would pass
    the test whatever the tree held. Proves the SAME code path finds a name that IS
    imported all over src/."""
    seen = 0
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                a.name.split(".")[0] == "logging" for a in node.names
            ):
                seen += 1
    assert seen > 50, f"the import walk found only {seen} stdlib-logging imports"


def test_the_lockfile_no_longer_pins_structlog():
    """``requirements.lock`` is the hash-verified clean-room install a new contributor
    runs; a leftover pin there would keep downloading the dropped package."""
    lock = (_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert not re.search(r"^structlog==", lock, re.M), (
        "requirements.lock still pins structlog after it left pyproject.toml"
    )
