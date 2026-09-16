"""The licence lines where data leaves the machine (S04-03 S4; Q1008 = a, Q823 ⛔).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The positive property is small: a line appears when its content is present. The
negative space is the point, and it has three parts —

  * a licence line NEVER appears for content the carrier does not hold (a CC BY-SA
    line on a ZIP with no Wikipedia text is a false statement, not caution);
  * NO ODbL line and NO share-alike note exists ANYWHERE, because Q823 is a
    maintainer-only question and is unanswered;
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
    HELD_PENDING_RULING,
    OSM_PENDING_RULING,
    PendingRulingError,
    attribution_dicts,
    attribution_lines,
    files_signal,
    osm_seam_blockers,
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
def test_osm_derived_corpus_rows_REFUSE_rather_than_render_a_short_block():
    with pytest.raises(PendingRulingError) as exc:
        attribution_lines({"table:articles", "table:osm_objects"})
    msg = str(exc.value)
    assert OSM_PENDING_RULING == "Q823" and "Q823" in msg
    assert "table:osm_objects" in msg
    assert osm_seam_blockers({"table:osm_ways", "table:articles"}) == ["table:osm_ways"]


def test_a_copied_geofabrik_extract_is_not_a_blocker_and_emits_no_line():
    """Upstream ODbL bytes carried as they are, not a derived database. Refusing them
    would be answering Q823 = b, which is the maintainer's call and not this slice's."""
    sig = {files_signal("osm_regions"), "table:articles"}
    assert osm_seam_blockers(sig) == []
    assert attribution_dicts(sig) == []


def test_the_held_ruling_is_recorded_so_the_absence_reads_as_a_decision():
    assert "openstreetmap" in HELD_PENDING_RULING
    assert "Q823" in HELD_PENDING_RULING["openstreetmap"]


_OSM_LICENCE_WORDS = re.compile(r"ODbL|Open Database License|Open Database Licence|share-alike note", re.I)
_CARRIERS = (
    "src/backup/attribution.py",
    "src/backup/export_summary.py",
    "src/backup/export_folder.py",
    "src/bulletin/evidence.py",
    "src/bulletin/render.py",
    "src/bulletin/edition.py",
    "src/static/app-backup.js",
)


def test_NO_odbl_line_exists_in_any_carrier():
    """The seam, asserted across every file that can put text into an export, a
    bulletin or an evidence ZIP. A commented-out line would fail this too, which is
    intended: a line one edit away from shipping is not a stop at the seam."""
    for rel in _CARRIERS:
        lines = (_REPO / rel).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not _OSM_LICENCE_WORDS.search(line):
                continue
            # The ONE legitimate mention is the prose explaining the ruling being waited
            # on, so the words are allowed only in the NEIGHBOURHOOD of a Q823 reference
            # (a paragraph wraps, so the mention and the ruling id are rarely on one
            # line). A line anywhere else — including a commented-out one, which is a
            # single edit away from shipping — fails.
            near = "\n".join(lines[max(0, i - 8) : i + 9])
            # `OSM_PENDING_RULING` IS the ruling id — the refusal message builds its text
            # from the constant rather than repeating the literal, which is the same
            # naming and is what keeps the two from drifting apart.
            assert "Q823" in near or "OSM_PENDING_RULING" in near, f"{rel}:{i + 1}: {line.strip()}"


def test_no_carrier_emits_an_attribution_line_mentioning_openstreetmap():
    for sig in (
        signals_from_tables({"wiki_pages": 1, "law_documents": 1, "articles": 5}),
        {files_signal("osm_regions")},
    ):
        for line in attribution_dicts(sig):
            assert "openstreetmap" not in line["text"].lower()
            assert "odbl" not in line["text"].lower()


# --------------------------------------------------------------------------- #
#  S6 — exports are never scheduled (Q220 = c), a stated non-feature
# --------------------------------------------------------------------------- #
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
