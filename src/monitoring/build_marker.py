"""Which build a session ran: the code's own markers, read without a subprocess.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (2026-10-01, crash findings on instance 091717, finding E). The session
ledger's boot records carried ``app_version`` and nothing else, and ``app_version`` does
not move between the commits of one release: every boot of that instance read ``0.4.0``
although the migration head changed between its two diagnostics bundles. So an UPDATE
read like a CRASH -- an end with no signal, then a boot -- and no crash could be
attributed to the build that had it.

WHAT IS RECORDED, on every boot record, as ``code``:
- ``git_head`` (and ``git_ref``): the checkout's commit, read as PLAIN FILES (``.git/HEAD``,
  the loose ref, or ``packed-refs``; a linked worktree's ``.git`` file is followed). Absent
  WITH A REASON where the install is not a checkout: a release archive carries no head, and
  an absent head is never written as an empty or invented one.
- ``migrations``: the number of migration scripts and a fingerprint of their file NAMES. A
  migration is added by (nearly) every update that changes the schema, so a changed
  fingerprint between two boots says "the code changed here" on an install with no git.
  It is a fingerprint of a directory listing, NOT the alembic head: the head needs alembic's
  script loader, which costs 0.2 to 0.4 s measured, and this runs on the boot path before
  unlock. The bundle's own ``schema_head`` (computed at export, off the boot path) says what
  the head is; this says only whether it moved.

NO SUBPROCESS, NO NETWORK, NO WRITE: a few small reads and one directory listing, well under
a millisecond on a warm disk. Every failure is a reason string, never an exception on the
boot path.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REF_NAME = re.compile(r"^refs/[A-Za-z0-9._/@+-]+$")


def _git_dirs(root: Path) -> tuple[Path | None, Path | None, str | None]:
    """(gitdir, commondir, reason). A linked worktree's ``.git`` is a FILE naming its gitdir;
    that gitdir's ``commondir`` file names where the shared refs live."""
    dot = root / ".git"
    try:
        if dot.is_dir():
            return dot, dot, None
        if dot.is_file():
            text = dot.read_text(encoding="utf-8", errors="replace").strip()
            if not text.startswith("gitdir:"):
                return None, None, "the .git file does not name a gitdir"
            gitdir = Path(text[len("gitdir:"):].strip())
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
            common = gitdir
            try:
                rel = (gitdir / "commondir").read_text(encoding="utf-8", errors="replace").strip()
                if rel:
                    common = Path(rel) if Path(rel).is_absolute() else (gitdir / rel).resolve()
            except OSError:
                pass
            return gitdir, common, None
    except OSError as exc:
        return None, None, f"the .git entry could not be read ({type(exc).__name__})"
    return None, None, "no .git next to the code: this install is not a git checkout (a release archive carries no head)"


def read_git_head(root: Path | None = None) -> dict[str, Any]:
    """The checkout's commit as ``{"git_head": sha, "git_ref": ref|None}``, or
    ``{"git_head": None, "reason": ...}`` saying why it could not be read."""
    root = root or _REPO_ROOT
    gitdir, common, why = _git_dirs(root)
    if gitdir is None or common is None:
        return {"git_head": None, "reason": why}
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        return {"git_head": None, "reason": f"HEAD could not be read ({type(exc).__name__})"}
    if _SHA.match(head):
        return {"git_head": head, "git_ref": None}  # a detached HEAD names the commit itself
    if not head.startswith("ref:"):
        return {"git_head": None, "reason": "HEAD is neither a commit nor a ref"}
    ref = head[len("ref:"):].strip()
    if not _REF_NAME.match(ref) or ".." in ref:
        return {"git_head": None, "reason": "HEAD names a ref in a form this reader does not follow"}
    # A loose ref wins over packed-refs, as git itself resolves them; a linked worktree keeps
    # its own HEAD but the shared refs in the common directory.
    for base in dict.fromkeys((gitdir, common)):
        try:
            loose = (base / ref).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if _SHA.match(loose):
            return {"git_head": loose, "git_ref": ref}
    try:
        packed = (common / "packed-refs").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"git_head": None, "git_ref": ref,
                "reason": f"HEAD names {ref}, which is not a loose ref here and there is no packed-refs to look in"}
    for line in packed:
        if not line or line[0] in "#^":
            continue
        sha, _, name = line.partition(" ")
        if name.strip() == ref and _SHA.match(sha):
            return {"git_head": sha, "git_ref": ref}
    return {"git_head": None, "git_ref": ref,
            "reason": f"HEAD names {ref}, which is neither a loose ref nor listed in packed-refs"}


def migrations_marker(root: Path | None = None) -> dict[str, Any]:
    """How many migration scripts there are and a fingerprint of their names, or the reason
    they could not be listed."""
    root = root or _REPO_ROOT
    try:
        names = sorted(p.name for p in (root / "migrations" / "versions").glob("*.py"))
    except OSError as exc:
        return {"count": None, "reason": f"the migrations directory could not be listed ({type(exc).__name__})"}
    if not names:
        return {"count": 0, "fingerprint": None, "reason": "no migration scripts were found next to the code"}
    digest = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:12]
    return {"count": len(names), "fingerprint": digest}


#: How the ``code`` block is read, said ONCE by the documents that carry it (the chronology): the block
#: sits on every boot record, and a sentence of this length repeated on each would be most of the line.
METHOD = (
    "plain file reads and one directory listing, no subprocess: the checkout's commit from "
    ".git (loose ref or packed-refs) and a fingerprint of the migration script names. The "
    "fingerprint says whether the schema code moved between two boots, not what the head is."
)


def code_markers(root: Path | None = None) -> dict[str, Any]:
    """The ``code`` block of a boot record. Never raises."""
    out: dict[str, Any] = {}
    try:
        out.update(read_git_head(root))
    except Exception as exc:  # noqa: BLE001 - a build marker never breaks a boot
        out.update({"git_head": None, "reason": f"the git head could not be read ({type(exc).__name__})"})
    try:
        out["migrations"] = migrations_marker(root)
    except Exception as exc:  # noqa: BLE001
        out["migrations"] = {"count": None, "reason": f"{type(exc).__name__}"}
    return out


_PROCESS_MARKERS: dict[str, Any] | None = None


def process_markers() -> dict[str, Any]:
    """The ``code`` block as THIS process first read it, kept for the life of the process.

    The boot record takes it at start, so every later reader (a run's ``begin`` line, a bundle)
    names the build that is RUNNING: a fresh read after a ``git pull`` without a restart would name
    code that is not the code the process loaded. Never raises."""
    global _PROCESS_MARKERS
    if _PROCESS_MARKERS is None:
        _PROCESS_MARKERS = code_markers()
    return _PROCESS_MARKERS


def reset_process_markers_for_tests() -> None:
    """Forget the cached block. Test-only."""
    global _PROCESS_MARKERS
    _PROCESS_MARKERS = None


def _fingerprint(block: dict[str, Any]) -> str | None:
    migrations = block.get("migrations")
    value = migrations.get("fingerprint") if isinstance(migrations, dict) else None
    return value if isinstance(value, str) and value else None


def changed_between(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str] | None:
    """Which markers differ between two boots' ``code`` blocks, or None when it cannot be said: either
    boot carries no block (an older ledger line), or no marker was readable on both boots and none of the
    readable ones moved -- unknown, never "unchanged".

    A marker is compared only when BOTH blocks carry it: a head that was unreadable on one boot (a ``None``
    beside a commit) says nothing about whether the code moved, and reading it as an update would put a
    crash that followed an unreadable boot under the heading "updated". By the same token it must not read
    as "unchanged" either: a marker that differs is reported whatever the others say, but when none differs
    and one was unreadable on ONE of the two boots (or on neither of them) the answer is None. A block
    whose ``migrations`` is not a mapping carries no fingerprint."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    diff: list[str] = []
    compared = unreadable_on_one = 0
    b_head, a_head = before.get("git_head"), after.get("git_head")
    b_has, a_has = isinstance(b_head, str) and bool(b_head), isinstance(a_head, str) and bool(a_head)
    if b_has and a_has:
        compared += 1
        if b_head != a_head:
            diff.append("git_head")
    elif b_has != a_has:
        unreadable_on_one += 1
    b_fp, a_fp = _fingerprint(before), _fingerprint(after)
    if b_fp and a_fp:
        compared += 1
        if b_fp != a_fp:
            diff.append("migrations")
    elif bool(b_fp) != bool(a_fp):
        unreadable_on_one += 1
    if diff:
        return diff
    return None if unreadable_on_one or not compared else []
