"""
TEMPORARY field-test instrumentation — the 0.0.8 live-test cycle only.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS (read this if you found it in a public clone): during the 0.0.8
live-test cycle the maintainer reinstalls the app repeatedly and sends the
debug bundle back to development. To make each install a productive test, this
module AUTOMATES exercising every network surface once — calendar-feed
verification (in polite batches), the market + index feed imports, one law
track and one wiki track — and records every outcome verbatim in
``data/field_test.jsonl`` (aggregated into the Settings → debug bundle).

It is TEMPORARY, for recurring self-improvement of the default install's
source/feed lists. It will be disabled/removed when the cycle ends. It does
NOT transmit anything: all logs stay on this machine until the operator
explicitly downloads and shares the bundle.

DEFAULT OFF for the public 0.1 tag: set ``OO_FIELD_TEST=1`` to opt in (the
maintainer still uses it for the reinstall/debug-bundle loop). When off, nothing
runs and no log is written. Boot is unaffected either way — steps run only inside
the first collect passes, which are already going to the network at the operator's
request, and every fetch goes through the ethical fetcher (robots fail-closed,
kill-switch aware).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from src.paths import data_dir

_LOG = logging.getLogger(__name__)
_CAL_BATCH = 50  # calendar feeds verified per collect pass (polite, resumable)


def enabled() -> bool:
    """Default OFF for the public 0.1 tag; set OO_FIELD_TEST=1 to opt in (temporary)."""
    return os.getenv("OO_FIELD_TEST", "0") == "1"


def _log_path() -> Path:
    return data_dir() / "field_test.jsonl"


def _append(rec: dict) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def recent_results(limit: int = 500) -> list[dict]:
    path = _log_path()
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _step_done(step: str) -> bool:
    return any(r.get("step") == step and r.get("ok") for r in recent_results(2000))


def _run_step(step: str, fn) -> None:
    rec = {"step": step, "at": datetime.now(UTC).isoformat(timespec="seconds")}
    try:
        rec["result"] = fn()
        rec["ok"] = True
    except Exception as exc:  # noqa: BLE001 - the verdict IS the data we want
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    _append(rec)
    _LOG.info("field-test step %s: ok=%s", step, rec["ok"])


def run_field_test(session, fetcher) -> dict | None:
    """Run the next pending field-test steps (one-time each; calendars batched).

    Called from the collect pass (never at boot). Honest + bounded: each step
    records exactly what happened; nothing retries forever; kill switch and
    robots verdicts apply through the shared fetcher.
    """
    if not enabled():
        return None

    # 1. Calendar directory: verify the next polite batch until all are checked.
    def _calendars():
        from src.events.feeds import load_families, load_verdicts, verify_feed

        verdicts = load_verdicts()
        pending = [
            fd["id"]
            for fam in load_families()
            for fd in fam["feeds"]
            if fd["id"] not in verdicts
        ][:_CAL_BATCH]
        for fid in pending:
            verify_feed(fetcher, fid)
        done = len(load_verdicts())
        total = sum(len(f["feeds"]) for f in load_families())
        return {"checked_now": len(pending), "checked_total": done, "feeds_total": total}

    from src.events.feeds import load_families, load_verdicts

    total_feeds = sum(len(f["feeds"]) for f in load_families())
    if len(load_verdicts()) < total_feeds:  # resumable; silent once complete
        _run_step("calendars_batch", _calendars)

    # 2–3. Market + index feeds: one full import each (per-feed verdicts persist
    # to import_results.jsonl via the API path's logic — here we call the core).
    for step, category in (("markets_import_all", None), ("indices_import_all", "index")):
        if _step_done(step):
            continue

        def _import(category=category):
            from src.markets.csv_feeds import import_feed
            from src.markets.feed_catalog import feeds_for_category

            ok = failed = 0
            failures = []
            for feed in feeds_for_category(category):
                try:
                    r = import_feed(
                        session,
                        url=feed.url,
                        symbol=feed.symbol,
                        fetcher=fetcher,
                        date_column=feed.date_column,
                        value_column=feed.value_column,
                        currency=feed.currency,
                        unit=feed.unit,
                        market=feed.market,
                        source=f"field-test:{feed.key}",
                    )
                    if r.status == "imported":
                        ok += 1
                    else:
                        failed += 1
                        failures.append({"key": feed.key, "status": r.status, "detail": r.detail})
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    failures.append({"key": feed.key, "status": "error", "detail": str(exc)[:200]})
            return {"imported": ok, "failed": failed, "failures": failures[:40]}

        _run_step(step, _import)

    # 4. Law tracking: one bounded pass over the tracked documents.
    if not _step_done("law_track"):
        def _law():
            from src.law.track import track_watched

            return track_watched(session, fetcher, limit_documents=5)

        _run_step("law_track", _law)

    # 5. Wiki tracking: one bounded pass over watched pages (if any).
    if not _step_done("wiki_track"):
        def _wiki():
            from src.wiki.client import WikiClient
            from src.wiki.track import track_watched

            return track_watched(session, WikiClient(), limit_pages=5)

        _run_step("wiki_track", _wiki)

    return {"log": str(_log_path()), "records": len(recent_results(2000))}
