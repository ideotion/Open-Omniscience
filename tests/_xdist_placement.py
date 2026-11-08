"""A pytest-xdist scheduler that puts every test FILE on a worker chosen in advance, and runs each worker's files in collection order.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY NOT xdist's OWN ``--dist loadfile``. It keeps a file whole on one worker, but it hands the next file to whichever worker is free first, so
which files share a process, and in what order, changes from run to run with the runner's timing. This suite has tests that read state an
earlier test in the same process left behind (a lane file in the shared data directory, a download registry kept alive, a keyword row written
by a thread): one process in a fixed order hides them the same way every run, and a timing-driven order shows a DIFFERENT few each run. Two full
runs on 2026-11-08 at the same commit failed on three tests and on four other tests. A required check that goes red on a coin is worse than a
slow one, so the placement here depends on nothing that moves between runs:

* the files collected are dealt longest first, each to the worker with the least work so far (LPT), on the measured seconds of
  ``configs/ci_shard_costs.json`` (``scripts/ci_shard.py``'s own table and dealing). A file the table does not name counts as the table's median
  file, so a new file needs no edit here. Ties go to the lower worker, and the order the files arrive in does not matter;
* each worker runs its files in the order pytest collected them, which is the order one process would have run them in, minus the other files.

Same files, same number of workers -> same placement, same order, every run. What can still differ from a one-process run is which files share
a process, so a hidden dependency can show here once; it then shows on every run until it is fixed, which is the point.

Same files means per COMMIT: a PR that adds a test file, or a refresh of the cost table, re-deals the files, so an order dependency in files
the PR never touched can surface there; it is then the same on every run of that commit.

It replaces the scheduler only for ``--dist loadfile`` and only where ``tests/conftest.py`` installs it (the suite's own runs); it prints one
line saying so at the start of the run, so nobody reads the log believing xdist's dynamic loadfile ran. A worker that crashes is reported
and replaced; the replacement gets the crashed worker's remaining tests (none if the crash was its last), as xdist's ``each`` scheduler does.
Every worker is handed its whole share up front, so ``--maxfail=N`` stops the controller's count but not the other workers' queues.
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Sequence
from pathlib import Path

import pytest

try:
    from xdist.report import report_collection_diff
    from xdist.scheduler.each import EachScheduling
except ImportError:  # no pytest-xdist: ``place`` still imports (its test runs); the scheduler is only ever built by xdist itself
    EachScheduling = object  # type: ignore[assignment,misc]

_ROOT = Path(__file__).resolve().parents[1]
_COSTS = _ROOT / "configs" / "ci_shard_costs.json"


def _file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def place(files: Sequence[str], workers: int, costs: dict[str, float]) -> dict[str, int]:
    """``{file: worker}`` (workers from 0): longest first to the least-loaded worker, ties to the lower one; an unlisted file costs the median."""
    default = statistics.median(costs.values()) if costs else 1.0
    weight = {f: float(costs.get(f, default)) for f in set(files)}
    loads = [0.0] * workers
    out: dict[str, int] = {}
    for f in sorted(weight, key=lambda p: (-weight[p], p)):
        at = min(range(workers), key=lambda k: (loads[k], k))
        out[f] = at
        loads[at] += weight[f]
    return out


def _load_costs() -> dict[str, float]:
    try:
        return {str(k): float(v) for k, v in json.loads(_COSTS.read_text(encoding="utf-8"))["costs"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}  # no table: every file weighs the same, still deterministic


def _rank(node) -> tuple[int, str]:
    """gw0, gw1, ... in number order; a worker named some other way (``--tx ...//id=name``) after them, by name."""
    name = str(node.gateway.id)
    m = re.fullmatch(r"gw(\d+)", name)
    return (int(m.group(1)), "") if m else (1 << 30, name)


class FilePlacementScheduling(EachScheduling):
    """``each``'s bookkeeping (every worker collects everything), but each worker is sent only the tests of its own files.

    Before placing anything it checks that every worker collected the same tests, as xdist's own ``loadfile`` does: a file missing from one
    worker's collection would otherwise run nowhere and the run would stay green. A mismatch is reported as a collection error and no test runs.
    """

    _placed = False

    def add_node_collection(self, node, collection: Sequence[str]) -> None:
        completed = self.collection_is_completed
        super().add_node_collection(node, collection)
        if completed:  # a replacement for a crashed worker: keep its collection, so a second crash on it is reported like the first
            self.node2collection.setdefault(node, list(collection))

    def _same_collections(self) -> bool:
        (first, col), *rest = sorted(self.node2collection.items(), key=lambda kv: _rank(kv[0]))
        same = True
        for node, other in rest:
            msg = report_collection_diff(col, other, first.gateway.id, node.gateway.id)
            if msg:
                same = False
                self.log(msg)
                self.config.hook.pytest_collectreport(report=pytest.CollectReport(nodeid=node.gateway.id, outcome="failed", longrepr=msg, result=[]))
        return same

    def _start(self, node, indices: list[int]) -> None:
        if indices:
            self.node2pending[node][:] = indices
            node.send_runtest_some(indices)
        node.shutdown()
        self._started.append(node)

    def schedule(self) -> None:
        assert self.collection_is_completed
        nodes = sorted(self.node2pending, key=_rank)
        if not self._placed:
            self._placed = True
            if not self._same_collections():
                self.log("**Different tests collected, aborting run**")
                for node in nodes:
                    self._start(node, [])
                return
            where = place([_file_of(i) for i in self.node2collection[nodes[0]]], len(nodes), _load_costs())
            for rank, node in enumerate(nodes):
                self._start(node, [i for i, nodeid in enumerate(self.node2collection[node]) if where[_file_of(nodeid)] == rank])
            return
        for node in nodes:  # later calls: a replacement for a crashed worker gets that worker's remaining tests, or nothing
            if node not in self._started:
                self._start(node, list(self.node2pending[node]))

    @property
    def tests_finished(self) -> bool:
        if not self.collection_is_completed or self._removed2pending:
            return False
        return all(not pending for pending in self.node2pending.values())
