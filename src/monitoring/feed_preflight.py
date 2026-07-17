"""
First-run feed preflight: robots + sample verification for every NON-SOURCE
fetch target (commodity/index CSV feeds, calendar feeds), appended to a
shareable JSONL log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (2026-06-10): initialization must verify the bundled calendar
directory and extract robots verdicts for ALL default fetch targets — sources,
financial feeds, calendars — into a log the operator can hand back, so the
default install's lists can be optimized from real verdicts ("manage a clean
install"). Boot stays offline: like the source preflight, this runs ONCE,
immediately before the first scheduled scrape (the run that is already going
to the network), and on demand.

Politeness: feeds cluster on a handful of hosts (FRED, calendar.google.com,
worldpublicholiday.com, webcal.guru…). We check robots ONCE per distinct host
and verify a bounded SAMPLE of feeds per provider — enough to validate each
provider's URL pattern without hammering anyone. Full verification stays an
explicit operator action (the directory's Verify buttons / verify-batch).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from src.paths import data_dir

_LOG = logging.getLogger(__name__)
_SAMPLE_PER_PROVIDER = 3


def _log_path() -> Path:
    return data_dir() / "feed_preflight.jsonl"


def has_run_before() -> bool:
    return _log_path().exists()


def _append(records: list[dict]) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def recent_results(limit: int = 1000) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _check_host_robots(fetcher, host: str) -> dict:
    """One host's robots verdict (the same honest taxonomy as the source preflight).

    Audit finding 2026-07-17 (SSRF, CWE-918): same fix as
    ``src/monitoring/preflight.py::_check_one`` -- a raw
    ``fetcher.session.get(url, allow_redirects=True)`` bypasses
    ``EthicalFetcher``'s SSRF guard and per-hop redirect revalidation. Guard
    the initial target explicitly, then route through
    ``EthicalFetcher._guarded_redirect_get`` (the same guarded path every
    real fetch uses) instead of the raw session.
    """
    rec: dict = {
        "kind": "robots",
        "host": host,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        fetcher._guard_target(urlparse(f"https://{host}").hostname)
        resp, _final = fetcher._guarded_redirect_get(f"https://{host}/robots.txt")
        code = resp.status_code
        if code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            rec["robots"] = (
                "allowed" if rp.can_fetch(fetcher.user_agent, f"https://{host}/") else "disallowed"
            )
            try:
                delay = rp.crawl_delay(fetcher.user_agent)
            except Exception:  # noqa: BLE001
                delay = None
            if delay:
                rec["crawl_delay_s"] = float(delay)
        elif code in (404, 410):
            rec["robots"] = "missing"  # no robots.txt => everything allowed (standard)
        elif code in (401, 403):
            rec["robots"] = "blocked"
        else:
            rec["robots"] = f"http_{code}"
    except Exception as exc:  # noqa: BLE001 - one host must not stop the sweep
        rec["robots"] = "unreachable"
        rec["error"] = str(exc)[:200]
    return rec


def _feed_targets() -> tuple[list[dict], list[dict]]:
    """(market_feeds, calendar_feeds) as {kind, key, url, host} — from the
    bundled catalogs only; nothing is invented."""
    market = []
    try:
        from src.markets.feed_catalog import load_feeds, load_index_feeds

        for f in list(load_feeds()) + list(load_index_feeds()):
            market.append(
                {
                    "kind": "market_feed",
                    "key": f.key,
                    "url": f.url,
                    "host": urlparse(f.url).netloc,
                }
            )
    except Exception:  # noqa: BLE001
        _LOG.warning("market feed catalog unavailable for preflight", exc_info=True)
    calendar = []
    try:
        from src.events.feeds import load_families

        for fam in load_families():
            for fd in fam["feeds"]:
                calendar.append(
                    {
                        "kind": "calendar_feed",
                        "key": fd["id"],
                        "url": fd["url"],
                        "host": urlparse(fd["url"]).netloc,
                    }
                )
    except Exception:  # noqa: BLE001
        _LOG.warning("calendar catalog unavailable for preflight", exc_info=True)
    return market, calendar


def run_feed_preflight(fetcher, *, sample_per_provider: int = _SAMPLE_PER_PROVIDER) -> dict:
    """Robots per distinct host + a per-provider sample verification; JSONL appended.

    Returns an honest summary {hosts, robots_denied, calendar_checked, market_checked}.
    Every verdict (good or bad) lands in the log — the point IS the log.
    """
    market, calendar = _feed_targets()
    records: list[dict] = []

    hosts = sorted({t["host"] for t in market + calendar if t["host"]})
    robots_by_host: dict[str, dict] = {}
    for host in hosts:
        rec = _check_host_robots(fetcher, host)
        robots_by_host[host] = rec
        records.append(rec)

    def _sample(targets: list[dict]) -> list[dict]:
        by_host: dict[str, int] = {}
        picked = []
        for t in targets:
            if robots_by_host.get(t["host"], {}).get("robots") in ("disallowed", "blocked"):
                continue  # never sample where robots said no — the verdict suffices
            if by_host.get(t["host"], 0) >= sample_per_provider:
                continue
            by_host[t["host"]] = by_host.get(t["host"], 0) + 1
            picked.append(t)
        return picked

    calendar_checked = 0
    for t in _sample(calendar):
        try:
            from src.events.feeds import verify_feed

            verdict = verify_feed(fetcher, t["key"])
            records.append({**t, **verdict})
            calendar_checked += 1
        except Exception as exc:  # noqa: BLE001
            records.append({**t, "status": "error", "error": str(exc)[:200]})

    market_checked = 0
    for t in _sample(market):
        rec = {**t, "checked_at": datetime.now(UTC).isoformat(timespec="seconds")}
        try:
            result = fetcher.fetch(t["url"], require_html=False)
            body = result.content or ""
            rec["status"] = "ok" if body.strip() else "empty"
            rec["bytes"] = len(body.encode("utf-8", "ignore"))
        except Exception as exc:  # noqa: BLE001
            rec["status"] = "unreachable"
            rec["error"] = str(exc)[:200]
        records.append(rec)
        market_checked += 1

    _append(records)
    denied = sum(1 for r in robots_by_host.values() if r["robots"] in ("disallowed", "blocked"))
    summary = {
        "hosts": len(hosts),
        "robots_denied": denied,
        "calendar_feeds_sampled": calendar_checked,
        "market_feeds_sampled": market_checked,
        "log": str(_log_path()),
    }
    _LOG.info("feed preflight: %s", summary)
    return summary
