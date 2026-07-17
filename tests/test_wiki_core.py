"""
Tests for the Wikipedia MediaWiki parser + edit-flagging (pure, no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.wiki.flagging import flag_revision
from src.wiki.mediawiki import (
    api_endpoint,
    build_revisions_params,
    parse_compare,
    parse_recentchanges,
    parse_revisions,
)


def test_api_endpoint_per_language():
    assert api_endpoint("en") == "https://en.wikipedia.org/w/api.php"
    assert api_endpoint("FR") == "https://fr.wikipedia.org/w/api.php"


def test_build_revisions_params():
    p = build_revisions_params("Berlin", limit=10, older_than=123)
    assert p["titles"] == "Berlin" and p["rvlimit"] == 10
    assert p["rvstartid"] == 123 and p["formatversion"] == 2


def test_parse_revisions_v2():
    payload = {
        "query": {
            "pages": [
                {
                    "pageid": 5,
                    "title": "Berlin",
                    "revisions": [
                        {
                            "revid": 200,
                            "parentid": 199,
                            "timestamp": "2024-03-02T10:00:00Z",
                            "user": "Alice",
                            "comment": "expand",
                            "size": 5200,
                            "minor": False,
                            "tags": ["mobile edit"],
                        },
                        {
                            "revid": 199,
                            "parentid": 198,
                            "timestamp": "2024-03-01T10:00:00Z",
                            "user": "1.2.3.4",
                            "anon": True,
                            "comment": "",
                            "size": 4000,
                            "minor": True,
                            "tags": [],
                        },
                    ],
                }
            ]
        }
    }
    revs = parse_revisions(payload)
    assert revs[0]["revid"] == 200 and revs[0]["size"] == 5200
    assert revs[0]["timestamp"].year == 2024
    assert revs[1]["editor_anon"] is True and revs[1]["minor"] is True


def test_parse_recentchanges_computes_delta():
    payload = {
        "query": {
            "recentchanges": [
                {
                    "revid": 10,
                    "old_revid": 9,
                    "title": "Climate change",
                    "type": "edit",
                    "user": "Bob",
                    "timestamp": "2024-03-03T00:00:00Z",
                    "oldlen": 5000,
                    "newlen": 3000,
                    "tags": ["mw-reverted"],
                },
            ]
        }
    }
    rc = parse_recentchanges(payload)
    assert rc[0]["delta_bytes"] == -2000 and rc[0]["tags"] == ["mw-reverted"]


def test_parse_compare_extracts_added_removed():
    body = (
        "<tr><td class='diff-deletedline'>old sentence here</td>"
        "<td class='diff-addedline'>new replacement sentence</td></tr>"
    )
    payload = {"compare": {"body": body}}
    d = parse_compare(payload)
    assert "old sentence" in d["removed"] and "new replacement" in d["added"]
    assert d["added_bytes"] > 0 and d["removed_bytes"] > 0


# --------------------------------------------------------------------------- #
# flagging
# --------------------------------------------------------------------------- #


def test_large_removal_flagged():
    r = flag_revision(delta_bytes=-1500, tags=[])
    assert r.flagged and "large_removal" in r.reasons


def test_revert_tag_flagged_even_if_small():
    r = flag_revision(delta_bytes=-50, tags=["mw-reverted"], minor=True)
    assert r.flagged and "revert" in r.reasons


def test_minor_cosmetic_edit_not_flagged():
    r = flag_revision(delta_bytes=12, tags=[], minor=True)
    assert not r.flagged and r.reasons == []


def test_anon_medium_edit_flagged():
    r = flag_revision(delta_bytes=-500, tags=[], editor_anon=True)
    assert r.flagged and "anon_large" in r.reasons


def test_ores_damaging_flagged():
    r = flag_revision(delta_bytes=20, tags=[], ores_damaging=0.92)
    assert r.flagged and "ores_damaging" in r.reasons


def test_burst_flagged():
    r = flag_revision(delta_bytes=100, tags=[], burst_count=6)
    assert r.flagged and "burst" in r.reasons


def test_burst_flagged_even_if_small_and_minor():
    """Audit finding 2026-07-17 (L2): burst_count is computed server-side from the
    fetched revision batch, NOT self-declared like `minor` -- so a burst must stand
    even when every edit in it is small and self-tagged "minor" (the same principle
    test_revert_tag_flagged_even_if_small already pins for revert tags). Before the
    fix this silently evaporated: a bad-faith burst of tiny "minor"-tagged edits
    could reach any burst_count and never be flagged."""
    r = flag_revision(delta_bytes=50, tags=[], minor=True, burst_count=6)
    assert r.flagged and "burst" in r.reasons
