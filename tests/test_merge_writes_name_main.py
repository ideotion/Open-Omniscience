"""Every write in ``merge.py`` names the schema it writes to.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

While a backup is attached, an unqualified table name falls through to the ATTACHED file when ``main`` lacks the table, so a write that
names no schema can land in the incoming backup (the measured case: the keyword thread's DELETE; ``tests/test_merge_main_schema.py``).
``init_db`` gives ``main`` every ``models.py`` table, so nothing reaches this in production; this file keeps it that way: the source scan
fails on a new unqualified ``INSERT`` / ``UPDATE`` / ``DELETE`` / ``REPLACE`` / ``DROP TRIGGER`` in the merge module (docstrings and
comments are not statements and are not read), and the behavioural case shows the failure it prevents.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402

_MERGE = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"

#: A statement at the START of a string: the writes the module sends. The target is read up to the next space or bracket.
_WRITE = re.compile(
    r'\s*(INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|DROP\s+TRIGGER(?:\s+IF\s+EXISTS)?)\s+("?[\w{}.]+"?)', re.I
)

#: Targets that may name no schema, each with the reason. Empty: ``temp.`` tables name theirs, and every other write names ``main``.
_UNQUALIFIED_ALLOWED: dict[str, str] = {}

_META = {
    "artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}


def _text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _writes() -> list[tuple[int, str, str]]:
    """``(line, verb, target)`` of every write statement string in the module."""
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(_MERGE.read_text(encoding="utf-8"))):
        text = _text(node)
        m = _WRITE.match(text) if text else None
        if m:
            out.append((node.lineno, " ".join(m.group(1).split()).upper(), m.group(2).strip('"')))
    return out


def test_the_scan_finds_the_writes_it_is_meant_to_guard():
    """A scan that matches nothing proves nothing: the module has dozens of writes, and the shapes below are all among them."""
    found = _writes()
    assert len(found) >= 60, len(found)
    verbs = {v for _, v, _ in found}
    assert {"INSERT INTO", "UPDATE", "DROP TRIGGER"} <= verbs, verbs
    assert any(t.startswith("temp.") for _, _, t in found), "temp tables are the exempt kind and must be seen to be exempt"
    assert any(t.startswith("main.") for _, _, t in found)
    assert any(t.startswith("main.{") for _, _, t in found), "a table named by an f-string placeholder is qualified inside it"


def test_every_write_in_the_merge_module_names_its_schema():
    bad = [
        f"merge.py:{line} {verb} {target}"
        for line, verb, target in _writes()
        if not target.startswith(("main.", "temp.")) and target not in _UNQUALIFIED_ALLOWED
    ]
    assert not bad, (
        "a write that names no schema falls through to the attached backup when main lacks the table; qualify it with `main.`:\n"
        + "\n".join(bad)
    )


def test_the_allowlist_has_no_dead_entries():
    targets = {t for _, _, t in _writes()}
    assert set(_UNQUALIFIED_ALLOWED) <= targets, "an allowlisted target no statement names any more"
    assert all(why.strip() for why in _UNQUALIFIED_ALLOWED.values())


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_bookkeeping_table_only_the_backup_has_is_never_written_to(tmp_path):
    """``merge_batches`` is created by the migrations, so every backup carries one. A corpus without it (``init_db`` makes that impossible,
    the test drops it on purpose) must make the merge FAIL, not record its batch in the incoming file."""
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        s.add(Article(url="https://s.example/1", canonical_url="https://s.example/1", source_id=src.id, title="T", content="c", hash="h1"))
        s.commit()
    with _corpus(live)() as s:
        s.commit()
    con = sqlite3.connect(live)
    try:
        con.execute("DROP TABLE merge_batches")
        con.commit()
    finally:
        con.close()
    before = _sha(inc)

    with pytest.raises(sqlite3.Error):
        merge_corpus(inc, live, _META)

    assert _sha(inc) == before, "the merge wrote into the attached backup"
