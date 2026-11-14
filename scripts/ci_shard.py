#!/usr/bin/env python3
"""Split the test suite into cost-balanced shards for CI, say which files a shard runs, and prove that the shards together ran what one process ran.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

    python scripts/ci_shard.py plan   --shard 2/3 --out FILE   # write `--ignore=<file>` for every test file shard 2 of 3 does NOT run (pytest @FILE), and say how many it runs
    python scripts/ci_shard.py files  --shard 2/3              # the test files shard 2 of 3 runs, on stdout
    python scripts/ci_shard.py check                           # every test file of the tree is in exactly one shard (exit 1 if not)
    python scripts/ci_shard.py digest [--pack] JUNIT_XML        # one line per test module: outcome counts and a hash of its (test, outcome) pairs
    python scripts/ci_shard.py collected --all ALL.txt S1.txt S2.txt ...   # the shards' `pytest --collect-only -q` together are the whole suite's (exit 1 if not)
    python scripts/ci_shard.py totals JUNIT_XML                # passed / skipped / xfailed / failed / error counts of a report, on one line
    python scripts/ci_shard.py parity --shard 2/3 --junit JUNIT_XML --oracle-env NAME   # compare this shard with an unsharded run's digest
    python scripts/ci_shard.py costs  [--stdout] [--min-seconds S] JUNIT_XML [...]   # rewrite configs/ci_shard_costs.json from measured per-module times

WHY. The CI ``test`` and ``core-only`` jobs each ran the whole suite in one process, 70 to 80 minutes, and the run's wall time was the slower
of the two (R412, decision 27). Each is now three jobs that each run a third of the files, so a PR waits for about the longest third.

HOW A FILE GETS ITS SHARD (and why it is not a plain round robin, a hash, or a hand-kept list).
* Files named in ``configs/ci_shard_costs.json`` (path -> seconds, measured) are dealt out longest first, each to the shard with the least
  work so far (LPT). The result depends on that table alone: adding or deleting a test file, or reading the files in another order, does not
  move any file that is in the table. A cost table is a measurement of ONE tree, so it ages; ``costs`` below rewrites it from a junit report.
* A file the table does not name (a new test file) goes to shard ``crc32(path) % N + 1``: stable, needs no edit in the PR that adds the file
  (a hand-kept list would conflict between open PRs after every merge, the shared-tail problem the ledger rules already fought), and spreads
  new files evenly in the long run. ``plan`` prints how many files were not in the table, so a table that has fallen behind is read, not guessed.
* ``overhead_seconds`` is a head start per shard for work a leg does besides its tests. Shard 1 ran the static steps of the ``test`` job until
  R668 (2026-11-13) moved them to the ``static`` job, so the list is empty now: the 80 it carried stayed until the two order-dependent tests the
  first re-deal exposed were made independent of their neighbours (R674, PR #1943), and went in the PR after it (docs/maintenance/CI_SHARDS.md).

HOW A SHARD IS RUN (and why it is not "pytest FILE FILE ..."). A shard ignores the other shards' files and lets pytest collect ``tests`` itself, so
everything the one-process run relied on at collection still applies: ``collect_ignore`` in tests/conftest.py (which keeps the analysis tests out of a
core-only install), ``norecursedirs``, ``python_files``. A path NAMED on the command line is not subject to ``collect_ignore``: the first sharded
Core-only leg passed its files explicitly, collected the two analysis modules a core-only install must not collect, and died at import. ``pytest @FILE``
with nothing but ``--ignore`` lines also fails safe: a shard that ignores every file ends in "no tests ran" (exit 5), where an empty list of files would
have run the whole suite.

WHAT IT IS NOT. It is not an isolation model: a test that passed only because an earlier test in the same process had left something behind
is a bug whichever shard it falls in, and the first sharded run is where it shows. ``parity`` is how that was looked for once: it compares a
shard's junit report with the digest of an unsharded run of the same commit, module by module, outcome by outcome, and names every difference.
It sees outcomes, not what a test did, and a test that passes in both but for different reasons is invisible to it.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COSTS = ROOT / "configs" / "ci_shard_costs.json"

#: pytest's own collection patterns (``python_files`` in pyproject.toml): a file the suite can collect.
_PATTERNS = ("test_*.py", "*_test.py")
#: One shard spec, ``I/N``.
_SPEC = re.compile(r"([1-9][0-9]*)/([1-9][0-9]*)")
_UNNAMED = "(unnamed)"
_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def parse_shard(spec: str) -> tuple[int, int]:
    """``"2/3"`` -> ``(2, 3)``. Raises ``ValueError`` for anything else, including a shard past the count."""
    found = _SPEC.fullmatch(spec.strip())
    if not found or int(found.group(1)) > int(found.group(2)):
        raise ValueError(f"a shard is written I/N with 1 <= I <= N, not {spec!r}")
    return int(found.group(1)), int(found.group(2))


def test_files(root: Path = ROOT) -> list[str]:
    """Every file pytest would collect under ``tests/``, as sorted posix paths relative to ``root``."""
    found = {
        path.relative_to(root).as_posix()
        for pattern in _PATTERNS
        for path in (root / "tests").rglob(pattern)
        if path.is_file()
    }
    return sorted(found)


def load_table(path: Path = COSTS) -> dict:
    """The cost table: ``{"shards": N, "overhead_seconds": [...], "costs": {path: seconds}, ...}``. Raises ``ValueError`` if it is malformed."""
    data = json.loads(path.read_text(encoding="utf-8"))
    costs = data.get("costs")
    if not isinstance(costs, dict) or not all(isinstance(k, str) and isinstance(v, (int, float)) and v >= 0 for k, v in costs.items()):
        raise ValueError(f"{path}: costs must map a path to a non-negative number of seconds")
    if not isinstance(data.get("shards"), int) or data["shards"] < 1:
        raise ValueError(f"{path}: shards must be a positive integer")
    overhead = data.get("overhead_seconds", [])
    if not isinstance(overhead, list) or len(overhead) > data["shards"] or not all(isinstance(v, (int, float)) and v >= 0 for v in overhead):
        raise ValueError(f"{path}: overhead_seconds must be a list of at most `shards` non-negative numbers")
    return data


def deal(costs: dict[str, float], shards: int, overhead: list[float] | None = None) -> dict[str, int]:
    """Longest first, each file to the shard with the least work so far (ties: the lower shard). Returns ``{path: shard}`` with shards from 1.

    Depends on ``costs`` and ``overhead`` only, and on nothing about the order they are given in."""
    loads = [float(v) for v in (overhead or [])] + [0.0] * shards
    loads = loads[:shards]
    out: dict[str, int] = {}
    for path in sorted(costs, key=lambda p: (-float(costs[p]), p)):
        at = min(range(shards), key=lambda k: (loads[k], k))
        out[path] = at + 1
        loads[at] += float(costs[path])
    return out


def unlisted_shard(path: str, shards: int) -> int:
    """The shard of a file the cost table does not name: a hash that is the same in every process, on every Python."""
    return zlib.crc32(path.encode("utf-8")) % shards + 1


def assign(files: list[str], shards: int, table: dict) -> dict[str, int]:
    """``{file: shard}`` for every file in ``files``. The table's own assignment is made for N = ``shards`` whatever the table's ``shards`` says."""
    dealt = deal(table["costs"], shards, table.get("overhead_seconds"))
    return {path: dealt.get(path) or unlisted_shard(path, shards) for path in files}


def shard_lookup(shards: int, table: dict):
    """A function path -> shard, dealing the table once (``assign`` for many paths one at a time would deal it for each)."""
    dealt = deal(table["costs"], shards, table.get("overhead_seconds"))
    return lambda path: dealt.get(path) or unlisted_shard(path, shards)


def files_of(shard: int, shards: int, table: dict, root: Path = ROOT) -> list[str]:
    return [path for path, at in assign(test_files(root), shards, table).items() if at == shard]


def ignore_args(mine: list[str], files: list[str]) -> list[str]:
    """The pytest arguments that run exactly ``mine`` of ``files``: ``--ignore=<file>`` for every other one, one per line. See HOW A SHARD IS RUN."""
    own = set(mine)
    return [f"--ignore={f}" for f in files if f not in own]


def predicted(files: list[str], table: dict, shard: int, shards: int) -> tuple[float, int]:
    """(seconds the table predicts for these files plus the shard's overhead, how many of them the table does not name)."""
    costs = table["costs"]
    overhead = list(table.get("overhead_seconds", [])) + [0.0] * shards
    return float(overhead[shard - 1]) + sum(float(costs.get(f, 0.0)) for f in files), sum(1 for f in files if f not in costs)


def problems(files: list[str], shards: int, table: dict) -> list[str]:
    """Why dealing ``files`` into ``shards`` is not a partition (empty when it is one): a file in no shard or in two, or a shard with nothing to run."""
    found: list[str] = []
    mapping = assign(files, shards, table)
    lists = {k: [f for f in files if mapping.get(f) == k] for k in range(1, shards + 1)}
    seen: Counter[str] = Counter(f for group in lists.values() for f in group)
    found += [f"{path} is in {seen[path]} shards" for path in sorted(files) if seen[path] != 1]
    found += [f"shard {k}/{shards} has no test file" for k, group in lists.items() if not group]
    return found


# --------------------------------------------------------------------------------------------- junit digests
def _module_of(classname: str, name: str) -> str:
    """``tests/test_x.py`` for a testcase of that file, or ``(unnamed)``. A collection-time skip has no classname; its name is the dotted module."""
    dotted = classname or name
    if len(dotted) > 300 or not _DOTTED.fullmatch(dotted):
        return _UNNAMED
    parts = dotted.split(".")
    for at, part in enumerate(parts):
        if at and (part.startswith("test_") or part.endswith("_test")):
            return "/".join(parts[: at + 1]) + ".py"
    return _UNNAMED


def _outcome(case) -> str:
    """One letter for one testcase: e error, f failure, s skipped, x expected failure, p passed (the worst one wins)."""
    kinds = {child.tag for child in case}
    if "error" in kinds:
        return "e"
    if "failure" in kinds:
        return "f"
    marker = case.find("skipped")
    if marker is not None:
        return "x" if marker.get("type") == "pytest.xfail" else "s"
    return "p"


def read_junit(path: Path) -> list[tuple[str, str, str, float]]:
    """``(module, test id, outcome letter, seconds)`` for every testcase of a junit report. Raises ``OSError`` or ``ValueError`` if it cannot be read."""
    try:
        from defusedxml import ElementTree as defused
    except ImportError as exc:  # pragma: no cover - defusedxml is a core dependency
        raise ValueError("defusedxml is not installed") from exc
    try:
        root = defused.parse(str(path)).getroot()
    except defused.ParseError as exc:
        raise ValueError(f"{path}: not a readable junit report ({exc})") from None
    rows = []
    for case in root.iter("testcase"):
        classname, name = case.get("classname") or "", case.get("name") or ""
        try:
            seconds = float(case.get("time") or 0.0)
        except ValueError:
            seconds = 0.0
        rows.append((_module_of(classname, name), f"{classname}::{name}", _outcome(case), seconds if seconds == seconds and seconds >= 0 else 0.0))
    return rows


def digest(rows: list[tuple[str, str, str, float]]) -> dict[str, dict]:
    """Per module: outcome counts, a 12-hex hash of its sorted ``test id, outcome`` pairs, and its seconds."""
    grouped: dict[str, list[tuple[str, str, float]]] = {}
    for module, test_id, letter, seconds in rows:
        grouped.setdefault(module, []).append((test_id, letter, seconds))
    out = {}
    for module, cases in grouped.items():
        pairs = sorted((test_id, letter) for test_id, letter, _ in cases)
        text = "\n".join(f"{test_id}\t{letter}" for test_id, letter in pairs)
        counts = Counter(letter for _, letter, _ in cases)
        out[module] = {
            "counts": "".join(f"{counts[k]}{k}" for k in "psxfe" if counts[k]),
            "hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
            "seconds": round(sum(s for _, _, s in cases), 3),
        }
    return out


def totals(dig: dict[str, dict]) -> Counter[str]:
    """Outcome letter -> number of tests, over every module of a digest (the ``unnamed`` bucket included: a test is a test)."""
    out: Counter[str] = Counter()
    for d in dig.values():
        for count, letter in re.findall(r"([0-9]+)([psxfe])", d["counts"]):
            out[letter] += int(count)
    return out


def describe(count: Counter[str]) -> str:
    return " ".join(f"{count[k]} {word}" for k, word in (("p", "passed"), ("s", "skipped"), ("x", "xfailed"), ("f", "failed"), ("e", "errors")))


def render(dig: dict[str, dict]) -> str:
    return "\n".join(f"{module} {d['counts']} {d['hash']} {d['seconds']}" for module, d in sorted(dig.items())) + "\n"


def parse_rendered(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        module, counts, hashed, seconds = line.rsplit(" ", 3)
        out[module] = {"counts": counts, "hash": hashed, "seconds": float(seconds)}
    return out


def pack(text: str) -> str:
    """Text -> one line of ASCII that fits a job output (gzip, then base64)."""
    return base64.b64encode(gzip.compress(text.encode("utf-8"), 9, mtime=0)).decode("ascii")


def unpack(blob: str) -> str:
    return gzip.decompress(base64.b64decode(blob.strip())).decode("utf-8")


def compare(oracle: dict[str, dict], mine: dict[str, dict], shard: int, shards: int, table: dict) -> list[str]:
    """What differs between this shard's digest and the unsharded oracle's slice for the same shard: modules missing, extra, or with other outcomes.

    A testcase whose module cannot be told (``(unnamed)``) is left out of both sides; ``main`` says how many there were."""
    of = shard_lookup(shards, table)
    slice_ = {m: d for m, d in oracle.items() if m != _UNNAMED and of(m) == shard}
    mine = {m: d for m, d in mine.items() if m != _UNNAMED}
    found = []
    for module in sorted(set(slice_) - set(mine)):
        found.append(f"{module}: ran in the unsharded run ({slice_[module]['counts']}), absent from shard {shard}/{shards}")
    for module in sorted(set(mine) - set(slice_)):
        found.append(f"{module}: ran in shard {shard}/{shards} ({mine[module]['counts']}), absent from the unsharded run's slice of this shard")
    for module in sorted(set(mine) & set(slice_)):
        a, b = slice_[module], mine[module]
        if (a["counts"], a["hash"]) != (b["counts"], b["hash"]):
            found.append(f"{module}: unsharded {a['counts']} {a['hash']}, shard {shard}/{shards} {b['counts']} {b['hash']}")
    return found


def read_collected(text: str) -> list[str]:
    """The test ids in the output of ``pytest --collect-only -q``: one ``path.py::name`` per line (the summary and blank lines are not ids)."""
    return [line.strip() for line in text.splitlines() if "::" in line and line.split("::", 1)[0].strip().endswith(".py") and " " not in line.split("::", 1)[0].strip()]


def module_count(ids: list[str]) -> int:
    return len({i.split("::", 1)[0] for i in ids})


def compare_collected(everything: list[str], shards: list[list[str]]) -> list[str]:
    """What differs between one collection of the whole suite and the shards' collections: ids no shard collected, ids a shard collected that the
    whole did not, ids collected twice (within a shard or by two shards). Empty when the shards are a partition of the whole."""
    whole = Counter(everything)
    seen: Counter[str] = Counter()
    which: dict[str, list[int]] = {}
    for number, ids in enumerate(shards, 1):
        for test_id in ids:
            seen[test_id] += 1
            which.setdefault(test_id, []).append(number)
    found = [f"{i}: collected by the whole suite, by no shard" for i in sorted(set(whole) - set(seen))]
    found += [f"{i}: collected by shard {which[i]}, not by the whole suite" for i in sorted(set(seen) - set(whole))]
    found += [f"{i}: collected {seen[i]} times by shards {which[i]}, {whole[i]} time(s) by the whole suite" for i in sorted(set(seen) & set(whole)) if seen[i] != whole[i]]
    return found


def measured_table(old: dict, reports: list[Path], min_seconds: float = 0.0) -> dict:
    """The table with ``costs`` replaced by the summed per-module seconds of the reports, rounded to a tenth. ``shards`` and the overhead are kept.

    A module under ``min_seconds`` is left out: it falls to the hash like a new file, which spreads the many small ones evenly and keeps the table short."""
    seconds: dict[str, float] = {}
    for report in reports:
        for module, _, _, took in read_junit(report):
            if module != _UNNAMED:
                seconds[module] = seconds.get(module, 0.0) + took
    return {**old, "costs": {m: round(s, 1) for m, s in sorted(seconds.items()) if s >= min_seconds}}


# --------------------------------------------------------------------------------------------------- CLI
def _table_path(args) -> Path:
    return Path(args.table) if args.table else COSTS


def _table_for(args) -> dict:
    return load_table(_table_path(args))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--table", help="the cost table (default configs/ci_shard_costs.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "files", "parity"):
        p = sub.add_parser(name)
        p.add_argument("--shard", required=True, metavar="I/N")
        if name == "plan":
            p.add_argument("--out", required=True)
        if name == "parity":
            p.add_argument("--junit", required=True)
            p.add_argument("--oracle-env", required=True, help="the name of an environment variable holding the unsharded digest, packed")
    sub.add_parser("check")
    g = sub.add_parser("collected", help="compare `pytest --collect-only -q` of the whole suite with the shards' (a partition, or the differing test ids)")
    g.add_argument("--all", required=True, help="the output of `pytest --collect-only -q` with no shard")
    g.add_argument("shard_outputs", nargs="+", help="the outputs of `pytest --collect-only -q @shard.args`, one per shard")
    sub.add_parser("totals").add_argument("junit")
    d = sub.add_parser("digest")
    d.add_argument("--pack", action="store_true", help="print the digest gzipped and base64-encoded on one line (a job output)")
    d.add_argument("junit")
    c = sub.add_parser("costs")
    c.add_argument("--stdout", action="store_true", help="print the table as compact JSON instead of rewriting configs/ci_shard_costs.json")
    c.add_argument("--min-seconds", type=float, default=0.0)
    c.add_argument("junit", nargs="+")
    args = ap.parse_args(argv)
    try:
        table = _table_for(args)
        if args.cmd in ("plan", "files", "parity"):
            shard, shards = parse_shard(args.shard)
        if args.cmd == "files":
            print("\n".join(files_of(shard, shards, table)))
        elif args.cmd == "plan":
            every = test_files()
            mine = files_of(shard, shards, table)
            if not mine:
                print(f"shard {shard}/{shards} has no test files: refusing to write a plan that runs nothing", file=sys.stderr)
                return 1
            ignored = ignore_args(mine, every)
            if shards > 1 and not ignored:
                print(f"shard {shard}/{shards} would ignore no file, so it would run the whole suite: refusing to write that plan", file=sys.stderr)
                return 1
            Path(args.out).write_text("".join(f"{line}\n" for line in ignored), encoding="utf-8")
            seconds, new = predicted(mine, table, shard, shards)
            print(f"shard {shard}/{shards}: runs {len(mine)} of {len(every)} test files (ignores {len(ignored)}); the table predicts {round(seconds)} s; {new} not in the table")
        elif args.cmd == "check":
            files = test_files()
            found: list[str] = []
            for shards in sorted({1, table["shards"]}):
                found += problems(files, shards, table)
            for line in found:
                print(line)
            print(f"{len(files)} test files, {table['shards']} shards: {'a partition' if not found else str(len(found)) + ' problem(s)'}")
            return 1 if found else 0
        elif args.cmd == "collected":
            whole = read_collected(Path(args.all).read_text(encoding="utf-8"))
            parts = [read_collected(Path(f).read_text(encoding="utf-8")) for f in args.shard_outputs]
            found = compare_collected(whole, parts)
            for line in found[:100]:
                print(line)
            print(f"whole suite: {len(whole)} tests in {module_count(whole)} modules")
            for number, ids in enumerate(parts, 1):
                print(f"shard {number}: {len(ids)} tests in {module_count(ids)} modules")
            union = [i for ids in parts for i in ids]
            print(f"shards together: {len(union)} tests in {module_count(union)} modules; {len(found)} difference(s)")
            if not whole:
                print("the whole-suite collection holds no test id: nothing was compared", file=sys.stderr)
                return 1
            return 1 if found else 0
        elif args.cmd == "totals":
            dig = digest(read_junit(Path(args.junit)))
            print(f"{sum(totals(dig).values())} tests in {len(dig)} modules: {describe(totals(dig))}")
        elif args.cmd == "digest":
            text = render(digest(read_junit(Path(args.junit))))
            print(pack(text) if args.pack else text, end="" if not args.pack else "\n")
        elif args.cmd == "costs":
            fresh = measured_table(table, [Path(p) for p in args.junit], args.min_seconds)
            if args.stdout:
                print(json.dumps(fresh, separators=(",", ":"), sort_keys=True))
            else:
                target = _table_path(args)  # the table that was read is the table that is rewritten
                target.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n", encoding="utf-8")
                print(f"wrote {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")
        elif args.cmd == "parity":
            blob = os.environ.get(args.oracle_env, "")
            if not blob:
                print(f"parity: ${args.oracle_env} is empty: there is no unsharded digest to compare with", file=sys.stderr)
                return 1
            oracle = parse_rendered(unpack(blob))
            this = digest(read_junit(Path(args.junit)))
            found = compare(oracle, this, shard, shards, table)
            for line in found[:200]:
                print(line)
            named = sum(1 for m in this if m != _UNNAMED)
            of = shard_lookup(shards, table)
            theirs = {m: d for m, d in oracle.items() if m != _UNNAMED and of(m) == shard}
            want = totals(theirs)
            got = totals({m: d for m, d in this.items() if m != _UNNAMED})
            print(f"unsharded run, this shard's modules: {describe(want)}")
            print(f"this shard:                          {describe(got)}")
            print(f"parity shard {shard}/{shards}: {named} modules compared ({len(this) - named} unnamed left out), {len(found)} difference(s)")
            if not theirs and not named:
                # two empty sides have no difference to find; a comparison of nothing is not evidence (a conftest import error gives exactly that)
                print(f"parity shard {shard}/{shards}: nothing was compared (the unsharded run holds {len(theirs)} named modules of this shard, this shard {named})", file=sys.stderr)
                return 1
            if want != got:
                print("the passed, skipped, xfailed, failed or error counts differ")
                return 1
            return 1 if found else 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"ci_shard: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
