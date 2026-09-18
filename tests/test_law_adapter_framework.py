"""The adapter framework, the source classes and the Q925 ⛔ seam (brief S04-10 S3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q906 = a ("one adapter per source format"), Q909 = a (three source classes, in a ruled
order of preference), Q910 = a (the EU's open paths allowed, the EU-Login dump excluded
as key-gated), Q919 = a (a law authority is a ``Source`` row with ``source_type="law"``),
Q921 = a (``counts_documents`` licenses a division), Q924 = a (a ``verified`` tier per
source), Q927 = a (a licence per document) — and Q925 ⛔, which this slice may not decide.

THE CENTRAL CLAIM THIS FILE EXISTS TO MEASURE: *"a second adapter fits without code
changes but none is added"*. That is unfalsifiable as prose and trivial to check for
real: a test registers a second parser and drives it through the whole pipeline. If the
framework needed a production change to accept one, this file would not run.
"""

from __future__ import annotations

import pytest

from src.law.adapters import AdapterRefusal, ParsedLaw, Provision
from src.law.adapters.registry import (
    SOURCE_CLASS_NOTES,
    SOURCE_CLASSES,
    UnknownFormatError,
    adapter_for,
    known_formats,
    parse_with,
    register_adapter,
    single_provision,
)
from src.law.catalog import (
    LAW_AUTHORITY_TYPES,
    LAW_SOURCE_TYPE,
    counts_documents,
    is_law_source_type,
    licence_for_url,
    load_legal_catalog,
    registration_source_rows,
    source_for_url,
    source_type_for,
    verified_tier,
)
from src.law.model import LICENCES

# ---------------------------------------------------------------------------
# Q906 — one adapter per format, and the seam a second one arrives through
# ---------------------------------------------------------------------------


def test_only_the_CLML_adapter_is_registered_because_Q925_is_PENDING():
    """Not an omission. Choosing a second format IS the pending decision."""
    assert known_formats() == ("clml",)


def test_a_SECOND_adapter_fits_with_no_production_change():
    """The slice's own acceptance line, measured rather than asserted in prose.

    A parser is registered here, in a test, and driven through the public entry point.
    Nothing in ``src/`` changes for this to work — which is the whole claim.
    """

    def _fake_uslm(data: bytes | str, *, retrieved_on: str | None = None) -> ParsedLaw:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
        return ParsedLaw(
            title="An Act From Another Format",
            provisions=[Provision(number="1", heading=None, text=text)],
            format="uslm",
            retrieved_on=retrieved_on,
            body_chars=len(text),
            text_recovered_pct=1.0,
        )

    register_adapter("uslm-test", _fake_uslm)
    try:
        assert "uslm-test" in known_formats()
        parsed = parse_with("uslm-test", b"Section 1 text.", retrieved_on="2026-09-18")
        assert parsed.format == "uslm"
        assert parsed.retrieved_on == "2026-09-18"
        assert parsed.provisions[0].identifier == "1"
    finally:
        from src.law.adapters import registry

        registry._ADAPTERS.pop("uslm-test", None)


def test_an_unknown_format_is_REFUSED_never_silently_scraped():
    """The dangerous fallback: a source declaring ``uslm`` and getting the HTML
    page-scraper would look like it worked — text present, provisions wrong, nothing
    said. That is worse than being told the source is unreadable."""
    with pytest.raises(UnknownFormatError) as excinfo:
        adapter_for("uslm")
    assert "uslm" in str(excinfo.value)
    assert "clml" in str(excinfo.value), "the refusal says what IS registered"


def test_two_adapters_cannot_claim_one_format():
    def _a(data, *, retrieved_on=None):  # pragma: no cover - never called
        raise AssertionError

    def _b(data, *, retrieved_on=None):  # pragma: no cover - never called
        raise AssertionError

    register_adapter("contested", _a)
    try:
        with pytest.raises(UnknownFormatError, match="already registered"):
            register_adapter("contested", _b)
        # The same function twice is not a conflict — an idempotent import is not a bug.
        register_adapter("contested", _a)
    finally:
        from src.law.adapters import registry

        registry._ADAPTERS.pop("contested", None)


def test_a_text_only_source_fills_the_model_with_ONE_provision():
    """Q906's last clause. The address is written in ONE place so two callers cannot
    give one document two different addresses and make it look replaced."""
    parsed = single_provision("The whole Act, as plain text.", title="A Plain Act")
    assert len(parsed.provisions) == 1
    assert parsed.provisions[0].identifier == "A Plain Act"
    assert parsed.text_recovered_pct == 1.0, (
        "for a text-only source the text IS the document, so the figure is a definition "
        "rather than a flattering default"
    )


def test_an_empty_text_only_document_is_refused():
    with pytest.raises(AdapterRefusal):
        single_provision("   ")


# ---------------------------------------------------------------------------
# Q909 — the three classes, in the ruled order
# ---------------------------------------------------------------------------


def test_the_source_classes_are_the_three_ruled_ones_IN_ORDER():
    """The order IS the ruling ("bulk open data first … then enumeration … then gazette
    feeds"), so it is the tuple's order and not a sort key somebody could change."""
    assert SOURCE_CLASSES == ("bulk", "enumeration", "gazette-feed")
    assert set(SOURCE_CLASS_NOTES) == set(SOURCE_CLASSES)
    for note in SOURCE_CLASS_NOTES.values():
        assert note.strip() and note[0].islower(), "a class note is a sentence fragment"


# ---------------------------------------------------------------------------
# Q919 — a law authority is a Source row with source_type="law"
# ---------------------------------------------------------------------------


def test_law_authorities_become_law_sources_and_the_others_do_NOT():
    rows = registration_source_rows(load_legal_catalog())
    kinds = {r["source_type"] for r in rows}
    assert LAW_SOURCE_TYPE in kinds
    assert "legal" not in kinds and "gazette" not in kinds, "both legacy tokens moved"
    # An IP office is a registry, not a law authority; case law is Q902's (e), NOT CHOSEN.
    assert "ip" in kinds, "an IP office keeps its own type"
    assert "case_law" in kinds, (
        "admitting case-law portals under the law type would quietly enter a document "
        "class Q902's (e) declined"
    )


@pytest.mark.parametrize(
    ("declared", "expected"),
    [("legal", "law"), ("gazette", "law"), ("ip", "ip"), ("case_law", "case_law")],
)
def test_the_source_type_mapping_is_a_rename_of_one_class_not_a_flattening(declared, expected):
    assert source_type_for({"source_type": declared}) == expected
    assert {"legal", "gazette"} == LAW_AUTHORITY_TYPES


def test_both_vocabularies_are_recognised_as_law():
    """A store mid-migration and a corpus restored from an older backup both hold the old
    token. A classifier that knew only the new one would silently drop 263 law portals
    out of the law provenance class on exactly those stores."""
    assert is_law_source_type("law") and is_law_source_type("legal")
    assert not is_law_source_type("ip") and not is_law_source_type(None)


def test_the_provenance_class_reads_BOTH_tokens():
    from src.catalog.provenance import LAW, provenance_of

    assert provenance_of("legislation.gov.uk", "law") == LAW
    assert provenance_of("legislation.gov.uk", "legal") == LAW


# ---------------------------------------------------------------------------
# Q921 — a division has to be DECLARED
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "count",
    [None, {}, {"value": 10}, {"value": 10, "counts_documents": False},
     {"value": 10, "counts_documents": "yes"}, {"value": 10, "counts_documents": 1}],
)
def test_coverage_may_NOT_divide_unless_the_row_says_so(count):
    """Ruling 47's rail: declare it explicitly, never infer it from the unit string.

    ``"yes"`` and ``1`` are both truthy in Python and neither is a declaration — a
    volume or a gazette issue contains many acts, so a division licensed by a truthy
    string produces a percentage of nothing.
    """
    assert counts_documents(count) is False


def test_coverage_MAY_divide_when_the_row_declares_it():
    assert counts_documents({"value": 10, "unit": "acts", "counts_documents": True}) is True


def test_no_catalogue_row_licenses_a_division_today():
    """Measured, not assumed: the field is new, so nothing declares it yet and every
    coverage figure still refuses. A test that only checked the helper would not notice
    a row quietly acquiring the flag without its unit being checked."""
    rows = load_legal_catalog()["sources"]
    declared = [s["domain"] for s in rows if counts_documents(s.get("official_count"))]
    assert declared == []


# ---------------------------------------------------------------------------
# Q924 — the verified tier, and what it does NOT claim
# ---------------------------------------------------------------------------


def test_an_unrecorded_verification_is_unverified_with_NO_date():
    """Stamping an absence with today's date turns "nobody looked" into a measurement."""
    tier = verified_tier({})
    assert tier["tier"] == "unverified"
    assert tier["as_of"] is None and tier["method"] is None


def test_an_unreadable_tier_degrades_and_SAYS_SO():
    tier = verified_tier({"verified": {"tier": "LIVE-ish"}})
    assert tier["tier"] == "unverified"
    assert tier["unreadable_tier"] == "LIVE-ish", "the bad value travels, so it is fixable"


def test_the_tier_is_NOT_derived_from_the_research_status():
    """Two different questions. A portal a researcher confirmed exists says nothing
    about whether an adapter in THIS tree can read it."""
    researched = {"verification": {"status": "fetched", "retrieved_at": "2026-07-17"}}
    assert verified_tier(researched)["tier"] == "unverified"


def test_the_CLML_source_is_fixture_verified_and_the_other_two_are_not():
    """The honest state of this tree: the adapter reads CLML fixtures, and all three
    priority hosts are egress-blocked from the build sandbox."""
    rows = {s["domain"]: s for s in load_legal_catalog()["sources"]}
    assert verified_tier(rows["legislation.gov.uk"])["tier"] == "fixture"
    assert verified_tier(rows["eur-lex.europa.eu"])["tier"] == "unverified"
    assert verified_tier(rows["gesetze-im-internet.de"])["tier"] == "unverified"
    for domain in ("legislation.gov.uk", "eur-lex.europa.eu", "gesetze-im-internet.de"):
        method = verified_tier(rows[domain])["method"] or ""
        assert method, "a tier with no method cannot be re-checked"


# ---------------------------------------------------------------------------
# Q910 — the EU's open paths are recorded; the key-gated dump is excluded
# ---------------------------------------------------------------------------


def test_the_EU_row_records_the_open_paths_AND_names_the_excluded_dump():
    """"We did not use it" is a recorded decision here, not an absence somebody has to
    reconstruct. No EU adapter is built either way — that is Q925's."""
    row = source_for_url("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019L0790")
    assert row is not None
    bulk = (row.get("structured") or {}).get("bulk") or ""
    assert "EU-Login" in bulk and "EXCLUDED" in bulk
    assert "Q910" in bulk
    assert (row.get("structured") or {}).get("api_key_required") is False
    assert "formex" in ((row.get("structured") or {}).get("formats") or [])
    assert "eur-lex" not in known_formats(), "no EU adapter is built in this slice"


# ---------------------------------------------------------------------------
# Q927 — the licence a document inherits
# ---------------------------------------------------------------------------


def test_a_document_inherits_its_source_licence_by_HOST_on_a_dot_boundary():
    assert licence_for_url("https://www.legislation.gov.uk/ukpga/2018/12/data.xml") == "ogl-3.0"
    assert licence_for_url("https://eur-lex.europa.eu/eli/dir/2019/790/oj") == "eu-reuse"
    # The loose suffix match would make this inherit the UK licence, which is exactly the
    # claim the lookup exists to carry.
    assert licence_for_url("https://notlegislation.gov.uk/x") == "unknown"
    assert licence_for_url(None) == "unknown"
    assert licence_for_url("https://example.test/act") == "unknown"


def test_every_catalogue_licence_is_in_the_MODEL_registry():
    """A free-string licence on a row would reach a reader as "licence not recorded",
    which looks like an honest absence and is in fact a lost fact."""
    rows = load_legal_catalog()["sources"]
    declared = {str(s["licence"]) for s in rows if s.get("licence")}
    assert declared, "control: at least one row declares a licence"
    assert declared <= set(LICENCES), f"not in the registry: {sorted(declared - set(LICENCES))}"


# ---------------------------------------------------------------------------
# Q925 ⛔ — the seam, and the shape of a file that decides nothing
# ---------------------------------------------------------------------------


def test_the_seam_report_is_current_and_RANKS_NOTHING():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/law_adapter_seam.py", "--check"],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    text = (root / "docs" / "product" / "LAW_ADAPTER_SEAM.md").read_text(encoding="utf-8")
    assert "PENDING" in text and "Q925" in text
    # No ranking COLUMN, and no ranking word inside a row. Checked on the table rows
    # rather than on the whole file: the first draft searched the prose too and tripped
    # on a sentence describing which hosts the BRIEF names, which ranks nothing. A test
    # that fails on the document explaining itself is measuring the wrong thing.
    rows = [ln.lower() for ln in text.splitlines() if ln.startswith("| ")]
    for forbidden in ("rank", "recommend", "priority", "best", "score", "first choice"):
        offenders = [ln for ln in rows if forbidden in ln]
        assert not offenders, f"a seam row must not {forbidden!r}: {offenders[:2]}"
    header = next(ln for ln in rows if "| source |" in ln)
    assert "rank" not in header
    # The three hosts the brief's live checks name are IN it — the first draft required a
    # `verification` block and so excluded all 51 curated rows, these three among them.
    for domain in ("legislation.gov.uk", "eur-lex.europa.eu", "gesetze-im-internet.de"):
        assert f"`{domain}`" in text


# ---------------------------------------------------------------------------
# Q919's migration for stores seeded before the ruling
# ---------------------------------------------------------------------------


def test_the_migration_moves_catalogue_rows_and_leaves_everything_else_alone(tmp_path):
    """Keyed on the ``via:legal`` provenance TAG, not on a domain list.

    The obvious implementation reads the catalogue and updates its 263 domains, which
    would put a 277-row YAML load on every boot AND silently miss a row whose catalogue
    entry was later removed — leaving it on the old token forever. The tag answers the
    question actually being asked: did this row come from the law catalogue?
    """
    from sqlalchemy import create_engine, text

    from src.database.maintenance import ensure_law_source_type
    from src.database.models import Base, Source

    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as con:
        for domain, source_type, tags in (
            ("legislation.gov.uk", "legal", "law,legislation,via:legal"),
            ("gazette.example.test", "gazette", "law,gazette,via:legal"),
            ("wipo.int", "ip", "ip,via:legal"),
            ("courts.example.test", "case_law", "case-law,via:legal"),
            # A `legal`-typed row from ANOTHER catalogue: not the law catalogue's, so not
            # this ruling's to move.
            ("someones-blog.example.test", "legal", "via:curated"),
        ):
            con.execute(
                text(
                    "INSERT INTO sources (name, domain, source_type, tags, enabled)"
                    " VALUES (:n, :d, :t, :g, 1)"
                ),
                {"n": domain, "d": domain, "t": source_type, "g": tags},
            )

    moved = ensure_law_source_type(engine)
    assert moved == 2, "the legal and gazette catalogue rows, and nothing else"

    from sqlalchemy.orm import sessionmaker

    with sessionmaker(bind=engine, future=True)() as session:
        by_domain = {s.domain: s.source_type for s in session.query(Source).all()}
    assert by_domain["legislation.gov.uk"] == "law"
    assert by_domain["gazette.example.test"] == "law"
    # An IP office is a registry, not a law authority; case law is Q902's (e), not chosen.
    assert by_domain["wipo.int"] == "ip"
    assert by_domain["courts.example.test"] == "case_law"
    assert by_domain["someones-blog.example.test"] == "legal", (
        "a `legal` row from another catalogue is not this ruling's to move"
    )

    # Idempotent: the rows it would match no longer carry the old token.
    assert ensure_law_source_type(engine) == 0
    engine.dispose()
