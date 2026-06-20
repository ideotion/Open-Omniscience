"""Upstream-watch (layer 3): comparison logic + issue body, fixture-driven (no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The watch's network call is injectable; here we feed GitHub-API fixtures and assert the
pure comparison + issue-body logic. The actual HTTP + ``gh`` calls run only in the CI
freshness workflow.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, _ROOT / "scripts" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


U = _load("check_upstream_updates")
FI = _load("freshness_issue")


def test_release_is_behind_normalises_v_prefix():
    assert U.release_is_behind("v1.5.4", "v1.5.4") is False
    assert U.release_is_behind("1.5.4", "v1.5.4") is False  # v-prefix ignored
    assert U.release_is_behind("v1.5.4", "v1.6.0") is True
    assert U.release_is_behind("v1.5.4", "") is False  # no upstream tag -> not "behind"


def test_release_and_commit_parsers():
    assert U.latest_release_tag({"tag_name": "v2.0.0"}) == "v2.0.0"
    assert U.latest_release_tag({"name": "x"}) == "x"
    assert U.latest_release_tag([]) is None
    payload = [{"commit": {"committer": {"date": "2026-08-03T10:00:00Z"}}}]
    assert U.latest_commit_month(payload) == "2026-08"
    assert U.latest_commit_month([]) is None


def test_month_is_behind():
    assert U.month_is_behind("2026-06", "2026-08") is True
    assert U.month_is_behind("2026-06", "2026-06") is False
    assert U.month_is_behind("2026-06", "2026-05") is False
    assert U.month_is_behind(None, "2026-08") is False  # unbundled sentinel -> not behind


def test_check_all_flags_behind_and_current_and_failures():
    # A fake GitHub API: alpine has moved on, duckdb is current, the geo mirror is current.
    def fake_fetch(url: str):
        if "alpinejs/alpine/releases/latest" in url:
            return {"tag_name": "v3.20.0"}            # newer than pinned v3.14.1 -> behind
        if "duckdb/duckdb/releases/latest" in url:
            return {"tag_name": "v1.5.4"}             # == pinned -> current
        if "ip-location-db/commits" in url:
            return [{"commit": {"committer": {"date": "2026-06-01T00:00:00Z"}}}]  # == as_of
        raise AssertionError(f"unexpected url {url}")

    rows = U.check_all(fetch=fake_fetch)
    by_id = {r["id"]: r for r in rows}
    assert by_id["vendored-alpine"]["status"] == "behind"
    assert by_id["duckdb-crypto-extension"]["status"] == "current"
    assert by_id["ip-geo-country"]["status"] == "current"


def test_check_all_degrades_loudly_never_crashes():
    def boom(url: str):
        raise RuntimeError("rate limited")

    rows = U.check_all(fetch=boom)
    assert rows and all(r["status"] == "check-failed" for r in rows)


def test_issue_body_actionable_only_when_something_needs_refresh():
    none, body = FI.build_issue_body({"stale": [], "artifacts": []}, {"behind": [], "upstream": []})
    assert none is False

    act, body = FI.build_issue_body(
        {"stale": ["ip-geo-country"], "artifacts": [{"id": "ip-geo-country", "detail": "7 months"}]},
        {"behind": ["vendored-alpine"],
         "upstream": [{"id": "vendored-alpine", "status": "behind", "detail": "v3.20.0 vs v3.14.1"}]},
    )
    assert act is True
    assert "ip-geo-country" in body and "vendored-alpine" in body
    assert "EXTERNAL_DEPENDENCIES.md" in body  # points at the checklist
