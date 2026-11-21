"""The app's packages are imported through ``src.``, never bare (rows 285 and 287).

With ``src/`` on ``sys.path`` a bare ``import config`` loads a SECOND copy of the package beside ``src.config``: its own
module objects and its own module-level state. Code written against one copy then reads state the other never sees.
``tests/test_config.py``'s ``reset_config()`` reset the bare copy while the app reads ``src.config``, so a config-state
bug could hide behind it; ``tests/test_source_manager.py`` created tables through one ``Base`` and queried them through
the other's classes. This scan keeps every top-level name under ``src/`` from being imported bare in src, tests or
scripts: static imports at any depth, ``importlib.import_module`` / ``__import__`` and the string targets of
``patch`` / ``setattr`` (which import their module too), plain strings and f-strings alike."""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCANNED = ("src", "tests", "scripts")
#: Calls whose first argument names a module that gets imported.
_DYNAMIC = frozenset({"import_module", "__import__", "patch", "setattr", "delattr"})


def _src_packages() -> frozenset[str]:
    names = set()
    for entry in (_ROOT / "src").iterdir():
        if entry.is_dir() and (entry / "__init__.py").is_file():
            names.add(entry.name)
        elif entry.suffix == ".py" and entry.stem != "__init__":
            names.add(entry.stem)
    return frozenset(names)


def _is_bare(dotted: str, packages: frozenset[str]) -> bool:
    return dotted.split(".", 1)[0] in packages


def _leading_text(node: ast.expr) -> str | None:
    """The literal text a string argument starts with (an f-string's text before its first placeholder)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return None


def _bare_imports(text: str, packages: frozenset[str]) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            lines += [node.lineno for alias in node.names if _is_bare(alias.name, packages)]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and _is_bare(node.module, packages):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            lead = _leading_text(node.args[0]) if name in _DYNAMIC else None
            # A dotted target only: setattr(obj, "name", v) and patch.object(...) take no module path
            if lead and "." in lead and _is_bare(lead, packages):
                lines.append(node.lineno)
    return lines


def test_no_module_imports_an_app_package_bare():
    packages = _src_packages()
    found = []
    for top in _SCANNED:
        for path in sorted((_ROOT / top).rglob("*.py")):
            for line in _bare_imports(path.read_text(encoding="utf-8"), packages):
                found.append(f"{path.relative_to(_ROOT).as_posix()}:{line}")
    assert not found, "import these through src. instead: " + ", ".join(found)


def test_the_package_list_is_read_from_src():
    packages = _src_packages()
    assert {"database", "config", "utils", "services", "crypto"} <= packages
    assert "src" not in packages and "__init__" not in packages


def test_the_scan_sees_each_form_of_the_bare_import():
    # Fails if the scan goes blind: each form below must be caught, and the src. forms must not be
    p = frozenset({"database", "config", "utils"})
    assert _bare_imports("import database\n", p) == [1]
    assert _bare_imports("def f():\n    if x:\n        import config.settings as s\n", p) == [3]
    assert _bare_imports("try:\n    from utils.cache import C\nexcept ImportError:\n    pass\n", p) == [2]
    assert _bare_imports("m = importlib.import_module('database.models')\n", p) == [1]
    assert _bare_imports("m = __import__('config.settings')\n", p) == [1]
    assert _bare_imports("m = import_module(f'database.{name}')\n", p) == [1]
    assert _bare_imports("@patch('utils.cache.time.time')\ndef t(): pass\n", p) == [1]
    assert _bare_imports("monkeypatch.setattr('config.settings.X', 1)\n", p) == [1]
    assert _bare_imports("from src.database.models import Base\nimport src.config\nfrom . import utils\n", p) == []
    assert _bare_imports("import databases\nfrom configparser import X\n# import config\n", p) == []
    assert _bare_imports("setattr(obj, 'config', 1)\npatch.object(utils, 'x')\nlog = getLogger('database.session')\n", p) == []
