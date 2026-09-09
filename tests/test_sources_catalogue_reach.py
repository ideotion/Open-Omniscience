"""The source catalogue: what boot pays for it, and how much of it a filter can see.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

TWO HALVES OF ONE FINDING, both measured on the live fixture (3,618 catalogue
rows) on 2026-09-09.

HALF ONE -- THE BOOT PAYLOAD. ``GET /api/sources`` shipped 714,399 bytes on every
page load, 98.8% of all boot API bytes, to fill a ``<select>`` inside a FOLDED
Settings section. ``docs/ledger/OPEN_QUEUE.md`` (2026-09-09) recorded the
backend half as a deliberate omission and said why: capping the default would
silently truncate both callers' dropdowns, "the same silent-wrong-answer shape
the whole audit is about", so the payload question needed a FRONTEND change.
This is that change, and it does not cap anything:

  * ``loadSources`` moved out of the boot essentials into ``_ADV_LOADERS.collect``,
    the fold its ``<select>`` actually lives in -- the same "folded must not mean
    fetched" rule that section already applies to the scheduler. Boot now makes
    ZERO requests for the catalogue (browser-verified).
  * both callers ask for the three keys they read via a new ``fields=``
    projection. A projection narrows COLUMNS, never rows: every source still
    comes back, so no dropdown loses an entry. Measured 714,399 -> 299,565 bytes
    (41.9%) for ``id,name,rss_url`` and 253,969 (35.5%) for ``id,name,domain``.
  * an unknown field name is REFUSED, not dropped -- silently ignoring an
    unrecognised query parameter is the exact defect this route was fixed for a
    day earlier, and a second parameter that did it would be repeating it.

HALF TWO -- THE READ THAT COULD NOT SEE THE CATALOGUE. Two callers used the
paginated sibling at its hard ceiling, ``GET /api/sources/?limit=1000``, over a
3,618-row catalogue and then filtered CLIENT-SIDE:

  * the batch-ingest picker, which meant 2,618 sources were unreachable through
    it and narrowing the filters printed "No sources match these filters." --
    a claim about the CATALOGUE assembled from 27.6% of it. Measured on the
    fixture: country ``tn`` (9 sources) and language ``bn`` (15) exist ONLY
    beyond the first page, so both read as absent. After the fix they return 9
    and 15.
  * the analysis window's Sources sub-tab, which merged catalog metadata by
    domain and rendered "No catalog metadata on file." for any corpus source
    past the page. LATENT on this fixture (all 8 corpus sources fall inside the
    page) and structurally the same defect, so it is fixed the same way.

The route has carried whole-catalogue filters all along -- "filtering happens in
SQL BEFORE pagination (so a filter spans the whole catalogue, not just the first
page)", its own docstring -- the picker simply never used them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    function_source,
    object_literal,
    python_function_source,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# The projection, against the real route
# ---------------------------------------------------------------------------

@pytest.fixture
def catalogue_client(tmp_path, monkeypatch):
    """A TestClient over a throwaway store holding a handful of sources."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Base, Source, engine, get_session

    Base.metadata.create_all(engine)
    session = get_session()
    try:
        if session.query(Source).count() == 0:
            for i in range(5):
                session.add(
                    Source(
                        name=f"Source {i}", domain=f"s{i}.example",
                        rss_url=(f"https://s{i}.example/feed" if i % 2 == 0 else None),
                        rate_limit_ms=2000, enabled=True, priority=1, tags="news,world",
                    )
                )
            session.commit()
    finally:
        session.close()
    with TestClient(app) as client:
        yield client


def test_a_projection_narrows_the_columns_and_never_the_rows(catalogue_client) -> None:
    """The whole point: the dropdown must not lose an entry."""
    full = catalogue_client.get("/api/sources").json()
    thin = catalogue_client.get("/api/sources?fields=id,name,rss_url").json()
    assert len(thin) == len(full) > 0, "a projection must return every row"
    assert [set(r) for r in thin] == [{"id", "name", "rss_url"}] * len(thin)
    assert [r["id"] for r in thin] == [r["id"] for r in full]
    # And the un-projected default is byte-identical to what it always served.
    assert set(full[0]) == {
        "id", "name", "domain", "rss_url", "rate_limit_ms", "enabled", "priority", "tags",
    }


def test_an_unknown_field_is_refused_rather_than_dropped(catalogue_client) -> None:
    """Silently ignoring an unrecognised parameter is the defect this route was
    fixed for the day before; the refusal must name what it did not understand."""
    r = catalogue_client.get("/api/sources?fields=id,nope,name")
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "nope" in detail, detail
    assert "rate_limit_ms" in detail, "the refusal should name the fields it does serve"
    # A partially-valid list must not half-succeed.
    assert catalogue_client.get("/api/sources?fields=bogus").status_code == 400


def test_an_empty_fields_list_is_refused_rather_than_returning_empty_rows(
    catalogue_client,
) -> None:
    """``fields=`` naming nothing would otherwise return a row of ``{}`` per source
    -- a successful-looking answer carrying no answer."""
    r = catalogue_client.get("/api/sources?fields=")
    assert r.status_code == 400, r.text
    assert "named nothing" in r.json()["detail"]


def test_the_projection_allow_list_is_exactly_the_row_it_serves() -> None:
    """The allow-list IS the contract: ``fields`` can never become an arbitrary
    attribute read against the ORM row."""
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    allow = re.search(r"_SOURCE_ROW_FIELDS: tuple\[str, \.\.\.\] = \(([^)]*)\)", src, re.S)
    assert allow, "the allow-list is gone"
    names = set(re.findall(r'"([a-z_]+)"', allow.group(1)))
    body = python_function_source(src, "list_sources")
    emitted = set(re.findall(r'^\s+"([a-z_]+)": s\.', body, re.M)) | {"tags"}
    assert names == emitted, (
        f"the allow-list and the row have drifted: allow-list only {names - emitted}, "
        f"row only {emitted - names}"
    )


# ---------------------------------------------------------------------------
# The catalog facts that used to be merged in from a truncated page
# ---------------------------------------------------------------------------

def test_corpus_sources_carries_the_catalog_facts_from_the_row_it_read() -> None:
    """They ride on the query that ALREADY joins Source and groups by Source.id,
    so a corpus source can no longer be reported as having no catalogue entry
    merely because it sorted past someone else's first page."""
    src = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    body = python_function_source(src, "corpus_sources")
    for field in ("Source.country", "Source.region", "Source.language",
                  "Source.source_type", "Source.tags"):
        assert_present(body, field, why="the catalog facts must come from the joined row")
    for key in ('"country"', '"region"', '"language"', '"source_type"'):
        assert_present(body, key, why="the fact must reach the response")


def test_the_sources_subtab_no_longer_merges_a_truncated_catalogue() -> None:
    js = function_source(read_static("app-corpus.js"), "renderCorpusSources")
    assert_absent(js, "/api/sources/?limit=1000",
                  why="that ceiling IS 1000 against a 3,618-row catalogue")
    assert_present(js, "/api/insights/corpus-sources",
                   why="the corpus source list is still the source of truth here")


# ---------------------------------------------------------------------------
# Boot cost
# ---------------------------------------------------------------------------

def test_boot_does_not_pull_the_source_catalogue() -> None:
    boot = read_static("app-boot.js")
    line = next(ln for ln in boot.splitlines() if "loadHealth(); loadLlmHealth()" in ln)
    assert "loadSources()" not in line, (
        "the catalogue must not be fetched in the boot essentials; it fills a "
        f"<select> in a folded section. Boot line: {line.strip()}"
    )


def _adv_loader(name: str) -> str:
    """The CODE of one ``_ADV_LOADERS`` entry, comments stripped.

    Both halves matter, and the first two attempts at this guard got each wrong.
    Asserting over the WHOLE literal passed when the call was deleted, because
    the comment above it still said the word -- ``js_source_helper``'s own
    docstring records that exact family of green-but-blind assertion. And
    asserting over the whole literal would also pass if the call landed in the
    WRONG entry, which is the failure this test exists to catch: a loader in
    ``sources`` does not open the fold ``collect`` owns.
    """
    lit = strip_comments(object_literal(read_static("app-shell.js"), "_ADV_LOADERS"))
    m = re.search(rf"\b{name}\s*:\s*\(\s*\)\s*=>\s*", lit)
    assert m, f"_ADV_LOADERS has no {name} entry"
    rest = lit[m.end():]
    if not rest.lstrip().startswith("{"):          # single-expression arrow
        return rest.split(",\n")[0]
    start = rest.index("{")
    depth, i = 0, start
    while i < len(rest):
        if rest[i] == "{":
            depth += 1
        elif rest[i] == "}":
            depth -= 1
            if depth == 0:
                return rest[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces in the {name} loader")


def test_the_dropdown_loads_with_the_fold_that_contains_it() -> None:
    """And the panel that used to ride along on the boot call keeps its own loader:
    a panel that used to appear must not stop appearing because its data moved."""
    collect = _adv_loader("collect")
    assert "loadSources()" in collect, (
        "#ing-source lives in the Collection fold; its loader must run when THAT "
        f"fold opens. The collect loader is: {collect}"
    )
    sources = _adv_loader("sources")
    assert "loadUnmanagedLanguages()" in sources, (
        "#unmanaged-lang-panel lives in the Sources fold and used to be populated "
        "as a side effect of the boot-time loadSources(); once that call moved to "
        f"the collect fold this panel needs its own. The sources loader is: {sources}"
    )


def test_both_dropdown_callers_ask_for_only_the_keys_they_read() -> None:
    src = function_source(read_static("app-sources.js"), "loadSources")
    assert_present(src, "/api/sources?fields=id,name,rss_url",
                   why="this dropdown prints the name and filters on rss_url")
    mkt = function_source(read_static("app-markets.js"), "loadMarketConfig")
    assert_present(mkt, "/api/sources?fields=id,name,domain",
                   why="this dropdown prints name (domain) and posts the id")


# ---------------------------------------------------------------------------
# The picker: whole-catalogue filters, and a bound that is said out loud
# ---------------------------------------------------------------------------

def test_the_picker_filters_on_the_server_over_the_whole_catalogue() -> None:
    """Client-side filtering over one page reported the CATALOGUE as empty from
    27.6% of it. Measured before the fix: country ``tn`` -> 0 rows though the
    catalogue holds 9; after: 9."""
    js = read_static("app-sources.js")
    q = function_source(js, "_biQuery")
    for param in ('"q"', '"languages"', '"countries"', '"types"', '"enabled"'):
        assert_present(q, param, why="every filter must reach the SQL, not the page")
    filt = function_source(js, "_biFiltered")
    assert "BI.sources.filter" not in filt, (
        "re-filtering in the browser would put the page back between the reader "
        "and the catalogue"
    )
    html = read_static("index.html")
    for box in ("bi-search", "bi-lang", "bi-country", "bi-type", "bi-enabled"):
        m = re.search(rf'id="{box}"[^>]*>', html)
        assert m, f"{box} is gone"
        assert "reloadBatchPicker()" in m.group(0), (
            f"{box} still calls the render-only path, so its filter never leaves "
            f"the browser: {m.group(0)}"
        )


def test_the_type_box_stays_a_substring_match_resolved_against_the_catalogue() -> None:
    """The server's ``types=`` is EXACT and the box is a substring ("stock" finds
    stock_exchange). Rather than silently redefining the box, the substring is
    resolved against the catalogue's own facet list, so a substring matching no
    type at all is a TRUE empty answer about the whole catalogue."""
    js = read_static("app-sources.js")
    types = function_source(js, "_biTypes")
    assert_present(types, "/api/sources/facets",
                   why="the catalogue's own list of types is what the substring resolves against")
    q = function_source(js, "_biQuery")
    assert_present(q, "includes(type)", why="the box must stay a substring match")
    assert "return null" in q, (
        "a substring that matches no known type should short-circuit to a true "
        "empty answer rather than sending an empty types= filter"
    )


def test_a_full_page_says_so_and_a_failed_read_is_not_an_empty_one() -> None:
    """Two distinct facts that used to print as one sentence."""
    js = read_static("app-sources.js")
    render = function_source(js, "renderBatchPicker")
    assert_present(render, "BI.failed",
                   why="a failed catalogue read must not read as 'nothing matched'")
    assert_present(render, "Could not load the source catalogue.",
                   why="the failure needs its own translated sentence")
    assert_present(render, "Showing the first {n} matching sources",
                   why="an unsaid bound reads as a complete list")
    load = function_source(js, "loadBatchPicker")
    assert_present(load, "BI.capped", why="the bound has to be measured to be said")
    assert "_BI_PAGE" in js, "the page size must be one named constant, not a literal"


def test_the_three_new_strings_ship_in_all_twelve_locales() -> None:
    keys = [
        "Could not load the source catalogue.",
        "No sources match these filters.",
        "Showing the first {n} matching sources. Refine the filters to reach the rest of the catalogue.",
    ]
    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        mapping = data.get("map", data)
        for key in keys:
            assert mapping.get(key), f"{path.name} is missing {key!r}"
        # The orphan pruned in the same pass (its source reference is gone).
        assert "Stats unavailable." not in mapping, (
            f"{path.name} still carries the orphaned key"
        )
