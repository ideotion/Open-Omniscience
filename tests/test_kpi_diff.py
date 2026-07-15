"""
The KPI differ (R2, scripts/kpi_diff.py) — hand-computed fixture deltas.

Pins: classification by declared direction (up/down improved/regressed, exact by verdict),
not-measurable / not-comparable honesty, no blended verdict, exit 0 for a well-formed diff and
a LOUD exit 2 on a schema-mismatched input. Stdlib-only (imported from the script file, the
analyze_keyword_log pattern — runs without the app installed).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _mod():
    path = _ROOT / "scripts" / "kpi_diff.py"
    spec = importlib.util.spec_from_file_location("kpi_diff", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kd = _mod()


def _m(mid, value, direction, verdict="green"):
    return {"id": mid, "name": mid, "value": value, "direction": direction, "verdict": verdict}


def _snap(metrics):
    return {"schema": "oo-kpi-1", "generated_at": "2026-07-14T00:00:00+00:00", "metrics": metrics}


def test_classify_down_metric_improvement():
    # a "down" metric (e.g. p95) getting smaller = improved.
    assert kd.classify(_m("K2", 600.0, "down"), _m("K2", 400.0, "down")) == "improved"
    assert kd.classify(_m("K2", 400.0, "down"), _m("K2", 600.0, "down")) == "regressed"


def test_classify_up_metric_regression():
    assert kd.classify(_m("K6", 40.0, "up"), _m("K6", 30.0, "up")) == "regressed"
    assert kd.classify(_m("K6", 40.0, "up"), _m("K6", 55.0, "up")) == "improved"


def test_classify_exact_uses_verdict_and_equal_is_unchanged():
    assert kd.classify(_m("K11", 100.0, "exact"), _m("K11", 100.0, "exact")) == "unchanged"
    # verdict flip on an exact metric:
    assert kd.classify(_m("K11", 98.0, "exact", "red"), _m("K11", 100.0, "exact", "green")) == "improved"
    assert kd.classify(_m("K11", 100.0, "exact", "green"), _m("K11", 98.0, "exact", "red")) == "regressed"


def test_classify_not_measurable_on_either_side():
    assert kd.classify(_m("K7", None, "up"), _m("K7", 50.0, "up")) == "not-measurable"
    assert kd.classify(_m("K7", 50.0, "up"), _m("K7", None, "up")) == "not-measurable"


def test_classify_missing_metric_is_not_comparable():
    assert kd.classify(None, _m("K13", 1, "exact")) == "not-comparable"
    assert kd.classify(_m("K13", 1, "exact"), None) == "not-comparable"


def test_diff_snapshots_counts_and_no_score_key():
    old = _snap([_m("K2", 600.0, "down"), _m("K6", 40.0, "up"), _m("K7", None, "up")])
    new = _snap([_m("K2", 400.0, "down"), _m("K6", 30.0, "up"), _m("K9", 1, "up")])
    r = kd.diff_snapshots(old, new)
    by = {row["id"]: row["classification"] for row in r["metrics"]}
    assert by["K2"] == "improved" and by["K6"] == "regressed"
    assert by["K7"] == "not-comparable"  # present old, absent new
    assert by["K9"] == "not-comparable"  # absent old, present new
    assert r["counts"]["improved"] == 1 and r["counts"]["regressed"] == 1
    # no blended score anywhere in the report keys
    for row in r["metrics"]:
        for k in row:
            assert not any(b in k.lower() for b in ("score", "ranking", "rating", "grade"))


def test_load_rejects_wrong_schema_loud(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else", "metrics": []}), encoding="utf-8")
    with pytest.raises(kd.KpiDiffError):
        kd.load_snapshot(str(bad))


def test_main_exit_codes(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(_snap([_m("K2", 600.0, "down")])), encoding="utf-8")
    b.write_text(json.dumps(_snap([_m("K2", 400.0, "down")])), encoding="utf-8")
    assert kd.main([str(a), str(b)]) == 0  # a regression/improvement never gates
    assert kd.main([str(a), str(b), "--json"]) == 0
    out = capsys.readouterr().out
    assert '"classification": "improved"' in out
    # a schema-mismatched input fails LOUD (exit 2)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "nope", "metrics": []}), encoding="utf-8")
    assert kd.main([str(a), str(bad)]) == 2
