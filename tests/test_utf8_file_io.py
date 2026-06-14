"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

PORTABILITY RATCHET: every text-mode ``open()`` in ``src/`` must pass an explicit
``encoding="utf-8"``.

Why a STATIC test and not a behavioural one: on Linux/macOS the default text
encoding is already UTF-8, so an un-annotated ``open()`` reads our catalogs and
templates fine — the bug is INVISIBLE on the Linux CI that gates merges. On
Windows the default is cp1252, so the same call dies with
``UnicodeDecodeError: 'charmap' codec can't decode byte ...`` the moment a file
holds a non-ASCII byte (an accented source name in ``configs/sources.yml``, a
glyph in ``index.html``). The Windows portability lane caught exactly this. Only
a static scan can keep it from regressing, since the green path hides it here.

Binary opens (``"rb"``/``"wb"``/``"ab"`` …) are exempt — encoding is meaningless
for bytes. Opens whose mode is a *computed* expression (e.g. ``open(dest, mode)``
in the dump downloader, where ``mode`` is ``"ab"``/``"wb"``) can't be classified
statically, so they're skipped here and must stay binary by construction.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"


def _offenders() -> list[str]:
    bad: list[str] = []
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            ):
                continue
            # Locate the mode argument (2nd positional or mode=...).
            mode_node: ast.expr | None = None
            if len(node.args) >= 2:
                mode_node = node.args[1]
            for kw in node.keywords:
                if kw.arg == "mode":
                    mode_node = kw.value
            has_encoding = any(kw.arg == "encoding" for kw in node.keywords)

            if mode_node is None:
                # No mode arg -> text mode by default -> needs an explicit encoding.
                is_text = True
            elif isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
                is_text = "b" not in mode_node.value
            else:
                # Computed mode: can't classify statically; must stay binary.
                continue

            if is_text and not has_encoding:
                rel = path.relative_to(_SRC.parent)
                bad.append(f"{rel}:{node.lineno}")
    return bad


def test_all_text_opens_declare_utf8_encoding() -> None:
    offenders = _offenders()
    assert not offenders, (
        "text-mode open() without encoding='utf-8' (crashes on Windows/cp1252 "
        "for any non-ASCII byte): " + ", ".join(offenders)
    )
