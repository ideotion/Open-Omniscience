"""The zero-token feed verification stage, driven with a FAKE fetch -- no network.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

What is pinned: the three rules (parse, >= 3 titled+linked entries, one dated entry within
120 days) each rejecting on their own; the declared-link path and the conventional-path
fallback; robots as a verdict that stops the host; the duplicate that is never fetched; the
probe bound; the catalogue-entry schema with row-provenance tags stripped; and resumability.
"""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_MODULE = Path(os.environ.get("VCF_MODULE") or (_ROOT / "scripts" / "analysis" / "verify_candidate_feeds.py"))


def _load():
    import sys

    spec = importlib.util.spec_from_file_location("verify_candidate_feeds", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: `@dataclass` under `from __future__ import annotations`
    # resolves the class's module through sys.modules, and a module loaded from a path
    # without this line is not there (AttributeError: 'NoneType' has no '__dict__').
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vcf = _load()
from src.ingest import FetchFailed, RobotsDisallowed  # noqa: E402

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _rss(n: int, *, days_ago: int | None = 2, titled: bool = True) -> str:
    items = []
    for i in range(n):
        date = ""
        if days_ago is not None:
            d = NOW - timedelta(days=days_ago + i)
            date = f"<pubDate>{d.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>"
        title = f"<title>Council approves the new water plan after a long debate {i}</title>" if titled else ""
        items.append(f"<item>{title}<link>https://ex.example/a{i}</link>{date}</item>")
    return ('<?xml version="1.0"?><rss version="2.0"><channel><title>Ex</title>'
            + "".join(items) + "</channel></rss>")


HOME_WITH_LINK = """<html><head><title>  The Example  Gazette </title>
<meta name="description" content="Daily news from Exampleland">
<link rel="stylesheet" href="/s.css">
<link rel="alternate" type="application/rss+xml" title="RSS" href="/feed.xml">
<link rel="alternate" type="application/atom+xml" href="https://cdn.ex.example/atom">
</head><body></body></html>"""
HOME_PLAIN = "<html><head><title>Plain</title></head><body>hi</body></html>"


class Res:
    def __init__(self, content, final_url):
        self.content, self.final_url = content, final_url


class FakeFetch:
    """url -> content string, or an exception to raise; counts every call."""

    def __init__(self, table: dict):
        self.table, self.calls = table, []

    def __call__(self, url, *, require_html=True, **_):
        self.calls.append(url)
        hit = self.table.get(url)
        if hit is None:
            raise FetchFailed(f"404 {url}")
        if isinstance(hit, Exception):
            raise hit
        return Res(hit, url)


def _row(domain="ex.example", **kw):
    base = {"name": "The Example Gazette", "domain": domain, "source_type": "news",
            "country": "fr", "language": "fr", "tags": "news,world-catalog,via:wikidata-discovery"}
    base.update(kw)
    return base


# ------------------------------------------------------------------ pure parsing

def test_declared_feed_links_are_found_in_page_order_and_resolved():
    links = vcf.discover_feed_links(HOME_WITH_LINK, "https://ex.example/")
    assert links == ["https://ex.example/feed.xml", "https://cdn.ex.example/atom"]


def test_a_stylesheet_or_a_non_feed_link_is_never_a_feed():
    html = '<link rel="alternate" type="text/html" hreflang="fr" href="/fr"><link rel="icon" href="/i.png">'
    assert vcf.discover_feed_links(html, "https://ex.example/") == []


def test_site_meta_is_extracted_and_collapsed():
    title, desc = vcf.extract_site_meta(HOME_WITH_LINK)
    assert title == "The Example Gazette" and desc == "Daily news from Exampleland"


def test_the_three_rules_each_reject_on_their_own():
    ok, facts = vcf.evaluate_feed(vcf.parse_feed(_rss(4)), now=NOW)
    assert ok == "verified" and facts["entries"] == 4 and facts["newest_entry"].startswith("2026-09-08")
    assert vcf.evaluate_feed(vcf.parse_feed(_rss(2)), now=NOW)[0] == "feed_too_few_entries"
    assert vcf.evaluate_feed(vcf.parse_feed(_rss(4, days_ago=200)), now=NOW)[0] == "feed_stale"
    assert vcf.evaluate_feed(vcf.parse_feed(_rss(4, days_ago=None)), now=NOW)[0] == "feed_undated"
    assert vcf.evaluate_feed(vcf.parse_feed("<html>not a feed</html>"), now=NOW)[0] == "feed_unparseable"
    assert vcf.evaluate_feed(vcf.parse_feed(_rss(4, titled=False)), now=NOW)[0] == "feed_too_few_entries"


# ------------------------------------------------------------------ one candidate

def test_verified_through_the_declared_link():
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)})
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.status == "verified" and v.reason == "verified"
    assert v.feed_url == "https://ex.example/feed.xml" and v.feed_kind == "link"
    assert v.entries == 5 and v.robots == "allowed" and v.site_title == "The Example Gazette"
    assert v.feed_probes == 1 and len(fetch.calls) == 2


def test_verified_through_a_conventional_path_when_the_page_declares_nothing():
    fetch = FakeFetch({"https://ex.example/": HOME_PLAIN, "https://ex.example/rss": _rss(4)})
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.status == "verified" and v.feed_kind == "conventional"
    assert v.feed_url == "https://ex.example/rss"


def test_robots_refusal_is_a_verdict_and_stops_the_host():
    fetch = FakeFetch({"https://ex.example/": RobotsDisallowed("robots says no")})
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.status == "rejected" and v.reason == "robots_disallowed" and v.robots == "disallowed"
    assert fetch.calls == ["https://ex.example/"]


def test_a_catalogue_duplicate_is_never_fetched():
    fetch = FakeFetch({})
    v = vcf.verify_candidate(_row(domain="www.bbc.co.uk"), fetch=fetch, now=NOW,
                             catalogue={"bbc.com", "bbc.co.uk"}, seen=set())
    assert v.reason == "duplicate_of_catalogue" and fetch.calls == []


def test_an_unreachable_homepage_falls_back_to_http_then_rejects():
    fetch = FakeFetch({})
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.reason == "homepage_unreachable"
    assert fetch.calls == ["https://ex.example/", "http://ex.example/"]


def test_feed_probes_are_bounded_per_host():
    html = "".join(f'<link rel="alternate" type="application/rss+xml" href="/f{i}">' for i in range(3))
    table = {"https://ex.example/": html}
    fetch = FakeFetch(table)  # every feed probe 404s
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.status == "rejected" and v.reason == "no_feed_found"
    assert v.feed_probes == vcf.MAX_FEED_PROBES
    assert len(fetch.calls) == 1 + vcf.MAX_FEED_PROBES


def test_a_parsed_but_stale_feed_reports_stale_not_missing():
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(4, days_ago=300)})
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.status == "rejected" and v.reason == "feed_stale" and v.newest_entry.startswith("2025")


def test_language_is_detected_from_the_headlines_or_falls_back_to_the_export_with_its_basis():
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(8)})
    v = vcf.verify_candidate(_row(language="fr"), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert v.status == "verified"
    from src.analytics.langdetect import detector_available

    if detector_available():
        # eight English headlines clear the detector's floors -> detected, and it overrides the export
        assert (v.language_detected, v.language_basis) == ("en", "detected")
    else:
        # a core install (no [analysis] extra -- the CI core-only lane): the detector honestly
        # answers nothing, so the export's value stands and the basis SAYS so. Never a guess.
        assert (v.language_detected, v.language_basis) == ("fr", "export")
    short = FakeFetch({"https://ex.example/": HOME_PLAIN, "https://ex.example/rss": _rss(3)})
    v2 = vcf.verify_candidate(_row(language="fr"), fetch=short, now=NOW, catalogue=set(), seen=set())
    assert v2.status == "verified" and (v2.language_detected, v2.language_basis) == ("fr", "export")
    v3 = vcf.verify_candidate(_row(language=""), fetch=FakeFetch({"https://ex.example/": HOME_PLAIN, "https://ex.example/rss": _rss(3)}),
                              now=NOW, catalogue=set(), seen=set())
    assert (v3.language_detected, v3.language_basis) == ("", "unknown")


# ------------------------------------------------------------------ outputs

def test_a_catalogue_entry_carries_the_brief_schema_and_no_row_tags():
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)})
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    e = vcf.to_catalogue_entry(v, today="2026-09-10")
    assert e["domain"] == "ex.example" and e["rss_url"] == "https://ex.example/feed.xml"
    assert e["verified"] is True and e["last_verified"] == "2026-09-10" and e["enabled"] is True
    assert e["country"] == "fr" and e["region"] == "europe" and e["source_type"] == "news"
    assert e["tags"] == ["news"] and e["priority"] == 3 and e["rate_limit_ms"] == 2000


def test_an_unknown_country_is_omitted_and_region_stays_global():
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)})
    v = vcf.verify_candidate(_row(country=""), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    e = vcf.to_catalogue_entry(v, today="2026-09-10")
    assert "country" not in e and e["region"] == "global"


def test_only_a_verified_verdict_becomes_an_entry():
    v = vcf.Verdict(domain="x.example", status="rejected", reason="feed_stale")
    with pytest.raises(ValueError):
        vcf.to_catalogue_entry(v, today="2026-09-10")


def test_run_writes_the_outputs_and_resumes_without_refetching(tmp_path):
    rows = [_row("a.example", name="A"), _row("b.example", name="B"), _row("c.example", name="C")]
    table = {
        "https://a.example/": HOME_PLAIN, "https://a.example/feed": _rss(4),
        "https://b.example/": HOME_PLAIN,  # no feed anywhere
        "https://c.example/": RobotsDisallowed("no"),
    }
    fetch = FakeFetch(table)
    summary = vcf.run(rows, fetch=fetch, out_dir=tmp_path, workers=2, now=NOW)
    assert summary["candidates"] == 3 and summary["verified"] == 1
    assert summary["by_reason"] == {"no_feed_found": 1, "robots_disallowed": 1, "verified": 1}
    doc = yaml.safe_load((tmp_path / "verified_sources.yml").read_text(encoding="utf-8"))
    assert [s["domain"] for s in doc["sources"]] == ["a.example"]
    rejected = (tmp_path / "rejections.csv").read_text(encoding="utf-8")
    assert "b.example" in rejected and "c.example" in rejected and "a.example" not in rejected
    # resume: nothing is fetched again, and the regenerated outputs still hold every verdict
    fetch2 = FakeFetch(table)
    again = vcf.run(rows + [_row("d.example", name="D")], fetch=fetch2, out_dir=tmp_path, workers=2, now=NOW)
    assert fetch2.calls and all(u.startswith(("https://d.example", "http://d.example")) for u in fetch2.calls)
    assert again["candidates"] == 4 and again["verified"] == 1


def test_a_duplicate_within_the_run_is_judged_once(tmp_path):
    rows = [_row("a.example"), _row("www.a.example"), _row("A.EXAMPLE")]
    fetch = FakeFetch({"https://a.example/": HOME_PLAIN, "https://a.example/feed": _rss(4)})
    summary = vcf.run(rows, fetch=fetch, out_dir=tmp_path, workers=1, now=NOW)
    assert summary["candidates"] == 1 and summary["verified"] == 1
