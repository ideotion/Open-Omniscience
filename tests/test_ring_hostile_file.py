"""F5, end to end: a restored backup writes ``keyword_rings_local.yml`` UNPARSED (``src/backup/merge.py``), and the file is then parsed.

Before the depth guard that parse went to libyaml, which segfaults the process on a document nested ~24,000 levels deep (a 200 KB
file). Now the file is refused with a log line that names it, its rings are not read, and every reader of the ring files completes:
boot-time/query-time ring loading (``load_rings``, ``_index``, ``_multi_index``), and an index pass (the stoplist's ring exemptions
read only the SHIPPED rings, by R102, so a local file cannot change what a pass writes, and the pass must complete beside it).
The crash itself is shown by running the pre-guard loader (the C loader called directly) on the same file in a child process.
"""
from __future__ import annotations

import logging
import subprocess
import sys

import pytest
import yaml

from src.analytics import equivalence as eq
from src.analytics import extract

_DEEP = 100_000


@pytest.fixture
def hostile_local_rings(tmp_path, monkeypatch):
    local = tmp_path / "rings" / "keyword_rings_local.yml"
    local.parent.mkdir(parents=True)
    local.write_text("rings: " + "[" * _DEEP + "x" + "]" * _DEEP + "\n", encoding="utf-8")
    monkeypatch.setattr(eq, "local_rings_path", lambda: local)
    eq.invalidate_ring_caches()
    yield local
    monkeypatch.undo()
    eq.invalidate_ring_caches()


def test_ring_loading_and_an_index_pass_complete_with_a_logged_refusal_naming_the_file(hostile_local_rings, caplog):
    caplog.set_level(logging.WARNING, logger="analytics.equivalence")
    rings = eq.load_rings()
    assert rings, "the shipped rings must still load beside a refused local file"
    assert all(r.id != "x" for r in rings)
    refusals = [r.getMessage() for r in caplog.records if "keyword_rings_local.yml" in r.getMessage()]
    assert refusals and "nested too deeply" in refusals[0] and "YAMLDepthError" in refusals[0]
    assert "[[[" not in refusals[0]  # the message names the file and carries no text of it
    eq._index()
    eq._multi_index()
    extract._ring_member_exemptions.cache_clear()
    assert isinstance(extract._ring_member_exemptions(), dict)  # the index pass's ring read: shipped rings only, completes


def test_the_shipped_rings_alone_are_unchanged_by_the_hostile_local_file(hostile_local_rings):
    with_file = {r.id for r in eq.load_rings()}
    eq.invalidate_ring_caches()
    assert {r.id for r in eq.shipped_rings()} == with_file


@pytest.mark.skipif(getattr(yaml, "CSafeLoader", None) is None, reason="libyaml is not present")
def test_the_same_file_crashes_the_pre_guard_loader(hostile_local_rings):
    code = (
        "import sys, yaml\n"
        "yaml.load(open(sys.argv[1], encoding='utf-8').read(), Loader=yaml.CSafeLoader)\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code, str(hostile_local_rings)], capture_output=True, text=True, timeout=120)
    assert done.returncode != 0, "the C loader no longer crashes on this file: re-measure the bound before keeping this test"
