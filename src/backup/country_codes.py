"""The ONE registry of country-bearing columns, and the restore-path normaliser.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (Q310 = a, gate row K). The restore merge keys on the VALUE, not on
an id: ``_merge_sources`` adopts ``country`` as an adoptable column and
``_merge_statistics`` joins ``COALESCE(t.country,'') = COALESCE(i.country,'')``. An
old backup's ``fr`` and a migrated ``FRA`` are unequal strings, so an unnormalised
restore across the alpha-2 -> alpha-3 move (Q301 = c, storage half in 0.5) would
DUPLICATE every affected row instead of deduplicating it. The fix is to normalise the
INCOMING staged copy to the store's canonical form BEFORE any of those joins run.

TWO CONSUMERS, ONE REGISTRY. :func:`normalise_staged_country_codes` (the merge step)
and the duplicate-key scan diagnostic both read :data:`COUNTRY_COLUMNS`. A second copy
is how two surfaces come to disagree about one quantity -- the same principle S04-13's
own ruling (Q1012 = a) was built on, one subsystem over.

WHAT IT REFUSES TO DO, and why each refusal is the safe direction:

* **An unrecognised value is left EXACTLY as it is.** ``to_iso2``/``to_iso3`` fail
  closed and answer ``None`` for junk, for a statistical aggregate (``WLD``, ``HIC``,
  ``EUU``) and for the app's own non-ISO jurisdictions (``uk``, ``int``) -- measured,
  not assumed. Writing that ``None`` back would DELETE the operator's data to make a
  code table happy. Unchanged loses nothing, and the scan reports the value so a human
  can see it.
* **NULL stays NULL.** An absent country is a gap; inventing a value for it is the
  fabrication this project refuses everywhere else.
* **A collision is REPORTED, never fatal.** Several of these columns sit inside UNIQUE
  constraints (``ix_lawdoc_jurisdiction_url``), so converting ``fr`` and ``FRA`` to one
  form can collide two rows that the incoming corpus itself held separately. Each
  per-value UPDATE runs in its own SAVEPOINT: a collision rolls back that one value and
  is published under ``collisions``, leaving every other value converted. Aborting the
  whole restore over a duplicate inside somebody else's corpus would strand them.

WHAT IS EXEMPT, and why it is not an oversight (see :data:`COUNTRY_COLUMNS_EXEMPT`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Literal

from src.catalog.countries import to_iso2, to_iso3

#: The store's canonical country form. **ONE constant, ONE read** (``_converter``):
#: the 0.5 storage half (Q301 = c, brief ``S05-02``) flips this literal and nothing
#: else in this module, and both settings are pinned by tests so the flip cannot
#: silently change what the normaliser claims to do. 0.4 is alpha-2 because that is
#: what the store holds today; the DIRECTION-AGNOSTIC part is that either form is
#: ACCEPTED on the way in whatever the target is.
CANONICAL_COUNTRY_FORM: Literal["alpha2", "alpha3"] = "alpha2"

#: table -> the columns on it that hold a country (or country-like) code, for the
#: tables the merge actually COPIES. A table nothing copies cannot contribute a
#: duplicate to the local corpus, so normalising it would be work with no subject --
#: but promoting such a table to a merge handler must bring it here. Enforced against
#: the live model metadata, never against this list's own good intentions, by
#: ``tests/test_country_code_normaliser.py``'s
#: ``test_every_country_bearing_column_of_a_MERGED_table_is_registered_or_exempt``.
COUNTRY_COLUMNS: dict[str, tuple[str, ...]] = {
    "sources": ("country",),
    "source_metadata": ("country",),
    "articles": ("country",),
    "external_sources": ("country",),
    "keyword_mentions": ("country",),
    # Both columns, and `jurisdiction` is the one the brief names explicitly. In 0.4
    # every shipped jurisdiction value normalises to itself (`fr` -> `fr`) or is
    # refused by the converter and left alone (`uk`, `eu`, `int` -- measured), so this
    # entry is a no-op today and live the moment the target flips.
    "law_documents": ("jurisdiction", "country"),
}

#: The country-bearing columns deliberately NOT normalised, each with the reason.
#: Both are the PUBLISHER's vocabulary replayed verbatim into an external contract,
#: which Q311 rules stays as it is; both also sit inside a UNIQUE constraint, so
#: rewriting them would change a key rather than a display value.
COUNTRY_COLUMNS_EXEMPT: dict[str, str] = {
    "stat_figures.ref_area": (
        "the area code AS PUBLISHED by the statistics agency, stored alpha-3 by "
        "convention (src/api/governments.py reads it back in that form) and part of "
        "uq_stat_figure_vintage -- normalising it to alpha-2 would corrupt the "
        "Governments surface and split one observation's vintages in two"
    ),
    "stat_subscriptions.country": (
        "the World Bank API's own `country` PARAMETER, replayed verbatim on the next "
        "fetch and carrying non-codes such as the literal 'all' "
        "(src/api/governments.py:614); it is part of uq_stat_subscription, so "
        "rewriting it would make a re-subscribe duplicate instead of dedupe (Q311: "
        "external contracts stay alpha-2 behind converters). EXEMPT FROM THE REWRITE, "
        "NOT FROM THE PROBLEM: the value arrives through a free-text box that folds "
        "neither case nor form, so `_merge_statistics`' subscription key compares it "
        "case-insensitively -- the comparison is merge.py's own business and rewrites "
        "nothing the World Bank will ever be sent"
    ),
    "article_mentioned_places.country": (
        "purely derived and in _MERGE_NOT_CARRIED -- no handler copies it, so it can "
        "never reach a value-keyed join; index_article rebuilds it after the swap"
    ),
}


def _converter() -> Callable[[str | None], str | None]:
    """The single read of :data:`CANONICAL_COUNTRY_FORM`.

    Read once, here, so the verdict AND every sentence about it come from one place --
    a second read is a second place to flip. Both converters accept EITHER input form
    and both fail closed, which is what makes the normaliser direction-agnostic rather
    than a one-way alpha-2 -> alpha-3 migration.
    """
    return to_iso3 if CANONICAL_COUNTRY_FORM == "alpha3" else to_iso2


def canonical_country(value: str | None) -> str | None:
    """The canonical form of ``value``, or ``None`` when it is not a country code.

    ``None`` here means "this module has nothing to say about that value" -- it is
    never written back. Callers leave such a value exactly as they found it.
    """
    return _converter()(value)


def _table_exists(con: sqlite3.Connection, schema: str, table: str) -> bool:
    row = con.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=? LIMIT 1",  # noqa: S608  # nosec B608 - `schema` is a module-internal literal alias ("inc"/"main"), never input
        (table,),
    ).fetchone()
    return row is not None


def _columns_of(con: sqlite3.Connection, schema: str, table: str) -> set[str]:
    return {
        r[1]
        for r in con.execute(f'PRAGMA {schema}.table_info("{table}")').fetchall()  # noqa: S608  # nosec B608 - `schema` is a module-internal literal; `table` comes from COUNTRY_COLUMNS, a fixed map
    }


def _live_corpus_in_target_form(con: sqlite3.Connection) -> dict:
    """Read-only: does the LIVE corpus already store the form this normaliser targets?

    Answers with counts, never a verdict. ``off_form`` is the number of distinct stored
    spellings in ``main`` that the converter WOULD rewrite -- so 0 means the live corpus
    is already in the target form and a restore cannot create a form mismatch, and any
    other number is the size of the gap. Values the converter refuses are not counted
    either way: they have no canonical form, so they are not evidence about which form
    the corpus uses.
    """
    off: dict[str, list[str]] = {}
    checked = 0
    for table in sorted(COUNTRY_COLUMNS):
        if not _table_exists(con, "main", table):
            continue
        present = _columns_of(con, "main", table)
        for column in COUNTRY_COLUMNS[table]:
            if column not in present:
                continue
            checked += 1
            try:
                rows = con.execute(
                    f'SELECT DISTINCT "{column}" FROM main."{table}" '  # noqa: S608  # nosec B608 - identifiers from the fixed COUNTRY_COLUMNS map
                    f'WHERE "{column}" IS NOT NULL AND "{column}" <> \'\''
                ).fetchall()
            except Exception:  # noqa: BLE001 - a read-only measurement never fails a restore
                continue
            for (value,) in rows:
                target = canonical_country(value)
                if target is not None and target != value:
                    off.setdefault(f"{table}.{column}", []).append(str(value))
    out: dict = {
        "columns_checked": checked,
        "off_form": sum(len(v) for v in off.values()),
        "method": (
            "distinct stored spellings in the LIVE corpus that this normaliser would "
            f"rewrite to {CANONICAL_COUNTRY_FORM}. 0 = the live corpus is already in "
            "the target form. Codes with no canonical form are not counted: they say "
            "nothing about which form the corpus uses"
        ),
    }
    if off:
        out["spellings"] = {k: sorted(set(v)) for k, v in sorted(off.items())}
        out["caveat"] = (
            "the live corpus is not fully in the target form, so a restore normalised "
            "toward that form can miss a value-keyed join and land a duplicate. This is "
            "the ordering S05-02 owns: rewrite the live corpus BEFORE flipping "
            "CANONICAL_COUNTRY_FORM, never after"
        )
    return out


def _convert_row_by_row(
    con: sqlite3.Connection, schema: str, table: str, column: str, value: str, target: str
) -> tuple[int, list[str]]:
    """Retry one spelling row at a time after the bulk UPDATE hit a constraint.

    The rare path, and the reason it exists: SQLite's default ON CONFLICT ABORT undoes
    the ENTIRE statement, so one colliding pair silently reverts every other row that
    happened to share that spelling -- including rows with no conflict of their own.
    Those rows then miss their own value-keyed join downstream and land as duplicates,
    which is the exact failure this whole module exists to prevent.

    Each row gets its OWN savepoint, so a row that genuinely cannot be converted is
    rolled back alone. Returns (rows converted, the distinct collision reasons), and the
    reasons are what the caller reports -- a collision is never swallowed.
    """
    ids = [
        r[0]
        for r in con.execute(
            f'SELECT rowid FROM {schema}."{table}" WHERE "{column}" = ?',  # noqa: S608  # nosec B608 - identifiers from the fixed COUNTRY_COLUMNS map; the VALUE is bound
            (value,),
        ).fetchall()
    ]
    done = 0
    reasons: list[str] = []
    for rid in ids:
        con.execute("SAVEPOINT oo_country_norm_row")
        try:
            con.execute(
                f'UPDATE {schema}."{table}" SET "{column}" = ? WHERE rowid = ?',  # noqa: S608  # nosec B608 - identifiers from the fixed COUNTRY_COLUMNS map; the VALUES are bound
                (target, rid),
            )
        except Exception as exc:  # noqa: BLE001 - one row's collision is not the restore's
            con.execute("ROLLBACK TO oo_country_norm_row")
            con.execute("RELEASE oo_country_norm_row")
            if str(exc) not in reasons:
                reasons.append(str(exc))
            continue
        con.execute("RELEASE oo_country_norm_row")
        done += 1
    return done, reasons


def normalise_staged_country_codes(con: sqlite3.Connection, *, schema: str = "inc") -> dict:
    """Normalise every registered country column of the ATTACHED staged corpus.

    Runs as the FIRST merge step, before any handler joins on one of these values.
    Writes only to ``schema`` (the disposable staged copy), never to the working copy
    and never to the live corpus.

    NO ``should_stop`` PARAMETER, deliberately: the merge wraps every step in
    ``_step_watch``, whose VDBE progress handler interrupts the running statement and
    raises -- the same stop mechanism every other step relies on. A second stop channel
    that no caller passes would be a control nothing exercises.

    Returns a report block: what was converted, what was left alone because the
    converter refused it, and what collided with a unique constraint. Every one of the
    three is a fact a reader needs -- "nothing changed" and "we could not change it"
    are different answers, and only a report tells them apart.
    """
    converted: dict[str, int] = {}
    refused: dict[str, list[str]] = {}
    collisions: list[dict] = []
    scanned = 0

    for table in sorted(COUNTRY_COLUMNS):
        if not _table_exists(con, schema, table):
            continue  # an older artifact predating the table; nothing to normalise
        present = _columns_of(con, schema, table)
        for column in COUNTRY_COLUMNS[table]:
            if column not in present:
                continue  # an older artifact predating the column
            scanned += 1
            key = f"{table}.{column}"
            # DISTINCT over the column, not a walk over the rows: every one of these
            # columns carries an index, and a corpus with a million articles still has
            # at most a couple of hundred distinct country codes. The work is bounded
            # by the CODE SET, never by the corpus.
            rows = con.execute(
                f'SELECT DISTINCT "{column}" FROM {schema}."{table}" '  # noqa: S608  # nosec B608 - both identifiers come from COUNTRY_COLUMNS, a fixed module-level map, and `schema` is a module-internal literal
                f'WHERE "{column}" IS NOT NULL AND "{column}" <> \'\''
            ).fetchall()
            for (value,) in rows:
                target = canonical_country(value)
                if target is None:
                    # The converter refused it: an aggregate, a non-ISO jurisdiction,
                    # or junk. LEFT EXACTLY AS IT IS -- see the module docstring.
                    refused.setdefault(key, []).append(str(value))
                    continue
                if target == value:
                    continue  # already canonical: the common case in 0.4
                # ONE statement for the whole spelling: the fast, overwhelmingly common
                # path, bounded by the code set rather than the corpus.
                con.execute("SAVEPOINT oo_country_norm")
                try:
                    cur = con.execute(
                        f'UPDATE {schema}."{table}" SET "{column}" = ? '  # noqa: S608  # nosec B608 - identifiers from the fixed COUNTRY_COLUMNS map; the VALUES are bound
                        f'WHERE "{column}" = ?',
                        (target, value),
                    )
                except Exception as exc:  # noqa: BLE001 - a collision must not abort a restore
                    con.execute("ROLLBACK TO oo_country_norm")
                    con.execute("RELEASE oo_country_norm")
                    # AND THEN ROW BY ROW, because SQLite's default ABORT undoes the
                    # WHOLE statement, not the offending row. Measured: with rows A and
                    # B colliding at one url and an unrelated row C sharing A's
                    # spelling at another, the bulk rollback left C unconverted -- and
                    # C then failed its own value-keyed join and landed as a DUPLICATE
                    # document. A collision must cost exactly the rows that collide.
                    n_rows, row_collisions = _convert_row_by_row(
                        con, schema, table, column, value, target
                    )
                    converted[key] = converted.get(key, 0) + n_rows
                    for reason in row_collisions or [str(exc)]:
                        collisions.append(
                            {"column": key, "from": str(value), "to": target,
                             "reason": reason}
                        )
                    continue
                con.execute("RELEASE oo_country_norm")
                converted[key] = converted.get(key, 0) + int(cur.rowcount or 0)

    report: dict = {
        "target_form": CANONICAL_COUNTRY_FORM,
        "columns_scanned": scanned,
        "rows_converted": sum(converted.values()),
        # THE 0.5 PRECONDITION, MEASURED ON EVERY RESTORE. This step normalises the
        # STAGED copy toward `CANONICAL_COUNTRY_FORM`; it does not and must not touch
        # the live corpus. So on the day that constant flips (S05-02), a live corpus
        # that has NOT yet been rewritten is holding the other form -- and every
        # value-keyed join then misses, turning one document into two. Reproduced under
        # simulation: with the constant set to "alpha3" and a live corpus still on
        # alpha-2, one law document came out as two rows while this report cheerfully
        # said "2 rows converted". It is REPORTED rather than refused because no
        # automatic verdict is available: a real corpus legitimately holds values the
        # converter refuses (aggregates, the app's non-ISO jurisdictions, junk) and can
        # be honestly mixed, so a threshold would either refuse good restores or miss
        # bad ones. The ordering is the answer -- the live rewrite lands BEFORE the
        # constant flips -- and this number is how an operator sees whether it has.
        "live_corpus_in_target_form": _live_corpus_in_target_form(con),
        "method": (
            "every registered country column of the incoming corpus is converted to "
            f"the store's canonical form ({CANONICAL_COUNTRY_FORM}) before the "
            "value-keyed joins; a code the converter does not recognise is left "
            "unchanged and listed, and NULL stays NULL"
        ),
    }
    if converted:
        report["converted"] = converted
    if refused:
        # Sorted + de-duplicated so the block is a set of CODES, not a row dump.
        report["left_unchanged"] = {k: sorted(set(v)) for k, v in sorted(refused.items())}
    if collisions:
        report["collisions"] = collisions
    return report


def scan_live_corpus(db) -> dict:
    """The scan, over the LIVE corpus behind an ORM Session.

    The one bridge from a Session to :func:`scan_country_code_duplicates`, shared by the
    diagnostics endpoint and the all-diagnostics bundle member. Two callers reaching for
    the raw connection their own way is how they come to disagree about which schema
    they scanned; and importing the ENDPOINT from the bundle would register its route at
    the bundle's import position, which the Q1139 split guard pins (it caught exactly
    that, by name, before this existed).
    """
    return scan_country_code_duplicates(db.connection().connection, schema="main")


def scan_country_code_duplicates(con: sqlite3.Connection, *, schema: str = "main") -> dict:
    """READ-ONLY: find rows that differ only by the FORM of their country code.

    The artifact gate row K closes on ("the maintainer restores a real pre-migration
    backup and the duplicate-key scan reports 0 duplicates"). This is that scan.

    WHAT IT LOOKS FOR, stated because a number nobody can interpret is not evidence:
    for each country-bearing column it groups the DISTINCT stored spellings by their
    canonical form, and reports any canonical form reached by MORE THAN ONE spelling.
    ``fr`` and ``FRA`` in one column is exactly that; ``fr`` alone is not; ``WLD`` is
    not, because it has no canonical form and is counted as unresolved instead.

    It is direction- AND target-agnostic, so it says the same thing before the 0.5
    storage flip and after it, and a reader can compare two runs.

    IT SCANS THE EXEMPT COLUMNS TOO, labelled. They are not normalised, and a reader
    who sees a duplicate there needs to know the normaliser will NOT fix it -- that is
    a finding about a migration, not about the restore. Reporting only what we act on
    would make the scan agree with the normaliser by construction, which is a check
    that cannot fail.

    ``schema`` is ``main`` (the live corpus) for the operator's run and can be an
    attached alias for a test. Nothing is written.
    """
    columns: dict[str, dict] = {}
    total = 0
    exempt_pairs = dict(COUNTRY_COLUMNS_EXEMPT)
    targets: list[tuple[str, str, bool]] = []
    for table, cols in COUNTRY_COLUMNS.items():
        targets.extend((table, c, False) for c in cols)
    for key in exempt_pairs:
        table, _, col = key.partition(".")
        targets.append((table, col, True))

    for table, column, exempt in sorted(targets):
        if not _table_exists(con, schema, table):
            continue
        if column not in _columns_of(con, schema, table):
            continue
        rows = con.execute(
            f'SELECT "{column}" AS v, COUNT(*) AS n FROM {schema}."{table}" '  # noqa: S608  # nosec B608 - identifiers come from the fixed COUNTRY_COLUMNS / COUNTRY_COLUMNS_EXEMPT maps
            f'WHERE "{column}" IS NOT NULL AND "{column}" <> \'\' GROUP BY "{column}"'
        ).fetchall()
        by_canonical: dict[str, list[tuple[str, int]]] = {}
        unresolved: list[str] = []
        for value, n in rows:
            canonical = canonical_country(value)
            if canonical is None:
                unresolved.append(str(value))
                continue
            by_canonical.setdefault(canonical, []).append((str(value), int(n)))
        groups = [
            {
                "canonical": canonical,
                "spellings": sorted(spellings),
                "rows": sum(n for _, n in spellings),
            }
            for canonical, spellings in sorted(by_canonical.items())
            if len(spellings) > 1
        ]
        entry: dict = {"duplicate_groups": len(groups)}
        if exempt:
            entry["normalised"] = False
            entry["reason"] = exempt_pairs[f"{table}.{column}"]
        if groups:
            entry["groups"] = groups
            if not exempt:
                total += len(groups)
        if unresolved:
            # Not duplicates and not a defect: aggregates, the app's own non-ISO
            # jurisdictions, and whatever junk a corpus has collected. Published so a
            # reader can see WHAT the scan could not judge rather than assuming the
            # answer covered everything.
            entry["unresolved_codes"] = sorted(set(unresolved))
        columns[f"{table}.{column}"] = entry

    return {
        "duplicates": total,
        "columns": columns,
        "target_form": CANONICAL_COUNTRY_FORM,
        "method": (
            "per country-bearing column, the distinct stored spellings are grouped by "
            "their canonical form; a group with more than one spelling is one "
            "duplicate. Codes with no canonical form (statistical aggregates, the "
            "app's non-ISO jurisdictions, junk) are listed as unresolved, never "
            "counted either way"
        ),
        "caveat": (
            "`duplicates` counts only the columns the restore normalises. A column "
            "marked normalised:false is scanned and REPORTED but excluded from the "
            "total; what a group there means differs per column, so each carries its "
            "own reason rather than one blanket claim -- an earlier single sentence "
            "said every such group was 'a question about a migration rather than "
            "about a restore', which was true of stat_figures.ref_area and false of "
            "stat_subscriptions.country, where two installs typing one country in two "
            "cases really did duplicate at restore until the merge key was folded"
        ),
    }
