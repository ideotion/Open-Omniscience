"""
Source-reliability preflight (maintainer-requested, 0.0.8 live-test feedback).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before really scraping, test every enabled source once: reach its homepage,
read its robots.txt, and record the verdict -- updating the per-source scraper
settings (SourceMetadata.robots_allowed, crawl_delay) accordingly. Every check
is appended to ``data/source_preflight.jsonl`` so the operator can hand the log
back for debugging. Sources whose robots.txt says "no" are flagged loudly (a
Home alert via the existing card engine reads this log) -- and the fetcher
already fail-closes on them at scrape time, so the alert is information, not
the enforcement.

Runs automatically ONCE before the first scheduler scrape (piggybacking an
operation that is already going to the network -- never at app boot, which must
stay offline), and on demand via POST /api/sources/preflight.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

_LOG = logging.getLogger(__name__)

_DEFAULT_LIMIT = 50  # bounded by design; the operator can raise per call


def _log_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "source_preflight.jsonl"


def has_run_before() -> bool:
    return _log_path().exists()


def _check_one(fetcher, source) -> dict:
    """One source's verdict. Uses the EthicalFetcher's session (same UA/proxy
    posture as real scraping) but reads robots DIRECTLY so we can report the
    status distinctly rather than just refusing.

    Audit finding 2026-07-17 (SSRF, CWE-918): this used to call
    ``fetcher.session.get(url, allow_redirects=True)`` directly on the raw
    ``requests.Session``, bypassing BOTH ``EthicalFetcher._guard_target``
    (which refuses private/loopback/link-local targets) and the manual
    per-hop redirect revalidation ``EthicalFetcher._guarded_redirect_get``
    already does for every other fetch path in this codebase -- the exact
    "robots used allow_redirects=True and so let its redirect chain bypass
    the guard" bug already found and fixed once inside ``EthicalFetcher``
    itself (see ``_guarded_redirect_get``'s own docstring). A source whose
    domain (user-addable via discovery/custom sources) later 30x-redirects
    to ``127.0.0.1``/a link-local address/a DNS-rebinding hostname would be
    fetched here with no guard at all. Fixed by guarding the INITIAL target
    explicitly (mirroring what ``EthicalFetcher.fetch()`` does before every
    real fetch) and routing both GETs through ``_guarded_redirect_get``,
    which re-validates every redirect hop the same way the real scrape path
    does.
    """
    base = f"https://{source.domain}"
    rec: dict = {
        "source_id": source.id,
        "domain": source.domain,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        fetcher._guard_target(urlparse(base).hostname)
    except Exception as exc:  # noqa: BLE001 - a refused/unresolvable target must not stop the sweep
        rec["robots"] = "unreachable"
        rec["robots_error"] = str(exc)[:200]
        rec["reachable"] = False
        rec["homepage_error"] = str(exc)[:200]
        rec["verdict"] = "unreachable"
        return rec

    # robots.txt -- the contract that governs everything else
    crawl_delay = None
    try:
        resp, _final = fetcher._guarded_redirect_get(f"{base}/robots.txt")
        code = resp.status_code
        if code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            allowed = rp.can_fetch(fetcher.user_agent, base + "/")
            rec["robots"] = "allowed" if allowed else "disallowed"
            try:
                crawl_delay = rp.crawl_delay(fetcher.user_agent)
            except Exception:  # noqa: BLE001
                crawl_delay = None
        elif code in (404, 410):
            rec["robots"] = "missing"  # standard: no robots.txt => everything allowed
        elif code in (401, 403):
            rec["robots"] = "blocked"  # site forbids reading robots => treat site as off-limits
        else:
            rec["robots"] = f"http_{code}"
    except Exception as exc:  # noqa: BLE001 - per-source problems must not stop the sweep
        rec["robots"] = "unreachable"
        rec["robots_error"] = str(exc)[:200]

    if crawl_delay:
        rec["crawl_delay_s"] = float(crawl_delay)

    # homepage ping (reachability + status), through the same guarded path
    try:
        resp, _final = fetcher._guarded_redirect_get(base + "/")
        rec["homepage_status"] = resp.status_code
        rec["reachable"] = 200 <= resp.status_code < 400
    except Exception as exc:  # noqa: BLE001
        rec["reachable"] = False
        rec["homepage_error"] = str(exc)[:200]

    rec["verdict"] = (
        "ok" if rec.get("reachable") and rec["robots"] in ("allowed", "missing")
        else "robots_denied" if rec["robots"] in ("disallowed", "blocked")
        else "unreachable"
    )
    return rec


def _apply_to_metadata(session, source, rec: dict) -> None:
    """Record the verdict on the source's scraper settings (real data, no guesses)."""
    from src.database.models import SourceMetadata

    meta = session.query(SourceMetadata).filter_by(source_id=source.id).first()
    if meta is None:
        meta = SourceMetadata(source_id=source.id)
        session.add(meta)
    meta.robots_allowed = rec["verdict"] != "robots_denied"
    if rec.get("crawl_delay_s"):
        meta.crawl_delay = rec["crawl_delay_s"]
        # honour a robots crawl-delay larger than the source's current politeness
        wanted_ms = int(rec["crawl_delay_s"] * 1000)
        if (source.rate_limit_ms or 0) < wanted_ms:
            source.rate_limit_ms = wanted_ms
    meta.robots_txt_url = f"https://{source.domain}/robots.txt"


def preflight_sources(session, fetcher=None, *, limit: int = _DEFAULT_LIMIT) -> dict:
    """Check up to ``limit`` enabled sources; log, apply, and summarise."""
    from src.database.models import Source

    if fetcher is None:
        from src.safety.fetcher import make_fetcher

        fetcher = make_fetcher()

    sources = (
        session.query(Source)
        .filter(Source.enabled.is_(True))
        .order_by(Source.priority.asc(), Source.id.asc())
        .limit(max(1, limit))
        .all()
    )
    records = []
    for src in sources:
        rec = _check_one(fetcher, src)
        _apply_to_metadata(session, src, rec)
        records.append(rec)
    session.flush()

    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    summary = {
        "checked": len(records),
        "ok": sum(1 for r in records if r["verdict"] == "ok"),
        "robots_denied": sorted(r["domain"] for r in records if r["verdict"] == "robots_denied"),
        "unreachable": sorted(r["domain"] for r in records if r["verdict"] == "unreachable"),
        "log": str(path),
    }
    if summary["robots_denied"]:
        _LOG.warning(
            "preflight: robots.txt denies scraping for: %s (recorded; the fetcher "
            "fail-closes on these regardless)",
            ", ".join(summary["robots_denied"]),
        )
    return summary


def recent_results(limit: int = 200) -> list[dict]:
    """The latest verdict per domain from the log (newest wins)."""
    path = _log_path()
    if not path.exists():
        return []
    by_domain: dict[str, dict] = {}
    for line in path.read_text("utf-8").splitlines()[-2000:]:
        try:
            rec = json.loads(line)
            by_domain[rec.get("domain", "?")] = rec
        except json.JSONDecodeError:
            continue
    rows = sorted(by_domain.values(), key=lambda r: r.get("checked_at", ""), reverse=True)
    return rows[: max(1, limit)]
