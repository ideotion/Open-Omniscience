# Open Omniscience - Global Intelligence Platform for Investigative Journalism
#
# Copyright (C) 2026 Ideotion
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For inquiries, contact: open-omniscience@ideotion.com
"""S05-02 S3 (Q305): the shipped configs speak the wire's alpha-3, and the loaders still hand the app its own form.

Two halves, because the rewrite is only safe if both hold:

* the CONFIGS: no ``country:`` / ``jurisdiction:`` value in ``configs/*.yml`` is left in a lowercase alpha-2 (or
  any other) spelling -- :func:`offenders` names each one by file and path, and a mutation test proves the check
  turns red when one is put back;
* the LOADERS: a config written in the shipped alpha-3 OR in an alpha-2 a user edited in reads the same, because
  the 0.4 normaliser is the net for user-edited configs and is never removed.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.countries import config_country, country_payload

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = sorted((ROOT / "configs").glob("*.yml"))
KEYS = ("country", "jurisdiction")


def _script():
    spec = importlib.util.spec_from_file_location("rewrite_config_countries", ROOT / "scripts" / "rewrite_config_countries.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rewrite_config_countries"] = mod
    spec.loader.exec_module(mod)
    return mod


def _pairs(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in KEYS and not isinstance(v, (dict, list)):
                yield path + (k,), v
            else:
                yield from _pairs(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _pairs(v, path + (i,))


def offenders(text: str) -> list[str]:
    """Every country/jurisdiction value in ``text`` that is not already the wire form, as ``path: value``.

    Read from the PARSED document, so a flow mapping (``{jurisdiction: uk, ...}``) is seen as well as a block
    line, and YAML's boolean for an unquoted ``NO`` (Norway) is an offender rather than a silent False."""
    bad = []
    for path, value in _pairs(yaml.safe_load(text)):
        if not (isinstance(value, str) and country_payload(value) == value and value == value.upper()):
            bad.append(f"{'/'.join(map(str, path))}: {value!r}")
    return bad


def test_the_configs_are_not_empty_of_countries():
    # A guard that scans nothing passes forever: pin that it sees the shipped catalogues.
    seen = {c.name: sum(1 for _ in _pairs(yaml.safe_load(c.read_text("utf-8")))) for c in CONFIGS}
    assert sum(seen.values()) > 5000, seen
    assert seen["sources.yml"] > 3000 and seen["legal_sources.yml"] > 50 and seen["world_events.yml"] > 100, seen


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: p.name)
def test_no_country_or_jurisdiction_is_left_in_an_old_spelling(config):
    bad = offenders(config.read_text("utf-8"))
    assert not bad, (
        f"{config.name}: {len(bad)} value(s) not in the wire form, first: {bad[:5]}; "
        "run `python scripts/rewrite_config_countries.py --write` (it edits only country values and proves it)"
    )


def test_the_check_reddens_by_name_when_one_alpha2_comes_back():
    """The mutation check the brief asks for: put ONE ``country: fr`` back and the check names it."""
    text = (ROOT / "configs" / "sources.yml").read_text("utf-8")
    assert offenders(text) == []
    first = re.search(r"country: [A-Z]{3}\b", text)
    mutated = text[: first.start()] + "country: fr" + text[first.end():]
    bad = offenders(mutated)
    assert len(bad) == 1 and bad[0].endswith("country: 'fr'"), bad


def test_the_check_reddens_on_an_unquoted_norway_and_on_a_flow_mapping_value():
    assert offenders("sources:\n  - {name: A, domain: a.no, country: NO}\n") == ["sources/0/country: False"]
    assert offenders("documents:\n  - {jurisdiction: uk, country: GBR}\n") == ["documents/0/jurisdiction: 'uk'"]
    assert offenders("documents:\n  - {jurisdiction: GBR, country: GBR}\n") == []


# --- the script ---------------------------------------------------------------------------------------------


def test_the_rewrite_script_has_nothing_left_to_do_and_says_so():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rewrite_config_countries.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert done.returncode == 0, (done.stdout[-800:], done.stderr[-800:])
    assert "total rewritten: 0" in done.stdout
    assert "left as written" not in done.stdout, "a value the script cannot place sits in a shipped config"


def test_the_rewrite_changes_only_country_values_and_refuses_anything_else():
    mod = _script()
    old = "# keep me\nsources:\n  - {name: 'A', domain: a.fr, country: fr, language: fr}  # trailing\n  - name: B\n    jurisdiction: uk\n"
    new, changes = mod.rewrite_text(old)
    assert new == "# keep me\nsources:\n  - {name: 'A', domain: a.fr, country: FRA, language: fr}  # trailing\n  - name: B\n    jurisdiction: GBR\n"
    assert [c["new"] for c in changes] == ["FRA", "GBR"]
    assert mod.prove_equivalent(old, new) == []
    # A rewrite that also touched a title (or any other value) is refused by name.
    assert mod.prove_equivalent(old, new.replace("name: B", "name: C"))
    # ... and so is one that turns a country into a different country.
    assert mod.prove_equivalent(old, new.replace("FRA", "DEU"))


def test_the_rewrite_leaves_prose_and_comments_alone():
    mod = _script()
    old = "# country: fr\nnotes: see jurisdiction: uk in the text\nsources:\n  - {name: A, country: fr}\n"
    new, _ = mod.rewrite_text(old)
    assert new == "# country: fr\nnotes: see jurisdiction: uk in the text\nsources:\n  - {name: A, country: FRA}\n"


def test_an_unquoted_no_is_norway_not_false():
    mod = _script()
    old = "events:\n  - {title: T, country: NO}\n"
    new, _ = mod.rewrite_text(old)
    assert yaml.safe_load(old)["events"][0]["country"] is False  # YAML 1.1: the file never said Norway
    assert yaml.safe_load(new)["events"][0]["country"] == "NOR"
    assert mod.prove_equivalent(old, new) == []


# --- the loaders: either spelling reads the same ------------------------------------------------------------


def test_config_country_reads_either_form_and_never_invents():
    assert config_country("FRA") == config_country("fr") == config_country("FR") == "fr"
    assert config_country("GBR") == "gb" and config_country("INT") == "int" and config_country("EUU") == "eu"
    assert config_country("nowhere-land") == "nowhere-land"  # unplaced: as written
    assert config_country(None) is None and config_country("") == "" and config_country(False) is False


def test_law_jurisdiction_lands_on_the_spelling_the_rows_hold():
    from src.law.catalog import law_jurisdiction

    assert [law_jurisdiction(v) for v in ("GBR", "uk", "EUU", "eu", "INT", "int", "FRA", "fr", "USA")] == [
        "uk", "uk", "eu", "eu", "int", "int", "fr", "fr", "us",
    ]


@pytest.mark.parametrize("form", ["alpha2", "alpha3"])
@pytest.mark.parametrize("spelling", ["GBR", "uk"])
def test_registering_the_law_catalogue_twice_in_either_spelling_makes_no_second_row(tmp_path, form, spelling):
    """The failure this pins: an alpha-3 ``jurisdiction`` read as is would be a second row beside the stored ``uk``
    (UNIQUE ``(jurisdiction, url)`` then fails the whole registration at boot)."""
    from src.database.country_form import writing_in
    from src.database.models import Base, LawDocument
    from src.law.catalog import register_documents

    cat = tmp_path / "legal_sources.yml"
    cat.write_text(
        "documents:\n"
        f"  - {{jurisdiction: {spelling}, title: HRA, url: 'https://example.org/hra', country: {spelling}, language: en}}\n"
        "  - {jurisdiction: FRA, title: DDHC, url: 'https://example.org/ddhc', country: FRA, language: fr}\n",
        encoding="utf-8",
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with writing_in(form), sessionmaker(bind=engine)() as s:
        first = register_documents(s, cat, tmp_path / "none.yml")
        second = register_documents(s, cat, tmp_path / "none.yml")
        rows = sorted((r.jurisdiction, r.country) for r in s.query(LawDocument).all())
    assert first["created"] == 2 and second["created"] == 0
    assert rows == [("fr", "fr"), ("uk", "gb")]


def test_a_row_stored_as_uk_is_matched_by_the_alpha3_catalogue(tmp_path):
    from src.database.country_form import writing_in
    from src.database.models import Base, LawDocument
    from src.law.catalog import register_documents

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cat = tmp_path / "c.yml"
    cat.write_text(
        "documents:\n  - {jurisdiction: GBR, title: HRA, url: 'https://example.org/hra', country: GBR, language: en}\n",
        encoding="utf-8",
    )
    with writing_in("alpha2"), sessionmaker(bind=engine)() as s:
        s.add(LawDocument(jurisdiction="uk", title="HRA", url="https://example.org/hra", category="legislation"))
        s.commit()
        out = register_documents(s, cat, tmp_path / "none.yml")
        row = s.query(LawDocument).one()
    assert out["created"] == 0 and out["healed_language"] == 1
    assert (row.jurisdiction, row.country, row.language) == ("uk", "gb", "en")


@pytest.mark.parametrize("spelling", ["FRA", "fr", "FR"])
def test_the_gazetteer_reads_a_city_in_any_spelling(tmp_path, spelling):
    from src.catalog.cities import load_cities

    f = tmp_path / "cities.yml"
    f.write_text(f"cities:\n  - {{name: Lyon, lat: 45.76, lon: 4.84, country: {spelling}}}\n", encoding="utf-8")
    assert [(c.name, c.country) for c in load_cities(f)] == [("Lyon", "fr")]


@pytest.mark.parametrize("spelling", ["FRA", "fr"])
def test_an_anchor_reads_in_any_spelling(tmp_path, monkeypatch, spelling):
    from src.timemap import anchors

    f = tmp_path / "world_timeline.yml"
    f.write_text(
        "anchors:\n  - {id: a1, title: T, date: '1789-07-14', lat: 48.85, lon: 2.35, "
        f"country: {spelling}}}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(anchors, "CATALOG_PATH", f)
    anchors._raw.cache_clear()
    anchors.load_anchors.cache_clear()
    try:
        assert [a["country"] for a in anchors.load_anchors()] == ["fr"]
    finally:
        anchors._raw.cache_clear()
        anchors.load_anchors.cache_clear()


@pytest.mark.parametrize("spelling", ["FRA", "fr"])
def test_an_event_and_a_feed_family_read_in_any_spelling(tmp_path, monkeypatch, spelling):
    from src.events import catalog as events
    from src.events import feeds

    ev = tmp_path / "world_events.yml"
    ev.write_text(
        f"events:\n  - {{title: Bastille Day, official_url: 'https://example.org', month: 7, day: 14, country: {spelling}}}\n",
        encoding="utf-8",
    )
    fam = tmp_path / "calendar_feeds.yml"
    fam.write_text(
        "families:\n  - key: f1\n    name: F\n    country: " + spelling + "\n"
        "    feeds:\n      - {id: x, url: 'https://example.org/x.ics'}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(events, "CATALOG_PATH", ev)
    monkeypatch.setattr(feeds, "CATALOG_PATH", fam)
    for fn in (events._raw, events.load_events, feeds._raw, feeds.load_families):
        fn.cache_clear()
    try:
        # these two catalogues have always been read in UPPERCASE alpha-2 (their consumers compare with .upper())
        assert [e["country"] for e in events.load_events()] == ["FR"]
        assert [f["country"] for f in feeds.load_families()] == ["FR"]
    finally:
        for fn in (events._raw, events.load_events, feeds._raw, feeds.load_families):
            fn.cache_clear()


@pytest.mark.parametrize("spelling", ["FRA", "fr"])
def test_catalog_discovery_finds_an_entry_in_either_spelling(tmp_path, monkeypatch, spelling):
    """The channel compared the catalogue's country to alpha-2 targets, so alpha-3 would have proposed nothing."""
    from src.database.models import Base
    from src.discovery import channels
    from src.ingest import seed_sources

    cat = tmp_path / "sources.yml"
    cat.write_text(
        f"sources:\n  - {{name: Le Monde, domain: lemonde.example, country: {spelling}, language: fr}}\n", encoding="utf-8"
    )
    monkeypatch.setattr(seed_sources, "DEFAULT_SOURCES_PATH", cat)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        out = channels.catalog_candidates(s, cap=10)
    assert [(d["domain"], d["evidence"]["country"]) for d in out["decisions"]] == [("lemonde.example", "fr")]


# --- the maintainer tooling that writes, reads or checks these files must follow ---------------------------------


def _tool(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"cfg_tool_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"cfg_tool_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_merged_batch_is_written_in_the_files_form_so_the_next_merge_does_not_undo_the_rewrite():
    merge = _tool("merge_source_batch")
    text = merge.render([{"name": "Le Monde (France)", "domain": "lemonde.example", "country": "fr", "language": "fr"}])
    assert yaml.safe_load(text)[0]["country"] == "FRA"
    # what it appends is exactly what the repo test accepts
    assert offenders("sources:\n" + "".join("  " + line + "\n" for line in text.splitlines())) == []


def test_the_batch_check_still_compares_a_title_country_with_the_entry_in_either_spelling():
    merge = _tool("merge_source_batch")
    entry = {"name": "Le Monde (France)", "domain": "lemonde.example", "source_type": "news", "language": "fr",
             "verified": True, "rss_url": "https://lemonde.example/rss", "last_verified": "2026-10-16", "tags": []}
    ok = [merge.check_entry({**entry, "country": c}, existing=set(), seen=set()) for c in ("fr", "FRA")]
    assert all(why is None or "states country" not in why for why in ok), ok
    why = merge.check_entry({**entry, "country": "DEU"}, existing=set(), seen=set())
    assert why and "states country" in why, why


def test_the_enrichment_and_tag_cleanup_write_alpha3():
    enrich = _tool("merge_enrichment_results")
    sources = [{"domain": "a.example", "name": "A"}]
    stats = enrich.merge(sources, [{"domain": "a.example", "country": "fr", "confidence": "high"}], min_conf="low")["stats"]
    assert stats["country_set"] == 1 and sources[0]["country"] == "FRA"
    cleanup = _tool("cleanup_source_tags")
    rows = [{"name": "B", "domain": "b.example", "tags": ["guam"]}, {"name": "C", "domain": "c.fr", "tags": []}]
    cleanup.clean(rows, do_cctld=True)
    assert [r.get("country") for r in rows] == ["GUM", "FRA"]


def test_the_legal_validator_reads_the_shipped_form_and_the_committed_catalogue_is_clean():
    vlc = _tool("validate_legal_catalog")
    assert vlc._is_wire_country("GBR") and vlc._is_wire_country("EUU") and vlc._is_wire_country("INT")
    assert not vlc._is_wire_country("gbr") and not vlc._is_wire_country("XXX") and not vlc._is_wire_country("fr")
    generated = yaml.safe_load((ROOT / "configs" / "legal_sources_generated.yml").read_text("utf-8"))
    curated = yaml.safe_load((ROOT / "configs" / "legal_sources.yml").read_text("utf-8"))
    assert vlc.validate(generated, curated)["errors"] == []


def test_the_splice_report_counts_the_shipped_catalogue_by_alpha2_whatever_the_file_holds():
    spec = importlib.util.spec_from_file_location("cfg_tool_splice", ROOT / "scripts" / "analysis" / "stage_b_splice_report.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cfg_tool_splice"] = mod
    spec.loader.exec_module(mod)
    counts = mod._shipped_country_counts()
    assert counts.get("fr", 0) > 20 and "fra" not in counts and "FRA" not in counts, sorted(counts)[:10]


def test_the_real_events_keep_their_uppercase_alpha2_and_norway_is_a_string_now():
    from src.events import catalog as events

    countries = {e["title"]: e["country"] for e in events.load_events()}
    assert all(isinstance(c, str) and c == c.upper() and len(c) in (2, 3) for c in countries.values()), {
        t: c for t, c in countries.items() if not (isinstance(c, str) and c == c.upper())
    }
    # The unquoted `NO` this event carried was YAML's boolean false: it never said Norway to a loader.
    assert countries["Norges Bank policy rate decision"] == "NO"
    assert {"US", "EU", "INT"} <= set(countries.values())
