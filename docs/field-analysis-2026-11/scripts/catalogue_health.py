#!/usr/bin/env python3
"""Per-instance and cross-instance health of every shipped catalogue key.

Input: DERIVED/catalogue-join.jsonl (catalogue_join.py).
Prints aggregate tables (markdown) and writes PRIVATE DERIVED/catalogue-classes.jsonl
(one row per key with per-instance class + cross-instance verdict).

Per-instance class of a catalogue key:
  collected        >=1 stored article (article_count from per_source_summary)
  disqualified     status disqualified (whatever its articles)
  nf:never-checked no article, last_feed_status null (collector never checked its feed)
  nf:no-http       no article, last_feed_status 0 (checked, no HTTP status: network error or refusal)
  nf:http-ok       no article, last_feed_status 200/304 (feed answered, nothing stored)
  nf:http-<code>   no article, other HTTP status
  nf:no-feed       no article, the row has no feed (has_feed false)
  nf:unknown       no article, class columns not exported (Windows build)
  absent           the key is not a source row on that instance
Usage: python3 -I catalogue_health.py DERIVED
"""
import json, os, sys
from collections import Counter, defaultdict

derived = sys.argv[1]
rows = [json.loads(l) for l in open(os.path.join(derived, 'catalogue-join.jsonl'))]
INST = ['Windows', 'Linux A', 'Linux B', 'Linux C']


def klass(x):
    if x is None:
        return 'absent'
    if x.get('status') == 'disqualified':
        return 'disqualified'
    if x.get('has_article') and (x.get('article_count') or 0) > 0:
        return 'collected'
    if x.get('has_feed') is False:
        return 'nf:no-feed'
    lfs = x.get('last_feed_status', 'missing')
    if 'last_feed_status' not in x or x.get('match') == 'domain-only' and lfs is None and x.get('has_feed') is None:
        return 'nf:unknown'
    if lfs is None:
        return 'nf:never-checked'
    if lfs == 0:
        return 'nf:no-http'
    if lfs in (200, 304):
        return 'nf:http-ok'
    return f'nf:http-{lfs}'

per = {i: Counter() for i in INST}
by_file = defaultdict(lambda: {i: Counter() for i in INST})
out = open(os.path.join(derived, 'catalogue-classes.jsonl'), 'w')
cross = Counter()
for r in rows:
    f = r['entries'][0]['file']
    cls = {}
    for i in INST:
        c = klass(r['inst'].get(i))
        cls[i] = c
        per[i][c] += 1
        by_file[f][i][c] += 1
    linux = [cls[i] for i in INST[1:]]
    present = [c for c in cls.values() if c != 'absent']
    n_col = sum(c == 'collected' for c in cls.values())
    if not present:
        v = 'not-a-row-anywhere'
    elif n_col == len(present):
        v = 'collected-everywhere'
    elif n_col > 0:
        v = 'collected-somewhere'
    elif all(c == 'nf:no-feed' for c in present):
        v = 'feedless-never-collected'
    elif all(c in ('nf:no-http',) or c.startswith('nf:http-4') or c.startswith('nf:http-5') for c in linux if c != 'absent') and any(c != 'absent' for c in linux):
        v = 'failing-on-every-linux'
    elif all(c == 'nf:http-ok' for c in linux if c != 'absent') and any(c != 'absent' for c in linux):
        v = 'answers-but-empty-on-every-linux'
    elif all(c == 'nf:never-checked' for c in linux if c != 'absent'):
        v = 'never-checked-on-every-linux'
    else:
        v = 'never-collected-mixed'
    cross[v] += 1
    r2 = {'domain': r['domain'], 'feed_key': r['feed_key'], 'file': f, 'name': r['entries'][0]['name'], 'class': cls, 'verdict': v,
          'article_counts': {i: (r['inst'][i] or {}).get('article_count') for i in INST},
          'feed_status': {i: (r['inst'][i] or {}).get('last_feed_status') for i in INST}}
    out.write(json.dumps(r2, ensure_ascii=False) + '\n')
out.close()

classes = sorted({c for i in INST for c in per[i]})
print('| class | ' + ' | '.join(INST) + ' |')
print('|---|' + '---:|' * len(INST))
for c in classes:
    print(f'| {c} | ' + ' | '.join(str(per[i][c]) for i in INST) + ' |')
print(f'| total keys | ' + ' | '.join(str(sum(per[i].values())) for i in INST) + ' |')
print()
print('| cross-instance verdict | keys |')
print('|---|---:|')
for v, n in cross.most_common():
    print(f'| {v} | {n} |')
print()
for f, d in by_file.items():
    print(f'{f}: ' + '; '.join(f"{i}: col {d[i]["collected"]}/{sum(d[i].values())}" for i in INST))
