#!/usr/bin/env python3
"""
appjs_decomposition_check — the no-regression bar for the S-3 split of ``src/static/app.js``.

WHY THIS EXISTS. The ledger's recorded blocker for S-3 was the *interleaved-shared-helper
hazard*: a wrongly-moved helper passes ``node --check`` and breaks only at runtime, in a
browser nobody was running. So the split needs a bar that a non-browser session cannot fake.
This script is that bar. It drives the REAL app in Chromium through the standing
``ui_walk``/``ui_walk_playwright`` instrument (never a parallel driver) and answers three
questions:

1. **Do all the globals still resolve?**  Every top-level declaration in the pre-split
   ``app.js`` is a name the SPA reaches through the global scope — 413 of them are named by
   inline ``on*=`` handlers alone, which resolve against nothing else. The baseline run
   records which names actually resolve IN THE BROWSER (not which names exist in the source:
   the browser is the thing that has to agree), and every later run diffs against that frozen
   set. A module that fails to load, a slice that lost a declaration, or a load-order mistake
   shows up here as a named missing global rather than as a mystery dead click.

   The candidate list is measured, never hand-written: ``--emit-candidates`` derives it from
   the source with the ``tests/js_source_helper`` discipline, and the browser filters it down
   to what genuinely resolves.

2. **Does every surface still render?**  Walks the flagship + backlog surfaces AND every
   top-level tab and every subtab of every tab, recording ``pageerror`` separately from
   ``console.error`` — the single most important lesson of the 2026-07-22 GUI run, which
   reported "384 JS errors" that were 100 % rate-limit console lines and zero uncaught
   exceptions. A run that conflates them manufactures a crisis.

3. **What does it cost to parse and compile?**  ``--measure`` reads Chrome's own
   ``Performance.getMetrics`` (``ScriptDuration``) under CDP CPU throttling, median of N
   loads. This is the S-3 claim's evidence: the ROADMAP row says the real cost of a
   21k-line single file is parse/compile on 2-core field VMs, and a structural change that
   claims a win owes a number rather than an assertion.

HONEST SCOPE. Chromium in a remote sandbox, states B (empty) and C (populated). State A
(virgin) is deliberately absent: it renders ``unlock.html``, which does not load ``app.js``
at all, so it cannot exercise this change. Surfaces verified here graduate to
"Chromium-verified (remote sandbox) · awaiting human UX pass" — never the Gecko-verified (VM)
bar, and never a substitute for the maintainer's own pass.

Usage:
    .venv/bin/python scripts/appjs_decomposition_check.py --emit-candidates > /tmp/cand.json
    .venv/bin/python scripts/appjs_decomposition_check.py \\
        --candidates /tmp/cand.json --baseline-out docs/audit/appjs-split/globals.json
    .venv/bin/python scripts/appjs_decomposition_check.py \\
        --candidates /tmp/cand.json --baseline docs/audit/appjs-split/globals.json \\
        --out docs/audit/appjs-split/wave1.json

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = Path(__file__).resolve().parent.parent

STATE_B_URL = "http://127.0.0.1:8002"
STATE_C_URL = "http://127.0.0.1:8000"


# --------------------------------------------------------------------------------------- #
#  Candidate globals, derived from the SOURCE
# --------------------------------------------------------------------------------------- #

_DECL = re.compile(
    r"^(?:(?:async)\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)"
    r"|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"|^class\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def _app_module_paths() -> list[Path]:
    """Every ``/static/*.js`` app module, in the order ``index.html`` loads them.

    Read from index.html rather than hard-coded, for the reason the i18n scope guard exists:
    a list maintained by hand drifts from the thing it claims to describe, silently.
    """
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    out: list[Path] = []
    for m in re.finditer(r'<script src="/static/([A-Za-z0-9_./-]+\.js)"', html):
        p = _ROOT / "src" / "static" / m.group(1)
        if p.exists():
            out.append(p)
    return out


def emit_candidates() -> dict:
    """Top-level declaration names across the app modules.

    Uses a plain line-anchored declaration match over the module sources. Names that are NOT
    genuinely global (a declaration nested inside a function body, which this cannot tell
    apart without a parser) simply fail to resolve in the browser and are filtered out by the
    baseline — so a false positive here costs nothing, while a false NEGATIVE would silently
    shrink the bar. The match is therefore deliberately generous.
    """
    names: list[str] = []
    per_file: dict[str, int] = {}
    for p in _app_module_paths():
        src = p.read_text(encoding="utf-8")
        # top-level declarations are indented by exactly 4 spaces in this tree's app modules
        found = set()
        for line in src.split("\n"):
            if not line.startswith("    ") or line.startswith("     "):
                continue
            m = _DECL.match(line.strip())
            if m:
                found.add(next(g for g in m.groups() if g))
        per_file[p.name] = len(found)
        names.extend(found)
    uniq = sorted(set(names))
    return {"candidates": uniq, "count": len(uniq), "per_file": per_file}


# --------------------------------------------------------------------------------------- #
#  Browser probes
# --------------------------------------------------------------------------------------- #


def _chromium_path() -> str:
    override = os.environ.get("OO_TEST_CHROMIUM_PATH")
    if override:
        return override
    base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for d in sorted(base.glob("chromium-*"), reverse=True):
        exe = d / "chrome-linux" / "chrome"
        if exe.exists():
            return str(exe)
    raise SystemExit("no pinned Chromium build found under PLAYWRIGHT_BROWSERS_PATH")


def _resolving_globals(page, candidates: list[str]) -> list[str]:
    """Which candidate names actually resolve in the page's global scope.

    ``typeof`` inside an indirect eval reaches the global LEXICAL environment too, which a
    bare ``window[name]`` lookup does not: a top-level ``const``/``let`` in a classic script
    is a global binding but never a ``window`` property. Checking only ``window`` would
    silently drop every ``const`` in the file — 302 of them — from the bar.
    """
    return page.evaluate(
        """(names) => names.filter((n) => {
             try { return (0, eval)("typeof " + n) !== "undefined"; }
             catch (e) { return false; }
           })""",
        candidates,
    )


def _all_tabs(page) -> list[str]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('.nav-item[data-tab]'))
                     .map(b => b.dataset.tab)"""
    )


def _subtabs_of(page) -> list[str]:
    """data-tab values currently VISIBLE in the relocated subtab strip."""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('#subtab-strip button[data-tab]'))
                     .filter(b => b.offsetParent !== null)
                     .map(b => b.dataset.tab)"""
    )


def _script_duration_ms(page, cdp) -> float:
    metrics = cdp.send("Performance.getMetrics")["metrics"]
    by = {m["name"]: m["value"] for m in metrics}
    return by.get("ScriptDuration", 0.0) * 1000.0


def measure_parse(url: str, *, throttle: int, loads: int) -> dict:
    """Median script-evaluation time over N cold loads, under CPU throttling."""
    from playwright.sync_api import sync_playwright

    samples: list[float] = []
    bytes_seen: list[int] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=_chromium_path())
        for _ in range(loads):
            ctx = browser.new_context()  # a fresh context each time: no code cache carry-over
            page = ctx.new_page()
            cdp = ctx.new_cdp_session(page)
            cdp.send("Performance.enable")
            if throttle > 1:
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
            total = {"n": 0}
            page.on(
                "response",
                lambda r, total=total: total.__setitem__(
                    "n", total["n"] + int(r.headers.get("content-length") or 0)
                )
                if "/static/" in r.url and r.url.endswith(".js")
                else None,
            )
            page.goto(url + "/", wait_until="load")
            page.wait_for_timeout(500)
            samples.append(_script_duration_ms(page, cdp))
            bytes_seen.append(total["n"])
            ctx.close()
        browser.close()
    return {
        "throttle_x": throttle,
        "loads": loads,
        "script_duration_ms": [round(s, 1) for s in samples],
        "median_ms": round(statistics.median(samples), 1),
        "js_bytes_median": int(statistics.median(bytes_seen)) if bytes_seen else 0,
    }


def walk_state(name: str, url: str, candidates: list[str], shots: Path | None) -> dict:
    from playwright.sync_api import sync_playwright

    from src.monitoring.ui_walk import BACKLOG_SURFACES, FLAGSHIP_SURFACES, Surface
    from src.monitoring.ui_walk_playwright import PlaywrightUiWalkDriver

    result: dict = {
        "state": name,
        "url": url,
        "boot_pageerrors": [],
        "globals_resolving": [],
        "steps": [],
        "pageerrors": [],
        "console_error_sample": [],
    }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=_chromium_path())
        ctx = browser.new_context(viewport={"width": 1440, "height": 950})
        page = ctx.new_page()
        boot_errs: list[str] = []
        page.on("pageerror", lambda e: boot_errs.append(str(e)))
        page.goto(url + "/", wait_until="load")
        page.wait_for_timeout(1200)
        result["boot_pageerrors"] = list(boot_errs)
        result["globals_resolving"] = sorted(_resolving_globals(page, candidates))

        driver = PlaywrightUiWalkDriver(
            page, base_url=url, screenshot_dir=shots if shots else None
        )

        surfaces: list[Surface] = list(FLAGSHIP_SURFACES) + list(BACKLOG_SURFACES)
        # every top-level tab, then every subtab that tab exposes
        for tab in _all_tabs(page):
            surfaces.append(Surface(f"tab_{tab}", f"tab {tab}", nav_tab=tab, dom_id=f"tab-{tab}"))

        seen: set[str] = set()
        for s in surfaces:
            if s.id in seen:
                continue
            seen.add(s.id)
            step = {"id": s.id, "label": s.label, "visible": None, "pageerrors": [], "error": ""}
            try:
                driver.goto(s)
                step["visible"] = driver.is_visible(s.dom_id) if s.dom_id else None
                driver.console_errors()
                step["pageerrors"] = list(driver.last_pageerrors)
                if driver.last_pageerrors:
                    result["pageerrors"].extend(
                        f"{s.id}: {e}" for e in driver.last_pageerrors
                    )
                if driver.last_console_error_lines:
                    result["console_error_sample"].extend(
                        f"{s.id}: {e}" for e in driver.last_console_error_lines[:2]
                    )
                # drill this tab's own subtabs
                if s.id.startswith("tab_"):
                    for sub in _subtabs_of(page):
                        sid = f"{s.id}/{sub}"
                        if sid in seen:
                            continue
                        seen.add(sid)
                        sstep = {"id": sid, "label": sid, "visible": None, "pageerrors": []}
                        try:
                            driver.goto(
                                Surface(sid, sid, nav_tab=s.nav_tab, subtab=sub, dom_id="")
                            )
                            driver.console_errors()
                            sstep["pageerrors"] = list(driver.last_pageerrors)
                            if driver.last_pageerrors:
                                result["pageerrors"].extend(
                                    f"{sid}: {e}" for e in driver.last_pageerrors
                                )
                        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
                            sstep["error"] = f"{type(exc).__name__}: {exc}"[:200]
                        result["steps"].append(sstep)
            except Exception as exc:  # noqa: BLE001
                step["error"] = f"{type(exc).__name__}: {exc}"[:200]
            result["steps"].append(step)
        ctx.close()
        browser.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-candidates", action="store_true")
    ap.add_argument("--candidates", type=Path)
    ap.add_argument("--baseline", type=Path, help="frozen globals file to diff against")
    ap.add_argument("--baseline-out", type=Path, help="write the frozen globals file")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--shots", type=Path)
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--throttle", type=int, default=6)
    ap.add_argument("--loads", type=int, default=5)
    ap.add_argument("--state-b", default=STATE_B_URL)
    ap.add_argument("--state-c", default=STATE_C_URL)
    args = ap.parse_args()

    if args.emit_candidates:
        print(json.dumps(emit_candidates(), indent=1))
        return

    if args.measure:
        out = {
            "schema": "oo-appjs-parse-1",
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "state_c": measure_parse(args.state_c, throttle=args.throttle, loads=args.loads),
        }
        print(json.dumps(out, indent=1))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(out, indent=1))
        return

    cands = json.loads(args.candidates.read_text())["candidates"]
    report = {
        "schema": "oo-appjs-split-check-1",
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "candidate_count": len(cands),
        "states": [],
    }
    for nm, url in (("B-empty", args.state_b), ("C-populated", args.state_c)):
        shots = (args.shots / nm) if args.shots else None
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
        report["states"].append(walk_state(nm, url, cands, shots))

    resolving = sorted(set(report["states"][-1]["globals_resolving"]))
    if args.baseline_out:
        args.baseline_out.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_out.write_text(
            json.dumps({"globals": resolving, "count": len(resolving)}, indent=1)
        )
        print(f"baseline written: {len(resolving)} resolving globals")

    verdict = {"ok": True, "reasons": []}
    if args.baseline:
        base = set(json.loads(args.baseline.read_text())["globals"])
        now = set(resolving)
        missing = sorted(base - now)
        added = sorted(now - base)
        report["globals_missing_vs_baseline"] = missing
        report["globals_added_vs_baseline"] = added
        if missing:
            verdict["ok"] = False
            verdict["reasons"].append(f"{len(missing)} globals no longer resolve: {missing[:12]}")

    for st in report["states"]:
        if st["boot_pageerrors"]:
            verdict["ok"] = False
            verdict["reasons"].append(f"{st['state']}: boot pageerror {st['boot_pageerrors'][:3]}")
        if st["pageerrors"]:
            verdict["ok"] = False
            verdict["reasons"].append(f"{st['state']}: {len(st['pageerrors'])} pageerrors")
    report["verdict"] = verdict

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1))
    for st in report["states"]:
        vis = sum(1 for s in st["steps"] if s.get("visible") is True)
        errs = sum(1 for s in st["steps"] if s.get("error"))
        print(
            f"{st['state']}: {len(st['steps'])} steps, {vis} visible, {errs} nav errors, "
            f"{len(st['pageerrors'])} pageerrors, {len(st['globals_resolving'])} globals"
        )
    print("VERDICT:", "PASS" if verdict["ok"] else "FAIL")
    for r in verdict["reasons"]:
        print("  -", r)
    sys.exit(0 if verdict["ok"] else 1)


if __name__ == "__main__":
    main()
