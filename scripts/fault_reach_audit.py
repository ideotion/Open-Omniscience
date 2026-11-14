#!/usr/bin/env python3
"""Run the fault-reach audit (OPEN_QUEUE item 30, R412): which tests install a fault that never fires?

    python scripts/fault_reach_audit.py                    # every candidate test file, -n auto
    python scripts/fault_reach_audit.py -n 4 tests/test_x.py   # some files, four workers
    python scripts/fault_reach_audit.py --issue            # also open / edit / close the rolling GitHub issue (the weekly job)

The method is in ``tests/fault_reach.py``. This script picks the candidate files (a test that installs a raising stub or a lambda
``.throw``, or a file that mentions ``side_effect``), runs pytest over them with the plugin, folds parametrized cases onto their
function and compares the result with the reviewed baseline ``tests/fault_reach_baseline.txt``:

* NEW: a test that ran, installed a non-guard fault and never fired it, and is not in the baseline. Read it: either the test is vacuous
  (fix it so the code reaches the fault, proved by a mutant that is red under the fixed test) or the zero is correct (add it to the
  baseline with the reason, one line).
* STALE: a baseline line whose test ran and now fires its fault, or that names a test which no longer exists. Remove it.

Exit 0 when both lists are empty, 1 otherwise, 2 when pytest itself did not run. The report goes to ``--report`` (Markdown). It is a
weekly job (``.github/workflows/fault-reach.yml``) and never a PR gate: the hand reading is the expensive part, and a new fault test then
gets read once, not on every PR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.fault_reach import GUARD_EXCEPTIONS, analyse  # noqa: E402

BASELINE = ROOT / "tests" / "fault_reach_baseline.txt"
_LABEL = "fault-reach"
_TITLE = "Fault-reach audit: tests whose injected fault never fires"


def function_key(nodeid: str) -> str:
    """``tests/x.py::TestC::test_y[case]`` -> ``tests/x.py::TestC::test_y``."""
    return re.sub(r"\[.*\]$", "", nodeid)


def candidate_files(root: Path = ROOT) -> list[Path]:
    out = []
    for p in sorted((root / "tests").rglob("test_*.py")):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "side_effect" in text:
            out.append(p)
            continue
        try:
            if analyse(p).installs:
                out.append(p)
        except SyntaxError:
            continue
    return out


def read_baseline(path: Path = BASELINE) -> dict[str, str]:
    """``key<TAB>reason`` per line; ``#`` starts a comment line. A line without a reason is refused."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        key, sep, reason = line.partition("\t")
        if not sep or not reason.strip() or "::" not in key:
            raise ValueError(f"{path.name}:{n}: expected 'tests/<file>.py::<test><TAB><reason>', got {raw!r}")
        if key in out:
            raise ValueError(f"{path.name}:{n}: {key} is listed twice")
        out[key] = reason.strip()
    return out


@dataclass
class Device:
    kind: str  # "stub" or "mock"
    name: str
    where: str  # file:line(s)
    exceptions: list[str]


@dataclass
class Verdict:
    flagged: dict[str, list[Device]] = field(default_factory=dict)  # key -> its never-fired devices
    ran: set[str] = field(default_factory=set)
    installed: set[str] = field(default_factory=set)  # keys with at least one non-guard device


def judge(results: list[dict], root: Path = ROOT) -> Verdict:
    """Fold the plugin's per-worker results into one verdict per test function."""
    hits: set[tuple[str, str, int]] = set()
    ran: set[str] = set()
    mock_sites: dict[tuple[str, str, int], set[str]] = defaultdict(set)
    mock_hits: set[tuple[str, str, int]] = set()
    for r in results:
        hits.update((a, b, c) for a, b, c in r["hits"])
        ran.update(r["ran"])
        for nodeid, f, ln, excs in r["mock_sites"]:
            mock_sites[(nodeid, f, ln)].update(excs)
        mock_hits.update((a, b, c) for a, b, c in r["mock_hits"])

    fired_lines: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for nodeid, f, ln in hits:
        fired_lines[function_key(nodeid)].add((f, ln))
    v = Verdict(ran={function_key(n) for n in ran})

    devices: dict[str, list[tuple[Device, bool]]] = defaultdict(list)
    static_cache: dict[str, dict] = {}
    for key in v.ran:
        rel, _, qual = key.partition("::")
        if rel not in static_cache:
            p = (root / rel).resolve()
            try:
                static_cache[rel] = {"abs": str(p), "installs": analyse(p).installs}
            except (OSError, SyntaxError, UnicodeDecodeError):
                static_cache[rel] = {"abs": str(p), "installs": {}}
        info = static_cache[rel]
        for s in info["installs"].get(qual, []):
            if s.guard:
                continue
            fired = any((info["abs"], ln) in fired_lines[key] for ln in s.lines)
            span = f"{min(s.lines)}" if len(s.lines) == 1 else f"{min(s.lines)}-{max(s.lines)}"
            devices[key].append((Device("stub", s.name, f"{rel}:{span}", sorted(s.exceptions)), fired))
    for (nodeid, f, ln), excs in mock_sites.items():
        if excs <= GUARD_EXCEPTIONS:
            continue
        key = function_key(nodeid)
        rel = os.path.relpath(f, root)
        devices[key].append((Device("mock", "side_effect", f"{rel}:{ln}", sorted(excs)), (nodeid, f, ln) in mock_hits))

    for key, devs in devices.items():
        if key not in v.ran:
            continue
        # one device per site: the same mock line in several parametrized cases folds to one entry, fired if any case fired it
        by_site: dict[tuple[str, str], tuple[Device, bool]] = {}
        for d, fired in devs:
            prev = by_site.get((d.kind, d.where))
            by_site[(d.kind, d.where)] = (d, fired or (prev[1] if prev else False))
        v.installed.add(key)
        if not any(f for _, f in by_site.values()):
            v.flagged[key] = [d for d, _ in by_site.values()]
    return v


def run_pytest(files: list[Path], workers: str, out_dir: Path, basetemp: str | None = None) -> int:
    env = dict(os.environ, FAULT_REACH_DIR=str(out_dir))
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.fault_reach", "-o", "addopts="]
    if workers != "0":
        args += ["-n", workers, "--dist", "loadfile"]
    if basetemp:
        args += ["--basetemp", basetemp]
    args += [str(f.relative_to(ROOT)) for f in files]
    return subprocess.run(args, cwd=ROOT, env=env, check=False).returncode


def load_results(out_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("reach-*.json"))]


def existing_tests(keys: set[str], root: Path = ROOT) -> set[str]:
    """Which of ``keys`` still name a test function in the tree (static, so a skipped test still counts as existing)."""
    import ast

    by_file: dict[str, set[str]] = defaultdict(set)
    for k in keys:
        rel, _, qual = k.partition("::")
        by_file[rel].add(qual)
    out: set[str] = set()
    for rel, quals in by_file.items():
        p = root / rel
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        names = set()
        for st in tree.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(st.name)
            elif isinstance(st, ast.ClassDef):
                names.update(f"{st.name}::{m.name}" for m in st.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
        out.update(f"{rel}::{q}" for q in quals if q in names)
    return out


def compare(v: Verdict, baseline: dict[str, str], scope_all: bool, root: Path = ROOT) -> tuple[dict[str, list[Device]], dict[str, str]]:
    new = {k: d for k, d in v.flagged.items() if k not in baseline}
    alive = existing_tests(set(baseline), root)
    stale = {}
    for k in baseline:
        if k not in alive:
            stale[k] = "no such test any more"
        elif k in v.ran and k not in v.flagged:
            stale[k] = "it ran and fired its fault" if k in v.installed else "it ran and no longer installs a non-guard fault"
        elif scope_all and k not in v.ran:
            pass  # skipped in this environment: neither stale nor confirmed
    return new, stale


def report(v: Verdict, new: dict[str, list[Device]], stale: dict[str, str], baseline: dict[str, str]) -> str:
    out = ["# Fault-reach audit", ""]
    out.append(
        f"{len(v.ran)} test functions ran; {len(v.installed)} installed a non-guard fault; {len(v.flagged)} never fired one "
        f"({len(v.flagged) - len(new)} of them reviewed in the baseline, {len(new)} new). Stale baseline lines: {len(stale)}."
    )
    out.append("")
    out.append("A NEW test is vacuous until shown otherwise: fix it so the code reaches the fault (and prove it with a source mutant the old "
               "test let through), or add it to `tests/fault_reach_baseline.txt` with the reason the right count is zero.")
    if new:
        out += ["", "## New", ""]
        for k in sorted(new):
            out.append(f"- `{k}`")
            for d in new[k]:
                out.append(f"  - {d.kind} `{d.name}` at `{d.where}` raises {', '.join(d.exceptions) or '?'}")
    if stale:
        out += ["", "## Stale baseline lines (remove them)", ""]
        out += [f"- `{k}`: {why}" for k, why in sorted(stale.items())]
    not_run = sorted(k for k in baseline if k not in v.ran and k not in stale)
    if not_run:
        out += ["", f"## Baseline lines not checked here ({len(not_run)}: skipped or not collected in this environment)", ""]
        out += [f"- `{k}`" for k in not_run]
    return "\n".join(out) + "\n"


def _gh(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 127, "gh not installed"
    return p.returncode, (p.stdout or p.stderr).strip()


def sync_issue(actionable: bool, body: str) -> None:
    """One rolling issue: open or edit it while something needs reading, close it when nothing does. A gh failure is printed, never fatal."""
    rc, out = _gh(["issue", "list", "--label", _LABEL, "--state", "open", "--json", "number", "--jq", ".[0].number"])
    number = out if rc == 0 and out.isdigit() else None
    if actionable:
        if number:
            rc, out = _gh(["issue", "edit", number, "--body", body])
        else:
            _gh(["label", "create", _LABEL, "--color", "c5def5", "--description", "weekly fault-reach audit"])
            rc, out = _gh(["issue", "create", "--title", _TITLE, "--label", _LABEL, "--body", body])
    elif number:
        rc, out = _gh(["issue", "close", number, "--comment", "The fault-reach audit is clean this week."])
    if rc != 0:
        print(f"fault-reach: issue sync failed ({rc}): {out}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="test files (default: every candidate file)")
    ap.add_argument("-n", default="auto", help="pytest-xdist workers ('0' for none; default auto)")
    ap.add_argument("--report", default="fault-reach-report.md")
    ap.add_argument("--basetemp", help="passed to pytest")
    ap.add_argument("--keep", help="copy the plugin's raw results into this folder")
    ap.add_argument("--results", help="judge the raw results kept in this folder instead of running pytest")
    ap.add_argument("--issue", action="store_true", help="open, edit or close the rolling GitHub issue")
    a = ap.parse_args(argv)

    baseline = read_baseline()
    files = [Path(f).resolve() for f in a.files] if a.files else candidate_files()
    if a.results:  # judge a kept run again without running pytest (the analysis may have moved since)
        rc, results = 0, load_results(Path(a.results))
    else:
        with tempfile.TemporaryDirectory(prefix="fault-reach-") as td:
            rc = run_pytest(files, a.n, Path(td), a.basetemp)
            results = load_results(Path(td))
            if a.keep:
                Path(a.keep).mkdir(parents=True, exist_ok=True)
                for r in Path(td).glob("reach-*.json"):
                    (Path(a.keep) / r.name).write_bytes(r.read_bytes())
    if not results or rc not in (0, 1):
        print(f"fault-reach: pytest did not run cleanly (exit {rc}, {len(results)} result files)", file=sys.stderr)
        return 2
    v = judge(results)
    if a.files:  # a partial run cannot call a baseline line for another file stale
        rels = {str(f.relative_to(ROOT)) for f in files}
        baseline = {k: r for k, r in baseline.items() if k.partition("::")[0] in rels}
    new, stale = compare(v, baseline, scope_all=not a.files)
    text = report(v, new, stale, baseline)
    Path(a.report).write_text(text, encoding="utf-8")
    print(text)
    if a.issue:
        sync_issue(bool(new or stale), text)
    return 1 if (new or stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
