#!/usr/bin/env python3
"""Draw a seeded random sample of N source-sample articles per instance for MANUAL labelling and
print a compact view (id, words, title, head, tail). Output is private (article text).
Usage: python3 -I label_sample.py DATA_ROOT INSTANCES_JSON N SEED"""
import glob, json, random, sys
root, inst, n, seed = sys.argv[1], json.load(open(sys.argv[2])), int(sys.argv[3]), int(sys.argv[4])
for folder, label in inst.items():
    fs = sorted(glob.glob(f'{root}/{folder}/*source-samples-*/samples/*.json'))
    for i, f in enumerate(random.Random(f'{seed}:{label}').sample(fs, n)):
        s = json.load(open(f)); a = s.get('article') or {}; t = ' '.join((a.get('content') or '').split())
        print(f"[{label[-1]}{i:02d}] wc={a.get('word_count')} lang={a.get('language')}/{s['source'].get('language')} type={s['source'].get('source_type')} q={a.get('quarantined')} T={(a.get('title') or '')[:70]!r}")
        print(f"   H: {t[:170]}")
        print(f"   E: {t[-120:]}")
