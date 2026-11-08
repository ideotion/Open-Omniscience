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

It replaces the scheduler only for ``--dist loadfile`` and only where ``tests/conftest.py`` installs it (the suite's own runs); it prints one
line saying so at the start of the run, so nobody reads the log believing xdist's dynamic loadfile ran. A worker that crashes is replaced and
the replacement gets the crashed worker's remaining tests, as xdist's ``each`` scheduler does.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from pathlib import Path

from xdist.scheduler.each import EachScheduling

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


class FilePlacementScheduling(EachScheduling):
    """``each``'s bookkeeping (every worker collects everything), but each worker is sent only the tests of its own files."""

    def schedule(self) -> None:
        assert self.collection_is_completed
        nodes = sorted(self.node2pending, key=lambda n: int(str(n.gateway.id).lstrip("gw") or 0))
        fresh = [n for n in nodes if n not in self._started and not self.node2pending[n]]
        if fresh:
            collection = self.node2collection[fresh[0]]
            where = place([_file_of(i) for i in collection], len(nodes), _load_costs())
            for rank, node in enumerate(nodes):
                if node not in fresh:
                    continue
                mine = [i for i, nodeid in enumerate(self.node2collection[node]) if where[_file_of(nodeid)] == rank]
                if not mine:
                    node.shutdown()
                    self._started.append(node)
                    continue
                self.node2pending[node][:] = mine
                node.send_runtest_some(mine)
                node.shutdown()
                self._started.append(node)
        for node, pending in self.node2pending.items():  # a replacement for a crashed worker: it was handed that worker's remaining tests
            if node not in self._started and pending:
                node.send_runtest_some(pending)
                node.shutdown()
                self._started.append(node)

    @property
    def tests_finished(self) -> bool:
        if not self.collection_is_completed or self._removed2pending:
            return False
        return all(not pending for pending in self.node2pending.values())
