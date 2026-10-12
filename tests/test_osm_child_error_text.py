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


def _held(monkeypatch, value: str = "held-by-the-process-for-a-log-line-5517") -> str:
    monkeypatch.setenv("OO_DB_PASSPHRASE", value)
    return value


def test_the_index_build_failures_are_logged_without_the_held_passphrase(osm_lane_dir, monkeypatch, caplog):
    # A child holds the store's passphrase and its stderr rides into the parent's report: `exc_info=True` writes the
    # exception as it made its message. MUTATION TARGET: either call back to `_LOG.warning(..., exc_info=True)`.
    import logging

    held = _held(monkeypatch)

    def _boom(*a, **kw):
        raise RuntimeError(f"index said {held}")

    monkeypatch.setattr("src.osm.places.build_search_index", _boom)
    monkeypatch.setattr("src.osm.view.build_view_index", _boom)
    caplog.set_level(logging.WARNING)
    report = ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert report.status == "complete"
    assert "search index was not built" in caplog.text and "view index was not built" in caplog.text
    assert "RuntimeError" in caplog.text and held not in caplog.text


def test_the_admin1_split_records_and_logs_a_failure_without_the_held_passphrase(osm_lane_dir, tmp_path, monkeypatch, caplog):
    # MUTATION TARGET: the row's error, the unreadable answer's error or either log line back to the hand-made form.
    import logging

    from src.osm import completeness
    from tests.test_osm_completeness import _outlines

    held = _held(monkeypatch)
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    caplog.set_level(logging.WARNING)

    real_state = completeness.admin1_state
    monkeypatch.setattr(completeness, "admin1_state", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(f"state said {held}")))
    out = completeness.tag_completeness("ZZZ")
    assert out["admin1"]["status"] == "unreadable" and "RuntimeError" in out["admin1"]["error"] and held not in out["admin1"]["error"]
    monkeypatch.setattr(completeness, "admin1_state", lambda *a, **kw: (_ for _ in ()).throw(_unicode_error()))
    _clean(completeness.tag_completeness("ZZZ")["admin1"]["error"])
    monkeypatch.setattr(completeness, "admin1_state", real_state)

    monkeypatch.setattr(completeness, "_border", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(f"border said {held}")))
    with pytest.raises(RuntimeError):
        completeness.count_admin1("ZZZ", path=_outlines(tmp_path))
    with store.lane_session("osm") as s:
        from src.osm.lane_models import OsmAdmin1Split

        row = s.query(OsmAdmin1Split).filter_by(alpha3="ZZZ").one()
        assert row.status == "failed" and "RuntimeError" in row.error and held not in row.error
    assert "could not read the admin-1 split" in caplog.text
    assert held not in caplog.text


def test_the_admin1_count_thread_logs_a_failure_without_the_held_passphrase(osm_lane_dir, monkeypatch, caplog):
    import logging

    from src.osm import completeness

    held = _held(monkeypatch)
    monkeypatch.setattr(completeness, "count_admin1", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError(f"count said {held}")))
    caplog.set_level(logging.WARNING)
    ran = []
    monkeypatch.setattr(completeness.threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda self: ran.append(target())})())
    monkeypatch.setattr(completeness, "load_outlines", lambda p=None: {"regions": {"ZZ-W": {"country": "ZZZ", "rings": []}}})
    monkeypatch.setattr(completeness, "_country_regions", lambda doc, a3: {"ZZ-W": {}})
    completeness.start_count("ZZZ")
    assert ran, "the thread body ran"
    assert "admin-1 count for ZZZ failed" in caplog.text and "RuntimeError" in caplog.text and held not in caplog.text


def test_the_whole_of_each_script_is_under_the_handler(osm_lane_dir, monkeypatch, capsys):
    # The key lookup, the file stats and the lane size read all run in a process that holds the passphrase: a default
    # traceback would print the exception as it made its message. MUTATION TARGET: `main` back to a bare body.
    held = _held(monkeypatch)
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")

    def _boom(*a, **kw):
        raise RuntimeError(f"lookup said {held}")

    import src.database.connect as connect

    monkeypatch.setattr(connect, "get_passphrase", _boom)
    for module, extra in ((INGEST_CLI, []), (HISTORY_CLI, ["--history", str(FIXTURE)])):
        monkeypatch.setattr(sys, "argv", ["x", "--extract", str(FIXTURE), "--country", "ZZ", *extra])
        assert module.main() == 1
        out = capsys.readouterr().out
        assert out.startswith("failed: RuntimeError") and held not in out


def test_the_gazetteer_build_is_wholly_under_the_handler(osm_lane_dir, monkeypatch, capsys):
    from scripts import build_place_gazetteer as BUILD
    from src.entities import gazetteer_build as G

    held = _held(monkeypatch)
    monkeypatch.setattr(G, "today", lambda: (_ for _ in ()).throw(RuntimeError(f"clock said {held}")))
    assert BUILD.main(["--country", "ZZ", "--no-wikidata"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("failed: RuntimeError") and held not in out
