"""
CSV import / export for the source catalog (defined, documented columns).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A simple, round-trippable format so an operator can bulk-add or back up sources
from a spreadsheet. Parsing is forgiving about column order and header case,
strict about the essentials (a row needs a name and a usable domain), and
reports bad rows rather than dropping them silently (PRODUCT_SYNTHESIS §3.7).
``upsert_sources`` creates new sources and updates existing ones (matched by
domain), so re-importing an edited export is safe.
"""

from __future__ import annotations

import csv
import io

from src.catalog.countries import normalize_country
from src.catalog.normalize import registrable_domain

# The defined column set (export order). Only name + domain are required on import.
EXPORT_COLUMNS: list[str] = [
    "name",
    "domain",
    "rss_url",
    "source_type",
    "country",
    "language",
    "region",
    "tags",
    "priority",
    "rate_limit_ms",
    "enabled",
    "reliability_score",
]

# Integer columns and their (lo, hi) clamps; out-of-range -> reported as an error.
_INT_FIELDS = {
    "priority": (1, 3),
    "rate_limit_ms": (100, 600000),
    "reliability_score": (1, 10),
}
_TRUE = {"1", "true", "yes", "y", "on", "enabled"}
_FALSE = {"0", "false", "no", "n", "off", "disabled"}


def write_csv(rows: list[dict]) -> str:
    """Serialise source rows (dicts keyed by EXPORT_COLUMNS) to CSV text."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    # Neutralize spreadsheet formula injection in every cell (S-004).
    from src.utils.security import csv_safe_cell

    for r in rows:
        writer.writerow({c: csv_safe_cell(r.get(c)) for c in EXPORT_COLUMNS})
    return buf.getvalue()


def template_csv() -> str:
    """A header row plus two example rows documenting the expected format."""
    examples = [
        {
            "name": "Example News",
            "domain": "example.com",
            "rss_url": "https://example.com/feed.xml",
            "source_type": "news",
            "country": "us",
            "language": "en",
            "region": "north-america",
            "tags": "politics,world",
            "priority": 2,
            "rate_limit_ms": 2000,
            "enabled": "true",
            "reliability_score": 7,
        },
        {
            "name": "Example Exchange",
            "domain": "exchange.example",
            "rss_url": "",
            "source_type": "stock_exchange",
            "country": "gb",
            "language": "en",
            "region": "europe",
            "tags": "markets,equities",
            "priority": 2,
            "rate_limit_ms": 3000,
            "enabled": "true",
            "reliability_score": 8,
        },
    ]
    return write_csv(examples)


def parse_sources_csv(text: str) -> tuple[list[dict], list[str]]:
    """Parse CSV text into validated source-kwargs dicts. Returns (rows, errors).

    Required: ``name`` and a usable ``domain`` (a bare domain or a full URL — it is
    reduced to a registrable host). Unknown columns are ignored; malformed rows are
    reported with their line number, never silently dropped.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return [], ["empty file or missing header row"]

    # Case-insensitive header -> canonical column.
    colmap = {raw: raw.strip().lower() for raw in reader.fieldnames}
    known = set(EXPORT_COLUMNS)

    rows: list[dict] = []
    errors: list[str] = []
    for i, raw_row in enumerate(reader, start=2):  # row 1 is the header
        rec = {
            colmap[k]: (v.strip() if isinstance(v, str) else v)
            for k, v in raw_row.items()
            if colmap.get(k) in known
        }
        name = (rec.get("name") or "").strip()
        domain = registrable_domain(rec.get("domain"))
        if not name or not domain:
            errors.append(f"row {i}: missing name or usable domain")
            continue

        out: dict = {"name": name, "domain": domain}
        for opt in ("rss_url", "source_type", "country", "language", "region", "tags"):
            val = (rec.get(opt) or "").strip()
            if val:
                out[opt] = val.lower() if opt in ("country", "language") else val
        # Country: canonical lowercase ISO-2 via the one conversion layer —
        # accepts codes, full names and slugs; unrecognisable values are dropped
        # (never stored as junk).
        if "country" in out:
            cc = normalize_country(out["country"])
            if cc:
                out["country"] = cc
            else:
                out.pop("country")

        bad = False
        for field, (lo, hi) in _INT_FIELDS.items():
            val = (rec.get(field) or "").strip()
            if not val:
                continue
            try:
                n = int(float(val))
            except ValueError:
                errors.append(f"row {i}: {field} is not a number ({val!r})")
                bad = True
                break
            if not (lo <= n <= hi):
                errors.append(f"row {i}: {field} {n} out of range {lo}-{hi}")
                bad = True
                break
            out[field] = n
        if bad:
            continue

        enabled = (rec.get("enabled") or "").strip().lower()
        if enabled in _TRUE:
            out["enabled"] = True
        elif enabled in _FALSE:
            out["enabled"] = False
        elif enabled:
            errors.append(f"row {i}: enabled not understood ({enabled!r})")
            continue

        rows.append(out)
    return rows, errors


def upsert_sources(session, rows: list[dict]) -> dict:
    """Create new sources and update existing ones (matched by domain).

    Returns ``{created, updated, skipped, errors}``. A row whose domain already
    exists updates only the fields present in that row.
    """
    from src.database.models import Source

    created = updated = 0
    errors: list[str] = []
    existing = {d: sid for sid, d in session.query(Source.id, Source.domain).all()}

    for row in rows:
        domain = row["domain"]
        try:
            if domain in existing:
                src = session.query(Source).filter_by(domain=domain).first()
                for k, v in row.items():
                    if k != "domain":
                        setattr(src, k, v)
                updated += 1
            else:
                session.add(Source(**row))
                existing[domain] = -1
                created += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the batch
            session.rollback()
            errors.append(f"{domain}: {exc}")
            continue
    session.commit()
    return {"created": created, "updated": updated, "skipped": len(errors), "errors": errors}
