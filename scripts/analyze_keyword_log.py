#!/usr/bin/env python3
"""
Keyword-diagnostics log analyzer — turn a manageable export into review-ready
keyword-quality proposals.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app's ``GET /api/diagnostics/keywords`` endpoint emits a bounded, per-language
"keyword-diagnostics" document (schema ``oo-export-1``) so a human/agent can ingest
the corpus's keyword behaviour WITHOUT shipping the whole 60 MB mention store
(maintainer design: "the logging system creates manageable documents you can
ingest"). This script closes that loop: it reads ONE such log and proposes, with
evidence, the next optimization batch for:

  * keyword COLLECTION  — net-new function-word / weekday / boilerplate stopword
                          candidates (vs the live ``_EXTRA_STOPWORD_TEXT`` + the
                          per-language sets), so "stupid" keywords like "that"
                          stop being collected;
  * TAGGING             — keywords mis-tagged ``kind=entity`` that are really
                          common words (sentence-initial-capital false entities);
  * language EQUIVALENCE — cross-language ring candidates (Latin-script cognate
                          clusters + the top concept per language to map by hand),
                          proposed as additions to ``configs/keyword_equivalents.yml``;
  * FAMILIES            — within-language singular/plural pairs that never merged.

HONESTY BY CONSTRUCTION (matches the maintainer's keyword-policy rulings):
  - It PROPOSES; it never edits source or data. Every list is for human review.
  - "net-new" is measured against the REAL stoplists parsed from source, so it
    never re-proposes a word already filtered.
  - Candidates are RANKED by stopword-likelihood SIGNALS (short length, high
    cross-article spread, single dominant article-language), never asserted as
    truth; content words and proper nouns are separated out, not silently dropped.
  - Cognate ring candidates are flagged "verify by signature" (cognate != meaning;
    false friends exist) — language-qualified exactly like the rings file.

Usage:
    python scripts/analyze_keyword_log.py LOG.json
    python scripts/analyze_keyword_log.py LOG.json --top 30
    python scripts/analyze_keyword_log.py LOG.json --json proposals.json
    python scripts/analyze_keyword_log.py LOG.json \
        --stoplist src/analytics/extract.py src/services/stopwords.py \
        --rings configs/keyword_equivalents.yml

Dependency-free (stdlib only) on purpose: it runs against an exported log on any
machine, including one without the app's runtime installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Reference data (stdlib-local; the script must run without the app installed)
# --------------------------------------------------------------------------- #

# Weekday names across the app's UI + corpus languages. The extractor already
# strips MONTH names (en/fr + es/de/it/nl/ru blocks) but never weekday names, so
# "Sunday"/"sabado"/"lordag" leak as top keywords. Lower-cased, accent-as-stored.
_WEEKDAYS = set(
    """
    monday tuesday wednesday thursday friday saturday sunday
    lundi mardi mercredi jeudi vendredi samedi dimanche
    lunes martes miercoles miércoles jueves viernes sabado sábado domingo
    montag dienstag mittwoch donnerstag freitag samstag sonnabend sonntag
    lunedi lunedì martedi martedì mercoledi mercoledì giovedi giovedì venerdi
    venerdì sabato domenica
    segunda terca terça quarta quinta sexta sabado domingo
    maandag dinsdag woensdag donderdag vrijdag zaterdag zondag
    mandag tirsdag onsdag torsdag fredag lordag lørdag sondag søndag
    poniedzialek poniedziałek wtorek sroda środa czwartek piatek piątek sobota niedziela
    hetfo hétfő kedd szerda csutortok csütörtök pentek péntek szombat vasarnap vasárnap
    ponedeljak utorak sreda cetvrtak četvrtak petak subota nedelja nedjelja
    ponedeljek torek sreda cetrtek četrtek petek sobota nedelja
    senin selasa rabu kamis jumat sabtu minggu
    понедельник вторник среда четверг пятница суббота воскресенье
    الاثنين الإثنين الثلاثاء الأربعاء الخميس الجمعة السبت الأحد
    """.split()
)

# Cross-source boilerplate vocabulary: social-follow CTAs, paywall/comment-widget
# chrome, ad/loader markers. A keyword (or n-gram) containing one of these is a
# boilerplate SUSPECT (still human-reviewed — these also flag legit content).
_BOILERPLATE_HINTS = set(
    """
    advertisement loading subscribe newsletter follow comments comment cookie
    cookies paywall login signin register login sponsored e-avis e-paper
    facebook twitter instagram whatsapp telegram youtube tiktok linkedin patreon
    pročitajte komentare diskusiji oglas artiklen læs adgang binding abonner
    abonnement abonnez accedi accedere suscríbete suscribete inscrivez
    """.split()
)

# Languages we surface stopword proposals for, in a stable display order.
_LANG_ORDER = [
    "en", "fr", "es", "de", "it", "pt", "nl", "ru", "sv", "nb", "da",
    "pl", "hu", "sr", "sl", "ar", "tr", "id", "fi", "hi", "?",
]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_log(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("kind") != "keyword-diagnostics":
        print(
            f"warning: {path.name} kind={doc.get('kind')!r} "
            "(expected 'keyword-diagnostics') — proceeding best-effort",
            file=sys.stderr,
        )
    data = doc.get("data", doc)
    if "keywords" not in data:
        raise SystemExit(f"{path}: no 'keywords' array found — not a keyword log?")
    return doc


def parse_stoplist(paths: list[Path]) -> set[str]:
    """Best-effort union of stopword tokens parsed from the app source.

    Over-inclusive on purpose (we read every quoted string-literal token): a wider
    'existing' set only makes the net-new proposals MORE conservative — we never
    re-propose a word that is already filtered.
    """
    existing: set[str] = set()
    token_re = re.compile(r'"([^"]*)"' r"|'([^']*)'")
    for p in paths:
        try:
            txt = p.read_text(encoding="utf-8")
        except OSError:
            print(f"warning: stoplist source {p} not found — skipping", file=sys.stderr)
            continue
        for a, b in token_re.findall(txt):
            for tok in (a or b).split():
                t = tok.strip().casefold()
                if t:
                    existing.add(t)
    return existing


def parse_ring_members(path: Path) -> set[str]:
    """Pull the ``lang:term`` members already present in keyword_equivalents.yml.

    Tiny regex parser (no yaml dependency): finds every ``"xx:term"`` inside a
    ``members: [...]`` list so we never re-propose an existing ring member.
    """
    members: set[str] = set()
    try:
        txt = path.read_text(encoding="utf-8")
    except OSError:
        print(f"warning: rings file {path} not found — skipping", file=sys.stderr)
        return members
    for m in re.findall(r'"([a-z?]{1,3}:[^"]+)"', txt):
        members.add(m.casefold())
    return members


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _lang(k: dict[str, Any]) -> str:
    return k.get("language") or "?"


def _dominant_sig(k: dict[str, Any]) -> str:
    sig = k.get("language_signature") or {}
    return max(sig, key=sig.get) if sig else "?"


def _is_proper_noun_suspect(term: str) -> bool:
    """Heuristic: original surface keeps an internal/initial capital -> likely a
    name we must NOT stoplist (Diallo, Matteo, MAIB)."""
    core = term.strip()
    return bool(core) and (core[0].isupper() or any(c.isupper() for c in core[1:]))


def _sig_concentration(k: dict[str, Any]) -> tuple[str, float]:
    """(dominant article-language, its share of the keyword's signature).

    A genuine function word CONCENTRATES in its own language's articles; a name
    or loan-word/concept SPREADS across many languages. The display ``term`` is
    stored lower-cased, so case can't tell "york"/"donald" from "could" — but the
    signature can. This is the honest evidence the log already carries."""
    sig = k.get("language_signature") or {}
    if not sig:
        return "?", 0.0
    total = sum(sig.values()) or 1
    dom = max(sig, key=sig.get)
    return dom, sig[dom] / total


# --------------------------------------------------------------------------- #
# Analyses
# --------------------------------------------------------------------------- #

def stopword_candidates(
    keywords: list[dict], existing: set[str], top: int
) -> dict[str, list[dict]]:
    """Net-new single-word ``term`` candidates per language, ranked by a
    stopword-likelihood score and split into high-confidence vs review."""
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for k in keywords:
        if k.get("kind") != "term":
            continue
        term = k.get("term", "")
        if " " in term:
            continue
        norm = k.get("normalized", term.casefold())
        if norm in existing:
            continue
        arts = int(k.get("articles", 0))
        ment = int(k.get("mentions", 0))
        # stopword-likelihood signal: short + wide article spread + repeated.
        # purely a SURFACING rank, never a verdict.
        length_sig = max(0.0, 1.0 - (len(norm) - 2) / 8.0)  # 2 chars -> 1.0, 10 -> 0.0
        density = (ment / arts) if arts else 0.0
        score = arts * (0.5 + 0.5 * length_sig) + density
        proper = _is_proper_noun_suspect(term)
        weekday = norm in _WEEKDAYS
        own = _lang(k)
        dom_lang, dom_share = _sig_concentration(k)
        # A function word concentrates in its OWN language's articles. A name or
        # loan-word spreads (dom_lang != own, or a low share) -> push to review.
        concentrated = weekday or (dom_share >= 0.55 and dom_lang in (own, "?"))
        high_conf = (not proper) and concentrated and (weekday or (len(norm) <= 7 and arts >= 3))
        by_lang[own].append(
            {
                "term": term,
                "normalized": norm,
                "articles": arts,
                "mentions": ment,
                "score": round(score, 2),
                "weekday": weekday,
                "proper_noun_suspect": proper,
                "dominant_signature": dom_lang,
                "signature_concentration": round(dom_share, 2),
                "bucket": "high_confidence" if high_conf else "review",
            }
        )
    out: dict[str, list[dict]] = {}
    for lg, items in by_lang.items():
        items.sort(key=lambda x: -x["score"])
        out[lg] = items[: max(top, 0)] if top else items
    return out


def weekday_leaks(keywords: list[dict]) -> list[dict]:
    hits = []
    for k in keywords:
        if (k.get("normalized") or "").casefold() in _WEEKDAYS:
            hits.append(
                {
                    "term": k.get("term"),
                    "normalized": k.get("normalized"),
                    "language": _lang(k),
                    "kind": k.get("kind"),
                    "articles": k.get("articles"),
                }
            )
    hits.sort(key=lambda x: -(x["articles"] or 0))
    return hits


def boilerplate_suspects(keywords: list[dict], log: dict) -> dict[str, Any]:
    """Cross-source boilerplate (hint-word match) + the per_source_concentration
    section the log already computed (single-source boilerplate)."""
    cross = []
    for k in keywords:
        term = (k.get("term") or "")
        toks = {t.casefold() for t in re.split(r"[\s,.;:!?@/]+", term) if t}
        if toks & _BOILERPLATE_HINTS or "@" in term:
            cross.append(
                {
                    "term": term,
                    "language": _lang(k),
                    "kind": k.get("kind"),
                    "articles": k.get("articles"),
                }
            )
    cross.sort(key=lambda x: -(x["articles"] or 0))
    psc = (log.get("data", {}) or {}).get("per_source_concentration", {})
    return {
        "cross_source_hint_matches": cross,
        "per_source_concentration_suspects": psc.get("suspects", []),
        "per_source_concentration_total": psc.get("suspects_total"),
    }


def mistagged_entities(keywords: list[dict], top: int) -> list[dict]:
    """kind=entity whose surface is a single lower-case word or a weekday — the
    classic sentence-initial-capital false entity (World/Set/Due/Sunday)."""
    hits = []
    for k in keywords:
        if k.get("kind") != "entity":
            continue
        term = (k.get("term") or "")
        if " " in term:
            continue
        norm = (k.get("normalized") or term).casefold()
        if term.islower() or norm in _WEEKDAYS:
            hits.append(
                {
                    "term": term,
                    "normalized": norm,
                    "language": _lang(k),
                    "articles": int(k.get("articles", 0)),
                    "weekday": norm in _WEEKDAYS,
                }
            )
    hits.sort(key=lambda x: -x["articles"])
    return hits[: top or len(hits)]


def ring_candidates(
    keywords: list[dict], existing_members: set[str], top: int
) -> list[dict]:
    """Latin-script cognate clusters: single-word forms (len>=5) that share a
    4-char prefix across >=2 different stored languages and are not already ring
    members. Candidates only — cognate != equivalence; verify by signature."""
    latin = {"en", "fr", "es", "de", "it", "pt", "nl", "sv", "nb", "da", "pl", "id", "tr", "ro", "ca"}
    _PREFIX = 5  # 4 chars over-generates false friends (parte≠party); 5 is tighter
    by_prefix: dict[str, dict[str, dict]] = defaultdict(dict)
    for k in keywords:
        lg = _lang(k)
        if lg not in latin:
            continue
        norm = (k.get("normalized") or "").casefold()
        if " " in norm or len(norm) < _PREFIX or not norm.isalpha() or norm in _WEEKDAYS:
            continue
        if f"{lg}:{norm}" in existing_members:
            continue
        pref = norm[:_PREFIX]
        cur = by_prefix[pref].get(lg)
        if cur is None or int(k.get("articles", 0)) > cur["articles"]:
            by_prefix[pref][lg] = {"term": norm, "articles": int(k.get("articles", 0))}
    out = []
    for pref, perlang in by_prefix.items():
        if len(perlang) < 2:
            continue
        shortest = min(len(d["term"]) for d in perlang.values())
        # drop members whose length is far from the shortest (party vs participantes)
        kept = {lg: d for lg, d in perlang.items() if len(d["term"]) <= shortest + 3}
        if len(kept) < 2:
            continue
        members = [f"{lg}:{d['term']}" for lg, d in sorted(kept.items())]
        spread = sum(d["articles"] for d in kept.values())
        out.append(
            {
                "prefix": pref,
                "members": members,
                "languages": sorted(kept),
                "total_articles": spread,
                "note": "LOW-CONFIDENCE cognate hint — false friends exist; verify by signature",
            }
        )
    out.sort(key=lambda x: -x["total_articles"])
    return out[: top or len(out)]


def top_concepts(keywords: list[dict], top: int) -> dict[str, list[dict]]:
    """The widest-spread CONTENT terms per language (not stopword-ish, not
    boilerplate) — the manual-mapping seed for equivalence rings. The maintainer
    built keyword_equivalents.yml by hand-mapping exactly these across languages."""
    out: dict[str, list[dict]] = {}
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for k in keywords:
        norm = (k.get("normalized") or "")
        if len(norm) < 4 or norm in _WEEKDAYS:
            continue
        toks = {t.casefold() for t in re.split(r"[\s,.;:!?@/]+", k.get("term") or "") if t}
        if toks & _BOILERPLATE_HINTS:
            continue
        by_lang[_lang(k)].append(k)
    for lg, items in by_lang.items():
        items.sort(key=lambda k: -int(k.get("articles", 0)))
        out[lg] = [
            {"term": k.get("normalized"), "articles": int(k.get("articles", 0)), "kind": k.get("kind")}
            for k in items[: top or len(items)]
        ]
    return out


def inflection_pairs(keywords: list[dict], top: int) -> list[dict]:
    """Within-language singular/plural pairs not merged into one family."""
    by_lang: dict[str, dict[str, dict]] = defaultdict(dict)
    for k in keywords:
        norm = (k.get("normalized") or "")
        if " " in norm:
            continue
        by_lang[_lang(k)][norm] = k
    pairs = []
    for lg, m in by_lang.items():
        for norm, k in m.items():
            for suf in ("s", "es"):
                base = norm[: -len(suf)]
                if len(base) >= 4 and base in m:
                    pairs.append(
                        {
                            "language": lg,
                            "base": base,
                            "plural": norm,
                            "base_articles": int(m[base].get("articles", 0)),
                            "plural_articles": int(k.get("articles", 0)),
                        }
                    )
    pairs.sort(key=lambda x: -(x["base_articles"] + x["plural_articles"]))
    return pairs[: top or len(pairs)]


def language_mismatch_summary(keywords: list[dict], top: int) -> dict[str, Any]:
    flagged = [k for k in keywords if k.get("language_mismatch")]
    examples = sorted(flagged, key=lambda k: -int(k.get("articles", 0)))[: top or len(flagged)]
    return {
        "flagged": len(flagged),
        "total": len(keywords),
        "examples": [
            {
                "term": k.get("term"),
                "stored": _lang(k),
                "dominant_signature": _dominant_sig(k),
                "articles": k.get("articles"),
            }
            for k in examples
        ],
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def build_proposals(doc: dict, existing: set[str], members: set[str], top: int) -> dict:
    data = doc.get("data", doc)
    kws = data["keywords"]
    return {
        "source_log": {
            "app_version": doc.get("app_version"),
            "generated_at": doc.get("generated_at"),
            "corpus": data.get("corpus"),
        },
        "tagging_distribution": _kind_dist(kws),
        "stopword_candidates": stopword_candidates(kws, existing, top),
        "weekday_leaks": weekday_leaks(kws),
        "boilerplate": boilerplate_suspects(kws, doc),
        "mistagged_entities": mistagged_entities(kws, top),
        "ring_candidates": ring_candidates(kws, members, top),
        "top_concepts": top_concepts(kws, top),
        "inflection_pairs": inflection_pairs(kws, top),
        "language_mismatch": language_mismatch_summary(kws, top),
    }


def _kind_dist(kws: list[dict]) -> dict[str, int]:
    d: dict[str, int] = defaultdict(int)
    for k in kws:
        d[k.get("kind", "?")] += 1
    return dict(d)


def print_report(p: dict, top: int) -> None:
    sl = p["source_log"]
    corpus = sl.get("corpus") or {}
    print("=" * 78)
    print(f"KEYWORD-LOG ANALYSIS  (app {sl.get('app_version')}, {sl.get('generated_at')})")
    print(
        f"  corpus: {corpus.get('articles')} articles / {corpus.get('sources')} sources / "
        f"{corpus.get('keywords_total')} keywords ({corpus.get('keywords_exported')} exported)"
    )
    print(f"  tagging: {p['tagging_distribution']}")
    print("=" * 78)

    print("\n## 1. STOPWORD CANDIDATES (net-new vs live stoplists) — collection quality")
    print("   high-confidence = short/weekday function-word-ish; review = inspect (may be content)")
    for lg in _LANG_ORDER:
        items = p["stopword_candidates"].get(lg)
        if not items:
            continue
        hi = [i["normalized"] for i in items if i["bucket"] == "high_confidence"][:top]
        rv = [i["normalized"] for i in items if i["bucket"] == "review"][:8]
        if hi:
            print(f"  [{lg}] high-confidence: {' '.join(hi)}")
        if rv:
            print(f"  [{lg}] review:          {' '.join(rv)}")

    wk = p["weekday_leaks"]
    print(f"\n## 2. WEEKDAY-NAME leaks (month-pass never covered weekdays): {len(wk)}")
    print("   " + "  ".join(f"{w['term']}({w['language']},{w['articles']})" for w in wk[:18]))

    bp = p["boilerplate"]
    print(
        f"\n## 3. BOILERPLATE suspects: {len(bp['cross_source_hint_matches'])} cross-source + "
        f"{bp['per_source_concentration_total']} single-source (per_source_concentration)"
    )
    for b in bp["cross_source_hint_matches"][:10]:
        print(f"   cross  [{b['language']}] {b['term']!r} ({b['articles']} arts)")
    for s in bp["per_source_concentration_suspects"][:6]:
        print(f"   single [{s.get('source')}] {s.get('term')!r} ({s.get('articles_with_keyword')} arts)")

    me = p["mistagged_entities"]
    print(f"\n## 4. MIS-TAGGED entities (sentence-initial-cap false entities): {len(me)} shown")
    print("   " + "  ".join(f"{m['term']}({m['articles']})" for m in me[:24]))

    print("\n## 5. CROSS-LANGUAGE EQUIVALENCE aids")
    print("   5a. top CONTENT concepts per language (hand-map these into rings, the way")
    print("       configs/keyword_equivalents.yml was built):")
    for lg in _LANG_ORDER:
        items = p["top_concepts"].get(lg)
        if not items:
            continue
        print(f"      [{lg}] " + " ".join(i["term"] for i in items[:10]))
    rc = p["ring_candidates"]
    print(f"   5b. LOW-confidence cognate hints (false friends exist — verify by signature): {len(rc)}")
    for r in rc[:10]:
        print(f"      {r['members']}  (~{r['total_articles']} arts)")

    ip = p["inflection_pairs"]
    print(f"\n## 6. SINGULAR/PLURAL pairs not merged into one family: {len(ip)} shown")
    for x in ip[:12]:
        print(f"   [{x['language']}] {x['base']}({x['base_articles']}) <-> {x['plural']}({x['plural_articles']})")

    lm = p["language_mismatch"]
    print(f"\n## 7. LANGUAGE-MISMATCH (attribution noise): {lm['flagged']}/{lm['total']} flagged")
    for e in lm["examples"][:8]:
        print(f"   {e['term']!r}: stored={e['stored']} dominant={e['dominant_signature']} ({e['articles']} arts)")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path, help="keyword-diagnostics export (oo-export-1) JSON")
    ap.add_argument("--top", type=int, default=24, help="max items per section (0 = all)")
    ap.add_argument(
        "--stoplist",
        type=Path,
        nargs="*",
        default=[Path("src/analytics/extract.py"), Path("src/services/stopwords.py")],
        help="source files whose quoted tokens form the 'already filtered' baseline",
    )
    ap.add_argument(
        "--rings",
        type=Path,
        default=Path("configs/keyword_equivalents.yml"),
        help="existing equivalence rings (so we never re-propose a member)",
    )
    ap.add_argument("--json", type=Path, default=None, help="write machine-readable proposals here")
    args = ap.parse_args(argv)

    doc = load_log(args.log)
    existing = parse_stoplist(args.stoplist)
    members = parse_ring_members(args.rings)
    proposals = build_proposals(doc, existing, members, args.top)
    proposals["baseline"] = {
        "existing_stopword_tokens": len(existing),
        "existing_ring_members": len(members),
    }
    print_report(proposals, args.top)
    if args.json:
        args.json.write_text(json.dumps(proposals, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[wrote machine-readable proposals -> {args.json}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
