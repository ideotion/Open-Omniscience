"""The ring files are read with the catalogue loader's safe class (libyaml when the wheel has it), not ``yaml.safe_load``.

The generated ring file is 566 KB; the pure-Python parse of it was 0.98 s (read on a first install and a reseed only) and libyaml's is 0.11 to 0.14 s
(Export, catalogue-parse REPORT item 6). A faster loader is only acceptable while it returns the same object and stays safe,
so this pins the route (``_read_yaml`` goes through the catalogue loader, not ``yaml.safe_load``) and both: the object equals the pure-Python parser's for each shipped ring file, and a payload that asks the loader
to run code is refused (``_read_yaml`` answers ``{}``), nothing executed.
"""
from __future__ import annotations

import yaml

from src.analytics import equivalence


def test_the_loader_returns_the_same_object_as_the_pure_python_parser_for_each_shipped_ring_file():
    for path in equivalence.shipped_rings_paths():
        text = path.read_text("utf-8")
        assert equivalence._read_yaml(path) == (yaml.safe_load(text) or {}), path.name


def test_a_ring_file_that_asks_for_code_is_refused_and_nothing_runs(tmp_path):
    ran = tmp_path / "ran"
    evil = tmp_path / "evil.yml"
    evil.write_text(f'!!python/object/apply:pathlib.Path.touch [!!python/object/apply:pathlib.Path ["{ran}"]]\n', "utf-8")
    assert equivalence._read_yaml(evil) == {}
    assert not ran.exists()


def test_a_missing_or_empty_ring_file_is_an_empty_mapping(tmp_path):
    empty = tmp_path / "empty.yml"
    empty.write_text("", "utf-8")
    assert equivalence._read_yaml(empty) == {}
    assert equivalence._read_yaml(tmp_path / "absent.yml") == {}


def test_the_ring_reader_goes_through_the_shared_safe_loader(tmp_path, monkeypatch):
    # The equality test above passes on the old ``yaml.safe_load`` call too; this is the one that fails on it.
    calls = []
    real = equivalence.load_safe_yaml
    monkeypatch.setattr(equivalence, "load_safe_yaml", lambda text: calls.append(text) or real(text))
    ring = tmp_path / "ring.yml"
    ring.write_text("a: 1\n", "utf-8")
    assert equivalence._read_yaml(ring) == {"a": 1}
    assert calls == ["a: 1\n"]


def test_the_seeder_and_the_rings_reader_parse_with_one_loader_class():
    from src.ingest import seed_sources
    from src.utils import safe_yaml

    assert seed_sources._YAML_LOADER is safe_yaml.YAML_LOADER
    assert seed_sources._SAFE_YAML_LOADERS is safe_yaml.SAFE_YAML_LOADERS
    assert {c.__name__ for c in safe_yaml.SAFE_YAML_LOADERS} <= {"CSafeLoader", "SafeLoader"}


def test_the_shared_module_imports_nothing_of_the_project():
    # It is hashed into the engine identity and imported by an index pass: a project import here is the seed chain again.
    import ast
    from pathlib import Path

    from src.utils import safe_yaml

    tree = ast.parse(Path(safe_yaml.__file__).read_text("utf-8"))
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [None])}
    assert {m for m in imported if m} <= {"__future__", "yaml"}, imported
