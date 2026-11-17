#!/usr/bin/env python3
"""Look for each statistics agency's NEWS page and write what was found, for a person to confirm (row 118; 0.6 gate row A, Q1147).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. ``src/stats/agencies.py`` registers an agency as a source only through its ``news_url``, and that field is set only once
someone fetched the page and confirmed it (maintainer ruling 9, 2026-07-31): a home page is usually a dataset portal, and a
crawl of a portal yields downloads, not articles. Nothing in the tree could look, so ``directory_progress`` reads 0 confirmed.
This script does the looking. It PROPOSES; it never writes ``agencies.py``. A session reads the report and writes the rows a
person confirmed, in a reviewed pull request.

WHAT IT ASKS, per agency of the shipped directory (``--only`` narrows it):

1. the agency's ``home_url``, through the app's ONE fetch path (``EthicalFetcher`` built by ``make_fetcher``: robots.txt
   fail-closed, the honest bot user agent or the operator's protected-mode proxy, per-host politeness, the SSRF guards, a size
   cap). Every redirect hop must stay on the agency's own registrable domain (``insee.fr`` for ``www.insee.fr``), or the fetch is
   refused as out of scope and recorded;
2. at most ``MAX_CANDIDATES`` links from that page, on the same registrable domain: a feed the page declares
   (``<link rel="alternate">`` RSS/Atom) first, then links whose address or text holds a news word in one of the app's twelve
   languages (``NEWS_WORDS``), in page order. Nothing is ranked;
3. each candidate once, and its SHAPE measured: a feed's entries, or for a page the distinct dates written in it and its
   same-site links. A candidate is PROPOSED when it is a feed with at least ``MIN_ITEMS`` entries or a page with at least
   ``MIN_ITEMS`` distinct dates. That is a shape, not a confirmation: the report says so beside every proposal.

THE CONSENT. It asks the network only with ``--online``, the operator's consent for this run. Without it, it prints the hosts it
would ask and exits 2 having sent nothing. The app's own airplane state lives in the app's process and cannot be seen from here,
so the flag is the consent, as in ``scripts/law_pit_real_run.py``. Protected mode is honoured: ``make_fetcher`` reads the app's
safety settings, and protected mode with no proxy refuses before any request.

THE REPORT (``--out``, JSON, at most ``MAX_REPORT_BYTES`` so it can be sent back): per agency the home page's outcome, the
candidates with their measured shape, the proposal or the reason there is none; then the counts. Addresses are the agencies' own
public pages; no cookie, header or page text is kept. Exit 0 when the report is written, 2 refused, 1 the run itself failed.

    python scripts/stat_news_check.py --online --out stat-news-check.json
    python scripts/stat_news_check.py --online --only fr-insee,uk-ons --out stat-news-check.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

#: Links read from a home page and asked once each.
MAX_CANDIDATES = 3
#: Entries of a feed, or distinct dates on a page, for a candidate to be proposed.
MIN_ITEMS = 3
#: The report fits what a person can send back (2026-11-15: every returned file at most 200 KB).
MAX_REPORT_BYTES = 200_000
#: Size cap on any one page asked (bytes); a news list is far smaller.
MAX_PAGE_BYTES = 3_000_000

#: Words that mark a news, press or release section, in the app's twelve languages (casefolded; matched as substrings of the
#: link's address and text). A list, not a model: a section named otherwise is simply not found, and the report says so.
NEWS_WORDS: tuple[str, ...] = (
    # en
    "news", "press", "release", "media", "announcement",
    # fr
    "actualit", "communiqu", "presse", "salle-de-presse",
    # de
    "nachricht", "pressemitteil", "aktuell",
    # es / pt
    "noticia", "notícia", "prensa", "comunicado", "imprensa", "novedad", "sala-de-prensa",
    # ru
    "новост", "пресс", "сообщени",
    # ar
    "أخبار", "اخبار", "بيان", "صحف",
    # zh
    "新闻", "新聞", "发布", "發布", "动态",
    # ja
    "ニュース", "報道", "お知らせ", "新着",
    # hi / bn
    "समाचार", "प्रेस", "সংবাদ", "প্রেস",
    # id
    "berita", "siaran-pers", "siaran pers", "rilis",
)

_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre|"
    "januar|februar|märz|juni|juli|oktober|dezember|"
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|"
    "janeiro|fevereiro|março|maio|junho|julho|setembro|outubro|novembro|dezembro"
)
#: Date shapes counted on a page. Each match is reduced to its digits and words, and DISTINCT ones are counted, so one date
#: repeated in a header and a footer counts once.
_DATE_PATTERNS = (
    re.compile(r"\b(?:19|20)\d\d-[01]\d-[0-3]\d\b"),
    re.compile(r"\b[0-3]?\d[./][01]?\d[./](?:19|20)\d\d\b"),
    re.compile(r"(?:19|20)\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"),
    re.compile(rf"\b[0-3]?\d\.?\s+(?:de\s+)?(?:{_MONTHS})\.?\s+(?:de\s+)?(?:19|20)\d\d\b", re.I),
    re.compile(rf"\b(?:{_MONTHS})\.?\s+[0-3]?\d,?\s+(?:19|20)\d\d\b", re.I),
)


class _Links(HTMLParser):
    """Anchors (address, text) and declared feeds, in page order. Script and style text is not link text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self.feeds: list[str] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "link" and "alternate" in a.get("rel", "").lower().split() and a.get("type", "").lower() in _FEED_TYPES:
            if a.get("href"):
                self.feeds.append(a["href"])
        elif tag == "a" and a.get("href"):
            self._href, self._text = a["href"], []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._text).split())))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None and not self._skip:
            self._text.append(data)


def site(url_or_host: str | None) -> str | None:
    """The registrable domain of a URL or host (``insee.fr`` for ``https://www.insee.fr/x``), None when there is none."""
    from src.catalog.publicsuffix import registrable_domain_psl

    if not url_or_host:
        return None
    host = urlparse(url_or_host).hostname if "//" in url_or_host else url_or_host
    return registrable_domain_psl((host or "").lower().rstrip(".") or None, include_private=False)


def in_scope(url: str, home_site: str) -> bool:
    """True only for an http(s) URL with no userinfo, no backslash and no control character whose registrable domain is the
    agency's own."""
    if not isinstance(url, str) or "\\" in url or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        p = urlparse(url)
        host = p.hostname
    except ValueError:
        return False
    return p.scheme in ("http", "https") and p.username is None and p.password is None and site(host) == home_site


def candidates(html: str, base_url: str, home_site: str, limit: int = MAX_CANDIDATES) -> list[dict[str, str]]:
    """The links worth asking, in order: declared feeds first, then news-worded links; in scope, deduplicated, at most ``limit``."""
    parser = _Links()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a page the parser chokes on yields what it read so far
        pass
    out: list[dict[str, str]] = []
    seen = {urldefrag(base_url)[0]}

    def add(href: str, why: str) -> None:
        url = urldefrag(urljoin(base_url, href.strip()))[0]
        if len(out) < limit and url not in seen and in_scope(url, home_site):
            seen.add(url)
            out.append({"url": url, "why": why})

    for href in parser.feeds:
        add(href, "feed declared by the home page")
    for href, text in parser.anchors:
        hay = f"{href} {text}".casefold()
        word = next((w for w in NEWS_WORDS if w in hay), None)
        if word:
            add(href, f"link matched {word!r}")
    return out


def distinct_dates(text: str) -> int:
    found: set[str] = set()
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            found.add(" ".join(re.findall(r"\w+", m.group(0).casefold())))
    return len(found)


def feed_entries(body: str) -> int | None:
    """Entries of an RSS/Atom body, or None when it is not a feed."""
    import feedparser

    parsed = feedparser.parse(body)
    if not getattr(parsed, "version", ""):
        return None
    return sum(1 for e in parsed.entries if e.get("title") and e.get("link"))


def shape(body: str, final_url: str, home_site: str) -> dict[str, Any]:
    """What a candidate looks like: a feed's entries, or a page's distinct dates and same-site links."""
    entries = feed_entries(body) if body.lstrip()[:200].lower().startswith(("<?xml", "<rss", "<feed")) else None
    if entries is not None:
        return {"kind": "feed", "entries": entries, "list_shaped": entries >= MIN_ITEMS}
    parser = _Links()
    try:
        parser.feed(body)
        parser.close()
    except Exception:  # noqa: BLE001
        pass
    links = {urldefrag(urljoin(final_url, h))[0] for h, _t in parser.anchors}
    dates = distinct_dates(re.sub(r"<[^>]+>", " ", body))
    return {"kind": "page", "distinct_dates": dates, "same_site_links": sum(1 for u in links if in_scope(u, home_site)),
            "list_shaped": dates >= MIN_ITEMS}


def _refusal(exc: Exception) -> dict[str, str]:
    """A fetch refusal as its class and a fixed word: the library's text can carry a proxy address, so it is not kept."""
    from src.ingest import (
        BlockedTarget,
        CrawlDelayDeferred,
        FetchError,
        RedirectOutOfScope,
        RobotsDisallowed,
        RobotsUnavailable,
    )

    kind = "error" if not isinstance(exc, FetchError) else "fetch_failed"
    for cls, word in ((RobotsDisallowed, "robots_disallowed"), (RobotsUnavailable, "robots_unavailable"),
                      (CrawlDelayDeferred, "crawl_delay_deferred"), (RedirectOutOfScope, "redirect_out_of_scope"),
                      (BlockedTarget, "blocked_target")):
        if isinstance(exc, cls):
            kind = word
            break
    return {"outcome": kind, "error_class": type(exc).__name__}


Fetch = Callable[..., Any]


def check_agency(agency: Any, fetch: Fetch) -> dict[str, Any]:
    """One agency, end to end. ``fetch(url, *, require_html, redirect_scope)`` is ``EthicalFetcher.fetch`` (a stand-in in tests)."""
    home = agency.home_url
    home_site = site(home)
    row: dict[str, Any] = {"code": agency.code, "name": agency.name, "home_url": home, "known_news_url": agency.news_url}
    if not home_site or not in_scope(home, home_site):
        return {**row, "verdict": "home_url_unusable", "candidates": [], "proposed": None}

    def scope(u: str) -> bool:
        return in_scope(u, home_site)

    try:
        page = fetch(home, require_html=True, redirect_scope=scope)
    except Exception as exc:  # noqa: BLE001 - every refusal is a recorded verdict, never a crash of the run
        return {**row, "home": _refusal(exc), "verdict": "home_not_read", "candidates": [], "proposed": None}
    if not scope(page.final_url):
        return {**row, "home": {"outcome": "redirect_out_of_scope"}, "verdict": "home_not_read", "candidates": [], "proposed": None}
    row["home"] = {"outcome": "read", "status": page.status_code, "final_url": page.final_url}
    found = candidates(page.content or "", page.final_url, home_site)
    if not found:
        return {**row, "verdict": "no_candidate_link", "candidates": [], "proposed": None}
    for c in found:
        try:
            got = fetch(c["url"], require_html=False, redirect_scope=scope)
        except Exception as exc:  # noqa: BLE001
            c.update(_refusal(exc))
            continue
        if not scope(got.final_url):
            c["outcome"] = "redirect_out_of_scope"
            continue
        c.update({"outcome": "read", "status": got.status_code, "final_url": got.final_url})
        c.update(shape(got.content or "", got.final_url, home_site))
    proposed = next((c["final_url"] for c in found if c.get("list_shaped")), None)
    return {**row, "verdict": "proposed" if proposed else "candidates_not_list_shaped", "candidates": found, "proposed": proposed}


def build_report(rows: list[dict[str, Any]], *, fetcher_mode: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    report = {
        "schema": "oo-stat-news-check-1",
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "fetcher": fetcher_mode,
        "method": (
            f"per agency: its home page, then at most {MAX_CANDIDATES} same-site links (declared feeds first, then links whose "
            f"address or text holds a news word), each read once; proposed = a feed with at least {MIN_ITEMS} entries or a page "
            f"with at least {MIN_ITEMS} distinct written dates"
        ),
        "caveat": (
            "A proposal is a SHAPE, not a confirmation: open it and check it is the agency's own news or release list before "
            "it is written as news_url. An agency with no proposal may still have a news page this list of words did not find."
        ),
        "n_agencies": len(rows),
        "verdicts": dict(sorted(counts.items())),
        "agencies": rows,
    }
    return fit(report)


def fit(report: dict[str, Any], limit: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    """Keep the report within ``limit`` bytes: candidates of agencies with no proposal go first, and the cut is counted."""
    def size() -> int:
        return len(json.dumps(report, ensure_ascii=False).encode("utf-8"))

    dropped = 0
    for r in report["agencies"]:
        if size() <= limit:
            break
        if not r.get("proposed") and r.get("candidates"):
            dropped += len(r["candidates"])
            r["candidates"] = []
    report["candidates_dropped_to_fit"] = dropped
    return report


def _fetcher() -> tuple[Any, str]:
    from src.safety.fetcher import make_fetcher

    return make_fetcher(timeout=30.0, max_bytes=MAX_PAGE_BYTES), "app safety settings (make_fetcher)"


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--online", action="store_true", help="your consent for this run to ask the agencies' sites")
    ap.add_argument("--out", type=Path, required=True, help="the JSON report to write")
    ap.add_argument("--only", default="", help="comma-separated agency codes (default: every agency in the directory)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    from src.stats.agencies import list_agencies

    only = {c.strip() for c in args.only.split(",") if c.strip()}
    agencies = [a for a in list_agencies() if not only or a.code in only]
    unknown = sorted(only - {a.code for a in agencies})
    if unknown:
        print(f"unknown agency code(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    hosts = sorted({urlparse(a.home_url).hostname or a.home_url for a in agencies})
    print(f"{len(agencies)} agencies; this run asks these hosts (and same-site pages they link to):")
    for h in hosts:
        print(f"  {h}")
    if not args.online:
        print("refused: add --online to consent to these requests. Nothing was sent.", file=sys.stderr)
        return 2
    try:
        fetcher, mode = _fetcher()
    except Exception as exc:  # noqa: BLE001 - protected mode with no proxy, an unreadable settings file
        print(f"refused before any request: the fetcher could not be built ({type(exc).__name__})", file=sys.stderr)
        return 2
    rows = []
    for n, agency in enumerate(agencies, 1):
        row = check_agency(agency, fetcher.fetch)
        print(f"[{n}/{len(agencies)}] {agency.code}: {row['verdict']}" + (f" -> {row['proposed']}" if row["proposed"] else ""))
        rows.append(row)
    report = build_report(rows, fetcher_mode=mode)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes): {report['verdicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
