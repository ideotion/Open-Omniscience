#!/usr/bin/env python3
"""
mutation_checks -- proof that the look (scripts/analytics45_look.py) can FAIL.

A walk that has only ever passed proves nothing about its judges. This serves the page a deliberately
broken copy of one static file at a time (through the look's own ``--serve``; the working tree is never
touched) and requires the look to exit non-zero AND to name the check that should have caught it:

  1. the changes cell draws `0` where it must say `unknown` (an edition the stream recorded nothing for)
  2. the attention edition drop-down no longer reloads the table on a pick
  3. the attention edition drop-down is redrawn showing the OLD edition after a pick (a revert)
  4. the phone-width table rules are removed (the last column is cut off at 360 px)

and first that the UNMUTATED page passes the same single run (the control), so a failure is the mutation's.
Writes mutation-results.json beside this file. Run against a booted offline app:

    python docs/audit/analytics45-look-2026-10-12/mutation_checks.py --url http://127.0.0.1:8014

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STATIC = ROOT / "src" / "static"
LOOK = ROOT / "scripts" / "analytics45_look.py"

_UNKNOWN_CELL = (
    '''`<span class="muted" title="${esc(t("The live stream has recorded nothing for this edition on this machine, so the count is unknown, not zero."))}">${esc(t("unknown"))}</span>`'''
)
_HANDLER = '''if (e.target && e.target.id === "wiki-att-edition") loadWikiAttention(e.target.value, true);'''
_SELECTED = '''e === pick ? " selected" : ""'''

MUTATIONS = [
    {"name": "changes cell draws 0 for an unknown count", "file": "app-living.js", "old": _UNKNOWN_CELL, "new": "`0`",
     "width": "1440x900", "expect": "changes 3, 0, then unknown", "expect_generated": "changes ["},
    {"name": "edition drop-down no longer reloads the table", "file": "app-living.js", "old": _HANDLER,
     "new": 'if (e.target && e.target.id === "wiki-att-edition") { /* mutated: no reload */ }',
     "width": "1440x900", "expect": "the run completed"},
    {"name": "edition drop-down redrawn showing the old edition", "file": "app-living.js", "old": _SELECTED,
     "new": 'e === "en" ? " selected" : ""', "width": "1440x900", "expect": "edition drop-down: de picked"},
    {"name": "phone-width table rules removed", "file": "app.css", "regex": r"@media \(max-width: 480px\) \{\n  \.wiki-table-wrap.*?\n\}\n@media \(max-width: 340px\) \{.*?\n\}\n",
     "new": "", "width": "360x800", "expect": "fits its frame"},
]


def run_look(url: str, width: str, serve: tuple[str, Path] | None, out: Path, truth: str | None = None) -> tuple[int, list[str]]:
    cmd = [sys.executable, str(LOOK), "--url", url, "--out", str(out), "--width", width, "--theme", "ink", "--lang", "en"]
    if truth:
        cmd += ["--truth", truth]
    if serve:
        cmd += ["--serve", f"{serve[0]}={serve[1]}"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    failed = []
    results = out / "look-results.json"
    if results.is_file():
        data = json.loads(results.read_text(encoding="utf-8"))
        failed = [c["check"] for r in data["runs"] for c in r["checks"] if c["status"] != "ok"]
    return done.returncode, failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--truth", help="judge a GENERATED state (the JSON analytics45_generate.py printed) instead of the seeded one")
    ap.add_argument("--results", help="where to write the results JSON (default: mutation-results.json beside this file)")
    a = ap.parse_args()
    if a.truth and not a.results:
        ap.error("--truth needs --results: the default file is the committed record of the SEEDED look and must not be overwritten")
    report: dict = {"control": None, "mutations": []}
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        rc, failed = run_look(a.url, "1440x900", None, tmpd / "control", a.truth)
        report["control"] = {"exit": rc, "failed": failed}
        ok &= rc == 0 and not failed
        for i, m in enumerate(MUTATIONS):
            src = (STATIC / m["file"]).read_text(encoding="utf-8")
            if "regex" in m:
                mutated, n = re.subn(m["regex"], m["new"], src, count=1, flags=re.S)
            else:
                n = src.count(m["old"])
                mutated = src.replace(m["old"], m["new"], 1)
            if n != 1 or mutated == src:
                report["mutations"].append({"name": m["name"], "error": f"the text to mutate was found {n} times, not once"})
                ok = False
                continue
            path = tmpd / f"mut{i}-{m['file']}"
            path.write_text(mutated, encoding="utf-8")
            rc, failed = run_look(a.url, m["width"], (m["file"], path), tmpd / f"mut{i}", a.truth)
            expect = m["expect_generated"] if a.truth and "expect_generated" in m else m["expect"]
            caught = rc != 0 and any(expect in c for c in failed)
            ok &= caught
            report["mutations"].append({"name": m["name"], "width": m["width"], "exit": rc, "expected_check": expect,
                                        "failed_checks": failed, "caught": caught})
    Path(a.results or HERE / "mutation-results.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"control_exit": report["control"]["exit"], "caught": [m.get("caught") for m in report["mutations"]]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
