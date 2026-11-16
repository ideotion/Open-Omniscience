"""Living sources in a backup: the lane files' additive merge on import (R729).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS. ``wiki.db``, ``law.db`` and ``osm.db`` sit beside the corpus (Q719); the
backup dialog's «Living sources» row now carries them INSIDE the encrypted volume set,
each as a ``lanes/<kind>.db`` member snapshotted with its own encryption kept
(``stream_backup.collect_lane_members``). This module puts one back: it ATTACHes the
staged snapshot, with its key, to the LIVE lane and merges it table by table on the
source's own identities. The user's ask is the rule (2026-11-15): sources accumulate
across backups and updates, nothing replaced or lost.

THE RULES (R729, ruled 2026-11-16; design /mnt/project-files/living-sources-backup/DESIGN.md):
  * L1 an entity only the backup has is inserted with its own following/pinned flags and
    joins the ordinary schedule; the import fetches nothing, and every gate (airplane mode,
    consent, the lane's own switch) still decides whether it ever is. An entity on both
    sides keeps THIS machine's flags: ``watching = false`` here is an operator's unfollow,
    and no backup turns it back on. The count of newly followed pages is reported.
  * Identity columns the local row lacks (QID, title, language, country, admission reason)
    are FILLED from the backup; a value already here is never replaced.
  * L2 a per-entity fact and a walked page's listing are readings of the source's current
    state: the later reading wins, an equal timestamp keeps the local one -- exactly what a
    local refresh does.
  * L3 a baseline is this machine's first read and stays; a different baseline in the backup
    is kept as a REVISION, so its text is not lost.
  * Revisions and feed changes are inserted when absent and never updated.
  * L4 WARM keeps latest + previous (Q710): texts on both sides are pooled by revision and
    the two newest kept; the report counts the texts dropped that way.
  * L5 this machine's own measurements, bookmarks and consent records stay behind
    (``lane_meta``, ``versioned_cursors``/``gaps``/``size_samples``/``disclosures``, the walk's
    cursors and samples, ``wiki_lane_hourly``, ``wiki_warm_editions``/``scan``); the lane's
    search index is derived and its own triggers queue every merged text for indexing.

ONE TRANSACTION PER STORE. A failure anywhere rolls the lane back to what it was; the backup
is never written. Idempotent by construction: every insert is guarded by the natural key and
every update by a strict comparison, so importing the same backup again changes nothing.

NO PLAINTEXT ON DISK. The staged member keeps the SQLCipher encryption it was exported with
and is attached with its key; nothing is decrypted into a file. The key is a bound
parameter of ``ATTACH ... KEY ?`` (as ``connect.snapshot_to_plaintext`` binds it), never SQL
text, and is never logged: a failure is reported by its class only.

WHICH LANES. ``MERGEABLE_KINDS`` is the list this build can merge, and the export carries
ONLY those, so a backup never holds a lane its own build could not put back. A lane member
from a NEWER build that this one does not know is left unmerged and reported as such.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("backup.lane_merge")

#: The lanes this build both exports and merges. OSM joins in its own PR.
MERGEABLE_KINDS: tuple[str, ...] = ("wiki", "law")

#: Member-name prefix inside the volume set. A namespace of its own, like ``blobs/``.
LANE_PREFIX = "lanes"

#: The method line every report carries, so a reader knows what "merged" means here.
METHOD = (
    "Each living-source store in the backup was opened with its key and merged into this "
    "computer's store on the source's own identifiers, in one transaction: rows only the "
    "backup had were added, gaps in rows already here were filled, newer readings of a "
    "page's current state replaced older ones, and nothing else here was changed or removed."
)


class LaneMergeError(RuntimeError):
    """A lane member could not be merged. The live lane is left as it was."""


def member_name(kind: str) -> str:
    """The volume-set member name of one lane's snapshot."""
    return f"{LANE_PREFIX}/{kind}.db"


def valid_member(entry: Any) -> str | None:
    """The lane kind an ``lane_members`` manifest entry names, or ``None`` if it is not one.

    The manifest is self-signable by anyone, so the NAME is never trusted to choose a
    file: the kind must be a known lane and the name exactly the one this build would
    have written for it. Anything else is ignored, never joined into a path.
    """
    from src.versioned.lanes import KINDS

    if not isinstance(entry, dict):
        return None
    kind = entry.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        return None
    if entry.get("name") != member_name(kind):
        return None
    return kind


def attach_page_size() -> int:
    """SQLCipher's compiled-in page size: the size an ``ATTACH ... KEY`` reads a file at."""
    import sqlcipher3

    con = sqlcipher3.connect(":memory:")
    try:
        return int(con.execute("PRAGMA cipher_default_page_size").fetchone()[0])
    finally:
        con.close()


def snapshot_lane_for_backup(kind: str, dest: Path) -> dict[str, Any]:
    """A consistent snapshot of one live lane, for the volume set. Returns its manifest entry.

    ENCRYPTION KEPT: an encrypted lane is copied with ``sqlcipher_export`` into a file keyed
    with the same process passphrase, in one statement (one read transaction, so writers
    carry on and the copy is one consistent state); a plaintext lane (``OO_DB_PLAINTEXT``)
    is copied as plaintext, as the corpus is. Either way the volume envelope then encrypts
    it with the backup passphrase.

    WHY THE COPY IS WRITTEN AT THE COMPILED-IN PAGE SIZE and not the live file's (DB-10's
    16384): SQLCipher decodes a keyed file only at the page size it was written with, and
    an ``ATTACH ... KEY`` -- the import's way in, which needs no plaintext copy -- always
    reads at the compiled-in default. The rows are copied into the live lane on import, so
    the live file's own page size is never touched. The size is recorded in the entry and
    the import refuses, by name, a member written at another one.
    """
    from src.database.connect import (
        DatabaseLockedError,
        _export,
        connect,
        get_passphrase,
        is_encrypted_file,
        snapshot_to_plaintext,
    )
    from src.versioned.store import lane_path

    src = lane_path(kind)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    encrypted = bool(is_encrypted_file(src))
    if not encrypted:
        from src.versioned.store import PlaintextLaneRefused, _corpus_is_encrypted

        if _corpus_is_encrypted():
            # The snapshot is staged inside the destination folder (a USB stick, say):
            # a plaintext lane beside an encrypted corpus is never copied there in the clear.
            raise PlaintextLaneRefused(
                f"the {kind} lane is stored unencrypted beside an encrypted corpus; it is not "
                "copied into the backup folder in the clear"
            )
        snapshot_to_plaintext(src, dest)
        return {"name": member_name(kind), "kind": kind, "sqlcipher": False}
    key = get_passphrase()
    if not key:
        raise DatabaseLockedError(f"{src.name} is encrypted: cannot snapshot while locked")
    page_size = attach_page_size()
    conn = connect(src, check_same_thread=False)
    try:
        # The key is a bound parameter, never SQL text.
        conn.execute("ATTACH DATABASE ? AS snap KEY ?", (str(dest), key))
        conn.execute(f"PRAGMA snap.cipher_page_size = {int(page_size)}")
        _export(conn, "snap")
        conn.execute("DETACH DATABASE snap")
    except BaseException:
        dest.unlink(missing_ok=True)  # a partial copy is never mistaken for one
        raise
    finally:
        conn.close()
    return {"name": member_name(kind), "kind": kind, "sqlcipher": True, "page_size": page_size}


# --------------------------------------------------------------------------- #
#  Attaching the staged member
# --------------------------------------------------------------------------- #
def _attach(conn: Any, path: Path, keys: Iterable[str | None]) -> None:
    """ATTACH ``path`` as ``inc``, trying each key; refuse by name when none opens it."""
    from src.database.connect import is_encrypted_file

    encrypted = is_encrypted_file(path)
    if encrypted is None:
        raise LaneMergeError("the lane member is empty or missing from the staged backup")
    # The member was written at SQLCipher's compiled-in page size (snapshot_lane_for_backup
    # says why), which is the only size an ATTACH reads a keyed file at.
    candidates = [k for k in dict.fromkeys(keys) if k] if encrypted else [""]
    # The member is untrusted input attached inside a keyed live connection: SQL its schema
    # carries (view bodies, defaults, generated columns, virtual-table modules) may run only
    # with functions SQLite marks innocuous. _refuse_unsafe_inc then refuses the rest by name.
    conn.execute("PRAGMA trusted_schema = OFF")
    for key in candidates:
        try:
            # Some driver builds refuse a wrong key at ATTACH, others at the first read.
            conn.execute("ATTACH DATABASE ? AS inc KEY ?", (str(path), key))  # the key is bound, never SQL text
            conn.execute("SELECT count(*) FROM inc.sqlite_master").fetchone()
            return
        except Exception:  # noqa: BLE001 - a wrong key reads as "not a database"; try the next
            with contextlib.suppress(Exception):  # nothing was attached
                conn.execute("DETACH DATABASE inc")
    raise LaneMergeError(
        "the lane member is encrypted and none of the available passphrases open it; "
        "pass the source store's own passphrase to merge it"
    )


#: Every table the merge reads from the attached member.
_READ_TABLES = frozenset(
    {
        "lane_meta",
        "versioned_entities",
        "versioned_revisions",
        "versioned_baselines",
        "versioned_changes",
        "versioned_entity_facts",
        "wiki_walk_pages",
        "wiki_warm_pages",
        "law_identities",
        "law_document_meta",
        "law_provisions",
    }
)


def _refuse_unsafe_inc(conn: Any) -> None:
    """Refuse a member whose tables the merge reads are not plain tables.

    A real snapshot holds ordinary tables under these names. A view, a virtual table or a
    generated column under one of them would run SQL the backup's author chose inside this
    machine's keyed connection, so the member is refused before anything is read from it.
    """
    rows = conn.execute("SELECT type, name, sql FROM inc.sqlite_master WHERE name IN ({})".format(",".join("?" * len(_READ_TABLES))), tuple(sorted(_READ_TABLES))).fetchall()  # noqa: S608  # nosec B608 # placeholders only
    for typ, name, sql in rows:
        if typ != "table" or str(sql or "").lstrip().upper().startswith("CREATE VIRTUAL"):
            raise LaneMergeError("the lane member holds a table this build does not merge from (not a plain table); refusing to merge it")
        hidden = [r for r in conn.execute(f'PRAGMA inc.table_xinfo("{name}")').fetchall() if int(r[6] or 0) != 0]
        if hidden:
            raise LaneMergeError("the lane member holds a table with computed columns; refusing to merge it")
        # Timestamps are copied as they are stored, so one this build could not read back
        # (an integer, a 13th month) would be committed and break every later read of the
        # table. Any such value refuses the member before anything is written.
        live_types = {str(r[1]): str(r[2] or "").upper() for r in conn.execute(f'PRAGMA main.table_info("{name}")')}
        inc_cols = {str(r[1]) for r in conn.execute(f'PRAGMA inc.table_info("{name}")')}
        for col, typ_ in live_types.items():
            if col not in inc_cols or not ("DATE" in typ_ or "TIME" in typ_):
                continue
            bad = conn.execute(
                f'SELECT 1 FROM inc."{name}" WHERE "{col}" IS NOT NULL AND (typeof("{col}") != \'text\' '  # noqa: S608  # nosec B608 # names are the live schema's own, filtered to _READ_TABLES
                f'OR datetime("{col}") IS NULL OR substr("{col}", 1, 19) != datetime("{col}")) LIMIT 1'
            ).fetchone()
            if bad is not None:
                raise LaneMergeError("the lane member holds a timestamp this build cannot read; refusing to merge it")


def _columns(conn: Any, schema: str, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")').fetchall()]


def _has(conn: Any, schema: str, table: str) -> bool:
    master = "sqlite_temp_master" if schema == "temp" else f"{schema}.sqlite_master"
    return (
        conn.execute(f"SELECT 1 FROM {master} WHERE type='table' AND name=?", (table,)).fetchone()  # noqa: S608  # nosec B608 # schema is a module literal
        is not None
    )


def _changes(conn: Any) -> int:
    return int(conn.execute("SELECT changes()").fetchone()[0])


# --------------------------------------------------------------------------- #
#  The wiki lane (and the shared versioned_* tables every lane has)
# --------------------------------------------------------------------------- #
#: Identity columns filled from the backup when the local row has none (never replaced).
_ENTITY_FILL = ("qid", "title", "language", "country_alpha3", "admitted_reason")


def _insert_select(
    conn: Any,
    table: str,
    *,
    source_from: str,
    overrides: dict[str, str],
    where: str,
    source_alias: str,
    params: dict[str, Any] | None = None,
) -> int:
    """``INSERT INTO main.<table>`` the columns both files have (minus ``id``), each read as
    ``<alias>.<col>`` unless ``overrides`` gives its expression. Columns only the backup's
    older or newer schema has are left to their defaults here."""
    live = _columns(conn, "main", table)
    inc = set(_columns(conn, "inc", table))
    cols = [c for c in live if c != "id" and (c in inc or c in overrides)]
    exprs = [overrides.get(c, f'{source_alias}."{c}"') for c in cols]
    names = ", ".join(f'"{c}"' for c in cols)
    conn.execute(
        f"INSERT INTO main.{table} ({names}) SELECT {', '.join(exprs)} FROM {source_from} WHERE {where}",  # noqa: S608  # nosec B608 # table/clauses are module literals; columns are the LIVE schema's own
        params or {},
    )
    return _changes(conn)


def _merge_shared(conn: Any, out: dict[str, Any]) -> None:
    """The ``versioned_*`` tables, in dependency order (entities first)."""
    tables: dict[str, dict[str, int]] = out["tables"]
    if not _has(conn, "inc", "versioned_entities"):
        return
    live_cols = set(_columns(conn, "main", "versioned_entities"))
    inc_cols = set(_columns(conn, "inc", "versioned_entities"))
    fill = [c for c in _ENTITY_FILL if c in live_cols and c in inc_cols]
    filled = 0
    if fill:
        sets = ", ".join(f'"{c}" = COALESCE(m."{c}", i."{c}")' for c in fill)
        gaps = " OR ".join(f'(m."{c}" IS NULL AND i."{c}" IS NOT NULL)' for c in fill)
        conn.execute(
            f"UPDATE main.versioned_entities AS m SET {sets} FROM inc.versioned_entities AS i "  # noqa: S608  # nosec B608 # columns from the module's _ENTITY_FILL list
            f"WHERE i.external_id = m.external_id AND ({gaps})"
        )
        filled = _changes(conn)
    absent = "NOT EXISTS (SELECT 1 FROM main.versioned_entities m WHERE m.external_id = i.external_id)"
    # A page the backup marked deleted is stored, never counted as followed.
    live = " AND i.deleted_at IS NULL" if "deleted_at" in inc_cols else ""
    row = conn.execute(
        "SELECT count(*), coalesce(sum(CASE WHEN i.watching THEN 1 ELSE 0 END), 0) "  # nosec B608 # the clause is a module literal
        f"FROM inc.versioned_entities i WHERE {absent}{live}"
    ).fetchone()
    out["newly_followed"] = int(row[1]) if "watching" in inc_cols else int(row[0])
    # ``last_checked_at`` is when THIS machine asked (a different fact from when the
    # source changed): a page this machine has never asked about says so.
    inserted = _insert_select(
        conn,
        "versioned_entities",
        source_from="inc.versioned_entities i",
        overrides={"last_checked_at": "NULL"},
        where=absent,
        source_alias="i",
    )
    tables["versioned_entities"] = {"inserted": inserted, "filled": filled}

    conn.execute("DROP TABLE IF EXISTS temp.lm_ent")
    conn.execute("CREATE TEMP TABLE lm_ent (inc_id INTEGER PRIMARY KEY, loc_id INTEGER NOT NULL)")
    conn.execute(
        "INSERT INTO temp.lm_ent SELECT i.id, m.id FROM inc.versioned_entities i "
        "JOIN main.versioned_entities m ON m.external_id = i.external_id"
    )

    if _has(conn, "inc", "versioned_revisions"):
        n = _insert_select(
            conn,
            "versioned_revisions",
            source_from="inc.versioned_revisions r JOIN temp.lm_ent e ON e.inc_id = r.entity_id",
            # The corpus article this version became on the OTHER machine is a row id in
            # THAT corpus. Readers find a version's article here by its address
            # (src/wiki/versions.py ``_in_corpus``), so a foreign id is dropped, never kept.
            overrides={"entity_id": "e.loc_id", "article_id": "NULL"},
            where=(
                "NOT EXISTS (SELECT 1 FROM main.versioned_revisions m "
                "WHERE m.entity_id = e.loc_id AND m.revision_ref = r.revision_ref)"
            ),
            source_alias="r",
        )
        tables["versioned_revisions"] = {"inserted": n}

    if _has(conn, "inc", "versioned_baselines"):
        # L3: a different baseline in the backup is kept as a revision of its own, BEFORE
        # the absent-baseline insert (whose rows then match and are skipped on a re-run).
        kept = 0
        if _has(conn, "main", "versioned_revisions"):
            conn.execute(
                "INSERT INTO main.versioned_revisions (entity_id, revision_ref, observed_at, "
                "revised_at, content_hash, content, byte_size, diff_method) "
                "SELECT e.loc_id, b.revision_ref, b.captured_at, b.revised_at, b.content_hash, "
                "b.content, b.byte_size, 'no-previous-text' "
                "FROM inc.versioned_baselines b JOIN temp.lm_ent e ON e.inc_id = b.entity_id "
                "WHERE EXISTS (SELECT 1 FROM main.versioned_baselines lb "
                "WHERE lb.entity_id = e.loc_id AND lb.revision_ref <> b.revision_ref) "
                "AND NOT EXISTS (SELECT 1 FROM main.versioned_revisions m "
                "WHERE m.entity_id = e.loc_id AND m.revision_ref = b.revision_ref)"
            )
            kept = _changes(conn)
        n = _insert_select(
            conn,
            "versioned_baselines",
            source_from="inc.versioned_baselines b JOIN temp.lm_ent e ON e.inc_id = b.entity_id",
            overrides={"entity_id": "e.loc_id"},
            where="NOT EXISTS (SELECT 1 FROM main.versioned_baselines m WHERE m.entity_id = e.loc_id)",
            source_alias="b",
        )
        tables["versioned_baselines"] = {"inserted": n, "kept_as_revision": kept}

    if _has(conn, "inc", "versioned_changes"):
        n = _insert_select(
            conn,
            "versioned_changes",
            source_from="inc.versioned_changes c LEFT JOIN temp.lm_ent e ON e.inc_id = c.entity_id",
            overrides={
                "entity_id": "e.loc_id",
                "ingested_revision_id": (
                    "(SELECT m.id FROM main.versioned_revisions m "
                    "JOIN inc.versioned_revisions ir ON ir.id = c.ingested_revision_id "
                    "WHERE m.entity_id = e.loc_id AND m.revision_ref = ir.revision_ref)"
                ),
            },
            where=(
                "NOT EXISTS (SELECT 1 FROM main.versioned_changes m "
                "WHERE m.feed = c.feed AND m.change_ref = c.change_ref)"
            ),
            source_alias="c",
        )
        tables["versioned_changes"] = {"inserted": n}

    if _has(conn, "inc", "versioned_entity_facts"):
        # L2: the later reading wins; an equal timestamp keeps the local one (strict >).
        conn.execute(
            "UPDATE main.versioned_entity_facts AS m SET value_json = f.value_json, "
            "revision_ref = f.revision_ref, observed_at = f.observed_at "
            "FROM inc.versioned_entity_facts f JOIN temp.lm_ent e ON e.inc_id = f.entity_id "
            "WHERE m.entity_id = e.loc_id AND m.name = f.name AND f.observed_at > m.observed_at "
            "AND f.observed_at <= :horizon",
            {"horizon": _horizon()},
        )
        updated = _changes(conn)
        n = _insert_select(
            conn,
            "versioned_entity_facts",
            source_from="inc.versioned_entity_facts f JOIN temp.lm_ent e ON e.inc_id = f.entity_id",
            # A reading dated past this machine's clock is stored at the horizon, never later.
            overrides={"entity_id": "e.loc_id", "observed_at": "MIN(f.observed_at, :horizon)"},
            where=(
                "NOT EXISTS (SELECT 1 FROM main.versioned_entity_facts m "
                "WHERE m.entity_id = e.loc_id AND m.name = f.name)"
            ),
            source_alias="f",
            params={"horizon": _horizon()},
        )
        tables["versioned_entity_facts"] = {"inserted": n, "updated": updated}
    conn.execute("DROP TABLE IF EXISTS temp.lm_ent")


#: How far past this machine's clock a backup's timestamp may sit and still count as a
#: reading (clock skew between two of the operator's machines). A later one is not a
#: reading anyone took: it never wins "the later reading wins" (L2), so a backup cannot
#: pin a value that no honest reading could ever replace.
_CLOCK_SKEW = timedelta(days=1)

#: How far above this machine's highest revision of an edition a backup's revision may be
#: and still displace a local text (L4). Wikipedia revision ids grow by tens of millions a
#: year on the largest edition; a backup claiming more is not pooled, so it cannot evict
#: the local texts with a number no real fetch would ever exceed.
_REVID_REACH = 500_000_000


def _horizon() -> str:
    """The latest timestamp a backup may claim, in the lane's stored text format."""
    return (datetime.now(UTC) + _CLOCK_SKEW).replace(tzinfo=None).isoformat(sep=" ")


def _merge_walk(conn: Any, out: dict[str, Any]) -> None:
    if not _has(conn, "inc", "wiki_walk_pages"):
        return
    conn.execute(
        "UPDATE main.wiki_walk_pages AS m SET title = i.title, qid = i.qid, "
        "length_bytes = i.length_bytes, last_revid = i.last_revid, walked_at = i.walked_at "
        "FROM inc.wiki_walk_pages i "
        "WHERE i.edition = m.edition AND i.page_id = m.page_id AND i.walked_at > m.walked_at "
        "AND i.walked_at <= :horizon",
        {"horizon": _horizon()},
    )
    updated = _changes(conn)
    # ``pass_no`` counts THIS machine's walk passes; a page it never walked is pass 0, so the
    # next local pass refreshes it rather than reading as already seen by a later pass.
    n = _insert_select(
        conn,
        "wiki_walk_pages",
        source_from="inc.wiki_walk_pages i",
        overrides={"pass_no": "0", "walked_at": "MIN(i.walked_at, :horizon)"},
        where=(
            "NOT EXISTS (SELECT 1 FROM main.wiki_walk_pages m "
            "WHERE m.edition = i.edition AND m.page_id = i.page_id)"
        ),
        source_alias="i",
        params={"horizon": _horizon()},
    )
    out["tables"]["wiki_walk_pages"] = {"inserted": n, "updated": updated}


_WARM_TEXT = ("revid", "text", "bytes", "revised_at")


def _merge_warm(conn: Any, out: dict[str, Any]) -> None:
    if not _has(conn, "inc", "wiki_warm_pages"):
        return
    n = _insert_select(
        conn,
        "wiki_warm_pages",
        source_from="inc.wiki_warm_pages i",
        overrides={},
        where=(
            "NOT EXISTS (SELECT 1 FROM main.wiki_warm_pages m "
            "WHERE m.edition = i.edition AND m.page_id = i.page_id) "
            "AND coalesce(i.latest_revid, 0) <= coalesce((SELECT max(x.latest_revid) "
            "FROM main.wiki_warm_pages x WHERE x.edition = i.edition), :unbounded) + :reach"
        ),
        source_alias="i",
        params={"reach": _REVID_REACH, "unbounded": 2**62},
    )
    # L4: pool both sides' texts by revision and keep the two newest (Q710). The join reads
    # revision numbers only; a text is read, one row at a time, only for a page that changes,
    # so a re-import of this machine's own backup never holds the lane's texts in memory.
    horizon = _horizon()
    # The highest revision this machine holds per edition, read before any update.
    ceiling = {
        str(ed): int(mx) + _REVID_REACH
        for ed, mx in conn.execute(
            "SELECT edition, max(latest_revid) FROM main.wiki_warm_pages "
            "WHERE latest_revid IS NOT NULL GROUP BY edition"
        )
    }
    rows = conn.execute(
        "SELECT m.edition, m.id, i.id, m.latest_revid, m.previous_revid, i.latest_revid, i.previous_revid, "
        "m.wanted_revid, i.wanted_revid, m.due_since, i.due_since, m.fetched_at, i.fetched_at "
        "FROM main.wiki_warm_pages m JOIN inc.wiki_warm_pages i "
        "ON i.edition = m.edition AND i.page_id = m.page_id"
    )
    cols = ", ".join(f"{w}_{c}" for w in ("latest", "previous") for c in _WARM_TEXT)
    width = len(_WARM_TEXT)
    updated = dropped = refused = 0
    changes: list[tuple[Any, ...]] = []
    for r in rows:
        edition, m_id, i_id, m_lat, m_prev, i_lat, i_prev, m_want, i_want, m_due, i_due, m_fetched, i_fetched = r
        # (revid, schema, row id, slot): local first, so an equal revid keeps the local copy.
        pool: dict[int, tuple[str, int, str]] = {}
        for rv, schema, rid, slot in (
            (m_lat, "main", m_id, "latest"),
            (m_prev, "main", m_id, "previous"),
            (i_lat, "inc", i_id, "latest"),
            (i_prev, "inc", i_id, "previous"),
        ):
            if rv is None or int(rv) in pool:
                continue
            if schema == "inc" and int(rv) > ceiling.get(str(edition), 2**62):
                refused += 1  # a revision no real fetch would reach: never pooled
                continue
            pool[int(rv)] = (schema, rid, slot)
        kept = sorted(pool, reverse=True)[:2]
        cap = ceiling.get(str(edition), 2**62)
        if i_want is not None and int(i_want) > cap:
            i_want = None  # the same bound as the texts: a wanted revision no fetch would reach
        if i_fetched is not None and str(i_fetched) > horizon:
            i_fetched = None  # a fetch dated past this machine's clock is not a fetch
        wants = [w for w in (m_want, i_want) if w is not None]
        want = max(wants) if wants else None
        due = m_due if m_due is not None else i_due
        if kept and (want is None or kept[0] >= int(want)):
            due = None
        fetched = max([f for f in (m_fetched, i_fetched) if f is not None], default=None)
        keep_src = [pool[k] for k in kept]
        local_src = [("main", m_id, "latest")] if m_lat is not None else []
        if m_prev is not None:
            local_src.append(("main", m_id, "previous"))
        if keep_src == local_src and want == m_want and due == m_due and fetched == m_fetched:
            continue
        changes.append((m_id, keep_src, [rv for rv in pool if rv not in kept], i_id, want, due, fetched))
    for m_id, keep_src, lost, i_id, want, due, fetched in changes:
        texts: list[tuple[Any, ...]] = []
        for schema, rid, slot in keep_src:
            texts.append(
                tuple(
                    conn.execute(
                        f"SELECT {', '.join(f'{slot}_{c}' for c in _WARM_TEXT)} FROM {schema}.wiki_warm_pages WHERE id = ?",  # noqa: S608  # nosec B608 # slot/schema are module literals
                        (rid,),
                    ).fetchone()
                )
            )
        while len(texts) < 2:
            texts.append((None,) * width)
        # Only texts that existed count as dropped, and only on a page this merge changes.
        if lost:
            m_row = conn.execute(f"SELECT {cols} FROM main.wiki_warm_pages WHERE id = ?", (m_id,)).fetchone()  # noqa: S608  # nosec B608 # columns from _WARM_TEXT
            i_row = conn.execute(f"SELECT {cols} FROM inc.wiki_warm_pages WHERE id = ?", (i_id,)).fetchone()  # noqa: S608  # nosec B608 # columns from _WARM_TEXT
            seen: set[int] = set()
            for row_ in (m_row, i_row):
                for k in range(2):
                    rv, txt = row_[k * width], row_[k * width + 1]
                    if rv is not None and int(rv) in lost and int(rv) not in seen and txt is not None:
                        seen.add(int(rv))
            dropped += len(seen)
        conn.execute(
            "UPDATE main.wiki_warm_pages SET latest_revid = ?, latest_text = ?, latest_bytes = ?, "
            "latest_revised_at = ?, previous_revid = ?, previous_text = ?, previous_bytes = ?, "
            "previous_revised_at = ?, wanted_revid = ?, due_since = ?, fetched_at = ? WHERE id = ?",
            (*texts[0], *texts[1], want, due, fetched, m_id),
        )
        updated += 1
    _recount_warm_editions(conn)
    out["tables"]["wiki_warm_pages"] = {"inserted": n, "updated": updated}
    if refused:
        out["tables"]["wiki_warm_pages"]["texts_refused"] = refused
    out["warm_texts_dropped"] = dropped


def _recount_warm_editions(conn: Any) -> None:
    """Keep ``wiki_warm_editions.pages_with_text`` equal to the rows it counts.

    The model writes that count in the same transaction as the rows, so it cannot disagree
    with them; the merge gives rows text too, so it recounts them here, inside the merge's
    transaction. The other counters are this machine's own fetches (L5) and are left alone.
    """
    if not _has(conn, "main", "wiki_warm_editions"):
        return
    info = conn.execute('PRAGMA main.table_info("wiki_warm_editions")').fetchall()
    cols, vals = ["edition", "pages_with_text"], ["p.edition", "p.n"]
    for r in info:
        name, typ_, notnull, default = str(r[1]), str(r[2] or "").upper(), int(r[3] or 0), r[4]
        if name in cols or not notnull or default is not None:
            continue
        cols.append(name)
        vals.append(":now" if ("DATE" in typ_ or "TIME" in typ_) else "0")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
    conn.execute(
        f"INSERT INTO main.wiki_warm_editions ({', '.join(cols)}) "  # noqa: S608  # nosec B608 # columns are the live schema's own
        f"SELECT {', '.join(vals)} FROM (SELECT edition, count(*) AS n FROM main.wiki_warm_pages "
        "WHERE latest_bytes IS NOT NULL OR previous_bytes IS NOT NULL GROUP BY edition) p WHERE true "
        "ON CONFLICT(edition) DO UPDATE SET pages_with_text = excluded.pages_with_text "
        "WHERE pages_with_text != excluded.pages_with_text",
        {"now": now},
    )


# --------------------------------------------------------------------------- #
#  The law lane (R729, PR 2): identities, per-language metadata, provisions
# --------------------------------------------------------------------------- #
#: Identity columns filled from the backup when the local row has none (never replaced).
#: ``status`` and ``legal_system`` are NOT here: they are never NULL ("unknown" is a real
#: value), and the law lane records no date for them, so no later reading can be told apart.
_LAW_IDENTITY_FILL = ("issuing_body", "enacted_on", "published_on", "commenced_on", "repealed_on")
#: The same for one language version of a law.
_LAW_META_FILL = ("title", "source_url")
#: Filled only when the backup's row states the SAME provenance and licence as the local one:
#: ``translated_by`` is read as a pair with ``translation_kind`` (``model.provenance_of``) and
#: ``source_authority`` comes from the same catalogue row as ``licence_id``, so a value
#: filled across a different pair would name the wrong body beside this machine's claim.
_LAW_META_PAIRED_FILL = ("translated_by", "source_authority")
_LAW_TRIPLE = (
    "m.identity_scheme = i.identity_scheme AND m.jurisdiction_alpha3 = i.jurisdiction_alpha3 "
    "AND m.document_identity = i.document_identity"
)


def _corpus_law_links(conn: Any) -> None:
    """The live corpus's law links, in two temp tables of the lane connection.

    ``law.db`` links into ``corpus.db`` by minted strings (``src/law/lane_models.py``). A
    language version or a provision whose string the live corpus does not hold would be a
    member of a law group with no document behind it, so only linked rows are merged; the
    rest are counted. A provision's ``document_lane_key`` is read from the corpus, never
    from the backup: the corpus merge files an incoming version under THIS machine's copy
    of the same law, whose key is this machine's own.
    """
    from sqlalchemy import text

    from src.database.session import session_scope

    conn.execute("DROP TABLE IF EXISTS temp.lm_law_doc")
    conn.execute("DROP TABLE IF EXISTS temp.lm_law_rev")
    conn.execute("CREATE TEMP TABLE lm_law_doc (lane_key TEXT PRIMARY KEY)")
    conn.execute("CREATE TEMP TABLE lm_law_rev (lane_key TEXT PRIMARY KEY, doc_key TEXT NOT NULL)")
    with session_scope() as db:
        docs = db.execute(text("SELECT lane_key FROM law_documents WHERE lane_key IS NOT NULL")).all()
        revs = db.execute(
            text(
                "SELECT r.lane_key, d.lane_key FROM law_revisions r JOIN law_documents d ON d.id = r.document_id "
                "WHERE r.lane_key IS NOT NULL AND d.lane_key IS NOT NULL"
            )
        ).all()
    conn.executemany("INSERT OR IGNORE INTO temp.lm_law_doc VALUES (?)", [tuple(r) for r in docs])
    # The corpus does not make a key unique; a version key under two documents names no one
    # document, so it links nothing rather than an arbitrary one of them.
    owners: dict[str, set[str]] = {}
    for rev_key, doc_key in revs:
        owners.setdefault(str(rev_key), set()).add(str(doc_key))
    conn.executemany(
        "INSERT INTO temp.lm_law_rev VALUES (?, ?)",
        [(k, next(iter(v))) for k, v in owners.items() if len(v) == 1],
    )


def _merge_law(conn: Any, out: dict[str, Any]) -> None:
    tables: dict[str, dict[str, int]] = out["tables"]
    if not (_has(conn, "inc", "law_identities") and _has(conn, "inc", "law_document_meta")):
        return
    if not _has(conn, "temp", "lm_law_doc"):  # read before the transaction by merge_lane_file
        _corpus_law_links(conn)
    horizon = {"horizon": _horizon()}
    # A language version this machine lacks and whose document the live corpus holds.
    linked_new = (
        "i.lane_key IN (SELECT lane_key FROM temp.lm_law_doc) "
        "AND NOT EXISTS (SELECT 1 FROM main.law_document_meta m WHERE m.lane_key = i.lane_key)"
    )

    live_cols = set(_columns(conn, "main", "law_identities"))
    inc_cols = set(_columns(conn, "inc", "law_identities"))
    fill = [c for c in _LAW_IDENTITY_FILL if c in live_cols and c in inc_cols]
    filled = 0
    if fill:
        sets = ", ".join(f'"{c}" = COALESCE(m."{c}", i."{c}")' for c in fill)
        gaps = " OR ".join(f'(m."{c}" IS NULL AND i."{c}" IS NOT NULL)' for c in fill)
        conn.execute(
            f"UPDATE main.law_identities AS m SET {sets} FROM inc.law_identities AS i "  # noqa: S608  # nosec B608 # columns from the module's _LAW_IDENTITY_FILL list
            f"WHERE {_LAW_TRIPLE} AND ({gaps})"
        )
        filled = _changes(conn)
    # Only identities a merged language version will belong to: an identity with no
    # document behind it would be an empty law group on this machine.
    inserted = _insert_select(
        conn,
        "law_identities",
        source_from="inc.law_identities i",
        overrides={"created_at": "MIN(i.created_at, :horizon)"},
        where=(
            f"NOT EXISTS (SELECT 1 FROM main.law_identities m WHERE {_LAW_TRIPLE}) "
            f"AND i.id IN (SELECT i.identity_id FROM inc.law_document_meta i WHERE {linked_new})"
        ),
        source_alias="i",
        params=horizon,
    )
    tables["law_identities"] = {"inserted": inserted, "filled": filled}

    conn.execute("DROP TABLE IF EXISTS temp.lm_lid")
    conn.execute("CREATE TEMP TABLE lm_lid (inc_id INTEGER PRIMARY KEY, loc_id INTEGER NOT NULL)")
    conn.execute(f"INSERT INTO temp.lm_lid SELECT i.id, m.id FROM inc.law_identities i JOIN main.law_identities m ON {_LAW_TRIPLE}")  # noqa: S608  # nosec B608 # a module literal

    meta_live = set(_columns(conn, "main", "law_document_meta"))
    meta_inc = set(_columns(conn, "inc", "law_document_meta"))
    mfill = [c for c in _LAW_META_FILL if c in meta_live and c in meta_inc]
    mfilled = 0
    if mfill:
        sets = ", ".join(f'"{c}" = COALESCE(m."{c}", i."{c}")' for c in mfill)
        gaps = " OR ".join(f'(m."{c}" IS NULL AND i."{c}" IS NOT NULL)' for c in mfill)
        conn.execute(
            f"UPDATE main.law_document_meta AS m SET {sets} FROM inc.law_document_meta AS i "  # noqa: S608  # nosec B608 # columns from the module's _LAW_META_FILL list
            f"WHERE i.lane_key = m.lane_key AND ({gaps})"
        )
        mfilled = _changes(conn)
    paired = [c for c in _LAW_META_PAIRED_FILL if c in meta_live and c in meta_inc]
    if paired and {"translation_kind", "licence_id"} <= (meta_live & meta_inc):
        sets = ", ".join(f'"{c}" = COALESCE(m."{c}", i."{c}")' for c in paired)
        gaps = " OR ".join(f'(m."{c}" IS NULL AND i."{c}" IS NOT NULL)' for c in paired)
        conn.execute(
            f"UPDATE main.law_document_meta AS m SET {sets} FROM inc.law_document_meta AS i "  # noqa: S608  # nosec B608 # columns from the module's _LAW_META_PAIRED_FILL list
            "WHERE i.lane_key = m.lane_key AND i.translation_kind = m.translation_kind "
            f"AND i.licence_id = m.licence_id AND ({gaps})"
        )
        mfilled += _changes(conn)
    unlinked = int(
        conn.execute(
            "SELECT count(*) FROM inc.law_document_meta i WHERE i.lane_key NOT IN (SELECT lane_key FROM temp.lm_law_doc) "
            "AND NOT EXISTS (SELECT 1 FROM main.law_document_meta m WHERE m.lane_key = i.lane_key)"
        ).fetchone()[0]
    )
    # A linked version whose identity the member does not hold belongs to no law: counted too.
    unlinked += int(
        conn.execute(
            f"SELECT count(*) FROM inc.law_document_meta i WHERE {linked_new} "  # noqa: S608  # nosec B608 # a module literal
            "AND i.identity_id NOT IN (SELECT inc_id FROM temp.lm_lid)"
        ).fetchone()[0]
    )
    # The closed vocabularies are the model's own (``src/law/model.py``): a value this build
    # does not know is stored as the honest unknown, never as a claim the reader would
    # render (an unknown kind would otherwise read as "published by another government").
    from src.law.model import GRANULARITIES, LICENCES, TRANSLATION_KINDS

    vocab: dict[str, Any] = dict(horizon)
    kinds = ", ".join(f":k{n}" for n in range(len(TRANSLATION_KINDS)))
    lics = ", ".join(f":l{n}" for n in range(len(LICENCES)))
    grains = ", ".join(f":g{n}" for n in range(len(GRANULARITIES)))
    vocab.update({f"k{n}": v for n, v in enumerate(TRANSLATION_KINDS)})
    vocab.update({f"l{n}": v for n, v in enumerate(LICENCES)})
    vocab.update({f"g{n}": v for n, v in enumerate(GRANULARITIES)})
    n = _insert_select(
        conn,
        "law_document_meta",
        source_from="inc.law_document_meta i JOIN temp.lm_lid l ON l.inc_id = i.identity_id",
        overrides={
            "identity_id": "l.loc_id",
            "language": "lower(i.language)",
            "translation_kind": f"CASE WHEN i.translation_kind IN ({kinds}) THEN i.translation_kind ELSE 'unrecorded' END",
            "licence_id": f"CASE WHEN i.licence_id IN ({lics}) THEN i.licence_id ELSE 'unknown' END",
            "granularity": f"CASE WHEN i.granularity IN ({grains}) THEN i.granularity ELSE 'act' END",
            "first_seen_at": "MIN(i.first_seen_at, :horizon)",
            "updated_at": "MIN(i.updated_at, :horizon)",
        },
        where=linked_new,
        source_alias="i",
        params=vocab,
    )
    tables["law_document_meta"] = {"inserted": n, "filled": mfilled, "not_linked": unlinked}

    if _has(conn, "inc", "law_provisions"):
        # A provision belongs to one VERSION; one whose version the corpus does not hold
        # under the same key is counted, never stored (its text is in the backup's corpus).
        p_unlinked = int(
            conn.execute(
                "SELECT count(*) FROM inc.law_provisions p WHERE p.revision_lane_key NOT IN (SELECT lane_key FROM temp.lm_law_rev) "
                "AND NOT EXISTS (SELECT 1 FROM main.law_provisions m "
                "WHERE m.revision_lane_key = p.revision_lane_key AND m.address = p.address)"
            ).fetchone()[0]
        )
        pn = _insert_select(
            conn,
            "law_provisions",
            source_from="inc.law_provisions p JOIN temp.lm_law_rev r ON r.lane_key = p.revision_lane_key",
            overrides={"document_lane_key": "r.doc_key", "created_at": "MIN(p.created_at, :horizon)"},
            where=(
                "NOT EXISTS (SELECT 1 FROM main.law_provisions m "
                "WHERE m.revision_lane_key = p.revision_lane_key AND m.address = p.address)"
            ),
            source_alias="p",
            params=horizon,
        )
        tables["law_provisions"] = {"inserted": pn, "not_linked": p_unlinked}
    for t in ("lm_lid", "lm_law_doc", "lm_law_rev"):
        conn.execute(f"DROP TABLE IF EXISTS temp.{t}")


_STEPS = {
    "wiki": (_merge_shared, _merge_walk, _merge_warm),
    "law": (_merge_shared, _merge_law),
}


# --------------------------------------------------------------------------- #
#  Entry points
# --------------------------------------------------------------------------- #
def merge_lane_file(kind: str, path: Path, keys: Iterable[str | None]) -> dict[str, Any]:
    """Merge one staged lane snapshot into this machine's lane. One transaction."""
    from src.database.connect import connect
    from src.versioned.store import create_lane, dispose_lane, lane_path

    if kind not in _STEPS:
        raise LaneMergeError(f"this build cannot merge the {kind} lane yet")
    t0 = time.monotonic()
    create_lane(kind)  # idempotent; refuses by name while locked or beside an encrypted corpus in the clear
    out: dict[str, Any] = {"kind": kind, "tables": {}, "newly_followed": 0, "warm_texts_dropped": 0}
    conn = connect(lane_path(kind), check_same_thread=False)
    try:
        conn.isolation_level = None
        _attach(conn, path, keys)
        try:
            _refuse_unsafe_inc(conn)
            meta = None
            if _has(conn, "inc", "lane_meta"):
                meta = conn.execute("SELECT kind FROM inc.lane_meta ORDER BY id LIMIT 1").fetchone()
            # Every lane file stamps lane_meta when it is created, so a member without the
            # stamp, or with another kind's, is not this lane. The stamp is never echoed.
            if meta is None or meta[0] != kind:
                raise LaneMergeError(f"the member named {kind} is not a {kind} lane; refusing to merge it")
            if kind == "law":
                # Read before the lane's write lock is taken, so a law poller is not held
                # behind a corpus read; a link added meanwhile only waits for a re-import.
                _corpus_law_links(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                for step in _STEPS[kind]:
                    step(conn, out)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.execute("DETACH DATABASE inc")
    finally:
        conn.close()
    # Engines built before the merge may hold pages cached from the old file state; a lane
    # engine re-reads on its next checkout, so disposing is cheap insurance, never required.
    dispose_lane(kind)
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out


#: The longest failure reason a lane row keeps.
_REASON_LIMIT = 300


def merge_staged_lanes(
    staging_dir: Path,
    lane_members: Iterable[Any],
    keys: Iterable[str | None],
) -> dict[str, Any]:
    """Merge every lane member a staged backup carries. Never raises.

    One lane failing leaves that lane as it was and is reported; the others still merge.
    The report names no secret: a failure is its class and a fixed sentence.
    """
    from src.database.connect import DatabaseLockedError
    from src.monitoring.secret_scrub import record_text
    from src.versioned.store import PlaintextLaneRefused

    keys = list(keys)
    report: dict[str, Any] = {"lanes": [], "method": METHOD}
    for entry in lane_members or ():
        kind = valid_member(entry)
        if kind is None:
            report["lanes"].append({"kind": None, "state": "ignored", "reason": "not a lane member this build knows"})
            continue
        if kind not in MERGEABLE_KINDS:
            report["lanes"].append(
                {"kind": kind, "state": "not-merged", "reason": "this build cannot merge this lane yet; the backup still carries it"}
            )
            continue
        size = entry.get("page_size")
        # The manifest is untrusted: a page size that is not a plain integer is refused, never parsed.
        bad_size = size is not None and (isinstance(size, bool) or not isinstance(size, int))
        if entry.get("sqlcipher") and (bad_size or (size is not None and size != attach_page_size())):
            report["lanes"].append(
                {"kind": kind, "state": "not-merged", "reason": "the lane was written at a page size this build's encryption library cannot attach"}
            )
            continue
        path = Path(staging_dir) / member_name(kind)
        try:
            res = merge_lane_file(kind, path, keys)
            res["state"] = "merged"
            report["lanes"].append(res)
        except (LaneMergeError, DatabaseLockedError, PlaintextLaneRefused) as exc:
            # This module's own sentences, and the lane store's named refusals (locked; a
            # plaintext lane beside an encrypted corpus): scrubbed all the same.
            report["lanes"].append({"kind": kind, "state": "failed", "reason": record_text(exc, *keys, limit=_REASON_LIMIT)})
        except sqlite3.Error as exc:
            _LOG.warning("merging the %s lane failed (%s); the lane is unchanged", kind, type(exc).__name__)
            report["lanes"].append({"kind": kind, "state": "failed", "reason": f"database error ({type(exc).__name__}); the lane is unchanged"})
        except Exception as exc:  # noqa: BLE001 - one lane's failure never costs the import; the class only
            _LOG.warning("merging the %s lane failed (%s); the lane is unchanged", kind, type(exc).__name__)
            report["lanes"].append({"kind": kind, "state": "failed", "reason": f"{type(exc).__name__}; the lane is unchanged"})
    report["newly_followed"] = sum(int(x.get("newly_followed") or 0) for x in report["lanes"])
    return report


# --------------------------------------------------------------------------- #
#  Lanes still owed by an artifact whose corpus already merged
# --------------------------------------------------------------------------- #
#: An artifact's corpus is skipped on a second import once it has merged. When its lanes
#: did NOT merge (a failure, or a queue holding the corpus on a working copy) the digest is
#: recorded here, so the next import of that artifact runs instead of being skipped and the
#: lanes are not left behind for good. Digests and kinds only: no secret, no path, no text.
_PENDING_NAME = "lane_merge_pending.json"
_PENDING_LOCK = threading.Lock()


def _pending_path() -> Path:
    from src.versioned.store import lane_path

    return lane_path("wiki").parent / _PENDING_NAME


def _read_pending() -> dict[str, Any]:
    try:
        raw = json.loads(_pending_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


#: How many merge attempts an artifact's owed lanes get before it is skipped again like
#: any merged artifact. A lane that can never merge (a member that is missing, a store
#: nobody here holds the passphrase for) must not turn every re-import of it into a full
#: restore for good; after the last attempt the report and the log say why.
MAX_LANE_ATTEMPTS = 3


def lanes_pending(digest: str | None) -> bool:
    """Whether an artifact with this digest still owes this machine a lane merge."""
    if not digest:
        return False
    entry = _read_pending().get(digest)
    if not isinstance(entry, dict):
        return False
    try:
        return int(entry.get("attempts") or 0) < MAX_LANE_ATTEMPTS
    except (TypeError, ValueError):
        return False


def _write_pending(update: Any) -> None:
    from src.safety.file_lock import atomic_replace, file_lock

    try:
        path = _pending_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # The new content depends on the old: the file lock across the read and the replace.
        with _PENDING_LOCK, file_lock(path):
            cur = _read_pending()
            if not update(cur):
                return
            atomic_replace(path, json.dumps(cur, sort_keys=True))
    except OSError as exc:
        _LOG.warning("could not record which living sources are still owed (%s)", type(exc).__name__)


def mark_lanes_owed(digest: str | None, lane_members: Iterable[Any]) -> None:
    """Before a merge starts: the lanes are owed until it says otherwise, so a kill mid-merge
    (after the corpus already recorded the artifact as merged) never loses them. Never raises."""
    kinds = sorted({k for k in (valid_member(e) for e in lane_members or ()) if k in MERGEABLE_KINDS})
    if not digest or not kinds:
        return

    def update(cur: dict[str, Any]) -> bool:
        got = cur.get(digest)
        prev: dict[str, Any] = got if isinstance(got, dict) else {}
        try:
            attempts = int(prev.get("attempts") or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        cur[digest] = {"kinds": kinds, "attempts": attempts, "at": datetime.now(UTC).isoformat(timespec="seconds")}
        return True

    _write_pending(update)


def record_lane_outcome(digest: str | None, living: dict[str, Any]) -> None:
    """Remember (or forget) that this artifact's lanes are still owed. Never raises.

    A deferred lane (held behind the import queue) was never attempted, so it does not use
    up an attempt; a failed one keeps the count ``mark_lanes_owed`` set.
    """
    if not digest:
        return
    lanes = [x for x in living.get("lanes") or () if isinstance(x, dict)]
    owed = sorted({str(x.get("kind")) for x in lanes if x.get("state") in ("failed", "deferred")})
    if living.get("error"):
        owed = owed or ["all"]

    def update(cur: dict[str, Any]) -> bool:
        if not owed:
            if digest in cur:
                del cur[digest]
                return True
            return False
        got = cur.get(digest)
        prev: dict[str, Any] = got if isinstance(got, dict) else {}
        attempts = prev.get("attempts") or 0  # a deferred lane was never attempted: no count added
        cur[digest] = {"kinds": owed, "attempts": attempts, "at": datetime.now(UTC).isoformat(timespec="seconds")}
        return True

    _write_pending(update)
    if owed and not lanes_pending(digest):
        _LOG.warning(
            "the living sources of one backup did not merge after %d attempts; it is now skipped like "
            "any merged backup (re-import it with force to try again)",
            MAX_LANE_ATTEMPTS,
        )


def deferred_report(lane_members: Iterable[Any]) -> dict[str, Any]:
    """The lanes of an artifact whose corpus is held on an import queue's working copy."""
    lanes = []
    for entry in lane_members or ():
        kind = valid_member(entry)
        if kind is None:
            continue
        lanes.append(
            {
                "kind": kind,
                "state": "deferred",
                "reason": (
                    "the corpus from this backup is waiting for the rest of its import group, so its "
                    "living sources merge when the group is saved; if it is not saved, importing "
                    "this backup again merges them"
                ),
            }
        )
    return {"lanes": lanes, "method": METHOD, "newly_followed": 0}


def hold_lane_members(
    staging_dir: Path, lane_members: Iterable[Any], group_dir: Path, digest: str | None
) -> dict[str, Any] | None:
    """Keep a held item's lane members beside the import queue's working copy. Never raises.

    The staging tree is deleted when the item ends, but the corpus it brought reaches the
    live store only when the group commits, so the members are copied into the group's own
    directory (which the stale-staging janitor reclaims if this process dies) and merged
    then. Only ENCRYPTED members are kept: the group directory promises an orphan is
    encrypted whenever the corpus is, and a plaintext one stays owed for a re-import.
    """
    import hashlib
    import secrets
    import shutil

    from src.database.connect import is_encrypted_file

    kept: list[dict[str, Any]] = []
    try:
        # The digest can come from a backup's own manifest, so it never names a path: the
        # directory is a hash of it (or a random name), and must resolve inside the group.
        leaf = hashlib.sha256(str(digest).encode("utf-8")).hexdigest()[:32] if digest else secrets.token_hex(16)
        root = Path(group_dir).resolve()
        dest = root / "lanes" / leaf
        if not dest.resolve().is_relative_to(root):
            return None
        for entry in lane_members or ():
            kind = valid_member(entry)
            if kind is None or kind not in MERGEABLE_KINDS or not entry.get("sqlcipher"):
                continue
            src = Path(staging_dir) / member_name(kind)
            # The manifest's flag is a claim: the file itself must read as encrypted.
            if not src.is_file() or is_encrypted_file(src) is not True:
                continue
            target = dest / member_name(kind)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            # Only the fields the merge reads: the rest of a manifest entry is untrusted.
            kept.append({k: entry[k] for k in ("name", "kind", "sqlcipher", "page_size") if k in entry})
    except OSError as exc:
        _LOG.warning("could not keep a held backup's living sources for its group (%s)", type(exc).__name__)
        return None
    if not kept:
        return None
    return {"dir": str(dest), "members": kept, "digest": digest}
