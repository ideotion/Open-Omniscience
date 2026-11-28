#!/usr/bin/env python3
"""Cross-snapshot evidence per shipped catalogue key: in how many snapshots (instance x date)
the key is a source row, how many of them stored >=1 article, the article counts, and the
current Linux feed-status classes (catalogue_health.py).

Inputs: CATALOGUE.json (catalogue_index.py), one or more DERIVED dirs (build_sources.py),
        DERIVED/catalogue-classes.jsonl (catalogue_health.py, current snapshots).
Writes PRIVATE OUT.jsonl, prints aggregate tables.
Usage: python3 -I catalogue_evidence.py CATALOGUE.json CLASSES.jsonl OUT.jsonl DERIVED [DERIVED...]
"""
import glob, json, os, sys
from collections import Counter, defaultdict

cat_path, classes_path, out_path, *dirs = sys.argv[1:]
cat = json.load(open(cat_path))
keys = {}
for r in cat:
    keys.setdefault((r['domain'], r['feed_key']), r)
snap = {}
for d in dirs:
    for f in sorted(glob.glob(os.path.join(d, 'sources-*.jsonl'))):
        label = os.path.basename(f)[8:-6].replace('_', ' ')
        idx = {}
        for line in open(f):
            x = json.loads(line)
            idx[((x.get('domain') or '').lower(), x.get('feed_key'))] = x
        snap[label] = idx
classes = {(r['domain'], r['feed_key']): r for r in (json.loads(l) for l in open(classes_path))}

def ac(x):
    s = x.get('summary') or {}
    if 'article_count' in s:
        return s['article_count'] or 0
    return x.get('articles_in_source') or 0 if x.get('has_article') else 0

out = open(out_path, 'w')
dist = Counter(); tab = Counter()
for k, e in keys.items():
    per = {}
    for label, idx in snap.items():
        x = idx.get(k)
        if x is not None:
            per[label] = ac(x)
    n_rows = len(per); n_col = sum(1 for v in per.values() if v > 0)
    c = classes.get(k, {})
    lin = [c.get('class', {}).get(i) for i in ('Linux A', 'Linux B', 'Linux C')]
    rec = {'domain': k[0], 'feed_key': k[1], 'file': e['file'], 'name': e['name'], 'source_type': e['source_type'],
           'country': e['country'], 'language': e['language'], 'snap_rows': n_rows, 'snap_collected': n_col,
           'max_articles': max(per.values()) if per else None, 'linux_classes': lin, 'verdict': c.get('verdict')}
    out.write(json.dumps(rec, ensure_ascii=False) + '\n')
    if n_col == 0 and n_rows:
        tab[('never-stored-anywhere', tuple(sorted(set(x for x in lin if x))))] += 1
    dist[(n_col, n_rows)] += 1
out.close()
print('snapshots:', len(snap), sorted(snap))
print('\n| keys that are rows in N snapshots and stored >=1 article in M | count |')
for (m, n), v in sorted(dist.items(), key=lambda t: (-t[0][1], -t[0][0])):
    print(f'| rows {n}, collected {m} | {v} |')
print('\n| never stored in any snapshot: current Linux A/B/C classes | keys |')
for (t, cls), v in tab.most_common():
    print(f'| {", ".join(cls)} | {v} |')
