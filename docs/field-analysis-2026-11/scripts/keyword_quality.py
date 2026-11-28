#!/usr/bin/env python3
"""Keyword quality per source from per_source_keywords.jsonl + per_source_summary.jsonl.

A top-12 term whose article share (term.articles / articles the top-12 was computed over)
is >= 0.5 is called 'template-like' here: the same structural rule the app's read-time
outlet_furniture uses (MIN_SHARE = 0.5, src/analytics/outlet_furniture.py). That is a
structural fact, not a verdict: a single-topic outlet's topic word also passes.
Denominator per source = min(article_count, 800) because fingerprint_sampled sources are
computed over a seeded 800-article sample (source_quality.py, per the field dictionary).
Only sources with >=20 articles and a non-empty top-12 are counted.
Prints per-instance aggregates and the most frequent template-like terms (catalogue-wide
words only; the per-source lists stay private).
Usage: python3 -I keyword_quality.py DATA_ROOT INSTANCES_JSON
"""
import glob, json, sys
from collections import Counter

root, inst = sys.argv[1], json.load(open(sys.argv[2]))
order = ['Windows', 'Linux A', 'Linux B', 'Linux C']
res = {}
for folder, label in inst.items():
    sq = sorted(glob.glob(f'{root}/{folder}/*-source-quality'))[0]
    ac = {}
    for l in open(sq + '/per_source_summary.jsonl'):
        d = json.loads(l); ac[d['source_id']] = (d['article_count'], d.get('ratio_audited'))
    n = n_t = 0; shares = []; terms = Counter(); nterm = []
    for l in open(sq + '/per_source_keywords.jsonl'):
        d = json.loads(l)
        cnt, aud = ac.get(d['source_id'], (0, False))
        top = d.get('top_keywords') or []
        if cnt < 20 or not top or not aud:
            continue
        den = min(cnt, 800)
        tl = [t['normalized'] or t['term'] for t in top if t['articles'] / den >= 0.5]
        n += 1; n_t += bool(tl); nterm.append(len(tl))
        terms.update(set(tl))
    res[label] = (n, n_t, nterm, terms)
print('| instance | sources (>=20 articles, audited) | with >=1 template-like top-12 term | mean template-like terms per source |')
print('|---|---:|---:|---:|')
for o in order:
    n, n_t, nt, _ = res[o]
    print(f'| {o} | {n} | {n_t} ({100*n_t/n:.1f}%) | {sum(nt)/n:.2f} |')
allt = Counter()
for o in order:
    allt.update(res[o][3])
print('\nmost frequent template-like terms (number of source rows, summed over instances):')
print(', '.join(f'{t} ({c})' for t, c in allt.most_common(60)))
