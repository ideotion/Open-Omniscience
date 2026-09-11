"""Which of the discovered candidates COMPLEMENT the shipped catalogue? -- a review worklist,
never an auto-add.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-09-10): the ~80k discovered candidates "are a treasure we should
not dismiss" -- how to handle them, and how to extract from them the sources that would
complement the ~3,600 shipped ones. The maintainer attached the instance's sources export
(``GET /api/sources/export`` as CSV: name, domain, rss_url, source_type, country, language,
region, tags, priority, rate_limit_ms, enabled, reliability_score).

WHAT THIS DOES, offline and from that file alone:

1. Splits the export into the CATALOGUE (enabled rows: the shipped catalogues plus anything
   the operator enabled) and the DISCOVERED set (``via:wikidata-discovery``), and the
   discovered set by ``source_type`` -- because 62 % of it is institutions and religious
   organisations, which are registry entries rather than trial candidates.
2. Dedupes the discovered news rows against the catalogue: an exact registrable-domain match
   or a known alias (``src.utils.url_utils.DOMAIN_ALIASES``) is a DUPLICATE; a host that is a
   subdomain of a catalogue domain is flagged, not dropped (a regional edition can be a real,
   distinct feed).
3. Fills a missing language from the ccTLD, conservatively (``src.catalog.cctld`` only
   answers for single-language ccTLDs; a generic TLD stays unknown, never guessed).
4. Classes each news row by the GAP it would fill, measured against the catalogue's own
   per-country and per-language counts -- a class, not a score:
     T1  the catalogue has NO source in this country
     T2  the catalogue has 1-4 sources in this country
     T3  the row's language has fewer than 20 catalogue sources (and T1/T2 do not apply)
     T4  everything else
   Within a class rows are ordered by country then name: nothing here ranks one outlet above
   another, because nothing in the export could honestly do so.
5. Writes a bounded SHORTLIST (T1 + T2 + T3, capped per country, the cap stated) and a
   REPORT with the composition, the dedupe outcome, the gap tables and the caveats.

WHAT IT CANNOT DO, said plainly: nothing here touches the network, so no feed is discovered
and no site is verified -- every row stays a Wikidata claim that an outlet exists and has a
website. The shortlist is the input to the app's own trial (or to a clearnet review session),
not a catalogue entry. No composite score, no ranking, no field named score/rating/grade.

Run:
  .venv/bin/python scripts/analysis/complement_candidates.py \
      --export path/to/open-omniscience-sources.csv \
      --out-dir docs/research/sources/discovered_candidates_<date>
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.catalog.cctld import infer_language  # noqa: E402
from src.catalog.countries import continent_of, country_display_name  # noqa: E402
from src.catalog.normalize import registrable_domain  # noqa: E402
from src.utils.url_utils import DOMAIN_ALIASES, normalize_domain  # noqa: E402

DISCOVERY_TAG = "via:wikidata-discovery"
T2_MAX_CATALOGUE_SOURCES = 4      # 1..4 catalogue sources in the country -> T2
T3_MAX_LANGUAGE_SOURCES = 20      # fewer than this many catalogue sources in the language -> T3
DEFAULT_PER_COUNTRY_CAP = 100     # the shortlist is a worklist; the cap bounds the FILE, never a count
_NON_ASCII = re.compile(r"[^\x00-\x7f]")


def _tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _reg(domain: str) -> str:
    return registrable_domain(domain) or normalize_domain(domain)


def _alias_set(domain: str) -> set[str]:
    """The domain plus every known alias of it, both directions."""
    d = normalize_domain(domain)
    out = {d}
    out.update(DOMAIN_ALIASES.get(d, []))
    for k, vals in DOMAIN_ALIASES.items():
        if d in vals:
            out.add(k)
            out.update(vals)
    return out


def load_export(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def analyse(rows: list[dict], *, per_country_cap: int = DEFAULT_PER_COUNTRY_CAP) -> dict:
    catalogue = [r for r in rows if (r.get("enabled") or "").strip().lower() == "true"]
    discovered = [r for r in rows if DISCOVERY_TAG in _tags(r.get("tags"))]
    # By identity, not `r not in list`: a list scan per row is O(n^2) -- four minutes on 85k rows.
    placed = {id(r) for r in catalogue} | {id(r) for r in discovered}
    other = [r for r in rows if id(r) not in placed]

    by_type = Counter(r.get("source_type") or "" for r in discovered)
    news = [r for r in discovered if (r.get("source_type") or "") == "news"]

    # --- the catalogue's own shape, the denominator every gap is measured against
    cat_country = Counter((r.get("country") or "").lower() for r in catalogue)
    cat_language = Counter((r.get("language") or "").lower() for r in catalogue)
    cat_domains: set[str] = set()
    for r in catalogue:
        cat_domains.update(_alias_set(_reg(r["domain"])))

    # --- dedupe + flags + language fill
    kept: list[dict] = []
    dup = sub = idn = 0
    lang_filled = 0
    for r in news:
        dom = _reg(r["domain"])
        aliases = _alias_set(dom)
        flags: list[str] = []
        if aliases & cat_domains:
            dup += 1
            continue
        if any(dom.endswith("." + c) for c in cat_domains):
            sub += 1
            flags.append("subdomain_of_catalogue_domain")
        if _NON_ASCII.search(dom):
            idn += 1
            flags.append("idn_domain")
        if dom.count(".") >= 3:
            flags.append("deep_host")
        lang = (r.get("language") or "").lower()
        lang_basis = "export" if lang else ""
        if not lang:
            guess = infer_language(dom)
            if guess:
                lang, lang_basis = guess, "cctld"
                lang_filled += 1
        kept.append({
            "name": r.get("name") or "",
            "domain": dom,
            "country": (r.get("country") or "").lower(),
            "language": lang,
            "language_basis": lang_basis,
            "flags": ";".join(flags),
        })

    # --- gap classes
    disc_country = Counter(r["country"] for r in kept)
    disc_language = Counter(r["language"] for r in kept)
    tier_count: Counter = Counter()
    for r in kept:
        c, lang = r["country"], r["language"]
        n_c = cat_country.get(c, 0) if c else None
        n_l = cat_language.get(lang, 0) if lang else None
        if c and n_c == 0:
            tier = "T1"
        elif c and 1 <= n_c <= T2_MAX_CATALOGUE_SOURCES:
            tier = "T2"
        elif lang and n_l < T3_MAX_LANGUAGE_SOURCES:
            tier = "T3"
        else:
            tier = "T4"
        r["tier"] = tier
        r["catalogue_sources_in_country"] = "" if n_c is None else n_c
        r["catalogue_sources_in_language"] = "" if n_l is None else n_l
        tier_count[tier] += 1

    # --- the shortlist: T1 + T2 + T3, per-country cap, country/name order (no ranking)
    shortlist: list[dict] = []
    capped_countries: dict[str, int] = {}
    per_country: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(kept, key=lambda x: (x["tier"], x["country"], x["name"].lower())):
        if r["tier"] in ("T1", "T2", "T3"):
            per_country[r["country"] or "∅"].append(r)
    for c, rs in per_country.items():
        if len(rs) > per_country_cap:
            capped_countries[c] = len(rs)
        shortlist.extend(rs[:per_country_cap])
    shortlist.sort(key=lambda x: (x["tier"], x["country"], x["name"].lower()))

    return {
        "rows": len(rows),
        "catalogue": len(catalogue),
        "catalogue_with_feed": sum(1 for r in catalogue if (r.get("rss_url") or "").strip()),
        "discovered": len(discovered),
        "discovered_with_feed": sum(1 for r in discovered if (r.get("rss_url") or "").strip()),
        "other": len(other),
        "discovered_by_type": dict(by_type),
        "news": len(news),
        "news_duplicates_of_catalogue": dup,
        "news_subdomain_flagged": sub,
        "news_idn_flagged": idn,
        "news_language_filled_from_cctld": lang_filled,
        "news_language_unknown": sum(1 for r in kept if not r["language"]),
        "news_kept": len(kept),
        "tiers": dict(tier_count),
        "shortlist": shortlist,
        "shortlist_cap": per_country_cap,
        "shortlist_capped_countries": capped_countries,
        "cat_country": cat_country,
        "cat_language": cat_language,
        "disc_country": disc_country,
        "disc_language": disc_language,
        "kept": kept,
        "institution_by_country": Counter(
            (r.get("country") or "").lower() for r in discovered
            if (r.get("source_type") or "") == "institution"
        ),
    }


def _md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def write_outputs(result: dict, out_dir: Path, *, export_name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ["tier", "country", "language", "language_basis", "name", "domain",
              "catalogue_sources_in_country", "catalogue_sources_in_language", "flags"]
    with (out_dir / "shortlist.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in result["shortlist"]:
            w.writerow({k: r.get(k, "") for k in fields})

    cat_c, disc_c = result["cat_country"], result["disc_country"]
    countries = sorted(
        {c for c in disc_c if c},
        key=lambda c: (-(disc_c[c]), c),
    )
    gap_rows = []
    for c in countries[:60]:
        gap_rows.append([
            c, country_display_name(c) or "", continent_of(c) or "",
            cat_c.get(c, 0), disc_c[c],
            result["institution_by_country"].get(c, 0),
        ])
    zero_countries = sorted(c for c in disc_c if c and cat_c.get(c, 0) == 0)
    cat_l, disc_l = result["cat_language"], result["disc_language"]
    lang_rows = [
        [lang or "∅", cat_l.get(lang, 0), disc_l[lang]]
        for lang in sorted(disc_l, key=lambda x: -disc_l[x])[:40]
    ]
    tiers = result["tiers"]
    capped = result["shortlist_capped_countries"]

    report = f"""# Discovered candidates vs the shipped catalogue — what complements it

**Input:** `{export_name}` ({result['rows']:,} rows), the instance's sources export the
maintainer attached on 2026-09-10. **Method:** `scripts/analysis/complement_candidates.py`,
offline, from the file alone — no fetch, no verification. Every discovered row is a Wikidata
claim that an outlet exists and has a website; **none has a feed** and none has been reached.

## 1. Composition

| Set | Rows | With a feed |
|---|---|---|
| Catalogue (enabled) | {result['catalogue']:,} | {result['catalogue_with_feed']:,} |
| Discovered (`{DISCOVERY_TAG}`) | {result['discovered']:,} | {result['discovered_with_feed']:,} |
| Other (promoted candidates, hand-added, cited) | {result['other']:,} | — |

Discovered rows by type: {', '.join(f"**{k or '∅'}** {v:,}" for k, v in sorted(result['discovered_by_type'].items(), key=lambda kv: -kv[1]))}.
Institutions and religious organisations are **registry entries**, not trial candidates: the
trial judges extraction validity and would admit a ministry's press page as readily as a
newspaper. They stay discoverable, searchable and hand-promotable, and the per-country
institution counts below are the seed of the official-sources vertical.

## 2. The news rows, deduped against the catalogue

| Step | Rows |
|---|---|
| Discovered rows typed `news` | {result['news']:,} |
| Removed: exact domain or known alias already in the catalogue | {result['news_duplicates_of_catalogue']:,} |
| Kept for classing | {result['news_kept']:,} |
| Flagged (kept): subdomain of a catalogue domain | {result['news_subdomain_flagged']:,} |
| Flagged (kept): internationalised domain name | {result['news_idn_flagged']:,} |
| Language filled from a single-language ccTLD | {result['news_language_filled_from_cctld']:,} |
| Language still unknown after that | {result['news_language_unknown']:,} |

## 3. Gap classes (a class, not a score)

| Class | Meaning | Rows |
|---|---|---|
| T1 | the catalogue has **no** source in the row's country | {tiers.get('T1', 0):,} |
| T2 | the catalogue has 1–{T2_MAX_CATALOGUE_SOURCES} sources in the country | {tiers.get('T2', 0):,} |
| T3 | the row's language has fewer than {T3_MAX_LANGUAGE_SOURCES} catalogue sources | {tiers.get('T3', 0):,} |
| T4 | none of the above | {tiers.get('T4', 0):,} |

Countries with **zero** catalogue sources and at least one discovered news outlet
({len(zero_countries)}): {', '.join(zero_countries) or '—'}.

The shortlist (`shortlist.csv`, {len(result['shortlist']):,} rows) holds T1 + T2 + T3, ordered
by class, country and name — **no row outranks another** — capped at {result['shortlist_cap']}
per country so the file stays reviewable. Countries the cap truncated (total in brackets):
{', '.join(f"{c} ({n})" for c, n in sorted(capped.items())) or 'none'}.

## 4. Catalogue vs discovered, by country (top 60 by discovered news rows)

{_md_table(['code', 'country', 'region', 'catalogue', 'discovered news', 'discovered institutions'], gap_rows)}

## 5. By language (top 40 by discovered news rows; ∅ = unknown after the ccTLD fill)

{_md_table(['language', 'catalogue', 'discovered news'], lang_rows)}

## 6. How to read this, and what it is not

- A discovered row that reaches collection still passes the trial: this file changes the
  ORDER in which the discovery queue is worked (complement first), never the gate.
- The classes measure the catalogue's own thinness, not an outlet's worth. A T4 row can be
  the best newspaper in its country; a T1 row can be a defunct site. Nothing offline can tell.
- The catalogue's country field is empty on {result['cat_country'].get('', 0):,} of its
  {result['catalogue']:,} rows, so the per-country denominators UNDERSTATE coverage for
  countries whose catalogue sources carry no country. The fix for that is the catalogue's
  NULL-only country reconcile, not this file.
- Nothing here is a source until a feed (or a sitemap) is found and the trial stores real
  articles. The next step is networked: feed autodiscovery over the shortlist, through the
  app's own guarded fetcher.
"""
    (out_dir / "REPORT.md").write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--export", required=True, type=Path, help="the sources export CSV")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--per-country-cap", type=int, default=DEFAULT_PER_COUNTRY_CAP)
    args = ap.parse_args(argv)
    rows = load_export(args.export)
    result = analyse(rows, per_country_cap=args.per_country_cap)
    write_outputs(result, args.out_dir, export_name=args.export.name)
    summary = {k: v for k, v in result.items()
               if k not in ("shortlist", "kept", "cat_country", "cat_language",
                            "disc_country", "disc_language", "institution_by_country")}
    summary["shortlist_rows"] = len(result["shortlist"])
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
