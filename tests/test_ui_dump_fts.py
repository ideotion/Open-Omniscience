"""
Wave 3 H — a Settings → Wikipedia full-text-search-over-dumps surface.

The "Read a page" box searched dump TITLES only; this dedicated box searches downloaded
dump BODIES via GET /api/wiki/dumps/fts-search, with index build/status/cancel/clear via
/api/wiki/dumps/index. Hits open in the local dump reader (invariant #6: local first);
an unbuilt index degrades to an honest empty state. This is a dedicated surface — it does
NOT touch the omnibar _wiki_group (Session G's fold).

Browser-unverified per fork-3 — node-checked + grep-guarded here.
"""

from __future__ import annotations

from tests.test_repo_invariants import _ui_source


def test_dump_fts_box_and_controls_exist():
    ui = _ui_source()
    for el in ('id="dumpfts-q"', 'id="dumpfts-out"', 'id="dumpfts-index"',
               'id="dumpfts-build-wiki"', 'id="dumpfts-wiki"'):
        assert el in ui, f"the dump full-text-search box needs {el}"


def test_dump_fts_functions_and_endpoints_wired():
    ui = _ui_source()
    for fn in ("dumpFtsSearch", "dumpFtsBuild", "dumpFtsCancel", "dumpFtsClear",
               "dumpFtsOpen", "loadDumpIndexStatus"):
        assert fn in ui, f"the dump FTS handler {fn} must exist"
    assert "/api/wiki/dumps/fts-search" in ui, "search must hit the fts-search endpoint"
    assert "/api/wiki/dumps/index" in ui, "index status/build/clear must hit the index endpoint"
    assert "/api/wiki/dumps/index/cancel" in ui, "cancel must hit the index/cancel endpoint"


def test_dump_fts_hits_open_in_the_local_reader():
    ui = _ui_source()
    # dumpFtsOpen reuses the existing local dump reader (dumpReadPage over #dumpread-*),
    # never a bare external jump — invariant #6.
    assert "dumpReadPage()" in ui, "a hit must open via the local dump reader"
    assert 'dumpFtsOpen(' in ui, "hits must call dumpFtsOpen to open the local reader"


def test_dump_fts_has_an_honest_no_index_empty_state():
    ui = _ui_source()
    assert '"no-index"' in ui or "'no-index'" in ui, "an unbuilt index must be handled honestly"


def test_dump_fts_status_loads_with_the_wikipedia_settings():
    ui = _ui_source()
    # loadWikiDumps (the Wikipedia dumps onShow) must also refresh the FTS index status.
    assert "loadDumpIndexStatus();" in ui, "the index status must load with the dumps panel"
