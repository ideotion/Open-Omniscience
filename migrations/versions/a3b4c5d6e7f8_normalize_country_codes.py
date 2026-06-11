"""normalize country values to lowercase ISO-2 + remove the fabricated US default

The de-US-centring fix (0.09 KEY POINT). Three real defects, one migration:

1. MIXED ENCODINGS -- ``sources.country`` (String(2), never enforced by SQLite)
   accumulated three styles: catalog slugs ("united-states"), uppercase codes
   ("US"), lowercase codes ("us"). Every country column is canonicalised to
   lowercase ISO 3166-1 alpha-2 through the one conversion layer
   (src/catalog/countries.py). Values that cannot be recognised are LEFT AS-IS
   (they surface in the coverage report's extra_codes -- degrade loudly, never
   silently discard).

2. FABRICATED US BIAS -- ``Source.country`` had ``default="US"``: every source
   created without an explicit country was silently labelled American (the
   live-test "US=1553" inflation). For rows carrying that default the value was
   never asserted by anyone, so it is re-derived honestly: the shipped catalog's
   explicit country for the domain, else the domain's ccTLD, else NULL
   ("unknown" is the truthful answer).

   STATED TRADE-OFF: a 'us' value asserted by a user (only possible via CSV
   import; the create/update API never accepted a country) is indistinguishable
   in the database from the silent default, so on a non-US-inferable domain it
   is ALSO cleared. The asymmetry justifies it -- the default fabricated values
   by the thousand, explicit CSV 'us' on a gTLD domain is rare and restorable
   by re-importing the CSV (imports normalise and stick from now on).

3. CORRUPTED MENTION GEOGRAPHY -- ``keyword_mentions.country`` was written as
   ``source.country[:2].lower()``; slug values were truncated into WRONG codes
   ("china" -> "ch" = Switzerland, "germany" -> "ge" = Georgia). The column is
   by definition a denormalisation of the source country, so it is rebuilt
   wholesale from the (now corrected) sources.

Revision ID: a3b4c5d6e7f8
Revises: c9d8e7f6a5b4
Create Date: 2026-06-11 00:00:00.000000
"""

import logging
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

# (table, column) pairs that hold a country value. keyword_mentions is handled
# separately (phase C rebuilds it from sources; its truncated values can look
# like VALID codes of the wrong country, so per-value normalisation cannot fix it).
_COUNTRY_COLUMNS = (
    ("sources", "country"),
    ("source_metadata", "country"),
    ("articles", "country"),
    ("external_sources", "country"),
)


def _plan_updates(values: list[str | None]) -> dict[str, str]:
    """Map each distinct stored value to its canonical form (only where it changes).

    Unrecognisable values are deliberately absent from the plan: they stay in the
    database untouched and visible (the coverage report lists them) rather than
    being guessed at or silently dropped.
    """
    from src.catalog.countries import normalize_country

    plan: dict[str, str] = {}
    for v in values:
        if not v:
            continue
        canonical = normalize_country(v)
        if canonical and canonical != v:
            plan[v] = canonical
    return plan


def _catalog_domain_countries() -> dict[str, str]:
    """domain -> canonical country for every shipped-catalog entry that states one."""
    from src.catalog.countries import normalize_country
    from src.ingest import seed_sources as seeds

    out: dict[str, str] = {}
    for path in (
        seeds.DEFAULT_SOURCES_PATH,
        seeds.MARKETS_SOURCES_PATH,
        seeds.WORLD_SOURCES_PATH,
        seeds.SPECTRUM_SOURCES_PATH,
        seeds.LEGAL_SOURCES_PATH,
    ):
        try:
            if not path.exists():
                continue
            for s in seeds.load_sources_from_yaml(path):
                cc = normalize_country(str(s.get("country") or ""))
                if cc and s.get("domain"):
                    out.setdefault(s["domain"], cc)
        except Exception:  # noqa: BLE001 -- a missing/odd catalog must not abort
            log.warning("country migration: could not read catalog %s", path, exc_info=True)
    return out


def upgrade() -> None:
    bind = op.get_bind()

    # --- Phase A: canonicalise encodings, column by column ------------------
    for table, col in _COUNTRY_COLUMNS:
        rows = bind.execute(
            text(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL")  # noqa: S608
        ).fetchall()
        plan = _plan_updates([r[0] for r in rows])
        for old, new in plan.items():
            bind.execute(
                text(f"UPDATE {table} SET {col} = :new WHERE {col} = :old"),  # noqa: S608
                {"new": new, "old": old},
            )
        if plan:
            log.info("country migration: %s.%s -- %d distinct values canonicalised",
                     table, col, len(plan))

    # --- Phase B: undo the fabricated default="US" on sources ---------------
    # A 'us' value may be (a) asserted by the shipped catalog, (b) implied by a
    # reliable ccTLD, or (c) the old silent default. (a) and (b) re-derive to
    # 'us' and keep it; (c) re-derives to the catalog/ccTLD answer or to NULL.
    try:
        from src.catalog.cctld import infer_country

        catalog = _catalog_domain_countries()
        us_rows = bind.execute(
            text("SELECT id, domain FROM sources WHERE country = 'us'")
        ).fetchall()
        rederived = cleared = 0
        for sid, domain in us_rows:
            cc = catalog.get(domain or "") or infer_country(domain)
            if cc != "us":
                bind.execute(
                    text("UPDATE sources SET country = :cc WHERE id = :sid"),
                    {"cc": cc, "sid": sid},
                )
                if cc:
                    rederived += 1
                else:
                    cleared += 1
        log.info(
            "country migration: %d 'us' sources checked -- %d re-derived to another "
            "country, %d cleared to NULL (value was the old default, not an assertion)",
            len(us_rows), rederived, cleared,
        )
    except Exception:  # noqa: BLE001 -- phase B is an enhancement over phase A
        log.warning(
            "country migration: default-US cleanup skipped (catalog/ccTLD unavailable); "
            "encodings are canonicalised but the US inflation remains -- re-run "
            "`alembic upgrade head` from a full install to finish",
            exc_info=True,
        )

    # --- Phase C: rebuild the denormalised mention geography ----------------
    op.execute(
        text(
            "UPDATE keyword_mentions SET country = ("
            " SELECT s.country FROM articles a JOIN sources s ON s.id = a.source_id"
            " WHERE a.id = keyword_mentions.article_id)"
        )
    )


def downgrade() -> None:
    # One-way by design: the previous state was a defect (mixed encodings, a
    # fabricated default, truncation-corrupted codes). Recreating it would be
    # restoring a bug, and the discarded variants carry no information.
    pass
