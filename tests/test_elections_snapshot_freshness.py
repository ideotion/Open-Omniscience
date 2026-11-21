"""Docket row 258: the Wikidata election snapshot states its age, and an OLD one says so.

``configs/elections_snapshot.json`` is written by an operator's networked run and then only read.
Brief S06-04 S1 asks for it as a dated artifact with a registry entry and a freshness rule; before
this row the app read a year-old snapshot exactly like a fresh one, and an election called since
its date (a snap vote above all, V1-3) was silently absent. Now ``with_snapshot`` carries
``age_days`` and ``stale``, the Agenda and the coverage report say it, and the registry carries the
same window.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from src.civic.calendar_report import SNAPSHOT_PATH, SNAPSHOT_STALE_DAYS, with_snapshot

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 21)


def _snap(tmp_path, as_of: str):
    p = tmp_path / "snap.json"
    p.write_text(json.dumps({"as_of": as_of, "rows": []}), encoding="utf-8")
    return p


@pytest.mark.parametrize(
    ("days", "stale"),
    [(0, False), (10, False), (SNAPSHOT_STALE_DAYS, False), (SNAPSHOT_STALE_DAYS + 1, True), (400, True)],
)
def test_a_snapshot_carries_its_age_and_is_stale_only_past_the_window(tmp_path, days, stale):
    as_of = (TODAY - timedelta(days=days)).isoformat()
    _, info = with_snapshot([], TODAY, _snap(tmp_path, as_of))
    assert info["state"] == "present"
    assert info["age_days"] == days
    assert info["stale_after_days"] == SNAPSHOT_STALE_DAYS
    assert info["stale"] is stale


def test_a_snapshot_dated_after_today_is_never_read_as_fresh(tmp_path):
    _, info = with_snapshot([], TODAY, _snap(tmp_path, (TODAY + timedelta(days=3)).isoformat()))
    assert info["age_days"] is None and info["stale"] is True


def test_an_absent_snapshot_is_absent_not_stale(tmp_path):
    _, info = with_snapshot([], TODAY, tmp_path / "absent.json")
    assert info == {"state": "absent"}


def test_the_registry_carries_the_snapshot_with_the_same_window():
    reg = yaml.safe_load((ROOT / "configs" / "external_artifacts.yml").read_text(encoding="utf-8"))
    entries = reg["artifacts"] if isinstance(reg, dict) else reg
    entry = next(a for a in entries if a["id"] == "wikidata-elections-snapshot")
    pin = entry["pin"]
    assert ROOT / pin["path"] == SNAPSHOT_PATH, "the registry watches the file the app reads"
    assert pin["vintage_key"] == "as_of" and pin["optional"] is True
    assert entry["freshness"] == {"max_age_days": SNAPSHOT_STALE_DAYS}
    assert "-o configs/elections_snapshot.json" in entry["refresh"]


@pytest.mark.parametrize(
    ("as_of", "today"),
    [
        ("2026-08-01", date(2026, 11, 30)),  # 121 days: a month count still read "3/3 months"
        ("2026-09-01", date(2026, 11, 30)),  # 90 days: not stale for either
        ("2026-12-20", date(2026, 11, 21)),  # after today: stale for both
        ("2026-11-21", date(2026, 11, 21)),
    ],
)
def test_the_registry_and_the_app_give_one_verdict(tmp_path, monkeypatch, as_of, today):
    """Not two constants compared: the registry's own evaluate() on the same file and day."""
    import src.maintenance.registry as R

    reg = yaml.safe_load((ROOT / "configs" / "external_artifacts.yml").read_text(encoding="utf-8"))
    entries = reg["artifacts"] if isinstance(reg, dict) else reg
    entry = dict(next(a for a in entries if a["id"] == "wikidata-elections-snapshot"))
    path = _snap(tmp_path, as_of)
    entry["pin"] = {**entry["pin"], "path": str(path)}  # an absolute path replaces the repo root on join
    monkeypatch.setattr(R, "load_registry", lambda *a, **k: [entry])
    (row,) = R.evaluate(today=today)
    _, info = with_snapshot([], today, path)
    assert (row["status"] == "stale") is info["stale"], (row, info)


def test_the_coverage_report_says_a_stale_snapshot(tmp_path, monkeypatch):
    import src.civic.calendar_report as cr
    from scripts.elections_coverage_report import main

    monkeypatch.setattr(cr, "SNAPSHOT_PATH", _snap(tmp_path, "2026-01-02"))
    out = tmp_path / "r.md"
    assert main(["-o", str(out), "--today", "2026-11-21"]) == 0
    text = out.read_text(encoding="utf-8")
    assert "- Snapshot STALE: 323 days old, past the 90-day limit" in text


_NODE = r"""
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const src = fs.readFileSync(process.argv[1], "utf8");
const a = src.indexOf("function agSnapshotStale("), b = src.indexOf("function agNavToday()");
const ctx = { ooIsoDate: (s) => s };
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + "\nthis.f = agSnapshotStale;", ctx);
const T = (s) => s, TF = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => String(v[k]));
assert.strictEqual(ctx.f({ state: "present", stale: false, age_days: 5 }, T, TF), "");
assert.strictEqual(ctx.f({ state: "absent" }, T, TF), "");
assert.strictEqual(ctx.f(null, T, TF), "");
const old = ctx.f({ state: "present", stale: true, age_days: 120, stale_after_days: 90, as_of: "2026-07-24" }, T, TF);
assert.ok(old.includes("120 days old") && old.includes("90-day limit") && old.includes("since 2026-07-24"), old);
assert.ok(ctx.f({ state: "present", stale: true, age_days: null }, T, TF).includes("dated after today"));
console.log("ok");
"""


def test_the_agenda_draws_the_age_in_the_caveat_colour():
    from tests.js_source_helper import function_body

    js = (ROOT / "src" / "static" / "app-agenda.js").read_text(encoding="utf-8")
    assert "agSnapshotStale(floor.snapshot" in js
    line = next(ln for ln in js.splitlines() if "${esc(agSnapshotStale(" in ln)
    assert "color:var(--caveat)" in line, "the age is a caveat, drawn visibly"
    body = function_body(js, "agSnapshotStale")
    keys = [
        "The Wikidata election snapshot is dated after today, so its age cannot be read: elections called recently"
        " may be missing. Run the snapshot again.",
        "The Wikidata election snapshot is {days} days old, past the {limit}-day limit: elections called since {date},"
        " snap elections above all, are not in it. Run the snapshot again.",
    ]
    for k in keys:
        assert k in body
        for loc in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
            tr = json.loads(loc.read_text(encoding="utf-8")).get(k)
            assert tr, (loc.name, k)
            for ph in ("{days}", "{limit}", "{date}"):
                assert (ph in tr) == (ph in k), (loc.name, ph)
    proc = subprocess.run(["node", "-e", _NODE, str(ROOT / "src" / "static" / "app-agenda.js")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
