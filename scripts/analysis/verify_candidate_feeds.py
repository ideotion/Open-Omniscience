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
run can be split across sessions (``--limit``) and a crash costs nothing already written.

RUN (inside a clearnet session, after building the venv -- in the repository or in the kit):
  .venv/bin/python scripts/analysis/verify_candidate_feeds.py \
      --candidates path/to/shortlist.csv --out-dir data/candidate_feeds --workers 8 --resume
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from src.catalog.normalize import registrable_domain  # noqa: E402
from src.ingest import FetchError, RobotsDisallowed, RobotsUnavailable  # noqa: E402
from src.utils.url_utils import DOMAIN_ALIASES, normalize_domain  # noqa: E402

MIN_ENTRIES = 3
FRESH_DAYS = 120
MAX_LINK_FEEDS = 3          # <link rel=alternate> candidates tried, in page order
MAX_FEED_PROBES = 6         # feed fetches per host, links + conventional paths together
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
    robots: str = ""                  # allowed | disallowed | unavailable | ""
    tags: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    checked_at: str = ""


REASONS = (
    "duplicate_of_catalogue", "duplicate_in_run", "robots_disallowed", "robots_unavailable",
    "homepage_unreachable", "no_feed_found", "feed_unparseable", "feed_too_few_entries",
    "feed_stale", "feed_undated", "verified", "error",
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
) -> Verdict:
    """The whole check for ONE candidate. ``fetch(url, require_html=...)`` is the fetcher's
    ``fetch`` (a seam so tests inject a fake); it returns an object with ``content`` and
    ``final_url`` and raises ``FetchError`` subclasses on refusal."""
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
        except RobotsUnavailable:
            v.robots = "unavailable"
            last_reason = "robots_unavailable"
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
        if v.feed_probes >= MAX_FEED_PROBES:
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

def to_catalogue_entry(v: Verdict, *, today: str) -> dict:
    """A ``configs/sources.yml`` entry for a VERIFIED verdict -- the schema the diversification
    brief fixed. Fields the run could not establish are OMITTED, never guessed."""
    if v.status != "verified":
        raise ValueError("only a verified verdict becomes a catalogue entry")
    tags = [t for t in v.tags if not any(t.startswith(p) or t == p for p in _ROW_TAGS)]
    if "news" not in tags:
        tags.insert(0, "news")
    entry: dict = {
        "name": v.name or v.site_title or v.domain,
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


def load_candidates(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if (r.get("domain") or "").strip()]


def load_resume(path: Path) -> tuple[list[Verdict], set[str]]:
    verdicts: list[Verdict] = []
    if not path.exists():
        return verdicts, set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            verdicts.append(Verdict(**{k: d[k] for k in d if k in Verdict.__dataclass_fields__}))
        except Exception:  # noqa: BLE001 - a torn last line is skipped, never fatal
            continue
    return verdicts, {v.domain for v in verdicts}


def run(
    rows: list[dict], *, fetch: FetchFn, out_dir: Path, workers: int = 8, now: datetime | None = None,
    catalogue: set[str] | None = None, resume: bool = True, limit: int | None = None,
    progress: Callable[[int, int, Verdict], None] | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    catalogue = set(catalogue or ())
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "verified.jsonl"
    prior, done = load_resume(jsonl) if resume else ([], set())
    todo = [r for r in rows if (registrable_domain(str(r.get("domain") or "")) or "") not in done]
    if limit is not None:
        todo = todo[:limit]
    seen: set[str] = set(done)
    lock = threading.Lock()
    verdicts: list[Verdict] = list(prior)
    n = 0
    with jsonl.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {}
        for r in todo:
            dom = registrable_domain(str(r.get("domain") or "")) or ""
            with lock:
                if dom and dom in seen:
                    continue
                seen.add(dom)
            futures[pool.submit(verify_candidate, r, fetch=fetch, now=now, catalogue=catalogue,
                                seen=set())] = r
        for fut in as_completed(futures):
            v = fut.result()
            with lock:
                verdicts.append(v)
                fh.write(json.dumps(asdict(v), ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
            if progress:
                progress(n, len(futures), v)
    return write_outputs(verdicts, out_dir, today=now.date().isoformat())


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
    args = ap.parse_args(argv)

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
                  catalogue=cat, resume=not args.no_resume, limit=args.limit, progress=_progress)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
