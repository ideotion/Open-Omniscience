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
_hash_memo: dict[str, tuple[int, int, str]] = {}  # path -> (size, mtime_ns, sha256)
_head_memo: dict[str, tuple[int, int, dict[str, Any] | None]] = {}  # path -> (size, mtime_ns, head or None)
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


def _hash_cached(path: Path) -> str:
    st = path.stat()
    key = str(path)
    with _lock:
        hit = _hash_memo.get(key)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
            return hit[2]
    digest = sha256_file(path)
    with _lock:
        _hash_memo[key] = (st.st_size, st.st_mtime_ns, digest)
    return digest


def _read_head(path: Path) -> dict[str, Any] | None:
    """The file's top-level fields (not its concepts), or ``None`` when it is not a thesaurus document.

    Memoised by size and mtime like the hash: a thesaurus is several MB, and the status is read on every view.
    Raises ``OSError``/``ValueError`` for a file that cannot be read as JSON (not memoised: said each time)."""
    st = path.stat()
    key = str(path)
    with _lock:
        hit = _head_memo.get(key)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
            return hit[2]
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    head = ({k: doc.get(k) for k in _HEAD_KEYS} if isinstance(doc, dict) and isinstance(doc.get("concepts"), dict)
            else None)
    with _lock:
        _head_memo[key] = (st.st_size, st.st_mtime_ns, head)
    return head


def canonical_bytes(doc: dict[str, Any]) -> bytes:
    """The one serialisation the build writes: sorted keys, no spaces, UTF-8, one final newline.

    With the build's sorted label lists and gaps, the same source and options give the same bytes,
    so the same SHA-256 on any machine.
    """
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def thesaurus_status(scheme: str, base: Path | None = None) -> dict[str, Any]:
    """The one state of ``scheme``'s built file, with its reason and what the build recorded."""
    path, spath = thesaurus_path(scheme, base), summary_path(scheme, base)
    out: dict[str, Any] = {"scheme": scheme, "name": _DISPLAY_NAMES.get(scheme, scheme), "format_expected": FORMAT_VERSION}
    if not path.exists():
        return {**out, "state": "missing",
                "reason": f"no {path.name} in the data directory's thesauri folder: run scripts/thesaurus_build.py"}
    try:
        head = _read_head(path)
    except (OSError, ValueError) as exc:
        return {**out, "state": "unreadable", "reason": f"{path.name} is not readable JSON ({type(exc).__name__})"}
    if head is None or head.get("scheme") != scheme:
        return {**out, "state": "unreadable", "reason": f"{path.name} is not a built {scheme} thesaurus"}
    out.update(vintage=head.get("vintage"), license=head.get("license"), n_concepts=head.get("n_concepts"),
               languages=head.get("languages"), format=head.get("format"))
    if head.get("format") != FORMAT_VERSION:
        return {**out, "state": "old_format",
                "reason": f"{path.name} has format {head.get('format')!r}; this version reads format {FORMAT_VERSION}"}
    try:
        summary = json.loads(spath.read_text(encoding="utf-8"))
        recorded = summary["output"]["sha256"]
        if not isinstance(recorded, str):
            raise TypeError("no string output.sha256")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**out, "state": "unverified",
                "reason": f"{spath.name} is missing or unreadable ({type(exc).__name__}), so the hash cannot be checked"}
    out["built_at_tool"] = summary.get("tool_version")
    actual = _hash_cached(path)
    out["sha256"] = actual
    if actual != recorded:
        return {**out, "state": "hash_mismatch",
                "reason": f"{path.name} has SHA-256 {actual[:12]}…, its build recorded {recorded[:12]}…"}
    return {**out, "state": "ok", "reason": ""}


def load_thesaurus(scheme: str, base: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """``(artifact, status)``: the artifact only when the status is ``ok``; otherwise ``None`` and the reason."""
    status = thesaurus_status(scheme, base)
    if status["state"] != "ok":
        return None, status
    # The bytes parsed are the bytes hashed: a file replaced between the check and the read is caught here.
    data = thesaurus_path(scheme, base).read_bytes()
    if hashlib.sha256(data).hexdigest() != status["sha256"]:
        return None, {**status, "state": "hash_mismatch",
                      "reason": f"{scheme}.json changed while it was being read; read it again"}
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict) or "concepts" not in doc or doc.get("scheme") != scheme:
        return None, {**status, "state": "unreadable", "reason": f"{scheme}.json is not a built {scheme} thesaurus"}
    return doc, status


def statuses(base: Path | None = None) -> list[dict[str, Any]]:
    """Every known scheme's status, in :data:`src.catalog.skos.SCHEMES` order."""
    return [thesaurus_status(s, base) for s in skos.SCHEMES]
