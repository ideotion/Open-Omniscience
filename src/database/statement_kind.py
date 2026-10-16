"""Is this SQL statement a plain read? The question ``release_idle_connection`` asks of everything that ran on a transaction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (WAL / disk, 2026-10-16). Ending a session's read transaction to give its pooled connection back is a ROLLBACK, and a
rollback discards whatever the transaction wrote. The driver's changed-row count (``sqlite3.Connection.total_changes``) sees every row an
INSERT, UPDATE or DELETE changed on any path, but SQLite does not count a schema change (CREATE, DROP, ALTER, REINDEX) or a PRAGMA that
writes the database header (``user_version``, ``application_id``, ``schema_version``) as a changed row, and an explicit BEGIN (the
``read_snapshot`` recipe) keeps those inside the transaction, where the rollback undoes them. So the release also asks whether any
statement that ran on the transaction was something OTHER than a plain read.

WHAT COUNTS AS A PLAIN READ -- an allowlist, because the answer to an unknown statement must be "no" (a wrong "no" keeps a connection a
little longer; a wrong "yes" discards a write):

- ``SELECT``, ``VALUES``, ``EXPLAIN``, and ``WITH`` (a common table expression is a read, or it is a DML statement whose rows the driver's
  count already sees; it cannot carry a schema change);
- ``BEGIN``, ``SAVEPOINT`` and ``RELEASE``: they change nothing, and they are what SQLAlchemy and the ``read_snapshot`` recipe send;
- a PRAGMA from the two lists below, in its READ form: no ``=``, and no parenthesised value unless the pragma takes an argument to
  look something up. ``PRAGMA user_version = 3`` and ``PRAGMA user_version(3)`` set; ``PRAGMA user_version`` reads;
  ``PRAGMA table_info(note)`` reads. A PRAGMA that is on neither list (``wal_checkpoint``, ``optimize``, ``shrink_memory``,
  ``incremental_vacuum``, ``key``, an unknown one) is not a plain read.

A statement that starts with a comment, is empty, or is anything else (INSERT, UPDATE, DELETE, REPLACE, CREATE, DROP, ALTER, REINDEX,
VACUUM, ANALYZE, ATTACH, DETACH, COMMIT, END, ROLLBACK) is not a plain read. Nothing here parses SQL; it reads the first word, so it is
cheap enough to run on every statement the process sends.
"""

from __future__ import annotations

import re

_FIRST_WORD = re.compile(r"\s*([A-Za-z]+)")
_PRAGMA = re.compile(r"\s*PRAGMA\s+(?:\w+\s*\.\s*)?(\w+)\s*(\()?", re.IGNORECASE)

PLAIN_READ_WORDS = frozenset({"SELECT", "WITH", "VALUES", "EXPLAIN", "BEGIN", "SAVEPOINT", "RELEASE"})

#: PRAGMAs that only report, read with no value: ``PRAGMA page_count``.
READ_ONLY_PRAGMAS = frozenset(
    {
        "application_id", "auto_vacuum", "busy_timeout", "cache_size", "cell_size_check", "cipher_page_size", "cipher_provider",
        "cipher_version", "collation_list", "compile_options", "data_version", "database_list", "encoding", "foreign_keys",
        "freelist_count", "journal_mode", "journal_size_limit", "locking_mode", "max_page_count", "mmap_size", "page_count", "page_size",
        "query_only", "read_uncommitted", "recursive_triggers", "schema_version", "secure_delete", "synchronous", "temp_store",
        "threads", "user_version", "wal_autocheckpoint",
    }
)  # fmt: skip

#: PRAGMAs that take an argument to look something up and change nothing: ``PRAGMA table_info(note)``.
READ_ONLY_PRAGMAS_WITH_ARGUMENT = frozenset(
    {
        "foreign_key_check", "foreign_key_list", "function_list", "index_info", "index_list", "index_xinfo", "integrity_check",
        "module_list", "pragma_list", "quick_check", "table_info", "table_list", "table_xinfo",
    }
)  # fmt: skip


def is_plain_read(statement: str) -> bool:
    """True only for a statement that cannot change the database: see the module docstring. Never raises on a ``str``."""
    found = _FIRST_WORD.match(statement)
    if found is None:
        return False
    word = found.group(1).upper()
    if word in PLAIN_READ_WORDS:
        return True
    if word != "PRAGMA":
        return False
    pragma = _PRAGMA.match(statement)
    if pragma is None:
        return False
    name, parenthesised = pragma.group(1).lower(), pragma.group(2) is not None
    if "=" in statement:  # ``PRAGMA name = value``, and any value that looks like one: the answer to doubt is no
        return False
    if name in READ_ONLY_PRAGMAS_WITH_ARGUMENT:
        return True
    return name in READ_ONLY_PRAGMAS and not parenthesised
