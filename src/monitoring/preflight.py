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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from src.ingest import (
    EthicalFetcher,
    RobotsDisallowed,
    RobotsUnavailable,
    kill_switch_engaged_since,
    kill_switch_epoch,
)
from src.ingest.fetch_verdict import is_kill_switch_refusal
from src.monitoring.secret_scrub import record_text

_LOG = logging.getLogger(__name__)

_DEFAULT_LIMIT = 50  # bounded by design; the operator can raise per call

#: The fixed words of a homepage ping that robots.txt kept from being made (R636), written as the record's ``homepage_skipped``.
#: The ping obeys robots.txt, fail-closed: it is made only when the read of robots.txt just before it allows the homepage or finds
#: none (404/410), and each redirect hop it would follow is robots-checked as a page fetch's is. Fixed words, never a refusal's own
#: text: the record is handed back as it is, and its reachability is then not established (``reachable`` is None).
_PING_SKIPPED_DISALLOWED = "homepage not requested: robots.txt disallows it"
_PING_SKIPPED_UNREADABLE = "homepage not requested: robots.txt could not be read"
#: ... and of a ping whose redirect was not followed: the homepage answered (a redirect, so it is reachable), its hop was refused.
_PING_HOP_DISALLOWED = "homepage redirect not followed: robots.txt disallows the address it leads to"
_PING_HOP_UNREADABLE = "homepage redirect not followed: the robots.txt of the address it leads to could not be read"


def _log_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "source_preflight.jsonl"


def has_run_before() -> bool:
    return _log_path().exists()


def _skipped_offline(rec: dict, refusal: str) -> dict:
    """The record of a source nobody asked (a check that FAILED while the kill switch is engaged is read as the switch's, whatever shape
    the error took: ``_guarded_redirect_get`` is not wrapped by the fetcher, so a Stop that lands during the request arrives as the raw
    ``HTTPSConnectionPool(...)`` requests error, which the anchored sentence match rightly does not admit; the cost is one genuine
    failure discarded when it coincides with a Stop, and the run is retried whole on the next online pass): airplane mode refused the check, so the source's reachability and robots are UNKNOWN, which
    is a different fact from unreachable (the same idiom as feed verification: ``skipped_offline``, present only when the kill switch
    caused it)."""
    rec["verdict"] = "skipped_offline"
    rec["robots"] = "skipped_offline"
    rec["reachable"] = None
    rec["skipped_offline"] = True
    rec["refusal"] = refusal
    return rec


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
    # The engagement epoch (R614), captured before this source's first request: a Stop pressed and cleared again anywhere in the check,
    # waits included, makes a failure the switch's, as when the switch is still engaged.
    epoch = kill_switch_epoch()
    rec: dict = {
        "source_id": source.id,
        "domain": source.domain,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        EthicalFetcher._refuse_parser_mismatch(base)  # before the guard looks the domain up (R622)
        fetcher._guard_target(urlparse(base).hostname)
    except Exception as exc:  # noqa: BLE001 - a refused/unresolvable target must not stop the sweep
        if is_kill_switch_refusal(record_text(exc)) or kill_switch_engaged_since(epoch):  # our sentence on the WHOLE scrubbed text (R298), or a Stop in the check (R614)
            return _skipped_offline(rec, record_text(exc, limit=200, typed=False))
        rec["robots"] = "unreachable"
        rec["robots_error"] = record_text(exc, limit=200, typed=False)
        rec["reachable"] = False
        rec["homepage_error"] = record_text(exc, limit=200, typed=False)
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
            # The host declined to serve robots.txt to us: off-limits, fail-closed, as the fetcher treats it (RobotsUnavailable,
            # cause "refused"). A refusal on that ONE path, not a policy (over Tor often the exit's reputation): its verdict is
            # ``robots_refused``, never ``robots_denied``, and the metadata column stays unknown (OPEN_QUEUE C1).
            rec["robots"] = "blocked"
        else:
            rec["robots"] = f"http_{code}"
    except Exception as exc:  # noqa: BLE001 - per-source problems must not stop the sweep
        if is_kill_switch_refusal(record_text(exc)) or kill_switch_engaged_since(epoch):  # our sentence on the WHOLE scrubbed text (R298), or a Stop in the check (R614)
            return _skipped_offline(rec, record_text(exc, limit=200, typed=False))
        rec["robots"] = "unreachable"
        rec["robots_error"] = record_text(exc, limit=200, typed=False)

    if crawl_delay:
        rec["crawl_delay_s"] = float(crawl_delay)

    # homepage ping (reachability + status), through the same guarded path. It obeys robots.txt, fail-closed (R636): only a read
    # above that allows the homepage or finds no robots.txt lets it be made, and ``hop_robots`` checks each hop it would follow.
    hop_verdict = None
    if rec["robots"] not in ("allowed", "missing"):
        rec["reachable"] = None  # nobody asked: not established, never "unreachable"
        rec["homepage_skipped"] = _PING_SKIPPED_DISALLOWED if rec["robots"] == "disallowed" else _PING_SKIPPED_UNREADABLE
    else:
        try:
            resp, _final = fetcher._guarded_redirect_get(base + "/", hop_robots=True)
            rec["homepage_status"] = resp.status_code
            rec["reachable"] = 200 <= resp.status_code < 400
        except Exception as exc:  # noqa: BLE001
            if is_kill_switch_refusal(record_text(exc)) or kill_switch_engaged_since(epoch):  # our sentence on the WHOLE scrubbed text (R298), or a Stop in the check (R614)
                return _skipped_offline(rec, record_text(exc, limit=200, typed=False))
            if isinstance(exc, (RobotsDisallowed, RobotsUnavailable)):
                # Only a hop is robots-checked in there, so the homepage answered with a redirect: reachable, as a 3xx is above.
                rec["reachable"] = True
                rec["homepage_skipped"] = _PING_HOP_DISALLOWED if isinstance(exc, RobotsDisallowed) else _PING_HOP_UNREADABLE
                # ... and not "ok": the address the homepage sends a crawler to is off-limits by its robots.txt, or its robots.txt
                # could not be read (steward 3's low 1). ``robots`` stays the homepage's own answer, which is what the metadata
                # records (``robots_allowed``), since the homepage's robots.txt did allow it.
                hop_verdict = (
                    "robots_denied"
                    if isinstance(exc, RobotsDisallowed)
                    else "robots_refused"
                    if getattr(exc, "cause", None) == "refused"  # 401/403 on the hop host's robots.txt (OPEN_QUEUE C1)
                    else "unreachable"
                )
            else:
                rec["reachable"] = False
                rec["homepage_error"] = record_text(exc, limit=200, typed=False)

    rec["verdict"] = hop_verdict or (
        "ok" if rec.get("reachable") and rec["robots"] in ("allowed", "missing")
        else "robots_denied" if rec["robots"] == "disallowed"
        else "robots_refused" if rec["robots"] == "blocked"
        else "unreachable"
    )
    return rec


def _apply_to_metadata(session, source, rec: dict) -> None:
    """Record the verdict on the source's scraper settings (real data, no guesses)."""
    from sqlalchemy import null

    from src.database.models import SourceMetadata

    meta = session.query(SourceMetadata).filter_by(source_id=source.id).first()
    created = meta is None
    if meta is None:
        meta = SourceMetadata(source_id=source.id)
        session.add(meta)
    # TRI-STATE, and the None is the point (2026-09-11). This was
    # `rec["verdict"] != "robots_denied"`, which wrote robots_allowed=True whenever the
    # verdict was "unreachable" -- asserting, in the API and in every query over this
    # column, a permission that was never established, from a robots.txt we never read.
    # The column is nullable and NULL means UNKNOWN: we did not learn whether crawling is
    # allowed, which is a different fact from learning that it is.
    robots_state = rec.get("robots")
    if robots_state in ("allowed", "missing"):
        meta.robots_allowed = True
    elif robots_state == "disallowed":
        meta.robots_allowed = False
    else:                                   # blocked (401/403) / unreachable / http_5xx / anything unrecognised
        # "blocked" joined this branch with OPEN_QUEUE C1: a robots.txt the host refused to serve us was never read, so it
        # says nothing about whether crawling is allowed. The fetcher refuses the site either way (fail-closed, unchanged).
        # On a row this call creates, a plain ``None`` is not written: the ORM leaves a None column with a default out of the
        # INSERT, so the column's ``default=True`` was stored and a source checked for the first time read as ALLOWED from a
        # robots.txt nobody read (measured 2026-11-14 for "unreachable"). ``null()`` writes the NULL.
        meta.robots_allowed = null() if created else None
    if rec.get("crawl_delay_s"):
        meta.crawl_delay = rec["crawl_delay_s"]
        # honour a robots crawl-delay larger than the source's current politeness
        wanted_ms = int(rec["crawl_delay_s"] * 1000)
        if (source.rate_limit_ms or 0) < wanted_ms:
            source.rate_limit_ms = wanted_ms
    meta.robots_txt_url = f"https://{source.domain}/robots.txt"


def preflight_sources(
    session,
    fetcher=None,
    *,
    limit: int = _DEFAULT_LIMIT,
    progress: Callable[[int, int, str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Check up to ``limit`` enabled sources; log, apply, and summarise.

    ``progress(done, total, domain)`` is called after each source so the task manager
    can name what is being checked (PRH-23: the first-run preflight is up to 50 hosts
    over Tor, and with no progress a first launch looks stalled). ``should_stop()`` is
    consulted between sources.

    AIRPLANE MODE IS A STOP TOO, and is named as one: a source the kill switch refused was never asked, so it is not "unreachable" and
    its learned ``robots_allowed`` is not overwritten with NULL. The sweep reports ``complete: False`` and ``skipped_offline`` (present
    only then) and the caller rolls back (``skipped_offline`` the same additive idiom as feed verification).

    ALL-OR-NOTHING on a stop, deliberately: the log is what :func:`has_run_before`
    reads, so writing a partial log would mark the preflight "done" with most sources
    unchecked and nothing would ever go back for them. A stopped run writes NO log and
    reports ``complete: False``; the caller rolls back and the next pass retries the
    whole bounded set. Same reason the caller must not commit a partial run.
    """
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
    complete = True
    refused: dict | None = None
    # robots.txt and the homepage are the OUTLET's: its feeds share the verdict, so the host is asked once per
    # sweep (row J, D1) and every feed row still gets its own record and its own metadata.
    by_outlet: dict[str, dict] = {}
    for i, src in enumerate(sources):
        if should_stop is not None and should_stop():
            complete = False
            break
        first = by_outlet.get(src.domain)
        if first is None:
            rec = _check_one(fetcher, src)
            by_outlet[src.domain] = rec
        else:
            rec = {**first, "source_id": src.id}
        if rec.get("skipped_offline"):
            # The kill switch refuses every host the same way: stop asking, and stop here with NOTHING written (below).
            refused = rec
            break
        _apply_to_metadata(session, src, rec)
        records.append(rec)
        if progress is not None:
            progress(i + 1, len(sources), rec.get("domain") or "")
    if refused is not None:
        return {
            "checked": len(records),
            "complete": False,
            "skipped_offline": len(sources) - len(records),
            "stopped": "the network kill switch (airplane mode) is engaged: the remaining sources were not asked. Nothing was logged "
            "or changed, so no source is marked unreachable and the first-run preflight still runs on the next online pass",
        }
    if not complete:
        return {
            "checked": len(records),
            "complete": False,
            "stopped": "cancelled before every source was checked; nothing was logged, "
            "so the next pass retries the whole set",
        }
    session.flush()

    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    summary: dict[str, Any] = {
        "checked": len(records),
        "complete": True,
        "ok": sum(1 for r in records if r["verdict"] == "ok"),
        "robots_denied": sorted(r["domain"] for r in records if r["verdict"] == "robots_denied"),
        # 401/403 on robots.txt: refused to us, not a stated policy (OPEN_QUEUE C1); still never scraped.
        "robots_refused": sorted(r["domain"] for r in records if r["verdict"] == "robots_refused"),
        "unreachable": sorted(r["domain"] for r in records if r["verdict"] == "unreachable"),
        "log": str(path),
    }
    if summary["robots_denied"]:
        _LOG.warning(
            "preflight: robots.txt denies scraping for: %s (recorded; the fetcher "
            "fail-closes on these regardless)",
            ", ".join(summary["robots_denied"]),
        )
    if summary["robots_refused"]:
        _LOG.warning(
            "preflight: these hosts refused to serve robots.txt (401/403), so they are not scraped; "
            "that is a refusal to us, not a stated policy: %s",
            ", ".join(summary["robots_refused"]),
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
