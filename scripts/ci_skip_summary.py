#!/usr/bin/env python3
"""Print how many tests a CI job skipped, by CLASS and by test module, and its slowest test modules: counts and seconds only, never a reason.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

    python scripts/ci_skip_summary.py JUNIT_XML          # the file pytest wrote with --junitxml

WHY. "What did this job NOT run?" could only be answered by re-running the suite locally (the 2026-10-29 skip audit did exactly that), because the
only reader of a CI job log that works from a session returns the last few kilobytes, and ``pytest -rsfE``'s skip block is hundreds of lines long.
The two full-suite jobs (``test`` and ``core-only``) now write a junit report and run this as the LAST step of the job, on red as well as green: a few
dozen short lines (at most about seventy-five: the lists below are capped) that fit in any tail. It is an OBSERVATION. It never fails a job (exit status 0 whatever it finds), because a count
that changes is a question for a reader, not a verdict (R350: no pins for pytest reds).

WHAT IT PRINTS, AND WHAT IT NEVER DOES. A skip's reason is free text written by a test author, and pytest puts it into the report next to an
absolute path (a skip at COLLECTION time, such as a module-level ``importorskip``, carries ``('/home/runner/.../tests/test_x.py', 2, "Skipped: could not
import 'duckdb': ...")`` as its element text). No free text is ever printed. The output is made of fixed words, integers, and two kinds of name
that must match a strict identifier pattern, and stay under a length bound, before they are used at all. That is a LIMIT on what can get through, not
a promise about every string: anything shaped like an identifier passes (a module named in an ``importorskip`` is printed as the module it names, and
``tests/test_ci_skip_summary.py`` says so in a test of its own), and these names come from the repository's own source, never from the environment:

* the class ``import MODULE``: the module an ``importorskip`` named (``could not import 'duckdb'``), the one reason that has a machine-readable shape;
  every other skip is the class ``other`` (``skip()`` / ``skipif`` with a reason: the full text is in the pytest summary above, in the web log);
* the TEST MODULE a skip belongs to (``tests.test_x``), largest first.

Expected failures (``pytest.xfail``) are not skips: they are counted apart from them, in the first line.

THE SLOWEST MODULES. A second block adds, per test module, the SUM of its testcases' ``time`` attributes in whole seconds, the ten largest and the
rest summed in one line. That is a measurement with a stated meaning, not the job's wall time: pytest writes a testcase's time as setup plus call plus
teardown, a session fixture's SETUP is charged to the first test that asks for it and its TEARDOWN to the last test of the whole run (even one in a
module that never used it), and collection and the imports of a ``conftest.py`` are charged to no test (measured 2026-10-31: a session fixture
with a 0.4 s setup and a 0.2 s teardown, and a 0.5 s conftest import, summed to 1.61 s over two tests in a 2.68 s process). A module that is first to use
a heavy session fixture, or holds the run's last test, therefore carries that fixture's cost. A ``time`` that is not a plain decimal number is counted in
one line ("N test cases carried no readable time") and added to nothing. It is the number the sharding question of the 70 to 80 minute full-suite jobs
(a user item) needs on every run instead of once, and it gates nothing.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

#: A module named by ``pytest.importorskip``: the message is ``could not import 'NAME': ...`` (test level) or the same text inside the element body
#: (collection level, where the message is only ``collection skipped``). Only an identifier of at most 64 characters is taken from it.
_IMPORT = re.compile(r"could not import '([A-Za-z_][A-Za-z0-9_.]{0,63})'")
_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
#: Lines of each list (by class, by test module) kept in the log: the job's tail is read through a window of a few kilobytes. The rest of a list is
#: summed in one line, never dropped silently.
_LIST_LINES = 25
#: The longest name taken from a report. A longer one is not a module of this repository (a line must stay short whatever the report says).
_NAME_MAX = 200
_COLLECTION = "collection skipped"
#: The slowest modules kept in the log; the rest of the modules are summed in one line.
_SLOWEST_LINES = 10
#: A testcase's ``time``: pytest writes plain decimals (``0.123``). Anything else (an exponent, a sign, ``nan``, ``inf``, a digit outside 0-9) is not a time.
_SECONDS = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9})?")


def _test_module(classname: str, name: str) -> str:
    """The test module a testcase belongs to, as a dotted name, or a fixed word when it cannot be told safely."""
    dotted = classname or name  # a collection-time skip has no classname; its name is the module
    if len(dotted) > _NAME_MAX or not _DOTTED.fullmatch(dotted):
        return "(unnamed)"
    parts = dotted.split(".")
    for at, part in enumerate(parts):
        if part.startswith("test_"):
            return ".".join(parts[: at + 1])
    return "(not a test module)"


def _skip_class(message: str, text: str) -> str:
    found = _IMPORT.search(text if message == _COLLECTION else message)
    return f"import {found.group(1)}" if found else "other"


def _list(counts: Counter[str], noun: str) -> list[str]:
    """The ``_LIST_LINES`` largest entries, then one line summing the rest (never a silent cut)."""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = [f"  {name}  {count}" for name, count in ranked[:_LIST_LINES]]
    rest = sum(count for _, count in ranked[_LIST_LINES:])
    if rest:
        lines.append(f"  (and {len(ranked) - _LIST_LINES} more {noun}, {rest} skips)")
    return lines


def _load(path: Path):
    """(the report's root element, None), or (None, the one line that says why it could not be read). Never raises."""
    try:
        from defusedxml import ElementTree as defused
    except ImportError:  # pragma: no cover - defusedxml is a core dependency
        return None, "skip summary: defusedxml is not installed, so the junit report was not read"
    try:
        return defused.parse(str(path)).getroot(), None
    except OSError:
        return None, "skip summary: no junit report was written (pytest did not get as far as writing one)"
    except defused.ParseError:
        return None, "skip summary: the junit report could not be parsed (pytest may have been killed while writing it)"
    except Exception as exc:  # noqa: BLE001 - an observation step must not turn a job red; the class name is the whole message
        return None, f"skip summary: the junit report could not be read ({type(exc).__name__})"


def summarize(path: Path) -> list[str]:
    """The lines to print for one junit report. Never raises: a report that cannot be read becomes one line saying which kind of failure it was."""
    root, why = _load(path)
    if root is None:
        return [why]

    total = skipped = xfailed = 0
    classes: Counter[str] = Counter()
    modules: Counter[str] = Counter()
    for case in root.iter("testcase"):
        total += 1
        marker = case.find("skipped")
        if marker is None:
            continue
        if marker.get("type") == "pytest.xfail":
            xfailed += 1
            continue
        skipped += 1
        classes[_skip_class(marker.get("message") or "", marker.text or "")] += 1
        modules[_test_module(case.get("classname") or "", case.get("name") or "")] += 1

    lines = [f"{total} test cases: {total - skipped - xfailed} ran, {skipped} skipped, {xfailed} expected failures"]
    if skipped:
        lines.append("skipped, by class (counts only; the reasons are in the pytest summary in the job's web log):")
        lines += _list(classes, "classes")
        lines.append(f"skipped, by test module (largest first, {min(len(modules), _LIST_LINES)} of {len(modules)}):")
        lines += _list(modules, "modules")
    return lines


def slowest(path: Path) -> list[str]:
    """The slowest test modules by the sum of their testcases' times, in whole seconds; ``[]`` when the report cannot be read (``summarize`` says so)."""
    root, _ = _load(path)
    if root is None:
        return []
    seconds: dict[str, float] = {}
    unreadable = 0
    for case in root.iter("testcase"):
        raw = case.get("time") or ""
        if not _SECONDS.fullmatch(raw):
            unreadable += 1
            continue
        module = _test_module(case.get("classname") or "", case.get("name") or "")
        seconds[module] = seconds.get(module, 0.0) + float(raw)
    ranked = sorted(seconds.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = [f"per-test times summed (not the job's wall time): {round(sum(seconds.values()))} s in all"]
    if ranked:
        lines.append(f"slowest test modules (largest first, {min(len(ranked), _SLOWEST_LINES)} of {len(ranked)}):")
        lines += [f"  {name}  {round(value)} s" for name, value in ranked[:_SLOWEST_LINES]]
        if len(ranked) > _SLOWEST_LINES:
            lines.append(f"  (and {len(ranked) - _SLOWEST_LINES} more modules, {round(sum(value for _, value in ranked[_SLOWEST_LINES:]))} s)")
    if unreadable:
        lines.append(f"  {unreadable} test cases carried no readable time")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ci_skip_summary.py JUNIT_XML", file=sys.stderr)
        return 2
    print("### Skipped tests (counts only, no gate)")
    print("```")
    print("\n".join(summarize(Path(argv[1]))))
    print("```")
    timing = slowest(Path(argv[1]))
    if timing:
        print("### Slowest test modules (seconds only, no gate)")
        print("```")
        print("\n".join(timing))
        print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
