"""The scanner behind ``tests/test_no_raw_exc_info.py``: finds the log calls that write an exception the way it made its own message.

``exc_info=True`` (and ``Logger.exception``) hand the log record a live exception whose text and traceback a handler formats
with no scrub: a keyed open's driver error chains the passphrase, and ``data/app_errors.jsonl`` rides the diagnostics bundle.
``secret_scrub.log_failure`` is the one way a failure is logged; this finds everything else."""

from __future__ import annotations

import ast
from pathlib import Path

#: Names a logger is bound to in this code base (``log``, ``_LOG``, ``logger``, ``logging`` itself, ``self.log``...).
_LOGGER_HINTS = ("log", "logger", "logging")
#: ``traceback`` helpers that turn an exception into text: in a log argument they are the same sink as ``exc_info``.
_TEXT_MAKERS = {
    "format_exc",
    "print_exc",
    "format_exception",
    "print_exception",
    "format_tb",
    "print_tb",
}
#: The modules that ARE the scrub (they read an exception to scrub it) or read a record's ``exc_info`` back; nothing else.
EXEMPT = {"src/monitoring/secret_scrub.py", "src/monitoring/errorlog.py"}


def _receiver(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id.lower().lstrip("_")
    if isinstance(node, ast.Attribute):
        return node.attr.lower().lstrip("_")
    return ""


def _is_logger(node: ast.expr) -> bool:
    name = _receiver(node)
    return bool(name) and any(h in name for h in _LOGGER_HINTS)


def _falsy(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and not node.value


def scan_source(text: str) -> list[tuple[int, str]]:
    """Every (line, kind) in ``text`` that writes an exception unscrubbed."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        for kw in node.keywords:
            if kw.arg == "exc_info" and not _falsy(kw.value):
                found.append((node.lineno, "exc_info"))
        if isinstance(func, ast.Attribute):
            if func.attr == "exception" and _is_logger(func.value):
                found.append((node.lineno, "exception"))
            if func.attr == "exc_info" and _receiver(func.value) == "sys":
                found.append((node.lineno, "sys.exc_info"))
            if func.attr in _TEXT_MAKERS and _receiver(func.value) == "traceback":
                found.append((node.lineno, func.attr))
        elif isinstance(func, ast.Name) and func.id in _TEXT_MAKERS:
            found.append((node.lineno, func.id))
    return sorted(set(found))


def scan_tree(root: Path) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in EXEMPT:
            continue
        hits = scan_source(path.read_text(encoding="utf-8"))
        if hits:
            out[rel] = hits
    return out
