"""Row 439: the restore converts country codes WITHOUT writing the staged copy, and the working copy comes out exactly as before.

Before row 439 the merge's first step rewrote the staged copy in place (``normalise_staged_country_codes``), so every pre-0.5
backup restored into a new install waited for the staged copy's whole integrity walk (R834: nothing writes ``inc`` before the
verdict). The step now decides the conversion in memory (``plan_staged_country_codes``) and the copy steps read it.

THE PROPERTY: for any staged corpus, the working copy a merge leaves is the same, row for row and byte for byte in every
column, as the one the in-place conversion left; the report says the same thing; and the staged file is byte-identical
afterwards. Shown against the old step itself (kept in ``country_codes``), over corpora that mix both forms, case variants,
codes the converter refuses, empty strings and NULLs, and law documents whose conversion collides on (jurisdiction, url).
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from src.backup import merge as merge_mod  # noqa: E402
from src.backup.country_codes import normalise_staged_country_codes  # noqa: E402
from src.backup.merge import merge_corpus  # noqa: E402
from src.database import country_form as cf  # noqa: E402
from src.database.models import Base  # noqa: E402
from tests._app_engine import app_sqlite_engine  # noqa: E402

_META = {"artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0", "alembic_rev": "head", "manifest": None}

#: Every kind of value a country column holds in the field: both forms and their case variants, the app's own non-ISO law codes,
#: aggregates and junk the converter refuses, words, a sub-national code, the empty string and NULL.
_CODES = ["fr", "FR", "FRA", "fra", "gb", "GB", "GBR", "uk", "de", "DEU", "eu", "EUU", "int", "WLD", "zz", "xx1", "france",
          "us-ca", "", None]
_LAW_CODES = ["fr", "FR", "FRA", "fra", "gb", "GB", "GBR", "gbr", "uk", "eu", "int", "france", "us-ca"]


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("cc439") / "template.db"
    engine = app_sqlite_engine(path, future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


def _fill(path: Path, rng: random.Random, form: str, *, n: int, tag: str) -> None:
    """A corpus in ``form`` holding ``n`` rows of every merged table with a country column, drawn from ``_CODES``; law documents on few
    urls, so two spellings of one jurisdiction land on one url and their conversion collides."""
    con = sqlite3.connect(path)
    try:
        if form == "alpha3":
            cf.write_form(con, "alpha3", by="test")
        pick = rng.choice
        src_ids = []
        for i in range(max(2, n // 3)):
            cur = con.execute(
                "INSERT INTO sources (name, domain, enabled, country) VALUES (?, ?, 1, ?)", (f"s{i}", f"s{i}.example", pick(_CODES))
            )
            src_ids.append(cur.lastrowid)
            con.execute("INSERT INTO source_metadata (source_id, country) VALUES (?, ?)", (cur.lastrowid, pick(_CODES)))
        for _ in range(n):
            h = f"h{rng.randrange(3 * n)}"  # the two sides share some articles: a duplicate adopts a NULL country
            if con.execute("SELECT 1 FROM articles WHERE hash = ?", (h,)).fetchone():
                continue
            con.execute(
                "INSERT INTO articles (url, canonical_url, source_id, title, content, hash, language, country, created_at)"
                " VALUES (?, ?, ?, 't', ?, ?, 'en', ?, '2026-01-01 00:00:00')",
                (f"https://a.example/{h}", f"https://a.example/{h}", pick(src_ids), f"body {h}", h, pick(_CODES)),
            )
        for i in range(n // 2):
            con.execute("INSERT INTO external_sources (domain, name, country) VALUES (?, 'e', ?)", (f"e{rng.randrange(n)}-{tag}{i}.example", pick(_CODES)))
            con.execute(
                "INSERT OR IGNORE INTO places (id, kind, name, country, country_alpha3) VALUES (?, 'city', ?, ?, ?)",
                (rng.randrange(1, 2 * n), f"p{i}", pick(_CODES), pick(["FRA", "GBR", None])),
            )
        urls = [f"https://law.example/{k}" for k in range(3)]
        law_ids = []
        for _ in range(n // 2):
            try:
                cur = con.execute(
                    "INSERT INTO law_documents (jurisdiction, title, url, watched, country) VALUES (?, 'Loi', ?, 1, ?)",
                    (pick(_LAW_CODES), pick(urls), pick(_CODES)),
                )
            except sqlite3.IntegrityError:
                continue  # that spelling is on that url already
            law_ids.append(cur.lastrowid)
        rev_ids = []
        for k, did in enumerate(law_ids):
            cur = con.execute("INSERT INTO law_revisions (document_id, content_hash) VALUES (?, ?)", (did, f"hash-{k % 2}"))
            rev_ids.append(cur.lastrowid)
            con.execute(
                "INSERT INTO law_revision_summaries (revision_id, summary, model, prompt_version, prompt_text, created_at)"
                " VALUES (?, ?, 'm1', 'v1', 'p', '2026-01-01 00:00:00')",
                (cur.lastrowid, f"{tag}-summary-{k}"),
            )
        docs = con.execute("SELECT jurisdiction, url FROM law_documents").fetchall()
        for k, (juris, url) in enumerate(docs[: max(1, len(docs) // 2)]):
            con.execute(
                "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
                " VALUES (1, 'law_revision_summaries', ?, 1, ?, ?, 'machine-Z', 'pending', '2026-01-01')",
                (
                    json.dumps({"jurisdiction": juris, "document_url": url, "revision_content_hash": f"hash-{k % 2}", "model": "m1"},
                               separators=(",", ":")),
                    json.dumps({"summary": f"Z-{k}", "prompt_version": "v1"}, separators=(",", ":")),
                    json.dumps({"v": 1, "kind": "model", "producer": "m1"}),
                ),
            )
        for k in range(n // 4):
            con.execute(
                "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
                " VALUES (1, 'places', ?, 1, ?, ?, 'machine-Z', 'pending', '2026-01-01')",
                (
                    json.dumps({"place_id": rng.randrange(1, 2 * n)}, separators=(",", ":")),
                    json.dumps({"name": f"q{k}", "kind": "city", "country": pick(_CODES)}, separators=(",", ":")),
                    json.dumps({"v": 1, "kind": "model", "producer": "m1"}),
                ),
            )
        # An alternate of a table whose JSON cannot hold a code (read as stored, never copied), and one unreadable row on each side of
        # that line: the copy holds only the rows that can convert, and the report still counts the whole table's unreadable rows.
        for table, identity, fields in (
            ("keyword_translations", json.dumps({"keyword_id": 1, "language": "fr"}, separators=(",", ":")), json.dumps({"text": f"{tag}-mot"})),
            ("keyword_translations", "not json", json.dumps({"text": "x"})),
            ("places", json.dumps({"place_id": 1}), "{broken"),
        ):
            con.execute(
                "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
                " VALUES (1, ?, ?, 1, ?, ?, 'machine-Z', 'pending', '2026-01-01')",
                (table, identity, fields, json.dumps({"v": 1, "kind": "model", "producer": "m1"})),
            )
        con.commit()
    finally:
        con.close()


def _old_step(con, batch_id, results) -> None:
    """The step as it was before row 439: the staged copy rewritten in place."""
    results["_country_codes"] = normalise_staged_country_codes(con, schema="inc")


def _dump(path: Path) -> dict[str, list]:
    """Every row of every table of the working copy, in rowid order. Left out: the merge's own clock, and the batch's stored report
    (compared on its own, by ``_report``, where only the method sentence may differ)."""
    con = sqlite3.connect(path)
    try:
        out: dict[str, list] = {}
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql NOT LIKE 'CREATE VIRTUAL%' ORDER BY name"
        )]
        for t in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            keep = [c for c in cols if not (t == "merge_batches" and c in ("imported_at", "counts_json")) and not (t == "metadata_alternates" and c in ("created_at", "provenance"))]
            if not keep:
                continue
            sel = ", ".join(f'"{c}"' for c in keep)
            try:
                rows = con.execute(f'SELECT {sel} FROM "{t}" ORDER BY rowid').fetchall()
            except sqlite3.OperationalError:
                rows = con.execute(f'SELECT {sel} FROM "{t}" ORDER BY 1').fetchall()
            out[t] = [tuple(_masked(v) for v in row) for row in rows]
        return out
    finally:
        con.close()


_TODAY = datetime.now(UTC).strftime("%Y-%m-%d")


def _masked(value):
    """A time the merge stamped from its own clock (this run's date) is the one value two runs may not share."""
    if isinstance(value, str) and value.startswith(_TODAY):
        return "<now>"
    if isinstance(value, str) and _TODAY in value and value.lstrip().startswith("{"):
        return "<json with now>"
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(counts: dict) -> dict:
    out = dict(counts["_country_codes"])
    out.pop("method")
    return out


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("sform, tform", [("alpha2", "alpha3"), ("alpha3", "alpha2"), ("alpha2", "alpha2"), ("alpha3", "alpha3")])
def test_the_working_copy_is_what_the_in_place_conversion_left(monkeypatch, tmp_path, template, seed, sform, tform):
    rng = random.Random(f"{seed}-{sform}-{tform}")
    src = tmp_path / "src.db"
    tgt = tmp_path / "tgt.db"
    shutil.copy(template, src)
    shutil.copy(template, tgt)
    _fill(src, rng, sform, n=24, tag="B")
    _fill(tgt, rng, tform, n=10, tag="A")
    src_old, tgt_old = tmp_path / "src-old.db", tmp_path / "tgt-old.db"
    shutil.copy(src, src_old)
    shutil.copy(tgt, tgt_old)
    before = _digest(src)

    new_counts, _ = merge_corpus(src, tgt, _META)
    assert _digest(src) == before, "the staged copy was written"

    monkeypatch.setattr(merge_mod, "_normalise_country_codes", _old_step)
    old_counts, _ = merge_corpus(src_old, tgt_old, _META)
    assert _digest(src_old) != before or not old_counts["_country_codes"].get("rows_converted"), "the old step wrote nothing to compare with"

    assert _dump(tgt) == _dump(tgt_old)
    assert _report(new_counts) == _report(old_counts)
    for key in set(old_counts) | set(new_counts):
        if key != "_country_codes":
            assert new_counts.get(key) == old_counts.get(key), key


def test_a_collision_on_jurisdiction_and_url_is_reported_and_kept_as_before(monkeypatch, tmp_path, template):
    """``gb`` and ``GBR`` of one url in a backup restored into an alpha-3 store: ``gb`` cannot become ``GBR`` (the pair would be one key),
    so it stays ``gb``, and the report names the collision -- exactly as the in-place conversion did."""
    src, tgt = tmp_path / "src.db", tmp_path / "tgt.db"
    shutil.copy(template, src)
    shutil.copy(template, tgt)
    con = sqlite3.connect(tgt)
    cf.write_form(con, "alpha3", by="test")
    con.commit()
    con.close()
    con = sqlite3.connect(src)
    for juris, url in (("gb", "https://law.example/a"), ("GBR", "https://law.example/a"), ("gb", "https://law.example/b")):
        con.execute("INSERT INTO law_documents (jurisdiction, title, url, watched) VALUES (?, 'Loi', ?, 1)", (juris, url))
    con.commit()
    con.close()
    before = _digest(src)
    counts, _ = merge_corpus(src, tgt, _META)
    assert _digest(src) == before
    report = counts["_country_codes"]
    assert [(c["column"], c["from"], c["to"]) for c in report["collisions"]] == [("law_documents.jurisdiction", "gb", "GBR")]
    assert report["converted"] == {"law_documents.jurisdiction": 1}  # the row on url b, alone
    con = sqlite3.connect(tgt)
    try:
        assert sorted(con.execute("SELECT jurisdiction, url FROM law_documents")) == [
            ("GBR", "https://law.example/a"), ("GBR", "https://law.example/b"), ("gb", "https://law.example/a")
        ]
    finally:
        con.close()


def test_a_step_run_without_the_plan_reads_the_column_as_stored(tmp_path, template):
    """``staged_country_sql`` answers the column itself where no plan was made on the connection (a handler run on its own)."""
    from src.backup.country_codes import staged_country_sql

    con = sqlite3.connect(":memory:")
    assert staged_country_sql(con, "articles", "country") == 'i."country"'
    with pytest.raises(ValueError):
        staged_country_sql(con, "articles", "title")
    with pytest.raises(ValueError):
        staged_country_sql(con, "articles", "country", alias="i; DROP")


@pytest.mark.parametrize("tform, staged, expected", [("alpha3", "fr", "FRA"), ("alpha2", "FRA", "fr"), ("alpha3", "WLD", "WLD")])
def test_a_duplicate_article_adopts_its_country_converted(tmp_path, template, tform, staged, expected):
    """A local article with no country adopts the backup's copy's, in the store's form, and the staged file is not written for it."""
    src, tgt = tmp_path / "src.db", tmp_path / "tgt.db"
    shutil.copy(template, src)
    shutil.copy(template, tgt)
    for path, country, form in ((src, staged, None), (tgt, None, tform)):
        con = sqlite3.connect(path)
        if form == "alpha3":
            cf.write_form(con, "alpha3", by="test")
        cur = con.execute("INSERT INTO sources (name, domain, enabled) VALUES ('s', 's.example', 1)")
        con.execute(
            "INSERT INTO articles (url, canonical_url, source_id, title, content, hash, language, country, created_at)"
            " VALUES ('https://s.example/1', 'https://s.example/1', ?, 't', 'body', 'h1', 'en', ?, '2026-01-01 00:00:00')",
            (cur.lastrowid, country),
        )
        con.commit()
        con.close()
    before = _digest(src)
    merge_corpus(src, tgt, _META)
    assert _digest(src) == before
    con = sqlite3.connect(tgt)
    try:
        assert con.execute("SELECT country FROM articles").fetchall() == [(expected,)]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  R825: the plan's temp tables never reach a temp FILE on an encrypted connection
# --------------------------------------------------------------------------- #
def test_on_an_encrypted_working_copy_the_plan_is_built_with_temp_store_memory(monkeypatch, tmp_path, template):
    """The spelling map, the law_documents copy and the alternates copy hold the user's codes, urls and identities; SQLCipher writes
    a FILE temp database without its codec. Asserted on the merge's own connection, at the moment the plan is built, not assumed
    from a driver default."""
    pytest.importorskip("sqlcipher3")
    import src.database.connect as connect_mod
    from src.backup import country_codes as cc

    key = "correct horse battery staple"
    src, plain, enc = tmp_path / "src.db", tmp_path / "plain.db", tmp_path / "working.db"
    shutil.copy(template, src)
    shutil.copy(template, plain)
    _fill(src, random.Random("enc"), "alpha2", n=12, tag="B")
    _fill(plain, random.Random("enc-t"), "alpha3", n=4, tag="A")
    connect_mod.reencrypt_plain_to(plain, enc, key)
    seen: list[tuple] = []
    real = cc.plan_staged_country_codes

    def spy(con, **kw):  # noqa: ANN001, ANN003, ANN202
        out = real(con, **kw)
        temp = {r[1]: r[2] for r in con.execute("PRAGMA database_list")}.get("temp")
        tables = sorted(r[0] for r in con.execute("SELECT name FROM temp.sqlite_master WHERE type = 'table' AND name LIKE 'oo_country_%'"))
        seen.append((type(con).__module__, con.execute("PRAGMA temp_store").fetchone()[0], temp, tables))
        return out

    monkeypatch.setattr(cc, "plan_staged_country_codes", spy)
    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", lambda *a, **k: None)
    before = connect_mod.get_passphrase()
    connect_mod.set_passphrase(key)
    try:
        merge_corpus(src, enc, _META)
    finally:
        connect_mod.set_passphrase(before)
    assert len(seen) == 1, seen
    module, mode, temp_file, tables = seen[0]
    assert "sqlcipher" in module
    assert mode == 2, "temp_store is not MEMORY on the encrypted merge's connection"
    assert not temp_file, f"the temp schema is backed by a file: {temp_file!r}"
    assert {"oo_country_plan", "oo_country_map", "oo_country_law_documents", "oo_country_alternates"} <= set(tables), tables


def test_the_plan_refuses_an_encrypted_connection_whose_temp_store_is_not_memory(tmp_path):
    """Fail closed: the plan does not switch temp_store itself (that drops the connection's temp tables), it refuses and says why."""
    sqlcipher3 = pytest.importorskip("sqlcipher3")
    from src.backup.country_codes import plan_staged_country_codes

    con = sqlcipher3.connect(str(tmp_path / "e.db"))
    try:
        con.execute("PRAGMA key='k'")
        con.execute("PRAGMA temp_store=FILE")
        with pytest.raises(RuntimeError, match="temp_store"):
            plan_staged_country_codes(con, schema="main")
        assert not con.execute("SELECT name FROM temp.sqlite_master").fetchall(), "a temp table was created before the refusal"
    finally:
        con.close()


def test_only_the_alternates_that_can_hold_a_code_are_copied(tmp_path, template):
    """The alternates copy is bounded by what can convert: a table whose JSON has no country key stays in the staged file only."""
    from src.backup.country_codes import plan_staged_country_codes

    src = tmp_path / "src.db"
    shutil.copy(template, src)
    _fill(src, random.Random("alt"), "alpha3", n=12, tag="B")
    con = sqlite3.connect(":memory:")
    try:
        con.execute("ATTACH DATABASE ? AS inc", (str(src),))
        cf.write_form(con, "alpha2", by="test")
        report = plan_staged_country_codes(con, schema="inc")
        copied = {r[0] for r in con.execute("SELECT DISTINCT table_name FROM temp.oo_country_alternates")}
        assert copied == {"law_revision_summaries", "places"}, copied
        total_bad = con.execute(
            "SELECT COUNT(*) FROM inc.metadata_alternates WHERE NOT json_valid(identity) OR NOT json_valid(fields)"
        ).fetchone()[0]
        assert total_bad == 2
        assert report["alternates"]["left_unreadable"] == total_bad, report["alternates"]
    finally:
        con.close()


#: Names a backup's own catalogue can carry. None of them may reach SQL text: as a plain extra column each one is ignored and the
#: restore converts as before; inside a unique key over a country column each one is refused with the restore's fixed words.
_HOSTILE = ['a"b', "a`b", "[a]", "x; DROP TABLE articles; --", "line\nbreak", "n" * 2000, "JURISDICTION_2", "Jurisdiction_2",
            "pa\u00efs\u2603", "url", "Url"]


@pytest.mark.parametrize("name", _HOSTILE)
def test_a_hostile_name_beside_the_keys_is_ignored_and_the_restore_converts(tmp_path, template, name):
    src, tgt = tmp_path / "src.db", tmp_path / "tgt.db"
    shutil.copy(template, src)
    shutil.copy(template, tgt)
    con = sqlite3.connect(src)
    q = '"' + name.replace('"', '""') + '"'
    if name.lower() != "url":
        con.execute(f"ALTER TABLE law_documents ADD COLUMN {q} TEXT")
    con.execute(f"CREATE INDEX {'"ix ' + name.replace(chr(34), chr(34) * 2) + chr(34)} ON law_documents (jurisdiction, {q})")
    con.execute("INSERT INTO law_documents (jurisdiction, title, url, watched) VALUES ('gb', 'Loi', 'https://l.example/1', 1)")
    con.commit()
    con.close()
    con = sqlite3.connect(tgt)
    cf.write_form(con, "alpha3", by="test")
    con.commit()
    con.close()
    before = _digest(src)
    counts, _ = merge_corpus(src, tgt, _META)
    assert _digest(src) == before
    assert counts["_country_codes"]["converted"] == {"law_documents.jurisdiction": 1}
    con = sqlite3.connect(tgt)
    try:
        assert con.execute("SELECT jurisdiction FROM law_documents").fetchall() == [("GBR",)]
    finally:
        con.close()


@pytest.mark.parametrize("name", [n for n in _HOSTILE if n.lower() != "url"] + ["PARTIAL", "EXPR"])
def test_a_unique_key_the_app_does_not_make_is_refused_in_fixed_words(tmp_path, template, name):
    """A unique key over a country column that this version does not declare (any extra column, a partial index, an index over an
    expression) is refused before a row moves, in the restore's fixed sentence, never with the file's own names, never uncaught."""
    from src.backup.country_codes import STAGED_KEYS_DIFFER
    from src.backup.merge import MergeError

    src, tgt = tmp_path / "src.db", tmp_path / "tgt.db"
    shutil.copy(template, src)
    shutil.copy(template, tgt)
    con = sqlite3.connect(src)
    if name == "PARTIAL":
        con.execute("CREATE UNIQUE INDEX ix_p ON law_documents (country, url) WHERE country IS NOT NULL")
    elif name == "EXPR":
        con.execute("CREATE UNIQUE INDEX ix_e ON law_documents (lower(jurisdiction), url)")
    else:
        q = '"' + name.replace('"', '""') + '"'
        con.execute(f"ALTER TABLE law_documents ADD COLUMN {q} TEXT")
        con.execute(f"CREATE UNIQUE INDEX ix_h ON law_documents (jurisdiction, {q})")
    con.execute("INSERT INTO law_documents (jurisdiction, title, url, watched) VALUES ('gb', 'Loi', 'https://l.example/1', 1)")
    con.commit()
    con.close()
    before = _digest(src), _digest(tgt)
    with pytest.raises(MergeError) as err:
        merge_corpus(src, tgt, _META)
    assert str(err.value) == STAGED_KEYS_DIFFER
    assert (_digest(src), _digest(tgt)) == before, "a refused restore wrote something"


def test_the_copy_is_built_from_the_apps_own_names_never_the_files(tmp_path, template):
    """No DDL text the plan runs carries a name read from the staged file: traced, every CREATE names only fixed identifiers."""
    from src.backup.country_codes import plan_staged_country_codes

    src = tmp_path / "src.db"
    shutil.copy(template, src)
    _fill(src, random.Random("names"), "alpha2", n=12, tag="B")
    con = sqlite3.connect(src)
    con.execute('ALTER TABLE law_documents ADD COLUMN "zz""; DROP" TEXT')
    con.commit()
    con.close()
    con = sqlite3.connect(":memory:")
    try:
        con.execute("ATTACH DATABASE ? AS inc", (str(src),))
        seen: list[str] = []
        con.set_trace_callback(seen.append)
        plan_staged_country_codes(con, schema="inc")
        ddl = [s for s in seen if s.lstrip().upper().startswith(("CREATE", "INSERT INTO TEMP"))]
        assert ddl and not any("zz" in s or "DROP" in s for s in ddl), ddl
    finally:
        con.close()
