"""Standing invariants for the decomposed UI engine.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/static/app.js`` was decomposed into ordered modules (structural debt S-3;
``docs/design/APPJS_DECOMPOSITION_2026-08-20.md``). The split itself was proven by
BYTE-PARITY -- concatenating the modules in load order reproduced the pre-split
file exactly -- but that is a one-time migration proof, not an invariant: the
whole point of splitting is that people now edit the modules, and a hash pinned
here would fail on the first legitimate change.

These are the properties that DO hold forever, and each of them is a way the
decomposition could rot silently:

* the modules load in a defined order with the boot block LAST -- it is pure
  load-time wiring and assumes every definition already exists;
* nothing declares the same top-level name twice. In one file that was
  impossible to miss; across seventeen it is easy, and the ledger records that a
  duplicate top-level name silently overrides rather than erroring;
* every module index.html loads actually exists, and every module on disk is
  actually loaded -- an orphan file is dead code that still looks live;
* the service worker precaches all of them (an offline shell missing a module is
  a broken app, not a slower one);
* the i18n chrome audit reads all of them, which is finding I-1's lesson applied
  to the thing that could re-blind it.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import app_js, app_modules

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"

# Top-level declarations sit at exactly four spaces of indentation in this tree's
# UI engine; anything nested is indented further. Anchoring on that is what keeps
# the duplicate-name scan from matching declarations inside function bodies.
_TOP_DECL = re.compile(
    r"^    (?:(?:async\s+)?function\s*\*?\s*|const\s+|let\s+|var\s+|class\s+)([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def _decls(text: str) -> list[str]:
    return _TOP_DECL.findall(text)


def test_the_engine_loads_in_a_defined_order_with_boot_last():
    mods = app_modules()
    assert mods, "index.html loads no app module"
    if len(mods) > 1:
        assert mods[-1] == "app-boot.js", (
            f"app-boot.js must be the LAST module loaded, got {mods[-1]!r}. It is "
            "load-time wiring only -- it calls showTab(), builds the ooSubtabs "
            "components and attaches listeners, all of which assume every "
            "definition above already exists."
        )
        assert mods.count("app-boot.js") == 1, "app-boot.js is loaded more than once"


def test_every_loaded_module_exists_and_every_module_file_is_loaded():
    mods = app_modules()
    for m in mods:
        assert (_STATIC / m).exists(), f"index.html loads {m}, which does not exist"
    on_disk = {p.name for p in _STATIC.glob("app*.js")}
    orphans = on_disk - set(mods)
    assert not orphans, (
        f"module file(s) {sorted(orphans)} exist but index.html never loads them -- "
        "dead code that still reads as live. Either load it or delete it."
    )


def test_no_top_level_name_is_declared_in_two_modules():
    """The ledger's silent-override lesson, now across module boundaries.

    Duplicate top-level function declarations do not error: the later one wins,
    quietly. Within one file that was at least greppable; across modules a
    collision can be introduced by two people who never open the same file.
    """
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for m in app_modules():
        for name in _decls((_STATIC / m).read_text(encoding="utf-8")):
            if name in seen and seen[name] != m:
                dupes.append(f"{name} (in {seen[name]} and {m})")
            seen.setdefault(name, m)
    assert not dupes, "top-level names declared in more than one module: " + ", ".join(dupes)


def test_no_module_declares_the_same_name_twice_internally():
    for m in app_modules():
        names = _decls((_STATIC / m).read_text(encoding="utf-8"))
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"{m} declares {sorted(dupes)} more than once"


def test_the_service_worker_precaches_every_module():
    """An offline shell missing a module is a BROKEN app, not a slower one.

    sw.js is network-first, so an online user self-heals -- which is exactly why
    this could rot unnoticed until someone opened the app offline.
    """
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    for m in app_modules():
        assert f'"/static/{m}"' in sw, (
            f"{m} is loaded by index.html but not in sw.js's SHELL precache list"
        )


def test_the_i18n_chrome_audit_reads_every_module():
    """Finding I-1's lesson, applied to the thing that could re-blind it.

    The audit used to open index.html and nothing else, so it reported 100 %
    coverage while the engine went unread. A module list that drifted from
    index.html would reproduce that failure one module at a time.
    """
    spec = importlib.util.spec_from_file_location(
        "i18n_report", _ROOT / "scripts" / "i18n_report.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    scanned = set(mod._aux_js())
    for m in app_modules():
        assert m in scanned, f"the i18n chrome audit does not read {m}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to parse-check JS")
def test_every_module_parses_on_its_own():
    for m in app_modules():
        r = subprocess.run(
            ["node", "--check", str(_STATIC / m)], capture_output=True, text=True
        )
        assert r.returncode == 0, f"{m} does not parse:\n{r.stderr[:500]}"


def test_app_js_helper_returns_the_whole_engine():
    """``app_js()`` is what 151 source-asserting test sites read.

    If it ever returned one module instead of the engine, every NEGATIVE
    assertion in those tests would pass for free against source that no longer
    contains what it checks -- the vacuity failure js_source_helper exists to end.
    """
    whole = app_js()
    parts = [(_STATIC / m).read_text(encoding="utf-8") for m in app_modules()]
    assert whole == "".join(parts), "app_js() is not the concatenation of the modules"
    assert len(whole) > 500_000, (
        f"app_js() returned only {len(whole)} bytes -- that is not the whole UI "
        "engine, and every source assertion built on it is now weaker than it reads"
    )
