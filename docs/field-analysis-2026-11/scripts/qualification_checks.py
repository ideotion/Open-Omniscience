#!/usr/bin/env python3
"""Source-qualification checks across instances.
1. Agreement between instances on the measured verdicts in source-qualification.json.
2. For catalogue domains disqualified on BOTH of two instances: which extraction-failure
   criterion fired, by elimination. Only pathology_rate and link_density_rate can disqualify
   (src/analytics/source_audit.py:109-144, derive_status :643-660). pathology articles are
   counted from keyword_outliers.jsonl (pathology_furniture_repetition); a source with fewer
   than 5 cannot have been flagged on pathology (_MIN_PATHOLOGY_ARTICLES, :104), so the
   flag must be link_density_rate. Caveat: today's corpus, not the corpus at verdict time.
3. Link density (external_link_count / word_count) of the random_per_source article of those
   sources vs qualified sources (sample_articles.jsonl, same instance).
Usage: python3 -I qualification_checks.py DATA_ROOT INSTANCES_JSON LABEL_X LABEL_Y"""
import glob, json, sys
root, inst, lx, ly = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
folder = {v: k for k, v in inst.items()}
V = {}
for lab in inst.values():
    d = json.load(open(glob.glob(f'{root}/{folder[lab]}/*-source-qualification.json')[0]))
    V[lab] = {v['domain']: v['status'] for v in d['verdicts'] if v['basis'] == 'measured'}
    print(lab, 'measured verdicts', len(V[lab]), 'disqualified', sum(s == 'disqualified' for s in V[lab].values()))
common = set(V[lx]) & set(V[ly])
agree = sum(V[lx][d] == V[ly][d] for d in common)
both = {d for d in common if V[lx][d] == V[ly][d] == 'disqualified'}
print(f'{lx} vs {ly}: judged by both {len(common)}, same verdict {agree}, disqualified by both {len(both)}')
for lab in (lx, ly):
    sq = glob.glob(f'{root}/{folder[lab]}/*-source-quality')[0]
    summ = {}
    for l in open(sq + '/per_source_summary.jsonl'):
        d = json.loads(l); summ[d['source_id']] = d
    sids = {s for s, d in summ.items() if d['domain'] in both and d['qualification_status'] == 'disqualified'}
    path = {}
    for l in open(sq + '/keyword_outliers.jsonl'):
        r = json.loads(l)
        if r['source_id'] in sids and r['pathology_furniture_repetition']:
            path[r['source_id']] = path.get(r['source_id'], 0) + 1
    ge5 = sum(1 for s in sids if path.get(s, 0) >= 5)
    dq, ok = [], []
    for l in open(sq + '/sample_articles.jsonl'):
        r = json.loads(l)
        if 'random_per_source' not in r['selection_method'] or not r['word_count']:
            continue
        d = summ.get(r['source_id'])
        if not d or not d.get('ratio_audited'):
            continue
        ld = r['external_link_count'] / r['word_count']
        (dq if r['source_id'] in sids else ok if d['qualification_status'] == 'qualified' else []).append(ld)
    def pct(a, p):
        a = sorted(a); return round(a[int(p * (len(a) - 1))], 3) if a else None
    print(f'{lab}: disqualified-by-both rows {len(sids)}; >=5 pathological articles {ge5}; so link_density_rate on {len(sids) - ge5}')
    for name, a in (('disqualified-by-both', dq), ('qualified', ok)):
        print(f'   random article link density, {name}: n={len(a)} median={pct(a, .5)} p75={pct(a, .75)} share>=0.05={sum(x >= 0.05 for x in a) / max(1, len(a)):.2f}')
