"""Which build a session ran (2026-10-07), so an update reads as an update and not as a crash.

A boot record used to say the app version and nothing finer, and two builds of one version (a branch between releases, a
patched checkout) were the same build to every reader. ``build_identity`` is:

* ``source_fingerprint``: the SHA-256 (first 16 hex digits) of the bytes of every ``*.py`` file under the app's ``src/``,
  each preceded by its relative path, in path order. A hash of the BYTES, not of names and sizes: an edit that keeps the
  size changes it. ``files`` and ``bytes`` say how much was hashed;
* ``commit``: the checkout's HEAD, read from ``.git`` with no subprocess (``null`` where there is no checkout, as in an
  installed copy), with ``dirty`` never claimed: the fingerprint is what says the tree differs;
* ``schema_head``: the migration scripts' head revision (``null`` when it cannot be read);
* ``took_ms``: what reading it cost, once per process (the result is kept).

Never raises; a part that cannot be read is ``null``, never a guess.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

_CACHE: dict[str, Any] | None = None


def _src_root() -> Path:
    return Path(__file__).resolve().parents[1]


def source_fingerprint(root: Path | None = None) -> dict[str, Any]:
    """``{"source_fingerprint", "files", "bytes"}`` over the ``*.py`` files under ``root`` (default: the app's ``src``)."""
    base = root or _src_root()
    digest = hashlib.sha256()
    files = total = 0
    for path in sorted(base.rglob("*.py"), key=lambda p: p.relative_to(base).as_posix()):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest.update(path.relative_to(base).as_posix().encode("utf-8") + b"\0")
        digest.update(data)
        digest.update(b"\0")
        files += 1
        total += len(data)
    return {"source_fingerprint": digest.hexdigest()[:16], "files": files, "bytes": total}


_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _sha(text: str) -> str | None:
    """``text`` when it is a whole object id (40 hex characters, or 64 in a repository that uses SHA-256), else ``None``: an id is
    never cut, and a text that is not one is not recorded as one."""
    text = text.strip().lower()
    return text if _SHA.match(text) else None


def git_commit(repo: Path | None = None) -> str | None:
    """HEAD of the checkout at ``repo`` (default: the app's parent directory), read from ``.git`` without a subprocess."""
    try:
        git = (repo or _src_root().parent) / ".git"
        if git.is_file():  # a worktree or a submodule: ``gitdir: <path>``, relative to the directory the ``.git`` file is in
            line = git.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir:"):
                return None
            target = Path(line.split(":", 1)[1].strip())
            git = target if target.is_absolute() else git.parent / target
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return _sha(head)
        ref = head.split(":", 1)[1].strip()
        loose = git / ref
        if loose.is_file():
            return _sha(loose.read_text(encoding="utf-8"))
        common = git / "commondir"
        roots = [git] + ([git / common.read_text(encoding="utf-8").strip()] if common.is_file() else [])
        for root in roots:
            packed = root / "packed-refs"
            if packed.is_file():
                for row in packed.read_text(encoding="utf-8").splitlines():
                    if row.endswith(" " + ref) and not row.startswith("#"):
                        return _sha(row.split(" ", 1)[0])
            candidate = root / ref
            if candidate.is_file():
                return _sha(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return None


_REVISION = re.compile(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
_DOWN_REVISION = re.compile(r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*([^\n]*)", re.MULTILINE)


def schema_head(versions: Path | None = None) -> str | None:
    """The migration scripts' head revision, read from the scripts' own ``revision`` and ``down_revision`` lines (the one revision
    no other names as its parent), or ``None`` when there is not exactly one. Alembic's own API answers the same and costs half
    a second of imports at every boot, which this record is not worth; ``tests/test_build_id.py`` pins the two to agree."""
    try:
        folder = versions or (_src_root().parent / "migrations" / "versions")
        revisions: set[str] = set()
        parents: set[str] = set()
        for path in folder.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            own = _REVISION.search(text)
            if own is None:
                continue
            revisions.add(own.group(1))
            down = _DOWN_REVISION.search(text)
            if down is not None:
                parents.update(re.findall(r"[\"']([^\"']+)[\"']", down.group(1)))
        heads = revisions - parents
        return next(iter(heads)) if len(heads) == 1 else None
    except (OSError, ValueError):
        return None


def build_identity() -> dict[str, Any]:
    """This build's identity (see the module docstring), read once per process."""
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    t0 = time.perf_counter()
    out: dict[str, Any] = {"commit": git_commit()}
    try:
        out.update(source_fingerprint())
    except Exception:  # noqa: BLE001
        out.update({"source_fingerprint": None, "files": None, "bytes": None})
    out["schema_head"] = schema_head()
    out["took_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    _CACHE = out
    return dict(out)


def _reset_for_tests() -> None:
    global _CACHE
    _CACHE = None
