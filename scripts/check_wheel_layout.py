#!/usr/bin/env python3
"""Check that a built wheel carries the runtime data the app reads, from the wheel's own file list.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (R353, R380). ``release.yml`` is the only workflow that builds this project's wheel, and it builds it at TAG time; every CI job installs the
project with ``pip install -e``, which reads the checkout and so can never show a file the wheel lacks. The failure is quiet: the wheel installs, the
app boots, and the feature is absent with a plausible reason (``src/geo/data`` was uncovered by every built wheel from the day it was added, and
``src/legal/documents.py`` falls back to the French text when a translated one is missing). ``pyproject.toml`` declares the data by glob
(``[tool.setuptools.package-data]``) and ``MANIFEST.in`` by graft, and a list is something somebody has to remember: a file under ``src/`` outside
``static/`` and the two ``data`` directories (a new ``src/analytics/table.json``) matches none of the globs and would simply not ship.

THE RULE. The expectation is derived from the tracked tree, not remembered: every tracked file under ``src/``, ``configs/``, ``migrations/``,
``docs/legal/`` and ``docs/i18n/`` must be in the wheel, except the paths named in ``NOT_SHIPPED`` (each with its reason). A short list of ANCHORS is
checked against the wheel alone, so that a file lost from the tree as well as from the wheel still fails (a rule derived from the tree passes
vacuously when the tree loses the file too).

WHAT THIS IS NOT. It reads a file list. It does not install the wheel or boot the app from it (that end-to-end run belongs to the release
procedure). Beyond the five trees above it asks for nothing from ``docs/``: ``pyproject.toml`` ships ``docs/*.md`` and those two subtrees on
purpose, and the developer trees (``audit``, ``ledger``, ``research``, ``archive``, ``plans``, ``design``, ``product``, ``maintenance``,
``process``, ``testing``) stay out (2,350 tracked ``docs/`` files at ``8850e61ca``, 2026-10-28). CI runs it on the wheel that ``python -m build``
makes from the sdist, as ``release.yml`` does, so ``MANIFEST.in`` decides what it sees, exactly as it decides what is published.

Usage: ``python scripts/check_wheel_layout.py dist/open_omniscience-X.Y.Z-py3-none-any.whl`` (exactly one wheel; run from the repository root;
exit 0 clean, 1 with one sentence per problem, 2 on a usage error).
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The trees the app reads at run time, relative to the package root (which is ``site-packages`` on a wheel install). Everything tracked under
#: one of them must be in the wheel unless NOT_SHIPPED names it. The two ``docs`` subtrees are the 12-language legal gate and the translated
#: quick-start; the rest of ``docs/`` is documentation for developers.
RUNTIME_TREES: tuple[str, ...] = ("src", "configs", "migrations", "docs/legal", "docs/i18n")

#: Tracked files under RUNTIME_TREES that the wheel does not carry on purpose, each with the reason. A path here that is no longer tracked is
#: reported as stale, so the list cannot outlive the file.
NOT_SHIPPED: dict[str, str] = {
    "src/analytics/duckdb_ext/README.md": (
        "a README in the directory the DuckDB loader reads the bundled httpfs binaries from; nothing reads the README itself "
        "(binaries placed there later will not ship either, and this check will then name them)"
    ),
}

#: Files whose absence from the wheel is the failure this check exists for, checked against the wheel alone. One per tree or data kind the app
#: reads: the code, the UI, the two ``src/*/data`` kinds, the sources catalogue the sources-import route reads, the migrations, the in-app
#: manual, one translated legal document plus its ``ui.json`` (a missing translation falls back to French without an error) and the one
#: translated quick-start (a missing one falls back to English).
ANCHORS: tuple[str, ...] = (
    "src/api/main.py",
    "src/static/index.html",
    "src/catalog/data/public_suffix_list.dat",
    "src/geo/data/dbip_country_lite.csv.gz",
    "configs/sources.yml",
    "migrations/env.py",
    "migrations/script.py.mako",
    "docs/USER_MANUAL.md",
    "docs/legal/CGU.md",
    "docs/legal/de/CGU.md",
    "docs/legal/de/ui.json",
    "docs/i18n/fr/QUICKSTART.md",
)


def tree_of(path: str) -> str | None:
    """The RUNTIME_TREES entry a repository-relative POSIX path is under, or None."""
    for tree in RUNTIME_TREES:
        if path.startswith(tree + "/"):
            return tree
    return None


def problems(tracked: Iterable[str], wheel_names: Iterable[str]) -> list[str]:
    """Everything wrong with a wheel's file list against the tracked tree, as sentences; empty when the wheel carries what it must."""
    in_wheel = set(wheel_names)
    tracked_set = set(tracked)
    found: list[str] = []
    for anchor in ANCHORS:
        if anchor not in in_wheel:
            found.append(f"the wheel does not carry {anchor} (an anchor: the app reads it at run time)")
    for path in sorted(NOT_SHIPPED):
        if path not in tracked_set:
            found.append(f"NOT_SHIPPED names {path}, which is no longer tracked: drop the entry")
    for path in sorted(tracked_set):
        tree = tree_of(path)
        if tree is None or path in NOT_SHIPPED or path in in_wheel:
            continue
        found.append(
            f"the wheel does not carry {path} (tracked under {tree}/): declare it in [tool.setuptools.package-data] or MANIFEST.in, "
            f"or name it in NOT_SHIPPED with the reason"
        )
    return found


def tracked_files(root: Path = ROOT) -> list[str]:
    """The files git tracks under ``root``, as repository-relative POSIX paths (NUL-separated, so no path is C-quoted)."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def wheel_names(wheel: Path) -> list[str]:
    """The file names inside a wheel, ``*.dist-info`` metadata left out (it is not the app's tree)."""
    with zipfile.ZipFile(wheel) as zf:
        return [n for n in zf.namelist() if not n.split("/", 1)[0].endswith(".dist-info")]


def generator_line(wheel: Path) -> str:
    """The wheel's own ``Generator:`` line (the build tool and its version), or a stated absence."""
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if name.endswith(".dist-info/WHEEL"):
                for line in zf.read(name).decode("utf-8", "replace").splitlines():
                    if line.startswith("Generator:"):
                        return line
    return "Generator: (not stated in the wheel)"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: check_wheel_layout.py <exactly one wheel>", file=sys.stderr)
        return 2
    wheel = Path(args[0])
    if not wheel.is_file():
        print(f"no such wheel: {wheel}", file=sys.stderr)
        return 2
    names = wheel_names(wheel)
    found = problems(tracked_files(), names)
    if found:
        print(f"{wheel.name}: {len(found)} problem(s) in the wheel's layout ({generator_line(wheel)})")
        for line in found:
            print(f"  - {line}")
        return 1
    tops = ("src", "configs", "migrations", "docs")
    per_tree = ", ".join(f"{t} {sum(1 for n in names if n.split('/', 1)[0] == t)}" for t in tops)
    print(f"{wheel.name}: layout ok, {len(names)} files ({per_tree}); {generator_line(wheel)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
