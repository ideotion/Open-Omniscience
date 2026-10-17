#!/usr/bin/env python3
"""Scratch probe: what ``osmium.filter.IdFilter`` costs, measured as resident memory.

usage: idfilter_probe.py N SPAN [--set]

Builds an ``IdFilter`` from N ascending ids spread evenly over SPAN (a list of ids, an ``array('q')``, or with --set a Python
``set`` as ``ways_by_id``/``nodes_by_id`` pass), then deletes it and reads memory again. ``IdFilter`` is backed by libosmium's
``IdSet`` (the structure ``idset_probe.py`` measured): 4 MiB for every 2**25-id window an id falls in, so its cost follows the
SPAN of the ids, not their count. The history phase hands it every tracked node id, and the border pass hands it a border's
way and node ids; both are therefore a flat cost per id RANGE, which the ingest pays once and then frees.
"""
import sys
from array import array

import osmium


def rss_mb() -> float:
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS"):
            return int(line.split()[1]) / 1024
    return float("nan")


n, span = int(sys.argv[1]), int(sys.argv[2])
step = max(1, span // n)
ids = array("q", (i * step + 1 for i in range(n)))
src = set(ids) if "--set" in sys.argv else ids
base = rss_mb()
f = osmium.filter.IdFilter(src)
held = rss_mb()
del f
freed = rss_mb()
print(f"N={n} span={span} source={'set' if '--set' in sys.argv else 'array'} "
      f"filter_MB={held - base:.0f} after_delete_MB={freed - base:.0f} bytes_per_id={(held - base) * 1048576 / n:.1f}")
