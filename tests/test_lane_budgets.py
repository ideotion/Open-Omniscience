"""The published per-lane budgets, the growth arithmetic and the storage report.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-08 slice 4 (Q1006, Q1010, Q1011, ruled 2026-09-15). What this pins, each as its own
test:

* THE TABLE (``configs/lane_budgets.yml``) names every lane, carries ONLY the numbers
  that were ruled (Q707's 20 GB for Wikipedia) and refuses a malformed edit BY NAME --
  a budget surface that fell back to a default would be inventing a number;
* the two CODE copies of the Wikipedia number (``settings.WIKI_LANE_DEFAULT_BUDGET_GB``,
  ``tiers.DEFAULT_TOTAL_BUDGET_GB``) equal the table's row, so neither side can move
  alone;
* GROWTH is the change in the lane's own recorded size between the first and last
  reading of a 30-day window, and below seven days of span it is ABSENT with a reason --
  never a two-hour reading scaled to a month;
* the lane SIZE gauges leave a gap, never a zero, when a lane has no file;
* the REPORT keeps the operator's budget and the published one apart, degrades to named
  states, and touches no network.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from src.versioned import budget as B
from src.versioned.budget import (
    ALL_KINDS,
    GROWTH_MIN_SPAN_DAYS,
    GROWTH_WINDOW_DAYS,
    MIB,
    TABLE_PATH,
    BudgetTableError,
    gauge_metric,
    growth_from_series,
    lane_mib,
    load_table,
    setting_bounds,
    storage_report,
)

_ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3


@pytest.fixture()
def db():
    from src.database.session import SessionLocal, init_db

    init_db()
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #
def test_the_shipped_table_loads_and_names_every_lane_in_display_order():
    t = load_table()
    assert t.version == 1
    assert [r.kind for r in t.lanes] == ["press", "wiki", "law", "osm"]
    # The reference machine the answer sheet states (§11, VERIFIED): 2 cores / 3.5 GB.
    assert (t.reference_cores, t.reference_ram_gb) == (2, 3.5)
    assert t.reference_ram_bytes == int(3.5 * GIB)


def test_the_lane_list_is_the_corpus_plus_every_versioned_kind():
    """A lane added to ``src.versioned.lanes`` must get a row, or the table refuses to load."""
    from src.versioned.lanes import KINDS

    assert ("press", *KINDS) == ALL_KINDS


def test_only_the_ruled_number_is_published():
    """Q707's 20 GB is the one lane budget any ruling has set. The others stay None until
    a ruling moves one -- and that ruling changes this test in the same diff."""
    t = load_table()
    wiki = t.row("wiki")
    assert (wiki.budget_gb, wiki.ruling, wiki.reason) == (20, "Q707", None)
    for kind in ("press", "law", "osm"):
        row = t.row(kind)
        assert (row.budget_gb, row.reason, row.ruling) == (None, "not_ruled", None), kind


def test_the_wikipedia_row_equals_both_code_copies_of_the_number():
    from src.scheduler.settings import WIKI_LANE_DEFAULT_BUDGET_GB
    from src.wiki.tiers import DEFAULT_TOTAL_BUDGET_GB

    row = load_table().row("wiki")
    assert row.budget_gb == WIKI_LANE_DEFAULT_BUDGET_GB == DEFAULT_TOTAL_BUDGET_GB
    assert row.setting == "wiki_lane_budget_gb"


def test_every_setting_the_table_names_is_editable_within_the_servers_own_bounds():
    """A row naming a setting with no known bounds would render read-only in silence."""
    from src.scheduler.settings import WIKI_LANE_BUDGET_GB_MAX, WIKI_LANE_BUDGET_GB_MIN

    named = [r for r in load_table().lanes if r.setting]
    assert named, "the Wikipedia row must stay editable"
    for row in named:
        bounds = setting_bounds(row.setting)
        assert bounds is not None, f"{row.setting} has no bounds, so Storage cannot offer it"
        assert bounds[0] <= row.budget_gb <= bounds[1]
    assert setting_bounds("wiki_lane_budget_gb") == (WIKI_LANE_BUDGET_GB_MIN, WIKI_LANE_BUDGET_GB_MAX)
    assert setting_bounds(None) is None and setting_bounds("interval_minutes") is None


def _mutated(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "lane_budgets.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _set(path: list[str], value):
    def go(raw):
        node = raw
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return go


def _drop(path: list[str]):
    def go(raw):
        node = raw
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return go


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (_drop(["lanes", "law", "budget_gb"]), "budget_gb is required"),
        # An invented number: a figure beside the not-ruled token.
        (_set(["lanes", "law", "budget_gb"], 5), "carries no reason token"),
        # ...and one with the token removed but no ruling to cite.
        (lambda r: (r["lanes"]["law"].update(budget_gb=5), r["lanes"]["law"].pop("reason")), "needs the ruling"),
        (_set(["lanes", "wiki", "ruling"], "the maintainer"), "needs the ruling"),
        (_set(["lanes", "wiki", "budget_gb"], 0), "positive whole number"),
        (_set(["lanes", "wiki", "budget_gb"], True), "positive whole number"),
        (_set(["lanes", "wiki", "budget_gb"], 20.5), "positive whole number"),
        (_set(["lanes", "osm", "reason"], "too_big"), "needs a reason from"),
        (_set(["lanes", "press", "ruling"], "Q1"), "a ruling names a number"),
        (_set(["lanes", "tor"], {"budget_gb": None, "reason": "not_ruled"}), r"unknown \['tor'\]"),
        (_drop(["lanes", "osm"]), r"missing \['osm'\]"),
        (_set(["lanes", "wiki", "note"], "x"), "unknown key"),
        (_set(["lanes", "wiki", "setting"], "wiki_lane_budget"), "is not a scheduler setting"),
        # Unhashable: without the type check this was a TypeError, and a 500.
        (_set(["lanes", "wiki", "setting"], ["wiki_lane_budget_gb"]), "is not a scheduler setting"),
        (_set(["version"], 2), "table version"),
        (_set(["version"], True), "table version"),
        (_set(["reference_machine", "ram_gb"], -1), "ram_gb must be a positive"),
        (_set(["reference_machine", "ram_gb"], float("nan")), "ram_gb must be a positive"),
        (_set(["reference_machine", "ram_gb"], float("inf")), "ram_gb must be a positive"),
        (_set(["reference_machine", "cores"], 0), "positive whole number"),
        (_set(["reference_machine", "disk_gb"], 100), "exactly cores and ram_gb"),
        (_set(["extra"], 1), "unknown top-level"),
    ],
)
def test_a_malformed_table_is_refused_by_name(tmp_path, mutate, needle):
    with pytest.raises(BudgetTableError, match=needle):
        load_table(_mutated(tmp_path, mutate))


def test_an_unreadable_or_invalid_file_is_refused_by_name(tmp_path):
    with pytest.raises(BudgetTableError, match="could not be read"):
        load_table(tmp_path / "absent.yml")
    latin = tmp_path / "latin.yml"
    latin.write_bytes("version: 1  # r\xe9f\xe9rence\n".encode("latin-1"))
    with pytest.raises(BudgetTableError, match="could not be read: UnicodeDecodeError"):
        load_table(latin)
    bad = tmp_path / "bad.yml"
    bad.write_text("lanes: [unclosed", encoding="utf-8")
    with pytest.raises(BudgetTableError, match="not valid YAML"):
        load_table(bad)
    listy = tmp_path / "list.yml"
    listy.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(BudgetTableError, match="must be a mapping"):
        load_table(listy)


# --------------------------------------------------------------------------- #
# Growth -- measured from the lane's own bytes, or not shown
# --------------------------------------------------------------------------- #
def _series(*points: tuple[float, int]) -> list[dict]:
    """``(days_ago, MiB)`` pairs, oldest first, as ``metric_history`` returns them."""
    now = datetime(2026, 9, 25, 12, 0, 0)
    return [{"t": (now - timedelta(days=d)).isoformat(), "n": n} for d, n in points]


def test_no_readings_is_no_history():
    g = growth_from_series([], recording_began_at=None)
    assert g["measured"] is False and g["reason"] == "no_history" and g["samples"] == 0
    assert "delta_bytes" not in g and "per_30_days_bytes" not in g


@pytest.mark.parametrize("points", [((0, 100),), ((6.9, 100), (0, 900)), ((0.1, 100), (0, 101))])
def test_under_seven_days_of_span_is_too_short_and_carries_no_rate(points):
    g = growth_from_series(_series(*points), recording_began_at="2026-09-18T00:00:00")
    assert g["measured"] is False and g["reason"] == "too_short"
    assert "per_30_days_bytes" not in g and "delta_bytes" not in g
    assert g["min_span_days"] == GROWTH_MIN_SPAN_DAYS == 7


def test_seven_days_is_enough_and_the_rate_is_the_arithmetic_stated():
    g = growth_from_series(_series((7, 1000), (3, 1100), (0, 1140)), recording_began_at="2026-09-01T00:00:00")
    assert g["measured"] is True and g["samples"] == 3 and g["span_days"] == 7.0
    assert g["delta_bytes"] == 140 * MIB
    # First to last over the wall-clock between them, scaled to 30 days -- nothing else.
    assert g["per_30_days_bytes"] == round(140 * MIB * 30 / 7)
    assert g["window_days"] == GROWTH_WINDOW_DAYS == 30


def test_a_shrinking_lane_reports_a_negative_rate_and_a_flat_one_zero():
    down = growth_from_series(_series((10, 5000), (0, 4700)), recording_began_at=None)
    assert down["delta_bytes"] == -300 * MIB and down["per_30_days_bytes"] == -900 * MIB
    flat = growth_from_series(_series((12, 70), (0, 70)), recording_began_at=None)
    assert flat["measured"] is True and flat["delta_bytes"] == 0 and flat["per_30_days_bytes"] == 0


def test_an_absent_lane_has_no_growth_and_no_history_read(db, monkeypatch):
    import src.database.snapshots as snaps

    monkeypatch.setattr(snaps, "metric_history", lambda *a, **k: pytest.fail("read history for an absent lane"))
    g = B.lane_growth(db, "law", size_state="absent")
    assert (g["measured"], g["reason"]) == (False, "absent")


def test_a_history_read_that_fails_is_named_not_raised(db, monkeypatch):
    import src.database.snapshots as snaps

    def boom(*_a, **_k):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(snaps, "metric_history", boom)
    g = B.lane_growth(db, "press", size_state="present")
    assert (g["measured"], g["reason"]) == (False, "unreadable")


def test_growth_reads_the_lanes_own_recorded_gauge_end_to_end(db):
    """Through the real snapshot store: rows seeded in this session only (rolled back)."""
    from src.database.models import StatSnapshot

    metric = gauge_metric("press")
    db.query(StatSnapshot).filter(StatSnapshot.metric == metric).delete()
    now = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    for days, mib in ((40, 10), (20, 100), (11, 130), (1, 160)):
        db.add(StatSnapshot(metric=metric, taken_at=now - timedelta(days=days), value=mib))
    db.flush()
    g = B.lane_growth(db, "press", size_state="present")
    # The 40-day reading is outside the window: first = 20 days ago, last = 1 day ago.
    assert g["measured"] is True and g["samples"] == 3
    assert g["delta_bytes"] == 60 * MIB and g["span_days"] == 19.0
    assert g["recording_began_at"] == (now - timedelta(days=40)).isoformat()


# --------------------------------------------------------------------------- #
# The size gauges
# --------------------------------------------------------------------------- #
def test_every_lane_has_a_size_gauge_and_none_is_a_library_counter():
    from src.database.snapshots import _GAUGE_METRICS, ALL_METRICS

    for kind in ALL_KINDS:
        assert gauge_metric(kind) in _GAUGE_METRICS, kind
        # Settings -> Storage material, like wal_bytes: never on the Library's allowlist.
        assert gauge_metric(kind) not in ALL_METRICS
    with pytest.raises(ValueError, match="unknown lane"):
        gauge_metric("tor")


def test_an_absent_lane_gauge_is_a_gap_and_a_present_one_is_whole_mib(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    assert lane_mib("wiki") is None  # a GAP in the series, never a recorded zero
    lane_file = tmp_path / "wiki.db"
    with lane_file.open("wb") as fh:
        fh.truncate(5 * MIB + 123)  # sparse: the size without the disk
    (tmp_path / "wiki.db-wal").write_bytes(b"x" * 1000)
    assert lane_mib("wiki") == 5  # rounded down, sidecars included
    assert B.lane_bytes("wiki") == 5 * MIB + 123 + 1000


def test_the_hourly_recorder_writes_a_present_lane_and_skips_an_absent_one(db, monkeypatch):
    import src.database.snapshots as snaps
    from src.database.models import StatSnapshot

    sizes = {"press": 42, "wiki": 7, "law": None, "osm": None}
    monkeypatch.setattr(B, "lane_mib", lambda kind: sizes[kind])
    # A distinct hour nobody else records, so the (metric, hour) gate is ours alone.
    when = datetime(2001, 1, 1, 3, 30, tzinfo=UTC)
    out = snaps.maybe_snapshot_library_stats(db, now=when)
    rec = out.get("recorded", {})
    assert rec.get("lane_mib_press") == 42 and rec.get("lane_mib_wiki") == 7
    assert "lane_mib_law" not in rec and "lane_mib_osm" not in rec
    stored = {
        m for (m,) in db.query(StatSnapshot.metric).filter(
            StatSnapshot.taken_at == datetime(2001, 1, 1, 3, 0), StatSnapshot.metric.like("lane_mib_%")
        )
    }
    assert stored == {"lane_mib_press", "lane_mib_wiki"}


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
def _lane(rep: dict, kind: str) -> dict:
    return next(e for e in rep["lanes"] if e["kind"] == kind)


class _Settings:
    def __init__(self, gb):
        self.wiki_lane_budget_gb = gb


def test_the_report_on_a_fresh_data_folder(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(20))
    rep = storage_report(db)
    assert [e["kind"] for e in rep["lanes"]] == list(ALL_KINDS)
    wiki, law, osm = _lane(rep, "wiki"), _lane(rep, "law"), _lane(rep, "osm")
    for e in (wiki, law, osm):
        assert e["size_state"] == "absent" and e["bytes"] is None  # never 0
        assert (e["growth"]["measured"], e["growth"]["reason"]) == (False, "absent")
    assert wiki["implemented"] is True and law["implemented"] is False and osm["implemented"] is False
    assert wiki["budget"]["gb"] == 20 and wiki["budget"]["source"] == "published"
    assert wiki["budget"]["used_share"] is None and wiki["budget"]["exhausted"] is None
    assert law["budget"]["gb"] is None and law["budget"]["reason"] == "not_ruled"
    # An absent Wikipedia lane can still take its whole budget.
    assert rep["claimable_bytes"] == 20 * GIB
    assert rep["table"]["reference_machine"] == {"cores": 2, "ram_gb": 3.5, "ram_bytes": int(3.5 * GIB)}
    # The reading is shown beside the reference with NO verdict between them.
    assert not {k for k in rep if "versus" in k}
    assert isinstance(rep["disk"]["free_bytes"], int)
    assert rep["budgets_fit"] is (rep["claimable_bytes"] <= rep["disk"]["free_bytes"])


def test_a_raised_budget_is_yours_and_the_published_number_stays_beside_it(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with (tmp_path / "wiki.db").open("wb") as fh:
        fh.truncate(2 * GIB)
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(35))
    b = _lane(storage_report(db), "wiki")["budget"]
    assert (b["gb"], b["published_gb"], b["source"]) == (35, 20, "yours")
    assert b["used_share"] == 2 / 35 and b["exhausted"] is False
    assert (b["setting"], b["min_gb"], b["max_gb"]) == ("wiki_lane_budget_gb", 1, 2000)


def test_a_small_lane_is_never_rounded_into_an_empty_share(db, tmp_path, monkeypatch):
    """A fresh wiki lane (120 KiB) under the 20 GB default is a share of 0.0000057. Rounded
    to four decimals it was 0.0, and the panel drew "0% used" for a lane that holds
    something -- the exact reading the client's "<1" exists to refuse."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "wiki.db").write_bytes(b"\0" * 122_880)
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(20))
    b = _lane(storage_report(db), "wiki")["budget"]
    assert 0 < b["used_share"] < 0.01


def test_a_stored_copy_of_the_default_is_still_the_published_number(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(20))
    assert _lane(storage_report(db), "wiki")["budget"]["source"] == "published"


def test_a_full_lane_is_exhausted_by_measurement_and_budgets_are_weighed_against_the_disk(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with (tmp_path / "wiki.db").open("wb") as fh:
        fh.truncate(GIB + 1)  # sparse
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(1))
    rep = storage_report(db)
    assert _lane(rep, "wiki")["budget"]["exhausted"] is True
    assert rep["claimable_bytes"] == 0  # over budget claims nothing more, never a negative
    assert rep["budgets_fit"] is True


def test_an_unreadable_disk_makes_the_fit_unknown_never_a_fit(db, tmp_path, monkeypatch):
    """THREE STATES: fits, does not fit, unknown. An unreadable drive must not read as room."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(20))
    monkeypatch.setattr("src.config.hardware_reading.disk_bytes", lambda _p=None: (None, None))
    rep = storage_report(db)
    assert rep["disk"] == {"free_bytes": None, "total_bytes": None}
    assert rep["claimable_bytes"] == 20 * GIB and rep["budgets_fit"] is None


def test_budgets_larger_than_the_free_disk_do_not_fit(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.scheduler.settings.load_settings", lambda: _Settings(20))
    monkeypatch.setattr("src.config.hardware_reading.disk_bytes", lambda _p=None: (15 * GIB, 64 * GIB))
    rep = storage_report(db)
    assert rep["budgets_fit"] is False


def test_an_unreadable_table_is_a_named_state_and_every_size_still_renders(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(B, "TABLE_PATH", tmp_path / "gone.yml")
    rep = storage_report(db)
    assert rep["table"] is None
    assert "could not be read" in rep["table_error"]
    assert all(e["budget"]["gb"] is None and e["budget"]["reason"] is None for e in rep["lanes"])
    assert rep["claimable_bytes"] is None and rep["budgets_fit"] is None
    assert _lane(rep, "press")["size_state"] in {"present", "unmeasurable"}


def test_the_report_opens_no_socket(db, tmp_path, monkeypatch):
    """Q1011's "no network", enforced rather than asserted: every socket entry point raises."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def refuse(*_a, **_k):
        raise AssertionError("the storage report tried to open a socket")

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    rep = storage_report(db)
    assert rep["lanes"] and rep["reading"]


def test_the_endpoint_serves_the_report_and_is_wired():
    from fastapi.testclient import TestClient

    from src.api.lane_storage import router
    from src.api.main import app

    # Anchored to the router's OWN definitions and the wiring source (the recorded rule:
    # never a positive assertion against the shared app singleton's route list).
    assert "/api/storage/lanes" in {r.path for r in router.routes}
    wiring = (_ROOT / "src" / "api" / "_wiring.py").read_text(encoding="utf-8")
    assert "from src.api.lane_storage import router as lane_storage_router" in wiring
    with TestClient(app) as client:
        r = client.get("/api/storage/lanes")
        assert r.status_code == 200
        body = r.json()
        assert [e["kind"] for e in body["lanes"]] == list(ALL_KINDS)
        assert body["reading"]["when"] in {"boot", "now"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_storage_renderers_node_suite():
    """The panel's refusals run as REAL code: an unmeasured rate draws no figure, a lane
    with no ruled budget draws no number, an absent lane never reads "0 B", and the Save
    button quotes its arguments the way the XSS lesson requires."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "lane_storage_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "lane storage: all assertions passed" in proc.stdout
