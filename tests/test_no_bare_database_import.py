"""The store's modules are imported as ``src.database``, never as a bare ``database`` (row 285).

With ``src/`` on ``sys.path`` a bare ``import database.models`` loads a SECOND copy of the package beside
``src.database``: its own module objects, its own ``Base`` and metadata, its own engine bindings and module-level
caches. Code written against one copy then reads state the other never sees; ``tests/test_source_manager.py`` created
its tables through one ``Base`` and queried them through the other's classes until row 285. This scan keeps the bare
path out of src, tests and scripts."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCANNED = ("src", "tests", "scripts")
_BARE = re.compile(r"^database(\.|$)")
_DYNAMIC = re.compile(r"""import_module\(\s*["']database(\.|["'])""")


def _bare_imports(text: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            lines += [node.lineno for alias in node.names if _BARE.match(alias.name)]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and _BARE.match(node.module):
            lines.append(node.lineno)
    lines += [text.count("\n", 0, m.start()) + 1 for m in _DYNAMIC.finditer(text)]
    return lines


def test_no_module_imports_the_bare_database_package():
    found = []
    for top in _SCANNED:
        for path in sorted((_ROOT / top).rglob("*.py")):
            for line in _bare_imports(path.read_text(encoding="utf-8")):
                found.append(f"{path.relative_to(_ROOT).as_posix()}:{line}")
    assert not found, "import these through src.database instead: " + ", ".join(found)


def test_the_scan_sees_each_form_of_the_bare_import():
    # Fails if the scan goes blind: each form below must be caught, and the src.database forms must not be
    assert _bare_imports("import database\n") == [1]
    assert _bare_imports("import database.models as m\n") == [1]
    assert _bare_imports("from database.models import Base\n") == [1]
    assert _bare_imports("from database import session\n") == [1]
    assert _bare_imports("x = importlib.import_module('data" + "base.models')\n") == [1]  # split so this file passes its own scan
    assert _bare_imports("from src.database.models import Base\nimport src.database\nfrom . import database\n") == []
    assert _bare_imports("import databases\nfrom database_tools import x\n") == []
