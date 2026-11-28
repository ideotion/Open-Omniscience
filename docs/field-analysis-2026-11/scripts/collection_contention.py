#!/usr/bin/env python3
"""Collection bottleneck evidence: collect_perf_windows decisions and writer/cpu saturation
shares (debug-bundle.json; src/scheduler/bandwidth.py window_history) and the write gate's
per-holder totals (contention.json sections.write-gate; cumulative since that app start).
Usage: python3 -I collection_contention.py DATA_ROOT INSTANCES_JSON"""
import glob, json, sys
from collections import Counter
root, inst = sys.argv[1], json.load(open(sys.argv[2]))
for folder, label in inst.items():
    dec = Counter(); ws = []; cs = []
    for f in glob.glob(f'{root}/{folder}/*/debug-bundle.json'):
        for w in json.load(open(f))['data'].get('collect_perf_windows', {}).get('windows', []):
            dec[w.get('decision')] += 1; ws.append(w.get('writer_saturated_share') or 0); cs.append(w.get('cpu_saturated_share') or 0)
    print(f'{label}: windows {dict(dec)} writer_saturated mean {sum(ws)/max(1,len(ws)):.2f} cpu_saturated mean {sum(cs)/max(1,len(cs)):.2f}')
    for f in sorted(glob.glob(f'{root}/{folder}/*/contention.json'))[-1:]:
        g = json.load(open(f))['sections']['write-gate']['gate']
        print(f'   gate: grants {g["grants"]} contended {g["contended"]} total_wait_s {g["total_wait_s"]:.0f} max_wait_s {g["max_wait_s"]:.0f} '
              f'total_held_s {g["total_held_s"]:.0f} hold_cpu_s {g.get("total_hold_cpu_s", 0):.0f} max_hold_s {g["max_hold_s"]:.0f}')
        coll = [h for h in g['by_holder'] if h['holder'].startswith('oo-collect')]
        other = sorted([h for h in g['by_holder'] if not h['holder'].startswith('oo-collect')], key=lambda h: -h['held_s'])[:3]
        ch = sum(h['holds'] for h in coll); cs_ = sum(h['held_s'] for h in coll)
        print(f'   collector threads: holds {ch} held_s {cs_:.0f} mean hold {cs_/max(1,ch):.1f}s; top other holders: ' +
              ', '.join(f'{h["holder"]} {h["held_s"]:.0f}s/{h["holds"]}' for h in other))
