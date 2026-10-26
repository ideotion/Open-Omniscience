"""Every /api/quarantine route is named in docs/QUALIFICATION.md (qualification lane, 2026-10-26).

The reports are read by an operator who is told to look at samples before applying anything; a report
nobody is told about is one nobody reads. Anchored to the router's own source, never to the shared app."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_quarantine_route_is_named_in_the_qualification_doc():
    src = (ROOT / "src" / "api" / "quarantine.py").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "QUALIFICATION.md").read_text(encoding="utf-8")
    paths = set(re.findall(r'@router\.(?:get|post)\("(/[^"]*)"', src))
    assert paths, "router source no longer parsed"
    missing = sorted(p for p in paths if f"/api/quarantine{p}" not in doc)
    assert not missing, f"routes missing from docs/QUALIFICATION.md: {missing}"


def test_the_doc_keeps_the_dry_run_first_and_report_only_statements():
    doc = (ROOT / "docs" / "QUALIFICATION.md").read_text(encoding="utf-8")
    for phrase in ("write=false", "REPORT-ONLY", "never deletes", "no network call"):
        assert phrase in doc
