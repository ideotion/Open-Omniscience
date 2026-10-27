"""The gazetteer is parsed with the shared safe loader (libyaml when the wheel has it), not ``yaml.safe_load``.

WAL premise sweep 2026-10-27 (``wal-lane/premise-sweep-2026-10-27.md``, D1/A4), measured on a 50,000-city, 4.2 MB gazetteer written by
``City.to_dict`` + ``safe_dump`` on a 4-core box: ``load_cities`` 20.0 s with the pure-Python loader against 4.4 s with ``CSafeLoader``,
paid once per process by the first map request. The statement measured is ``yaml.safe_load(path.read_text())`` against the same text
through ``CSafeLoader``. A faster loader is acceptable only while it returns the same objects, so this pins which class runs in each
case and that the cities and the vintage come out identical either way.
"""
from __future__ import annotations

import pytest
import yaml

from src.catalog import cities
from src.utils import safe_yaml

_LOADERS = [pytest.param(yaml.SafeLoader, id="pure")]
if getattr(yaml, "CSafeLoader", None) is not None:
    _LOADERS.append(pytest.param(yaml.CSafeLoader, id="libyaml"))


def _gazetteer(tmp_path, n=300):
    rows = [
        {"name": f"Città {i}", "country": "FR", "lat": 40.0 + i / 1000, "lon": 2.0 + i / 1000, "population": 1000 + i,
         "qid": f"Q{1000 + i}", "aliases": [f"Ville {i}", f"Stadt {i}"]}
        for i in range(n)
    ]
    p = tmp_path / "cities.yml"
    p.write_text(yaml.safe_dump({"as_of": "2026-10-01", "cities": rows}, allow_unicode=True), "utf-8")
    return p


@pytest.mark.parametrize("cls", _LOADERS)
def test_the_loader_class_that_runs_is_the_one_the_shared_module_names(cls, tmp_path, monkeypatch):
    used = []

    class Spy(cls):
        def __init__(self, text):
            used.append(cls)
            super().__init__(text)

    monkeypatch.setattr(safe_yaml, "YAML_LOADER", Spy)
    p = _gazetteer(tmp_path)
    assert cities._file_vintage(p) == "2026-10-01"
    assert cities._load_file(p)
    assert used == [cls, cls]


@pytest.mark.parametrize("cls", _LOADERS)
def test_the_cities_and_the_vintage_are_identical_to_the_pure_python_parse(cls, tmp_path, monkeypatch):
    p = _gazetteer(tmp_path)
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", cls)
    got = cities._load_file(p)
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.SafeLoader)
    assert got == cities._load_file(p)
    assert got[0].name == "Città 0"
    assert yaml.safe_load(p.read_text("utf-8"))["as_of"] == "2026-10-01"


def test_the_default_loader_is_libyaml_when_the_wheel_has_it():
    expected = getattr(yaml, "CSafeLoader", None) or yaml.SafeLoader
    assert safe_yaml.YAML_LOADER is expected


def test_a_damaged_gazetteer_is_still_a_yaml_error_not_a_crash(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("cities: [unclosed\n", "utf-8")
    assert cities._file_vintage(bad) is None
    with pytest.raises(yaml.YAMLError):
        cities._load_file(bad)
