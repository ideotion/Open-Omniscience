#!/usr/bin/env python3
"""Scratch probe: what libosmium's in-memory location index (``sparse_mem_array``) costs per stored node, as resident memory.

usage: location_probe.py N [--sample-every K]

Stores N ascending node ids with locations (what the scan hands it) and prints resident memory as it grows, then the figure per
location at the end. The index is a vector of 16-byte entries, so it grows by doubling its capacity: right after a doubling the
process briefly holds the old and the new buffer, which the PEAK column shows against the settled figure.
"""
import resource
import sys

import osmium.index
from osmium.osm import Location


def rss_mb() -> float:
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS"):
            return int(line.split()[1]) / 1024
    return float("nan")


n = int(sys.argv[1])
every = n // 8
m = osmium.index.create_map("sparse_mem_array")
base = rss_mb()
loc = Location(5.1, 52.1)
rows = []
for i in range(1, n + 1):
    m.set(i * 600, loc)
    if i % every == 0:
        rows.append((i, rss_mb() - base))
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 - base
for i, mb in rows:
    print(f"{i:>11,} stored  {mb:8.0f} MB  {mb * 1048576 / i:5.1f} B each")
print(f"peak over the run {peak:.0f} MB = {peak * 1048576 / n:.1f} B per final location (a doubling holds old and new buffer at once)")
