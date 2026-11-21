"""``load_safe_yaml`` refuses a document nested past ``MAX_NESTING`` instead of letting libyaml's composer crash the process.

libyaml's composer recurses on the C stack with no limit of its own. Measured 2026-10-27 on an 8 MiB stack, main thread and worker
thread alike: block and flow mappings parse to 23,681 levels and crash at 23,925, sequences parse to 25,876 and crash at 26,364. The
pure-Python loader raises RecursionError at about 500 levels. Both paths now raise the same ``YAMLDepthError``, a ``yaml.YAMLError``.
"""
from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

from src.utils import safe_yaml
from src.utils.safe_yaml import MAX_NESTING, YAMLDepthError, load_safe_yaml

_LOADERS = [pytest.param(yaml.SafeLoader, id="pure")]
if getattr(yaml, "CSafeLoader", None) is not None:
    _LOADERS.append(pytest.param(yaml.CSafeLoader, id="libyaml"))

_DEEP = 100_000


def _seq(n):
    return "- " * n + "x"


def _flow_seq(n):
    return "[" * n + "x" + "]" * n


def _flow_map(n):
    return "{a: " * n + "x" + "}" * n


def _block_map(n):
    return "".join(" " * i + "a:\n" for i in range(n)) + " " * n + "x"


@pytest.fixture(params=_LOADERS)
def loader(request, monkeypatch):
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", request.param)
    return request.param


@pytest.mark.parametrize("make", [_seq, _flow_seq, _flow_map], ids=["seq", "flow-seq", "flow-map"])
def test_a_100000_deep_document_is_refused_with_the_same_error_on_both_loader_paths(loader, make):
    with pytest.raises(YAMLDepthError) as err:
        load_safe_yaml(make(_DEEP))
    assert isinstance(err.value, yaml.YAMLError)
    # libyaml's refusal names the bound; the pure loader's RecursionError is turned into the error without a number (its own limit)
    assert (str(MAX_NESTING) in str(err.value)) == (loader is not yaml.SafeLoader)
    assert "x" not in str(err.value).replace("nests deeper than", "")  # no text of the document in the message


def test_a_deep_block_mapping_is_refused_on_both_loader_paths(loader):
    # indentation makes a block mapping quadratic in size, so this one is 2,000 deep (4 MB), already 8x the bound
    with pytest.raises(YAMLDepthError):
        load_safe_yaml(_block_map(2000))


def test_the_bound_itself_parses_on_both_paths(loader):
    assert load_safe_yaml(_seq(MAX_NESTING)) is not None
    assert load_safe_yaml(_flow_map(MAX_NESTING)) is not None


@pytest.mark.skipif(getattr(yaml, "CSafeLoader", None) is None, reason="libyaml is not present")
def test_one_level_over_the_bound_is_refused_before_libyaml_composes_it(monkeypatch):
    # The pure path has no pre-pass (measured: the pass would take 1,934 ms on top of a 2,489 ms parse of the 5,580-row overlay,
    # 78%): it is already crash-safe and refuses at about 500 levels through RecursionError, so the sharp bound is libyaml's.
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.CSafeLoader)
    with pytest.raises(YAMLDepthError):
        load_safe_yaml(_seq(MAX_NESTING + 1))
    with pytest.raises(YAMLDepthError):
        load_safe_yaml(_flow_map(MAX_NESTING + 1))


def test_ordinary_documents_read_exactly_as_yaml_safe_load_reads_them(loader):
    from pathlib import Path

    for name in ("keyword_equivalents.yml", "catalog_targets.yml", "legal_sources.yml", "language_countries.yml"):
        text = (Path(__file__).resolve().parents[1] / "configs" / name).read_text("utf-8")
        assert load_safe_yaml(text) == yaml.safe_load(text), name
    assert load_safe_yaml("") is None
    assert load_safe_yaml("a: 1") == {"a": 1}


def test_a_malformed_document_is_still_an_ordinary_yaml_error(loader):
    with pytest.raises(yaml.YAMLError) as err:
        load_safe_yaml("verdicts: [unclosed\n")
    assert not isinstance(err.value, YAMLDepthError)


def libyaml_limits_nesting() -> bool:
    """True when the libyaml PyYAML carries has a nesting limit of its own: 0.2.6, bundled from PyYAML 6.0.4 (2026-11-20). Keyed on
    libyaml's own version, not PyYAML's, because a PyYAML built against a system libyaml takes that one's behaviour."""
    from yaml import _yaml

    return tuple(int(p) for p in _yaml.get_version_string().split(".")[:3]) >= (0, 2, 6)


def assert_the_unguarded_c_loader_fails_on_it(done: subprocess.CompletedProcess) -> None:
    """The reason the guard exists, as the installed libyaml has it: below 0.2.6 the C loader dies by signal (a crash, not an
    exception); from 0.2.6 its scanner raises past 1,000 levels instead. Either way the guard's refusal must come first, at 256."""
    if libyaml_limits_nesting():
        assert done.returncode == 1 and "exceeded maximum nesting depth" in done.stderr, (
            "libyaml 0.2.6 or later no longer raises its own nesting error on this input: re-measure the bound")
    else:
        # not "died by signal": Windows reports a stack overflow as the positive code 0xC00000FD
        assert done.returncode != 0, "libyaml no longer crashes on deep nesting: the guard's premise changed; re-measure the bound"
        # ... and not by an ordinary Python exception (exit 1 with a traceback): that would be the library fixing itself
        assert "Traceback" not in done.stderr, "libyaml now raises on deep nesting instead of crashing: re-measure the bound"


@pytest.mark.skipif(getattr(yaml, "CSafeLoader", None) is None, reason="libyaml is not present")
def test_the_unguarded_libyaml_loader_really_does_crash_on_this_input():
    # Run in a child so the crash is a return code and not this test's death: the loader this repo used before the guard (the C
    # loader, called directly) dies by signal on a 100,000-deep document below libyaml 0.2.6, and raises from 0.2.6 (row 239).
    code = (
        "import yaml\n"
        f"t = {'- '!r} * {_DEEP} + 'x'\n"
        "yaml.load(t, Loader=yaml.CSafeLoader)\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert_the_unguarded_c_loader_fails_on_it(done)


@pytest.mark.skipif(getattr(yaml, "CSafeLoader", None) is None, reason="libyaml is not present")
def test_past_libyamls_own_limit_the_refusal_is_still_the_depth_error_on_every_shape(monkeypatch):
    """Row 239 (R696): from libyaml 0.2.6 a flow document past 1,000 levels raises a ScannerError from the scanner's read-ahead before
    the event count reaches the bound; it must come out as the same YAMLDepthError, through both entry points, on every shape."""
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.CSafeLoader)
    for doc in (_flow_seq(1001), _flow_map(1001), _seq(1001), _block_map(1001), _flow_seq(_DEEP)):
        for call in (safe_yaml.refuse_if_too_deep, load_safe_yaml):
            with pytest.raises(YAMLDepthError, match=str(MAX_NESTING)):
                call(doc)
    with pytest.raises(yaml.YAMLError) as err:  # an ordinary scanner error is still not a depth refusal
        load_safe_yaml("a: [1, 2\n")
    assert not isinstance(err.value, YAMLDepthError)


def test_the_shared_module_still_imports_nothing_of_the_project():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(safe_yaml.__file__).read_text("utf-8"))
    imported = {n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [None])}
    assert {m for m in imported if m} <= {"__future__", "yaml"}, imported


def test_the_catalogue_loader_goes_through_the_guard_too(loader, monkeypatch):
    # seed_sources keeps its own wrapper (the GC pause) around the parse of the seven boot catalogues; it must not bypass the guard
    from src.ingest import seed_sources

    if loader is yaml.SafeLoader:  # its module-level copy of the class: without this the pure case would hand libyaml the document
        monkeypatch.setattr(seed_sources, "_YAML_LOADER", yaml.SafeLoader)
    with pytest.raises(YAMLDepthError):
        seed_sources._load_safe_yaml(_seq(_DEEP))
    assert seed_sources._load_safe_yaml("sources:\n  - name: A\n    domain: a.example\n") == {
        "sources": [{"name": "A", "domain": "a.example"}]
    }


@pytest.mark.skipif(not hasattr(yaml, "CSafeLoader"), reason="the bound is libyaml's")
def test_a_truncated_document_past_the_bound_is_still_named_too_deep(monkeypatch):
    # the 257th opener is the last thing the parser can read: the bound is checked at each opener, so the refusal is the depth one,
    # not whatever the parser raises on the next event
    monkeypatch.setattr(safe_yaml, "YAML_LOADER", yaml.CSafeLoader)
    for text in ("[" * (MAX_NESTING + 1), "[" * (MAX_NESTING + 1) + "}"):
        with pytest.raises(YAMLDepthError):
            load_safe_yaml(text)
