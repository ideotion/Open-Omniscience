#!/usr/bin/env python3
"""Build one per-source table per instance from the field exports.

Joins, per source row (source_id within one instance):
  * source-samples/*/samples/source-*.json  (source row + one random stored article)
  * source-samples manifests' sources_without_article (+ class columns where present)
  * source-quality per_source_summary.jsonl and per_source_keywords.jsonl
Writes PRIVATE files (raw per-instance source lists): OUT/sources-<label>.jsonl
Article text is reduced to lengths and a few derived flags; nothing here is published.

Older exports (2026-11-14) name the folders oo-field-source-quality and 01..NN; both layouts are read.
Usage: python3 -I build_sources.py DATA_ROOT INSTANCES_JSON OUT_DIR
"""
import glob, json, os, sys

data_root, inst_json, out_dir = sys.argv[1:4]
labels = json.load(open(inst_json))
os.makedirs(out_dir, exist_ok=True)


def one(pattern):
    hits = sorted(glob.glob(pattern))
    return hits[0] if hits else None


def via_of(tags):
    for t in (tags or '').split(','):
        t = t.strip()
        if t.startswith('via:'):
            return t[4:]
    return None

for folder, label in labels.items():
    base = os.path.join(data_root, folder)
    rows = {}
    # 1. samples (sources with >=1 stored article)
    zips = sorted(glob.glob(base + '/*source-samples-*')) or sorted(d for d in glob.glob(base + '/[0-9][0-9]') if os.path.isdir(d))
    for z in zips:
        man = json.load(open(z + '/manifest.json'))
        sw = man.get('sources_without_article') or {}
        cols = sw.get('columns') or []
        cls_cols = (sw.get('classes') or {}).get('columns') or []
        cls_rows = (sw.get('classes') or {}).get('rows') or []
        for r in sw.get('rows') or []:
            d = dict(zip(cols, r))
            sid = d['source_id']
            rec = rows.setdefault(sid, {'source_id': sid})
            rec.update({'domain': d.get('domain'), 'feed_key': d.get('feed_key'), 'has_article': False})
            if 'class' in d and cls_rows:
                c = dict(zip(cls_cols, cls_rows[d['class']]))
                for k in ('enabled', 'status', 'via', 'has_feed', 'last_qualification', 'last_feed_status'):
                    rec[k] = c.get(k)
        for f in glob.glob(z + '/samples/*.json'):
            s = json.load(open(f))
            src, art = s['source'], s.get('article') or {}
            sid = src['id']
            rec = rows.setdefault(sid, {'source_id': sid})
            content = art.get('content') or ''
            rec.update({
                'domain': src.get('domain'), 'feed_key': src.get('feed_key'), 'name': src.get('name'),
                'rss_url': src.get('rss_url'), 'enabled': src.get('enabled'), 'status': src.get('status'),
                'via': via_of(src.get('tags')), 'tags': src.get('tags'), 'source_type': src.get('source_type'),
                'country': src.get('country'), 'language': src.get('language'), 'region': src.get('region'),
                'reliability_score': src.get('reliability_score'), 'priority': src.get('priority'),
                'article_count_src': src.get('article_count'), 'articles_in_source': s.get('articles_in_source'),
                'qualified_at': src.get('qualified_at'), 'criteria_version': src.get('qualification_criteria_version'),
                'last_crawled_at': src.get('last_crawled_at'), 'has_catalog_baseline': bool(src.get('catalog_baseline')),
                'has_article': True,
                'sample': {
                    'article_id': art.get('id'), 'url': art.get('url'), 'canonical_url': art.get('canonical_url'),
                    'title': art.get('title'), 'content_chars': len(content), 'compressed': art.get('compressed_content') is not None,
                    'word_count': art.get('word_count'), 'published_at': art.get('published_at'),
                    'created_at': art.get('created_at'), 'language': art.get('language'),
                    'detected_language': art.get('detected_language'), 'quarantined': art.get('quarantined'),
                    'quarantine_reason': art.get('quarantine_reason'), 'fetched_host': art.get('fetched_host'),
                    'author': bool(art.get('author')),
                },
            })
    # 2. per_source_summary / keywords
    sq = one(base + '/*-source-quality') or one(base + '/oo-field-source-quality')
    if sq:
        for line in open(sq + '/per_source_summary.jsonl'):
            d = json.loads(line)
            rec = rows.setdefault(d['source_id'], {'source_id': d['source_id']})
            rec['summary'] = {k: d.get(k) for k in (
                'article_count', 'ratio_audited', 'provenance_class', 'outlier_count', 'outlier_rate',
                'dominant_outlier_kind', 'n_indexed', 'pct_indexed', 'listing_url_count', 'listing_url_rate',
                'qualification_status', 'qualified_at', 'qualification_criteria_version', 'is_newsletter')}
            rec.setdefault('domain', d.get('domain')); rec.setdefault('feed_key', d.get('feed_key'))
        for line in open(sq + '/per_source_keywords.jsonl'):
            d = json.loads(line)
            rec = rows.setdefault(d['source_id'], {'source_id': d['source_id']})
            rec['keywords'] = {'top': [ (k.get('keyword') or k.get('term'), k.get('mentions') or k.get('n')) for k in (d.get('top_keywords') or [])],
                               'furniture_share': d.get('furniture_share'), 'flagged_furniture': d.get('flagged_furniture'),
                               'metric_distributions': d.get('metric_distributions')}
    out = os.path.join(out_dir, f"sources-{label.replace(' ', '_')}.jsonl")
    with open(out, 'w') as w:
        for sid in sorted(rows):
            w.write(json.dumps(rows[sid], ensure_ascii=False) + '\n')
    n_art = sum(1 for r in rows.values() if r.get('has_article'))
    print(f'{label}: {len(rows)} source rows, {n_art} with a stored article -> {out}')
