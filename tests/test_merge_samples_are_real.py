"""Every ``samples`` list a restore report carries must hold real names.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``DomainResult.samples`` exists so a report can NAME a few of the things an import added,
beside the counts. It never did. All three collectors -- sources, articles, wiki pages --
ran their sample query AFTER their own INSERT, and each query selects the incoming rows
that do NOT yet exist locally, so by the time it ran every one of them did. The list was
empty on every import ever taken, ``as_dict`` omits an empty ``samples``, and so the field
simply never appeared: a fabricated absence, reading as "this import added nothing worth
naming".

PR #915 recorded the sources site. Measuring it found all three (2 sources, 3 articles and
2 wiki pages added; ``samples`` absent from all three), so this pins each one separately --
a guard on one site would have left the class open at the other two.

WHY THE SAMPLES HONESTLY SAY "added" AND NOT "about to be added": :func:`_new_row_samples`
reads them back out of ``merged_rows`` -- the provenance the merge already writes for every
row it inserts -- so the list reports what LANDED rather than re-deriving what was predicted
to land. (This file first fixed the ordering instead, by reading the samples BEFORE the
INSERT; that also produced correct lists here, but it restates the INSERT's own predicate,
and the ``articles`` INSERT additionally joins ``temp.map_sources``, so a restatement could
name a row the INSERT then skipped. The provenance read cannot drift from the statement, so
it is the one that survived the 2026-09-07 merge; these cases are kept because their
fixtures differ from the ones in ``test_merge_report_samples.py`` -- an empty local corpus
and a re-merge, against that file's shared-row discrimination.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Article, Base, Source, WikiPage

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_incoming(path: Path, *, n_articles: int = 3) -> None:
    with _corpus(path)() as s:
        src = Source(name="alpha", domain="alpha.example", status="unqualified")
        s.add(src)
        s.flush()
        s.add(Source(name="beta", domain="beta.example", status="unqualified"))
        for i in range(n_articles):
            s.add(Article(
                url=f"https://alpha.example/{i}",
                canonical_url=f"https://alpha.example/{i}",
                title=f"Story {i}", content="x" * 50,
                hash=f"h{i}".ljust(64, "0"), source_id=src.id, created_at=_T0,
            ))
        s.add(WikiPage(wiki="en", title="Some Page", watched=True))
        s.commit()


def _plan(tmp_path: Path, *, n_articles: int = 3) -> dict:
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _seed_incoming(staged, n_articles=n_articles)
    _corpus(working)  # an empty local corpus: everything incoming is new
    counts, _ = merge_corpus(staged, working, _BATCH_META)
    return counts


def test_sources_name_the_domains_they_added(tmp_path):
    got = _plan(tmp_path)["sources"]
    assert got["new"] == 2
    assert sorted(got.get("samples") or []) == ["alpha.example", "beta.example"]


def test_articles_name_the_titles_they_added(tmp_path):
    got = _plan(tmp_path)["articles"]
    assert got["new"] == 3
    assert sorted(got.get("samples") or []) == ["Story 0", "Story 1", "Story 2"]


def test_wiki_pages_name_the_pages_they_added(tmp_path):
    got = _plan(tmp_path)["wiki_pages"]
    assert got["new"] == 1
    assert (got.get("samples") or []) == ["en:Some Page"]


def test_a_sample_list_is_bounded_and_the_count_stays_the_number(tmp_path):
    """NEGATIVE SPACE, and the anti-capping rule: the sample list is EXAMPLES and is
    capped, so it must never be read as the total -- the count column beside it is not
    capped and must still report every row."""
    from src.backup.merge import _SAMPLE_LIMIT

    n = _SAMPLE_LIMIT + 4
    got = _plan(tmp_path, n_articles=n)["articles"]
    assert got["new"] == n, "a displayed figure is never secretly a cap"
    assert len(got["samples"]) == _SAMPLE_LIMIT


def test_a_duplicate_import_names_nothing_because_it_added_nothing(tmp_path):
    """NEGATIVE SPACE. The whole defect was an empty list where names belonged; the fix
    must not invent names where there genuinely are none. Re-merging the same corpus adds
    nothing, so every sample list must be absent -- not populated with rows that were
    already here."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _seed_incoming(staged)
    _corpus(working)
    merge_corpus(staged, working, _BATCH_META)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    for table in ("sources", "articles", "wiki_pages"):
        assert counts[table]["new"] == 0
        assert "samples" not in counts[table], (
            f"{table} named rows it did not add: a sample list must describe THIS merge"
        )


def test_the_report_renders_the_names_it_collected():
    """The other half of the dead end: the merge collected samples and nothing read them.
    A value with no reader is not a fix."""
    from src.backup.import_reports import render_import_report_markdown

    md = render_import_report_markdown({
        "committed": True,
        "plan": {
            "sources": {"new": 2, "duplicate": 0, "conflict": 0,
                        "samples": ["alpha.example", "beta.example"]},
            "articles": {"new": 1, "duplicate": 0, "conflict": 0},
        },
    })
    assert "alpha.example" in md and "beta.example" in md


def test_the_report_says_nothing_when_there_is_nothing_to_name():
    """NEGATIVE SPACE for the renderer: no heading over an empty list."""
    from src.backup.import_reports import render_import_report_markdown

    md = render_import_report_markdown({
        "committed": True,
        "plan": {"sources": {"new": 0, "duplicate": 2, "conflict": 0}},
    })
    assert "Examples of what was added" not in md
