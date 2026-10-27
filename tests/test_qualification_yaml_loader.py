"""The shipped qualification overlay is parsed with the shared safe loader (libyaml when present), not ``yaml.safe_load``.

Measured 2026-10-27 (qual lane, 5 runs each, median; CPython 3.13.16, PyYAML 6.0.3 with libyaml, 4 cores, nothing beside it) on overlays
rendered by ``qualification_merge.render``, the writer of the shipped file: 5,580 rows (one per ``configs/sources.yml`` entry, 813,485 B)
1,929 ms with ``yaml.safe_load`` against 356 ms with libyaml; 55,800 rows (8,186,225 B) 26,086 ms against 5,478 ms. The overlay is read
at every boot and by the status read. The two UPLOAD readers deliberately stay on ``yaml.safe_load`` (see the test that pins it). A faster loader is acceptable only while it returns the same objects, so this pins which class runs
at each site and that a generated 5,580-row overlay reads back identically under the pure loader.
"""
from __future__ import annotations

import pytest
import yaml

from src.catalog import qualification_merge as qm
from src.catalog import qualification_overlay as qo
from src.utils import safe_yaml

_LOADERS = [pytest.param(yaml.SafeLoader, id="pure")]
if getattr(yaml, "CSafeLoader", None) is not None:
    _LOADERS.append(pytest.param(yaml.CSafeLoader, id="libyaml"))

_ROWS = 5580


def _rendered(n=_ROWS) -> str:
    rows = {
        f"site{i}.example{i % 97}.org": {
            "domain": f"site{i}.example{i % 97}.org", "status": "qualified" if i % 3 else "disqualified",
            "qualified_at": "2026-09-01T10:00:00+00:00", "criteria_version": "2026-08-1", "basis": "measured",
        }
        for i in range(n)
    }
    return qm.render(rows)


@pytest.fixture
def overlay_path(tmp_path):
    p = tmp_path / "source_qualification.yml"
    p.write_text(_rendered(), encoding="utf-8")
    return p


def _spy(monkeypatch, cls):
    used = []

    class Spy(cls):
        # counted where the document is CONSTRUCTED: the depth guard builds a second loader for its event pass on libyaml,
        # so instantiations are not parses
        def get_single_data(self):
            used.append(cls)
            return super().get_single_data()

    monkeypatch.setattr(safe_yaml, "YAML_LOADER", Spy)
    return used


@pytest.mark.parametrize("cls", _LOADERS)
def test_load_overlay_runs_the_loader_class_the_shared_module_names(cls, overlay_path, monkeypatch):
    used = _spy(monkeypatch, cls)
    assert len(qo.load_overlay(overlay_path)) == _ROWS
    assert used == [cls]


@pytest.mark.parametrize("cls", _LOADERS)
def test_the_merge_readers_run_the_loader_class_the_shared_module_names(cls, monkeypatch):
    used = _spy(monkeypatch, cls)
    text = _rendered(50)
    assert len(qm.existing_from_text(text)) == 50
    assert used == [cls]


def test_the_upload_readers_keep_the_pure_loader(monkeypatch):
    # An uploaded export is attacker-sized input. libyaml's loader does not raise RecursionError on deep nesting: on this
    # box a 100,000-deep "- - - x" document segfaults the process (20,000 deep parses), where the pure loader refuses it
    # with RecursionError, which the readers turn into a 400. So these two sites must never reach the shared loader.
    def boom(_text):
        raise AssertionError("an upload was parsed with the shared (libyaml) loader")

    monkeypatch.setattr(qm, "load_safe_yaml", boom)
    text = _rendered(5)
    assert len(qm._rows_from_export_yaml(text, "x.yml", None)) == 5
    assert qm.repair_record_flags_of_export_bytes(text.encode()) == {}


@pytest.mark.parametrize("cls", _LOADERS)
def test_a_generated_overlay_reads_back_identical_to_the_pure_python_parse(cls, overlay_path, monkeypatch):
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", cls)
    got = qo.load_overlay(overlay_path)
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.SafeLoader)
    assert got == qo.load_overlay(overlay_path)
    assert len(got) == _ROWS
    text = overlay_path.read_text(encoding="utf-8")
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", cls)
    assert qm.existing_from_text(text) == {
        str(r["domain"]): r for r in yaml.safe_load(text)["verdicts"]
    }


def test_a_broken_overlay_is_still_an_empty_overlay_not_a_crash(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("verdicts: [unclosed\n", encoding="utf-8")
    assert qo.load_overlay(bad) == {}


@pytest.mark.parametrize("cls", _LOADERS)
def test_the_status_read_parses_the_overlay_once_and_reports_the_same_header(cls, overlay_path, monkeypatch):
    # Before: load_overlay parsed the file and the header read parsed it again (about 3.9 s for 5,580 rows on the pure loader).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    used = _spy(monkeypatch, cls)
    status = qo.overlay_status(session, path=overlay_path)
    assert used == [cls]
    assert status["file"]["generated_at"] == str(yaml.safe_load(overlay_path.read_text("utf-8"))["generated_at"])
    assert status["file"]["exists"] is True
    assert status["shipped_qualified"] + status["shipped_disqualified"] == _ROWS


def test_the_status_header_of_an_absent_or_broken_overlay_is_unchanged(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    absent = qo.overlay_status(session, path=tmp_path / "nope.yml")
    assert absent["file"]["exists"] is False and absent["file"]["generated_at"] is None
    bad = tmp_path / "bad.yml"
    bad.write_text("verdicts: [unclosed\n", encoding="utf-8")
    broken = qo.overlay_status(session, path=bad)
    assert broken["file"]["exists"] is True and broken["file"]["generated_at"] is None
