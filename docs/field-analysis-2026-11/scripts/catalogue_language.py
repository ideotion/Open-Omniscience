#!/usr/bin/env python3
"""Catalogue language check.

For every shipped catalogue key, compare the dominant script of its random sample article
(article_quality.py, meta.script) with the script its CATALOGUE language implies, over every
snapshot that sampled it. Only script-level errors are visible ('en' declared, Cyrillic text);
same-script errors (ru vs be, es vs pt) are not, so this is a lower bound.
A key is proposed for a language fix when >=3 snapshots sampled it with >=50 letters of text,
>=75% of them mismatch, and every mismatching snapshot found the same script.
Usage: python3 -I catalogue_language.py CATALOGUE.json OUT.json DERIVED [DERIVED...]
"""
import glob, json, os, sys
from collections import Counter, defaultdict

cat_path, out, *dirs = sys.argv[1:]
SCRIPT = {'ru': 'CYRILLIC', 'uk': 'CYRILLIC', 'bg': 'CYRILLIC', 'mk': 'CYRILLIC', 'be': 'CYRILLIC', 'kk': 'CYRILLIC', 'ky': 'CYRILLIC',
          'mn': 'CYRILLIC', 'tg': 'CYRILLIC', 'ar': 'ARABIC', 'fa': 'ARABIC', 'ur': 'ARABIC', 'ps': 'ARABIC', 'he': 'HEBREW',
          'el': 'GREEK', 'hy': 'ARMENIAN', 'ka': 'GEORGIAN', 'hi': 'DEVANAGARI', 'mr': 'DEVANAGARI', 'ne': 'DEVANAGARI', 'bn': 'BENGALI',
          'pa': 'GURMUKHI', 'gu': 'GUJARATI', 'ta': 'TAMIL', 'te': 'TELUGU', 'kn': 'KANNADA', 'ml': 'MALAYALAM', 'si': 'SINHALA',
          'th': 'THAI', 'lo': 'LAO', 'km': 'KHMER', 'my': 'MYANMAR', 'am': 'ETHIOPIC', 'zh': 'CJK', 'ja': 'CJK', 'ko': 'HANGUL'}
LATIN = set('en fr de es pt it nl sv no nb nn da fi is et lv lt pl cs sk sl hr bs ro hu tr az sq ca eu gl ga cy mt id ms tl vi sw ha yo ig zu xh so af eo la uz tk'.split())
cat = {}
for r in json.load(open(cat_path)):
    cat.setdefault((r['domain'], r['feed_key']), r)
obs = defaultdict(list)
for d in dirs:
    for f in glob.glob(os.path.join(d, 'sources-*.jsonl')):
        lab = os.path.basename(f)[8:-6]
        ff = os.path.join(d, f'article-flags-{lab}.jsonl')
        if not os.path.exists(ff):
            continue
        scr = {}
        for l in open(ff):
            x = json.loads(l); scr[x['meta']['source_id']] = x['meta']['script']
        for l in open(f):
            x = json.loads(l)
            k = ((x.get('domain') or '').lower(), x.get('feed_key'))
            if k in cat and x.get('has_article') and scr.get(x['source_id']):
                obs[k].append(scr[x['source_id']])
props = []; checked = 0
for k, s in obs.items():
    lang = (cat[k].get('language') or '').lower()[:2]
    want = SCRIPT.get(lang, 'LATIN' if lang in LATIN else None)
    if not want or len(s) < 3:
        continue
    checked += 1
    mism = [x for x in s if x != want]
    if len(mism) / len(s) >= 0.75 and len(set(mism)) == 1:
        e = cat[k]
        props.append({'domain': k[0], 'feed_key': k[1], 'file': e['file'], 'index': e['index'], 'name': e['name'],
                      'catalogue_language': e.get('language'), 'expected_script': want, 'observed_script': mism[0],
                      'snapshots': len(s), 'mismatching': len(mism)})
json.dump(props, open(out, 'w'), ensure_ascii=False, indent=1)
print('catalogue keys checked (>=3 sampled snapshots, script-checkable language):', checked)
print('proposed language fixes:', len(props), Counter((p['catalogue_language'], p['observed_script']) for p in props).most_common(15))
