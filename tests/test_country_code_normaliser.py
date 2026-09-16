"""The restore-path country-code normaliser and the duplicate-key scan (Q310 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THESE MERGE INTO A DIFFERENT CORPUS. The restore anyone actually runs is a
self-restore, where every row reads as a duplicate and no INSERT runs at all -- so a
self-restore can never exercise a handler, which is the standing lesson
``tests/test_merge_owed_tables.py`` opens with. Every test here drives the REAL
``merge_corpus`` over two real SQLite corpora, one populated and one empty.

THE FIXTURE IS DELIBERATELY "ALREADY MIGRATED". A pre-migration corpus holds alpha-2
and the normaliser is a no-op on it, so a fixture built from today's data would prove
only that nothing crashed. These corpora carry alpha-3, which is what a 0.5-era backup
will hold -- so the conversion really runs and the guard can fail.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup import country_codes as cc  # noqa: E402
from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import (  # noqa: E402
    Article,
    Base,
    LawDocument,
    Source,
    StatSubscription,
)

_BATCH_META = {
    "artifact_kind": "oo-backup-3",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _article(source_id: int, n: int, country: str | None):
    return Article(
        title=f"T{n}",
        url=f"https://ex.example/{n}",
        canonical_url=f"https://ex.example/{n}",
        content="body",
        hash=f"h{n}",
        source_id=source_id,
        country=country,
        created_at=_T0,
    )


# --------------------------------------------------------------------------- #
#  The conversion itself
# --------------------------------------------------------------------------- #
def test_an_alpha3_incoming_corpus_is_converted_to_the_stores_form(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        src = Source(name="N", domain="n.example", country="FRA")
        s.add(src)
        s.flush()
        s.add(_article(src.id, 1, "DEU"))
        s.commit()
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert s.query(Source).one().country == "fr", (
            "an incoming alpha-3 source country reached the store unconverted -- the "
            "restore would hold two spellings of one country"
        )
        assert s.query(Article).one().country == "de"
    block = counts["_country_codes"]
    assert block["rows_converted"] == 2
    assert block["converted"] == {"sources.country": 1, "articles.country": 1}
    assert block["target_form"] == "alpha2"


def test_a_value_already_in_the_stores_form_is_left_alone(tmp_path):
    """The negative-space twin of the test above: an over-eager normaliser that
    rewrote every row would pass the conversion test and fail this one."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(Source(name="N", domain="n.example", country="fr"))
        s.commit()
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    assert counts["_country_codes"]["rows_converted"] == 0
    assert "converted" not in counts["_country_codes"]
    with _corpus(working)() as s:
        assert s.query(Source).one().country == "fr"


def test_an_unrecognised_code_survives_the_restore_unchanged(tmp_path):
    """THE DATA-LOSS CASE. ``to_iso2`` fails closed and answers None for an aggregate,
    for the app's own non-ISO jurisdictions and for junk. Writing that None back would
    delete the operator's value to satisfy a code table; leaving it loses nothing. Both
    halves are asserted -- that the value survives AND that the report names it, because
    a silent survival is indistinguishable from a normaliser that never ran."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(Source(name="A", domain="a.example", country="ZZ"))
        s.add(Source(name="B", domain="b.example", country="WLD"))
        s.commit()
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = {x.domain: x.country for x in s.query(Source).all()}
    assert got == {"a.example": "ZZ", "b.example": "WLD"}
    assert counts["_country_codes"]["left_unchanged"]["sources.country"] == ["WLD", "ZZ"]


def test_a_null_country_is_never_normalised_into_a_value(tmp_path):
    """A gap stays a gap. The brief's negative-space lens names this one by hand.

    A PURELY NEGATIVE assertion is satisfied by a normaliser that does nothing at all,
    so the fixture also carries a row the normaliser MUST convert. Now the test fails
    both ways: if NULL is filled in, and if the engine never ran."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        src = Source(name="N", domain="n.example", country=None)
        s.add(src)
        s.flush()
        s.add(_article(src.id, 1, None))
        # the live wire: a row that has to change, in the same corpus and the same pass
        other = Source(name="C", domain="c.example", country="FRA")
        s.add(other)
        s.flush()
        s.add(_article(other.id, 2, "DEU"))
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert sorted(
            (c if c is not None else "<null>")
            for (c,) in s.query(Source.country).all()
        ) == ["<null>", "fr"], "either a NULL was filled in, or the normaliser never ran"
        assert sorted(
            (c if c is not None else "<null>")
            for (c,) in s.query(Article.country).all()
        ) == ["<null>", "de"]


def test_the_law_jurisdiction_column_is_normalised_too(tmp_path):
    """``jurisdiction`` is the column the brief names explicitly. In 0.4 every shipped
    value normalises to itself, so the discriminating fixture has to carry an alpha-3
    one -- and the app's OWN non-ISO jurisdictions must survive beside it."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(LawDocument(jurisdiction="FRA", url="https://l.example/1", title="A",
                          country="ITA"))
        s.add(LawDocument(jurisdiction="uk", url="https://l.example/2", title="B",
                          country=None))
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = {d.title: (d.jurisdiction, d.country) for d in s.query(LawDocument).all()}
    assert got["A"] == ("fr", "it")
    assert got["B"] == ("uk", None), (
        "the app's own non-ISO jurisdiction was rewritten or dropped; `uk` has no ISO "
        "alpha-2 and must pass through untouched"
    )


def test_an_external_contract_column_is_NOT_rewritten(tmp_path):
    """``stat_subscriptions.country`` is the World Bank API's own parameter, replayed
    verbatim on the next fetch and part of ``uq_stat_subscription``. Q311 keeps external
    contracts as they are. This is the guard that stops a future reader "completing"
    the registry by adding it."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(StatSubscription(source="worldbank", indicator="SP.POP.TOTL", country="USA"))
        s.add(StatSubscription(source="worldbank", indicator="SP.DYN.LE00.IN", country="all"))
        s.add(Source(name="N", domain="n.example", country="FRA"))
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = sorted(x.country for x in s.query(StatSubscription).all())
        # The live wire, in the same corpus and the same pass: a column that MUST be
        # rewritten. Without it a normaliser that did nothing at all would pass this
        # test -- a negative assertion is satisfied for free by a no-op.
        normalised = [c for (c,) in s.query(Source.country).all()]
    assert got == ["USA", "all"], (
        "the WB country PARAMETER was normalised; the next re-fetch would send a "
        "different query and the unique key would no longer dedupe"
    )
    assert normalised == ["fr"], (
        f"the normaliser did not run at all (sources.country is {normalised}), so the "
        "assertion above proves nothing about the exemption"
    )


def test_the_normaliser_runs_BEFORE_every_handler_that_reads_a_country(tmp_path):
    """ORDER IS THE WHOLE POINT, so it is asserted directly rather than inferred from
    an outcome. A normaliser that ran last would leave every one of these joins reading
    the un-normalised value, and the conversion test above would still pass."""
    from src.backup.merge import _merge_steps

    names = [name for name, _fn in _merge_steps()]
    assert names[0] == "country codes", f"the normaliser is not the first step: {names[:3]}"
    for later in ("sources", "articles", "official statistics", "law"):
        assert names.index(later) > 0


# --------------------------------------------------------------------------- #
#  The target is ONE constant with ONE read (the 0.5 flip)
# --------------------------------------------------------------------------- #
def test_flipping_the_canonical_form_changes_what_the_normaliser_emits(tmp_path, monkeypatch):
    """The 0.5 storage half (Q301 = c) flips ONE literal. Both settings are pinned here,
    so the flip cannot silently change what the module claims to do -- a one-line flip
    owes a disclosure that is true on both sides of it."""
    monkeypatch.setattr(cc, "CANONICAL_COUNTRY_FORM", "alpha3")
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(Source(name="N", domain="n.example", country="fr"))
        s.commit()
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert s.query(Source).one().country == "FRA"
    assert counts["_country_codes"]["target_form"] == "alpha3"
    assert "alpha3" in counts["_country_codes"]["method"], (
        "the published method still names the old target -- the sentence and the "
        "arithmetic have to come from the same read"
    )


def test_the_canonical_form_is_read_in_exactly_one_place():
    """Anti-drift: a second read is a second place to flip. Asserted over the module's
    own source with comments stripped, because the constant is NAMED in the docstrings
    that explain it and a bare count would read those."""
    import ast
    import inspect

    src = inspect.getsource(cc)
    tree = ast.parse(src)
    reads = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == "CANONICAL_COUNTRY_FORM"
        and isinstance(n.ctx, ast.Load)
    ]
    # `_converter` decides; the report and the scan echo it as a VALUE, which is
    # reporting rather than deciding. Only the decision may be single.
    deciding = [n for n in reads if n.lineno == _converter_line(src)]
    assert len(deciding) == 1, (
        f"{len(deciding)} decisions read CANONICAL_COUNTRY_FORM; there must be exactly one"
    )


def _converter_line(src: str) -> int:
    for i, line in enumerate(src.splitlines(), start=1):
        if "return to_iso3 if CANONICAL_COUNTRY_FORM" in line:
            return i
    raise AssertionError("the converter's decision line moved; re-anchor this guard")


# --------------------------------------------------------------------------- #
#  The registry is derived from the models, not from good intentions
# --------------------------------------------------------------------------- #
def test_every_country_bearing_column_of_a_MERGED_table_is_registered_or_exempt():
    """The completeness check the 2026-07-24 dropped-column lesson asks for, one level
    over: a new country column on a merged table must join the normaliser's registry or
    the exempt registry WITH A REASON. Anything else is an oversight by definition."""
    from src.backup.merge import _MERGE_HANDLED

    registered = {f"{t}.{c}" for t, cols in cc.COUNTRY_COLUMNS.items() for c in cols}
    exempt = set(cc.COUNTRY_COLUMNS_EXEMPT)
    missing = []
    for table in sorted(Base.metadata.tables):
        if table not in _MERGE_HANDLED:
            continue
        for col in Base.metadata.tables[table].columns:
            if "country" not in col.name.lower() and col.name.lower() not in (
                "jurisdiction", "ref_area"
            ):
                continue
            key = f"{table}.{col.name}"
            if key not in registered and key not in exempt:
                missing.append(key)
    assert not missing, (
        "these country-bearing columns of MERGED tables are in neither registry: "
        f"{missing}. Add them to COUNTRY_COLUMNS, or to COUNTRY_COLUMNS_EXEMPT with "
        "the reason they must not be rewritten."
    )


def test_every_exempt_entry_names_a_real_column():
    """The other direction: an exemption for a column that no longer exists is a
    reason nobody can check, and it makes the registry read as covering more than it
    does."""
    stale = []
    for key in cc.COUNTRY_COLUMNS_EXEMPT:
        table, _, col = key.partition(".")
        t = Base.metadata.tables.get(table)
        if t is None or col not in t.columns:
            stale.append(key)
    assert not stale, f"exempt entries naming columns that do not exist: {stale}"


def test_every_exempt_entry_carries_a_reason():
    for key, reason in cc.COUNTRY_COLUMNS_EXEMPT.items():
        assert len(reason) > 40, f"{key} is exempt with no usable reason"


# --------------------------------------------------------------------------- #
#  The duplicate-key scan (the gate's artifact)
# --------------------------------------------------------------------------- #
def _scan(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return cc.scan_country_code_duplicates(con, schema="main")
    finally:
        con.close()


def test_the_scan_reports_zero_after_restoring_a_pre_migration_backup(tmp_path):
    """The gate's acceptance clause, on the CI fixture. The real-restore half is the
    operator's and is `not-measurable-here`.

    THE FIXTURE HAS TO DISAGREE WITH ITSELF, or this proves nothing. It used to seed
    BOTH corpora with ``"fr"`` -- so the scan answered 0 whether or not the normaliser
    ran, and the test passed with the normaliser's body replaced by ``pass``. The staged
    side now carries the genuinely PRE-migration spellings (alpha-3, the form a backup
    taken after the 0.5 flip carries, plus an upper-case alpha-2 a hand-edited catalog
    carries) while the live side is alpha-2, so a 0 here means the normaliser reconciled
    them rather than that there was nothing to reconcile."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        src = Source(name="N", domain="n.example", country="FRA")  # pre-migration form
        s.add(src)
        s.flush()
        s.add(_article(src.id, 1, "DEU"))
        s.commit()
    with _corpus(working)() as s:
        mine = Source(name="M", domain="m.example", country="fr")
        s.add(mine)
        s.flush()
        s.add(_article(mine.id, 2, "de"))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    report = _scan(working)
    assert report["duplicates"] == 0, report
    # ...and the fixture really did carry both forms, so the 0 above is a reconciliation
    # and not an empty scan (the anti-vacuity floor).
    with _corpus(working)() as s:
        assert sorted(c for (c,) in s.query(Source.country).all()) == ["fr", "fr"]
        assert sorted(c for (c,) in s.query(Article.country).all()) == ["de", "de"]


def test_the_scan_SEES_a_duplicate_when_one_exists(tmp_path):
    """Anti-vacuity. A scan that always answers 0 would satisfy the gate's clause
    without ever having looked, so the discriminating case is a corpus that really
    holds both spellings."""
    live = tmp_path / "live.db"
    with _corpus(live)() as s:
        s.add(Source(name="A", domain="a.example", country="fr"))
        s.add(Source(name="B", domain="b.example", country="FRA"))
        s.commit()

    rep = _scan(live)

    assert rep["duplicates"] == 1
    group = rep["columns"]["sources.country"]["groups"][0]
    assert group["canonical"] == "fr"
    assert [sp for sp, _n in group["spellings"]] == ["FRA", "fr"]
    assert group["rows"] == 2


def test_the_scan_does_not_count_an_aggregate_as_a_duplicate(tmp_path):
    """The mirror defect: an over-eager scan reporting `WLD` beside `wl` would invent
    a finding, and a fabricated FAIL is exactly as dishonest as a fabricated pass."""
    live = tmp_path / "live.db"
    with _corpus(live)() as s:
        s.add(Source(name="A", domain="a.example", country="WLD"))
        s.add(Source(name="B", domain="b.example", country="fr"))
        s.commit()

    rep = _scan(live)

    assert rep["duplicates"] == 0
    assert rep["columns"]["sources.country"]["unresolved_codes"] == ["WLD"]


def test_the_scan_reports_an_exempt_column_without_counting_it(tmp_path):
    """The exempt columns are scanned and LABELLED, never silently skipped: a reader
    seeing a duplicate there needs to know the restore will not fix it. Reporting only
    what the normaliser acts on would make the scan agree with it by construction."""
    live = tmp_path / "live.db"
    with _corpus(live)() as s:
        s.add(StatSubscription(source="worldbank", indicator="X", country="USA"))
        s.add(StatSubscription(source="worldbank", indicator="Y", country="us"))
        s.commit()

    rep = _scan(live)

    entry = rep["columns"]["stat_subscriptions.country"]
    assert entry["normalised"] is False
    assert entry["duplicate_groups"] == 1
    assert rep["duplicates"] == 0, (
        "an exempt column was counted in the headline total; a duplicate there is a "
        "question about a migration, not about a restore"
    )


def test_the_scan_writes_nothing(tmp_path):
    """READ-ONLY is the whole contract of a diagnostic an operator runs on their live
    corpus. Proved by comparing the file's bytes, not by reading the SQL."""
    live = tmp_path / "live.db"
    with _corpus(live)() as s:
        s.add(Source(name="A", domain="a.example", country="FRA"))
        s.add(Source(name="B", domain="b.example", country="fr"))
        s.commit()
    con = sqlite3.connect(live)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    before = live.read_bytes()

    _scan(live)

    assert live.read_bytes() == before


def test_the_scan_answers_the_same_whatever_the_target_form(tmp_path, monkeypatch):
    """Target-agnostic, so a reader can compare a run taken before the 0.5 flip with
    one taken after it. `fr` and `FRA` are one fact in two spellings under either."""
    live = tmp_path / "live.db"
    with _corpus(live)() as s:
        s.add(Source(name="A", domain="a.example", country="fr"))
        s.add(Source(name="B", domain="b.example", country="FRA"))
        s.commit()

    a2 = _scan(live)["duplicates"]
    monkeypatch.setattr(cc, "CANONICAL_COUNTRY_FORM", "alpha3")
    a3 = _scan(live)["duplicates"]

    assert a2 == a3 == 1


def test_the_bundle_member_drives_the_real_scan(tmp_path):
    """A test of the helper is not a test of its wiring. Monkeypatching the scan and
    asserting the bundle member reflects it proves the member CALLS it -- a source
    check that the name appears in bundle.py would pass with the call deleted."""
    import src.backup.country_codes as mod
    from src.api.diagnostics import _country_code_scan

    live = tmp_path / "live.db"
    _corpus(live)
    engine = create_engine(f"sqlite:///{live}", future=True)
    sentinel = {"duplicates": 4242, "columns": {}}
    original = mod.scan_country_code_duplicates
    mod.scan_country_code_duplicates = lambda *a, **k: sentinel
    try:
        with sessionmaker(bind=engine, future=True)() as s:
            s.execute(text("SELECT 1"))
            assert _country_code_scan(s) is sentinel
    finally:
        mod.scan_country_code_duplicates = original


# --------------------------------------------------------------------------- #
#  A collision costs exactly the rows that collide
# --------------------------------------------------------------------------- #
def test_one_collision_does_not_strand_the_OTHER_rows_of_that_spelling(tmp_path):
    """MEASURED DEFECT, found by an adversarial pass and fixed. SQLite's default ON
    CONFLICT ABORT undoes the WHOLE statement, so the one-UPDATE-per-spelling loop let a
    single colliding pair silently revert every other row that shared that spelling --
    rows with no conflict of their own. Those rows then missed their OWN value-keyed join
    and landed as duplicate documents, which is precisely what this module exists to
    prevent.

    The fixture is the exact shape: A and B collide at one URL once ``FR`` becomes
    ``fr``; C shares A's SPELLING at a different URL and collides with nothing. Before
    the fix the report said ``rows_converted: 0`` and the merged corpus held TWO rows for
    C's URL. Now C converts, its duplicate is gone, and the genuine A/B collision is
    still reported rather than swallowed."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(LawDocument(jurisdiction="FR", url="https://x/1", title="Row A"))
        s.add(LawDocument(jurisdiction="fr", url="https://x/1", title="Row B"))
        s.add(LawDocument(jurisdiction="FR", url="https://x/2", title="Row C"))
        s.commit()
    with _corpus(working)() as s:
        s.add(LawDocument(jurisdiction="fr", url="https://x/2", title="Local copy of 2"))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        at_two = [d.jurisdiction for d in s.query(LawDocument).filter_by(url="https://x/2")]
    assert at_two == ["fr"], (
        f"an unrelated collision stranded row C: {at_two}. The document now exists twice "
        "under two spellings of one jurisdiction"
    )
    cc = counts["_country_codes"]
    assert cc["rows_converted"] >= 1, cc
    # ...and the REAL collision is still reported. A fix that swallowed it would trade
    # one silence for another.
    assert cc.get("collisions"), "the genuine A/B collision went unreported"
    assert cc["collisions"][0]["column"] == "law_documents.jurisdiction"


def test_a_collision_still_leaves_the_STAGED_row_exactly_as_it_was(tmp_path):
    """The negative-space twin of the row-by-row retry: a row that genuinely cannot be
    converted must be rolled back, never half-written and never dropped."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(LawDocument(jurisdiction="FR", url="https://y/1", title="Upper"))
        s.add(LawDocument(jurisdiction="fr", url="https://y/1", title="Lower"))
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = sorted((d.jurisdiction, d.title) for d in s.query(LawDocument).all())
    assert got == [("FR", "Upper"), ("fr", "Lower")], (
        f"a colliding row was mangled or dropped rather than left alone: {got}"
    )


# --------------------------------------------------------------------------- #
#  Flip day (S05-02) is MEASURED on every restore
# --------------------------------------------------------------------------- #
def test_a_corpus_already_in_the_target_form_reports_zero_off_form(tmp_path):
    """The normal case, today: the live corpus stores alpha-2, the normaliser targets
    alpha-2, and there is no form gap to report."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(Source(name="N", domain="n.example", country="FRA"))
        s.commit()
    with _corpus(working)() as s:
        s.add(Source(name="M", domain="m.example", country="de"))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    block = counts["_country_codes"]["live_corpus_in_target_form"]
    assert block["off_form"] == 0, block
    assert "caveat" not in block, "a caveat was raised over a corpus that is in form"
    assert block["columns_checked"] >= 5, block


def test_flip_day_is_REPORTED_when_the_live_corpus_is_still_on_the_other_form(
    tmp_path, monkeypatch
):
    """THE SIMULATED CORRUPTION, kept as a test. With ``CANONICAL_COUNTRY_FORM`` flipped
    to alpha-3 while the live corpus is still alpha-2, normalising the staged copy
    toward alpha-3 makes every value-keyed join miss: one law document really does come
    out as two rows. Nothing in this slice can decide that automatically -- a real
    corpus legitimately holds values the converter refuses and can be honestly mixed --
    so the restore MEASURES the gap and names the ordering S05-02 owns.

    This test is also the tripwire for that flip: if a future session flips the constant
    without rewriting the live corpus first, this is the failure that says so."""
    monkeypatch.setattr(cc, "CANONICAL_COUNTRY_FORM", "alpha3")
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(LawDocument(jurisdiction="fr", url="https://l/1", title="Same", country="fr"))
        s.commit()
    with _corpus(working)() as s:
        s.add(LawDocument(jurisdiction="fr", url="https://l/1", title="Mine", country="fr"))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    block = counts["_country_codes"]["live_corpus_in_target_form"]
    assert block["off_form"] > 0, (
        "flip day went unreported; an operator would see '2 rows converted' and a "
        "duplicated document with nothing connecting the two"
    )
    assert "S05-02" in block["caveat"]
    assert "law_documents.jurisdiction" in block["spellings"]
    # ...and the duplicate really is there, so the measurement is not theatre.
    with _corpus(working)() as s:
        assert s.query(LawDocument).filter_by(url="https://l/1").count() == 2


def test_the_measurement_never_counts_a_code_that_HAS_no_canonical_form(tmp_path):
    """Aggregates and the app's own non-ISO jurisdictions say nothing about which form a
    corpus uses, so counting them would report a permanent, unfixable gap on every
    healthy corpus -- an alarm that is always on is an alarm nobody reads."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _corpus(staged)
    with _corpus(working)() as s:
        s.add(LawDocument(jurisdiction="uk", url="https://l/2", title="UK", country="uk"))
        s.add(Source(name="W", domain="w.example", country="WLD"))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    block = counts["_country_codes"]["live_corpus_in_target_form"]
    assert block["off_form"] == 0, block
