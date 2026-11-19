"""The street view's frame budget (S07-02 S3, street half; row 187 item 5): the synthetic grid, the record, and the diagnostics slot.

The browser run itself is ``scripts/osm_street_frame_budget.py`` (measured in Chromium; its sandbox figure is in the PR and the shipped
row). These pin what a run's figures stand on: a grid exactly at the server's caps, a record read back without a zero for an unmeasured
frame, and a script that still finds the app's own drawing function.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.osm import diagnostics as D
from src.osm import frame_budget as fb
from src.osm import view as V

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def record_path(tmp_path, monkeypatch):
    p = tmp_path / fb.RECORD_NAME
    monkeypatch.setattr(fb, "_path", lambda: p)
    return p


def _script():
    spec = importlib.util.spec_from_file_location("osm_street_frame_budget", ROOT / "scripts" / "osm_street_frame_budget.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(**over):
    res = {
        "label": "sandbox",
        "caps": {"roads": 8000, "vertices": 60000, "labels": 60, "labels_placed": 60},
        "canvas": {"w": 1280, "h": 800, "dpr": 1},
        "frames": 120, "warmup": 10,
        "draw_ms": {"n": 120, "p50": 94.8, "p95": 121.4, "max": 126.7},
        "frame_ms": {"n": 120, "p50": 100.0, "p95": 116.7, "max": 133.3},
        "browser": "Chromium 153.0.8010.12 (headless)",
        "machine": {"os": "Linux", "arch": "x86_64", "cpus": 4, "memory_gb": 15.7},
    }
    res.update(over)
    return res


# -- the grid ------------------------------------------------------------------------------------------------------------------------ #

def test_the_grid_is_exactly_at_the_servers_caps():
    g = fb.synthetic_grid(V.POINTS_PER_VIEW, V.VERTICES_PER_VIEW, 1280, 800)
    assert len(g) == 8000 == V.POINTS_PER_VIEW
    assert sum(len(r["c"]) for r in g) == 60000 == V.VERTICES_PER_VIEW
    assert all(len(r["c"]) >= 2 for r in g)


def test_the_grid_holds_every_street_class_most_of_them_minor():
    g = fb.synthetic_grid(8000, 60000, 1280, 800)
    by = [sum(1 for r in g if r["k"] == k) for k in range(len(V.STREET_CLASSES))]
    assert len(fb.CLASS_SHARE) == len(V.STREET_CLASSES)
    assert all(n > 0 for n in by)
    assert max(range(len(by)), key=by.__getitem__) == 5  # minor streets, the commonest class
    assert sum(by) == 8000


def test_the_grid_is_deterministic_and_inside_the_canvas():
    a = fb.synthetic_grid(8000, 60000, 1280, 800)
    assert a == fb.synthetic_grid(8000, 60000, 1280, 800)
    xs = [x for r in a for x, _ in r["c"]]
    ys = [y for r in a for _, y in r["c"]]
    # the wobble is 1.5 px at most
    assert min(xs) >= -1.5 and max(xs) <= 1281.5 and min(ys) >= -1.5 and max(ys) <= 801.5


def test_the_major_roads_have_a_straight_run_long_enough_for_a_label():
    """Without one no label is ever placed, and the label path (measureText, the overlap test) would cost nothing in the figure."""
    g = fb.synthetic_grid(8000, 60000, 1280, 800)
    major = [r for r in g if r["k"] <= 4]
    longest = [max(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(r["c"], r["c"][1:], strict=False)) for r in major]
    assert sum(1 for x in longest if x >= 80) >= fb.CLASS_SHARE[4] * 8000


def test_a_road_with_fewer_than_two_vertices_is_refused():
    with pytest.raises(ValueError):
        fb.synthetic_grid(10, 19, 100, 100)


# -- the summary --------------------------------------------------------------------------------------------------------------------- #

def test_nothing_measured_is_none_never_zero():
    assert fb.summarise([]) is None
    assert fb.summarise([None, float("nan"), -1]) is None


def test_the_quantiles_are_nearest_rank():
    got = fb.summarise([float(i) for i in range(1, 101)])
    assert got == {"n": 100, "p50": 50.0, "p95": 95.0, "max": 100.0}
    assert fb.summarise([7.0]) == {"n": 1, "p50": 7.0, "p95": 7.0, "max": 7.0}


# -- the record and the slot --------------------------------------------------------------------------------------------------------- #

def test_no_record_reads_not_measured_with_its_reason(record_path):
    got = fb.member_slot()
    assert got == {"state": "not measured", "reason": fb.NOT_MEASURED_REASON}
    assert "draw_ms" not in got and "p50" not in json.dumps(got)


def test_a_recorded_run_reads_back(record_path):
    assert fb.record(_run()) is not None
    got = fb.member_slot()
    assert got["state"] == "measured" and got["label"] == "sandbox"
    assert got["draw_ms"] == {"n": 120, "p50": 94.8, "p95": 121.4, "max": 126.7}
    assert got["frame_ms"]["p95"] == 116.7
    assert got["caps"] == {"roads": 8000, "vertices": 60000, "labels": 60}
    assert got["canvas"] == {"w": 1280, "h": 800, "dpr": 1}
    assert got["machine"] == {"os": "Linux", "arch": "x86_64", "cpus": 4, "memory_gb": 15.7}
    assert got["measured_at"] and "unmeasured" not in got


def test_a_timing_the_run_lacks_is_named_not_zero(record_path):
    fb.record(_run(frame_ms=None))
    got = fb.member_slot()
    assert got["state"] == "measured" and got["frame_ms"] is None
    assert got["unmeasured"] == {"frame_ms": "this run did not record it"}


def test_a_record_with_no_timing_is_unreadable_not_measured(record_path):
    fb.record(_run(draw_ms=None, frame_ms=None))
    assert fb.member_slot()["state"] == "unreadable"


@pytest.mark.parametrize("text", ["{not json", json.dumps([1, 2]), json.dumps({"schema": "other/1", "draw_ms": {"n": 1}})])
def test_a_broken_or_foreign_file_is_unreadable(record_path, text):
    record_path.write_text(text, encoding="utf-8")
    got = fb.member_slot()
    assert got["state"] == "unreadable" and got["reason"]


def test_a_hand_edited_record_passes_no_free_text_and_no_wrong_kinds(record_path):
    fb.record(_run())
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    rec["label"] = "x" * 500
    rec["browser"] = "y" * 500
    rec["machine"] = {"os": "z" * 500, "arch": 3, "cpus": "four", "memory_gb": True, "hostname": "secret-host"}
    rec["draw_ms"]["p50"] = "fast"
    rec["extra"] = "/home/someone/path"
    record_path.write_text(json.dumps(rec), encoding="utf-8")
    got = fb.member_slot()
    text = json.dumps(got)
    assert "secret-host" not in text and "/home/someone" not in text
    assert len(got["label"]) == fb.LABEL_MAX and len(got["browser"]) == 60 and len(got["machine"]["os"]) == 20
    assert got["machine"]["arch"] is None and got["machine"]["cpus"] is None and got["machine"]["memory_gb"] is None
    assert got["draw_ms"] is None and got["unmeasured"] == {"draw_ms": "this run did not record it"}


def test_the_slot_stays_small_at_its_widest(record_path):
    """It sits in R421's 20,000 B member beside the countries; every free field is clipped, so its widest is bounded."""
    big = {"n": 10**9, "p50": 1e12, "p95": 1e12, "max": 1e12}
    fb.record(_run(label="L" * 500, browser="B" * 500, draw_ms=big, frame_ms=big,
                   machine={"os": "O" * 99, "arch": "A" * 99, "cpus": 10**6, "memory_gb": 1e9}))
    assert len(json.dumps(fb.member_slot(), separators=(",", ":")).encode()) < 1000


def test_a_failed_write_records_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "_path", lambda: tmp_path / "no-such-dir" / "deeper" / fb.RECORD_NAME)
    assert fb.record(_run()) is None


# -- the diagnostics member ---------------------------------------------------------------------------------------------------------- #

def test_the_member_carries_the_slot_even_without_a_lane(record_path, monkeypatch):
    from src.versioned import store

    monkeypatch.setattr(store, "lane_exists", lambda name: False)
    got = D.diagnostics_member()
    assert got["lane"] == "absent" and got["street_view"]["state"] == "not measured"
    fb.record(_run())
    assert D.diagnostics_member()["street_view"]["draw_ms"]["p50"] == 94.8


def test_a_slot_that_raises_does_not_break_the_member(record_path, monkeypatch):
    from src.versioned import store

    monkeypatch.setattr(store, "lane_exists", lambda name: False)
    monkeypatch.setattr(fb, "member_slot", lambda: 1 / 0)
    got = D.diagnostics_member()
    assert got["lane"] == "absent" and got["street_view"] == {
        "state": "unreadable", "reason": "the frame budget record could not be read", "error": "ZeroDivisionError"}


# -- the script ---------------------------------------------------------------------------------------------------------------------- #

def test_the_script_finds_the_apps_own_drawing_function():
    src = _script().drawing_source()
    assert src.startswith("const _OO_OSM_STREET_STYLE")
    assert "const _OO_OSM_STREET_LABELS" in src and "function _ooOsmDrawStreets(" in src
    assert src.rstrip().endswith("}") and src.count("{") == src.count("}")


def test_the_script_refuses_when_the_function_is_gone(monkeypatch, tmp_path):
    mod = _script()
    fake = tmp_path / "app-map.js"
    fake.write_text("const x = 1;\n", encoding="utf-8")
    monkeypatch.setattr(mod, "APP_MAP", fake)
    with pytest.raises(LookupError):
        mod.drawing_source()


def test_the_script_without_a_browser_client_is_a_named_refusal(monkeypatch, capsys):
    mod = _script()

    def boom(**_kw):
        raise RuntimeError("the Playwright client is not installed (the [uiwalk] extra)")

    monkeypatch.setattr(mod, "measure", boom)
    assert mod.main(["--label", "x"]) == 2
    assert "refused: the Playwright client is not installed" in capsys.readouterr().err


def test_a_label_carries_no_path_or_address(record_path):
    fb.record(_run(label="/home/me/vm: http://10.0.0.1", browser="Chromium/1 (x)"))
    got = fb.member_slot()
    text = json.dumps(got)
    assert "/" not in text and ":" not in got["label"] and ":" not in got["browser"]
    assert got["label"].startswith("-home-me-vm") and fb.clean_label("") == "unlabelled"


def test_a_time_the_record_did_not_write_is_not_shown(record_path):
    fb.record(_run())
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    assert fb._ISO.fullmatch(rec["measured_at"])
    rec["measured_at"] = "see /etc/passwd"
    record_path.write_text(json.dumps(rec), encoding="utf-8")
    assert fb.member_slot()["measured_at"] is None
