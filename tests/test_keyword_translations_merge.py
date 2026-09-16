"""The tentative keyword-translation table rides the backup (Q404 🔒 = a, gate row K).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``S04-06`` owns the writers; this slice owns the table, the migration and the merge
handler, so the format bump carries it and the writers land on a schema that already
restores. The merge is driven into a DIFFERENT corpus, because a self-restore sees every
row as a duplicate and never runs the INSERT.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import Base, KeywordTranslation  # noqa: E402

_BATCH_META = {
    "artifact_kind": "oo-backup-3",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _tr(term="chat", src="fr", tgt="en", text="cat", model="m1", pv="kw-translate-v1"):
    return KeywordTranslation(
        term=term, source_lang=src, target_lang=tgt, text=text,
        model=model, prompt_version=pv, created_at=_T0,
    )


def test_a_translation_survives_a_merge_into_a_fresh_corpus(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_tr())
        s.commit()
    _corpus(working)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = s.query(KeywordTranslation).one()
    assert (got.term, got.source_lang, got.target_lang, got.text) == ("chat", "fr", "en", "cat")
    assert (got.model, got.prompt_version) == ("m1", "kw-translate-v1")
    assert counts["keyword_translations"]["new"] == 1


def test_the_same_row_arriving_twice_is_a_duplicate_not_a_second_row(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_tr())
        s.commit()
    with _corpus(working)() as s:
        s.add(_tr())
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert s.query(KeywordTranslation).count() == 1
    assert counts["keyword_translations"]["new"] == 0
    assert counts["keyword_translations"]["duplicate"] == 1


def test_two_MODELS_answering_the_same_pair_both_survive(tmp_path):
    """The ruled identity is the FULL tuple, the ``stat_figures`` vintage shape: a
    different model is a different measurement, and collapsing them would pick a winner
    between two answers nobody compared."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_tr(model="m2", text="feline"))
        s.commit()
    with _corpus(working)() as s:
        s.add(_tr(model="m1", text="cat"))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = {(t.model, t.text) for t in s.query(KeywordTranslation).all()}
    assert got == {("m1", "cat"), ("m2", "feline")}


def test_a_new_PROMPT_VERSION_is_a_new_row(tmp_path):
    """Half the provenance of a value the UI must label "≈": a translation is shown to
    a reader AS text, so which prompt produced it is what makes the label checkable."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_tr(pv="kw-translate-v2", text="feline"))
        s.commit()
    with _corpus(working)() as s:
        s.add(_tr(pv="kw-translate-v1", text="cat"))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert s.query(KeywordTranslation).count() == 2


def test_an_incoming_row_NEVER_replaces_a_local_one(tmp_path):
    """With the full tuple as the key the insert is a pure dedupe: it can add, it can
    never overwrite. A fixture where the two agree on the key and DISAGREE on the text
    is the only one that can tell the difference."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_tr(text="INCOMING"))
        s.commit()
    with _corpus(working)() as s:
        s.add(_tr(text="LOCAL"))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert s.query(KeywordTranslation).one().text == "LOCAL"
    # ...AND the handler actually looked. Without this the test passes unchanged if the
    # merge step for this table is deleted outright: the pre-existing LOCAL row would
    # still read "LOCAL", so "never overwrote" and "never ran" are the same observation.
    assert counts["keyword_translations"]["duplicate"] == 1, (
        "the incoming row was not even RECOGNISED as a duplicate; this test cannot tell "
        "'refused to overwrite' from 'did nothing at all'"
    )


def test_a_row_with_NULL_model_and_prompt_is_not_re_inserted_every_restore(tmp_path):
    """``x = NULL`` is NULL in SQL, so an un-COALESCEd key would read every row with a
    null model as "not present" and add a copy on every single restore -- the exact
    duplicate this whole slice exists to prevent, one table over."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        s.add(_tr(model=None, pv=None))
        s.commit()
    with _corpus(working)() as s:
        s.add(_tr(model=None, pv=None))
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        assert s.query(KeywordTranslation).count() == 1
    assert counts["keyword_translations"]["new"] == 0


def test_the_table_is_registered_as_handled():
    from src.backup.merge import _MERGE_HANDLED

    assert "keyword_translations" in _MERGE_HANDLED


def test_the_schema_states_the_cross_corpus_identity():
    """The 2026-08-03 owed-tables rule: an identity the schema cannot answer must not
    have one invented silently. Here the schema answers it, so the guard is that the
    constraint really carries all five columns."""
    uq = [
        c for c in KeywordTranslation.__table__.constraints
        if getattr(c, "name", None) == "uq_keyword_translation"
    ]
    assert uq, "uq_keyword_translation is missing; the merge key would be a convention"
    assert {c.name for c in uq[0].columns} == {
        "term", "source_lang", "target_lang", "model", "prompt_version"
    }


def test_nothing_in_the_keyword_index_reads_this_table():
    """"Never the trusted index" is a property, not a promise in a docstring. The table
    is brand new, so the honest guard is that its only readers today are the definition
    and the merge handler -- a future reader in the analytics path has to argue for
    itself rather than arrive silently.

    PARSED, NOT GREPPED. The format-bump comment in ``artifact.py`` NAMES the table to
    explain why the format moved, and a substring search duly reported that comment as
    a reader (it did, on this guard's first run). The recorded repair is not to reword
    the comment -- it is what a future session reads before deciding the table is
    unused -- but to scope the match to the syntactic form a real reference takes: an
    identifier, or a string literal that is not a docstring."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    hits = set()
    for path in sorted((root / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "KeywordTranslation" not in text and "keyword_translations" not in text:
            continue
        tree = ast.parse(text)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            named = (
                (isinstance(node, ast.Name) and node.id == "KeywordTranslation")
                or (isinstance(node, ast.Attribute) and node.attr == "KeywordTranslation")
                or (isinstance(node, ast.alias) and node.name == "KeywordTranslation")
                or (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "keyword_translations" in node.value
                    and id(node) not in docstrings
                )
            )
            if named:
                hits.add(str(path.relative_to(root)))
                break
    allowed = {
        "src/database/models.py",          # the definition
        "src/backup/merge.py",             # the merge handler
    }
    assert hits <= allowed, (
        f"keyword_translations gained a reader outside the backup engine: "
        f"{sorted(hits - allowed)}. That is S04-06's slice, and it owes the "
        "tentative-tier label wherever it renders one."
    )
    assert hits == allowed, (
        f"the guard found no reference in {sorted(allowed - hits)} -- it is looking in "
        "the wrong place, and an empty search satisfies the assertion above for free"
    )


# --------------------------------------------------------------------------- #
#  The schema enforces the identity it declares
# --------------------------------------------------------------------------- #
def test_the_UNIQUE_constraint_alone_does_NOT_cover_a_null_provenance(tmp_path):
    """The MEASUREMENT behind the extra index, kept as a test so the reason survives.

    In SQLite a UNIQUE constraint treats NULL as distinct from NULL, so
    ``uq_keyword_translation`` stops nothing at all when ``model`` and
    ``prompt_version`` are unset -- and they are nullable by design. This pins the
    SQLite semantics themselves, so if they ever changed, the guard below would be
    understood as redundant rather than mysteriously still passing."""
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, term TEXT, model TEXT,"
        " CONSTRAINT uq UNIQUE (term, model))"
    )
    for _ in range(2):
        con.execute("INSERT OR IGNORE INTO t (term, model) VALUES ('x', NULL)")
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2, (
        "SQLite now treats NULL as equal in a UNIQUE constraint; re-check whether "
        "uq_keyword_translation_nullsafe is still needed"
    )


def test_a_null_provenance_duplicate_is_REFUSED_by_the_schema(tmp_path):
    """What the plain constraint cannot do, the expression index does -- so the DB
    enforces the same five-column identity the merge handler COALESCEs, and ``S04-06``'s
    writer cannot be silently non-idempotent by using the obvious idiom."""
    import sqlite3

    db = tmp_path / "kt.db"
    _corpus(db)
    con = sqlite3.connect(db)
    for text_ in ("first", "second-DUPLICATE"):
        con.execute(
            "INSERT OR IGNORE INTO keyword_translations"
            " (term, source_lang, target_lang, text, model, prompt_version)"
            " VALUES (?,?,?,?,NULL,NULL)",
            ("maison", "fr", "en", text_),
        )
    con.commit()
    rows = con.execute("SELECT text FROM keyword_translations").fetchall()
    assert rows == [("first",)], (
        f"a NULL-provenance duplicate was stored: {rows}. The schema's declared "
        "identity and the merge key disagree again"
    )


def test_a_null_keyed_duplicate_PAIR_does_not_cross_into_a_clean_corpus(tmp_path):
    """The restore half of the same fact, and the one that matters for data safety: a
    corpus written before the index existed could hold such a pair, and a merge must
    CONTAIN it rather than spread it. Driven by dropping the index on the staged side
    only, which is exactly what such an older corpus looks like."""
    import sqlite3

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    _corpus(staged)
    _corpus(working)
    raw = sqlite3.connect(staged)
    raw.execute("DROP INDEX IF EXISTS uq_keyword_translation_nullsafe")
    for text_ in ("river-v1", "river-v2-DUPLICATE"):
        raw.execute(
            "INSERT INTO keyword_translations"
            " (term, source_lang, target_lang, text, model, prompt_version)"
            " VALUES (?,?,?,?,NULL,NULL)",
            ("riviere", "fr", "en", text_),
        )
    raw.commit()
    assert raw.execute("SELECT COUNT(*) FROM keyword_translations").fetchone()[0] == 2
    raw.close()

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        got = [t.text for t in s.query(KeywordTranslation).all()]
    assert got == ["river-v1"], (
        f"the staged corpus's own duplicate crossed the boundary: {got}"
    )


def test_the_nullsafe_index_is_in_BOTH_the_model_and_the_migration():
    """It has to be in the MODEL, not only the migration: ``Base.metadata.create_all``
    makes this table at boot before any stamp moves, and the migration's own
    already-exists guard then returns early -- so an index declared only in the
    migration would be missing on the common path, which is the one every fresh install
    takes."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    names = {i.name for i in KeywordTranslation.__table__.indexes}
    assert "uq_keyword_translation_nullsafe" in names, names
    idx = next(i for i in KeywordTranslation.__table__.indexes
               if i.name == "uq_keyword_translation_nullsafe")
    assert idx.unique, "the null-safe index is not UNIQUE, so it enforces nothing"

    mig = (root / "migrations" / "versions"
           / "5adfcc0ed33e_keyword_translations.py").read_text(encoding="utf-8")
    assert "uq_keyword_translation_nullsafe" in mig, (
        "an existing database would never gain the index the model now declares"
    )
    assert "_has_table" in mig, (
        "the migration lost its already-exists guard; measured, `alembic upgrade head` "
        "over a create_all-made table dies with 'table already exists' and the RESTORE "
        "path (which never calls create_all) would then fail to restore that artifact"
    )
