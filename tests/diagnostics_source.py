"""One reader for ``src/api/diagnostics``, whether it is a module or a package.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS, and why it lands BEFORE a single route moves. J1 in the docket asks
for `src/api/diagnostics.py` -- 6,291 lines, 128 route decorators -- to become a
package. Twenty-eight test sites across eleven files read that path AS A FILE, and the
completeness ratchet
(`test_repo_invariants.py::test_all_diagnostics_bundle_covers_every_get_diagnostic`)
additionally regexes `@router.get("...")` out of that text. Turning the module into a
package makes the path a DIRECTORY, and `Path("src/api/diagnostics.py").read_text()`
then raises -- loudly, at twenty-eight sites, which sounds survivable and is not the
danger.

The danger is the 2026-08-20 `app.js` split, whose recorded lesson is that a POSITIVE
assertion fails loudly and gets fixed while a NEGATIVE one passes FOR FREE against a
file that no longer contains what it checks. 151 sites went vacuous in one commit that
way. A half-migrated diagnostics split does the same thing here: a site repointed at
ONE module of the new package keeps every `assert X in src` honest and turns every
`assert X not in src` into a tautology.

So this reader is the first commit of the split, and it does the boring thing on
purpose: today it returns the single file's text unchanged, so migrating a call site to
it is a no-op that can be verified by the suite staying green. The day the package
exists, the same callers keep seeing the whole of diagnostics, and no assertion changes
meaning.

THE ORDER IS READ FROM THE PACKAGE, never hard-coded here -- a hand-maintained list is
the thing that drifts, silently, from what is actually on disk. `__init__.py` comes
first, then the submodules in the order `__init__.py` imports them, then EVERY
remaining `.py` file in sorted order. That last clause is the safety property worth
stating: a module nobody imports still contributes its text, so a negative assertion
cannot pass because someone forgot an import line.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_REL = ("src", "api", "diagnostics")

# `from . import a, b` / `from .a import x` / `import .a` -- the shapes an __init__ uses
# to pull its own submodules in. Only the module NAME is taken; the order is the order
# the lines appear, which is the order the package itself declares.
_REL_IMPORT = re.compile(r"^\s*from\s+\.(\w+)\s+import\b|^\s*from\s+\.\s+import\s+(.+)$", re.M)


def _package_order(pkg: Path) -> list[Path]:
    """Every ``.py`` in the package, ordered by what ``__init__.py`` imports first."""
    init = pkg / "__init__.py"
    ordered: list[Path] = []
    seen: set[Path] = set()
    if init.is_file():
        ordered.append(init)
        seen.add(init)
        for m in _REL_IMPORT.finditer(init.read_text(encoding="utf-8")):
            names = [m.group(1)] if m.group(1) else [
                n.strip().split(" as ")[0].strip() for n in m.group(2).split(",")
            ]
            for name in names:
                cand = pkg / f"{name}.py"
                if cand.is_file() and cand not in seen:
                    ordered.append(cand)
                    seen.add(cand)
    # Everything else, sorted -- an unimported module still contributes its text.
    for p in sorted(pkg.glob("*.py")):
        if p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered


def diagnostics_parts(root: Path | None = None) -> list[tuple[str, str]]:
    """``(name, text)`` for each file that makes up ``src/api/diagnostics``.

    For callers that genuinely need per-file granularity (a line number, a
    "which module defines this" question). Most callers want
    :func:`diagnostics_source`.
    """
    base = (root or _ROOT).joinpath(*_REL[:-1])
    mod = base / f"{_REL[-1]}.py"
    pkg = base / _REL[-1]
    if mod.is_file():
        return [(mod.name, mod.read_text(encoding="utf-8"))]
    if pkg.is_dir():
        parts = [(p.name, p.read_text(encoding="utf-8")) for p in _package_order(pkg)]
        assert parts, (
            f"{pkg} is a directory but holds no .py files -- every source assertion "
            "against diagnostics would run over an empty string and pass vacuously"
        )
        return parts
    raise AssertionError(
        f"neither {mod} nor {pkg}/ exists -- diagnostics was renamed or moved. Fix this "
        "reader rather than the call sites: returning '' here would silently pass every "
        "negative assertion in the suite."
    )


def diagnostics_source(root: Path | None = None) -> str:
    """The whole of ``src/api/diagnostics``, as one string.

    Joined with ``""`` so each file keeps its own trailing newline and the
    concatenation is byte-exact rather than newline-shifted -- the same convention
    :func:`tests.js_source_helper.app_js` uses, so an ``.index()`` offset or a line
    count a caller computes stays consistent.
    """
    return "".join(text for _name, text in diagnostics_parts(root))
