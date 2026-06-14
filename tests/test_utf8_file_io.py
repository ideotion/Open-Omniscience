"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

PORTABILITY RATCHET: every text file read/write in ``src/`` must pass an explicit
``encoding="utf-8"`` — the builtin ``open()`` AND pathlib's ``Path.read_text`` /
``Path.write_text``.

Why a STATIC test and not a behavioural one: on Linux/macOS the default text
encoding is already UTF-8, so an un-annotated read works fine — the bug is
INVISIBLE on the Linux CI that gates merges. On Windows the default is cp1252,
so the same call dies with ``UnicodeDecodeError: 'charmap' codec can't decode
byte ...`` the moment a file holds a non-ASCII byte (an accented source name in
``configs/sources.yml``, a glyph in ``index.html``). The Windows portability
lane caught exactly this. Only a static scan can keep it from regressing, since
the green path hides it here.

Coverage note: the first cut of this ratchet only checked the builtin ``open()``
and MISSED ``yaml.safe_load(path.read_text())`` in the seed-catalog loader — the
real ``position 71598`` crash. So ``read_text``/``write_text`` are now in scope
too.

Out of scope, deliberately:
- Binary opens (``"rb"``/``"wb"``/``"ab"`` …) — encoding is meaningless for bytes.
- Opens whose mode is a *computed* expression (e.g. ``open(dest, mode)`` in the
  dump downloader, where ``mode`` is ``"ab"``/``"wb"``) — can't be classified
  statically; they must stay binary by construction.
- ``.open()`` METHOD calls — too ambiguous to classify statically (``Image.open``
  on a ``BytesIO``, ``tarfile.open``, ``gzip.open`` … are not text-file opens).
  The builtin ``open()`` covers the file-open case; there are currently no
  text-mode ``Path.open()`` calls to catch.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# The Windows lane RUNS the tests, so a test file's bare read_text() crashes it
# just like production code — scan both trees.
_SCANNED = ("src", "tests")


def _builtin_open_offender(node: ast.Call) -> bool:
    """A builtin ``open(...)`` in text mode without an explicit encoding."""
    if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
        return False
    mode_node: ast.expr | None = None
    if len(node.args) >= 2:
        mode_node = node.args[1]
    for kw in node.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    has_encoding = any(kw.arg == "encoding" for kw in node.keywords)

    if mode_node is None:
        is_text = True  # no mode -> text default
    elif isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        is_text = "b" not in mode_node.value
    else:
        return False  # computed mode: can't classify; must stay binary

    return is_text and not has_encoding


def _read_write_text_offender(node: ast.Call) -> bool:
    """``Path.read_text()`` / ``Path.write_text()`` without an explicit encoding.

    ``read_text(encoding=None, errors=None)`` -> encoding is positional arg 0.
    ``write_text(data, encoding=None, ...)`` -> encoding is positional arg 1.
    """
    if not (isinstance(node.func, ast.Attribute) and node.func.attr in ("read_text", "write_text")):
        return False
    if any(kw.arg == "encoding" for kw in node.keywords):
        return False
    enc_pos = 0 if node.func.attr == "read_text" else 1
    return len(node.args) <= enc_pos


def _offenders() -> list[str]:
    bad: list[str] = []
    for sub in _SCANNED:
        for path in (_ROOT / sub).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if _builtin_open_offender(node) or _read_write_text_offender(node):
                    bad.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    return bad


def test_all_text_io_declares_utf8_encoding() -> None:
    offenders = _offenders()
    assert not offenders, (
        "text file read/write without encoding='utf-8' (crashes on Windows/cp1252 "
        "for any non-ASCII byte): " + ", ".join(offenders)
    )
