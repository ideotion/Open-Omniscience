"""store.py's contribution to the engine identity is the code ``index_article`` can reach, not the file's bytes.

Why: store.py changed in 24 of ~40 commits that touched any engine file in 30 days, so the engine id changed about every 18 hours
and a backup rarely carried (R24). The narrowing must never UNDER-include: every reachable definition moves the id, and every doubt
(dynamic lookup, an import that could call back, a redefinition) falls back to the whole file.
"""

from __future__ import annotations

import ast

import pytest

from src.analytics import engine_identity as ei

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
    assert "reindex_articles" in still and "reindex_all_batch" in still
    assert len(moved) >= 5 and len(still) >= 10


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
