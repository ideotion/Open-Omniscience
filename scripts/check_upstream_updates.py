#!/usr/bin/env python3
"""
Check whether UPSTREAM is newer than our pin, for registry entries we can check.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is layer 3's network-using half — it runs in CI ONLY (the freshness workflow), never
in the app. For each registry entry that declares an ``upstream_check`` it queries the
GitHub API and compares to our recorded pin:

  * ``type: release``      -> latest GitHub release tag vs the entry's ``current`` tag;
  * ``type: path_commit``  -> the month of the latest commit touching ``path`` vs our
    ``*_AS_OF`` (so a refreshed data mirror is noticed).

It DEGRADES LOUDLY but never crashes: an unreachable upstream / rate limit becomes a
``check-failed`` row, not a failed run. The comparison logic is pure + fixture-tested; only
``_fetch_json`` touches the network. The pip + GitHub-Actions pins are handled by
Dependabot, so they are intentionally not re-checked here.

Usage (CI):
  python scripts/check_upstream_updates.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.maintenance import registry as R  # noqa: E402


def _fetch_json(url: str) -> Any:
    headers = {"User-Agent": "oo-freshness/0.1", "Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - documented GitHub API
        return json.loads(r.read().decode("utf-8"))


# --- pure comparison helpers (fixture-tested; no network) -------------------- #
def _norm_tag(t: str) -> str:
    return re.sub(r"^v", "", str(t or "").strip())


def release_is_behind(current: str, latest_tag: str) -> bool:
    """True iff ``latest_tag`` is a different (newer-or-changed) release than ``current``.
    We flag any difference rather than risk a missed bump on odd version schemes."""
    return bool(latest_tag) and _norm_tag(latest_tag) != _norm_tag(current)


def latest_release_tag(payload: Any) -> str | None:
    if isinstance(payload, dict):
        return payload.get("tag_name") or payload.get("name")
    return None


def latest_commit_month(payload: Any) -> str | None:
    """YYYY-MM of the most recent commit in a GitHub commits-list payload."""
    if isinstance(payload, list) and payload:
        date = (((payload[0] or {}).get("commit") or {}).get("committer") or {}).get("date")
        m = re.match(r"^(\d{4}-\d{2})", str(date or ""))
        return m.group(1) if m else None
    return None


def month_is_behind(as_of: str | None, upstream_month: str | None) -> bool:
    """True iff the upstream file's month is strictly after our pinned ``as_of`` month."""
    if not as_of or not upstream_month:
        return False
    a = re.match(r"^(\d{4})-(\d{2})", str(as_of))
    u = re.match(r"^(\d{4})-(\d{2})", str(upstream_month))
    if not a or not u:
        return False
    return (int(u.group(1)), int(u.group(2))) > (int(a.group(1)), int(a.group(2)))


# --- orchestration ---------------------------------------------------------- #
def check_all(fetch: Callable[[str], Any] = _fetch_json) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for a in R.load_registry():
        uc = a.get("upstream_check")
        if not uc:
            continue
        gh, typ = uc.get("github"), uc.get("type")
        rec: dict[str, Any] = {"id": a["id"], "status": "current", "detail": ""}
        try:
            if typ == "release":
                payload = fetch(f"https://api.github.com/repos/{gh}/releases/latest")
                latest = latest_release_tag(payload)
                cur = uc.get("current", "")
                if latest is None:
                    rec.update(status="check-failed", detail="no release tag in response")
                elif release_is_behind(cur, latest):
                    rec.update(status="behind", detail=f"upstream {latest} vs pinned {cur}")
                else:
                    rec["detail"] = f"up to date ({latest})"
            elif typ == "path_commit":
                path = uc.get("path", "")
                payload = fetch(
                    f"https://api.github.com/repos/{gh}/commits?path={path}&per_page=1"
                )
                up_month = latest_commit_month(payload)
                pin = a.get("pin") or {}
                as_of = R.read_const(pin.get("file", ""), pin.get("const", "")) if pin else None
                if up_month is None:
                    rec.update(status="check-failed", detail="no commit date in response")
                elif month_is_behind(as_of, up_month):
                    rec.update(status="behind", detail=f"upstream {up_month} vs pinned {as_of}")
                else:
                    rec["detail"] = f"up to date ({up_month})"
            else:
                rec.update(status="check-failed", detail=f"unknown upstream_check type {typ!r}")
        except Exception as e:  # noqa: BLE001 - never crash the watch on a flaky upstream
            rec.update(status="check-failed", detail=f"{type(e).__name__}: {str(e)[:120]}")
        rows.append(rec)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = check_all()
    behind = [r["id"] for r in rows if r["status"] == "behind"]
    if args.json:
        print(json.dumps({"upstream": rows, "behind": behind}, indent=2))
    else:
        for r in rows:
            print(f"  {r['status']:12} {r['id']:26} {r['detail']}")
        print(f"\n  behind upstream: {', '.join(behind) if behind else 'none'}")
    return 1 if behind else 0


if __name__ == "__main__":
    raise SystemExit(main())
