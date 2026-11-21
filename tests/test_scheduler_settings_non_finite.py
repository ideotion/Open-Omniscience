"""A stored or sent number that is not finite never breaks the scheduler settings (docket row 252).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

JSON reads ``1e999`` as infinity and Python's ``json`` also accepts ``NaN`` and ``Infinity``. ``int(inf)`` raises
``OverflowError``, which the settings coercion did not catch, so one damaged or hand-edited field made EVERY read of the
scheduler settings raise, and a save that carried one answered 500 instead of the usual refusal. NaN came out of the
float clamp as one of its bounds, chosen by argument order. Each of these now takes the path any other unreadable value
takes: the field's default when reading, a named refusal when saving.
"""

from __future__ import annotations

import json
import math

import pytest

from src.scheduler import settings as sch


@pytest.fixture()
def stored(tmp_path, monkeypatch):
    path = tmp_path / "scheduler_settings.json"
    monkeypatch.setattr(sch, "_settings_path", lambda: path)

    def write(raw: str) -> None:
        path.write_text(raw, encoding="utf-8")

    return write


@pytest.mark.parametrize("bad", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
def test_a_stored_non_finite_integer_reads_as_its_default(stored, bad):
    stored('{"crawl_per_pass": %s, "collect_parallelism": %s, "crawl_max_pages": 9}' % (bad, bad))
    d = sch.SchedulerSettings()
    s = sch.load_settings()
    assert s.crawl_per_pass == d.crawl_per_pass
    assert s.collect_parallelism == d.collect_parallelism
    assert s.crawl_max_pages == 9, "the readable field beside it is kept"


@pytest.mark.parametrize("bad", ["NaN", "1e999", "-1e999"])
def test_a_stored_non_finite_float_reads_as_its_default_never_as_a_bound(stored, bad):
    stored('{"equilibrium_floor": %s}' % bad)
    assert sch.load_settings().equilibrium_floor == sch.SchedulerSettings().equilibrium_floor


def test_a_stored_infinite_weight_is_dropped_and_the_finite_ones_kept(stored):
    stored('{"language_equilibrium": {"en": 1e999, "fr": 0.5, "de": NaN}}')
    assert sch.load_settings().language_equilibrium == {"fr": 0.5}


def test_finite_values_still_clamp_as_before(stored):
    stored(json.dumps({"crawl_per_pass": 10**9, "equilibrium_floor": 7.5}))
    s = sch.load_settings()
    assert s.crawl_per_pass == 100 and s.equilibrium_floor == 1.0


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_a_non_finite_save_is_refused_by_name(stored, bad):
    with pytest.raises(sch.SchedulerSettingsError, match="crawl_per_pass must be an integer"):
        sch.save_settings({"crawl_per_pass": bad})
    with pytest.raises(sch.SchedulerSettingsError, match="equilibrium_floor"):
        sch.save_settings({"equilibrium_floor": bad})


def test_a_float_too_large_to_be_one_is_refused_by_name(stored):
    with pytest.raises(sch.SchedulerSettingsError, match="equilibrium_floor must be a number"):
        sch.save_settings({"equilibrium_floor": 10**400})


def test_the_endpoint_answers_a_non_finite_number_with_a_refusal_never_a_500(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app, raise_server_exceptions=False) as c:
        for body in ('{"crawl_per_pass": 1e999}', '{"equilibrium_floor": 1e999}', '{"crawl_per_pass": NaN}'):
            r = c.put("/api/scheduler/config", content=body, headers={"content-type": "application/json"})
            assert r.status_code in (400, 422), (body, r.status_code, r.text[:200])


def test_the_same_shape_elsewhere_refuses_or_falls_back_instead_of_raising(monkeypatch):
    """The same ``int(float(...))`` on text a person or a file supplies: an imported sources CSV and the storage-guard
    size variables. Each answers the way it already answers a word that is not a number."""
    from src.catalog.csv_io import parse_sources_csv
    from src.scheduler import storage_guard

    rows, errors = parse_sources_csv("name,domain,priority\nX,x.example,1e999\n")
    assert rows == [] and any("priority is not a number" in e for e in errors)
    monkeypatch.setenv("OO_WAL_HIGH_MB", "inf")
    assert storage_guard._env_mb("OO_WAL_HIGH_MB") is None
