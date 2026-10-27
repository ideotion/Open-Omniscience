"""The two remaining readers of a file the operator (or a restored backup) controls, on the shared guarded loader.

``ring_loader.merge_local_rings`` reads the same local ring file as F5 (a restored backup writes it unparsed) and
``SourceManager.import_sources_from_yaml`` reads a path its caller hands it. Both used the pure ``yaml.safe_load``: crash-safe, but a
100,000-deep document (about 200 KB) raised ``RecursionError`` at about 500 levels, which neither ``except (OSError, yaml.YAMLError)`` nor a
route handler catches. Now both refuse it as ``YAMLDepthError`` (a ``yaml.YAMLError``) on BOTH loader paths, with the process alive.
Timing (CPython 3.13, PyYAML 6.0.3, this container): refusing the 100,000-deep file costs 2.7 ms (median of 5) through libyaml's event pass and
1,385 ms (median of 5) through the pure loader's RecursionError; a parse of the shipped 1.4 MB ``sources.yml`` adds a measured 180 to 210 ms of event pass to
a 781 to 1,014 ms libyaml load (the pure loader needs several times that).
"""
from __future__ import annotations

import logging

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import ring_loader
from src.database.models import Base
from src.database.source_manager import SourceManager
from src.utils import safe_yaml
from src.utils.safe_yaml import YAMLDepthError

_DEEP = 100_000


@pytest.fixture(params=["libyaml", "pure"])
def loader(request, monkeypatch):
    if request.param == "libyaml":
        if getattr(yaml, "CSafeLoader", None) is None:
            pytest.skip("libyaml is not present")
        monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.CSafeLoader)
    else:
        monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.SafeLoader)
    return request.param


def _hostile(path, prefix):
    path.write_text(prefix + "[" * _DEEP + "x" + "]" * _DEEP + "\n", encoding="utf-8")
    return path


def test_merging_into_a_hostile_local_ring_file_is_refused_and_leaves_it_untouched(loader, tmp_path, caplog):
    target = _hostile(tmp_path / "keyword_rings_local.yml", "rings: ")
    before = target.read_bytes()
    caplog.set_level(logging.WARNING)
    added = ring_loader.merge_local_rings([{"id": "x", "members": ["a", "b"]}], path=target)
    assert added == 0
    assert target.read_bytes() == before, "an unreadable local file is never overwritten"
    assert any("unreadable" in r.getMessage() and "keyword_rings_local.yml" in r.getMessage() for r in caplog.records)


def test_importing_a_hostile_sources_file_raises_a_yaml_error_not_a_recursion_error(loader, tmp_path):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        path = _hostile(tmp_path / "sources.yml", "sources: ")
        with pytest.raises(YAMLDepthError) as caught:
            SourceManager(session).import_sources_from_yaml(str(path))
        assert isinstance(caught.value, yaml.YAMLError)
    finally:
        session.close()
