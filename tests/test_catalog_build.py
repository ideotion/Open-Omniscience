"""
Tests for the catalog generator orchestrator, coverage, and query config.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The orchestrator is driven by a fake `run_query` returning fixture payloads, so a
full multi-country generation is exercised with no network. Coverage maths and
the shipped query config are pinned too.
"""

from __future__ import annotations

from src.catalog.build import generate_catalog, load_query_config, write_catalog_yaml
from src.catalog.countries import ISO_3166_1_ALPHA2
from src.catalog.coverage import coverage_report


def _wd(name, url, lang=None):
    b = {"itemLabel": {"value": name}, "website": {"value": url}}
    if lang:
        b["lang"] = {"value": lang}
    return b


def test_generate_catalog_dedups_and_excludes(tmp_path):
    # Fixture WDQS payloads per country.
    payloads = {
        "fr": {
            "results": {
                "bindings": [
                    _wd("Le Example", "https://le-example.fr", "fr"),
                    _wd("Dup", "https://le-example.fr"),  # in-batch dup domain
                    _wd("Social", "https://twitter.com/x"),  # social -> excluded
                ]
            }
        },
        "jp": {
            "results": {
                "bindings": [
                    _wd("Example JP", "https://example.jp", "ja"),
                    _wd("Already Shipped", "https://shipped.test"),  # existing -> excluded
                ]
            }
        },
    }

    def run_query(cc, type_qids):
        assert type_qids  # specs pass real ids through
        return payloads[cc]

    specs = [{"source_type": "news", "type_qids": ["Q11032"], "tags": ["news"]}]
    res = generate_catalog(run_query, ["fr", "jp"], specs, existing_domains={"shipped.test"})
    domains = {s["domain"] for s in res["sources"]}
    assert domains == {"le-example.fr", "example.jp"}
    assert res["stats"]["skipped_dupes"] == 1
    assert res["stats"]["skipped_existing"] == 1
    assert res["stats"]["countries_queried"] == 2

    # And it writes the seeder-compatible YAML shape.
    out = write_catalog_yaml(tmp_path / "world.yml", res["sources"])
    import yaml

    loaded = yaml.safe_load(out.read_text())["sources"]
    assert {s["domain"] for s in loaded} == domains


def test_generate_catalog_records_errors_without_aborting():
    def run_query(cc, type_qids):
        if cc == "boom":
            raise RuntimeError("simulated WDQS timeout")
        return {"results": {"bindings": [_wd("OK", "https://ok.test")]}}

    specs = [{"source_type": "news", "type_qids": ["Q11032"], "tags": []}]
    res = generate_catalog(run_query, ["boom", "us"], specs)
    assert {s["domain"] for s in res["sources"]} == {"ok.test"}
    assert any("boom" in e for e in res["stats"]["errors"])


def test_coverage_report_counts_and_gaps():
    counts = {"fr": 5, "jp": 1, "zz": 9}  # zz not a real ISO code -> 'extra'
    rep = coverage_report(counts, thin_threshold=3)
    assert rep["total_countries"] == len(ISO_3166_1_ALPHA2)
    assert "fr" not in rep["missing"] and "jp" not in rep["missing"]
    assert "jp" in rep["thin"] and "fr" not in rep["thin"]
    assert "zz" in rep["extra_codes"]
    assert 0 <= rep["coverage_pct"] <= 100


def test_shipped_query_config_is_valid():
    cfg = load_query_config()
    assert cfg["specs"], "expected at least one spec"
    assert all(s["type_qids"] for s in cfg["specs"])
    types = {s["source_type"] for s in cfg["specs"]}
    assert "news" in types and "institution" in types
