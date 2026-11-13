"""R302: the rollup affordability verdict reads a cgroup memory limit, not only the machine's figure.

Measured 2026-10-27 (keyword lane): inside a 2,048 MB cgroup psutil reported 15,542 MB available and a build needing 3,904 MB was
started. These tests fake the cgroup files (v1, v2, a nested limit, ``max``, 2**63, unreadable) and show the verdict now declines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analytics import rollup_serve
from src.config import cgroup_memory

MB = 1024 * 1024


def _v2(tmp_path: Path, *, own: str = "/app", levels: dict[str, dict[str, str]]) -> tuple[str, str]:
    root = tmp_path / "cg"
    (root).mkdir()
    (root / "cgroup.controllers").write_text("memory\n")
    for rel, files in levels.items():
        d = root / rel.strip("/") if rel.strip("/") else root
        d.mkdir(parents=True, exist_ok=True)
        for name, body in files.items():
            (d / name).write_text(body)
    proc = tmp_path / "proc_cgroup"
    proc.write_text(f"0::{own}\n")
    return str(root), str(proc)


def _v1(tmp_path: Path, *, own: str = "/oo", files: dict[str, str]) -> tuple[str, str]:
    root = tmp_path / "cg"
    d = root / "memory" / own.strip("/")
    d.mkdir(parents=True)
    for name, body in files.items():
        (d / name).write_text(body)
    proc = tmp_path / "proc_cgroup"
    proc.write_text(f"4:memory:{own}\n")
    return str(root), str(proc)


def test_v2_limit_less_usage_plus_reclaimable_cache(tmp_path):
    root, proc = _v2(tmp_path, levels={"/app": {
        "memory.max": str(2048 * MB), "memory.current": str(1000 * MB), "memory.stat": f"anon 1\ninactive_file {200 * MB}\n"}})
    got = cgroup_memory.cgroup_available_mb(root, proc)
    assert got == {"available_mb": 1248.0, "limit_mb": 2048.0, "source": "cgroup_v2", "unreadable": False}


def test_v2_nested_limit_the_tightest_ancestor_wins(tmp_path):
    root, proc = _v2(tmp_path, own="/a/b", levels={
        "/a": {"memory.max": str(512 * MB), "memory.current": str(100 * MB)},
        "/a/b": {"memory.max": "max", "memory.current": str(90 * MB)},
    })
    got = cgroup_memory.cgroup_available_mb(root, proc)
    assert got["available_mb"] == 412.0 and got["limit_mb"] == 512.0  # no memory.stat at /a: no reclaim claimed


def test_v2_max_is_no_limit(tmp_path):
    root, proc = _v2(tmp_path, levels={"/app": {"memory.max": "max", "memory.current": str(10 * MB)}})
    got = cgroup_memory.cgroup_available_mb(root, proc)
    assert got["available_mb"] is None and got["unreadable"] is False


def test_v1_limit_and_two_to_the_63_is_no_limit(tmp_path):
    root, proc = _v1(tmp_path, files={
        "memory.limit_in_bytes": str(2048 * MB), "memory.usage_in_bytes": str(6 * MB),
        "memory.stat": f"cache 9\ntotal_inactive_file {2 * MB}\ninactive_file {1 * MB}\n"})
    got = cgroup_memory.cgroup_available_mb(root, proc)
    assert got["available_mb"] == 2044.0 and got["source"] == "cgroup_v1"  # total_inactive_file preferred
    (Path(root) / "memory" / "oo" / "memory.limit_in_bytes").write_text("9223372036854771712")
    assert cgroup_memory.cgroup_available_mb(root, proc)["available_mb"] is None


def test_unreadable_limit_is_none_never_zero(tmp_path):
    root, proc = _v2(tmp_path, levels={"/app": {"memory.max": "garbage", "memory.current": str(10 * MB)}})
    got = cgroup_memory.cgroup_available_mb(root, proc)
    assert got["available_mb"] is None and got["unreadable"] is True
    assert cgroup_memory.smaller_available_mb(15542.0, got) == (15542.0, "machine (a cgroup limit could not be read)")


def test_smaller_figure_and_its_name():
    assert cgroup_memory.smaller_available_mb(15542.0, {"available_mb": 2042.0}) == (2042.0, "cgroup limit")
    assert cgroup_memory.smaller_available_mb(1000.0, {"available_mb": 2042.0}) == (1000.0, "machine")
    assert cgroup_memory.smaller_available_mb(None, {"available_mb": 2042.0}) == (2042.0, "cgroup limit")
    assert cgroup_memory.smaller_available_mb(1000.0, {"available_mb": None}) == (1000.0, "machine")


def test_the_affordability_verdict_declines_under_a_small_cgroup(monkeypatch):
    """The measured case: psutil 15,542 MB available, a 2,048 MB cgroup with 2,042 MB free, a build needing 3,904 MB."""
    psutil = pytest.importorskip("psutil")

    class _VM:
        available = 15542 * MB

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb",
                        lambda *a, **k: {"available_mb": 2042.0, "limit_mb": 2048.0, "source": "cgroup_v1", "unreadable": False})
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 2413.0)
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    verdict = rollup_serve._affordability_verdict()
    assert verdict is not None and verdict["reason"] == "mem-short"
    assert verdict["available_mb"] == 2042.0 and verdict["available_from"] == "cgroup limit"
    assert "available_from" in rollup_serve._DETAIL_FIELDS


def test_without_a_cgroup_limit_the_verdict_names_the_machine(monkeypatch):
    psutil = pytest.importorskip("psutil")

    class _VM:
        available = 1000 * MB

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())
    monkeypatch.setattr(cgroup_memory, "cgroup_available_mb",
                        lambda *a, **k: {"available_mb": None, "limit_mb": None, "source": None, "unreadable": False})
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 740.0)
    monkeypatch.setattr(rollup_serve, "_guard_floor_mb", lambda: 256.0)
    verdict = rollup_serve._affordability_verdict()
    assert verdict["available_mb"] == 1000.0 and verdict["available_from"] == "machine"


def test_reclaim_is_counted_per_level_so_a_full_child_still_wins(tmp_path):
    """Review finding: an ancestor whose small raw headroom is mostly a sibling's page cache must not hide a child cgroup that is
    full of anonymous memory. Ancestor: 4 GB limit, 3.5 GB used of which 3 GB inactive cache (3.5 GB reclaimable room). Child:
    2 GB limit, 1.2 GB used, no cache (0.8 GB room). The child's 0.8 GB is the answer."""
    G = 1024 * MB
    root, proc = _v2(tmp_path, own="/slice/app", levels={
        "/slice": {"memory.max": str(4 * G), "memory.current": str(int(3.5 * G)), "memory.stat": f"inactive_file {3 * G}\n"},
        "/slice/app": {"memory.max": str(2 * G), "memory.current": str(int(1.2 * G)), "memory.stat": "inactive_file 0\n"},
    })
    got = cgroup_memory.cgroup_available_mb(root, proc)
    assert got["available_mb"] == pytest.approx(0.8 * 1024, abs=0.2)
    assert got["limit_mb"] == pytest.approx(2 * 1024, abs=0.1)
