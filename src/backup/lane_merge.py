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
and is attached with its key; nothing is decrypted into a file. The key is passed the way
``connect.snapshot_preserving`` passes it (an escaped SQL literal, because ``ATTACH ... KEY``
takes no bound parameter on every driver build) and is never logged: a failure is reported
by its class only.

WHICH LANES. ``MERGEABLE_KINDS`` is the list this build can merge, and the export carries
ONLY those, so a backup never holds a lane its own build could not put back. A lane member
from a NEWER build that this one does not know is left unmerged and reported as such.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("backup.lane_merge")

#: The lanes this build both exports and merges. Law and OSM join in their own PRs.
MERGEABLE_KINDS: tuple[str, ...] = ("wiki",)

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
        _sql_literal_escape,
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
        snapshot_to_plaintext(src, dest)
        return {"name": member_name(kind), "kind": kind, "sqlcipher": False}
    key = get_passphrase()
    if not key:
        raise DatabaseLockedError(f"{src.name} is encrypted: cannot snapshot while locked")
    page_size = attach_page_size()
    conn = connect(src, check_same_thread=False)
    try:
        conn.execute(f"ATTACH DATABASE ? AS snap KEY '{_sql_literal_escape(key)}'", (str(dest),))
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
    from src.database.connect import _sql_literal_escape, is_encrypted_file

    encrypted = is_encrypted_file(path)
    if encrypted is None:
        raise LaneMergeError("the lane member is empty or missing from the staged backup")
    # The member was written at SQLCipher's compiled-in page size (snapshot_lane_for_backup
    # says why), which is the only size an ATTACH reads a keyed file at.
    candidates = [k for k in dict.fromkeys(keys) if k] if encrypted else [""]
    for key in candidates:
        try:
            # Some driver builds refuse a wrong key at ATTACH, others at the first read.
            conn.execute(f"ATTACH DATABASE ? AS inc KEY '{_sql_literal_escape(key)}'", (str(path),))
            conn.execute("SELECT count(*) FROM inc.sqlite_master").fetchone()
            return
        except Exception:  # noqa: BLE001 - a wrong key reads as "not a database"; try the next
            with contextlib.suppress(Exception):  # nothing was attached
                conn.execute("DETACH DATABASE inc")
    raise LaneMergeError(
        "the lane member is encrypted and none of the available passphrases open it; "
        "pass the source store's own passphrase to merge it"
    )


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
        f"INSERT INTO main.{table} ({names}) SELECT {', '.join(exprs)} FROM {source_from} WHERE {where}"  # noqa: S608  # nosec B608 # table/clauses are module literals; columns are the LIVE schema's own
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
    row = conn.execute(
        "SELECT count(*), coalesce(sum(CASE WHEN i.watching THEN 1 ELSE 0 END), 0) "  # nosec B608 # the clause is a module literal
        f"FROM inc.versioned_entities i WHERE {absent}"
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
            "WHERE m.entity_id = e.loc_id AND m.name = f.name AND f.observed_at > m.observed_at"
        )
        updated = _changes(conn)
        n = _insert_select(
            conn,
            "versioned_entity_facts",
            source_from="inc.versioned_entity_facts f JOIN temp.lm_ent e ON e.inc_id = f.entity_id",
            overrides={"entity_id": "e.loc_id"},
            where=(
                "NOT EXISTS (SELECT 1 FROM main.versioned_entity_facts m "
                "WHERE m.entity_id = e.loc_id AND m.name = f.name)"
            ),
            source_alias="f",
        )
        tables["versioned_entity_facts"] = {"inserted": n, "updated": updated}
    conn.execute("DROP TABLE IF EXISTS temp.lm_ent")


def _merge_walk(conn: Any, out: dict[str, Any]) -> None:
    if not _has(conn, "inc", "wiki_walk_pages"):
        return
    conn.execute(
        "UPDATE main.wiki_walk_pages AS m SET title = i.title, qid = i.qid, "
        "length_bytes = i.length_bytes, last_revid = i.last_revid, walked_at = i.walked_at "
        "FROM inc.wiki_walk_pages i "
        "WHERE i.edition = m.edition AND i.page_id = m.page_id AND i.walked_at > m.walked_at"
    )
    updated = _changes(conn)
    # ``pass_no`` counts THIS machine's walk passes; a page it never walked is pass 0, so the
    # next local pass refreshes it rather than reading as already seen by a later pass.
    n = _insert_select(
        conn,
        "wiki_walk_pages",
        source_from="inc.wiki_walk_pages i",
        overrides={"pass_no": "0"},
        where=(
            "NOT EXISTS (SELECT 1 FROM main.wiki_walk_pages m "
            "WHERE m.edition = i.edition AND m.page_id = i.page_id)"
        ),
        source_alias="i",
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
            "WHERE m.edition = i.edition AND m.page_id = i.page_id)"
        ),
        source_alias="i",
    )
    # L4: pool both sides' texts by revision and keep the two newest (Q710).
    sel = ", ".join(
        f"{side}.{w}_{c}" for side in ("m", "i") for w in ("latest", "previous") for c in _WARM_TEXT
    )
    rows = conn.execute(
        f"SELECT m.id, m.wanted_revid, i.wanted_revid, m.due_since, i.due_since, m.fetched_at, "  # noqa: S608  # nosec B608 # columns from the module's _WARM_TEXT list
        f"i.fetched_at, {sel} FROM main.wiki_warm_pages m JOIN inc.wiki_warm_pages i "
        "ON i.edition = m.edition AND i.page_id = m.page_id"
    ).fetchall()
    updated = dropped = 0
    for r in rows:
        row_id, m_want, i_want, m_due, i_due, m_fetched, i_fetched = r[:7]
        texts = r[7:]
        width = len(_WARM_TEXT)
        slots = [tuple(texts[k * width:(k + 1) * width]) for k in range(4)]  # m.latest, m.prev, i.latest, i.prev
        local = slots[:2]
        pool: dict[int, tuple] = {}
        for s in slots:  # local first: an equal revid keeps the local copy
            if s[0] is not None and int(s[0]) not in pool:
                pool[int(s[0])] = s
        kept = sorted(pool, reverse=True)[:2]
        dropped += sum(1 for rv, s in pool.items() if rv not in kept and s[1] is not None)
        latest = pool[kept[0]] if kept else (None,) * width
        previous = pool[kept[1]] if len(kept) > 1 else (None,) * width
        wants = [w for w in (m_want, i_want) if w is not None]
        want = max(wants) if wants else None
        due = m_due if m_due is not None else i_due
        if latest[0] is not None and (want is None or int(latest[0]) >= int(want)):
            due = None
        fetched = max([f for f in (m_fetched, i_fetched) if f is not None], default=None)
        if (latest, previous) == tuple(local) and want == m_want and due == m_due and fetched == m_fetched:
            continue
        conn.execute(
            "UPDATE main.wiki_warm_pages SET latest_revid = ?, latest_text = ?, latest_bytes = ?, "
            "latest_revised_at = ?, previous_revid = ?, previous_text = ?, previous_bytes = ?, "
            "previous_revised_at = ?, wanted_revid = ?, due_since = ?, fetched_at = ? WHERE id = ?",
            (*latest, *previous, want, due, fetched, row_id),
        )
        updated += 1
    out["tables"]["wiki_warm_pages"] = {"inserted": n, "updated": updated}
    out["warm_texts_dropped"] = dropped


_STEPS = {
    "wiki": (_merge_shared, _merge_walk, _merge_warm),
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
            meta = None
            if _has(conn, "inc", "lane_meta"):
                meta = conn.execute("SELECT kind FROM inc.lane_meta ORDER BY id LIMIT 1").fetchone()
            if meta is not None and meta[0] != kind:
                raise LaneMergeError(f"the member named {kind} holds a {meta[0]} lane; refusing to merge it")
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
        if entry.get("sqlcipher") and size is not None and int(size) != attach_page_size():
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
            report["lanes"].append({"kind": kind, "state": "failed", "reason": record_text(exc, *keys)})
        except sqlite3.Error as exc:
            _LOG.warning("merging the %s lane failed (%s); the lane is unchanged", kind, type(exc).__name__)
            report["lanes"].append({"kind": kind, "state": "failed", "reason": f"database error ({type(exc).__name__}); the lane is unchanged"})
        except Exception as exc:  # noqa: BLE001 - one lane's failure never costs the import; the class only
            _LOG.warning("merging the %s lane failed (%s); the lane is unchanged", kind, type(exc).__name__)
            report["lanes"].append({"kind": kind, "state": "failed", "reason": f"{type(exc).__name__}; the lane is unchanged"})
    report["newly_followed"] = sum(int(x.get("newly_followed") or 0) for x in report["lanes"])
    return report
