"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

The parallel-session law-catalog enrichment channel (maintainer-ruled 2026-07-17;
docs/design/LAW_SOURCES_ACQUISITION_2026-07-17.md): the generated file merges into
the live catalog CURATED-WINS, rich metadata rides along untouched, absence is a
byte-identical no-op, and the offline validator catches the fabrication-shaped
mistakes (undated counts, non-https URLs, duplicate/overriding rows, missing
verification) while LISTING unverified leads for the maintainer instead of
silently accepting them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
# Load catalog.py directly (not via the src.law package __init__, whose corpus import
# pulls src.database.write — PEP-695 syntax that py3.11 sandboxes cannot parse). The
# module under test only needs yaml + models; the spec-load exercises the same code CI runs.
import importlib.util  # noqa: E402

import validate_legal_catalog as vlc  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "law_catalog_standalone", Path(__file__).resolve().parents[1] / "src" / "law" / "catalog.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
load_legal_catalog = _mod.load_legal_catalog
registration_source_rows = _mod.registration_source_rows
registrable_documents = _mod.registrable_documents

CURATED = {
    "sources": [
        {"name": "Légifrance (France)", "domain": "legifrance.gouv.fr", "country": "fr",
         "language": "fr", "source_type": "legal"},
    ],
    "documents": [
        {"jurisdiction": "fr", "title": "DDHC", "url": "https://ex.fr/ddhc",
         "official_url": "https://ex.fr/ddhc"},
    ],
}


def _gen_entry(**over) -> dict:
    base = {
        "name": "Cambodia — Ministry of Justice consolidated laws",
        "domain": "moj.gov.kh",
        "country": "kh",
        "languages": ["km", "fr"],
        "legal_language_note": "Major codes have official French versions.",
        "legal_system": "civil_law",
        "source_type": "legal",
        "kind": "consolidated_portal",
        "enumeration_url": "https://moj.gov.kh/codes",
        "official_count": {"value": 12, "unit": "codes", "as_of": "2026-07-18",
                           "source_url": "https://moj.gov.kh/codes"},
        "verification": {"status": "fetched", "retrieved_at": "2026-07-18",
                         "evidence": "loaded the enumeration page"},
        "confidence": "high",
    }
    base.update(over)
    return base


def _write(tmp_path, name, payload) -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return p


def test_generated_merges_curated_wins_and_metadata_rides_along(tmp_path):
    curated_p = _write(tmp_path, "curated.yml", CURATED)
    generated_p = _write(tmp_path, "gen.yml", {
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [
            _gen_entry(),
            # collides with curated on domain -> must be DROPPED (curated wins)
            _gen_entry(name="Legifrance override attempt", domain="legifrance.gouv.fr",
                       country="fr", languages=["fr"]),
        ],
        "documents": [
            {"jurisdiction": "fr", "title": "DDHC dup", "url": "https://ex.fr/ddhc",
             "verification": {"status": "fetched", "retrieved_at": "2026-07-18"}},
            {"jurisdiction": "kh", "title": "Cambodian Civil Code (fr)",
             "url": "https://moj.gov.kh/civil-code-fr",
             "verification": {"status": "fetched", "retrieved_at": "2026-07-18"}},
        ],
    })
    cat = load_legal_catalog(curated_p, generated_path=generated_p)
    domains = [s["domain"] for s in cat["sources"]]
    assert domains == ["legifrance.gouv.fr", "moj.gov.kh"], "curated wins; new row appended"
    assert cat["sources"][0]["name"] == "Légifrance (France)", "curated entry untouched"
    kh = cat["sources"][1]
    assert kh["languages"] == ["km", "fr"] and kh["enumeration_url"], "metadata rides along"
    assert kh["official_count"]["value"] == 12
    doc_keys = [(d["jurisdiction"], d["url"]) for d in cat["documents"]]
    assert doc_keys == [("fr", "https://ex.fr/ddhc"), ("kh", "https://moj.gov.kh/civil-code-fr")]


def test_no_generated_file_is_a_byte_identical_noop(tmp_path):
    curated_p = _write(tmp_path, "curated.yml", CURATED)
    absent = tmp_path / "absent.yml"
    assert load_legal_catalog(curated_p, generated_path=absent) == load_legal_catalog(
        curated_p, generated_path=absent
    )
    cat = load_legal_catalog(curated_p, generated_path=absent)
    assert len(cat["sources"]) == 1 and len(cat["documents"]) == 1


def test_validator_passes_a_clean_batch_and_tallies_verification():
    report = vlc.validate(
        {"schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
         "sources": [_gen_entry()], "documents": []},
        CURATED,
    )
    assert report["errors"] == []
    assert report["tally"]["fetched"] == 1 and report["leads"] == []


def test_validator_lists_leads_without_failing_them():
    entry = _gen_entry(verification={"status": "lead"})
    report = vlc.validate(
        {"schema": "oo-legal-catalog-gen-1", "as_of": "2026-07", "sources": [entry]},
        CURATED,
    )
    assert report["errors"] == [], "a lead is a maintainer decision, not a structural error"
    assert len(report["leads"]) == 1 and report["tally"]["lead"] == 1


def test_validator_catches_the_fabrication_shaped_mistakes():
    bad = {
        "schema": "wrong-schema", "as_of": "someday",
        "sources": [
            _gen_entry(country="france"),                              # not ISO-2
            _gen_entry(domain="dup.example"),
            _gen_entry(domain="dup.example"),                          # in-file dup (same role)
            _gen_entry(domain="legifrance.gouv.fr"),                   # overrides curated
            _gen_entry(enumeration_url="not-a-url"),                   # not a URL at all
            _gen_entry(official_count={"value": 76, "unit": "codes"}), # undated count
            _gen_entry(verification={"status": "trust-me"}),           # bad status
            {"name": "No verification", "domain": "x.example", "country": "xx",
             "languages": ["xx"], "source_type": "legal"},             # missing verification
        ],
        "documents": [
            # collides with the curated DDHC document -> curated wins, row must error
            {"jurisdiction": "fr", "title": "DDHC override", "url": "https://ex.fr/ddhc",
             "verification": {"status": "fetched", "retrieved_at": "2026-07-17"}},
        ],
    }
    report = vlc.validate(bad, CURATED)
    text = "\n".join(report["errors"])
    for needle in ("schema must be", "as_of must be", "ISO-2", "duplicate (domain, kind, country)",
                   "CURATED catalog", "https://", "never estimated",
                   "verification.status", "missing required field 'verification'",
                   "document already in the CURATED catalog"):
        assert needle in text, f"validator missed: {needle}\n{text}"


def test_generated_sources_register_disabled_and_lead_documents_never_register(tmp_path):
    """The review-before-enable posture (2026-07-17 CI catch): a research-harvested
    source must NEVER auto-enable at boot (several are robots-blocked), and an
    unverified lead document must never silently become a watched LawDocument."""
    curated_p = _write(tmp_path, "curated.yml", CURATED)
    gen_p = _write(tmp_path, "gen.yml", {
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [_gen_entry()],
        "documents": [
            {"jurisdiction": "tl", "title": "Código Civil",
             "url": "https://mj.example/cc.pdf",
             "verification": {"status": "fetched", "retrieved_at": "2026-07-17"}},
            {"jurisdiction": "ne", "title": "Recueil (lead)",
             "url": "https://justice.example/recueil.pdf",
             "verification": {"status": "lead"}},
        ],
    })
    cat = load_legal_catalog(curated_p, generated_path=gen_p)

    rows = {r["domain"]: r for r in registration_source_rows(cat)}
    gen_row = rows["moj.gov.kh"]
    assert gen_row["enabled"] is False, "a generated source must seed DISABLED"
    assert gen_row["_provenance"] == "legal-generated"
    assert "_generated" not in gen_row, "the marker never leaks into Source kwargs"
    cur_row = rows["legifrance.gouv.fr"]
    assert cur_row["_provenance"] == "legal" and "enabled" not in cur_row, \
        "curated entries keep their catalog-stated posture"

    doc_urls = [d["url"] for d in registrable_documents(cat)]
    assert "https://mj.example/cc.pdf" in doc_urls, "a fetched generated doc registers"
    assert "https://justice.example/recueil.pdf" not in doc_urls, "a lead never registers"
    assert "https://ex.fr/ddhc" in doc_urls, "curated docs register as before"


def test_validator_batch_calibrations_from_the_first_real_batches():
    """The 2026-07-17 first-8-batches calibration: descriptive structured fields,
    http-only warnings, two roles on one host, and the honest-gap domain-less lead."""
    doc = {
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [
            # structured.api/bulk are adapter-planning metadata: free text is fine
            _gen_entry(domain="freetext.example",
                       structured={"api": "Laws.Africa Content API v2, read-only",
                                   "bulk": "per-act PDF", "formats": ["pdf"]}),
            # an http-only official portal is recorded as found -> WARNING, never an error
            _gen_entry(domain="httponly.example",
                       enumeration_url="http://httponly.example/laws"),
            # one host, two ROLES (codes portal + gazette) = two rows, allowed
            _gen_entry(domain="tworoles.example", kind="consolidated_portal"),
            _gen_entry(domain="tworoles.example", kind="gazette"),
            # a multi-country platform (PacLII): one role, several jurisdictions, allowed
            _gen_entry(domain="paclii.example", kind="consolidated_portal", country="pg"),
            _gen_entry(domain="paclii.example", kind="consolidated_portal", country="sb"),
            # the honest-gap record: no working portal exists -> domain-less LEAD
            {"name": "Nowhere — no confirmed working portal", "country": "ye",
             "languages": ["ar"], "source_type": "gazette",
             "verification": {"status": "lead"}},
        ],
        "documents": [],
    }
    report = vlc.validate(doc, CURATED)
    assert report["errors"] == [], report["errors"]
    assert any("http-only" in w for w in report["warnings"])
    assert len(report["leads"]) == 1

    # ... but a domain-less row that CLAIMS verification is still an error
    gapless = dict(doc, sources=[{
        "name": "No domain but claims fetched", "country": "ye", "languages": ["ar"],
        "source_type": "gazette",
        "verification": {"status": "fetched", "retrieved_at": "2026-07-17"},
    }])
    report2 = vlc.validate(gapless, CURATED)
    assert any("missing required field 'domain'" in e for e in report2["errors"])
