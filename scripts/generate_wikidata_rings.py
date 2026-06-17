#!/usr/bin/env python3
"""Generate cross-language keyword RINGS from Wikidata labels (the pre-translation
program, Step 3).

Pre-translation AT SCALE without an LLM and without fabrication: for each seed
concept, find its Wikidata item (QID) and pull the multilingual LABELS + ALIASES
(all CC0) for the app's UI languages -> one ring carrying the translations AND the
synonyms (the aliases), SOURCED by the QID.

This runs on a NETWORKED machine -- Wikidata is not on the app's local-first fetch
path; the offline app only READS the generated file. The parse functions are pure
and offline-tested; only fetch_json() touches the network (stdlib urllib, no deps).

Output augments configs/keyword_rings_generated.yml, which src/analytics/
equivalence.py reads ALONGSIDE the hand-curated configs/keyword_equivalents.yml (a
curated ring WINS on an id collision). REVIEW generated rings before trusting them
(a wrong QID = a wrong concept); each ring carries its QID for audit, and the
existing language-signature gate still protects against false merges.

Usage:
    python scripts/generate_wikidata_rings.py --seeds seeds.txt
    python scripts/generate_wikidata_rings.py --from-log oo-keyword-log.json --top 300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

# The app's UI languages = the pre-translation scope. zh/ja are included for
# completeness though their keyword extraction is segmentation-limited today.
LANGS: tuple[str, ...] = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

_API = "https://www.wikidata.org/w/api.php"
_UA = "OpenOmniscience-ring-generator/0.1 (local-first research app)"


def wbsearch_url(term: str) -> str:
    qs = urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": term, "language": "en",
         "format": "json", "limit": 1, "type": "item"}
    )
    return f"{_API}?{qs}"


def wbentities_url(qid: str, langs: tuple[str, ...] = LANGS) -> str:
    qs = urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": qid, "props": "labels|aliases",
         "languages": "|".join(langs), "format": "json"}
    )
    return f"{_API}?{qs}"


def parse_search(payload: dict) -> str | None:
    """The first search result's QID, or None."""
    results = payload.get("search") or []
    return results[0].get("id") if results else None


def parse_entity(payload: dict, qid: str, langs: tuple[str, ...] = LANGS) -> dict[str, list[str]]:
    """``{lang: [label, *aliases]}`` for the languages present (label + synonyms)."""
    ent = (payload.get("entities") or {}).get(qid) or {}
    labels = ent.get("labels") or {}
    aliases = ent.get("aliases") or {}
    out: dict[str, list[str]] = {}
    for lang in langs:
        terms: list[str] = []
        lab = (labels.get(lang) or {}).get("value")
        if lab:
            terms.append(lab)
        for al in aliases.get(lang, []) or []:
            if al.get("value"):
                terms.append(al["value"])
        seen: set[str] = set()
        uniq: list[str] = []
        for t in terms:
            k = t.casefold()
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        if uniq:
            out[lang] = uniq
    return out


def _slug(s: str) -> str:
    return "-".join("".join(c if c.isalnum() else " " for c in s.lower()).split())


def build_ring(seed: str, qid: str, lang_terms: dict[str, list[str]]) -> dict | None:
    """A ring ``{id, qid, members:["lang:term", …]}``, or None if <2 languages."""
    members = [f"{lang}:{t}" for lang, terms in lang_terms.items() for t in terms]
    if len({m.split(":", 1)[0] for m in members}) < 2:
        return None  # a ring needs >=2 languages to merge anything
    en = lang_terms.get("en") or [seed]
    return {"id": _slug(en[0]) or qid.lower(), "qid": qid, "members": members}


def fetch_json(url: str, getter: Callable[[str], bytes] | None = None) -> dict:
    """GET + parse JSON. ``getter`` is injectable so tests never touch the network."""
    if getter is not None:
        return json.loads(getter(url))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - documented Wikidata API
        return json.loads(r.read())


def generate(seeds, getter=None, sleep=0.2, log=print) -> list[dict]:
    """Build rings for each seed; one seed's failure never aborts the run."""
    rings: list[dict] = []
    for seed in seeds:
        try:
            qid = parse_search(fetch_json(wbsearch_url(seed), getter))
            if not qid:
                log(f"  no QID for {seed!r}")
                continue
            lang_terms = parse_entity(fetch_json(wbentities_url(qid), getter), qid)
            ring = build_ring(seed, qid, lang_terms)
            if ring:
                rings.append(ring)
                log(f"  {seed} -> {qid} ({len(ring['members'])} members)")
            else:
                log(f"  {seed} -> {qid} but <2 languages, skipped")
        except Exception as e:  # noqa: BLE001 - per-seed resilience, logged
            log(f"  ERROR {seed!r}: {type(e).__name__}: {e}")
        if sleep:
            time.sleep(sleep)
    return rings


def _yaml_q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_yaml(rings: list[dict], as_of: str) -> str:
    lines = [
        "# Cross-language keyword RINGS generated from Wikidata labels + aliases (CC0).",
        "# GENERATED FILE - regenerate with scripts/generate_wikidata_rings.py; review before trusting.",
        "# Each ring carries its Wikidata QID for audit; a curated ring of the same id wins.",
        f'generated_as_of: "{as_of}"',
        "rings:",
    ]
    for r in rings:
        lines.append(f"  - id: {r['id']}")
        lines.append(f"    qid: {r['qid']}")
        lines.append("    members: [" + ", ".join(_yaml_q(m) for m in r["members"]) + "]")
    return "\n".join(lines) + "\n"


def load_seeds(args) -> list[str]:
    if args.seeds:
        return [
            ln.strip()
            for ln in Path(args.seeds).read_text("utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
    if args.from_log:
        doc = json.loads(Path(args.from_log).read_text("utf-8"))
        kws = (doc.get("data", doc)).get("keywords", [])
        en = [k for k in kws if k.get("language") == "en" and k.get("kind") == "term"]
        en.sort(key=lambda k: -int(k.get("articles", 0) or 0))
        return [k.get("normalized") or k.get("term") for k in en[: args.top]]
    return []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seeds", type=str, help="file of English seed terms (one per line)")
    ap.add_argument("--from-log", type=str, help="a keyword-diagnostics log; use its top English terms")
    ap.add_argument("--top", type=int, default=300, help="with --from-log, how many top terms")
    ap.add_argument(
        "-o", "--out", type=Path, default=Path("configs/keyword_rings_generated.yml")
    )
    args = ap.parse_args(argv)
    seeds = load_seeds(args)
    if not seeds:
        print("no seeds (use --seeds FILE or --from-log LOG.json)", file=sys.stderr)
        return 2
    print(f"generating rings for {len(seeds)} seeds via Wikidata...", file=sys.stderr)
    rings = generate(seeds, log=lambda m: print(m, file=sys.stderr))
    args.out.write_text(emit_yaml(rings, date.today().strftime("%Y-%m")), encoding="utf-8")
    print(f"[wrote {len(rings)} rings -> {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
