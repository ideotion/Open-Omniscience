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


def test_generated_sources_enable_by_default_and_lead_documents_never_register(tmp_path):
    """Maintainer ruling 2026-07-17: the merged catalog is maintainer-vetted (the PR
    review IS the gate), so generated sources ENABLE by default — the end user never
    hand-enables anything. Robots stays fail-closed and the bounded preflight verifies
    domains automatically. The one exclusion is about unverified fetch TARGETS, not user
    convenience: a lead document never silently becomes a watched LawDocument.

    AMENDED 2026-09-07 (S2): the docstring used to add "safe by construction: no rss_url
    → collect passes never fetch them". That is no longer true of every row — three rows
    whose OWN gazette_feed_verification records a fetched feed now carry an rss_url, on
    purpose (see the S2 block at the foot of this file). Updated deliberately rather than
    left standing, because a stale safety sentence reads as a guarantee; the enable-by-
    default posture this test is actually about is unchanged."""
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
    assert "enabled" not in gen_row, \
        "a generated source enables by default (the Source model default), never forced off"
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


# ---------------------------------------------------------------------------
# S2 (law-vertical brief 2026-07-17, built 2026-09-07): a verified gazette feed
# becomes an ordinary rss_url, and an UNVERIFIED one never does.
#
# The negative direction is the load-bearing one here. Over-eager wiring is not a
# broken fetch, it is a FABRICATED COVERAGE CLAIM: impo.com.uy's gazette_feed is the
# site's generic WordPress news feed, so promoting it would file Uruguayan site news
# posts in the corpus as that country's official gazette. Every assertion below
# therefore has its twin.
# ---------------------------------------------------------------------------

feed_rss_url = _mod.feed_rss_url

_FETCHED_FEED = {
    "status": "fetched",
    "retrieved_at": "2026-07-17",
    "evidence": "fetched the feed; well-formed RSS 2.0 with dated items",
}
_LEAD_FEED = {"status": "lead", "evidence": "NOT FETCHED — the URL was written down, never asked"}


def test_a_fetched_gazette_feed_becomes_an_rss_url_and_a_lead_one_never_does():
    fetched = _gen_entry(
        domain="gazette.example", gazette_feed="https://gazette.example/rss",
        gazette_feed_verification=dict(_FETCHED_FEED),
    )
    lead = _gen_entry(
        domain="newsfeed.example", gazette_feed="https://newsfeed.example/feed/",
        gazette_feed_verification=dict(_LEAD_FEED),
    )
    assert feed_rss_url(fetched) == "https://gazette.example/rss"
    assert feed_rss_url(lead) is None, (
        "a feed nobody fetched must never be promoted — that is how a site's news feed "
        "becomes 'the official gazette'"
    )


def test_a_row_level_fetched_status_is_not_the_feeds_status():
    """The whole reason gazette_feed_verification exists. Both rows below are
    ``verification.status: fetched`` at ROW level — that is a claim about the portal.
    Only the feed's OWN tier may decide the feed."""
    row = _gen_entry(
        domain="portal.example", gazette_feed="https://portal.example/feed/",
        verification={"status": "fetched", "retrieved_at": "2026-07-17",
                      "evidence": "loaded the portal's contents page"},
        gazette_feed_verification=dict(_LEAD_FEED),
    )
    assert row["verification"]["status"] == "fetched"
    assert feed_rss_url(row) is None


def test_a_gazette_feed_with_no_tier_at_all_is_never_promoted():
    """The pre-2026-09-07 shape. Absent tier is not permission."""
    assert feed_rss_url(_gen_entry(domain="x.example", gazette_feed="https://x.example/rss")) is None


def test_an_explicit_rss_url_always_wins_over_a_feed():
    row = _gen_entry(
        domain="both.example", rss_url="https://both.example/curated.xml",
        gazette_feed="https://both.example/other.rss",
        gazette_feed_verification=dict(_FETCHED_FEED),
    )
    assert feed_rss_url(row) is None, "this only ever fills an absence, never overrides"


def test_registration_carries_the_promoted_feed_and_only_that_one(tmp_path):
    curated_p = _write(tmp_path, "curated.yml", CURATED)
    gen_p = _write(tmp_path, "gen.yml", {
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [
            _gen_entry(domain="gazette.example", gazette_feed="https://gazette.example/rss",
                       gazette_feed_verification=dict(_FETCHED_FEED)),
            _gen_entry(domain="newsfeed.example", gazette_feed="https://newsfeed.example/feed/",
                       gazette_feed_verification=dict(_LEAD_FEED)),
            _gen_entry(domain="plain.example"),
        ],
        "documents": [],
    })
    rows = {r["domain"]: r for r in registration_source_rows(
        load_legal_catalog(curated_p, generated_path=gen_p))}
    assert rows["gazette.example"]["rss_url"] == "https://gazette.example/rss"
    assert "rss_url" not in rows["newsfeed.example"]
    assert "rss_url" not in rows["plain.example"], (
        "a row with no feed at all must stay feedless — 222 of the 225 generated rows are "
        "this case and a collect pass must not start polling them"
    )


def test_the_validator_requires_a_tier_on_every_gazette_feed():
    report = vlc.validate({
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [_gen_entry(domain="untiered.example",
                               gazette_feed="https://untiered.example/rss")],
    }, CURATED)
    assert any("must carry gazette_feed_verification" in e for e in report["errors"])

    # ANTI-VACUITY: the same row WITH a tier must pass, or the rule above is satisfied
    # by anything at all and says nothing about tiers.
    ok = vlc.validate({
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [_gen_entry(domain="tiered.example", gazette_feed="https://tiered.example/rss",
                               gazette_feed_verification=dict(_FETCHED_FEED))],
    }, CURATED)
    assert not ok["errors"], ok["errors"]


def test_the_validator_rejects_a_malformed_tier_in_each_direction():
    def _errs(**over):
        return vlc.validate({
            "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
            "sources": [_gen_entry(domain="f.example", gazette_feed="https://f.example/rss", **over)],
        }, CURATED)["errors"]

    # "search-verified" is deliberately NOT a feed tier: a search snippet cannot say a
    # URL serves a parseable feed, so admitting it would create a tier nothing can mean.
    assert any("status must be one of" in e for e in
               _errs(gazette_feed_verification={"status": "search-verified", "evidence": "snippet"}))
    assert any("retrieved_at" in e for e in _errs(
        gazette_feed_verification={"status": "fetched", "evidence": "fetched it"}))
    assert any("evidence is required" in e for e in _errs(
        gazette_feed_verification={"status": "fetched", "retrieved_at": "2026-07-17"}))
    # And a tier with no feed is also incoherent.
    orphan = vlc.validate({
        "schema": "oo-legal-catalog-gen-1", "as_of": "2026-07",
        "sources": [_gen_entry(domain="o.example", gazette_feed_verification=dict(_FETCHED_FEED))],
    }, CURATED)["errors"]
    assert any("without a gazette_feed" in e for e in orphan)


def test_the_shipped_catalog_promotes_exactly_the_three_fetched_feeds():
    """A guard on the SHIPPED DATA, not on the mechanism: this is the assertion that
    would redden if someone gave impo.com.uy a `fetched` tier without fetching it, or
    dropped a real one. Named domains, because which four rows carry a feed is a fact
    about this dated harvest, not a moving target."""
    rows = {r["domain"]: r for r in registration_source_rows(load_legal_catalog())}
    with_feed = {d: r for d, r in rows.items() if r.get("gazette_feed")}
    assert set(with_feed) == {
        "matsne.gov.ge", "impo.com.uy", "congbao.chinhphu.vn", "legal.gov.vc"
    }, sorted(with_feed)
    promoted = {d for d, r in rows.items() if r.get("rss_url")}
    assert promoted == {"matsne.gov.ge", "congbao.chinhphu.vn", "legal.gov.vc"}, sorted(promoted)
    assert "rss_url" not in rows["impo.com.uy"], (
        "impo.com.uy's feed is the site's generic WordPress news feed and was never "
        "fetched — its own notes say to verify before relying on it for gazette monitoring"
    )
