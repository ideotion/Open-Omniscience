"""Shared fixtures for the OSM lane's tests (S05-04). Not collected: no ``test_`` prefix.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "osm" / "synthetic.osm.pbf"

HAVE_OSMIUM = importlib.util.find_spec("osmium") is not None
#: Both readers where the [geo] extra is installed; the pure-Python one everywhere.
READERS = [
    "python",
    pytest.param("pyosmium", marks=pytest.mark.skipif(not HAVE_OSMIUM, reason="the [geo] extra is not installed")),
]


def generator():
    """``scripts/make_osm_fixture.py`` as a module: the literals every expected value comes from."""
    spec = importlib.util.spec_from_file_location("make_osm_fixture", ROOT / "scripts" / "make_osm_fixture.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def osm_lane_dir(tmp_path, monkeypatch):
    """A fresh data directory; lanes disposed on the way in and out (the engine map is global)."""
    from src.versioned import store

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    try:
        yield tmp_path
    finally:
        store.dispose_all()
