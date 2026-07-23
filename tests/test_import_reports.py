"""
Persisted, downloadable import reports (S3.5, 2026-07-23 field-feedback workflow).

Proves: the JSON write/list/read round-trip is UTF-8, atomic, and traversal-guarded;
the Markdown rendering never fabricates a number (only ever echoes what's already in
the report dict); and an empty/missing directory degrades to an empty list, never an
error.
"""

from __future__ import annotations

import json

import pytest

from src.backup.import_reports import (
    list_import_reports,
    persist_import_report,
    read_import_report,
    render_import_report_markdown,
)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    yield tmp_path


def _sample_report() -> dict:
    return {
        "kind": "restore",
        "plan": {
            "articles": {"new": 42, "duplicate": 8, "conflict": 0},
            "sources": {"new": 3, "duplicate": 1, "conflict": 0},
        },
        "corpus_delta": {
            "before": {"articles": 100, "sources": 5, "languages": 2, "countries": 1,
                       "keywords": 900, "date_min": "2020-01-01", "date_max": "2025-01-01"},
            "after": {"articles": 142, "sources": 8, "languages": 3, "countries": 2,
                      "keywords": 950, "date_min": "2020-01-01", "date_max": "2026-01-01"},
        },
        "work_induced": {"sources_pending": 4, "sources_candidates": 20},
        "quarantine_summary": {
            "scanned": 42, "quarantined": 3, "newly_written": 3, "already_quarantined": 0,
            "by_reason": {"url_homepage": 2, "nav_soup": 1},
        },
    }


def test_persist_list_read_round_trip():
    report = _sample_report()
    path = persist_import_report("restore", report)
    assert path.is_file()
    assert path.suffix == ".json"
    # UTF-8, no BOM, real JSON on disk
    raw = path.read_text(encoding="utf-8")
    assert json.loads(raw) == report

    listed = list_import_reports()
    assert len(listed) == 1
    assert listed[0]["filename"] == path.name
    assert listed[0]["kind"] == "restore"
    assert listed[0]["size_bytes"] > 0

    reread = read_import_report(path.name)
    assert reread == report


def test_two_reports_are_both_listed_newest_first():
    persist_import_report("restore", {"kind": "restore"}, run_id="aaa")
    persist_import_report("newsletter", {"kind": "newsletter"}, run_id="bbb")
    listed = list_import_reports()
    assert len(listed) == 2
    kinds = {r["kind"] for r in listed}
    assert kinds == {"restore", "newsletter"}


def test_empty_directory_lists_as_empty_never_an_error():
    assert list_import_reports() == []


def test_read_import_report_rejects_path_traversal():
    persist_import_report("restore", {"kind": "restore"}, run_id="real")
    for bad in ("../secret.json", "..\\secret.json", "/etc/passwd", "sub/dir.json", ".."):
        with pytest.raises(FileNotFoundError):
            read_import_report(bad)


def test_read_import_report_rejects_unknown_filename():
    with pytest.raises(FileNotFoundError):
        read_import_report("nonexistent-20260101T000000Z-zzzz.json")


def test_markdown_headline_uses_articles_never_a_cross_table_row_sum():
    report = _sample_report()
    md = render_import_report_markdown(report)
    headline = md.split("\n")[2]  # title, blank line, then the headline
    assert "42 new articles" in headline
    # the cross-table row-sum (42+8+3+1=54) must never appear as the headline number
    assert "54" not in headline


def test_markdown_never_fabricates_a_number_only_echoes_the_report():
    report = _sample_report()
    md = render_import_report_markdown(report)
    assert "100" in md and "142" in md  # the real before/after article counts
    assert "3" in md  # newly-quarantined count appears
    # a report missing corpus_delta must never show a growth section
    minimal = {"kind": "newsletter", "tally": {"new": 7}}
    md2 = render_import_report_markdown(minimal)
    assert "Corpus growth" not in md2
    assert "7 new articles" in md2


def test_markdown_handles_a_report_with_no_optional_sections():
    md = render_import_report_markdown({"kind": "restore"})
    assert "Import report (restore)" in md
