#!/usr/bin/env python3
"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Offline lint for the parallel-session law-catalog enrichment file
(``configs/legal_sources_generated.yml`` — contract + session prompt in
docs/design/LAW_SOURCES_ACQUISITION_2026-07-17.md). Run it BEFORE committing a
generated batch:

    python3 scripts/validate_legal_catalog.py [generated.yml] [--curated legal_sources.yml]

Checks: schema tag · required fields · ISO-2-shaped country codes (+ eu/int) ·
language-code shape · URL shape · in-file and vs-curated dedup · the mandatory
``verification`` block with a valid status · dated ``official_count`` (a count
without ``as_of``+``source_url`` is treated as estimated → ERROR: counts are only
ever read off the official page). Reports per-row errors + a verification-status
tally, and LISTS every ``lead`` (unverified) row for the maintainer's explicit
decision. Exit 0 = clean (leads may still be present — they are listed, not
auto-failed; the maintainer decides). Exit 1 = structural errors.

Calibrated against the first 8 real batches (2026-07-17):
- ``structured.api`` / ``structured.bulk`` accept a URL OR a short descriptive
  phrase — they are adapter-planning metadata, not fetch targets.
- an ``http://`` URL in a fetch-target field is a WARNING, not an error: an
  http-only official portal is a real thing in some jurisdictions, and silently
  rewriting it to https:// would fabricate a capability. It is listed for the
  maintainer; the fetcher never silently upgrades or downgrades.
- ``domain`` may be omitted ONLY on a ``lead`` row — the honest-gap record for a
  jurisdiction with no working portal (e.g. Yemen). The app-side loader already
  skips domain-less rows, so a gap record can never become a Source.
- the in-file dedup key is ``(domain, kind, country)``: one host legitimately
  carries two roles (a consolidated codes portal AND the gazette), and a
  multi-country platform (PacLII) carries one role for several jurisdictions.
  Registration must later collapse them onto the one Source row (Source.domain
  is unique).

Never edits anything — it proposes; the human vets (the house review gate).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guidance, not logic
    sys.exit("pyyaml is required: pip install pyyaml")

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GENERATED = _ROOT / "configs" / "legal_sources_generated.yml"
DEFAULT_CURATED = _ROOT / "configs" / "legal_sources.yml"

SCHEMA = "oo-legal-catalog-gen-1"
COUNTRY_RE = re.compile(r"^[a-z]{2}$")
LANG_RE = re.compile(r"^[a-z]{2,3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
VERIFICATION_STATUSES = ("fetched", "search-verified", "lead")
LEGAL_SYSTEMS_RE = re.compile(r"^(civil_law|common_law|mixed(:.+)?|religious|customary)$")
SOURCE_TYPES = ("legal", "ip", "case_law", "gazette")
SPECIAL_COUNTRIES = ("eu", "int")


def _err(errors: list[str], where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def _check_url(
    errors: list[str],
    warnings: list[str],
    where: str,
    field: str,
    value,
    *,
    allow_text: bool = False,
) -> None:
    if value in (None, "", "none"):
        return
    if not isinstance(value, str):
        _err(errors, where, f"{field} must be a string (got {value!r})")
        return
    if value.startswith("https://"):
        return
    if value.startswith("http://"):
        warnings.append(
            f"{where}: {field} is http-only ({value!r}) — kept as recorded; confirm "
            "https is genuinely unavailable before any fetch (never silently upgraded)"
        )
        return
    if allow_text:
        return  # descriptive adapter-planning metadata, not a fetch target
    _err(errors, where, f"{field} must be an https:// URL (got {value!r})")


def validate(generated: dict, curated: dict) -> dict:
    """Pure validation. Returns {errors, warnings, leads, tally, sources, documents}."""
    errors: list[str] = []
    warnings: list[str] = []
    leads: list[str] = []
    tally = dict.fromkeys(VERIFICATION_STATUSES, 0)

    if generated.get("schema") != SCHEMA:
        _err(errors, "top-level", f"schema must be {SCHEMA!r} (got {generated.get('schema')!r})")
    if not DATE_RE.match(str(generated.get("as_of", ""))):
        _err(errors, "top-level", "as_of must be YYYY-MM or YYYY-MM-DD")

    curated_domains = {s.get("domain") for s in curated.get("sources", [])}
    curated_docs = {
        (d.get("jurisdiction"), d.get("url")) for d in curated.get("documents", [])
    }
    seen_domains: set[str] = set()

    seen_domain_kinds: set[tuple] = set()
    for i, s in enumerate(generated.get("sources", []) or []):
        where = f"sources[{i}] ({s.get('domain') or s.get('name', '?')})"
        ver = s.get("verification") or {}
        status = ver.get("status")
        required = ["name", "country", "languages", "source_type", "verification"]
        if status != "lead":
            required.append("domain")  # a domain-less row is only ever an honest-gap lead
        for field in required:
            if not s.get(field):
                _err(errors, where, f"missing required field {field!r}")
        country = s.get("country", "")
        if country not in SPECIAL_COUNTRIES and not COUNTRY_RE.match(str(country)):
            _err(errors, where, f"country must be ISO-2 lowercase or eu/int (got {country!r})")
        for lang in s.get("languages") or []:
            if not LANG_RE.match(str(lang)):
                _err(errors, where, f"language code {lang!r} is not ISO-shaped")
        if s.get("source_type") and s["source_type"] not in SOURCE_TYPES:
            _err(errors, where, f"source_type must be one of {SOURCE_TYPES}")
        ls = s.get("legal_system")
        if ls and not LEGAL_SYSTEMS_RE.match(str(ls)):
            _err(errors, where, f"legal_system {ls!r} is not in the vocabulary")
        for field in ("enumeration_url", "gazette_feed"):
            _check_url(errors, warnings, where, field, s.get(field))
        st = s.get("structured") or {}
        for field in ("api", "bulk"):
            _check_url(errors, warnings, where, f"structured.{field}", st.get(field),
                       allow_text=True)
        oc = s.get("official_count")
        if oc is not None:
            if not isinstance(oc, dict) or not isinstance(oc.get("value"), int):
                _err(errors, where, "official_count must be {value:int, unit, as_of, source_url}")
            else:
                if not DATE_RE.match(str(oc.get("as_of", ""))):
                    _err(errors, where, "official_count.as_of missing/undated — a count is only "
                                        "ever READ OFF the official page, never estimated")
                _check_url(errors, warnings, where, "official_count.source_url",
                           oc.get("source_url"))
        if status not in VERIFICATION_STATUSES:
            _err(errors, where, f"verification.status must be one of {VERIFICATION_STATUSES}")
        else:
            tally[status] += 1
            if status == "lead":
                leads.append(where)
        if status in ("fetched", "search-verified") and not ver.get("retrieved_at"):
            _err(errors, where, "a verified row must carry verification.retrieved_at")
        dom = s.get("domain")
        if dom:
            key = (dom, s.get("kind"), country)
            if key in seen_domain_kinds:
                _err(errors, where, "duplicate (domain, kind, country) within the generated file "
                                    "(one host may carry two ROLES — codes portal + gazette — or "
                                    "one role for SEVERAL jurisdictions — PacLII — but never two "
                                    "rows of the same role for the same jurisdiction)")
            seen_domain_kinds.add(key)
            seen_domains.add(dom)
            if dom in curated_domains:
                _err(errors, where, "domain already in the CURATED catalog (curated wins — "
                                    "remove this row, or move a correction INTO the curated file)")

    seen_docs: set[tuple] = set()
    for i, d in enumerate(generated.get("documents", []) or []):
        where = f"documents[{i}] ({d.get('url', '?')})"
        for field in ("jurisdiction", "title", "url", "verification"):
            if not d.get(field):
                _err(errors, where, f"missing required field {field!r}")
        _check_url(errors, warnings, where, "url", d.get("url"))
        status = (d.get("verification") or {}).get("status")
        if status not in VERIFICATION_STATUSES:
            _err(errors, where, f"verification.status must be one of {VERIFICATION_STATUSES}")
        elif status == "lead":
            leads.append(where)
        dkey = (d.get("jurisdiction"), d.get("url"))
        if dkey in seen_docs:
            _err(errors, where, "duplicate (jurisdiction, url) within the generated file")
        seen_docs.add(dkey)
        if dkey in curated_docs:
            _err(errors, where, "document already in the CURATED catalog (curated wins)")

    return {
        "errors": errors,
        "warnings": warnings,
        "leads": leads,
        "tally": tally,
        "sources": len(generated.get("sources", []) or []),
        "documents": len(generated.get("documents", []) or []),
    }


def main(argv: list[str]) -> int:
    gen_path = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") else DEFAULT_GENERATED
    curated_path = DEFAULT_CURATED
    if "--curated" in argv:
        curated_path = Path(argv[argv.index("--curated") + 1])
    if not gen_path.exists():
        print(f"nothing to validate: {gen_path} does not exist")
        return 0
    generated = yaml.safe_load(gen_path.read_text(encoding="utf-8")) or {}
    curated = yaml.safe_load(curated_path.read_text(encoding="utf-8")) or {} if curated_path.exists() else {}
    report = validate(generated, curated)
    print(f"sources: {report['sources']} · documents: {report['documents']} · "
          f"verification: {report['tally']}")
    if report["leads"]:
        print(f"\nUNVERIFIED LEADS ({len(report['leads'])}) — maintainer decision needed "
              f"(a lead was never loaded by the research session):")
        for line in report["leads"]:
            print(f"  ? {line}")
    if report["warnings"]:
        print(f"\nWARNINGS ({len(report['warnings'])}) — recorded as found, review before fetch:")
        for line in report["warnings"]:
            print(f"  ! {line}")
    if report["errors"]:
        print(f"\nERRORS ({len(report['errors'])}):")
        for line in report["errors"]:
            print(f"  ✗ {line}")
        return 1
    print("\nstructurally clean" + (" (leads above still need vetting)" if report["leads"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
