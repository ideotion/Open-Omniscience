"""``statement_kind.is_plain_read``: the allowlist behind the release's "did anything that is not a read run here?" (WAL / disk, 2026-10-16).

The answer to an unknown statement must be NO: a wrong "no" keeps a pooled connection until the caller's own commit, a wrong "yes" lets a
rollback discard a schema change. So the table below is mostly the statements that must NOT be reads, and the reads are the forms
SQLAlchemy, the ``read_snapshot`` recipe and the diagnostics actually send.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.database import statement_kind
from src.database.statement_kind import (
    PLAIN_READ_WORDS,
    READ_ONLY_PRAGMAS,
    READ_ONLY_PRAGMAS_WITH_ARGUMENT,
    is_plain_read,
)

READS = [
    "SELECT 1",
    "select id from note where body = 'a=b'",
    "  \n\tSELECT id FROM note",
    "SELECT note.id FROM note WHERE note.id IN (?, ?)",
    "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 3) SELECT x FROM n",
    "VALUES (1), (2)",
    "EXPLAIN QUERY PLAN SELECT 1",
    "BEGIN",
    "BEGIN IMMEDIATE",
    "SAVEPOINT sa_savepoint_1",
    "RELEASE SAVEPOINT sa_savepoint_1",
    "PRAGMA page_count",
    "pragma page_size;",
    "PRAGMA main.freelist_count",
    "PRAGMA user_version",
    "PRAGMA journal_mode",
    "PRAGMA data_version",
    "PRAGMA table_info(note)",
    "PRAGMA table_xinfo('note')",
    "PRAGMA main.index_list(note)",
    "PRAGMA foreign_key_list(note)",
    "PRAGMA foreign_key_check",
    "PRAGMA quick_check",
    "PRAGMA integrity_check(10)",
    "PRAGMA cipher_version",
]

NOT_READS = [
    "",
    "   ",
    "-- a comment first\nSELECT 1",
    "/* a comment first */ SELECT 1",
    "(SELECT 1)",
    "42",
    "INSERT INTO note (body) VALUES ('x')",
    "insert or replace into note (id) values (1)",
    "REPLACE INTO note (id) VALUES (1)",
    "UPDATE note SET body = 'x'",
    "DELETE FROM note",
    "CREATE TABLE extra (id INTEGER)",
    "create index note_body on note (body)",
    "DROP TABLE spare",
    "ALTER TABLE note ADD COLUMN added TEXT",
    "REINDEX",
    "VACUUM",
    "ANALYZE",
    "ATTACH DATABASE 'x.db' AS other",
    "DETACH DATABASE other",
    "COMMIT",
    "END",
    "ROLLBACK",
    "ROLLBACK TO SAVEPOINT sa_savepoint_1",
    "PRAGMA user_version = 7",
    "PRAGMA user_version=7",
    "PRAGMA user_version(7)",
    "PRAGMA main.application_id = 1",
    "PRAGMA journal_mode = WAL",
    "PRAGMA journal_mode=DELETE",
    "PRAGMA foreign_keys = ON",
    "PRAGMA page_size = 8192",
    "PRAGMA schema_version = 99",
    "PRAGMA wal_checkpoint",
    "PRAGMA wal_checkpoint(TRUNCATE)",
    "PRAGMA optimize",
    "PRAGMA shrink_memory",
    "PRAGMA incremental_vacuum(10)",
    "PRAGMA key = 'x'",
    "PRAGMA rekey = 'x'",
    "PRAGMA cipher_migrate",
    "PRAGMA a_pragma_that_does_not_exist",
    "PRAGMA table_info('a=b')",
    "PRAGMA",
    "PRAGMA ;",
]


@pytest.mark.parametrize("statement", READS)
def test_a_plain_read_is_a_plain_read(statement):
    assert is_plain_read(statement) is True


@pytest.mark.parametrize("statement", NOT_READS)
def test_anything_that_could_change_the_database_is_not_a_plain_read(statement):
    assert is_plain_read(statement) is False


def test_the_allowlists_are_what_the_docstring_says():
    assert {"SELECT", "WITH", "VALUES", "EXPLAIN", "BEGIN", "SAVEPOINT", "RELEASE"} == PLAIN_READ_WORDS
    assert not PLAIN_READ_WORDS & {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "PRAGMA", "COMMIT", "ROLLBACK"}
    assert not READ_ONLY_PRAGMAS & READ_ONLY_PRAGMAS_WITH_ARGUMENT
    for name in READ_ONLY_PRAGMAS | READ_ONLY_PRAGMAS_WITH_ARGUMENT:
        assert name == name.lower() and name.replace("_", "").isalnum(), name


def test_no_acting_pragma_is_on_either_list():
    """These run something when sent, with or without a value: an allowlist that ever held one would read a checkpoint or a key as a read."""
    acting = {"wal_checkpoint", "optimize", "shrink_memory", "incremental_vacuum", "key", "rekey", "cipher_migrate", "writable_schema"}
    assert not acting & (READ_ONLY_PRAGMAS | READ_ONLY_PRAGMAS_WITH_ARGUMENT)


def test_every_pragma_on_the_no_value_list_is_a_write_when_given_a_value_and_a_read_without():
    for name in sorted(READ_ONLY_PRAGMAS):
        assert is_plain_read(f"PRAGMA {name}") is True, name
        assert is_plain_read(f"PRAGMA {name} = 1") is False, name
        assert is_plain_read(f"PRAGMA {name}(1)") is False, name


def test_every_pragma_on_the_argument_list_is_a_read_with_an_argument_and_a_write_with_a_value():
    for name in sorted(READ_ONLY_PRAGMAS_WITH_ARGUMENT):
        assert is_plain_read(f"PRAGMA {name}(note)") is True, name
        assert is_plain_read(f"PRAGMA {name} = 1") is False, name


def test_the_module_reads_the_first_word_and_parses_no_sql():
    """The listener runs on every statement the process sends: a regular expression and a set lookup, never a tokenizer."""
    source = Path(statement_kind.__file__).read_text(encoding="utf-8")
    assert "sqlparse" not in source and "tokenize" not in source
