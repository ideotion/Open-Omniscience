"""Leave the imported newsletters out of a DISPOSABLE ENCRYPTED corpus copy without VACUUM.

``VACUUM`` builds the whole new copy of the file in the connection's temp store, and under SQLCipher
that store is memory (a file there would be written in the clear, below the codec): on a big corpus
it is the corpus's size in RAM, ungated. So the encrypted copy is not vacuumed. The newsletter rows
are deleted with ``secure_delete`` on, the search index is merged so it forgets their words, and the
survivors are rewritten with ``sqlcipher_export`` into a FRESH keyed file, which holds no trace of
what was deleted and is the size of what is left.

THE RULES THIS FILE HOLDS, each pinned by a test that fails without it:

  * The key never enters SQL text or an exception. It is bound (``ATTACH DATABASE ? AS x KEY ?``) on
    the raw driver connection, and nothing on this path raises or records the text of what the driver
    said: a failure is reported by its class (or, for this module's own refusals, by their fixed
    text), and the text that is logged is run through ``secret_scrub.scrub_text`` first.
  * Every cipher setting of the source is copied, not only the page size, and the result is read back
    through the production open path before it replaces the copy. A setting the export cannot carry
    over (a plaintext header, which needs a salt of its own) refuses the export instead.
  * Any failure takes the other path: the rows are already deleted with ``secure_delete`` on and the
    index merged, so the copy is left as that and the partial file is removed. The note says which
    path ran, and that this path is the weaker one: ``secure_delete`` zeroes what the deletes free,
    but it cannot reach stale bytes already sitting in a page's free space from an earlier split
    (measured: the root page of ``articles``, once it turned into an interior page, kept a copy of
    the first rows it held), so only the rewrite guarantees that no deleted text is in the copy.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import scrub_text

__all__ = ["drop_newsletters_encrypted"]

log = logging.getLogger(__name__)

#: ``PRAGMA <name>`` values a SQLCipher file is read with, applied to the new file in this order
#: (the page size first: it must precede ``auto_vacuum`` on a fresh file, see ``connect._connect``).
_CIPHER_SETTINGS = (
    "cipher_page_size",
    "auto_vacuum",
    "kdf_iter",
    "cipher_hmac_algorithm",
    "cipher_kdf_algorithm",
)
_ALGORITHM = re.compile(r"[A-Z0-9_]{1,64}")
_ALIAS = "nlout"
_SIDE_FILES = ("-wal", "-shm", "-journal")

NOTE_EXPORT = "newsletters excluded by rewriting the survivors into a fresh encrypted file"
NOTE_DELETE = (
    "newsletters excluded by secure delete (the rewrite into a fresh file did not complete: {why}); "
    "fragments of the excluded newsletters can remain in this backup's unused space, encrypted with it "
    "(a restore does not bring them back); a backup made when the rewrite can run has none"
)


class _ExportRefused(Exception):
    """The export did not produce a file that may replace the copy. Its message is fixed text and
    carries nothing the driver said."""


def _pragma(con, name: str) -> Any:
    row = con.execute(f"PRAGMA {name}").fetchone()  # noqa: S608  # nosec B608 - name is one of this module's constants
    return row[0] if row else None


def _read_settings(con) -> dict[str, Any]:
    """The source's real cipher settings. A plaintext header is refused: it needs the source's
    salt on the new file, which this does not carry over."""
    header = int(_pragma(con, "cipher_plaintext_header_size") or 0)
    if header:
        raise _ExportRefused("the source has a plaintext header")
    out: dict[str, Any] = {}
    for name in _CIPHER_SETTINGS:
        value = _pragma(con, name)
        if name in ("cipher_hmac_algorithm", "cipher_kdf_algorithm"):
            value = str(value)
            if not _ALGORITHM.fullmatch(value):
                raise _ExportRefused(f"{name} is not a name this can carry over")
        else:
            value = int(value)
        out[name] = value
    return out


def _settings_equal(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return [k for k in a if a[k] != b.get(k)]


def _index_bytes(con) -> int:
    """The search index's size, from the lengths of its segment blobs (the blobs' own bytes, not the pages
    they sit on: a block that spills onto an overflow page occupies more on disk). 0 when there is no
    index."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'article_fts_data' AND type = 'table'").fetchone():
        return 0
    return int(con.execute("SELECT COALESCE(SUM(LENGTH(block)), 0) FROM article_fts_data").fetchone()[0])


def _remove(path: Path) -> None:
    for suffix in ("", *_SIDE_FILES):
        with contextlib.suppress(OSError):
            Path(str(path) + suffix).unlink(missing_ok=True)


def _count(con, table: str) -> int | None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return None
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone():
        return None
    return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608  # nosec B608 - table matched a plain-identifier pattern above


def _shape(con) -> dict[str, Any]:
    """What a faithful copy keeps: the table names, the two row counts the filter changes, the
    schema revision and ``user_version``."""
    tables = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'"))
    rev = None
    if _count(con, "alembic_version") is not None:
        row = con.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        rev = row[0] if row else None
    return {
        "tables": tables,
        "articles": _count(con, "articles"),
        "sources": _count(con, "sources"),
        "alembic": rev,
        "user_version": int(_pragma(con, "user_version") or 0),
    }


def _export_to(con, out: Path, key: str, settings: dict[str, Any]) -> None:
    """``sqlcipher_export`` the open source into ``out`` under ``key``, which is BOUND."""
    con.execute(f"ATTACH DATABASE ? AS {_ALIAS} KEY ?", (str(out), key))
    try:
        for name in _CIPHER_SETTINGS:
            value = settings[name]
            literal = f"'{value}'" if isinstance(value, str) else str(int(value))
            con.execute(f"PRAGMA {_ALIAS}.{name} = {literal}")  # noqa: S608  # nosec B608 - name is a constant, value an int or a validated [A-Z0-9_] name
        con.execute(f"SELECT sqlcipher_export('{_ALIAS}')")  # noqa: S608  # nosec B608 - fixed alias
    finally:
        with contextlib.suppress(Exception):
            con.execute(f"DETACH DATABASE {_ALIAS}")


def _read_back(out: Path, key: str, settings: dict[str, Any], shape: dict[str, Any]) -> None:
    """Open ``out`` the way the app does and refuse it unless it is the same store."""
    from src.database.connect import connect, is_encrypted_file

    if not is_encrypted_file(out):
        raise _ExportRefused("the new file is not encrypted")
    check = connect(out, key=key, check_same_thread=False)
    try:
        got = _read_settings(check)
        differ = _settings_equal(settings, got)
        if differ:
            raise _ExportRefused("the new file's cipher settings differ: " + ", ".join(differ))
        got_shape = _shape(check)
        if got_shape != shape:
            wrong = [k for k in shape if shape[k] != got_shape.get(k)]
            raise _ExportRefused("the new file differs from the filtered copy in: " + ", ".join(wrong))
    finally:
        check.close()


def _failure_text(exc: BaseException, key: str) -> str:
    """The class of ``exc`` and its message with the key taken out, for the log. Never the chain."""
    return f"{type(exc).__name__}: {scrub_text(str(exc), key)}"


def drop_newsletters_encrypted(db_path: Path, notes: list[str] | None = None) -> int:
    """Remove the imported-newsletter articles from the encrypted copy at ``db_path``, in place.
    Returns how many articles were dropped; ``notes`` receives one line saying which path ran."""
    from src.backup.artifact import _drop_newsletter_rows, preflight_free_space
    from src.backup.folder_backup import free_bytes
    from src.database.connect import connect, get_passphrase

    key = get_passphrase()
    con = connect(db_path, check_same_thread=False)
    out = db_path.with_name(db_path.name + ".fresh")
    exported = False
    try:
        # The deletes and the index merge run in ONE transaction with secure_delete on, so the rollback
        # journal holds every page they free before it is zeroed (the deleted articles' pages as well
        # as the old index segments) while the merged segment is written beside them. Bound: the
        # journal cannot hold more than the file does, plus the merged segment, which is no larger than
        # the index. Measured, delete-journal mode: 90% of 30,000 articles deleted, peak 2.0 x the copy
        # with the index 39% of it (the extra was 2.6 x the index); the 25% case peaked at 2.06 x. A
        # figure taken from the index alone undershot (the review's probe: over 2 x the index in 5 of 6
        # runs). Asked here, on the copy, so a drive in the gap is refused in words and not by the driver.
        merge_room = db_path.stat().st_size + _index_bytes(con)
        preflight_free_space(
            db_path.parent,
            merge_room,
            what="newsletter filter and search-index merge (no backup was written)",
        )
        # The pages the deletes free are zeroed; stale bytes older than this run are not (see the note).
        con.execute("PRAGMA secure_delete = ON")
        dropped = _drop_newsletter_rows(con, vacuum=False)
        if not dropped:
            return 0
        why = ""
        try:
            if not key:
                raise _ExportRefused("no passphrase is held")
            settings = _read_settings(con)
            shape = _shape(con)
            if free_bytes(db_path.parent) < db_path.stat().st_size:  # the rewrite is never larger than the copy
                raise _ExportRefused("there is not enough free space for the rewrite")
            _remove(out)
            _export_to(con, out, key, settings)
            con.close()
            con = None
            _read_back(out, key, settings, shape)
            exported = True
        except Exception as exc:  # noqa: BLE001 - any failure takes the secure-delete path
            why = str(exc) if isinstance(exc, _ExportRefused) else type(exc).__name__
            log.warning(
                "newsletter export did not complete, the copy keeps the secure-delete path: %s",
                _failure_text(exc, key or ""),
            )
            _remove(out)
        if exported:
            os.replace(out, db_path)
            for suffix in _SIDE_FILES:
                with contextlib.suppress(OSError):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)
        if notes is not None:
            notes.append(NOTE_EXPORT if exported else NOTE_DELETE.format(why=why))
        return dropped
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
        _remove(out)  # gone after a replace; a partial file after any failure
