"""The licence lines where data leaves the machine (S04-03 S4; Q1008 = a, Q823 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The positive property is small: a line appears when its content is present. The
negative space is the point, and it has three parts —

  * a licence line NEVER appears for content the carrier does not hold (a CC BY-SA
    line on a ZIP with no Wikipedia text is a false statement, not caution);
  * the ODbL line exists in ONE place (the registry) and rides only on OSM-derived
    content (Q823 = a, 2026-09-29; before that ruling no such line existed anywhere and
    OSM-derived rows refused the carrier);
  * a licence is never INVENTED for content whose terms this corpus did not record
    (the law rows) — the gap is published as a gap.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.backup.attribution import (
    attribution_dicts,
    signals_from_sources,
    signals_from_tables,
)
from src.bulletin.evidence import build_evidence_archive
from src.bulletin.period import resolve_period
from src.database.models import Article, Base, Source

_REPO = Path(__file__).resolve().parents[1]
_P = resolve_period("weekly", end=date(2026, 8, 1))  # 2026-07-25 .. 2026-07-31


# --------------------------------------------------------------------------- #
#  The registry: a line appears only against a measured signal
# --------------------------------------------------------------------------- #
def test_wikipedia_text_in_the_corpus_gets_the_cc_by_sa_line():
    lines = attribution_dicts(signals_from_tables({"articles": 10, "wiki_pages": 4}))
    assert [ln["key"] for ln in lines] == ["wikipedia"]
    assert "CC BY-SA 4.0" in lines[0]["text"]
    assert "share" in lines[0]["text"].lower()  # the share-alike obligation is stated
    assert lines[0]["because"] == "table:wiki_pages"


def test_a_corpus_without_wikipedia_gets_NO_wikipedia_line():
    assert attribution_dicts(signals_from_tables({"articles": 10, "sources": 3})) == []


def test_an_EMPTY_wiki_table_is_not_a_signal():
    """A table that exists and holds nothing carries no Wikipedia text. Claiming
    otherwise is the false-statement failure the whole module exists to avoid."""
    assert attribution_dicts(signals_from_tables({"wiki_pages": 0, "wiki_revisions": 0})) == []


def test_law_rows_publish_the_GAP_and_never_invent_a_licence():
    lines = attribution_dicts(signals_from_tables({"law_documents": 3}))
    assert [ln["key"] for ln in lines] == ["law"]
    text = lines[0]["text"]
    assert "NO licence metadata" in text
    assert "official source" in text and "never a grant" in text
    # A guessed licence would be worse than the gap. None of the plausible guesses
    # (public domain, CC0, Crown copyright, OGL) may appear.
    low = text.lower()
    for invented in ("public domain", "cc0", "crown copyright", "open government licence", "ogl"):
        assert invented not in low, invented


def test_a_wikipedia_source_contributing_to_a_bulletin_is_also_a_signal():
    lines = attribution_dicts(signals_from_sources([{"domain": "fr.wikipedia.org", "source_type": "wiki"}]))
    assert [ln["key"] for ln in lines] == ["wikipedia"]


def test_a_legal_source_contributing_is_the_law_signal():
    lines = attribution_dicts(signals_from_sources([{"domain": "law.uk.local", "source_type": "legal"}]))
    assert [ln["key"] for ln in lines] == ["law"]


def test_db_ip_is_declared_but_absent_today_with_the_reason_in_the_source():
    """Q1008 names DB-IP, and no DB-IP content rides an export today: the bundled table
    lives in the package and its lookups are done at query time, never stored. The line
    is REGISTERED so it appears on its own the day that changes — the test pins that it
    is absent for a stated reason rather than forgotten."""
    assert attribution_dicts(signals_from_tables({"articles": 10})) == []
    lines = attribution_dicts({"member:geo/dbip_country_lite.csv"})
    assert [ln["key"] for ln in lines] == ["db_ip"]
    assert "DB-IP" in lines[0]["text"] and "CC BY 4.0" in lines[0]["text"]
    src = (_REPO / "src/backup/attribution.py").read_text(encoding="utf-8")
    assert "never written to a corpus row" in src


def test_the_lines_are_ordered_the_same_way_for_every_carrier():
    both = attribution_dicts(signals_from_tables({"wiki_pages": 1, "law_documents": 1}))
    assert [ln["key"] for ln in both] == ["wikipedia", "law"]


# --------------------------------------------------------------------------- #
#  The Q823 seam
# --------------------------------------------------------------------------- #
def test_osm_derived_corpus_rows_carry_the_osm_credit_and_the_odbl():
    """Q823 = a: wherever OSM data leaves the machine it carries OSM's credit and the ODbL
    line with its share-alike term. The carrier is no longer refused."""
    lines = attribution_dicts({"table:articles", "table:osm_objects"})
    assert [ln["key"] for ln in lines] == ["openstreetmap"]
    text = lines[0]["text"]
    assert "© OpenStreetMap contributors" in text and "openstreetmap.org/copyright" in text
    assert "Open Database License" in text and "odbl" in text.lower() and "alike" in text
    assert lines[0]["because"] == "table:osm_objects"


@pytest.mark.parametrize("sig", ["table:places", "table:osm_history_changes", "files:osm_regions"])
def test_every_osm_derived_signal_brings_the_line(sig):
    assert [ln["key"] for ln in attribution_dicts({sig})] == ["openstreetmap"]


def test_nothing_osm_carried_means_no_osm_line():
    """The negative space, as for every other line: an export with no OSM content says
    nothing about OSM (a table that merely starts with "osm" in another word is not one)."""
    for sig in (
        signals_from_tables({"wiki_pages": 1, "law_documents": 1, "articles": 5}),
        signals_from_tables({"places": 0, "osm_objects": 0}),
        {"table:article_mentioned_places"},
    ):
        for line in attribution_dicts(sig):
            assert "openstreetmap" not in line["text"].lower(), sig
            assert "odbl" not in line["text"].lower(), sig


_OSM_LICENCE_WORDS = re.compile(r"Open Database License|Open Database Licence|opendatacommons", re.I)
_CARRIERS = (
    "src/backup/attribution.py",
    "src/backup/export_summary.py",
    "src/backup/export_folder.py",
    "src/bulletin/evidence.py",
    "src/bulletin/render.py",
    "src/bulletin/edition.py",
    "src/analytics/claim_bundle.py",
    "src/static/app-backup.js",
    "src/static/app-claim.js",
)


def test_the_odbl_line_is_written_in_ONE_place():
    """Every carrier renders the registry's line; none spells its own. A second copy is
    how two carriers come to credit OSM differently."""
    hits = [rel for rel in _CARRIERS
            if _OSM_LICENCE_WORDS.search((_REPO / rel).read_text(encoding="utf-8"))]
    assert hits == ["src/backup/attribution.py"], hits


def test_no_scheduled_export_mechanism_exists():
    """Q220 = c: exports stay a deliberate act. Option (a) — a backlog entry — was NOT
    chosen, so there is nothing to build and nothing to park; what this pins is that
    nobody added one by drift."""
    hits = []
    for path in (_REPO / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("auto_export", "export_schedule", "scheduled_export", "schedule_export"):
            if needle in text:
                hits.append(f"{path.relative_to(_REPO)}: {needle}")
    assert not hits, hits
    # And the user-facing docs say so, so an operator does not go looking for the setting.
    manual = (_REPO / "docs/USER_MANUAL.md").read_text(encoding="utf-8")
    assert "never scheduled" in manual.lower() or "deliberate act" in manual.lower()


# --------------------------------------------------------------------------- #
#  The evidence ZIP carrier
# --------------------------------------------------------------------------- #
def _corpus(
    *, domain: str = "alpha.test", source_type: str = "news", bystander: bool = False
) -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="Alpha", domain=domain, country="fr", source_type=source_type)
    s.add(src)
    if bystander:
        # A source that EXISTS in the corpus and contributes nothing to this period.
        # Without it the test cannot tell "measured against what contributed" from
        # "measured against the corpus" — a mutation swapping one for the other passed
        # every assertion, because with one source the two sets are identical.
        s.add(Source(name="WP", domain="fr.wikipedia.org", country="fr", source_type="wiki"))
    s.flush()
    for i in range(3):
        s.add(
            Article(
                url=f"https://{domain}/{i}",
                canonical_url=f"https://{domain}/{i}",
                source_id=src.id,
                title=f"Article {i}",
                content="body",
                hash=f"{i:064d}",
                language="fr",
                published_at=datetime.fromisoformat("2026-07-27 12:00:00"),
            )
        )
    s.commit()
    return s


def _zip_members(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


def test_the_evidence_zip_carries_the_lines_that_match_ITS_sources(tmp_path):
    s = _corpus(domain="fr.wikipedia.org", source_type="wiki")
    rep = build_evidence_archive(s, {"period": _P.to_dict()}, _P, tmp_path)
    members = _zip_members(Path(rep["path"]))
    assert "ATTRIBUTION.md" in members
    assert "CC BY-SA 4.0" in members["ATTRIBUTION.md"]
    manifest = json.loads(members["manifest.json"])
    assert [ln["key"] for ln in manifest["attribution"]] == ["wikipedia"]
    assert [ln["key"] for ln in rep["attribution"]] == ["wikipedia"]
    # The member is checksummed like every other, so the block is covered by the
    # manifest's own integrity record rather than riding beside it unverified.
    assert any(m["name"] == "ATTRIBUTION.md" and m["sha256"] for m in manifest["members"])


def test_a_press_only_evidence_zip_states_that_none_apply_rather_than_naming_one(tmp_path):
    # The corpus HOLDS a Wikipedia source; none of its articles are in this period. The
    # archive must be measured against what contributed to IT, so no CC BY-SA line.
    s = _corpus(bystander=True)
    rep = build_evidence_archive(s, {"period": _P.to_dict()}, _P, tmp_path)
    members = _zip_members(Path(rep["path"]))
    body = members["ATTRIBUTION.md"]
    assert "No third-party licence line applies" in body
    assert "CC BY" not in body and "ODbL" not in body
    # "None apply" is a statement about these contents, never a redistribution licence.
    assert "research record rather than a redistribution licence" in body
    assert json.loads(members["manifest.json"])["attribution"] == []


# --------------------------------------------------------------------------- #
#  The bulletin carrier
# --------------------------------------------------------------------------- #
def test_the_bulletin_renders_the_lines_from_ITS_OWN_record():
    from src.bulletin.render import render_markdown

    edition = {
        "period": _P.to_dict(),
        "masthead": {},
        "attribution": [{"key": "wikipedia", "text": "Wikipedia text — CC BY-SA 4.0 (…).", "because": "domain:fr.wikipedia.org"}],
    }
    md = render_markdown(edition)
    assert "## Attribution" in md
    assert "CC BY-SA 4.0" in md


def test_an_edition_that_says_none_apply_and_one_that_does_not_say_are_different():
    from src.bulletin.render import render_markdown

    says_none = render_markdown({"period": _P.to_dict(), "masthead": {}, "attribution": []})
    assert "## Attribution" in says_none
    assert "No third-party licence line applies" in says_none

    # A record written before this existed carries no key at all, and renders NOTHING:
    # a heading over no lines would read as "none apply", which it never said.
    silent = render_markdown({"period": _P.to_dict(), "masthead": {}})
    assert "## Attribution" not in silent
