"""The scanner behind ``tests/test_no_raw_exc_info.py``: finds the log calls that write an exception the way it made its own message.

``exc_info=True`` (and ``Logger.exception``) hand the log record a live exception whose text and traceback a handler formats
with no scrub: a keyed open's driver error chains the passphrase, and ``data/app_errors.jsonl`` rides the diagnostics bundle.
``secret_scrub.log_failure`` is the one way a failure is logged; this finds everything else.

WHAT IT SEES: ``exc_info=`` with any value but a false constant; ``**`` unpacked into a log call and the string ``"exc_info"``
used as a key (the same keyword by another door); ``.exception(msg)`` on ANY receiver (a ``Future``'s ``.exception()`` takes no
message, a logger's always does) and ``logging.exception``; and the ``traceback`` / ``sys`` text makers
(:data:`TRACEBACK_MAKERS`, :data:`SYS_MAKERS`), resolved through the file's own imports so ``import traceback as tb`` and
``from sys import exc_info`` are the same sink. Every call node counts once, so two sinks on one line are two.

ALSO ``exc-arg``: inside an ``except ... as name`` block, a log-method call (``debug`` ... ``critical``, ``log``, on ANY receiver) with
an argument that carries ``name`` by any route but its class (``type(name)``, ``name.__class__``) or a scrub helper
(:data:`SCRUB_HELPERS`): ``name``, ``str(name)[:200]``, ``"%s" % name``, ``.format(name)``, ``name.args``, ``name.__cause__``,
f-strings. Those write the engine's own words with no scrub. Not followed: ``e = name`` rebinding, and non-log text sinks (``print``).

WHAT IT DOES NOT: ``stack_info=True`` prints the current call stack (files, lines, source), not an exception, so it cannot carry
the words an exception carries; ``log.warning("%s", exc)`` is a different rule (the text made by hand), covered where the text
enters a record. A swap inside one file (one site converted, another added) keeps its count; the diff is where that is read."""

from __future__ import annotations

import ast
from pathlib import Path

#: ``traceback`` helpers that turn an exception into text or print it: in a log argument they are the same sink as ``exc_info``.
TRACEBACK_MAKERS = frozenset(
    {
        "format_exc",
        "print_exc",
        "format_exception",
        "format_exception_only",
        "print_exception",
        "format_tb",
        "print_tb",
        "TracebackException",
    }
)
#: ``sys`` readers of the exception being handled.
SYS_MAKERS = frozenset({"exc_info", "exception"})
SYS_ATTRIBUTES = frozenset({"last_exc", "last_value", "last_traceback"})
_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "critical", "exception", "log", "fatal"}
)
#: The modules that ARE the scrub (they read an exception to scrub it) or read a record's ``exc_info`` back; nothing else.
EXEMPT = {"src/monitoring/secret_scrub.py", "src/monitoring/errorlog.py"}


#: Calls that take an exception and write it through the scrub (or write its class): an argument inside one of these is safe.
SCRUB_HELPERS = frozenset(
    {
        "log_failure",
        "exception_text",
        "engine_text",
        "failure_label",
        "tidy_error",
        "exc_line",
        "traceback_text",
        "scrubbed",
        "scrubbed_value",
        "type",
    }
)


def _call_name(call: ast.Call) -> str:
    return (
        call.func.id
        if isinstance(call.func, ast.Name)
        else call.func.attr
        if isinstance(call.func, ast.Attribute)
        else ""
    )


def _unsafe_uses(arg: ast.expr, name: str) -> bool:
    """Is the handler's exception ``name`` used anywhere in ``arg`` other than as its class (``type(name)``, ``name.__class__``) or
    inside a scrub helper's arguments? ``str(name)[:200]``, ``"%s" % name``, ``name.args``, ``name.__cause__``, ``"a" + str(name)``
    and ``.format(name)`` are all uses. A name the handler rebinds (``e = name``) is not followed."""
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(arg):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(arg):
        if not (isinstance(node, ast.Name) and node.id == name):
            continue
        cursor: ast.AST = node
        safe = False
        while cursor in parents:
            above = parents[cursor]
            if isinstance(above, ast.Attribute) and above.attr == "__class__":
                safe = True
                break
            if isinstance(above, ast.Call) and _call_name(above) in SCRUB_HELPERS:
                safe = True
                break
            cursor = above
        if not safe:
            return True
    return False


def _exception_arguments(tree: ast.AST) -> list[tuple[int, str]]:
    """Inside ``except ... as name``, a log-method call (any receiver: ``getLogger(...).warning``, ``lg``, ``self.logs[0]``) with an
    argument, positional or keyword, that carries ``name`` by any route but its class or a scrub helper."""
    found: list[tuple[int, str]] = []
    for handler in ast.walk(tree):
        if not (isinstance(handler, ast.ExceptHandler) and handler.name):
            continue
        for node in (n for stmt in handler.body for n in ast.walk(stmt)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
            ):
                continue
            values = [*node.args, *(k.value for k in node.keywords)]
            if any(_unsafe_uses(v, handler.name) for v in values):
                found.append((node.lineno, "exc-arg"))
    return found


def _falsy(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and not node.value


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> the dotted thing it stands for, for the two modules whose readers are sinks."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in {"traceback", "sys", "logging"}:
                    out[a.asname or a.name] = a.name
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module in {"traceback", "sys", "logging"}
            and node.level == 0
        ):
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _qualified(node: ast.expr, alias: dict[str, str]) -> str:
    """``tb.format_exc`` -> ``traceback.format_exc`` through the file's imports; "" when it is not one of them."""
    if isinstance(node, ast.Name):
        return alias.get(node.id, "")
    if isinstance(node, ast.Attribute):
        base = _qualified(node.value, alias)
        return f"{base}.{node.attr}" if base else ""
    return ""


def scan_source(text: str, name: str = "<source>") -> list[tuple[int, str]]:
    """Every (line, kind) in ``text`` that writes an exception unscrubbed, one per offending node."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise SyntaxError(
            f"{name}: the exception-sink guard cannot parse it ({exc.msg}, line {exc.lineno})"
        ) from None
    alias = _aliases(tree)
    found: list[tuple[int, str]] = _exception_arguments(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "exc_info":
            found.append((node.lineno, "exc_info-key"))
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in SYS_ATTRIBUTES
            and _qualified(node, alias) == f"sys.{node.attr}"
        ):
            found.append((node.lineno, "sys." + node.attr))
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        method = func.attr if isinstance(func, ast.Attribute) else ""
        for kw in node.keywords:
            if kw.arg == "exc_info" and not _falsy(kw.value):
                found.append((node.lineno, "exc_info"))
            elif kw.arg is None and method in _LOG_METHODS:
                found.append((node.lineno, "kwargs-unpack"))
        qual = _qualified(func, alias)
        mod, _, leaf = qual.rpartition(".")
        if qual == "logging.exception" or (
            method == "exception" and (node.args or any(k.arg == "msg" for k in node.keywords))
        ):
            found.append((node.lineno, "exception"))
        elif qual.startswith("traceback.TracebackException."):
            found.append((node.lineno, "TracebackException"))
        elif mod == "traceback" and leaf in TRACEBACK_MAKERS:
            found.append((node.lineno, leaf))
        elif mod == "sys" and leaf in SYS_MAKERS:
            found.append((node.lineno, "sys." + leaf))
    return sorted(found)


def scan_tree(root: Path) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in EXEMPT:
            continue
        hits = scan_source(path.read_text(encoding="utf-8"), rel)
        if hits:
            out[rel] = hits
    return out
