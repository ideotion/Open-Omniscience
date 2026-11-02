"""store.py's contribution to the engine identity is the code ``index_article`` can reach, not the file's bytes.

Why: store.py changed in 24 of ~40 commits that touched any engine file in 30 days, so the engine id changed about every 18 hours
and a backup rarely carried (R24). The narrowing must never UNDER-include: every reachable definition moves the id, and every doubt
(dynamic lookup, an import that could call back, a redefinition) falls back to the whole file.
"""

from __future__ import annotations

import ast

import pytest

from src.analytics import engine_identity as ei
from tests.js_source_helper import python_function_source

REL = "src/analytics/store.py"
OWN = "src.analytics.store"


def _source() -> bytes:
    data = ei._read(REL)
    assert data is not None
    return data


def _digest(src: bytes | str, **kw):
    if isinstance(src, str):
        src = src.encode()
    return ei.narrowed_source_digest(src, "index_article", own_module=OWN, **kw)


def _mutate(src: bytes, name: str) -> bytes:
    """The same module with one extra statement at the top of ``name``'s body, round-tripped through ast.unparse."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            node.body.insert(0, ast.parse("_mutant_ = 1").body[0])
            break
    else:
        raise AssertionError(name)
    return ast.unparse(tree).encode()


def _top_level_functions(src: bytes) -> list[str]:
    return [n.name for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_the_real_store_module_can_be_narrowed():
    extra = ei._names_other_engine_modules_take_from(REL)
    assert extra is not None
    assert ei.narrowed_source_digest(_source(), "index_article", extra_roots=extra, own_module=OWN) is not None
    assert ei._engine_file_bytes(REL, _source()).startswith(b"\x00narrowed:")


def test_every_function_is_either_reachable_and_moves_the_id_or_unreachable_and_does_not():
    src = _source()
    extra = ei._names_other_engine_modules_take_from(REL) or frozenset()
    base = ast.unparse(ast.parse(src)).encode()
    base_digest = _digest(base, extra_roots=extra)
    assert base_digest is not None
    moved, still = [], []
    for name in _top_level_functions(src):
        d = _digest(_mutate(base, name), extra_roots=extra)
        (moved if d != base_digest else still).append(name)
    # index_article and the helpers it calls are in the identity; the drains and the rest are not
    assert "index_article" in moved
    assert "_write_mention_diff" in moved
    # the CALLERS of index_article feed it values it writes and certifies (country, precomputed terms, language): they are in
    assert "_reindex_articles_impl" in moved and "backfill_corpus" in moved
    # and so are the callers of those callers: the public wrapper and the batch driver choose the scope and country they pass on
    assert "reindex_articles" in moved and "reindex_all_batch" in moved
    assert len(moved) >= 10 and len(still) >= 5


def test_a_changed_constant_import_or_toplevel_statement_moves_the_id():
    base = b"import os\nLIMIT = 3\ndef index_article():\n    return LIMIT\n"
    d = _digest(base)
    assert d is not None
    assert _digest(base.replace(b"= 3", b"= 4")) != d
    assert _digest(base.replace(b"import os", b"import sys")) != d
    assert _digest(base + b"print('x')\n") != d


def test_docstrings_comments_and_line_numbers_do_not_move_the_id():
    base = b'def helper():\n    "old"\n    return 1\n\ndef index_article():\n    return helper()\n'
    d = _digest(base)
    edited = b'# a comment\n\n\ndef helper():\n    "new words"\n    return 1  # trailing\n\ndef index_article():\n    return helper()\n'
    assert _digest(edited) == d
    assert _digest(base.replace(b"return 1", b"return 2")) != d


def test_the_code_digest_follows_the_narrowing(monkeypatch):
    real = _source()
    reads = {"data": real}
    orig = ei._read

    def fake(rel):
        return reads["data"] if rel == REL else orig(rel)

    monkeypatch.setattr(ei, "_read", fake)
    compute = ei.code_digest.__wrapped__
    before = compute()
    reads["data"] = real + b"\n\ndef _a_new_drain():\n    return 1\n"  # unreachable addition
    assert compute() == before
    reads["data"] = _mutate(real, "index_article")  # reachable change
    assert compute() != before


@pytest.mark.parametrize(
    "source",
    [
        "def index_article():\n    return globals()['x']\n",
        "def index_article(name):\n    return getattr(object(), name)\n",
        "def index_article():\n    import json\n    from src.analytics.store import x\n",
        "def index_article():\n    from .store import x\n",
        "def index_article():\n    __import__('os')\n",
        "def index_article():\n    return eval('1')\n",
        "def helper():\n    return 1\ndef helper():\n    return 2\ndef index_article():\n    return helper()\n",
        "def other():\n    return 1\n",
        "def index_article(:\n",
    ],
)
def test_every_doubt_keeps_the_whole_file(source):
    assert _digest(source) is None


def test_a_constant_getattr_name_joins_the_walk():
    base = "def hidden():\n    return 1\ndef index_article(o):\n    return getattr(o, 'hidden')\n"
    d = _digest(base)
    assert d is not None
    assert _digest(base.replace("return 1", "return 2")) != d


def test_an_engine_module_that_imports_the_file_by_name_adds_a_root(tmp_path, monkeypatch):
    other = b"from src.analytics.store import used_by_engine\n"
    orig = ei._read
    monkeypatch.setattr(ei, "ENGINE_MODULES", (*ei.ENGINE_MODULES, "src/fake_engine_user.py"))
    monkeypatch.setattr(ei, "_read", lambda rel: other if rel == "src/fake_engine_user.py" else orig(rel))
    assert "used_by_engine" in (ei._names_other_engine_modules_take_from(REL) or frozenset())
    src = "def used_by_engine():\n    return 1\ndef index_article():\n    return 0\n"
    plain = _digest(src)
    with_root = _digest(src, extra_roots=frozenset({"used_by_engine"}))
    assert plain != with_root  # the extra root pulls the function into the identity


def test_a_caller_of_the_root_is_in_the_identity():
    base = "def index_article(country):\n    return country\ndef drain():\n    return index_article('de')\ndef unrelated():\n    return 1\n"
    d = _digest(base)
    assert d is not None
    assert _digest(base.replace("'de'", "'fr'")) != d  # the caller picks the argument
    assert _digest(base.replace("return 1", "return 2")) == d


def test_a_name_used_by_a_toplevel_statement_is_in_the_identity():
    base = "def h():\n    return 1\n_TABLE = {'k': h}\ndef index_article():\n    return _TABLE['k']()\n"
    d = _digest(base)
    assert d is not None
    assert _digest(base.replace("return 1", "return 2")) != d
    alias = "def h():\n    return 1\ntry:\n    from x import f\nexcept ImportError:\n    def f():\n        return h()\ndef index_article():\n    return f()\n"
    assert _digest(alias.replace("return 1", "return 2")) != _digest(alias)


def test_a_toplevel_import_of_a_module_that_imports_the_file_keeps_the_whole_file(monkeypatch):
    orig = ei._read
    monkeypatch.setattr(ei, "_read", lambda rel: b"from src.analytics.store import helper\n" if rel == "src/fake_back.py" else orig(rel))
    assert ei._repo_module_refers_to("src.fake_back", OWN)
    assert _digest("from src.fake_back import x\ndef index_article():\n    return x\n") is None


def test_relative_imports_resolve_against_the_importing_file():
    assert ei._absolute("src/services/__init__.py", 1, "duckduckgo") == "src.services.duckduckgo"
    assert ei._absolute("src/analytics/store.py", 1, "extract") == "src.analytics.extract"
    assert ei._absolute("src/analytics/store.py", 2, "catalog") == "src.catalog"
    assert ei._absolute("src/x.py", 0, "os.path") == "os.path"


def test_reindex_parallel_is_part_of_the_engine():
    # it computes the terms, sentiment and when/where/who a re-index hands to index_article as precomputed values
    assert "src/analytics/reindex_parallel.py" in ei.ENGINE_MODULES


def test_no_module_a_pass_loads_imports_the_narrowed_file():
    """The narrowing assumes nothing that RUNS during a pass calls back into store.py by name. The import graph is too connected to
    prove it statically, so prove it dynamically: load a real pass in a fresh interpreter and require that none of the repo
    modules it executed (store.py aside) imports store.py, in any form, at any depth."""
    from tests.test_index_engine_stamp import _probe

    loaded = _probe()["modules"]
    offenders = [m for m in loaded if m != OWN and ei._repo_module_refers_to(m, OWN)]
    assert not offenders, f"a module a pass executes imports store.py, so the narrowed identity may under-include: {offenders}"


def test_a_caller_of_a_caller_is_in_the_identity():
    """What calls the caller chooses the arguments it passes on: ``outer -> mid -> index_article``."""
    base = "def index_article(a):\n    return a\n\ndef mid(x):\n    return index_article(x)\n\ndef outer():\n    return mid({})\n"
    assert _digest(base) is not None
    assert _digest(base) != _digest(base.replace("mid({})", "mid({1})"))


def test_the_real_batch_driver_and_public_wrapper_are_in_the_identity():
    """The scope="keywords" mutation: reindex_all_batch decides the scope every article is indexed with."""
    src = _source().decode()
    fn = python_function_source(src, "reindex_all_batch")
    assert "scope=scope," in fn
    mutated = src.replace(fn, fn.replace("scope=scope,", 'scope="keywords",', 1), 1)
    assert mutated != src
    assert _digest(_source()) is not None
    assert _digest(mutated) != _digest(src)
    wrapper = src.replace("def reindex_articles(*args: Any, **kwargs: Any) -> dict:", "def reindex_articles(*args: Any, **kwargs: Any) -> dict:\n    _wrapper_mutant_ = 1", 1)
    assert wrapper != src
    assert _digest(wrapper) != _digest(src)


@pytest.mark.parametrize(
    "extra",
    [
        "def setx():\n    global _X\n    _X = 3\n",
        "_MODE = {}\ndef setter():\n    _MODE['k'] = 2\n",
        "class Cfg:\n    w = 1\ndef tweak():\n    Cfg.w = 3\n",
        "f = index_article\ndef via_alias():\n    return f(1)\n",
        "_CFG = {}\ndef tweak():\n    _CFG.update(k=2)\n",
        "_S = set()\ndef tweak():\n    _S.add('x')\n",
        "class Cfg:\n    w = 1\ndef tweak():\n    setattr(Cfg, 'w', 3)\n",
        "_REG = []\ndef register(f):\n    _REG.append(f)\n    return f\n@register\ndef plugin(a):\n    return a + 1\n",
    ],
)
def test_state_or_alias_the_walk_cannot_follow_keeps_the_whole_file(extra):
    """A function nothing reachable names can rebind module state; an alias hides its callers: both fall back to the whole file."""
    base = "_X = 1\ndef index_article(a):\n    return a + _X\n"
    assert _digest(base) is not None
    assert _digest(base + extra) is None


def test_a_nonlocal_in_a_nested_function_does_not_defeat_the_narrowing():
    src = "def index_article(a):\n    n = 0\n    def bump():\n        nonlocal n\n        n += 1\n    bump()\n    return n\n"
    assert _digest(src) is not None
