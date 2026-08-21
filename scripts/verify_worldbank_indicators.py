#!/usr/bin/env python3
"""Verify every curated World Bank indicator code against the live API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 36 codes in ``src/stats/indicators.INDICATOR_CATALOG`` were
SEARCH-VERIFIED and never fetched, and a wrong code fails SILENTLY: the app shows
"no data", which is indistinguishable from a country that genuinely does not report
the series. Two networked chat sessions (2026-08-07, 2026-08-13) failed to close
this -- the second was BLOCKED from constructing per-indicator URLs at all, and,
worse, silently served a different URL than the one requested and reported it as
the answer. A third chat re-run is the one route already known not to work.

So this is the route that does work: a machine with plain outbound HTTPS to
``api.worldbank.org`` runs ONE command and the whole catalog is checked. It reads
the codes from the catalog itself rather than a pasted list, so it cannot drift
from what the app actually ships.

THREE THINGS IT DOES THAT A HAND PASS KEEPS GETTING WRONG:

1. **It compares the URL it was SERVED against the URL it REQUESTED** and refuses
   the ``fetched`` tier when they differ (verdict ``UNVERIFIED-REWRITTEN``). That is
   the 2026-08-13 failure made structurally impossible rather than merely warned
   about: a silently-substituted response is the one failure that arrives wearing
   the strongest tier.

2. **It separates "the code is wrong" from "this country has no data for it."**
   The API rejects an unknown code with a ``message`` block (verdict ``DEAD-INVALID``
   -- the code is wrong), while a VALID code with nothing for that country returns a
   normal page header with ``total: 0`` (verdict ``EMPTY`` -- the code is fine, the
   country is not reporting). Collapsing those two condemns a working code or passes
   a broken one, and both reach a reader as a published figure. ``EMPTY`` is a prompt
   to re-run against another country (``--country WLD``), never a verdict on the code.

3. **It compares the API's own indicator name against our catalog LABEL** and flags a
   divergence. This is the ``EN.ATM.CO2E.PC`` case the catalog already carries a
   warning about: a code that still RESOLVES while the series behind it has been
   superseded reads exactly like a country that stopped reporting.

It writes a JSON report and prints a table. It CHANGES NOTHING -- updating the
catalog from its findings is a reviewed edit a human makes afterwards.

Usage:
    python scripts/verify_worldbank_indicators.py
    python scripts/verify_worldbank_indicators.py --country WLD --out report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stats.indicators import INDICATOR_CATALOG  # noqa: E402

_UA = "OpenOmniscience-IndicatorVerify/0.3 (+https://github.com/ideotion/open-omniscience)"
_BASE = "https://api.worldbank.org/v2"

#: Verdicts. Only OK and EMPTY mean the CODE is good; the rest are all "do not
#: promote this row to `fetched`", each for a different and stated reason.
OK = "OK"
EMPTY = "EMPTY"
DEAD_INVALID = "DEAD-INVALID"
REWRITTEN = "UNVERIFIED-REWRITTEN"
ERROR = "ERROR"


def indicator_url(code: str, country: str = "FRA", per_page: int = 5) -> str:
    """The per-indicator URL. Quoted, so a malformed code cannot smuggle a query."""
    c = urllib.parse.quote(country.strip(), safe="")
    i = urllib.parse.quote(code.strip(), safe=".")
    return f"{_BASE}/country/{c}/indicator/{i}?format=json&per_page={int(per_page)}"


def same_endpoint(requested: str, served: str) -> bool:
    """Did we get the URL we asked for?

    Compared on scheme+host+path+SORTED query, so a reordered query string is not a
    false alarm while a changed path, a dropped ``page`` or a different indicator is
    caught. An empty ``served`` means the fetcher could not report one, which is NOT
    evidence of agreement -- the caller treats it as unverifiable.
    """
    if not served:
        return False
    a, b = urllib.parse.urlsplit(requested), urllib.parse.urlsplit(served)
    if (a.scheme, a.netloc, a.path) != (b.scheme, b.netloc, b.path):
        return False
    return sorted(urllib.parse.parse_qsl(a.query)) == sorted(urllib.parse.parse_qsl(b.query))


def classify(payload: object) -> tuple[str, str | None, int, str | None]:
    """``(verdict, official_name, rows, note)`` for one decoded response.

    Pure, so the interesting cases are testable without a network. The World Bank
    answers an unknown indicator with ``[{"message": [...]}]`` and a known one with
    ``[page_meta, rows_or_null]``; anything else is reported as an unrecognised shape
    rather than guessed at.
    """
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        head = payload[0]
        if "message" in head:
            msgs = head.get("message") or []
            first = msgs[0] if msgs and isinstance(msgs[0], dict) else {}
            detail = first.get("value") or first.get("key") or "rejected by the API"
            return (DEAD_INVALID, None, 0, str(detail))
        if "total" in head or "page" in head:
            rows = payload[1] if len(payload) > 1 else None
            if not isinstance(rows, list) or not rows:
                total = head.get("total")
                return (EMPTY, None, 0,
                        f"the code is valid but this area reported nothing (total={total})")
            name = None
            for r in rows:
                ind = r.get("indicator") if isinstance(r, dict) else None
                if isinstance(ind, dict) and ind.get("value"):
                    name = str(ind["value"])
                    break
            return (OK, name, len(rows), None)
    return (ERROR, None, 0, f"unrecognised response shape: {type(payload).__name__}")


def fetch(url: str, getter: Callable[[str], tuple[bytes, str]] | None = None) -> tuple[object, str]:
    """``(decoded_payload, served_url)``. ``getter`` is injectable so tests never
    touch the network. The served URL is returned SEPARATELY and is load-bearing:
    the caller refuses the row if it does not match what it asked for."""
    if getter is not None:
        raw, served = getter(url)
        return (json.loads(raw), served)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - documented World Bank API
        return (json.loads(r.read()), r.geturl())


def check_one(entry: dict, country: str, per_page: int, getter=None) -> dict:
    """One catalog entry -> one report row. Never raises: a transport failure is a
    reported ERROR, because one dead code must not abandon the other 35."""
    code = entry["id"]
    url = indicator_url(code, country, per_page)
    row: dict = {
        "code": code,
        "catalog_label": entry.get("label"),
        "requested_url": url,
        "served_url": None,
        "verdict": ERROR,
        "official_name": None,
        "rows": 0,
        "label_matches": None,
        "note": None,
    }
    try:
        payload, served = fetch(url, getter)
    except urllib.error.HTTPError as exc:
        row["note"] = f"HTTP {exc.code} {exc.reason}"
        return row
    except Exception as exc:  # transport, TLS, decode - all reported, never fatal
        row["note"] = f"{type(exc).__name__}: {exc}"
        return row

    row["served_url"] = served
    if not same_endpoint(url, served):
        # Rule 5. A response to a DIFFERENT question cannot verify this code, and the
        # tier it would otherwise wear is the strongest one we have.
        row["verdict"] = REWRITTEN
        row["note"] = "the fetcher was served a different URL than requested"
        return row

    verdict, name, rows, note = classify(payload)
    row.update(verdict=verdict, official_name=name, rows=rows, note=note)
    if name and entry.get("label"):
        # Whitespace/case only -- anything more is for a human to read, not to auto-fix.
        row["label_matches"] = name.strip().casefold() == str(entry["label"]).strip().casefold()
    return row


def run(country: str = "FRA", per_page: int = 5, sleep: float = 0.3,
        getter=None, log=None) -> dict:
    """Check every catalog code. One row per code, in catalog order.

    ``sleep`` is politeness between live calls and is skipped entirely when a
    ``getter`` is injected, so tests do not pay for it.
    """
    results: list[dict] = []
    for i, entry in enumerate(INDICATOR_CATALOG):
        if i and sleep and getter is None:
            time.sleep(sleep)
        row = check_one(entry, country, per_page, getter)
        if log:
            log(row)
        results.append(row)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "requested_country": country,
        "catalog_source": "src/stats/indicators.py",
        "catalog_count": len(INDICATOR_CATALOG),
        "summary": counts,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--country", default="FRA", help="area to probe (default FRA; try WLD)")
    p.add_argument("--per-page", type=int, default=5)
    p.add_argument("--sleep", type=float, default=0.3, help="politeness pause between calls")
    p.add_argument("--out", type=Path, default=Path("worldbank-indicator-verification.json"))
    args = p.parse_args(argv)

    print(f"Checking {len(INDICATOR_CATALOG)} catalog codes against {args.country} ...")
    report = run(args.country, args.per_page, args.sleep)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for r in report["results"]:
        flag = "" if r["label_matches"] in (True, None) else "  [LABEL DIFFERS]"
        detail = r["official_name"] or r["note"] or ""
        if r["verdict"] == REWRITTEN:
            # The one verdict whose whole point is WHICH other question got answered.
            detail = f"{detail} -> served {r['served_url']}"
        print(f"  {r['verdict']:<22} {r['code']:<24} {detail}{flag}")
    print(f"\n{report['summary']}\nreport -> {args.out}")

    # A non-zero exit only for codes that are actually WRONG or unverifiable. EMPTY is
    # not a failure of the code: re-run with --country WLD before touching the catalog.
    bad = sum(report["summary"].get(v, 0) for v in (DEAD_INVALID, REWRITTEN, ERROR))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
