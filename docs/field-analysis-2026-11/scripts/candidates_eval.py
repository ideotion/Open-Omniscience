#!/usr/bin/env python3
"""Evaluate the instance-qualified candidate sources (candidates.json: qualified by the
instance's OWN measurement, not in any shipped catalogue) across instances.

Per domain: instances that qualified it, articles_stored (quarantined included, per the
exporter), newest publisher date (evidence.last_article = max published_at), and, from the
per-source tables (build_sources.py + article_quality.py flags), the random sample article's
word count and stub flags, and whether ANY instance holds the domain disqualified.
Rule used for 'catalogue candidate' (stated, tunable):
  qualified on >=3 of 4 instances; median articles_stored >= 20;
  newest article within 30 days of that export on >=2 instances;
  every sampled article has >=100 words and no stub/consent/js/error phrase;
  disqualified on no instance.
Writes PRIVATE OUT.json (full rows) and prints aggregate counts. The PUBLIC table is the
list of passing domains with their aggregate evidence only.
Usage: python3 -I candidates_eval.py DATA_ROOT INSTANCES_JSON DERIVED OUT.json
"""
import glob, json, os, statistics, sys
from collections import Counter, defaultdict
from datetime import datetime

root, inst_path, derived, out = sys.argv[1:5]
inst = json.load(open(inst_path))
cands = defaultdict(dict); gen = {}
for folder, label in inst.items():
    d = json.load(open(glob.glob(f'{root}/{folder}/*-candidate-sources/candidates.json')[0]))
    gen[label] = datetime.fromisoformat(d['generated_at'].replace('Z', '+00:00')).replace(tzinfo=None)
    for c in d['candidates']:
        cands[c['domain']][label] = c
src = {}; flags = {}
for label in inst.values():
    k = label.replace(' ', '_')
    rows = {}
    for l in open(os.path.join(derived, f'sources-{k}.jsonl')):
        r = json.loads(l); rows.setdefault((r.get('domain') or '').lower(), []).append(r)
    src[label] = rows
    fl = {}
    for l in open(os.path.join(derived, f'article-flags-{k}.jsonl')):
        r = json.loads(l); fl[r['meta']['source_id']] = r['flags']
    flags[label] = fl


def age_days(label, ts):
    if not ts:
        return None
    t = datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
    return (gen[label] - t).days

res = []; stale = Counter(); total = Counter()
for dom, per in cands.items():
    n = len(per)
    stored = [c['evidence'].get('articles_stored') or 0 for c in per.values()]
    ages = {l: age_days(l, c['evidence'].get('last_article')) for l, c in per.items()}
    for l, a in ages.items():
        total[l] += 1
        if a is None or a > 365:
            stale[l] += 1
    disq = [l for l in inst.values() if any(r.get('status') == 'disqualified' for r in src[l].get(dom, []))]
    bad_sample = []
    for l in per:
        for r in src[l].get(dom, []):
            f = flags[l].get(r['source_id'])
            if f and (f['words_lt_100'] or any(f[k] for k in ('stub_paywall', 'stub_consent', 'stub_js_wall', 'stub_error_page', 'stub_login'))):
                bad_sample.append(l)
    fresh = sum(1 for a in ages.values() if a is not None and a <= 30)
    ok = n >= 3 and statistics.median(stored) >= 20 and fresh >= 2 and not bad_sample and not disq
    any_c = next(iter(per.values()))
    res.append({'domain': dom, 'name': any_c.get('name'), 'feed': any_c.get('feed'), 'country': any_c.get('country'),
                'language': any_c.get('language'), 'source_type': any_c.get('source_type'), 'tags': any_c.get('tags'),
                'n_instances': n, 'median_stored': statistics.median(stored), 'fresh_instances': fresh,
                'min_age_days': min((a for a in ages.values() if a is not None), default=None),
                'bad_sample_on': sorted(set(bad_sample)), 'disqualified_on': disq, 'passes': ok})
json.dump(res, open(out, 'w'), ensure_ascii=False, indent=0)
print('candidate domains', len(res), 'by #instances', sorted(Counter(r['n_instances'] for r in res).items()))
print('candidates whose newest stored article is >365 d old or undated, per instance:', {l: f'{stale[l]}/{total[l]}' for l in total})
for k in (2, 3, 4):
    sub = [r for r in res if r['n_instances'] >= k]
    print(f'>={k} instances: {len(sub)}; median_stored>=20: {sum(r["median_stored"]>=20 for r in sub)}; fresh>=2: {sum(r["fresh_instances"]>=2 for r in sub)}; '
          f'bad sample somewhere: {sum(bool(r["bad_sample_on"]) for r in sub)}; disqualified somewhere: {sum(bool(r["disqualified_on"]) for r in sub)}')
print('PASSING:', sum(r['passes'] for r in res))
print('passing by source_type:', Counter(r['source_type'] for r in res if r['passes']).most_common())
