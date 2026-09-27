"""The dated export folder — ``<dest>/YYYYMMDDHHMM_OpenOmniscience_Backup``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED (R5, amended by Q212 = c; Q210 = a; Q211 = a; Q213 = c). Until now an export
wrote its volumes straight into whatever directory the operator typed, with no
subfolder and no timestamp, so a second export into the same place refreshed the
first one in situ. The ruling replaces that with a dated folder per export:

  * ``YYYYMMDDHHMM`` in LOCAL time (Q210 = a) -- the clock the operator reads off
    their own machine when they look at the drive, not UTC. The cost is stated
    rather than hidden: two exports either side of a DST change can sort out of
    order once a year.
  * ``OpenOmniscience`` spelled out (Q212 = c), not the ``OOS`` token R5 first
    named. ONE constant holds it, which is a design choice and not a ruling -- the
    bulletin's own ``_OOS_`` names are NOT covered by Q212 and are deliberately
    left alone (brief S04-03 section 6).
  * ``_2``, ``_3`` ... on collision (Q211 = a), so a repeat sorts beside its
    sibling instead of overwriting it.
  * Every export is a NEW folder, so no export ever reuses a previous export's
    volumes (Q213 = c). That costs hours and gigabytes on every run and the panel
    says so; it buys a set whose bytes were all written by one pass.

THE ALLOCATION IS THE GUARANTEE, not the naming. ``mkdir()`` is called WITHOUT
``exist_ok``, which is an atomic exclusive create: the call either makes a folder
that did not exist a moment ago or raises. So this function can never hand back a
directory that already holds someone's backup -- not through a race between two
exports started in the same minute, and not through a name that happens to match a
folder the operator made themselves. Nothing here ever writes into, truncates or
deletes an existing path.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

#: The spelled-out token (Q212 = c). One constant so the rename the ledger still
#: expects for the app's name is one edit here.
BACKUP_FOLDER_TOKEN = "OpenOmniscience"

#: What the operator ASKED this export to hold, written into the dated folder the moment
#: it is allocated (the 2026-09-27 re-walk, J-1). The export's second phase -- the
#: large-data copy -- is started by the page once the corpus phase is done, so a page
#: reload between the two phases meant the copy never started, and nothing anywhere
#: remembered it had been asked for: the reopened dialog read "Backup complete" over a
#: folder with no models in it. With the request on the drive beside the backup,
#: :func:`src.backup.export_summary.export_facts` compares it with what is actually there
#: and names what is missing. A record, never a gate: nothing reads it to decide what
#: to write.
REQUEST_NAME = "oo-export-request.json"
REQUEST_SCHEMA = "oo-export-request-1"

#: ``YYYYMMDDHHMM_OpenOmniscience_Backup``. The suffix is part of the ruled name.
BACKUP_FOLDER_SUFFIX = "Backup"

#: Stop trying ordinals long before an operator could have made this many folders in
#: one minute. Hitting it means something is wrong with the destination (a filesystem
#: refusing creates for a reason that is not "it exists"), and a loop that never ends
#: is a worse answer than a named failure.
_MAX_ORDINAL = 500

_TIMESTAMP = "%Y%m%d%H%M"


class ExportFolderError(RuntimeError):
    """Raised when no dated export folder could be created at the destination."""


def folder_name(when: datetime | None = None, *, ordinal: int = 1) -> str:
    """``202609121045_OpenOmniscience_Backup``, ``..._2`` for the second that minute.

    ``when`` is a NAIVE local datetime (Q210 = a). Passing an aware one is accepted
    and its own clock is used verbatim -- the caller is then responsible for it being
    the clock they mean, because this function will not convert a timezone behind
    their back.
    """
    stamp = (when or datetime.now()).strftime(_TIMESTAMP)
    base = f"{stamp}_{BACKUP_FOLDER_TOKEN}_{BACKUP_FOLDER_SUFFIX}"
    n = int(ordinal or 1)
    return base if n <= 1 else f"{base}_{n}"


def is_export_folder_name(name: str) -> bool:
    """Whether ``name`` is one of our dated export folders.

    Used by the tests and by anything that wants to recognise a set on a drive; it
    is deliberately a NAME test only and says nothing about the folder's contents.
    """
    part = name.split("_")
    if len(part) not in (3, 4):
        return False
    stamp, token, suffix = part[0], part[1], part[2]
    if token != BACKUP_FOLDER_TOKEN or suffix != BACKUP_FOLDER_SUFFIX:
        return False
    if len(stamp) != 12 or not stamp.isdigit():  # YYYYMMDDHHMM
        return False
    if len(part) == 3:
        return True
    return part[3].isdigit() and int(part[3]) >= 2


def allocate_export_folder(
    parent: str | os.PathLike[str], *, now: datetime | None = None
) -> Path:
    """Create and return a FRESH dated export folder under ``parent``.

    The returned path is guaranteed to have been empty the instant it was created,
    and no existing file or folder is read, written or removed to get there. Both
    export phases (the encrypted volumes and the copied large-data files) are handed
    this one path, so a single export is one folder.
    """
    base = Path(parent)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportFolderError(f"Cannot use destination {base}: {exc}") from exc
    if not base.is_dir():
        raise ExportFolderError(f"{base} is not a folder.")
    when = now or datetime.now()
    first: OSError | None = None
    for ordinal in range(1, _MAX_ORDINAL + 1):
        candidate = base / folder_name(when, ordinal=ordinal)
        try:
            candidate.mkdir()  # EXCLUSIVE: never exist_ok -- see the module docstring
        except FileExistsError:
            continue
        except OSError as exc:
            # A real filesystem refusal (permissions, read-only drive, full disk).
            # Reported as itself rather than retried under another name, which would
            # spin _MAX_ORDINAL times and then blame the ordinals.
            first = exc
            break
        return candidate
    if first is not None:
        raise ExportFolderError(f"Cannot create an export folder in {base}: {first}")
    raise ExportFolderError(
        f"Cannot create an export folder in {base}: "
        f"{folder_name(when)} and {_MAX_ORDINAL - 1} numbered siblings already exist."
    )


def write_export_request(
    folder: str | os.PathLike[str],
    *,
    corpus: bool,
    categories: list[str],
    inside: bool = False,
) -> Path | None:
    """Record, inside a freshly allocated export folder, what the export was asked for.

    ``categories`` are the large-data categories the operator ticked; ``inside`` says
    they ride INSIDE the encrypted artifact rather than being copied beside it, in
    which case no separate copy is owed. Only known categories are kept, in the order
    given, so a stray value from a client can never name a member that does not exist.

    NEVER RAISES. The record is an aid to reporting, not part of the backup: a drive
    that refuses this small write will refuse the volumes a moment later, and that
    failure is the one worth reporting. Returns the path, or ``None`` when it could
    not be written (logged).
    """
    from src.backup.folder_backup import _CATEGORIES

    d = Path(folder)
    seen: list[str] = []
    for c in categories or []:
        if c in _CATEGORIES and c not in seen:
            seen.append(c)
    record = {
        "schema": REQUEST_SCHEMA,
        "requested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "corpus": bool(corpus),
        "categories": seen,
        "inside": bool(inside) and bool(corpus) and bool(seen),
    }
    p = d / REQUEST_NAME
    tmp = d / (REQUEST_NAME + ".oopart")
    try:
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        _LOG.warning("export folder: could not record the request in %s", d, exc_info=True)
        return None
    return p


def read_export_request(folder: str | os.PathLike[str]) -> dict[str, Any] | None:
    """The request recorded by :func:`write_export_request`, or ``None``.

    ``None`` for a folder written before the record existed, or one whose record is
    unreadable: in both cases what was asked for is UNKNOWN, which the caller must
    report as unknown rather than as "nothing was asked for".
    """
    p = Path(folder) / REQUEST_NAME
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != REQUEST_SCHEMA:
        return None
    cats = raw.get("categories")
    return {
        "corpus": bool(raw.get("corpus")),
        "categories": [str(c) for c in cats] if isinstance(cats, list) else [],
        "inside": bool(raw.get("inside")),
        "requested_at": raw.get("requested_at"),
    }
