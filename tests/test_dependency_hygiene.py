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

AUDIT 10 / P2-14 (2026-09-08): the same defect, independently, for six more
packages -- verified by direct grep against the whole tree (not just src/), not
just re-reading the earlier finding:
  * FIVE more CORE deps with zero call sites: jinja2, pydantic-settings, tenacity,
    cachetools, orjson. Same shape as structlog -- removed from ``dependencies``,
    guarded below, superseded the moment a real call site lands.
  * networkx (an ``analysis``-extra member) IS imported, but only by
    scripts/analysis/phase4_analyzer.py (inside a try/except ImportError degrade)
    and referenced by tests/conftest.py's generic optional-extra skip probe --
    never by runtime code under src/. install.sh's default end-user install pulls
    in ``[analysis]``, so it was shipping a maintainer-script-only package to every
    default install. MOVED to ``[dev]`` rather than dropped outright, since it does
    have real (non-runtime) users; the guard below checks both halves of that move.
  * python-gnupg (the entire ``crypto`` extra) had zero references anywhere,
    including in src/custody/signing.py (the real, live signing path -- Ed25519 +
    optional PQC, never GPG); src/crypto/signatures.py's GPGSigner is an admitted
    NotImplementedError stub that never called into it. The extra was deleted
    outright (nothing else referenced the extra name "crypto").
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

# The five core removals from audit 10 / P2-14 -- same shape as structlog. Keyed by
# (declared pyproject.toml name, importable module root, requirements.lock pin name).
_ORPHANED_CORE_DEPS = (
    ("jinja2", "jinja2", "jinja2"),
    ("pydantic-settings", "pydantic_settings", "pydantic-settings"),
    ("tenacity", "tenacity", "tenacity"),
    ("cachetools", "cachetools", "cachetools"),
    ("orjson", "orjson", "orjson"),
)


def _core_dependencies() -> list[str]:
    """The ``[project] dependencies`` list, read as text rather than through a TOML
    parser: tomllib would also fold in the optional extras' own lists, and the claim
    here is specifically about what a CORE install is made to download."""
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"\ndependencies\s*=\s*\[(.*?)\n\]", text, re.S)
    assert block, "could not find the [project] dependencies array in pyproject.toml"
    return re.findall(r'"([^"]+)"', block.group(1))


def _optional_dependencies() -> dict[str, list[str]]:
    """The ``[project.optional-dependencies]`` table, parsed with ``tomllib`` (not
    regexed like ``_core_dependencies`` above) specifically so TOML comments are
    stripped by the parser -- a raw-text substring check here would be caught by
    the exact comment-satisfied-guard trap this file's own docstrings warn about:
    every removal below is explained in a comment that necessarily contains the
    removed package's name."""
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return data["project"]["optional-dependencies"]


def _extra_block(extra_name: str) -> list[str]:
    """Just the one named extra's own dependency list -- so a check about the
    ``analysis`` extra can't be accidentally satisfied by a match sitting in
    ``dev`` or anywhere else."""
    extras = _optional_dependencies()
    assert extra_name in extras, f"could not find the [{extra_name}] extra in pyproject.toml"
    return extras[extra_name]


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


def _src_import_offenders(module_root: str) -> list[str]:
    """Where (if anywhere) ``import <module_root>`` / ``from <module_root> import
    ...`` appears under ``src/``. Parsed with ``ast`` rather than grepped so a comment
    or docstring MENTIONING the package name (like the ones in this very file) can
    never satisfy the check -- the recorded comment-satisfied-guard trap."""
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
            if module_root in roots:
                offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    return offenders


def test_no_module_imports_structlog():
    """The other half: a dependency with no importer is the defect, and an importer
    with no dependency is a broken install."""
    offenders = _src_import_offenders("structlog")
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


# --------------------------------------------------------------------------- #
# Audit 10 / P2-14 (2026-09-08): five more core orphans, same shape as structlog.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("pyproject_name,module_root,lock_name", _ORPHANED_CORE_DEPS)
def test_orphaned_core_dep_is_not_declared(pyproject_name, module_root, lock_name):
    deps = _core_dependencies()
    assert not [d for d in deps if d.lower().startswith(pyproject_name)], (
        f"{pyproject_name} is declared again (audit 10, P2-14, 2026-09-08). It was "
        "dropped for having ZERO call sites anywhere in the tree. If it is being "
        "adopted for real, this test and its siblings are the deliberate update -- "
        "land them in the PR that adds the first call site."
    )


@pytest.mark.parametrize("pyproject_name,module_root,lock_name", _ORPHANED_CORE_DEPS)
def test_no_module_imports_orphaned_core_dep(pyproject_name, module_root, lock_name):
    offenders = _src_import_offenders(module_root)
    assert not offenders, (
        f"{module_root} is imported at {offenders} but is no longer a declared "
        "dependency (audit 10, P2-14) -- either declare it (and update the sibling "
        "test) or remove the import"
    )


@pytest.mark.parametrize("pyproject_name,module_root,lock_name", _ORPHANED_CORE_DEPS)
def test_the_lockfile_no_longer_pins_the_orphaned_core_dep(
    pyproject_name, module_root, lock_name
):
    """Same rationale as the structlog lockfile check above: a leftover pin would
    keep downloading a package pyproject.toml no longer declares."""
    lock = (_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert not re.search(rf"^{re.escape(lock_name)}==", lock, re.M), (
        f"requirements.lock still pins {lock_name} after it left pyproject.toml"
    )


# --------------------------------------------------------------------------- #
# Audit 10 / P2-14: networkx moved from [analysis] to [dev] -- it has real
# non-runtime users (a maintainer script, a test-collection probe) but nothing in
# src/, and [analysis] is what install.sh ships to every default end-user install.
# --------------------------------------------------------------------------- #


def test_networkx_is_not_in_the_analysis_extra():
    analysis = _extra_block("analysis")
    assert not [d for d in analysis if d.lower().startswith("networkx")], (
        "networkx is back in the [analysis] extra, which install.sh's default "
        "end-user install pulls in. It was moved to [dev] (audit 10, P2-14, "
        "2026-09-08) because nothing under src/ imports it -- only "
        "scripts/analysis/phase4_analyzer.py (an optional, gracefully-degrading "
        "import) and tests/conftest.py's extras-skip probe do. If a runtime module "
        "under src/ now needs it for real, move it back to [analysis] deliberately "
        "and update this test in the same PR."
    )


def test_networkx_is_still_declared_in_the_dev_extra():
    """The other half of the move: networkx must still be INSTALLABLE for the
    script/test that actually use it, just not shipped to every default install."""
    dev = _extra_block("dev")
    assert [d for d in dev if d.lower().startswith("networkx")], (
        "networkx is declared in neither [analysis] nor [dev] -- "
        "scripts/analysis/phase4_analyzer.py's circular-import check and "
        "tests/conftest.py's extras probe lose their real (non-runtime) dependency."
    )


def test_no_module_under_src_imports_networkx():
    offenders = _src_import_offenders("networkx")
    assert not offenders, (
        f"networkx is imported under src/ at {offenders} -- move it back to the "
        "[analysis] extra (it is a real runtime dependency now) and update the "
        "sibling test above."
    )


def test_the_lockfile_no_longer_pins_networkx():
    """requirements.lock is generated with ``--extra analysis`` only (per
    docs/CONTRIBUTING.md), so a [dev]-only dependency should not appear as a
    top-level pin in it."""
    lock = (_ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert not re.search(r"^networkx==", lock, re.M), (
        "requirements.lock pins networkx even though it left the [analysis] extra "
        "-- either it is still declared there by mistake, or something else in "
        "[analysis] now pulls it in transitively (update this test's reasoning if so)"
    )


# --------------------------------------------------------------------------- #
# Audit 10 / P2-14: the `crypto` extra (python-gnupg, its only member) is gone.
# No lockfile assertion here -- requirements.lock is generated with --extra
# analysis only (docs/CONTRIBUTING.md), so python-gnupg was never pinned there to
# begin with; there is nothing for a lockfile guard to protect.
# --------------------------------------------------------------------------- #


def test_the_crypto_extra_no_longer_exists():
    extras = _optional_dependencies()
    assert "crypto" not in extras, (
        "the `crypto` extra is declared again. It was deleted (audit 10, P2-14, "
        "2026-09-08) because its only member, python-gnupg, had ZERO references "
        "anywhere -- src/custody/signing.py is the real, live signing path "
        "(Ed25519 + optional PQC, never GPG) and src/crypto/signatures.py's "
        "GPGSigner is an admitted NotImplementedError stub that never called into "
        "it. If GPG signing is ever genuinely implemented, this test and its "
        "sibling below are the deliberate update."
    )
    all_extra_deps = [d for deps in extras.values() for d in deps]
    assert not [d for d in all_extra_deps if d.lower().startswith("python-gnupg")], (
        "python-gnupg is declared again in [project.optional-dependencies] -- "
        "see test_the_crypto_extra_no_longer_exists"
    )


def test_no_module_imports_gnupg():
    offenders = _src_import_offenders("gnupg")
    assert not offenders, (
        f"gnupg is imported at {offenders} but python-gnupg is no longer a "
        "declared dependency (audit 10, P2-14) -- either declare it (and update "
        "the sibling test) or remove the import"
    )
