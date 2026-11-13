"""Every memory verdict reads the cgroup limit the same way and says which figure it used (R302, the follow-up to #1942).

The three that read only the host's memory: the resident budget's tier (``config/memory_budget``), the whole-corpus scan floor
(``config/machine_floor``) and the memory guard's readings, both between passes (``scheduler/memguard._psutil_readings``) and
during one (``monitoring/collect_perf._vitals``). Each now goes through ``config/cgroup_memory.effective_memory``.
Measured case they all share: a 2,048 MB cgroup on a host with 15,542 MB available.
"""

from __future__ import annotations

import pytest

from src.config import cgroup_memory

MB = 1024 * 1024
_SMALL_CGROUP = {"available_mb": 1500.0, "limit_mb": 2048.0, "min_limit_mb": 2048.0, "source": "cgroup_v2", "unreadable": False}
_NO_LIMIT = {"available_mb": None, "limit_mb": None, "min_limit_mb": None, "source": None, "unreadable": False}
_UNREADABLE = {"available_mb": None, "limit_mb": None, "min_limit_mb": None, "source": None, "unreadable": True}


@pytest.fixture
def host(monkeypatch):
    """A 16 GB host with 15,542 MB available, as psutil reports it."""
    monkeypatch.setattr(cgroup_memory, "machine_memory_mb", lambda: (16384.0, 15542.0))


def _cgroup(monkeypatch, reading):
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb", lambda *a, **k: dict(reading))


# --------------------------------------------------------------------------- the one helper
def test_the_helper_takes_the_smaller_figure_and_names_it(monkeypatch, host):
    _cgroup(monkeypatch, _SMALL_CGROUP)
    got = cgroup_memory.effective_memory()
    assert got == {"total_mb": 2048.0, "total_from": "cgroup limit", "available_mb": 1500.0, "available_from": "cgroup limit"}


def test_without_a_limit_the_helper_names_the_machine(monkeypatch, host):
    _cgroup(monkeypatch, _NO_LIMIT)
    got = cgroup_memory.effective_memory()
    assert got == {"total_mb": 16384.0, "total_from": "machine", "available_mb": 15542.0, "available_from": "machine"}


def test_an_unreadable_limit_keeps_the_machine_figure_and_says_so(monkeypatch, host):
    _cgroup(monkeypatch, _UNREADABLE)
    got = cgroup_memory.effective_memory()
    assert got["total_mb"] == 16384.0 and got["available_mb"] == 15542.0
    assert got["total_from"] == got["available_from"] == "machine (a cgroup limit could not be read)"


def test_a_cgroup_that_raises_leaves_the_machine_figures(monkeypatch, host):
    def boom(*a, **k):
        raise OSError("no /proc")

    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb", boom)
    got = cgroup_memory.effective_memory()
    assert got["total_mb"] == 16384.0 and got["total_from"] == "machine"


def test_the_total_is_the_smallest_limit_at_any_level(tmp_path):
    """The tier wants the most memory the process can ever hold (the smallest limit), even when the level with the least room
    NOW is a larger one: a 1 GB child with 0.9 GB free under a 4 GB parent with 0.5 GB free."""
    G = 1024 * MB
    own = "/slice/app"
    for rel, lim, used in (("/slice", 4 * G, int(3.5 * G)), ("/slice/app", 1 * G, int(0.1 * G))):
        d = tmp_path / "cg" / rel.strip("/")
        d.mkdir(parents=True, exist_ok=True)
        (d / "memory.max").write_text(str(lim), encoding="utf-8")
        (d / "memory.current").write_text(str(used), encoding="utf-8")
        (d / "memory.stat").write_text("inactive_file 0\n", encoding="utf-8")
    (tmp_path / "cg" / "cgroup.controllers").write_text("memory\n", encoding="utf-8")
    proc = tmp_path / "proc_cgroup"
    proc.write_text(f"0::{own}\n", encoding="utf-8")
    got = cgroup_memory.cgroup_available_mb(str(tmp_path / "cg"), str(proc))
    assert got["available_mb"] == pytest.approx(512.0, abs=0.2) and got["limit_mb"] == pytest.approx(4096.0, abs=0.1)
    assert got["min_limit_mb"] == pytest.approx(1024.0, abs=0.1)


# --------------------------------------------------------------------------- 1. the resident budget
def test_the_budget_tier_is_decided_on_the_cgroup_limit(monkeypatch):
    from src.config import memory_budget as mb

    monkeypatch.setattr(mb, "total_ram_mb", lambda: 16384.0)
    _cgroup(monkeypatch, _SMALL_CGROUP)
    got = mb.resolve()
    assert got["total_ram_mb"] == 2048.0 and got["tier"] == "small"
    assert got["total_ram_from"] == "cgroup limit"
    assert "cgroup memory limit" in got["reason"]
    now = mb.reading_vs_now()["now"]
    assert now["total_ram_mb"] == 2048.0 and now["total_ram_from"] == "cgroup limit"


def test_the_budget_names_the_machine_without_a_limit(monkeypatch):
    from src.config import memory_budget as mb

    monkeypatch.setattr(mb, "total_ram_mb", lambda: 16384.0)
    _cgroup(monkeypatch, _NO_LIMIT)
    got = mb.resolve()
    assert got["total_ram_mb"] == 16384.0 and got["tier"] == "large" and got["total_ram_from"] == "machine"
    assert "cgroup" not in got["reason"]


def test_the_reindex_cache_is_sized_to_the_limit(monkeypatch):
    from src.analytics.reindex_cache import reindex_cache_mb

    monkeypatch.delenv("OO_REINDEX_CACHE_MB", raising=False)
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: 16000.0)
    _cgroup(monkeypatch, _NO_LIMIT)
    on_host = reindex_cache_mb()
    _cgroup(monkeypatch, _SMALL_CGROUP)
    assert reindex_cache_mb() < on_host


# --------------------------------------------------------------------------- 2. the scan floor
def test_the_scan_floor_judges_by_the_cgroup_and_names_it(monkeypatch, host):
    from src.config import machine_floor as MF

    _cgroup(monkeypatch, _SMALL_CGROUP)
    v = MF.machine_floor(override=False)
    assert v["total_mb"] == 2048.0 and v["available_mb"] == 1500.0
    assert v["total_from"] == v["available_from"] == "cgroup limit"
    assert v["below"] is True and v["declines"] is True  # under the 4,096 MB total floor
    assert "cgroup" in v["method"]


def test_the_scan_floor_on_the_host_alone_would_have_gone(monkeypatch, host):
    from src.config import machine_floor as MF

    _cgroup(monkeypatch, _NO_LIMIT)
    v = MF.machine_floor(override=False)
    assert v["below"] is False and v["total_from"] == "machine"


def test_a_figure_passed_in_is_named_as_given(monkeypatch, host):
    from src.config import machine_floor as MF

    _cgroup(monkeypatch, _SMALL_CGROUP)
    v = MF.machine_floor(override=False, total_mb=8192.0, available_mb=4000.0)
    assert v["total_from"] == v["available_from"] == "given"


def test_the_qualification_reader_gets_the_bounded_figure(monkeypatch, host):
    from src.config import machine_floor as MF

    _cgroup(monkeypatch, _SMALL_CGROUP)
    assert MF._mem_readings() == (2048.0, 1500.0)


# --------------------------------------------------------------------------- 3. the memory guard
def test_the_guard_between_passes_reads_the_cgroup(monkeypatch, host):
    from src.scheduler import memguard

    _cgroup(monkeypatch, _SMALL_CGROUP)
    r = memguard._psutil_readings()
    assert r["mem_avail_mb"] == 1500.0 and r["mem_total_mb"] == 2048.0
    assert r["mem_from"] == {"total": "cgroup limit", "available": "cgroup limit"}


def test_the_guard_during_a_pass_reads_the_cgroup(monkeypatch):
    psutil = pytest.importorskip("psutil")
    from src.monitoring import collect_perf

    class _VM:
        total = 16384 * MB
        available = 15542 * MB

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())
    _cgroup(monkeypatch, _SMALL_CGROUP)
    v = collect_perf._vitals()
    assert v["mem_avail_mb"] == 1500.0 and v["mem_total_mb"] == 2048.0
    assert v["mem_from"] == {"total": "cgroup limit", "available": "cgroup limit"}


def test_a_small_cgroup_trips_the_guard_a_host_reading_never_would(monkeypatch, host):
    """The point of the change, end to end: 200 MB free in the cgroup trips the 256 MB floor; the host's 15,542 MB never does."""
    from src.scheduler import memguard

    tight = dict(_SMALL_CGROUP, available_mb=200.0)
    _cgroup(monkeypatch, tight)
    g = memguard.MemoryGuard(trip_after=1, avail_floor_mb=256.0)
    assert g.poll() is True
    _cgroup(monkeypatch, _NO_LIMIT)
    g2 = memguard.MemoryGuard(trip_after=1, avail_floor_mb=256.0)
    assert g2.poll() is False
