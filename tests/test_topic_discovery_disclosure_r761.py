"""Discover by topic says everything it contacts, and the saying is tied to the fetching (row 224, R761).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The disclosure used to name ``html.duckduckgo.com`` "and only that host", while the action then visits each
site the search returns: its robots.txt, the page, the feed links it names, and 19 common feed addresses. This
changes the DISCLOSURE only; the fetch set is the one main had. What stops the two drifting apart again:

- the probes are ONE constant, ``FEED_PROBE_PATHS``, and the consent popup's table carries exactly it;
- a run of the real ``discover_sources_by_topic`` over a recording fetcher reaches only the result sites, and
  only at the result page, a feed link that page names, or one of those probes (robots.txt is the fetcher's own
  read, which the disclosure names too);
- the "Discover by topic" row of ``docs/SECURITY.md`` names every probe;
- the hover, the visible row and the Settings texts say "each site the search returns", keyed in all twelve
  locales and translated (a consent string left in English is not consent in eleven languages).

Mutation-checked by hand: a 20th probe added to the constant reddens the table and SECURITY.md checks; a probe
written as a literal inside ``discover_rss_feeds`` instead reddens the run; the hover sentence dropped from
``_laneHostTitle`` reddens the hover check.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from src.services import duckduckgo as ddg
from tests.js_source_helper import array_literal

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"

HOVER = (
    "then each site the search returns: its robots.txt, its page, the feed links it names (which may sit on "
    "another site), and these feed addresses on it:"
)
ROW = "+ each site the search returns"
SETTINGS = (
    "External topic discovery is the one feature that sends a free-text search query to an external service: it "
    "sends your topic query to DuckDuckGo to find candidate outlets, then visits each site the search returns (its "
    "robots.txt, its page, the feed links it names and common feed addresses such as /rss and /feed) to look for a "
    "feed."
)
STRONG = "Your query leaves this machine, and each of those sites sees your visit."
CHECKBOX = "Allow topic-discovery queries to DuckDuckGo and visits to the sites it returns"
CONFIRM = (
    "Send your topic-discovery queries to DuckDuckGo and visit each site it returns? Your query leaves this "
    "machine, and each of those sites sees your visit."
)
ENABLED = "Enabled: topic-discovery queries will be sent to DuckDuckGo, and each site it returns will be visited."
KEYS = (HOVER, ROW, SETTINGS, STRONG, CHECKBOX, CONFIRM, ENABLED)


def _lane() -> dict:
    lanes = json.loads(array_literal((STATIC / "net-hosts.js").read_text(encoding="utf-8"), "OO_NET_LANES"))
    (lane,) = [x for x in lanes if x["id"] == "topic-discovery"]
    return lane


def test_the_consent_table_carries_exactly_the_probes_the_code_makes():
    lane = _lane()
    assert lane["resultSites"] is True
    assert lane["probePaths"] == list(ddg.FEED_PROBE_PATHS)
    assert len(set(ddg.FEED_PROBE_PATHS)) == len(ddg.FEED_PROBE_PATHS) == 19
    # The search host stays the one host the SEARCH session may reach; the result sites are a class, not hosts.
    assert lane["hosts"] == ["html.duckduckgo.com"]


class _Resp:
    def __init__(self, content: str, content_type: str):
        self.content = content
        self.content_type = content_type


class _RecordingFetcher:
    """Answers every page with HTML naming one same-site and one off-site feed link; every feed-shaped path with RSS."""

    def __init__(self, log: list[str]):
        self.log = log

    def fetch(self, url: str, require_html: bool = True):
        self.log.append(url)
        if require_html:
            return _Resp(
                '<html><head><link rel="alternate" type="application/rss+xml" href="/own-feed.xml">'
                '<link rel="alternate" type="application/rss+xml" href="https://feeds.elsewhere.test/x.rss">'
                "</head></html>",
                "text/html",
            )
        return _Resp("<?xml version='1.0'?><rss version='2.0'></rss>", "application/rss+xml")


def test_the_action_reaches_only_what_the_disclosure_names(monkeypatch):
    results = [
        {"title": "A", "url": "https://a.example/news/story", "domain": "a.example"},
        {"title": "A again", "url": "https://a.example/other", "domain": "a.example"},  # same domain: not revisited
        {"title": "B", "url": "https://b.example/", "domain": "b.example"},
    ]
    monkeypatch.setattr(ddg.DuckDuckGoSearch, "search", classmethod(lambda cls, *a, **k: results))
    log: list[str] = []
    import src.safety.fetcher as fetcher_mod

    monkeypatch.setattr(fetcher_mod, "make_fetcher", lambda *a, **k: _RecordingFetcher(log))

    found = ddg.DuckDuckGoSearch.discover_sources_by_topic("press freedom")
    assert [s["domain"] for s in found] == ["a.example", "b.example"]

    linked = {"https://feeds.elsewhere.test/x.rss"}
    for site in ("https://a.example/news/story", "https://b.example/"):
        base = urlsplit(site)
        on_site = {u for u in log if urlsplit(u).netloc == base.netloc}
        paths = {urlsplit(u).path for u in on_site}
        allowed = {base.path, "/own-feed.xml", *ddg.FEED_PROBE_PATHS}
        assert paths <= allowed, f"{base.netloc}: fetched paths the disclosure does not name: {sorted(paths - allowed)}"
        assert set(ddg.FEED_PROBE_PATHS) <= paths, "every named probe is made"
    hosts = {urlsplit(u).netloc for u in log}
    assert hosts == {"a.example", "b.example", "feeds.elsewhere.test"}, (
        "only the result sites and the feed links their pages name"
    )
    assert {u for u in log if urlsplit(u).netloc == "feeds.elsewhere.test"} == linked
    assert "https://a.example/other" not in log


def test_the_security_row_names_every_probe_and_the_result_sites():
    text = (ROOT / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    (row,) = [ln for ln in text.splitlines() if ln.startswith("| **Discover by topic** |")]
    hosts_cell = row.split(" | ")[1]
    assert "each site the search returns" in hosts_cell.lower()
    assert "`/robots.txt`" in hosts_cell
    named = set(re.findall(r"`(/[^`]+)`", hosts_cell)) - {"/robots.txt"}
    assert named == set(ddg.FEED_PROBE_PATHS)
    assert "and only that host" not in row


def test_the_hover_and_the_visible_row_say_it_before_the_click():
    core = (STATIC / "app-core.js").read_text(encoding="utf-8")
    title = core[core.index("function _laneHostTitle(") : core.index("function _laneLine(")]
    assert "lane.resultSites" in title and "lane.probePaths" in title
    assert 't("' + HOVER + '")' in title
    line = core[core.index("function _laneLine(") : core.index("function _renderNetLanes(")]
    assert "lane.resultSites" in line and 't("' + ROW + '")' in line


def test_the_settings_texts_name_the_result_sites():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "<span>" + SETTINGS + "</span>" in html
    assert "<strong>" + STRONG + "</strong>" in html
    assert CHECKBOX in html
    backup = (STATIC / "app-backup.js").read_text(encoding="utf-8")
    assert 'confirm(t("' + CONFIRM + '"))' in backup
    assert 't("' + ENABLED + '")' in backup


@pytest.mark.parametrize("path", sorted((STATIC / "locales").glob("*.json")), ids=lambda p: p.stem)
def test_every_disclosure_string_is_keyed_and_translated(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in KEYS if k not in d]
    assert not missing, missing
    if path.stem != "en":
        english = [k for k in KEYS if d[k] == k]
        assert not english, f"{path.stem} leaves a consent string in English: {english}"
        for k in (HOVER, ROW, SETTINGS, CONFIRM, ENABLED):
            assert "DuckDuckGo" in d[k] or k in (HOVER, ROW), (path.stem, k)
        assert "robots.txt" in d[HOVER] and "robots.txt" in d[SETTINGS]
        assert "/rss" in d[SETTINGS] and "/feed" in d[SETTINGS]
