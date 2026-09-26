"""The 2026-09-26 click-through's row L: alpha-3 codes on every surface, name in the hover.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row L's gate clause (RELEASE_0.4_GATE, rulings Q301-Q308): every surface shows the ISO
3166-1 alpha-3 code with the localised name on hover; a non-ISO code (XKX, EUU, ANT,
INT) and a producer's published aggregate (WLD, HIC) are disclosed as what they are.
Storage stays lowercase alpha-2 -- every fix here converts at DISPLAY time.

The front-end defects whose fix is behaviour are EXECUTED in
``tests/alpha3_click_through_node_test.js`` (run from here); the rest are pinned by the
anchor table in ``tests/test_alpha3_display_surfaces.py`` or below. One test per defect
id, named for it, so a red run says which finding came back.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.stats import store
from src.stats.sdmx import StatFigure
from tests.js_source_helper import event_listener_bodies, function_body, read_static

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def _fig(area: str, *, agency: str = "worldbank", series: str = "SP.POP.TOTL") -> StatFigure:
    return StatFigure(
        agency=agency,
        series_id=series,
        ref_area=area,
        time_period="2023",
        value=1.0,
        unit="count",
        methodology_ref=None,
        adjustment=None,
        base_year=None,
        extracted_at="2026-09-26T00:00:00Z",
    )


# --------------------------------------------------------------------------- #
#  The front end, executed                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_front_end_fixes_hold_when_run():
    """L3, L6, L7, L9, L11, L13, L16, L17 -- the executed half."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "alpha3_click_through_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "alpha3_click_through_node_test.js: OK" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------- #
#  L6 -- the law-change card and the bulletin's law line                      #
# --------------------------------------------------------------------------- #


def test_l6_the_law_change_card_names_its_jurisdiction_in_alpha3(db):
    """The card printed the stored ``uk``; the law catalogue's ``uk`` is Q303's named
    case and reads ``GBR`` everywhere else. The title is a keyed frame, so it
    translates, and the signal carries the same code the title shows."""
    from src.briefing.producers import law_change

    doc = LawDocument(jurisdiction="uk", title="Test Act", url="https://uk.test/act")
    db.add(doc)
    db.commit()
    db.add(
        LawRevision(
            document_id=doc.id,
            observed_at=datetime.now(UTC),
            content_hash="h1",
            size=5000,
            delta_bytes=1500,
            flagged=True,
            flag_reasons="large_addition",
        )
    )
    db.commit()
    (card,) = law_change(db)
    assert card.title == "Law changed (GBR): Test Act"
    assert card.title_i18n == "Law changed ({jurisdiction}): {title}"
    assert card.title_vars == {"jurisdiction": "GBR", "title": "Test Act"}
    assert card.signal["jurisdiction"] == "GBR"
    assert card.evidence[0]["source"] == "GBR"
    # The card's IDENTITY is its key, not its title, so the wording change does not
    # re-surface a card someone already dismissed.
    assert card.key.startswith(f"law:{doc.id}:")


def test_l6_the_bulletin_law_line_uses_the_same_code():
    from src.bulletin.i18n import Translator
    from src.bulletin.render import _section_groups

    groups = _section_groups(
        {"law_examples": [{"jurisdiction": "uk", "title": "Test Act", "delta_bytes": 12}]},
        Translator("en"),
    )
    rows = [row for _label, items in groups for row in items]
    assert rows, groups
    subject, description = rows[0]
    assert subject == "Test Act"
    assert description.startswith("GBR"), description
    assert not description.startswith("uk"), description


# --------------------------------------------------------------------------- #
#  L10 -- language codes (Q306 = b: displayed as 639-2/T)                       #
# --------------------------------------------------------------------------- #


def test_l10_the_bulletin_prints_language_codes_in_639_2t():
    """Q306 = b's display step reaches the bulletin too: ``fra``, not the stored ``fr``."""
    from src.bulletin.i18n import Translator
    from src.bulletin.render import _article_lines

    lines = "\n".join(
        _article_lines(
            {
                "title": "x",
                "asserted": {"language": "fr"},
                "deduced": {"detected_language": "de"},
            },
            Translator("en"),
        )
    )
    assert "lang fra" in lines, lines
    assert "detected deu" in lines, lines
    assert "lang fr " not in lines + " " and "detected de " not in lines + " ", lines


# --------------------------------------------------------------------------- #
#  L8 -- the aggregate refusal names members as the screen beside it does      #
# --------------------------------------------------------------------------- #


def test_l8_the_incomplete_coverage_refusal_names_members_in_alpha3():
    from src.stats.aggregate import Member, aggregate_indicator
    from src.stats.indicators import indicator_aggregation, indicator_meta

    out = aggregate_indicator(
        indicator=indicator_meta("SP.POP.TOTL"),
        aggregation=indicator_aggregation("SP.POP.TOTL"),
        members=[Member("fr", 68.0), Member("ad", None), Member("ax", None)],
        weights=None,
        allow_incomplete=False,
    )
    refused = out["strategies"]["sum"]["refused"]
    assert "(AND, ALA)" in refused, refused
    assert "(ad, ax)" not in refused, refused
    # The PAYLOAD keeps the stored form: it is what an export quotes and a caller
    # re-requests with.
    assert out["coverage"]["missing"] == ["ad", "ax"]


# --------------------------------------------------------------------------- #
#  L9 / L13 -- a published aggregate travels with its classification          #
# --------------------------------------------------------------------------- #


def test_l9_l13_area_classification_tells_an_aggregate_from_a_country():
    assert store.area_classification("WLD") == {"area_kind": "aggregate", "area_name": "World"}
    assert store.area_classification("HIC")["area_kind"] == "aggregate"
    assert store.area_classification("FRA") == {"area_kind": "country", "area_name": None}
    assert store.area_classification("US") == {"area_kind": "country", "area_name": None}
    # Kosovo is a COUNTRY with a non-ISO code: the country cell discloses that, so it
    # must not be classified as an aggregate here.
    assert store.area_classification("XKX")["area_kind"] == "country"


def test_l13_stat_map_cells_carry_the_area_classification(db):
    store.store_figures(db, [_fig("FRA"), _fig("WLD")])
    cells = {c["ref_area"]: c for c in store.map_figures(db, series_id="SP.POP.TOTL")["cells"]}
    assert cells["WLD"]["area_kind"] == "aggregate" and cells["WLD"]["area_name"] == "World"
    assert cells["FRA"]["area_kind"] == "country" and cells["FRA"]["area_name"] is None


def test_l9_minerals_rows_carry_the_area_classification(db):
    store.store_figures(
        db,
        [
            _fig("WLD", agency="us-usgs", series="lithium:production"),
            _fig("US", agency="us-usgs", series="lithium:production"),
        ],
    )
    db.commit()
    summ = store.minerals_supply_summary(db)
    rows = {r["ref_area"]: r for c in summ["commodities"] for rs in c["measures"].values() for r in rs}
    assert rows["WLD"]["area_kind"] == "aggregate" and rows["WLD"]["area_name"] == "World"
    assert rows["US"]["area_kind"] == "country"


# --------------------------------------------------------------------------- #
#  L4 -- the Manage sources filter row at 375 px                               #
# --------------------------------------------------------------------------- #


def test_l4_the_sources_filter_row_wraps_at_phone_width():
    """Every wrapper was ``flex:1`` (basis 0), so at 375 px all seven fitted one line at
    ~13 px each and the 90 px summaries painted over one another. The fix gives the
    wrappers a real basis INSIDE the phone media query, so the row wraps."""
    html = read_static("index.html")
    assert 'class="row src-filter-row"' in html
    css = read_static("app.css")
    at = css.index(".src-filter-row > div:not(:last-child)")
    media = css.rfind("@media", 0, at)
    assert css[media : css.index("{", media)].replace(" ", "") == "@media(max-width:600px)", (
        "the rule must live in the phone media query, not change the desktop row"
    )
    rule = css[at : css.index("}", at)]
    assert re.search(r"flex:\s*1 1 130px", rule), rule


# --------------------------------------------------------------------------- #
#  L14 -- the statistics inputs and the CSV hint                               #
# --------------------------------------------------------------------------- #


def test_l14_the_examples_and_the_csv_hint_use_the_codes_the_app_shows():
    html = read_static("index.html")
    assert 'placeholder="FRA or all"' in html and 'placeholder="FR or all"' not in html
    assert 'id="statfig-view-area" placeholder="FRA"' in html
    assert "Country is a 2-letter code" not in html
    assert "<code>country_iso3</code>" in html
    # The hint says what csv_io.py DOES: the fall-back is keyed on the result, so an
    # unreadable `country` falls back too, and a disagreement is refused.
    assert "falls back to it when country is empty or unreadable" in html
    assert "refuses a row where the two disagree" in html
    assert "(e.g. FRA)" in read_static("app-map.js")


# --------------------------------------------------------------------------- #
#  L15 -- a language switch re-renders the sources table and the law tab       #
# --------------------------------------------------------------------------- #


def test_l15_the_language_switch_repaints_the_frozen_hovers():
    bodies = [
        re.sub(r"//[^\n]*", "", b)
        for b in event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    ]
    assert bodies, "no oo:langchange listener found"
    assert any(re.search(r"\bloadManagedSources\(\)", b) for b in bodies), (
        f"{len(bodies)} listener(s): none re-renders the sources TABLE (loadSources only "
        "refills the ingest <select>)"
    )
    assert any(re.search(r"\bloadLawDocs\(\)", b) and "law-docs" in b for b in bodies), (
        f"{len(bodies)} listener(s): none re-renders the law tab, guarded on it being painted"
    )
    # The minerals area hovers this batch added (L9) are baked at render time too.
    assert any(
        re.search(r"\bloadMineralsSupply\(\)", b) and "mkt-minerals-supply" in b for b in bodies
    ), f"{len(bodies)} listener(s): none re-renders the minerals table on a language switch"


# --------------------------------------------------------------------------- #
#  L17 -- the Manage sources meta line is a keyed frame                         #
# --------------------------------------------------------------------------- #


def test_l17_the_sources_count_line_is_a_keyed_frame():
    body = function_body(read_static("app-sources.js"), "loadManagedSources")
    assert 'tf("{total} source(s) · showing {from}–{to}"' in body
    assert "`${d.total} source(s)`" not in body
