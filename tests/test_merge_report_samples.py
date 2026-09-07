"""The restore-merge report's ``samples`` must name rows the merge actually added.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (found 2026-09-07, reproduced before it was fixed). Three merge steps --
``sources``, ``articles``, ``wiki_pages`` -- captured their example rows by re-running
the INSERT's own ``WHERE NOT EXISTS`` predicate AFTER ``_insert_tracked`` had run it.
The INSERT has just made that predicate false for exactly the rows it copied, so the
sample query returned nothing, every time, on every restore since the reports were
written. ``DomainResult.as_dict`` emits ``samples`` only when the list is non-empty, so
the key was simply absent -- and an absent examples block reads as "this merge added
nothing", which is the omitted-field-vs-a-zero confusion the honesty rules forbid.

No test covered ``samples`` at all, which is why it survived: the report was wrong in a
direction nothing asserted.

THE FIX reads back from ``merged_rows`` -- the provenance the merge already writes for
every inserted row -- so the list reports what LANDED rather than re-deriving what was
predicted to land. That also removes a second, quieter drift: the ``articles`` INSERT
additionally joins ``temp.map_sources``, so a restated predicate could name a row the
INSERT then skipped.

Both directions are pinned. A fix that reported every incoming row (rather than the new
ones) would satisfy the positive assertions and be wrong in the opposite direction, so
each positive case has a twin that merges a corpus introducing nothing at all.
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
_T0 = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _add_source(s, domain: str) -> Source:
    src = Source(name=domain, domain=domain)
    s.add(src)
    s.flush()
    return src


def _add_article(s, source: Source, *, hash_: str, title: str | None) -> None:
    s.add(Article(
        url=f"https://{source.domain}/{hash_}",
        canonical_url=f"https://{source.domain}/{hash_}",
        source_id=source.id, content=f"body {hash_}", hash=hash_,
        title=title, created_at=_T0,
    ))


def _merge(tmp_path: Path, build_staged, build_working) -> dict:
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        build_staged(s)
        s.commit()
    with _corpus(working)() as s:
        build_working(s)
        s.commit()
    results, _batch = merge_corpus(staged, working, _BATCH_META)
    return results


def _samples(results: dict, table: str) -> list[str]:
    return list(results.get(table, {}).get("samples", []))


# --------------------------------------------------------------------------- #
#  sources
# --------------------------------------------------------------------------- #
def test_source_samples_name_the_domains_the_merge_added(tmp_path):
    results = _merge(
        tmp_path,
        lambda s: [_add_source(s, d) for d in ("shared.example", "new-a.example", "new-b.example")],
        lambda s: _add_source(s, "shared.example"),
    )
    assert results["sources"]["new"] == 2
    got = _samples(results, "sources")
    assert sorted(got) == ["new-a.example", "new-b.example"], got
    # The domain that was already here is a DUPLICATE, never an example of new work.
    assert "shared.example" not in got


def test_source_samples_are_empty_when_the_merge_adds_no_source(tmp_path):
    """The negative twin. A fix that listed every INCOMING row would pass the test
    above and invent rows that never landed; only this case separates them."""
    results = _merge(
        tmp_path,
        lambda s: _add_source(s, "shared.example"),
        lambda s: _add_source(s, "shared.example"),
    )
    assert results["sources"]["new"] == 0
    assert _samples(results, "sources") == []
    # as_dict omits an empty list, so the key must be absent rather than present-and-empty.
    assert "samples" not in results["sources"]


# --------------------------------------------------------------------------- #
#  articles
# --------------------------------------------------------------------------- #
def _articles_staged(s):
    src = _add_source(s, "outlet.example")
    _add_article(s, src, hash_="h-shared", title="Already here")
    _add_article(s, src, hash_="h-new", title="Genuinely new")
    _add_article(s, src, hash_="h-blank", title=None)


def test_article_samples_name_the_titles_the_merge_added(tmp_path):
    def working(s):
        src = _add_source(s, "outlet.example")
        _add_article(s, src, hash_="h-shared", title="Already here")

    results = _merge(tmp_path, _articles_staged, working)
    assert results["articles"]["new"] == 2
    got = _samples(results, "articles")
    assert "Genuinely new" in got
    assert "Already here" not in got, "a duplicate article is not an example of new work"
    # A title-less article is still evidence the merge added something.
    assert "(untitled)" in got, got


def test_article_samples_are_empty_when_every_incoming_article_is_a_duplicate(tmp_path):
    results = _merge(tmp_path, _articles_staged, _articles_staged)
    assert results["articles"]["new"] == 0
    assert _samples(results, "articles") == []


# --------------------------------------------------------------------------- #
#  wiki pages
# --------------------------------------------------------------------------- #
def _wiki_staged(s):
    s.add(WikiPage(wiki="en", title="Shared page"))
    s.add(WikiPage(wiki="fr", title="Nouvelle page"))


def test_wiki_samples_name_the_pages_the_merge_added(tmp_path):
    results = _merge(
        tmp_path, _wiki_staged, lambda s: s.add(WikiPage(wiki="en", title="Shared page"))
    )
    assert results["wiki_pages"]["new"] == 1
    assert _samples(results, "wiki_pages") == ["fr:Nouvelle page"]


def test_wiki_samples_are_empty_when_the_merge_adds_no_page(tmp_path):
    results = _merge(tmp_path, _wiki_staged, _wiki_staged)
    assert results["wiki_pages"]["new"] == 0
    assert _samples(results, "wiki_pages") == []


# --------------------------------------------------------------------------- #
#  The shape itself
# --------------------------------------------------------------------------- #
def test_samples_are_bounded(tmp_path):
    """A sample list is a handful of EXAMPLES, never an unbounded dump of the import."""
    from src.backup.merge import _SAMPLE_LIMIT

    results = _merge(
        tmp_path,
        lambda s: [_add_source(s, f"n{i}.example") for i in range(_SAMPLE_LIMIT + 4)],
        lambda s: None,
    )
    assert results["sources"]["new"] == _SAMPLE_LIMIT + 4
    assert len(_samples(results, "sources")) == _SAMPLE_LIMIT
