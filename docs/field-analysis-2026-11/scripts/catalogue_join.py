#!/usr/bin/env python3
"""Join the shipped catalogue (catalogue_index.py output) with each instance's
per-source table (build_sources.py output) on (domain, feed_key).

Writes PRIVATE OUT_DIR/catalogue-join.jsonl: one row per unique catalogue key with
per-instance facts. Prints aggregate match statistics.
Usage: python3 -I catalogue_join.py CATALOGUE.json DERIVED_DIR
"""
import glob, json, os, sys
from collections import Counter, defaultdict

cat_path, derived = sys.argv[1:3]
cat = json.load(open(cat_path))
by_key = defaultdict(list)
for r in cat:
    by_key[(r['domain'], r['feed_key'])].append(r)

inst = {}
for f in sorted(glob.glob(os.path.join(derived, 'sources-*.jsonl'))):
    label = os.path.basename(f)[8:-6].replace('_', ' ')
    idx = {}
    dom_only = defaultdict(list)
    for line in open(f):
        r = json.loads(line)
        k = ((r.get('domain') or '').lower(), r.get('feed_key'))
        idx[k] = r
        dom_only[k[0]].append(r)
    inst[label] = (idx, dom_only)

out = open(os.path.join(derived, 'catalogue-join.jsonl'), 'w')
stats = {l: Counter() for l in inst}
for key, entries in by_key.items():
    row = {'domain': key[0], 'feed_key': key[1], 'entries': [{k: e[k] for k in ('file', 'index', 'name', 'rss_url', 'source_type', 'country', 'language', 'enabled')} for e in entries], 'inst': {}}
    for label, (idx, dom_only) in inst.items():
        r = idx.get(key)
        how = 'exact'
        if r is None and label == 'Windows':
            # Windows' never-collected rows carry no feed_key: fall back to a unique domain row
            cands = [x for x in dom_only.get(key[0], []) if x.get('feed_key') in (None, key[1])]
            if len(cands) == 1:
                r, how = cands[0], 'domain-only'
        if r is None:
            stats[label]['absent'] += 1
            row['inst'][label] = None
            continue
        s = r.get('summary') or {}
        stats[label]['matched_' + how] += 1
        row['inst'][label] = {
            'match': how, 'source_id': r['source_id'], 'has_article': r.get('has_article'),
            'article_count': s.get('article_count', r.get('articles_in_source') or 0),
            'status': r.get('status') or s.get('qualification_status'), 'enabled': r.get('enabled'),
            'via': r.get('via'), 'has_feed': r.get('has_feed'), 'last_feed_status': r.get('last_feed_status'),
            'last_qualification': r.get('last_qualification'),
            'outlier_rate': s.get('outlier_rate'), 'listing_url_rate': s.get('listing_url_rate'),
            'sample': r.get('sample'), 'furniture_share': (r.get('keywords') or {}).get('furniture_share'),
        }
    out.write(json.dumps(row, ensure_ascii=False) + '\n')
out.close()
print('catalogue keys', len(by_key))
for l, c in stats.items():
    print(l, dict(c))
