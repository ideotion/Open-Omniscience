"""Row 118: the statistics agencies' news-page checker (0.6 gate row A, Q1147).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The script proposes a news page per agency from what it reads; it never writes ``agencies.py`` and never asks the network
without ``--online``. A stand-in fetcher plays the sites, so nothing here leaves the machine.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("stat_news_check", ROOT / "scripts" / "stat_news_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stat_news_check"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _mod()
HOME = """<html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml"></head><body>
<a href="/en/data">Data</a><a href="https://www.insee.fr/fr/information/actualites">Actualités</a>
<a href="https://evil.test/news">News elsewhere</a><a href="//cdn.insee.fr/presse">Presse</a>
<a href="mailto:press@insee.fr">press</a><script>var a='<a href="/news-in-script">news</a>'</script>
<a href="/fr/information/actualites#top">again</a><a href="/statistiques/communiques">Communiqués</a></body></html>"""
NEWS_PAGE = "<ul>" + "".join(f'<li><a href="/n/{d}">Item</a> {d}</li>' for d in ("2026-11-01", "2026-11-05", "2026-11-09")) + "</ul>"
FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>a</title><link>https://www.insee.fr/a</link></item><item><title>b</title><link>https://www.insee.fr/b</link></item>
</channel></rss>"""


def _agency(home="https://www.insee.fr", code="fr-insee"):
    return types.SimpleNamespace(code=code, name="INSEE", home_url=home, news_url=None)


class _Sites:
    """A stand-in for EthicalFetcher.fetch: answers from a dict, records every request and the scope it was handed."""

    def __init__(self, pages: dict[str, object]):
        self.pages, self.asked = pages, []

    def __call__(self, url, *, require_html=True, redirect_scope=None):
        self.asked.append(url)
        assert redirect_scope is not None and redirect_scope(url), f"asked out of scope: {url}"
        got = self.pages.get(url)
        if isinstance(got, Exception):
            raise got
        if got is None:
            from src.ingest import FetchFailed

            raise FetchFailed("404")
        final, body = got if isinstance(got, tuple) else (url, got)
        return types.SimpleNamespace(final_url=final, status_code=200, content=body)


def test_candidates_are_feeds_first_then_news_words_same_site_only_deduplicated_and_bounded():
    got = M.candidates(HOME, "https://www.insee.fr/", "insee.fr")
    assert [c["url"] for c in got] == [
        "https://www.insee.fr/rss.xml",
        "https://www.insee.fr/fr/information/actualites",
        "https://cdn.insee.fr/presse",
    ], "the other site, mailto:, script text and the repeated fragment are not candidates; at most three"
    assert got[0]["why"] == "feed declared by the home page" and "actualit" in got[1]["why"]


def test_a_list_shaped_page_is_proposed_and_the_report_says_it_is_a_shape_not_a_confirmation():
    sites = _Sites({
        "https://www.insee.fr": ("https://www.insee.fr/", HOME),
        "https://www.insee.fr/rss.xml": FEED,  # two entries: under MIN_ITEMS
        "https://www.insee.fr/fr/information/actualites": NEWS_PAGE,
    })
    row = M.check_agency(_agency(), sites)
    assert row["verdict"] == "proposed" and row["proposed"] == "https://www.insee.fr/fr/information/actualites"
    feed, page, cdn = row["candidates"]
    assert (feed["kind"], feed["entries"], feed["list_shaped"]) == ("feed", 2, False)
    assert (page["kind"], page["distinct_dates"], page["list_shaped"]) == ("page", 3, True)
    assert cdn["outcome"] == "fetch_failed" and cdn["error_class"] == "FetchFailed"
    rep = M.build_report([row], fetcher_mode="test")
    assert rep["verdicts"] == {"proposed": 1} and "not a confirmation" in rep["caveat"]


def test_every_refusal_is_a_verdict_and_its_words_are_not_kept():
    from src.ingest import RobotsDisallowed

    row = M.check_agency(_agency(), _Sites({"https://www.insee.fr": RobotsDisallowed("socks5://user:secret@proxy:9050 said no")}))
    assert row["verdict"] == "home_not_read" and row["home"] == {"outcome": "robots_disallowed", "error_class": "RobotsDisallowed"}
    assert "secret" not in json.dumps(row)
    moved = M.check_agency(_agency(), _Sites({"https://www.insee.fr": ("https://evil.test/", HOME)}))
    assert moved["verdict"] == "home_not_read" and moved["home"]["outcome"] == "redirect_out_of_scope"
    none = M.check_agency(_agency(), _Sites({"https://www.insee.fr": "<a href='/data'>Data</a>"}))
    assert none["verdict"] == "no_candidate_link" and none["proposed"] is None


def test_scope_refuses_userinfo_backslashes_and_other_sites():
    for bad in ("https://user@www.insee.fr/x", "https://evil.test\\@www.insee.fr/", "ftp://www.insee.fr/", "https://insee.fr.evil.test/"):
        assert M.in_scope(bad, "insee.fr") is False, bad
    assert M.in_scope("http://www.insee.fr/a", "insee.fr") and M.in_scope("https://cdn.insee.fr/a", "insee.fr")


def test_dates_are_counted_once_each_in_several_shapes():
    text = "2026-11-01 2026-11-01 01/11/2026 2026年11月1日 1 novembre 2026 November 1, 2026 12 de marzo de 2026"
    assert M.distinct_dates(text) == 6


def test_without_online_it_names_the_hosts_and_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "_fetcher", lambda: pytest.fail("a fetcher was built without consent"))
    assert M.main(["--out", str(tmp_path / "r.json"), "--only", "fr-insee,uk-ons"]) == 2
    out = capsys.readouterr()
    assert "www.insee.fr" in out.out and "www.ons.gov.uk" in out.out and "--online" in out.err
    assert not (tmp_path / "r.json").exists()
    assert M.main(["--out", str(tmp_path / "r.json"), "--only", "nope"]) == 2


def test_an_online_run_goes_through_the_one_fetcher_and_writes_a_report_within_the_send_back_size(tmp_path, monkeypatch):
    sites = _Sites({"https://www.insee.fr": ("https://www.insee.fr/", HOME), "https://www.insee.fr/fr/information/actualites": NEWS_PAGE})
    monkeypatch.setattr(M, "_fetcher", lambda: (types.SimpleNamespace(fetch=sites), "stand-in"))
    out = tmp_path / "r.json"
    assert M.main(["--online", "--out", str(out), "--only", "fr-insee"]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["agencies"][0]["proposed"] and out.stat().st_size <= M.MAX_REPORT_BYTES
    assert sites.asked[0] == "https://www.insee.fr"


def test_the_real_fetcher_is_the_apps_own_factory():
    src = (ROOT / "scripts" / "stat_news_check.py").read_text(encoding="utf-8")
    assert "from src.safety.fetcher import make_fetcher" in src
    for lib in ("import requests", "import httpx", "urllib.request", "import socket"):
        assert lib not in src, lib


def test_the_report_is_cut_to_the_send_back_size_and_counts_what_went():
    rows = [{"code": str(i), "verdict": "candidates_not_list_shaped", "proposed": None,
             "candidates": [{"url": "https://x.test/" + "a" * 5000}] * 3} for i in range(40)]
    rep = M.fit({"agencies": rows}, limit=100_000)
    assert len(json.dumps(rep).encode()) <= 100_000 and rep["candidates_dropped_to_fit"] > 0
