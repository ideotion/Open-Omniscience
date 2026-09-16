"""``BACKUP_SUMMARY.md`` and the completion panel — ONE set of facts (R4; Q208, Q209).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Until now an export ended with one line: "Backup complete → <dest>". The engine had
already measured per-table counts, the archive's byte total, the alembic revision and
the app version on its way past -- and the job threw all of it away, because the only
consumer was a progress label. Q208 = a lists what the panel owes the operator and
Q209 = a adds a file carrying the SAME facts beside ``volumes.json``, "so the folder
explains itself on a removable drive years later".

THE POINT OF THIS MODULE IS THAT THERE IS ONE RENDERER. The panel and the file are
two presentations of :func:`export_facts`, so they cannot disagree -- which is
exactly what the gate row asks a test to prove. A second code path building "the same"
summary for the screen is how two surfaces come to report two different article
counts, and the reader has no way to tell which one lied.

WHERE THE FACTS COME FROM, and why none of them come from the browser:

  * the corpus half: the volume job's own last-completed summary. The job manager is
    a process-wide singleton, so this survives the tab being closed for the hours a
    real export runs -- the same property ``_uxShowLastCompletedExportSummary``
    already relies on.
  * the large-data half: ``oo-folder-backup.json`` read off the destination. Durable
    on disk, so a reopened dialog reports the files that are actually there rather
    than an in-memory progress counter that a reload cleared.
  * the verify verdict (Q218): the volume job's, because only the job can re-read
    every volume.

The client supplies the FOLDER and nothing else. A completion panel that took its
numbers from the page that asked for the export would be quoting the request back as
if it were the result.

HONEST ABSENCES. Every field that cannot be measured is absent WITH A REASON, never
zero and never a blank that reads as "none": ``None`` elapsed for the large-data
phase says the folder backup records no timing, and an unverified set says whether
verification was off, unavailable or FAILED -- three different facts that a single
missing "verified" would flatten into one.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.backup.attribution import (
    PendingRulingError,
    attribution_dicts,
    files_signal,
    signals_from_tables,
)

_LOG = logging.getLogger(__name__)

#: Written beside ``volumes.json`` (Q209 = a).
SUMMARY_NAME = "BACKUP_SUMMARY.md"

#: The ruled headline unit: ``articles`` leads the per-table counts (Q208 = a).
HEADLINE_TABLE = "articles"

#: What Q213 = c costs, stated wherever the export is reported. Not a warning about a
#: defect -- a price the ruling chose, which an operator planning a nightly export to
#: a slow USB stick needs in front of them.
FULL_WRITE_NOTE = (
    "Every export writes every volume: nothing is reused from an earlier backup, so "
    "this folder's bytes were all written by this one pass."
)

#: What Q218 = a costs. Also a price, also stated.
VERIFY_NOTE = (
    "Verify-after-write re-reads every volume from the destination and checks its "
    "checksum, so an export reads every byte back off the drive as well as writing "
    "it. That is what catches a stick that accepted the write and stored something "
    "else."
)


def _local_now_iso() -> str:
    """Local wall-clock time WITH its offset (Q210 = a picked the operator's clock).

    The offset is carried rather than dropped, because a bare local timestamp on a
    drive that travels is unreadable a year later -- the folder NAME is the thing
    ruled to be local and bare; the file can afford to be exact.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _table_rows(tables: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Per-table counts with ``articles`` FIRST (Q208 = a), the rest largest first.

    Every table is carried, empties included: "this backup holds no law documents" is
    a fact a reader of a five-year-old drive may well need, and dropping the zeros
    would make an empty table indistinguishable from a table the export forgot.
    """
    if not tables:
        return []
    rows: list[dict[str, Any]] = [
        {"name": str(n), "rows": int(c or 0)} for n, c in tables.items()
    ]
    rows.sort(key=lambda r: (str(r["name"]) != HEADLINE_TABLE, -int(r["rows"]), str(r["name"])))
    return rows


def _folder_manifest(dest: Path) -> dict[str, Any] | None:
    from src.backup.folder_backup import MANIFEST_NAME as FOLDER_MANIFEST

    p = dest / FOLDER_MANIFEST
    if not p.exists():
        return None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOG.warning("export summary: unreadable %s", FOLDER_MANIFEST, exc_info=True)
        return None
    return m if isinstance(m, dict) else None


def _file_categories(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Files copied per category, from the folder backup's OWN manifest.

    A category present with zero entries is dropped here (unlike the tables above):
    the manifest writes a key for every known category whether or not it was
    selected, so an empty list means "not part of this export" rather than "empty",
    and listing it would invent a member.
    """
    cats = (manifest or {}).get("categories") or {}
    out: list[dict[str, Any]] = []
    for name, items in cats.items():
        entries = items or []
        if not entries:
            continue
        out.append(
            {
                "category": str(name),
                "files": len(entries),
                "bytes": sum(int(e.get("size") or 0) for e in entries),
            }
        )
    out.sort(key=lambda c: (-c["bytes"], c["category"]))
    return out


def _verify_facts(summary: dict[str, Any] | None) -> dict[str, Any]:
    """The verify verdict as its own fact, with the three not-verified cases kept apart."""
    v = (summary or {}).get("verify")
    if not isinstance(v, dict):
        return {
            "state": "unknown",
            "reason": "this export recorded no verify result",
            "method": None,
        }
    return v


def export_facts(
    dest: str | os.PathLike[str],
    *,
    volume_status: dict[str, Any] | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Everything Q208 lists, measured, for ONE export folder.

    ``volume_status`` is the volume job manager's ``status()`` -- passed in rather
    than fetched so this module stays importable and testable without the job
    singleton. A status that is not a completed BACKUP OF THIS FOLDER is ignored:
    reporting another job's numbers under this folder's name is the exact
    data-safety bug the corpus gate upstream already refuses.
    """
    d = Path(dest)
    st = volume_status if isinstance(volume_status, dict) else {}
    summary = st.get("summary") if isinstance(st.get("summary"), dict) else None
    same_dest = bool(st.get("dest")) and Path(str(st["dest"])).resolve() == d.resolve()
    if not (st.get("mode") == "backup" and st.get("state") == "done" and same_dest):
        summary = None

    facts_block = (summary or {}).get("facts") or {}
    tables = facts_block.get("tables") if isinstance(facts_block.get("tables"), dict) else None
    folder = _folder_manifest(d)
    files = _file_categories(folder)

    signals = signals_from_tables(tables)
    signals |= {files_signal(c["category"]) for c in files}
    try:
        attribution = attribution_dicts(signals)
        attribution_error = None
    except PendingRulingError as exc:
        # The seam is REPORTED, never rendered around. A summary whose attribution
        # block is silently empty because a ruling is missing is the failure Q1008
        # exists to prevent; this says so in the artifact and in the panel.
        attribution, attribution_error = [], str(exc)

    corpus_s = summary.get("wall_s") if summary else None
    facts: dict[str, Any] = {
        "destination": str(d),
        "folder": d.name,
        "created_at": now_iso or _local_now_iso(),
        "corpus_included": summary is not None,
        "volumes": {
            "count": (summary or {}).get("volumes"),
            "bytes": _volume_bytes(d),
            "plaintext_bytes": (summary or {}).get("plaintext_bytes"),
            "parity": bool((summary or {}).get("parity")),
            "parity_available": (summary or {}).get("parity_available"),
        },
        "tables": _table_rows(tables),
        "files": files,
        "files_total_bytes": sum(c["bytes"] for c in files) if files else 0,
        "elapsed": {
            "corpus_s": corpus_s,
            "files_s": None,
            "files_s_reason": (
                "the large-data copy records no timing of its own"
                if files
                else "no large-data files were copied"
            ),
        },
        "encryption": {
            "artifact_encrypted": True if summary else None,
            "corpus_encrypted": (summary or {}).get("corpus_encrypted"),
            "files_encrypted": False if files else None,
            "note": (
                "The corpus and every member of the artifact are encrypted. Copied "
                "large-data files (dumps, maps, model weights) are public, "
                "re-downloadable blobs and are NOT encrypted — that is what makes a "
                "100 GB export feasible, and it is stated rather than implied."
            ),
        },
        "schema": {
            "backup_schema": facts_block.get("backup_schema"),
            "container": (summary or {}).get("format"),
            "alembic_rev": facts_block.get("alembic_rev"),
            "folder_schema": (folder or {}).get("schema"),
        },
        "app_version": facts_block.get("app_version"),
        "verify": _verify_facts(summary),
        "attribution": attribution,
        "attribution_error": attribution_error,
        "notes": list((summary or {}).get("notes") or []),
        "reuse": {"reused": False, "note": FULL_WRITE_NOTE},
    }
    return facts


def _volume_bytes(dest: Path) -> int | None:
    """Total bytes of the encrypted volumes + parity actually on the drive.

    Read off the MANIFEST (the set's own account of what it contains) rather than
    globbed off the directory, so a stray file an operator dropped in the folder is
    never counted as part of the backup.
    """
    from src.backup.volumes import MANIFEST_NAME

    p = dest / MANIFEST_NAME
    if not p.exists():
        return None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    total = 0
    for v in m.get("volumes") or []:
        total += int(v.get("bytes") or 0)
    for pv in (m.get("parity") or {}).get("volumes") or []:
        total += int(pv.get("bytes") or 0)
    return total


def _human(n: Any) -> str:
    if n is None:
        return "—"
    from src.backup.folder_backup import human_bytes

    return human_bytes(int(n))


def _seconds(n: Any) -> str:
    if n is None:
        return "—"
    s = float(n)
    if s < 90:
        return f"{s:.1f} s"
    m, rest = divmod(s, 60)
    return f"{int(m)} min {int(rest)} s"


def verify_sentence(verify: dict[str, Any]) -> str:
    """One plain sentence for a verify verdict — the panel and the file share it."""
    state = (verify or {}).get("state")
    total = (verify or {}).get("total")
    if state == "verified":
        return f"Verified — all {total} volumes were re-read and matched their checksums."
    if state == "failed":
        bad_volumes = list((verify or {}).get("bad") or [])
        bad = ", ".join(bad_volumes) or "unnamed volumes"
        return (
            f"NOT verified — the re-read found {len(bad_volumes)} of "
            f"{total} volumes that no longer match their checksum: {bad}. "
            "Treat this backup as unreliable until it is re-written."
        )
    if state == "off":
        return "NOT verified — verify-after-write was turned off for this export."
    reason = (verify or {}).get("reason") or "no reason was recorded"
    return f"NOT verified — {reason}."


def render_summary_markdown(facts: dict[str, Any]) -> str:
    """``BACKUP_SUMMARY.md`` — the same facts the panel shows, in the ruled order."""
    v = facts.get("volumes") or {}
    el = facts.get("elapsed") or {}
    enc = facts.get("encryption") or {}
    sch = facts.get("schema") or {}
    out: list[str] = [
        "# Open Omniscience — backup summary",
        "",
        f"- **Folder:** `{facts.get('folder')}`",
        f"- **Written:** {facts.get('created_at')}",
        "",
        "## What is in this folder",
        "",
    ]
    if facts.get("corpus_included"):
        out += [
            f"- **Encrypted volumes:** {v.get('count') if v.get('count') is not None else '—'}"
            f" · {_human(v.get('bytes'))} on the drive"
            f" · {_human(v.get('plaintext_bytes'))} of content",
            f"- **Parity (corruption recovery):** {'written' if v.get('parity') else 'none'}",
        ]
    else:
        out += ["- **Encrypted volumes:** none — no corpus was selected for this export."]
    files = facts.get("files") or []
    if files:
        out.append("- **Files copied, per category:**")
        for c in files:
            out.append(f"  - `{c['category']}`: {c['files']} files · {_human(c['bytes'])}")
    else:
        out.append("- **Files copied:** none.")
    out += [
        f"- **Elapsed (corpus):** {_seconds(el.get('corpus_s'))}",
        (
            f"- **Elapsed (files):** {_seconds(el.get('files_s'))}"
            if el.get("files_s") is not None
            else f"- **Elapsed (files):** not recorded — {el.get('files_s_reason')}"
        ),
        f"- **Destination:** `{facts.get('destination')}`",
        "",
        "## Integrity",
        "",
        f"- {verify_sentence(facts.get('verify') or {})}",
        f"- {VERIFY_NOTE}",
        f"- {(facts.get('reuse') or {}).get('note')}",
        "",
        "## Encryption",
        "",
        f"- **Corpus at rest in this backup:** "
        f"{_yes_no(enc.get('corpus_encrypted'))}",
        *(
            [f"- **Copied large-data files:** {_yes_no(enc.get('files_encrypted'))}"]
            if files
            else []
        ),
        f"- {enc.get('note')}",
        "",
        "## Versions",
        "",
        f"- **App version:** {sch_value(facts.get('app_version'))}",
        f"- **Backup schema:** {sch_value(sch.get('backup_schema'))}"
        f" · container {sch_value(sch.get('container'))}",
        f"- **Database schema (alembic):** {sch_value(sch.get('alembic_rev'))}",
    ]
    if sch.get("folder_schema"):
        out.append(f"- **Copied-files manifest schema:** {sch_value(sch.get('folder_schema'))}")
    tables = facts.get("tables") or []
    if tables:
        out += [
            "",
            "## What the corpus holds (rows per table, articles first)",
            "",
            "| Table | Rows |",
            "|---|---:|",
        ]
        out += [f"| `{r['name']}` | {r['rows']:,} |" for r in tables]
    lines = facts.get("attribution") or []
    if lines or facts.get("attribution_error"):
        out += ["", "## Attribution", ""]
        if facts.get("attribution_error"):
            out.append(
                f"- **This block could not be completed:** {facts['attribution_error']}"
            )
        for line in lines:
            out.append(f"- {line['text']}")
            out.append(f"  - *applies because:* `{line['because']}`")
    notes = facts.get("notes") or []
    if notes:
        out += ["", "## Notes recorded by the export", ""]
        out += [f"- {n}" for n in notes]
    out += [
        "",
        "---",
        "",
        "This file was written by the export that made this folder. It describes only "
        "what is here; it is not a signature and proves nothing about the bytes — "
        "`volumes.json` carries the per-volume checksums that do.",
        "",
        "**This file is not encrypted.** The backup's contents are: the corpus and every "
        "member of the artifact are unreadable without the passphrase. This summary is "
        "plain text beside them, and the counts above say how many articles, sources, "
        "law documents and tracked pages the corpus holds. That is what makes the folder "
        "explain itself years later, and it is also what a person who picks up this drive "
        "can read without the passphrase. Delete this file if that matters more than the "
        "explanation.",
        "",
    ]
    return "\n".join(out)


def _yes_no(flag: Any) -> str:
    if flag is None:
        return "—"
    return "yes" if flag else "no"


def sch_value(v: Any) -> str:
    return "—" if v in (None, "") else str(v)


def write_backup_summary(dest: str | os.PathLike[str], facts: dict[str, Any]) -> Path:
    """Write ``BACKUP_SUMMARY.md`` beside ``volumes.json``. Returns the path.

    Written with the same atomic replace the manifests use, so a reader who opens the
    drive mid-write never finds a half-file that looks like a short backup.
    """
    d = Path(dest)
    p = d / SUMMARY_NAME
    tmp = d / (SUMMARY_NAME + ".oopart")
    tmp.write_text(render_summary_markdown(facts), encoding="utf-8")
    os.replace(tmp, p)
    return p
