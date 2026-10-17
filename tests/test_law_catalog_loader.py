"""The law catalogue is read with the seed catalogue's SAFE loader (libyaml where the wheel has it), and the objects it
returns are the ones the pure-Python parser returns.

The generated legal catalogue is 297 KB; ``yaml.safe_load`` (pure Python) took 0.43 s and the boot reads it twice
(``seed_default_sources`` and ``seed_legal_sources``), 0.044 s with libyaml. A speed choice is only acceptable while it
is the same data, so this pins identical output -- same shape, same TYPES (dates, ints, strings), same aliasing -- on
every real catalogue the boot parses, not on a toy document.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from src.ingest import seed_sources
from src.law import catalog as law_catalog


def _signature(root: object) -> str:
    """A type-aware, alias-aware digest: a container met a second time contributes its first index, not its content."""
    seen: dict[int, int] = {}
    out: list[object] = []

    def walk(x: object) -> None:
        if isinstance(x, (dict, list)):
            if id(x) in seen:
                out.append(("ALIAS", seen[id(x)]))
                return
            seen[id(x)] = len(seen)
        out.append(type(x).__name__)
        if isinstance(x, dict):
            out.append(len(x))
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, list):
            out.append(len(x))
            for v in x:
                walk(v)
        else:
            out.append(repr(x))

    walk(root)
    return hashlib.sha256(repr(out).encode()).hexdigest()


def _pure(text: str) -> object:
    loader = yaml.SafeLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


REAL_CATALOGUES = [
    seed_sources.DEFAULT_SOURCES_PATH,
    law_catalog.LEGAL_CATALOG_PATH,
    law_catalog.GENERATED_CATALOG_PATH,
]


@pytest.mark.parametrize("path", REAL_CATALOGUES, ids=lambda p: Path(p).name)
def test_the_shared_loader_parses_each_real_catalogue_to_the_pure_parsers_objects(path):
    if not Path(path).exists():
        pytest.skip(f"{Path(path).name} is optional and absent here")
    text = Path(path).read_text(encoding="utf-8")
    fast = seed_sources._load_safe_yaml(text)
    slow = _pure(text)
    assert fast == slow
    assert _signature(fast) == _signature(slow), "same values but different types or aliasing"


def test_the_law_catalogue_reads_through_the_shared_safe_loader(monkeypatch):
    """Red without the switch: ``_read_catalog_yaml`` went to ``yaml.safe_load`` and never touched the shared loader."""
    calls: list[int] = []
    real = seed_sources._load_safe_yaml

    def spy(text: str):
        calls.append(len(text))
        return real(text)

    monkeypatch.setattr(law_catalog, "_load_safe_yaml", spy)
    got = law_catalog._read_catalog_yaml(law_catalog.LEGAL_CATALOG_PATH)
    assert len(calls) == 1 and got["sources"], "the curated catalogue is read once and yields its sources"


@pytest.mark.parametrize(
    "body, klass",
    [
        ("sources: [unclosed\n", "Error"),  # a malformed file: the named error, the class only
        ('!!python/object/apply:os.system ["echo pwned"]\n', "Error"),  # the unsafe tag is refused, never run
    ],
)
def test_an_unparseable_law_catalogue_still_ends_with_the_named_error_and_no_path_or_text(tmp_path, body, klass):
    target = tmp_path / "law.yml"
    target.write_text(body, encoding="utf-8")
    with pytest.raises(law_catalog.LawCatalogUnreadable, match="law.yml could not be read") as info:
        law_catalog._read_catalog_yaml(target)
    assert klass in str(info.value)
    assert str(tmp_path) not in str(info.value) and "pwned" not in str(info.value)


def _pure_loader(text: str):
    return _pure(text)


@pytest.mark.parametrize("loader_name", ["shared", "pure"])
def test_an_impossible_date_ends_in_the_named_error_under_both_loaders(tmp_path, monkeypatch, loader_name):
    """The independent read found, older than its delta: PyYAML's CONSTRUCTOR rejects ``2026-13-45`` with a ``ValueError``, which
    is not a ``YAMLError``, so the contract "every other failure ends the load with LawCatalogUnreadable, naming the file and
    the error's class only" did not hold for it under either loader. It does now, and the file's text stays out."""
    if loader_name == "pure":
        monkeypatch.setattr(law_catalog, "_load_safe_yaml", _pure_loader)
    target = tmp_path / "law.yml"
    target.write_text("sources: []\ndocuments: []\nas_of: 2026-13-45\n", encoding="utf-8")
    with pytest.raises(law_catalog.LawCatalogUnreadable, match="law.yml could not be read") as info:
        law_catalog._read_catalog_yaml(target)
    assert "ValueError" in str(info.value)
    assert str(tmp_path) not in str(info.value) and "13-45" not in str(info.value)
