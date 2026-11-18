"""Built SKOS thesauri in the data directory, and the check the app runs before it uses one (R737, row 119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A thesaurus is built on the operator's machine by ``scripts/thesaurus_build.py`` from a SKOS file
the operator downloaded (or fetched by the script, only when asked and only from the publisher's
host). The build writes two files into ``<data dir>/thesauri/``:

* ``<scheme>.json``: the thesaurus itself (``src.catalog.skos.build_artifact``'s document, plus
  ``format`` and the source's hash), written byte-for-byte the same for the same source and options;
* ``<scheme>.summary.json``: what the build saw (counts, the source and output hashes, the format
  and the tool version). It is small on purpose: it is the one file the operator sends back.

NOTHING IS USED UNCHECKED. :func:`thesaurus_status` reads both and returns ONE state, with a reason:

``ok``            the file is there, its format is the one this code reads, and its SHA-256 is the one
                  its build recorded;
``missing``       not built on this computer (the normal state until the operator builds it);
``unreadable``    the file is there but is not a thesaurus this code can read;
``old_format``    built by an older build tool, whose format this code no longer reads;
``hash_mismatch`` the file changed after its build (edited, truncated, or another file copied over it);
``unverified``    the build summary is missing or unreadable, so the hash cannot be checked.

Only ``ok`` is loaded (:func:`load_thesaurus`); every other state is set aside and SAID, never read
around. The release date (``vintage``) is reported as it is: how old is too old is not ruled, so no
age is called stale here. Nothing in this module opens a socket.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from pathlib import Path
from typing import Any

from src.catalog import skos

#: The thesaurus file's own format. Raise it when the build writes something older readers would misread;
#: a file of another format is set aside as ``old_format`` and the operator is told to build it again.
FORMAT_VERSION = 1

#: The build tool's version, recorded in every summary (a change to how the tool reads or writes moves it).
BUILD_TOOL_VERSION = "1"

STATES = ("ok", "missing", "unreadable", "old_format", "hash_mismatch", "unverified")

_DISPLAY_NAMES = {
    "eurovoc": "EuroVoc",
    "unesco-thesaurus": "UNESCO Thesaurus",
    "agrovoc": "AGROVOC",
    "iptc-media-topics": "IPTC Media Topics",
}

_lock = threading.Lock()
#: A file's identity for the memos: size, mtime, inode and ctime. ctime cannot be set from user space, so a file
#: rewritten to the same size with its old mtime put back still misses the memo, where ctime is a change time (see below).
_Stamp = tuple[int, int, int, int]
#: Whether ``st_ctime_ns`` is a change time the user cannot set. On Windows it is the CREATION time, which a same-size rewrite
#: with its old mtime put back leaves as it was (row 150, measured on the Windows CI leg), so there the hash is never taken
#: from the memo: it is read again on every status, and the out-of-date "ok" that the memo would give cannot be said.
_CHANGE_TIME_IS_TRUSTED = os.name != "nt"
_hash_memo: dict[str, tuple[_Stamp, str]] = {}  # path -> (stamp, sha256)
_head_memo: dict[str, tuple[_Stamp, dict[str, Any] | None]] = {}  # path -> (stamp, head or None)
#: The largest thesaurus or summary read (a guard against a file that is not one: EuroVoc in five languages is tens of MB).
MAX_FILE_BYTES = 512 * 1024 * 1024
#: What a file that cannot be read as a thesaurus raises here: OSError, a JSON or UTF-8 error (ValueError), and the
#: parser's RecursionError on deeply nested input.
_READ_ERRORS = (OSError, ValueError, RecursionError)
_HEAD_KEYS = ("scheme", "vintage", "license", "n_concepts", "languages", "format")


def thesauri_dir(base: Path | None = None) -> Path:
    """``<data dir>/thesauri`` (not created here: reading never writes)."""
    if base is not None:
        return Path(base)
    from src.paths import data_dir

    return data_dir() / "thesauri"


def thesaurus_path(scheme: str, base: Path | None = None) -> Path:
    _known(scheme)
    return thesauri_dir(base) / f"{scheme}.json"


def summary_path(scheme: str, base: Path | None = None) -> Path:
    _known(scheme)
    return thesauri_dir(base) / f"{scheme}.summary.json"


def _known(scheme: str) -> None:
    if scheme not in skos.SCHEMES:
        raise skos.SkosError(f"unknown scheme {scheme!r}; known: {', '.join(skos.SCHEMES)}")


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in blocks (a thesaurus is several MB)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _stamp(path: Path) -> _Stamp:
    """The memo key of a regular file, refusing anything else (a FIFO would block, a device never ends) and a file
    larger than :data:`MAX_FILE_BYTES`."""
    st = path.stat()
    if not stat.S_ISREG(st.st_mode):
        raise OSError(f"{path.name} is not a regular file")
    if st.st_size > MAX_FILE_BYTES:
        raise OSError(f"{path.name} is larger than {MAX_FILE_BYTES} bytes")
    return (st.st_size, st.st_mtime_ns, st.st_ino, st.st_ctime_ns)


def _hash_cached(path: Path) -> str:
    stamp = _stamp(path)
    key = str(path)
    with _lock:
        hit = _hash_memo.get(key)
        if hit and hit[0] == stamp and _CHANGE_TIME_IS_TRUSTED:
            return hit[1]
    digest = sha256_file(path)
    with _lock:
        _hash_memo[key] = (stamp, digest)
    return digest


def _read_head(path: Path) -> dict[str, Any] | None:
    """The file's top-level fields (not its concepts), or ``None`` when it is not a thesaurus document.

    Memoised by size and mtime like the hash: a thesaurus is several MB, and the status is read on every view.
    Raises one of :data:`_READ_ERRORS` for a file that cannot be read as JSON (not memoised: said each time)."""
    stamp = _stamp(path)
    key = str(path)
    with _lock:
        hit = _head_memo.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    head = ({k: doc.get(k) for k in _HEAD_KEYS} if isinstance(doc, dict) and isinstance(doc.get("concepts"), dict)
            else None)
    with _lock:
        _head_memo[key] = (stamp, head)
    return head


def canonical_bytes(doc: dict[str, Any]) -> bytes:
    """The one serialisation the build writes: sorted keys, no spaces, UTF-8, one final newline.

    With the build's sorted label lists and gaps, the same source and options give the same bytes,
    so the same SHA-256 on any machine.
    """
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


#: Every reason the status can give, as a translatable template (R737: a reason is shown to the reader, so it ships in
#: the twelve UI languages). The server sends the template and its parameters; ``reason`` is the English text, kept for
#: scripts and as the page's fallback. Parameters are file names, a scheme, a format, hash prefixes and an error's class
#: name: never a path.
REASONS = {
    "missing": "There is no {file} in the data folder's thesauri folder. Run scripts/thesaurus_build.py to build it.",
    "unreadable": "{file} cannot be read as a thesaurus ({error}).",
    "not_thesaurus": "{file} is not a built {scheme} thesaurus.",
    "old_format": "{file} has format {found}; this version reads format {expected}. Build it again.",
    "unverified": "The build summary {summary} is missing or unreadable ({error}), so the hash cannot be checked.",
    "hash_mismatch": "{file} has SHA-256 {actual}…, but its build recorded {recorded}…. Build it again.",
    "changed_while_read": "{file} changed while it was being read. Read it again.",
}


def _said(state: str, which: str, **params: Any) -> dict[str, Any]:
    params = {k: str(v) for k, v in params.items()}
    template = REASONS[which]
    return {"state": state, "reason": template.format(**params), "reason_key": template, "reason_params": params}


def thesaurus_status(scheme: str, base: Path | None = None) -> dict[str, Any]:
    """The one state of ``scheme``'s built file, with its reason and what the build recorded."""
    path, spath = thesaurus_path(scheme, base), summary_path(scheme, base)
    out: dict[str, Any] = {"scheme": scheme, "name": _DISPLAY_NAMES.get(scheme, scheme), "format_expected": FORMAT_VERSION}
    if not path.exists():
        return {**out, **_said("missing", "missing", file=path.name)}
    try:
        head = _read_head(path)
    except _READ_ERRORS as exc:
        return {**out, **_said("unreadable", "unreadable", file=path.name, error=type(exc).__name__)}
    if head is None or head.get("scheme") != scheme:
        return {**out, **_said("unreadable", "not_thesaurus", file=path.name, scheme=scheme)}
    out.update(vintage=head.get("vintage"), license=head.get("license"), n_concepts=head.get("n_concepts"),
               languages=head.get("languages"), format=head.get("format"))
    if head.get("format") != FORMAT_VERSION:
        return {**out, **_said("old_format", "old_format", file=path.name, found=repr(head.get("format"))[:40],
                               expected=FORMAT_VERSION)}
    try:
        _stamp(spath)
        summary = json.loads(spath.read_text(encoding="utf-8"))
        recorded = summary["output"]["sha256"]
        if not isinstance(recorded, str):
            raise TypeError("no string output.sha256")
    except (*_READ_ERRORS, KeyError, TypeError) as exc:
        return {**out, **_said("unverified", "unverified", summary=spath.name, error=type(exc).__name__)}
    out["built_at_tool"] = summary.get("tool_version")
    try:
        actual = _hash_cached(path)
    except OSError as exc:  # removed or replaced by something else since the read above
        return {**out, **_said("unreadable", "unreadable", file=path.name, error=type(exc).__name__)}
    out["sha256"] = actual
    if actual != recorded:
        return {**out, **_said("hash_mismatch", "hash_mismatch", file=path.name, actual=actual[:12],
                               recorded=recorded[:12])}
    return {**out, "state": "ok", "reason": ""}


def load_thesaurus(scheme: str, base: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(artifact, status)``: the artifact only when the status is ``ok``; otherwise ``None`` and the reason."""
    status = thesaurus_status(scheme, base)
    if status["state"] != "ok":
        return None, status
    # The bytes parsed are the bytes hashed: a file replaced between the check and the read is caught here.
    path = thesaurus_path(scheme, base)
    _stamp(path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != status["sha256"]:
        return None, {**status, **_said("hash_mismatch", "changed_while_read", file=path.name)}
    doc = json.loads(data.decode("utf-8"))
    if (not isinstance(doc, dict) or not isinstance(doc.get("concepts"), dict) or doc.get("scheme") != scheme
            or doc.get("format") != FORMAT_VERSION):
        return None, {**status, **_said("unreadable", "not_thesaurus", file=path.name, scheme=scheme)}
    return doc, status


def statuses(base: Path | None = None) -> list[dict[str, Any]]:
    """Every known scheme's status, in :data:`src.catalog.skos.SCHEMES` order."""
    out = []
    for s in skos.SCHEMES:
        try:
            out.append(thesaurus_status(s, base))
        except Exception as exc:  # noqa: BLE001 - one bad file never takes the whole list down
            out.append({"scheme": s, "name": _DISPLAY_NAMES.get(s, s), "format_expected": FORMAT_VERSION,
                        **_said("unreadable", "unreadable", file=f"{s}.json", error=type(exc).__name__)})
    return out
