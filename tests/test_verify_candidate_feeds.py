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


def test_a_harvested_name_never_claims_a_country_the_row_denies():
    """``3CatInfo (tv)``, measured on the 2026-09-11 remainder chunk: the Catalan public
    broadcaster, whose ``(tv)`` branding the catalogue's ``Name (Country)`` convention reads as
    Tuvalu while the row's own country says ``es``. It tripped
    test_catalog_honours_its_own_country_suffix_convention AFTER the splice, which is one step
    too late, so the name is normalised where the entry is BUILT."""
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)})
    v = vcf.verify_candidate(_row(name="3CatInfo (tv)"), fetch=fetch, now=NOW, catalogue=set(), seen=set())
    assert vcf.to_catalogue_entry(v, today="2026-09-10")["name"] == "3CatInfo"

    # An agreeing suffix is the convention itself and is KEPT.
    v2 = vcf.verify_candidate(_row(name="Le Monde (France)"), fetch=FakeFetch(
        {"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)}),
        now=NOW, catalogue=set(), seen=set())
    assert vcf.to_catalogue_entry(v2, today="2026-09-10")["name"] == "Le Monde (France)"

    # A parenthetical that is no country at all is not the convention's business.
    v3 = vcf.verify_candidate(_row(name="Kyodo News (English)"), fetch=FakeFetch(
        {"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)}),
        now=NOW, catalogue=set(), seen=set())
    assert vcf.to_catalogue_entry(v3, today="2026-09-10")["name"] == "Kyodo News (English)"


def test_a_country_suffix_with_no_country_on_the_row_is_dropped_too():
    """Nothing on the row supports the claim, so the name must not make it -- and the entry
    still keeps a usable name rather than collapsing to the bare domain."""
    fetch = FakeFetch({"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(5)})
    v = vcf.verify_candidate(_row(name="Island Radio (tv)", country=""), fetch=fetch, now=NOW,
                             catalogue=set(), seen=set())
    e = vcf.to_catalogue_entry(v, today="2026-09-10")
    assert "country" not in e and e["name"] == "Island Radio"

    # A name that is NOTHING BUT the suffix keeps it: stripping would leave no name at all.
    assert vcf._name_without_a_false_country("(tv)", "es") == "(tv)"


def test_sharding_partitions_the_worklist_exactly_once_and_never_splits_a_host():
    """Eight VMs on one worklist. The two properties that make that safe, and a third that
    makes it reproducible -- asserted on real-shaped domains rather than on the hash."""
    rows = [_row(f"news{i}.example") for i in range(400)]
    rows += [_row(h) for h in ("a.co.uk", "b.co.uk", "x.example", "y.example")]
    # Several rows of ONE host, which is the case the host-keyed split exists for.
    rows += [_row("news7.example"), _row("www.news7.example")]

    N = 8
    buckets = [[r for r in rows if vcf.shard_index(r["domain"], N) == i] for i in range(N)]

    # 1. A PARTITION: every row judged exactly once across the fleet, none twice, none never.
    assert sum(len(b) for b in buckets) == len(rows)
    assert {r["domain"] for b in buckets for r in b} == {r["domain"] for r in rows}
    for i, b in enumerate(buckets):
        for r in b:
            assert [j for j in range(N) if vcf.shard_index(r["domain"], N) == j] == [i]

    # 2. THE SHARD KEY IS THE RUN'S OWN DOMAIN KEY -- the politeness guarantee. Per-host rate
    #    limiting lives inside one process, so rows the run treats as ONE host must not land on
    #    two machines. Asserted against the very function run()/load_resume key on, so the two
    #    cannot drift apart; a subdomain is a DIFFERENT host to both, and that is consistent.
    assert vcf.shard_index("www.news7.example", N) == vcf.shard_index("news7.example", N)
    for r in rows:
        d = vcf.registrable_domain(r["domain"]) or r["domain"]
        assert vcf.shard_index(r["domain"], N) == vcf.shard_index(d, N)

    # 3. STABLE, not salted: the same answer in any process, or the machines disagree about
    #    who owns what. A PYTHONHASHSEED-dependent split would fail this across processes.
    assert vcf.shard_index("news7.example", N) == vcf.shard_index("news7.example", N)
    assert vcf.shard_index("theguardian.com", 8) == 7  # pinned: a change here re-partitions live runs

    # And it actually spreads -- a split that puts everything on one machine would pass 1-3.
    assert all(len(b) > 0 for b in buckets), [len(b) for b in buckets]


def test_run_judges_only_its_own_shard(tmp_path):
    rows = [_row(f"s{i}.example") for i in range(40)]
    table = {}
    for r in rows:
        table[f"https://{r['domain']}/"] = HOME_WITH_LINK
        table[f"https://{r['domain']}/feed.xml"] = _rss(5)
    judged = {}
    for i in (1, 2, 3):
        out = tmp_path / f"shard{i}"
        vcf.run(rows, fetch=FakeFetch(dict(table)), out_dir=out, workers=2, now=NOW,
                catalogue=set(), shard=(i, 3))
        judged[i] = {v.domain for v in vcf.load_resume(out / "verified.jsonl")[0]}
    # Disjoint, and together the whole worklist -- the fleet's output concatenates cleanly.
    assert judged[1] & judged[2] == set() and judged[1] & judged[3] == set() and judged[2] & judged[3] == set()
    assert judged[1] | judged[2] | judged[3] == {r["domain"] for r in rows}


def test_a_malformed_shard_spec_is_refused_rather_than_silently_partial():
    for bad in ("8", "0/8", "9/8", "3/0", "a/8", "3/8/2", "-1/8"):
        with pytest.raises(ValueError):
            vcf.parse_shard(bad)
    assert vcf.parse_shard("3/8") == (3, 8) and vcf.parse_shard("1/1") == (1, 1)


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

def test_an_interrupt_keeps_every_row_written_and_the_same_command_resumes(tmp_path):
    """Ctrl-C on a laptop run (the maintainer's own-machine path): rows judged so far stay in
    verified.jsonl, the summary says interrupted and how much remains, and the next run continues
    from the cursor without re-judging what was written."""
    table = {
        "https://a.example/": HOME_PLAIN, "https://a.example/rss": _rss(3),
        "https://b.example/": HOME_PLAIN, "https://b.example/rss": _rss(3),
        "https://c.example/": HOME_PLAIN, "https://c.example/rss": _rss(3),
    }
    rows = [_row(domain=d) for d in ("a.example", "b.example", "c.example")]

    class Interrupting(FakeFetch):
        def __call__(self, url, *, require_html=True, **_):
            if url.startswith("https://b.example/"):
                raise KeyboardInterrupt  # the operator's Ctrl-C lands while host b is in flight
            return super().__call__(url, require_html=require_html)

    first = vcf.run(rows, fetch=Interrupting(table), out_dir=tmp_path, workers=1, now=NOW, catalogue=set())
    assert first["interrupted"] is True and first["judged_this_run"] == 1 and first["remaining"] == 2
    assert first["candidates"] == 1 and (tmp_path / "summary.json").exists()  # partial outputs still written
    lines = [ln for ln in (tmp_path / "verified.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1 and '"a.example"' in lines[0]

    second = vcf.run(rows, fetch=FakeFetch(table), out_dir=tmp_path, workers=1, now=NOW, catalogue=set())
    assert second["interrupted"] is False and second["judged_this_run"] == 2 and second["remaining"] == 0
    lines = [ln for ln in (tmp_path / "verified.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3 and second["candidates"] == 3 and second["verified"] == 3


# ------------------------------------------------------------------ bounded in time (2026-09-10)

def test_a_declared_crawl_delay_bounds_the_probes_to_what_the_budget_affords():
    """The fetcher sleeps the declared Crawl-delay before EVERY request, so probes cost
    delay x probes of one worker: the budget divided by the delay is the probe count."""
    # the feed sits at the THIRD conventional path (/rss.xml); no declared links
    table = {"https://ex.example/": HOME_PLAIN, "https://ex.example/rss.xml": _rss(4)}
    delays = {"https://ex.example/": 250.0}
    fetch = FakeFetch(table)
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set(),
                             crawl_delay=delays.get, probe_budget_s=600.0)
    assert v.crawl_delay_s == 250.0 and v.feed_probes == 2  # 600 // 250 = 2 probes: /feed, /rss
    assert v.reason == "no_feed_found" and v.status == "rejected"

    v2 = vcf.verify_candidate(_row(), fetch=FakeFetch(table), now=NOW, catalogue=set(), seen=set(),
                              crawl_delay=delays.get, probe_budget_s=900.0)
    assert v2.feed_probes == 3 and v2.status == "verified"  # 900 // 250 = 3: the third probe finds it

    v3 = vcf.verify_candidate(_row(), fetch=FakeFetch(table), now=NOW, catalogue=set(), seen=set(),
                              crawl_delay=lambda _u: None)
    assert v3.feed_probes == 3 and v3.status == "verified" and v3.crawl_delay_s == 0.0  # no delay: unbounded


def test_a_crawl_delay_the_budget_cannot_afford_once_is_not_judged_and_records_the_delay():
    table = {"https://ex.example/": HOME_WITH_LINK, "https://ex.example/feed.xml": _rss(4)}
    fetch = FakeFetch(table)
    v = vcf.verify_candidate(_row(), fetch=fetch, now=NOW, catalogue=set(), seen=set(),
                             crawl_delay=lambda _u: 3600.0, probe_budget_s=600.0)
    # status DEFERRED, not "error" (ruling 2026-09-11). This row was never judged, and the
    # codebase had two statuses meaning that -- which is the conflation the whole robots
    # thread was about. `error` now means only "something went wrong in OUR code for this row".
    assert (v.status, v.reason) == ("deferred", "crawl_delay_too_long")
    assert v.crawl_delay_s == 3600.0 and v.feed_probes == 0
    assert fetch.calls == ["https://ex.example/"]  # the homepage only: not one probe was paid for
    assert v.homepage_url == "https://ex.example/" and v.site_title == "The Example Gazette"
    assert "crawl_delay_too_long" in vcf.REASONS and "host_timeout" in vcf.REASONS


def test_a_host_that_never_returns_is_host_timeout_and_the_run_moves_on_then_retries_it(tmp_path):
    import threading

    gate = threading.Event()
    table = {"https://a.example/": HOME_WITH_LINK, "https://a.example/feed.xml": _rss(4),
             "https://b.example/": HOME_WITH_LINK, "https://b.example/feed.xml": _rss(4)}

    class Blocking(FakeFetch):
        def __call__(self, url, *, require_html=True, **kw):
            if url.startswith("https://b.example/"):
                gate.wait(timeout=30)  # the host that never answers (a Crawl-delay sleep, a tarpit)
            return super().__call__(url, require_html=require_html, **kw)

    rows = [_row("a.example"), _row("b.example")]
    try:
        s = vcf.run(rows, fetch=Blocking(table), out_dir=tmp_path, workers=2, now=NOW, catalogue=set(),
                    stall_s=0.3)
    finally:
        gate.set()  # release the thread so the test process can exit
    assert s["stragglers"] == ["b.example"] and s["judged_this_run"] == 2 and s["remaining"] == 0
    assert s["by_reason"] == {"verified": 1, "host_timeout": 1}
    lines = [ln for ln in (tmp_path / "verified.jsonl").read_text(encoding="utf-8").splitlines() if ln]
    assert [__import__("json").loads(ln)["reason"] for ln in lines] == ["verified", "host_timeout"]

    # the same command resumes past it (a verdict is a verdict) ...
    again = vcf.run(rows, fetch=FakeFetch(table), out_dir=tmp_path, workers=2, now=NOW, catalogue=set())
    assert again["judged_this_run"] == 0 and again["stragglers"] == []
    # ... and --retry host_timeout re-judges exactly that row; its NEW line is the truth
    retried = vcf.run(rows, fetch=FakeFetch(table), out_dir=tmp_path, workers=2, now=NOW, catalogue=set(),
                      retry_reasons={"host_timeout"})
    assert retried["judged_this_run"] == 1 and retried["by_reason"] == {"verified": 2}
    prior, done = vcf.load_resume(tmp_path / "verified.jsonl")
    assert done == {"a.example", "b.example"} and len(prior) == 2
    assert {v.domain: v.reason for v in prior} == {"a.example": "verified", "b.example": "verified"}
    assert len((tmp_path / "verified.jsonl").read_text(encoding="utf-8").splitlines()) == 3  # appended, never rewritten


def test_the_cli_refuses_an_unknown_retry_reason(capsys):
    with pytest.raises(SystemExit) as exc:
        vcf.main(["--candidates", "x.csv", "--out-dir", "y", "--retry", "host_timeout,bogus"])
    assert exc.value.code == 2 and "bogus" in capsys.readouterr().err


def test_a_crash_inside_one_host_is_an_error_row_and_the_run_goes_on(tmp_path, monkeypatch):
    table = {"https://a.example/": HOME_WITH_LINK, "https://a.example/feed.xml": _rss(4),
             "https://b.example/": HOME_WITH_LINK, "https://b.example/feed.xml": "BOOM"}
    real = vcf.parse_feed

    def boom(content):
        if content == "BOOM":
            raise RuntimeError("a parser bug")
        return real(content)

    monkeypatch.setattr(vcf, "parse_feed", boom)
    s = vcf.run([_row("a.example"), _row("b.example")], fetch=FakeFetch(table), out_dir=tmp_path,
                workers=2, now=NOW, catalogue=set())
    assert s["by_reason"] == {"verified": 1, "error": 1} and s["stragglers"] == []
    prior, _ = vcf.load_resume(tmp_path / "verified.jsonl")
    err = next(v for v in prior if v.domain == "b.example")
    assert (err.status, err.reason, err.note) == ("rejected", "error", "RuntimeError: a parser bug")
