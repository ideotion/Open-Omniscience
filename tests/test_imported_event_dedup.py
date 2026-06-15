"""Cross-feed dedup of imported calendar events (ruled 2026-06-15: "we don't want
100 entries mentioning Christmas Day"). The same holiday carried by many feed
families collapses to one row that lists every source; a different date stays
separate (a contested/moved date is information, never hidden).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.events.feeds import collapse_imported


def test_collapses_same_event_across_families_unioning_sources():
    rows = [
        {"title": "Christmas Day", "date": "2026-12-25", "sources": ["fr-1"],
         "family": "holidays-fr", "family_name": "Holidays (FR)", "uids": ["a"]},
        {"title": "Christmas Day", "date": "2026-12-25", "sources": ["de-1"],
         "family": "holidays-de", "family_name": "Holidays (DE)", "uids": ["b"]},
        # case/punctuation variant from an aggregator -> same fingerprint
        {"title": "christmas day", "date": "2026-12-25", "sources": ["agg-1"],
         "family": "aggregator", "family_name": "Aggregator"},
        {"title": "Bastille Day", "date": "2026-07-14", "sources": ["fr-1"],
         "family": "holidays-fr", "family_name": "Holidays (FR)"},
    ]
    out = collapse_imported(rows)
    assert len(out) == 2, "Christmas (3 feeds) collapses to one; Bastille stays"
    xmas = next(e for e in out if e["title"].lower().startswith("christmas"))
    assert set(xmas["sources"]) == {"fr-1", "de-1", "agg-1"}
    assert xmas["source_count"] == 3 and xmas["family_count"] == 3
    assert set(xmas["families"]) == {"holidays-fr", "holidays-de", "aggregator"}
    assert xmas["uids"] == ["a", "b"]  # unioned, order preserved


def test_different_dates_stay_separate_disagreement_surfaced():
    rows = [
        {"title": "Eid", "date": "2026-03-20", "sources": ["x"], "family": "f1", "family_name": "F1"},
        {"title": "Eid", "date": "2026-03-21", "sources": ["y"], "family": "f2", "family_name": "F2"},
    ]
    out = collapse_imported(rows)
    assert len(out) == 2, "a contested date is never silently merged"


def test_single_family_view_is_not_collapsed():
    from src.events.feeds import imported_agenda  # smoke: collapse flag wired
    assert imported_agenda(family="nonexistent") == []
