"""No test module reads a POSIX-only signal at import time.

``signal.SIGHUP``, ``signal.SIGKILL`` and their kin do not exist on Windows. A test that names one inside its body is skipped or
fails there on its own; one that names it where the module is IMPORTED (a ``parametrize`` list, a decorator, a module constant, a
default argument) fails the whole module's collection, and every other test in it goes unrun on the Windows portability lane
(``test_guards_for_diff.py`` and ``test_native_inflight.py``, seen 2026-11-16). Name the signal as a string there and read it with
``getattr(signal, name)`` inside the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_POSIX_ONLY = frozenset({
    "SIGHUP", "SIGKILL", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM", "SIGCHLD", "SIGPIPE", "SIGCONT", "SIGSTOP", "SIGTSTP",
    "SIGWINCH", "SIGTTIN", "SIGTTOU", "SIGVTALRM", "SIGPROF", "SIGXCPU", "SIGXFSZ", "SIGSYS", "SIGTRAP", "SIGIO", "SIGURG",
})


def _import_time_reads(tree: ast.AST) -> list[tuple[int, str]]:
    """POSIX-only signal reads evaluated when the module is imported: outside every function and lambda body, counting a
    function's decorators and default arguments, which run at import."""
    hits: list[tuple[int, str]] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for part in [*node.decorator_list, *node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]:
                walk(part)
            return
        if isinstance(node, ast.Lambda):
            for part in [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]:
                walk(part)
            return
        # any chain ending in the name (signal.SIGHUP, signal.Signals.SIGHUP, an alias's sg.SIGHUP), and a module-level
        # ``from signal import SIGHUP``
        if isinstance(node, ast.Attribute) and node.attr in _POSIX_ONLY:
            hits.append((node.lineno, node.attr))
        if isinstance(node, ast.ImportFrom) and node.module == "signal":
            hits.extend((node.lineno, a.name) for a in node.names if a.name in _POSIX_ONLY)
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)
    return hits


def test_no_test_module_reads_a_posix_only_signal_at_import():
    found = {
        p.relative_to(_TESTS).as_posix(): hits
        for p in sorted(_TESTS.rglob("*.py"))
        if (hits := _import_time_reads(ast.parse(p.read_text(encoding="utf-8"))))
    }
    assert found == {}, f"name the signal as a string and getattr it inside the test: {found}"


def test_the_scan_sees_a_parametrize_list_and_not_a_test_body():
    """The mutation check: the shapes that failed collection are found, and a read inside a test body (which runs only when the
    test does, and is skipped there) is not."""
    caught = ast.parse('@pytest.mark.parametrize("s", [signal.SIGTERM, signal.SIGHUP])\ndef test_x(s):\n    pass\n')
    default = ast.parse("def helper(sig=signal.SIGKILL):\n    pass\n")
    body = ast.parse("def test_y():\n    os.kill(1, signal.SIGKILL)\n")
    alias = ast.parse("import signal as sg\nSIGS = (sg.SIGTERM, signal.Signals.SIGQUIT)\nfrom signal import SIGHUP, SIGTERM\n")
    assert _import_time_reads(caught) == [(1, "SIGHUP")]
    assert _import_time_reads(alias) == [(2, "SIGQUIT"), (3, "SIGHUP")]
    assert _import_time_reads(default) == [(1, "SIGKILL")]
    assert _import_time_reads(body) == []
