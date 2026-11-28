#!/usr/bin/env python3
"""Aggregate the 2026-09-11 Stage A candidate-verification kit results (summary.json per
shard, worklists w3 = institutions first pass, w5 = retry pass).
Usage: python3 -I stage_a.py STAGE_A_DIR [STAGE_A_SECOND_DIR]"""
import glob, json, sys
from collections import Counter
for root in sys.argv[1:]:
    for w in ('w3', 'w5'):
        fs = glob.glob(f'{root}/*/*/runs/{w}/summary.json')
        if not fs:
            continue
        t = Counter(); c = v = 0
        for f in fs:
            s = json.load(open(f)); c += s['candidates']; v += s['verified']; t.update(s['by_reason'])
        print(f'{w}: shards {len(fs)} judged {c} verified {v} ({100*v/c:.1f}%)')
        for k, n in t.most_common():
            print(f'   {k}: {n} ({100*n/c:.1f}%)')
