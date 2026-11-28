#!/usr/bin/env python3
"""Collection-pass ingest funnel from debug-bundle.json scheduler.recent_runs (<=30 newest
passes per bundle, data/scheduler_runs.jsonl via src/scheduler/runlog.py).

Per pass: duration_s, sources_processed, deferred_next_pass, recycled, and result.tally
(integer totals per pass, src/scheduler/runner.py; outcome names = IngestResult in
src/ingest/pipeline.py). Feed entries are per feed item; the outcome counters are per
item (article page) except not_modified / skipped_offline (per feed).
Passes are de-duplicated on started_at across bundles of the same instance.
Usage: python3 -I ingest_runs.py DATA_ROOT INSTANCES_JSON [EXTRA_ROOT EXTRA_JSON]
"""
import glob, json, sys
from collections import Counter, defaultdict

args = sys.argv[1:]
pairs = [(args[i], json.load(open(args[i + 1]))) for i in range(0, len(args), 2)]
per = defaultdict(dict)
for root, inst in pairs:
    for folder, label in inst.items():
        base = label.split(' @')[0]
        for f in glob.glob(f'{root}/{folder}/*/debug-bundle.json'):
            try:
                runs = json.load(open(f))['data']['scheduler']['recent_runs']
            except Exception:
                continue
            for r in runs:
                if r.get('lane') == 'press' and isinstance(r.get('result'), dict):
                    per[base][r['started_at']] = r
order = ['Windows', 'Linux A', 'Linux B', 'Linux C'] + sorted(k for k in per if k.startswith('H'))
KEYS = ['entries', 'stored', 'duplicate', 'fetch_failed', 'extract_failed', 'non_article', 'blocked_robots',
        'robots_unavailable', 'crawl_delay_deferred', 'not_modified', 'staged']
rows = []
for inst in order:
    runs = list(per.get(inst, {}).values())
    if not runs:
        continue
    t = Counter(); dur = []; sp = 0; dnp = []; st = 0; rec = Counter(); ff = Counter()
    first = min(r['started_at'] for r in runs); last = max(r['started_at'] for r in runs)
    for r in runs:
        res = r['result']
        for k, v in (res.get('tally') or {}).items():
            if isinstance(v, int):
                (ff if k.startswith('ff:') else t)[k] += v
        dur.append(res.get('duration_s') or 0); sp += res.get('sources_processed') or 0
        dnp.append(res.get('deferred_next_pass') or 0); st += res.get('articles_stored') or 0
        rec[str(res.get('recycled'))] += 1
    items = sum(t[k] for k in ('stored', 'duplicate', 'fetch_failed', 'extract_failed', 'non_article', 'blocked_robots', 'robots_unavailable', 'crawl_delay_deferred', 'staged'))
    dur.sort()
    rows.append((inst, len(runs), first[:10], last[:10], dur[len(dur) // 2] / 3600, sp, st, sum(dnp) / len(dnp), t, ff, items, rec))

print('| instance | passes | first..last start | median pass h | sources processed | articles_stored | mean deferred_next_pass | stored per hour |')
print('|---|---:|---|---:|---:|---:|---:|---:|')
for inst, n, a, b, med, sp, st, dnp, t, ff, items, rec in rows:
    hours = sum((r['result'].get('duration_s') or 0) for r in per[inst].values()) / 3600
    print(f'| {inst} | {n} | {a}..{b} | {med:.2f} | {sp} | {st} | {dnp:.0f} | {st / hours:.0f} |')
print('\nPer-item outcomes (sum over the passes; % of item outcomes):')
print('| instance | items | stored | duplicate | fetch_failed | extract_failed | non_article | blocked_robots | robots_unavailable | crawl_delay_deferred |')
print('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
for inst, n, a, b, med, sp, st, dnp, t, ff, items, rec in rows:
    def c(k):
        return f'{t[k]} ({100 * t[k] / items:.1f}%)' if items else '0'
    print(f'| {inst} | {items} | {c("stored")} | {c("duplicate")} | {c("fetch_failed")} | {c("extract_failed")} | {c("non_article")} | {c("blocked_robots")} | {c("robots_unavailable")} | {c("crawl_delay_deferred")} |')
print('\nfetch_failed by class (ff:*, % of fetch_failed):')
allff = sorted({k for r in rows for k in r[9]})
print('| instance | ' + ' | '.join(allff) + ' |')
print('|---|' + '---:|' * len(allff))
for inst, n, a, b, med, sp, st, dnp, t, ff, items, rec in rows:
    tot = sum(ff.values()) or 1
    print(f'| {inst} | ' + ' | '.join(f'{ff[k]} ({100 * ff[k] / tot:.0f}%)' for k in allff) + ' |')
print('\nother per-feed counters and pass end reasons:')
for inst, n, a, b, med, sp, st, dnp, t, ff, items, rec in rows:
    other = {k: v for k, v in t.items() if k not in KEYS}
    print(f'- {inst}: not_modified {t["not_modified"]}; entries {t["entries"]}; other {other}; recycled {dict(rec)}')
