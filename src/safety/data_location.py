"""Where the corpus lives — chosen once, at first launch, before anything is written.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-07-14): at first launch, after the language and legal steps and
BEFORE the passphrase, offer either the app's own data folder (the default) or "choose a
folder", in which an "OOS data" subfolder is created. It reuses the A11 seam rather than
inventing one: ``install.sh:persist_data_dir`` already validates a path and records
``export OO_DATA_DIR=`` in a 0600 ``oo.env`` at the install root, and ``scripts/launch.sh``
already sources that file on every start. What was missing is a way to make that choice
from the app, on a machine whose owner never typed an environment variable.

WHY IT PERSISTS AND RESTARTS RATHER THAN SWITCHING LIVE, which is the load-bearing
constraint and is not a preference:

``src/database/session.py`` evaluates ``DATABASE_URL``, ``engine`` and ``SessionLocal`` at
MODULE IMPORT, and three modules (``database/snapshots.py``, ``api/library.py``,
``api/database.py``) bind ``engine`` into their own module scope at import too. So there is
no rebind that reaches every holder. Meanwhile ``src.paths.data_dir()`` re-reads the
environment on EVERY call, which is what makes a live switch actively dangerous rather than
merely ineffective: the keys directory, the custody log, annotations, import reports, wiki
dumps and the model store would all move to the new folder while the corpus stayed in the
old one -- and on the next start ``DATABASE_URL`` would follow the environment to the new,
empty folder and report ``fresh``, with the operator's corpus orphaned beside a set of keys
that no longer sits next to it.

So the choice is only offered while the state is ``fresh``, when there is nothing yet to
split; the endpoint refuses afterwards. Moving an EXISTING corpus is the plain-folder-copy
path the manual documents (app stopped, copy the folder, point ``OO_DATA_DIR`` at it) --
deliberately not automated here, because a half-finished move of a multi-GB encrypted
corpus is the one outcome worse than not offering the button.

Everything here is local: filesystem reads and one 0600 file write. No network, no score.
"""

from __future__ import annotations

import os
import shlex
import stat
import tempfile
from pathlib import Path
from typing import Any

#: The subfolder created inside a folder the operator picks, so pointing the app at a
#: drive root (or at a folder they already keep other things in) leaves ONE named
#: directory behind rather than scattering keys/ custody/ corpus across it.
DATA_SUBDIR = "OOS data"

#: A refusal to write into a folder the app cannot prove is durable would be a hard block,
#: which this project does not do; what it does instead is SAY so. RAM-backed filesystems
#: are the case that can be proven (the same set ``monitoring.forensics`` reads).
_VOLATILE_FS = frozenset({"tmpfs", "ramfs"})

#: Enough room to be worth choosing. Not a hard floor -- the operator may proceed and is
#: told the number -- because "how big will your corpus get" is theirs to answer.
ADVISORY_FREE_BYTES = 5 * 1024**3


def env_file_path() -> Path:
    """``oo.env`` at the install root -- the file ``scripts/launch.sh`` sources.

    Derived from this module's location rather than the working directory: the app is
    launched from the launcher, from systemd, and from a test runner, and only the source
    tree's own position is the same in all three.
    """
    return Path(__file__).resolve().parents[2] / "oo.env"


def _filesystem_type(path: Path) -> str | None:
    """Reuses the forensics probe rather than re-deriving it: one answer about what a
    filesystem is, so the first-launch step and the persistence diagnostic can never
    disagree about the same folder."""
    from src.monitoring.forensics import _filesystem_type as probe

    return probe(path)


def _free_bytes(path: Path) -> int | None:
    import shutil

    target = path
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        return int(shutil.disk_usage(str(target)).free)
    except OSError:
        return None


def preflight(raw: str) -> dict[str, Any]:
    """Can the corpus live here, and what would the operator be taking on if it did?

    Returns ``usable`` plus every fact it managed to read. A refusal names the reason; a
    concern that is not a refusal (a volatile filesystem, little room) rides ``warnings``
    and does NOT block -- the operator may know something the probe cannot, and this
    project's standing posture is to state and let them decide, never to hard-block.

    An UNREADABLE fact is reported as unknown and never as a problem: "we could not tell
    how much room this drive has" and "this drive is full" are opposite findings, and only
    one of them is a reason not to proceed.

    Every warning and every refusal carries a ``code`` beside its English ``text``, because
    the first-launch page has to say these in twelve languages and a sentence with a path
    interpolated into it can never be a translation key.
    """
    text = (raw or "").strip()
    if not text:
        return {"usable": False, "reason_code": "empty",
                "reason": "no folder given", "input": raw}
    expanded = Path(text).expanduser()
    if not expanded.is_absolute():
        return {
            "usable": False,
            "reason_code": "not_absolute",
            "reason": "give an absolute path — a relative one depends on where the app "
                      "happens to be launched from, which is not the same every time",
            "input": raw,
        }

    target = expanded / DATA_SUBDIR
    # MACHINE-READABLE first. A warning composed as English prose here could never be
    # translated on the first-launch page (a flat t() lookup cannot match a sentence with
    # a path or a number interpolated into it), so each carries a ``code`` the page maps
    # onto its own keyed template, plus this module's own ``text`` for the readers that
    # are not the page -- the API, a log line, a diagnostic.
    warnings: list[dict[str, Any]] = []
    created_now = False
    try:
        existed = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        created_now = not existed
    except OSError as exc:
        return {
            "usable": False,
            "reason_code": "cannot_create",
            "reason": f"could not create {target}: {exc}",
            "input": raw,
            "path": str(target),
        }
    if not os.access(target, os.W_OK):
        _cleanup(target, created_now)
        return {"usable": False, "reason_code": "not_writable",
                "reason": f"{target} is not writable", "input": raw,
                "path": str(target)}

    # A folder that already holds a corpus is not a fresh location. Adopting it silently
    # would be the reverse of this module's whole point: the operator would be pointed at
    # someone else's (or their own older) encrypted store with a passphrase they are about
    # to choose for a store that does not exist.
    occupied = (target / "open_omniscience.db").exists()
    if occupied:
        warnings.append({
            "code": "already_has_a_corpus",
            "text": f"{target} already contains an Open Omniscience database. Using it "
                    "would open THAT corpus, which needs the passphrase it was created "
                    "with — not a new one.",
        })
    elif (expanded / "open_omniscience.db").exists():
        # The other way an operator arrives here: they pointed at an EXISTING data folder,
        # meaning "use this one". We would create `OOS data` INSIDE it, so their corpus
        # would sit unused one level up -- a silence that looks like the app losing it.
        # Told, not blocked: pointing OO_DATA_DIR at the folder itself is the way to reuse
        # a corpus, and that is a different action from choosing where a new one goes.
        warnings.append({
            "code": "parent_is_already_a_corpus",
            "text": f"{expanded} looks like an existing Open Omniscience data folder. "
                    f"Continuing creates a NEW, empty corpus in {target} and leaves that "
                    "one where it is. To reuse an existing corpus, point OO_DATA_DIR at "
                    "the folder itself instead.",
        })

    fs = _filesystem_type(target)
    if fs in _VOLATILE_FS:
        warnings.append({
            "code": "volatile_filesystem",
            "filesystem": fs,
            "text": f"this folder is on a {fs} (RAM-backed) filesystem, which is cleared "
                    "when the machine restarts — the corpus would not survive a reboot",
        })
    free = _free_bytes(target)
    if isinstance(free, int) and free < ADVISORY_FREE_BYTES:
        warnings.append({
            "code": "low_free_space",
            "free_gb": free // 1024**3,
            "text": f"about {free // 1024**3} GB free here; a corpus grows into tens of "
                    "GB, so this may fill up",
        })

    _cleanup(target, created_now)
    return {
        "usable": True,
        "input": raw,
        "path": str(target),
        "parent": str(expanded),
        "subdir": DATA_SUBDIR,
        "filesystem": fs,
        "free_bytes": free,
        "already_has_a_corpus": occupied,
        "warnings": warnings,
        "method": (
            "Creates the folder if it does not exist, checks it is writable, reads its "
            "filesystem type from /proc/mounts and its free space from statvfs. A fact "
            "that could not be read is reported as unknown, never as a problem."
        ),
    }


def _cleanup(target: Path, created_now: bool) -> None:
    """Leave the filesystem as we found it when the probe created the folder itself.

    A preflight is a QUESTION. An operator who types a path, is told it will not do, and
    then finds an empty "OOS data" folder sitting in it has been answered with a side
    effect. Only a directory this call made, and only while it is still empty.
    """
    if not created_now:
        return
    try:
        target.rmdir()
    except OSError:
        pass


def persist(raw: str) -> dict[str, Any]:
    """Record the choice in ``oo.env`` so the next launch uses it. Idempotent.

    Written the way ``install.sh:persist_data_dir`` writes it -- one ``export
    OO_DATA_DIR=`` line, shell-quoted, 0600, any previous line for the same variable
    replaced rather than appended to -- because ``scripts/launch.sh`` sources this file and
    a second line for the same variable would silently win over the first.

    Writes through a temp file in the same directory and ``os.replace``: a crash mid-write
    must leave the previous choice intact rather than a truncated env file that the next
    launch sources into a broken shell.
    """
    pre = preflight(raw)
    if not pre.get("usable"):
        return {"saved": False, **pre}

    target = Path(str(pre["path"]))
    target.mkdir(parents=True, exist_ok=True)
    env = env_file_path()
    kept = [
        ln
        for ln in (env.read_text(encoding="utf-8").splitlines() if env.exists() else [])
        if not ln.startswith("export OO_DATA_DIR=")
    ]
    kept.append(f"export OO_DATA_DIR={shlex.quote(str(target))}")
    body = "\n".join(kept) + "\n"

    fd, tmp_name = tempfile.mkstemp(prefix=".oo-env-", dir=str(env.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        # 0600, as install.sh records it. MEASURED redundant today and kept anyway,
        # with the measurement written down so nobody re-finds it as a survivor and
        # writes a vacuous test for it: `tempfile.mkstemp` already creates the file
        # 0600 (verified: it returns 0o600), and `os.replace` preserves the source
        # mode, so removing this line changes no outcome. It stays because it states
        # OUR requirement rather than inheriting the stdlib's -- the day this stops
        # going through mkstemp, the requirement is still here.
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, env)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return {"saved": False, "reason": f"could not write {env}: {exc}", **pre}

    return {
        "saved": True,
        "path": str(target),
        "env_file": str(env),
        "warnings": pre.get("warnings", []),
        "restart_required": True,
        "why_restart": (
            "The database URL is fixed when the app starts, so the new location takes "
            "effect on the next launch. Nothing has been written to the old folder yet, "
            "so nothing is left behind."
        ),
    }
