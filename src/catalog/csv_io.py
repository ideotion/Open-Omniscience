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
from src.catalog.languages import language_storage_code
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

#: Q313 (S05-02 S2): the export carries ONE country column -- `country`, alpha-3. The
#: transitional second column (`country_iso3`, 0.4) and the old alpha-2 value are gone
#: from the OUTPUT; `parse_sources_csv` still reads `country_iso3` on the way IN, forever,
#: because a sheet exported by 0.4 must import (the same promise the restore path makes
#: to old backups). A file carrying both spellings that disagree is refused by name.
LEGACY_IMPORT_COLUMNS: tuple[str, ...] = ("country_iso3",)

#: Columns an IMPORT reads: what the export writes, plus the legacy column above.
IMPORT_COLUMNS: list[str] = list(EXPORT_COLUMNS)

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
            "country": "USA",
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
    # The TEMPLATE documents what an import READS: one `country` column, alpha-3 (an
    # alpha-2, a name or a slug is read too). The legacy `country_iso3` is not offered.
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=IMPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    from src.utils.security import csv_safe_cell

    for r in examples:
        writer.writerow({c: csv_safe_cell(r.get(c)) for c in IMPORT_COLUMNS})
    return buf.getvalue()


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
    # The LEGACY `country_iso3` is read too (a sheet exported by 0.4 carries it) -- not
    # to be stored, but so a row where the two country columns DISAGREE can be refused
    # rather than silently resolved.
    known = set(EXPORT_COLUMNS) | set(LEGACY_IMPORT_COLUMNS)

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
        # Language: accept BOTH forms, the same discipline the country columns got
        # (S04-05 S8). The app DISPLAYS 639-2/T (`fra`), so an operator exporting,
        # editing and re-importing a sheet types back what they were shown --
        # `language_storage_code` turns that into the 639-1 the column stores, and
        # a 639-1 typed directly passes through it unchanged. A value it cannot
        # place (`pcm`, `yue`, `tet` have no 639-1 at all) is KEPT AS TYPED rather
        # than dropped: the column is free text for exactly those, and silently
        # discarding a real language the operator stated would be the worse answer.
        if "language" in out:
            out["language"] = language_storage_code(out["language"]) or out["language"]
        # Country: canonical lowercase ISO-2 via the one conversion layer —
        # accepts codes, full names and slugs; unrecognisable values are dropped
        # (never stored as junk).
        iso3_raw = (rec.get("country_iso3") or "").strip()
        if "country" in out:
            cc = normalize_country(out["country"])
            if cc:
                out["country"] = cc
            else:
                out.pop("country")
        # NOT an `elif`: the branch above can DROP an unrecognisable `country`, and an
        # `elif` would then throw away a perfectly readable `country_iso3` in the same
        # row -- leaving the source with no country at all although the operator stated
        # one in a form we understand. So the fall-back is keyed on the RESULT ("is
        # there a country now?"), never on which column happened to be present.
        if "country" not in out and iso3_raw:
            # Through `normalize_country`: it reads the alpha-3 forms AND Q303's four
            # (`EUU`, `INT`, `XKX`, `ANT`), which `to_iso2` refuses because they are not ISO
            # countries -- values the 0.4 export itself wrote -- and both fail closed on an
            # aggregate or an unknown code.
            cc = normalize_country(iso3_raw)
            if cc:
                out["country"] = cc
        if iso3_raw and "country" in out and normalize_country(out["country"]) != normalize_country(iso3_raw):
            # TWO STATEMENTS OF ONE FACT THAT DISAGREE. Refused by name: picking
            # `country` would discard an edit the operator made in the other column,
            # and picking `country_iso3` would discard the one they made here. Compared
            # through normalize_country on BOTH sides, so `fr` vs `FRA` is agreement, not a
            # conflict -- and so `eu` vs `INT` is NOT: an unreadable side is None, and
            # `country` is readable here, so a column that cannot be read never reads as
            # agreement (the old to_iso3 pair compared None with None for the four non-ISO
            # codes and let the operator's edit vanish).
            errors.append(
                f"row {i}: country {out['country']!r} and country_iso3 {iso3_raw!r} "
                "disagree; correct one of them (they are the same fact in two forms)"
            )
            continue

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

    Each row runs inside its own SAVEPOINT (``begin_nested``), so a mid-batch
    failure undoes ONLY that row -- rows staged earlier in the same import survive
    (finding OO-D7-001). A bare ``session.rollback()`` previously rolled back the
    whole commit window, silently discarding every good row that preceded the bad
    one while keeping the rows that followed it.
    """
    from src.analytics.managed import is_unmanaged
    from src.database.models import Source

    created = updated = 0
    errors: list[str] = []
    existing = {d: sid for sid, d in session.query(Source.id, Source.domain).all()}

    for row in rows:
        domain = row["domain"]
        is_update = domain in existing
        try:
            # begin_nested() issues a SAVEPOINT and flushes at block exit; an error
            # there auto-rolls-back to the savepoint (this row only) and re-raises.
            with session.begin_nested():
                if is_update:
                    src = session.query(Source).filter_by(domain=domain).first()
                    for k, v in row.items():
                        if k != "domain":
                            setattr(src, k, v)
                else:
                    # Language gating (maintainer 2026-06-18): a NEW source in a
                    # language the keyword engine cannot manage seeds DISABLED by
                    # default (kept, re-enablable) so the app never accumulates
                    # un-analysable junk. An explicit ``enabled`` in the row always
                    # wins (curation), and an unknown language stays enabled (we
                    # never disable what we cannot classify). Existing sources are
                    # untouched — re-seeding never flips the operator's choice.
                    if "enabled" not in row and is_unmanaged(row.get("language")):
                        row = {**row, "enabled": False}
                    session.add(Source(**row))
            # The savepoint committed cleanly -> count it only now (so a row that
            # failed at flush is never miscounted as created/updated).
            if is_update:
                updated += 1
            else:
                existing[domain] = -1
                created += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the batch
            errors.append(f"{domain}: {exc}")
            continue
    session.commit()
    return {"created": created, "updated": updated, "skipped": len(errors), "errors": errors}
