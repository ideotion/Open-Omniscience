"""Every column a merge is owed must SURVIVE the merge -- not just every table.

WHY THIS EXISTS. ``tests/test_merge_completeness.py`` closed the TABLE-level hole the
2026-07-24 ``source_qualification_attempts`` bug opened. The same defect class has a
second granularity, and it was still open: an ``INSERT INTO t (cols) SELECT ...``
allowlist silently drops every column added to the model AFTER the INSERT was written.

That is worse than a missing table, because a missing table is at least COUNTED in the
restore report, while a dropped column is invisible everywhere: the row arrives, the
column is nullable, and the value is a plausible ``NULL``. Nothing errors, nothing is
reported, and a spot check of the merged corpus looks correct.

Found 2026-08-03 by parsing merge.py's INSERT statements with the AST and diffing each
against its model, then confirming behaviourally through a real ``merge_corpus`` over two
real corpora. Fourteen columns across seven tables, every one of them added after its
INSERT was written:

    articles.detected_language        the whole deduced-language channel
    articles.server_ip/_reason/_at    the captured source-IP layer, unrecoverable
    articles.content_multihash        the K1 identity seam
    articles.canon_version            the K2 identity seam
    wiki_pages.latest_text/_revid     the living-source payload
    wiki_revisions.full_text          the per-revision text, explicitly ruled stored
    law_documents.country/language    the Cambodia-law-in-French case
    law_documents.latest_text/_revid  as above
    law_revisions.full_text           as above, law side
    external_sources.discovered_via   the Q4a discovery provenance
    article_analyses.prompt_text      provenance of an AI output
    keyword_supergroup_members.ring_id  the RING marker (see its own test)

A self-restore can never reveal any of this -- every row reads as a duplicate, so no
INSERT runs at all. These tests therefore merge a populated corpus into an EMPTY one,
which is the fresh-install restore the P0.2 bar actually names.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import (  # noqa: E402
    Article,
    ArticleAnalysis,
    Base,
    ExternalSource,
    KeywordSuperGroup,
    KeywordSuperGroupMember,
    LawDocument,
    LawRevision,
    Source,
    WikiPage,
    WikiRevision,
)

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}

_T0 = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _merged(tmp_path: Path, populate) -> Path:
    """Populate a staged corpus, merge it into an EMPTY local one, return the local path."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        populate(s)
        s.commit()
    _corpus(working)
    merge_corpus(staged, working, _BATCH_META)
    return working


# --------------------------------------------------------------------------- #
#  articles -- the deduced-language channel and the source-IP layer
# --------------------------------------------------------------------------- #
def test_an_articles_deduced_language_and_source_ip_survive_the_merge(tmp_path):
    """``detected_language`` is the ENTIRE deduced-language channel: an LLM/py3langid
    reading stored beside the source-asserted ``language`` as a distinct, labelled class.
    Dropping it resets every merged article to "never detected", and the residue is
    exactly what the langdetect ride-along then re-runs at model cost.

    ``server_ip`` is worse: it is a SOCKET-TIME observation. The connection is gone, so
    nothing can recompute it -- a re-index cannot help, and neither can a re-fetch (a
    later fetch observes a later edge)."""
    def populate(s):
        src = Source(name="Le Monde", domain="lemonde.fr")
        s.add(src)
        s.flush()
        s.add(Article(
            url="https://lemonde.fr/a", canonical_url="https://lemonde.fr/a",
            source_id=src.id, title="A", content="body",
            hash="h-article-1", language="fr", detected_language="fr",
            server_ip="9.9.9.9", server_ip_reason="socket", ip_observed_at=_T0,
            content_multihash="1220abcd", canon_version="v1",
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        got = s.query(Article).filter_by(hash="h-article-1").one()
        assert got.language == "fr", "control: the merge ran at all"
        assert got.detected_language == "fr", "the deduced-language channel was dropped"
        assert got.server_ip == "9.9.9.9", "an unrecoverable socket observation was dropped"
        assert got.server_ip_reason == "socket"
        assert got.ip_observed_at is not None
        assert got.content_multihash == "1220abcd", "the K1 identity seam was dropped"
        assert got.canon_version == "v1", "the K2 identity seam was dropped"


# --------------------------------------------------------------------------- #
#  wiki + law -- the versioned-source payloads
# --------------------------------------------------------------------------- #
def test_wiki_latest_and_revision_full_text_survive_the_merge(tmp_path):
    """The maintainer ruled per-revision FULL TEXT stored (2026-06-12) precisely so past
    versions can be materialised locally; the truncated ``diff_summary`` cannot do it. A
    merge that drops ``full_text`` reinstates exactly the gap that ruling closed."""
    def populate(s):
        page = WikiPage(
            wiki="fr", title="Élection", watched=True,
            baseline_text="BASE", latest_text="THE LATEST TEXT", latest_text_revid=42,
        )
        s.add(page)
        s.flush()
        s.add(WikiRevision(
            page_id=page.id, revid=42, timestamp=_T0, full_text="THE REVISION FULL TEXT",
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        page = s.query(WikiPage).filter_by(title="Élection").one()
        assert page.baseline_text == "BASE", "control: the merge ran at all"
        assert page.latest_text == "THE LATEST TEXT"
        assert page.latest_text_revid == 42
        rev = s.query(WikiRevision).filter_by(revid=42).one()
        assert rev.full_text == "THE REVISION FULL TEXT"


def test_law_country_language_and_full_text_survive_the_merge(tmp_path):
    """``law_documents.language`` is the languages-OF-THE-LAW field -- Cambodian law
    published in French. Dropping it hands the law corpus to ``index_article`` with no
    language, so the keyword engine treats French text as unknown and the whole
    stoplist/segmenter path degrades silently."""
    def populate(s):
        doc = LawDocument(
            jurisdiction="kh", title="Code", url="https://example.kh/code",
            country="kh", language="fr", latest_text="LATEST", latest_text_revid=7,
        )
        s.add(doc)
        s.flush()
        s.add(LawRevision(
            document_id=doc.id, observed_at=_T0, content_hash="ch-1",
            full_text="REV FULL TEXT",
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        doc = s.query(LawDocument).filter_by(url="https://example.kh/code").one()
        assert doc.jurisdiction == "kh", "control: the merge ran at all"
        assert doc.country == "kh"
        assert doc.language == "fr", "the Cambodia-law-in-French case"
        assert doc.latest_text == "LATEST"
        assert doc.latest_text_revid == 7
        rev = s.query(LawRevision).filter_by(content_hash="ch-1").one()
        assert rev.full_text == "REV FULL TEXT"


# --------------------------------------------------------------------------- #
#  provenance columns
# --------------------------------------------------------------------------- #
def test_external_source_discovery_provenance_survives_the_merge(tmp_path):
    """``discovered_via`` is the Q4a ruling's whole point: WHERE a source came from. A
    merged row with it NULL is indistinguishable from one discovered by nothing."""
    def populate(s):
        s.add(ExternalSource(
            domain="example.org", name="Example", discovered_via="wikipedia",
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        got = s.query(ExternalSource).filter_by(domain="example.org").one()
        assert got.name == "Example", "control: the merge ran at all"
        assert got.discovered_via == "wikipedia"


def test_ai_analysis_prompt_text_survives_the_merge(tmp_path):
    """No AI text is shown without its origin. ``prompt_version`` alone is a label; the
    verbatim ``prompt_text`` is the record of what was actually asked."""
    def populate(s):
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        art = Article(url="https://s.example/x", canonical_url="https://s.example/x",
                      source_id=src.id, title="X", content="c", hash="h-analysis-1")
        s.add(art)
        s.flush()
        s.add(ArticleAnalysis(
            article_id=art.id, kind="summary", result="R", model="m",
            prompt_version="v2", prompt_text="THE VERBATIM PROMPT",
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        got = s.query(ArticleAnalysis).filter_by(kind="summary").one()
        assert got.prompt_version == "v2", "control: the merge ran at all"
        assert got.prompt_text == "THE VERBATIM PROMPT"


def test_a_supergroup_ring_member_stays_a_ring_after_the_merge(tmp_path):
    """The subtlest of the fourteen, and the one that reads most like the qualification
    stamp: ``ring_id`` is the MARKER distinguishing a cross-language RING member from a
    plain family member, and its own migration records "NULL ring_id = a plain family
    member" as the pre-existing meaning.

    So a dropped ``ring_id`` does not arrive as missing data -- it arrives as a
    DIFFERENT, entirely legal member kind. ``_supergroup_totals`` then takes the family
    branch, and the super-group silently stops spanning languages: the exact capability
    the super-ring model exists to provide."""
    def populate(s):
        sg = KeywordSuperGroup(name="Energy")
        s.add(sg)
        s.flush()
        s.add(KeywordSuperGroupMember(
            supergroup_id=sg.id, normalized_term="inflation", ring_id="inflation",
        ))
        s.add(KeywordSuperGroupMember(
            supergroup_id=sg.id, normalized_term="petrol", ring_id=None,
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        members = {m.normalized_term: m for m in s.query(KeywordSuperGroupMember).all()}
        assert set(members) == {"inflation", "petrol"}, "control: the merge ran at all"
        assert members["inflation"].ring_id == "inflation", (
            "a RING member arrived as a plain family member -- legal, plausible, and wrong"
        )
        assert members["petrol"].ring_id is None, (
            "and a genuine family member must NOT gain a ring id"
        )


# --------------------------------------------------------------------------- #
#  The guard that closes the class: AST-level column completeness
# --------------------------------------------------------------------------- #
_INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL)


def _insert_columns() -> dict[str, set[str]]:
    """Parse merge.py's INSERT column lists with the AST, folded across string literals.

    Deliberately NOT a grep. The SQL is built from adjacent string literals with inline
    ``# nosec`` comments between them, so a line-oriented scan sees fragments of a column
    list and reports columns that are present as missing. The parser folds the literals
    the way Python itself does, which is the only reading that matches what executes.
    """
    src = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = _INSERT.search(node.value)
            if m:
                cols = {c.strip() for c in m.group(2).split(",") if c.strip()}
                out.setdefault(m.group(1), set()).update(cols)
    return out


def test_the_ast_parser_actually_finds_the_merge_inserts() -> None:
    """The guard below is only as strong as its parser: a regex that silently matched
    nothing would make every completeness assertion pass vacuously. Pin that it reads a
    real, known INSERT with a column the code demonstrably carries."""
    inserts = _insert_columns()
    assert len(inserts) > 20, f"the parser found only {len(inserts)} INSERTs -- it is broken"
    assert "articles" in inserts
    assert "hash" in inserts["articles"], "parsed an articles INSERT with no hash column"


def test_every_model_column_is_either_merged_or_declared_omitted() -> None:
    """THE completeness check, at column granularity.

    Failing here means a column was added to a model whose merge INSERT was written
    earlier -- so a fresh-install restore drops it, silently, as a plausible NULL. Either
    add the column to the INSERT (usually right), or declare it in
    ``_MERGE_COLUMN_INTENTIONALLY_OMITTED`` with the reason it must NOT be carried.
    """
    from src.backup.merge import _MERGE_COLUMN_INTENTIONALLY_OMITTED, _MERGE_HANDLED
    from src.database.models import Base

    inserts = _insert_columns()
    undeclared: list[str] = []
    for name, table in sorted(Base.metadata.tables.items()):
        # Scope: the tables a merge actually COPIES. Every INSERT in merge.py is not a
        # merge-copy -- ``merge_batches`` gets the app's OWN local batch record via an
        # INSERT..VALUES (its counts_json/report_json are filled by later UPDATEs), and
        # reading that one as though it were a copy would report columns as dropped that
        # are written a few lines later. _MERGE_HANDLED is the exact set that is copied.
        if name not in _MERGE_HANDLED or name not in inserts:
            continue  # table-level coverage is test_merge_completeness.py's job
        for col in table.columns:
            if col.name == "id" or col.name in inserts[name]:
                continue
            if f"{name}.{col.name}" not in _MERGE_COLUMN_INTENTIONALLY_OMITTED:
                undeclared.append(f"{name}.{col.name}")

    assert not undeclared, (
        "these model columns are in no merge INSERT and are not declared as deliberate "
        f"omissions, so a fresh-install restore drops them as a plausible NULL: {undeclared}"
    )


# The parser reads string CONSTANTS, so an INSERT whose table name is interpolated
# (``f"INSERT INTO {table} ..."``) is invisible to it. That is a blind spot in the guard
# above, not an absence of risk: a column added to one of those tables would be dropped
# with nothing to catch it. Each is named here with how it IS covered, and the set is
# pinned below so a NEW dynamic INSERT cannot join it silently.
_PARSER_BLIND_SPOTS = {
    "article_keyword_association": "f-string table name; covered behaviourally below",
    "article_keywords": "f-string table name; covered behaviourally below",
    "keyword_mentions": (
        "no INSERT exists by design -- the maintainer ruled 2026-07-29 that the merge does "
        "NOT copy mentions and the post-swap re-index produces them from the article text"
    ),
}


def test_the_guards_blind_spots_are_exactly_the_declared_ones() -> None:
    """A merged table the parser cannot see is a table the column guard does not guard.

    If this fails with a new name, that table's INSERT became dynamic (or it lost its
    INSERT): either cover it behaviourally and declare it here, or make its INSERT a
    literal so the parser reads it. Silence is the one option this test removes.
    """
    from src.backup.merge import _MERGE_HANDLED

    inserts = _insert_columns()
    invisible = {t for t in _MERGE_HANDLED if t not in inserts}
    assert invisible == set(_PARSER_BLIND_SPOTS), (
        f"the column guard's blind spots changed: {sorted(invisible)} vs "
        f"{sorted(_PARSER_BLIND_SPOTS)}"
    )


def test_the_article_keyword_link_tables_carry_every_column(tmp_path):
    """The behavioural half of the blind spot, for the two tables that have one.

    Their INSERT interpolates both the table name and its column list from a literal
    tuple, so nothing static checks that tuple against the model. This does it by
    evidence instead: give every non-key column a distinctive value and require it back."""
    from src.database.models import ArticleKeyword

    def populate(s):
        src = Source(name="S", domain="link.example")
        s.add(src)
        s.flush()
        art = Article(url="https://link.example/a", canonical_url="https://link.example/a",
                      source_id=src.id, title="A", content="c", hash="h-link-1")
        s.add(art)
        from src.database.models import Keyword
        kw = Keyword(term="Sahel", normalized_term="sahel", language="en")
        s.add(kw)
        s.flush()
        s.add(ArticleKeyword(
            article_id=art.id, keyword_id=kw.id, frequency=7,
            first_position=11, last_position=22, relevance_score=0.5,
        ))

    with _corpus(_merged(tmp_path, populate))() as s:
        got = s.query(ArticleKeyword).one()
        assert got.frequency == 7, "control: the merge ran at all"
        assert got.first_position == 11
        assert got.last_position == 22
        assert got.relevance_score == 0.5
        assert got.created_at is not None


def test_every_declared_omission_states_a_reason_and_names_a_real_column() -> None:
    """A declaration with no reason is indistinguishable from the oversight it replaces,
    and one naming a renamed column silently stops guarding anything."""
    from src.backup.merge import _MERGE_COLUMN_INTENTIONALLY_OMITTED
    from src.database.models import Base

    tables = Base.metadata.tables
    for key, reason in _MERGE_COLUMN_INTENTIONALLY_OMITTED.items():
        assert reason.strip() and len(reason) > 15, f"{key}'s reason is too thin to act on"
        table_name, _, col = key.partition(".")
        assert table_name in tables, f"{key} names a table that no longer exists"
        assert col in tables[table_name].columns, f"{key} names a column that no longer exists"
