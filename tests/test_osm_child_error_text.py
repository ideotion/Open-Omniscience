"""The OSM reference run's CHILDREN write their failures as text the parent carries into its report, and a child holds the
throwaway store's passphrase: a text an engine made from the key (a ``UnicodeError`` names the letter it could not encode and
its offset, which no exact-match scrub can recognise) must leave the child by its class alone.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sys

import pytest

from scripts import osm_history_ingest as HISTORY_CLI
from scripts import osm_ingest as INGEST_CLI
from src.osm import ingest
from src.osm.lane_models import OsmCountry
from src.versioned import store
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

_LEAKS = ("ä", "xe4", "ordinal", "position", "range(128)")


def _unicode_error() -> UnicodeEncodeError:
    return UnicodeEncodeError("ascii", "pässword-0123456789", 1, 2, "ordinal not in range(128)")


def _clean(text: str) -> None:
    assert "UnicodeEncodeError" in text, text
    for leaked in _LEAKS:
        assert leaked not in text, (leaked, text)


def test_the_ingest_records_a_unicode_error_by_class_alone(osm_lane_dir, monkeypatch):
    # MUTATION TARGET: `report.error` back to f"{type(exc).__name__}: {exc}" in src/osm/ingest.py.
    monkeypatch.setattr(ingest.T, "classify", lambda *a, **kw: (_ for _ in ()).throw(_unicode_error()))
    with pytest.raises(UnicodeEncodeError):
        ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
        assert row.status == "failed"
        _clean(row.error)


@pytest.mark.parametrize("module,target", [(INGEST_CLI, "src.osm.ingest.ingest_country"),
                                           (HISTORY_CLI, "src.osm.history.ingest_history")])
def test_the_children_print_a_unicode_error_by_class_alone(osm_lane_dir, monkeypatch, capsys, module, target):
    # MUTATION TARGET: the `failed:` line back to f"failed: {type(exc).__name__}: {exc}" in either script.
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    mod_name, attr = target.rsplit(".", 1)
    monkeypatch.setattr(sys.modules.setdefault(mod_name, __import__(mod_name, fromlist=[attr])), attr,
                        lambda *a, **kw: (_ for _ in ()).throw(_unicode_error()))
    argv = ["x", "--extract", str(FIXTURE), "--country", "ZZ"]
    if module is HISTORY_CLI:
        argv += ["--history", str(FIXTURE)]
    monkeypatch.setattr(sys, "argv", argv)
    assert module.main() == 1
    out = capsys.readouterr().out
    assert out.startswith("failed:")
    _clean(out)
