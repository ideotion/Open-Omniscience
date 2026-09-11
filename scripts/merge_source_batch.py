"""Append a reviewed batch of verified sources to ``configs/sources.yml`` -- as a TEXT SPLICE.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The last step of the candidate pipeline, and the only one that touches the curated
catalogue. It is deliberately dumb: it never re-serialises ``sources.yml`` (the recorded
"never re-serialise a curated file to edit one entry" lesson -- a YAML round-trip reformats
and reorders 3,400 untouched entries and buries the real diff), it appends rendered entries
to the END of the file, and it refuses anything it cannot vouch for:

* an entry without ``name``/``domain``/``rss_url``/``verified: true``/``last_verified`` (an
  unverified feed has no business in the curated file -- the 2026-09-10 ruling stamps this
  file's rows qualified at seed, so what enters here is collected from day one);
* a domain already present in ANY shipped catalogue, by registrable domain or known alias
  (``Source.domain`` is UNIQUE, so the entry would be SHADOWED and never registered -- the
  475-entry loss the catalogue already carries, not to be grown);
* a duplicate within the batch;
* a tag that is a row-provenance marker (``via:*``), a country name, or a language code;
* a ``name`` whose trailing parenthetical the catalogue reads as a COUNTRY that the entry's
  own ``country`` field contradicts (``3CatInfo (tv)`` with ``country: es`` -- ``tv`` is
  Tuvalu, the suffix is the channel's branding). The splice refuses rather than rewrites:
  names are normalised upstream, where the entry is built, and this is the gate that catches
  one arriving any other way.

Dry-run by default: prints the plan. ``--apply`` writes. Idempotent: a second apply of the
same batch appends nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.catalog.countries import normalize_country  # noqa: E402
from src.catalog.normalize import country_from_title, registrable_domain  # noqa: E402
from src.utils.url_utils import DOMAIN_ALIASES, normalize_domain  # noqa: E402

CATALOGUE_FILES = (
    "configs/sources.yml", "configs/sources_spectrum.yml", "configs/markets_sources.yml",
    "configs/legal_sources.yml", "configs/legal_sources_generated.yml",
    "configs/world_news_sources.yml",
    "configs/academic_sources.yml", "configs/official_sources.yml",
)
REQUIRED = ("name", "domain", "rss_url", "verified", "last_verified")
_LANGUAGE_CODES = frozenset({
    "ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh", "it", "nl", "pl",
    "tr", "ko", "uk", "sv", "no", "da", "fi", "cs", "hu", "ro", "el", "he", "fa", "th", "vi",
})


def _alias_set(domain: str) -> set[str]:
    d = normalize_domain(domain)
    out = {d}
    out.update(DOMAIN_ALIASES.get(d, []))
    for k, vals in DOMAIN_ALIASES.items():
        if d in vals:
            out.add(k)
            out.update(vals)
    return out


def catalogue_domains(root: Path) -> set[str]:
    out: set[str] = set()
    for name in CATALOGUE_FILES:
        p = root / name
        if not p.exists():
            continue
        for s in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("sources", []) or []:
            dom = (s or {}).get("domain") if isinstance(s, dict) else None
            if dom:
                out.update(_alias_set(registrable_domain(str(dom)) or str(dom)))
    return out


def check_entry(e: dict, *, existing: set[str], seen: set[str]) -> str | None:
    """The reason an entry is refused, or None. PURE."""
    for k in REQUIRED:
        if k not in e or e[k] in ("", None):
            return f"missing {k}"
    if e.get("verified") is not True:
        return "verified is not true"
    dom = registrable_domain(str(e["domain"])) or ""
    if not dom or dom != str(e["domain"]).strip().lower():
        return "domain is not a bare registrable domain"
    if _alias_set(dom) & existing:
        return "already in a shipped catalogue"
    if dom in seen:
        return "duplicate within the batch"
    title_country = country_from_title(str(e["name"]))
    if title_country and title_country != str(e.get("country") or "").strip().lower():
        return f"name states country {title_country}, entry says {e.get('country') or 'none'}"
    for t in e.get("tags") or []:
        t = str(t)
        if t.startswith("via:"):
            return f"row-provenance tag {t}"
        if t in _LANGUAGE_CODES:
            return f"language code in tags: {t}"
        if len(t) > 3 and (normalize_country(t) or normalize_country(t.replace("-", " "))):
            return f"country name in tags: {t}"
    return None


def plan(batch: list[dict], *, existing: set[str]) -> tuple[list[dict], list[tuple[str, str]]]:
    accepted: list[dict] = []
    refused: list[tuple[str, str]] = []
    seen: set[str] = set()
    for e in batch:
        if not isinstance(e, dict):
            refused.append(("?", "not a mapping"))
            continue
        why = check_entry(e, existing=existing, seen=seen)
        if why:
            refused.append((str(e.get("domain") or "?"), why))
            continue
        seen.add(str(e["domain"]))
        accepted.append(e)
    return accepted, refused


def render(entries: list[dict]) -> str:
    """The exact text appended: one ``- name:`` block per entry, in the file's own style."""
    return yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, default_flow_style=False)


def splice(target: Path, entries: list[dict]) -> int:
    if not entries:
        return 0
    data = target.read_bytes()
    if not data.endswith(b"\n"):
        data += b"\n"
    target.write_bytes(data + render(entries).encode("utf-8"))
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--batch", required=True, type=Path, help="a sources: YAML produced by the pipeline")
    ap.add_argument("--target", type=Path, default=_ROOT / "configs" / "sources.yml")
    ap.add_argument("--apply", action="store_true", help="write; the default is a dry run")
    args = ap.parse_args(argv)
    batch = (yaml.safe_load(args.batch.read_text(encoding="utf-8")) or {}).get("sources") or []
    existing = catalogue_domains(_ROOT)
    accepted, refused = plan(batch, existing=existing)
    for dom, why in refused:
        print(f"refused  {dom}: {why}")
    print(f"batch {len(batch)} -> accepted {len(accepted)}, refused {len(refused)}")
    if args.apply:
        n = splice(args.target, accepted)
        print(f"appended {n} entr{'y' if n == 1 else 'ies'} to {args.target}")
    else:
        print("dry run -- pass --apply to append")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
