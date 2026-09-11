"""Verify candidate sources' FEEDS -- the zero-token stage of the candidate pipeline.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-09-10): use an internet-connected session, with the sources export
attached, to run "a workflow of agents to check candidate sources and increase the current
list of 3,600 sources" -- and "think of token usage". The answer to the token question is
that checking a feed is not a judgement: it is a fetch, a parse and three rules, and a model
adds nothing to it but cost. So this script does the whole mechanical half of the work with
ZERO model tokens, and hands the model only the residue that needs judgement (is this a
journalism outlet, which topics), in `triage_verified_feeds.workflow.js`.

WHAT IT DOES, per candidate row (name, domain, and whatever the export carries):

1. DEDUPE against the shipped catalogues -- registrable domain plus the known aliases
   (`DOMAIN_ALIASES`) -- and within the run. A duplicate is recorded, never re-verified.
2. HOMEPAGE: one guarded fetch of ``https://<domain>/`` (``http://`` as the fallback), through
   the app's own ``EthicalFetcher``: robots.txt fail-closed, honest bot UA, per-host politeness,
   size cap. In the repository it comes from the ONE guarded factory (``make_fetcher``: the
   operator's proxy if the install runs protected mode); in the KIT built by
   ``build_candidate_kit.py`` (no settings store, marked by ``KIT_MANIFEST.json``) the SAME class
   is built directly in transparent mode, and the run log says which (``build_fetcher``). A
   robots refusal is a verdict (``robots_disallowed``), never worked around.
3. FEED DISCOVERY: ``<link rel="alternate" type="application/rss+xml|atom+xml">`` in the
   homepage first (the outlet's own declaration), then a SHORT list of conventional paths,
   stopping at the first feed that passes. Bounded: at most ``MAX_FEED_PROBES`` feed fetches
   per host, so a site with no feed costs a fixed handful of polite requests and no more.
4. THE THREE RULES the diversification brief already set (2026-07, "verify each, all must
   pass or drop"): the feed parses as RSS/Atom; it has at least ``MIN_ENTRIES`` entries with a
   title AND a link; at least one entry is dated within ``FRESH_DAYS``. An undated feed is
   ``feed_undated`` -- reported as its own reason, never guessed live.
4b. BOUNDED IN TIME (2026-09-10, the kit's first live run): the fetcher honours a host's
   robots ``Crawl-delay`` before EVERY request, so six probes at Crawl-delay 900 held one
   worker for ninety minutes, and one host with a longer delay held the whole shortlist for
   hours -- the pool waited for its last member. So the host's OWN declared delay now bounds
   its probes: ``min(MAX_FEED_PROBES, PROBE_TIME_BUDGET_S // delay)``, declared feed links
   first; a delay the budget cannot afford even once is ``crawl_delay_too_long`` (status
   ``error`` = not judged, the delay recorded). And the run never waits forever on a silent
   host: when nothing finishes for ``STALL_S``, the hosts still in flight are written as
   ``host_timeout`` (not judged) and the process exits without waiting for their threads.
   Both are re-judged on demand with ``--retry crawl_delay_too_long,host_timeout``.
5. LANGUAGE of the CONTENT, detected over the entry titles with the repo's own guarded
   detector (``src.analytics.langdetect``: below its floors it answers None, never guesses);
   the export's language is kept as the fallback and the BASIS is recorded either way.
6. OUTPUT: ``verified.jsonl`` (one record per candidate, every field of evidence, verdict and
   reason -- the resume cursor), ``rejections.csv`` (domain, reason), ``verified_sources.yml``
   (ONLY the rows that passed, in exactly the ``configs/sources.yml`` schema, ``verified: true``
   with today's ``last_verified`` -- a claim this run personally stakes), and ``summary.json``.

WHAT IT REFUSES TO DO: emit an entry for a feed it did not fetch and parse in this run; guess
a language, a country or a region; touch ``configs/sources.yml`` (the merge is a separate,
reviewed step: ``scripts/merge_source_batch.py``); rank anything.

RESUMABLE: ``--resume`` re-reads ``verified.jsonl`` and skips domains already judged, so a 22k
run can be split across sessions (``--limit``) and a crash costs nothing already written. A
domain's LAST line is its verdict, so ``--retry REASON[,REASON]`` re-judges the rows whose last
verdict carries one of those reasons by simply appending a newer line.

RUN (inside a clearnet session, after building the venv -- in the repository or in the kit):
  .venv/bin/python scripts/analysis/verify_candidate_feeds.py \
      --candidates path/to/shortlist.csv --out-dir data/candidate_feeds --workers 8 --resume
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import yaml

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.catalog.countries import continent_of  # noqa: E402
from src.catalog.normalize import country_from_title, registrable_domain  # noqa: E402
from src.ingest import FetchError, RobotsDisallowed, RobotsUnavailable  # noqa: E402
from src.utils.url_utils import DOMAIN_ALIASES, normalize_domain  # noqa: E402

MIN_ENTRIES = 3
FRESH_DAYS = 120
MAX_LINK_FEEDS = 3          # <link rel=alternate> candidates tried, in page order
MAX_FEED_PROBES = 6         # feed fetches per host, links + conventional paths together
PROBE_TIME_BUDGET_S = 600.0  # what a host's declared Crawl-delay may cost across its probes
STALL_S = 1200.0             # nothing finishing for this long: the in-flight hosts are host_timeout
CONVENTIONAL_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/?feed=rss2")
FEED_TYPES = frozenset({
    "application/rss+xml", "application/atom+xml", "application/rdf+xml",
    "application/xml", "text/xml",
})
HOMEPAGE_MAX_BYTES = 2 * 1024 * 1024
FEED_MAX_BYTES = 4 * 1024 * 1024
TITLES_KEPT = 8
CATALOGUE_FILES = (
    "configs/sources.yml", "configs/sources_spectrum.yml", "configs/markets_sources.yml",
    "configs/legal_sources.yml", "configs/legal_sources_generated.yml",
    "configs/world_news_sources.yml",
)
# Tags that describe a ROW's origin or the discovery machinery, never the source: dropped on
# the way into a catalogue entry (the 2026-09-09 "provenance is a fact about the row" lesson).
_ROW_TAGS = ("via:", "world-catalog", "discovered", "cited")
_REGION_OF_CONTINENT = {
    "Europe": "europe", "Asia": "asia", "Africa": "africa", "North America": "north-america",
    "South America": "south-america", "Oceania": "oceania",
}

_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


@dataclass
class Verdict:
    domain: str
    name: str = ""
    source_type: str = ""
    country: str = ""
    language_export: str = ""
    status: str = "rejected"          # verified | rejected | error
    reason: str = ""                  # closed vocabulary, see REASONS
    homepage_url: str = ""
    site_title: str = ""
    description: str = ""
    feed_url: str = ""
    feed_kind: str = ""               # link | conventional
    feed_probes: int = 0
    entries: int = 0
    dated_entries: int = 0
    newest_entry: str = ""
    titles: list[str] = field(default_factory=list)
    language_detected: str = ""
    language_basis: str = ""          # detected | export | unknown
    robots: str = ""                  # allowed | disallowed | unavailable:<cause> | ""
    crawl_delay_s: float = 0.0        # the host's declared Crawl-delay, when it declares one
    tags: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    checked_at: str = ""
    note: str = ""                    # what an error or host_timeout row can say about itself


REASONS = (
    "duplicate_of_catalogue", "duplicate_in_run", "robots_disallowed",
    # THE THREE FACTS THAT USED TO BE ONE (2026-09-11). Each refuses the fetch exactly as
    # before -- fail-closed is unchanged -- but a catalogue can now tell them apart, which
    # it must, because they deserve different answers and none of them is a policy:
    "robots_refused",         # 401/403 -- declined on THIS path; over Tor, often the exit
    "robots_server_error",    # 5xx or an unexpected status -- the host is broken
    "robots_unreachable",     # network failure, timeout, blocked redirect, redirect loop
    # ...and the legacy label, KEPT so `--retry robots_unavailable` still selects the 7,847
    # rows a pre-split run wrote. Nothing emits it any more; it is a retry key and a record.
    "robots_unavailable",
    "homepage_unreachable", "no_feed_found", "feed_unparseable", "feed_too_few_entries",
    "feed_stale", "feed_undated", "verified", "error",
    # status ``error`` = NOT judged, re-judged on demand with --retry:
    "crawl_delay_too_long",   # the host's declared Crawl-delay exceeds the probe budget
    "host_timeout",           # still in flight when nothing had finished for STALL_S
)


# --------------------------------------------------------------------------- parsing (pure)

def _attrs(tag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(tag):
        out[m.group(1).lower()] = (m.group(2) or m.group(3) or m.group(4) or "").strip()
    return out


def discover_feed_links(html: str, base_url: str, *, cap: int = MAX_LINK_FEEDS) -> list[str]:
    """Feed URLs the page DECLARES, in page order, resolved and deduped. PURE."""
    found: list[str] = []
    for m in _LINK_TAG_RE.finditer(html or ""):
        a = _attrs(m.group(0))
        rel = a.get("rel", "").lower().split()
        typ = a.get("type", "").lower().split(";")[0].strip()
        href = a.get("href", "")
        if not href:
            continue
        if not (("alternate" in rel and typ in FEED_TYPES) or "rss" in rel or "atom" in rel
                or "feed" in rel):
            continue
        url = urljoin(base_url, href)
        if urlparse(url).scheme not in ("http", "https"):
            continue
        if url not in found:
            found.append(url)
        if len(found) >= cap:
            break
    return found


def extract_site_meta(html: str) -> tuple[str, str]:
    """``(title, description)`` from the homepage, whitespace-collapsed, bounded. PURE."""
    title = ""
    m = _TITLE_RE.search(html or "")
    if m:
        title = _WS_RE.sub(" ", re.sub(r"<[^>]+>", "", m.group(1))).strip()[:200]
    desc = ""
    for tag in _META_RE.finditer(html or ""):
        a = _attrs(tag.group(0))
        key = (a.get("name") or a.get("property") or "").lower()
        if key in ("description", "og:description") and a.get("content"):
            desc = _WS_RE.sub(" ", a["content"]).strip()[:400]
            if key == "description":
                break
    return title, desc


def parse_feed(content: str | bytes) -> list[dict]:
    """Entries as ``{title, link, date}`` (date an aware UTC datetime or None). PURE.
    Anything feedparser cannot read yields an empty list, never an exception."""
    import feedparser

    try:
        parsed = feedparser.parse(content)
    except Exception:  # noqa: BLE001 - a broken feed is a verdict, not a crash
        return []
    if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", None):
        return []
    out: list[dict] = []
    for e in getattr(parsed, "entries", []) or []:
        title = _WS_RE.sub(" ", str(getattr(e, "title", "") or "")).strip()
        link = str(getattr(e, "link", "") or "").strip()
        date = None
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            t = getattr(e, key, None)
            if t:
                try:
                    date = datetime(*t[:6], tzinfo=UTC)
                except (TypeError, ValueError):
                    date = None
                if date:
                    break
        out.append({"title": title, "link": link, "date": date})
    return out


def evaluate_feed(entries: list[dict], *, now: datetime) -> tuple[str, dict]:
    """The three rules. Returns ``(reason, facts)`` with reason ``verified`` on a pass. PURE."""
    usable = [e for e in entries if e["title"] and e["link"]]
    dated = [e["date"] for e in usable if e["date"] is not None]
    facts = {
        "entries": len(usable),
        "dated_entries": len(dated),
        "newest_entry": max(dated).isoformat() if dated else "",
        "titles": [e["title"][:160] for e in usable[:TITLES_KEPT]],
    }
    if not entries:
        return "feed_unparseable", facts
    if len(usable) < MIN_ENTRIES:
        return "feed_too_few_entries", facts
    if not dated:
        return "feed_undated", facts
    if max(dated) < now - timedelta(days=FRESH_DAYS):
        return "feed_stale", facts
    return "verified", facts


def alias_set(domain: str) -> set[str]:
    d = normalize_domain(domain)
    out = {d}
    out.update(DOMAIN_ALIASES.get(d, []))
    for k, vals in DOMAIN_ALIASES.items():
        if d in vals:
            out.add(k)
            out.update(vals)
    return out


def catalogue_domains(paths: list[Path]) -> set[str]:
    out: set[str] = set()
    for p in paths:
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for s in data.get("sources", []) or []:
            dom = (s or {}).get("domain") if isinstance(s, dict) else None
            if dom:
                out.update(alias_set(registrable_domain(str(dom)) or str(dom)))
    return out


def detect_titles_language(titles: list[str]) -> str | None:
    """The repo's guarded detector over the joined titles; None below its floors."""
    try:
        from src.analytics.langdetect import detect_language
    except Exception:  # noqa: BLE001 - the [analysis] extra may be absent
        return None
    text = " ".join(t for t in titles if t)
    try:
        return detect_language(text)
    except Exception:  # noqa: BLE001 - detection is a hint, never a crash
        return None


# --------------------------------------------------------------------------- one candidate

FetchFn = Callable[..., object]


def verify_candidate(
    row: dict, *, fetch: FetchFn, now: datetime, catalogue: set[str], seen: set[str],
    crawl_delay: Callable[[str], float | None] | None = None,
    probe_budget_s: float = PROBE_TIME_BUDGET_S,
) -> Verdict:
    """The whole check for ONE candidate. ``fetch(url, require_html=...)`` is the fetcher's
    ``fetch`` (a seam so tests inject a fake); it returns an object with ``content`` and
    ``final_url`` and raises ``FetchError`` subclasses on refusal. ``crawl_delay(url)`` is the
    fetcher's ``crawl_delay_for`` (the host's declared Crawl-delay once its robots.txt has been
    read, else None): it bounds the probes to what ``probe_budget_s`` can afford."""
    started = time.monotonic()
    raw = str(row.get("domain") or "").strip()
    dom = registrable_domain(raw) or normalize_domain(raw)
    v = Verdict(
        domain=dom, name=str(row.get("name") or "").strip(),
        source_type=str(row.get("source_type") or "").strip(),
        country=str(row.get("country") or "").strip().lower(),
        language_export=str(row.get("language") or "").strip().lower(),
        tags=[t for t in str(row.get("tags") or "").split(",") if t.strip()],
        checked_at=now.isoformat(timespec="seconds"),
    )
    if not dom:
        v.status, v.reason = "rejected", "error"
        return v
    if alias_set(dom) & catalogue:
        v.status, v.reason = "rejected", "duplicate_of_catalogue"
        return v
    if dom in seen:
        v.status, v.reason = "rejected", "duplicate_in_run"
        return v

    # --- homepage
    html, base = "", ""
    last_reason = "homepage_unreachable"
    for scheme in ("https", "http"):
        url = f"{scheme}://{dom}/"
        try:
            res = fetch(url, require_html=True)
        except RobotsDisallowed:
            v.robots = "disallowed"
            last_reason = "robots_disallowed"
            break
        except RobotsUnavailable as exc:
            # SPLIT BY CAUSE (2026-09-11). One `robots_unavailable` bucket held three
            # different facts, and 7,847 rows of the completed run are un-attributed
            # because of it -- a refusal on this path, a broken host, and a network
            # failure each want a different answer, and "ban them" cannot be ruled on
            # honestly without knowing which is which.
            cause = getattr(exc, "cause", "unknown")
            v.robots = f"unavailable:{cause}"
            last_reason = f"robots_{cause}" if cause != "unknown" else "robots_unavailable"
            break
        except FetchError:
            continue
        except Exception:  # noqa: BLE001 - one host must never end the run
            last_reason = "error"
            continue
        html = str(getattr(res, "content", "") or "")
        base = str(getattr(res, "final_url", "") or url)
        v.robots = "allowed"
        break
    if not html and not base:
        v.status, v.reason = "rejected", last_reason
        v.elapsed_s = round(time.monotonic() - started, 2)
        return v
    v.homepage_url = base
    v.site_title, v.description = extract_site_meta(html)

    # --- the host's own pacing bounds its probes: the fetcher sleeps the declared Crawl-delay
    # before every request, so the probes cost delay x probes of one worker's time. Declared
    # feed links come first in the candidate order, so a small budget still tries the
    # outlet's own declaration before any conventional path.
    max_probes = MAX_FEED_PROBES
    delay = None
    if crawl_delay is not None:
        try:
            delay = crawl_delay(base)
        except Exception:  # noqa: BLE001 - an unreadable delay plans as no delay
            delay = None
    if delay:
        v.crawl_delay_s = float(delay)
        max_probes = min(MAX_FEED_PROBES, int(probe_budget_s // float(delay)))
        if max_probes <= 0:
            v.status, v.reason = "error", "crawl_delay_too_long"
            v.elapsed_s = round(time.monotonic() - started, 2)
            return v

    # --- feed candidates: declared first, then conventional; bounded
    candidates = discover_feed_links(html, base)
    kinds = {u: "link" for u in candidates}
    for path in CONVENTIONAL_PATHS:
        u = urljoin(base, path)
        if u not in kinds:
            candidates.append(u)
            kinds[u] = "conventional"
    reason = "no_feed_found"
    facts: dict = {}
    for url in candidates:
        if v.feed_probes >= max_probes:
            break
        v.feed_probes += 1
        try:
            res = fetch(url, require_html=False)
        except RobotsDisallowed:
            reason = "robots_disallowed"
            continue
        except FetchError:
            continue
        except Exception:  # noqa: BLE001
            continue
        entries = parse_feed(getattr(res, "content", "") or "")
        r, f = evaluate_feed(entries, now=now)
        if r == "verified":
            v.feed_url = str(getattr(res, "final_url", "") or url)
            v.feed_kind = kinds[url]
            reason, facts = r, f
            break
        # keep the most informative failure: a parsed-but-failing feed beats "nothing found"
        if r != "feed_unparseable" or reason == "no_feed_found":
            reason, facts = r, f
    v.entries = int(facts.get("entries", 0))
    v.dated_entries = int(facts.get("dated_entries", 0))
    v.newest_entry = str(facts.get("newest_entry", ""))
    v.titles = list(facts.get("titles", []))
    if reason == "verified":
        v.status = "verified"
        detected = detect_titles_language(v.titles)
        if detected:
            v.language_detected, v.language_basis = detected, "detected"
        elif v.language_export:
            v.language_detected, v.language_basis = v.language_export, "export"
        else:
            v.language_basis = "unknown"
    else:
        v.status = "rejected"
    v.reason = reason
    v.elapsed_s = round(time.monotonic() - started, 2)
    return v


# --------------------------------------------------------------------------- the fetcher

KIT_MARKER = "KIT_MANIFEST.json"   # written at the root of a kit by build_candidate_kit.py


def build_fetcher(*, min_interval_s: float, timeout: float, max_bytes: int, root: Path | None = None):
    """The ONE ethical fetcher, built two ways and never a third. Returns ``(fetcher, mode)``.

    In the repository or an install, the app's own factory (``make_fetcher``) builds it from
    the operator's safety settings -- protected mode, proxy, generic UA -- exactly as every
    ingest path does. In the KIT (a folder built by ``build_candidate_kit.py`` for a session
    without the repository, marked by ``KIT_MANIFEST.json`` at its root) there is no settings
    store to read, so the SAME ``EthicalFetcher`` is built directly in transparent mode with the
    honest bot user agent. ``mode`` names which, for the run log. Nothing else ever fetches."""
    from src.ingest import DEFAULT_USER_AGENT, EthicalFetcher

    params = {"min_interval_s": min_interval_s, "timeout": timeout, "max_bytes": max_bytes}
    if ((root or _ROOT) / KIT_MARKER).exists():
        fetcher = EthicalFetcher(user_agent=DEFAULT_USER_AGENT, **params)
        return fetcher, "kit -- transparent mode, honest bot user agent, no operator settings"
    from src.safety.fetcher import make_fetcher

    return make_fetcher(**params), "app safety settings (make_fetcher)"


# --------------------------------------------------------------------------- outputs

def _name_without_a_false_country(name: str, country: str | None) -> str:
    """Strip a trailing ``(xx)`` that the catalogue would READ AS A COUNTRY but the row
    contradicts.

    ``configs/sources.yml`` uses a trailing parenthetical as a human-authored ORIGIN marker
    (``Name (Country)``), and ``country_from_title`` reads it that way -- so a harvested site
    title that happens to end in something parsing as an ISO-2 code makes an origin CLAIM by
    accident. The measured case: ``3CatInfo (tv)``, the Catalan public broadcaster, where
    ``(tv)`` is the channel's own branding and ``tv`` is Tuvalu; the row's own ``country`` says
    ``es``. The catalogue's own invariant test caught it
    (``test_catalog_honours_its_own_country_suffix_convention``).

    So the parenthetical is kept ONLY when it agrees with the row's country, and dropped
    otherwise -- including when the row has no country at all, since then nothing supports the
    claim. A broadcaster genuinely branded ``(TV)`` loses that suffix: a small cosmetic cost,
    paid because in THIS file that slot means origin, and a name asserting an origin the row
    denies is a fabricated fact, not a formatting nit.
    """
    code = country_from_title(name)
    if not code or code == (country or "").strip().lower():
        return name
    stripped = re.sub(r"\s*\([^()]*\)\s*$", "", name).strip()
    return stripped or name


def to_catalogue_entry(v: Verdict, *, today: str) -> dict:
    """A ``configs/sources.yml`` entry for a VERIFIED verdict -- the schema the diversification
    brief fixed. Fields the run could not establish are OMITTED, never guessed."""
    if v.status != "verified":
        raise ValueError("only a verified verdict becomes a catalogue entry")
    tags = [t for t in v.tags if not any(t.startswith(p) or t == p for p in _ROW_TAGS)]
    if "news" not in tags:
        tags.insert(0, "news")
    entry: dict = {
        "name": _name_without_a_false_country(v.name or v.site_title or v.domain, v.country),
        "domain": v.domain,
        "rss_url": v.feed_url,
        "rate_limit_ms": 2000,
        "enabled": True,
        "verified": True,
        "last_verified": today,
    }
    if v.language_detected:
        entry["language"] = v.language_detected
    if v.country:
        entry["country"] = v.country
        region = _REGION_OF_CONTINENT.get(continent_of(v.country) or "")
        entry["region"] = region or "global"
    else:
        entry["region"] = "global"
    entry["source_type"] = v.source_type if v.source_type in ("news", "magazine", "broadcaster",
                                                              "wire-agency", "investigative") else "news"
    entry["tags"] = tags
    entry["priority"] = 3
    return entry


def write_outputs(verdicts: list[Verdict], out_dir: Path, *, today: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    reasons = Counter(v.reason for v in verdicts)
    verified = [v for v in verdicts if v.status == "verified"]
    with (out_dir / "rejections.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["domain", "name", "reason", "feed_probes", "robots"])
        for v in verdicts:
            if v.status != "verified":
                w.writerow([v.domain, v.name, v.reason, v.feed_probes, v.robots])
    entries = [to_catalogue_entry(v, today=today) for v in verified]
    header = (
        "# Candidate sources whose FEED this run fetched and parsed (verify_candidate_feeds.py).\n"
        f"# {len(entries)} entries, verified {today}. Review, then merge with\n"
        "# scripts/merge_source_batch.py -- never by hand-editing configs/sources.yml.\n"
    )
    (out_dir / "verified_sources.yml").write_text(
        header + yaml.safe_dump({"sources": entries}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    summary = {
        "candidates": len(verdicts),
        "verified": len(verified),
        "by_reason": dict(sorted(reasons.items())),
        "feed_kind": dict(Counter(v.feed_kind for v in verified)),
        "language_basis": dict(Counter(v.language_basis for v in verified)),
        "feed_probes_total": sum(v.feed_probes for v in verdicts),
        "verified_at": today,
        "note": (
            "verified means: the feed was fetched and parsed in THIS run, had >= "
            f"{MIN_ENTRIES} entries with a title and a link, and its newest dated entry was "
            f"within {FRESH_DAYS} days. Nothing here judges what the outlet IS -- that is the "
            "triage stage's question."
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def shard_index(domain: str, shards: int) -> int:
    """Which of ``shards`` machines owns this host. Keyed on the REGISTRABLE DOMAIN.

    That key is the whole point, not a detail. Politeness in this fetcher is a PER-HOST lock
    held inside ONE process, so it cannot span machines: if two shards each held rows that
    resolve to the same host, each would wait its own ``--min-interval`` and the host would
    quietly see DOUBLE the agreed rate -- the fleet breaking a promise no single machine could
    see itself breaking. Keying the split on the SAME function the fetcher and the resume
    cursor already key on means that cannot happen: rows the run treats as one host
    (``x.example`` and ``www.x.example``) land on one machine, and the per-host guarantee
    holds across the fleet exactly as it does on one box.

    WHAT IT DOES NOT CLAIM, stated because the stronger claim is the tempting one:
    ``registrable_domain`` strips ``www.`` but not arbitrary subdomains, so ``a.ui.ac.id`` and
    ``b.ui.ac.id`` are two hosts here and may land on two machines. That is not a regression --
    the per-host lock never covered sibling hosts of one organisation either, so a single run
    at ``--workers 12`` can already fetch both at once. Measured on the real remainder
    worklist, the question is moot: all 18,457 rows are distinct registrable domains, one row
    per host.

    sha256 rather than ``hash()``, which is salted per process and would give each machine a
    DIFFERENT partition of the same worklist -- rows judged twice and rows judged never, with
    nothing in any single run's output to show it. Stable across machines, versions and runs.
    """
    if shards < 1:
        raise ValueError("shards must be >= 1")
    d = registrable_domain(domain) or normalize_domain(domain) or domain
    return int.from_bytes(hashlib.sha256(d.encode("utf-8")).digest()[:8], "big") % shards


def parse_shard(spec: str) -> tuple[int, int]:
    """``"3/8"`` -> ``(3, 8)``, one-based and validated. Refuses anything a typo would produce,
    because a silently-wrong shard spec is a silently-incomplete run."""
    try:
        i_s, n_s = spec.split("/", 1)
        i, n = int(i_s), int(n_s)
    except ValueError:
        raise ValueError(f"--shard wants I/N, e.g. 3/8 (got {spec!r})") from None
    if n < 1 or not (1 <= i <= n):
        raise ValueError(f"--shard I/N needs 1 <= I <= N and N >= 1 (got {spec!r})")
    return i, n


def load_candidates(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if (r.get("domain") or "").strip()]


def load_resume(path: Path) -> tuple[list[Verdict], set[str]]:
    """Every domain's LAST verdict in the cursor, in first-seen order, and the set of domains
    it holds. A re-judged row (``--retry``) appends a newer line; the newest one is the truth."""
    last: dict[str, Verdict] = {}
    if not path.exists():
        return [], set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            v = Verdict(**{k: d[k] for k in d if k in Verdict.__dataclass_fields__})
        except Exception:  # noqa: BLE001 - a torn last line is skipped, never fatal
            continue
        last[v.domain] = v
    return list(last.values()), set(last)


def run(
    rows: list[dict], *, fetch: FetchFn, out_dir: Path, workers: int = 8, now: datetime | None = None,
    catalogue: set[str] | None = None, resume: bool = True, limit: int | None = None,
    progress: Callable[[int, int, Verdict], None] | None = None,
    retry_reasons: set[str] | frozenset[str] = frozenset(),
    crawl_delay: Callable[[str], float | None] | None = None,
    probe_budget_s: float = PROBE_TIME_BUDGET_S, stall_s: float = STALL_S,
    shard: tuple[int, int] | None = None,
    forget_robots: Callable[[str], object] | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    if shard is not None:
        i, n = shard
        rows = [r for r in rows if shard_index(str(r.get("domain") or ""), n) == i - 1]
    catalogue = set(catalogue or ())
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "verified.jsonl"
    prior, done = load_resume(jsonl) if resume else ([], set())
    if retry_reasons:
        # Re-judge the rows whose LAST verdict carries one of these reasons: they leave the
        # done-set, their old lines stay in the cursor, and the new line outranks them.
        redo = {v.domain for v in prior if v.reason in retry_reasons}
        prior = [v for v in prior if v.domain not in redo]
        done = done - redo
        # ...and forget each one's cached robots decision, or the per-host backoff that the
        # earlier failure created would answer this run from cache: the same verdict rewritten,
        # no host actually asked, and nothing in the output saying so. An explicit retry is an
        # operator overriding the deferral, which is exactly what the deferral is not for.
        if forget_robots is not None:
            for domain in redo:
                try:
                    forget_robots(domain)
                except Exception:  # noqa: BLE001 - one host must never end the run
                    pass
    todo = [r for r in rows if (registrable_domain(str(r.get("domain") or "")) or "") not in done]
    if limit is not None:
        todo = todo[:limit]
    seen: set[str] = set(done)
    lock = threading.Lock()
    verdicts: list[Verdict] = list(prior)
    n = 0
    interrupted = False
    stragglers: list[str] = []
    futures: dict = {}
    pool = ThreadPoolExecutor(max_workers=max(1, workers))

    def _domain_of(r: dict) -> str:
        raw = str(r.get("domain") or "").strip()
        return registrable_domain(raw) or normalize_domain(raw) or raw

    with jsonl.open("a", encoding="utf-8") as fh:

        def _record(v: Verdict) -> None:
            nonlocal n
            with lock:
                verdicts.append(v)
                fh.write(json.dumps(asdict(v), ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
            if progress:
                progress(n, len(futures), v)

        try:
            for r in todo:
                dom = registrable_domain(str(r.get("domain") or "")) or ""
                with lock:
                    if dom and dom in seen:
                        continue
                    seen.add(dom)
                futures[pool.submit(verify_candidate, r, fetch=fetch, now=now, catalogue=catalogue,
                                    seen=set(), crawl_delay=crawl_delay,
                                    probe_budget_s=probe_budget_s)] = r
            pending = set(futures)
            order = {fut: i for i, fut in enumerate(futures)}
            while pending:
                finished, pending = wait(pending, timeout=stall_s, return_when=FIRST_COMPLETED)
                if not finished:
                    # Nothing finished for a whole stall window. Whatever is still in flight is
                    # recorded as NOT judged, so one silent host can never hold a worklist
                    # (2026-09-10: one did, for hours, while 3,587 others were done). Their
                    # threads are left to end on their own; main() exits without waiting.
                    for fut in sorted(pending, key=order.__getitem__):
                        r = futures[fut]
                        v = Verdict(
                            domain=_domain_of(r), name=str(r.get("name") or "").strip(),
                            source_type=str(r.get("source_type") or "").strip(),
                            country=str(r.get("country") or "").strip().lower(),
                            language_export=str(r.get("language") or "").strip().lower(),
                            status="error", reason="host_timeout", elapsed_s=float(stall_s),
                            checked_at=now.isoformat(timespec="seconds"),
                            note=f"still in flight after {stall_s:.0f}s with nothing finishing",
                        )
                        stragglers.append(v.domain)
                        _record(v)
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                # Submission order, never set order: several futures can be done by the time
                # the wait returns, and a KeyboardInterrupt surfacing from one host's future
                # must not hide a row that finished before it (CI caught exactly that race).
                for fut in sorted(finished, key=order.__getitem__):
                    try:
                        v = fut.result()
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:  # noqa: BLE001 - one host's crash never ends the run
                        r = futures[fut]
                        v = Verdict(
                            domain=_domain_of(r), name=str(r.get("name") or "").strip(),
                            country=str(r.get("country") or "").strip().lower(),
                            language_export=str(r.get("language") or "").strip().lower(),
                            status="rejected", reason="error",
                            checked_at=now.isoformat(timespec="seconds"),
                            note=f"{type(exc).__name__}: {exc}"[:200],
                        )
                    _record(v)
        except KeyboardInterrupt:
            # Ctrl-C on a laptop run: take no new host, let the in-flight ones finish unrecorded
            # (the next run re-judges them -- cheap and correct), keep every row already written.
            # The JSONL cursor is exactly what --resume reads, so the same command continues.
            interrupted = True
            pool.shutdown(wait=False, cancel_futures=True)
        else:
            if not stragglers:
                pool.shutdown(wait=True)
    summary = write_outputs(verdicts, out_dir, today=now.date().isoformat())
    summary["interrupted"] = interrupted
    summary["judged_this_run"] = n
    summary["remaining"] = max(0, len(futures) - n)
    summary["stragglers"] = stragglers
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-interval", type=float, default=2.0, help="per-host politeness, seconds")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--catalogue", type=Path, action="append", default=None,
                    help="extra catalogue YAML(s) to dedupe against (the repo's are always included)")
    ap.add_argument("--retry", default="",
                    help="re-judge rows whose LAST verdict has one of these reasons (comma-separated), "
                         "e.g. host_timeout,crawl_delay_too_long")
    ap.add_argument("--probe-budget", type=float, default=PROBE_TIME_BUDGET_S,
                    help="seconds a host's declared Crawl-delay may cost across its feed probes")
    ap.add_argument("--shard", default=None, metavar="I/N",
                    help="judge only this machine's slice of the worklist, e.g. 3/8. Split by HOST, "
                         "so every row of one host stays on one machine and the per-host politeness "
                         "interval still holds across the fleet. Give each machine its own --out-dir.")
    ap.add_argument("--stall", type=float, default=STALL_S,
                    help="seconds without any host finishing before the in-flight ones are host_timeout")
    args = ap.parse_args(argv)
    retry = {s.strip() for s in args.retry.split(",") if s.strip()}
    unknown = sorted(retry - set(REASONS))
    if unknown:
        ap.error(f"--retry: unknown reason(s) {unknown}; known: {', '.join(REASONS)}")

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # IDN domains on a cp1252 console
        except (AttributeError, ValueError):
            pass
    fetcher, mode = build_fetcher(min_interval_s=args.min_interval, timeout=args.timeout,
                                  max_bytes=FEED_MAX_BYTES)
    print(f"fetcher: {mode}", flush=True)
    paths = [_ROOT / p for p in CATALOGUE_FILES] + list(args.catalogue or [])
    cat = catalogue_domains(paths)
    rows = load_candidates(args.candidates)

    def _progress(i: int, total: int, v: Verdict) -> None:
        if i % 50 == 0 or i == total:
            print(f"{i}/{total}  {v.domain}: {v.reason}", flush=True)

    summary = run(rows, fetch=fetcher.fetch, out_dir=args.out_dir, workers=args.workers,
                  catalogue=cat, resume=not args.no_resume, limit=args.limit, progress=_progress,
                  shard=parse_shard(args.shard) if args.shard else None,
                  forget_robots=getattr(fetcher, "forget_robots", None),
                  retry_reasons=retry, crawl_delay=getattr(fetcher, "crawl_delay_for", None),
                  probe_budget_s=args.probe_budget, stall_s=args.stall)
    print(json.dumps(summary, indent=1))
    code = 0
    if summary.get("interrupted"):
        print(f"interrupted: {summary['judged_this_run']} judged this run, {summary['remaining']} remaining "
              "-- run the same command again to continue (it resumes from verified.jsonl)", flush=True)
        code = 130
    if summary.get("stragglers"):
        print(f"{len(summary['stragglers'])} host(s) still in flight after {args.stall:.0f}s with nothing "
              f"finishing ({', '.join(summary['stragglers'][:5])}): recorded as host_timeout, NOT judged "
              "-- re-judge them later with --retry host_timeout. Exiting without waiting for them.",
              flush=True)
        # Their threads are blocked inside a fetch (a sleep the host asked for, a tarpit): a
        # normal exit would wait for them, which is the hang this guards against.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
