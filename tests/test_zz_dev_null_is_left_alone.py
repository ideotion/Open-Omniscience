"""No test hands a device node of ``/dev`` to something that writes by replacing, and the nodes are still devices when the suite is done.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. Two tests (three registry constructions: ``test_database_damage.py::test_a_latch_never_releases_by_itself_however_long_it_stands`` and the
two registries of ``test_database_verify_pages.py::test_a_pages_finding_beside_index_only_damage_is_data_scope_not_a_search_index_one``) pointed a
``DamageRegistry`` at ``Path(os.devnull)`` as its store, a store whose content they never looked at. The registry reads its store, then persists by writing
a temporary file beside it and ``os.replace``-ing that over the store path. A non-root user cannot create a file in ``/dev``, so on a CI runner the write
failed, the registry swallowed it (a store that cannot be written never takes the app down) and the test passed. ROOT can: a full-suite run in a root
container (a Docker image, a cloud sandbox) ended with ``/dev/null`` a regular file holding ``{"files": {"corpus": ...}}`` (measured 2026-11-01), and from
that moment every ``stdin=subprocess.DEVNULL`` read the registry's JSON, every ``2>/dev/null`` filled a file, and a test far from the cause went red
(``test_diff_installed_versions`` read a JSON object where it expected empty input). Nothing in the failing test names the culprit.

What this pins:

* a static scan of ``tests/``, ``src/`` and ``scripts/``: no file names the null device (``os.devnull`` through ``os``, ``os.path``, ``posixpath`` or ``ntpath``
  under any import alias, ``getattr(os, "devnull")``) or a whole-string ``/dev/<name>`` constant (str or bytes: ``"/dev/null"``, ``"/dev/full"``,
  ``"/dev/zero"``) as a PATH unless an allowlist entry says why it is safe. A redirect (``subprocess.DEVNULL``, ``2>/dev/null`` inside a longer shell string)
  is not one. An entry no file needs any more fails, so the list can only be as long as the truth;
* the premise: a registry REPLACES whatever is at its store path (a unix socket stands in for a device node, which a non-root user can make);
* the symptom: in a serial run this file sorts last, so its check runs after every other test, and fails when ``/dev/null``, ``/dev/zero``, ``/dev/full``,
  ``/dev/random`` or ``/dev/urandom`` is no longer a character device. It cannot name the culprit (the scan does); it names the damage at the end of the run
  instead of leaving it for the next one. Under ``pytest -n`` (``tests/conftest.py`` documents it) or a random-order plugin it runs among the others and can
  only miss damage done after it, never report damage that is not there.

What it does not see (each pinned by ``test_what_the_scan_cannot_see_is_stated``): a path built from parts (``Path("/dev") / "null"``, ``"/dev/" + "null"``), a
variable that happens to hold a device path, a device path inside a longer string (``"--out=/dev/null"``), ``sys.modules["os"].devnull``, and a store that is
not a device but is a RELATIVE path (``tests/test_damage_reread.py`` builds one: ``Path("x")``, which would write into the checkout).
"""

from __future__ import annotations

import ast
import os
import re
import socket
import stat
import sys
from pathlib import Path

import pytest

from src.database.damage import FILE_CORPUS, DamageRegistry

_ROOT = Path(__file__).resolve().parents[1]
_SCANNED = ("tests", "src", "scripts")
#: Files that name a device and are safe, each with why. Keyed by the repository path with forward slashes.
_ALLOWED = {
    "tests/test_ci_installed_versions_step.py": "the text of a mutated shell step (``rewrite(_SUMMARY, \"/dev/null\")``); nothing opens the path",
    "scripts/osm_reference_run.py": "``os.open(os.devnull, os.O_WRONLY)``: opens the null device to write to it and replaces nothing",
    "scripts/guards_for_diff.py": "``core.hooksPath={os.devnull}``: the text of a git config value that switches hooks off; nothing is written there",
}
#: The nodes the canary checks. ``/dev/full`` exists on Linux only.
_NODES = ("/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom")
_OPTIONAL_NODES = frozenset({"/dev/full"})
_DEVICE_PATH = re.compile(r"/dev/[A-Za-z0-9_.-]+")
_OS_MODULES = frozenset({"os", "os.path", "posixpath", "ntpath"})


def devnull_uses(source: str) -> list[tuple[int, str]]:
    """``(line, how)`` for each place ``source`` names a device node as a path: the null device through a module that has ``devnull`` (``os``,
    ``os.path``, ``posixpath``, ``ntpath``, under any alias), ``from <those> import devnull``, ``getattr(<those>, "devnull")``, or a str or bytes
    constant that is a whole ``/dev/<name>`` path."""
    tree = ast.parse(source)
    in_f_string = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}  # ``f"{base}/dev/null"`` is not the device
    modules: set[str] = set()  # the names that stand for os, os.path, posixpath or ntpath in this file
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _OS_MODULES:
                    modules.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            modules.update(a.asname or a.name for a in node.names if a.name == "path")
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "devnull":
            base = node.value
            if isinstance(base, ast.Attribute) and base.attr == "path":  # os.path.devnull
                base = base.value
            if isinstance(base, ast.Name) and base.id in modules:
                found.append((node.lineno, "os.devnull"))
        elif isinstance(node, ast.ImportFrom) and node.module in _OS_MODULES and any(a.name == "devnull" for a in node.names):
            found.append((node.lineno, "from os import devnull"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in modules
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "devnull"
        ):
            found.append((node.lineno, "getattr(os, 'devnull')"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)) and id(node) not in in_f_string:
            text = node.value if isinstance(node.value, str) else node.value.decode("latin-1")
            if _DEVICE_PATH.fullmatch(text):
                found.append((node.lineno, f'"{text}"'))
    return sorted(found)


def uses_in_tree(root: Path, scanned: tuple[str, ...] = _SCANNED, *, skip: Path | None = None) -> dict[str, list[tuple[int, str]]]:
    """``{repository path: uses}`` over every ``.py`` under ``root/<each of scanned>``, except ``skip``."""
    found: dict[str, list[tuple[int, str]]] = {}
    for top in scanned:
        for path in sorted((root / top).rglob("*.py")):
            if skip is not None and path == skip:
                continue
            text = path.read_text(encoding="utf-8")
            if "devnull" in text or "/dev/" in text:  # parse only what can contain one: a fixture of deliberately invalid Python must not turn this red
                uses = devnull_uses(text)
                if uses:
                    found[path.relative_to(root).as_posix()] = uses
    return found


def allowlist_problems(used: dict[str, list[tuple[int, str]]], allowed: dict[str, str]) -> dict[str, list[str]]:
    """What is wrong between the files that name a device and the allowlist: ``unexplained`` (a use with no entry), ``stale`` (an entry no
    file needs any more) and ``unreasoned`` (an entry with no reason). Empty lists are left out."""
    out = {
        "unexplained": sorted(set(used) - set(allowed)),
        "stale": sorted(set(allowed) - set(used)),
        "unreasoned": sorted(path for path, why in allowed.items() if not why.strip()),
    }
    return {key: names for key, names in out.items() if names}


def node_problem(path: str, mode: int) -> str | None:
    """What is wrong with the node at ``path`` whose ``st_mode`` is ``mode``; ``None`` when it is a character device."""
    if stat.S_ISCHR(mode):
        return None
    kind = "a regular file" if stat.S_ISREG(mode) else "a directory" if stat.S_ISDIR(mode) else "not a character device"
    hint = " (Linux, as root: remove it and `mknod -m 666 /dev/null c 1 3`)" if path == "/dev/null" else ""
    return f"{path} is {kind}, so everything on this machine that reads or writes it now meets a file some test or tool wrote{hint}"


def check_node(path: str) -> str | None:
    """What is wrong with the device node at ``path`` right now; ``None`` when it is a character device."""
    try:
        mode = os.stat(path).st_mode
    except OSError as exc:
        return f"{path} cannot be read ({type(exc).__name__})"
    return node_problem(path, mode)


def damaged_nodes(paths: tuple[str, ...] = _NODES, optional: frozenset[str] = _OPTIONAL_NODES) -> list[str]:
    """One sentence per node of ``paths`` that is not a character device; a node in ``optional`` that is absent is not a problem."""
    out = []
    for path in paths:
        if path in optional and not os.path.lexists(path):
            continue
        problem = check_node(path)
        if problem:
            out.append(problem)
    return out


def test_no_file_names_a_device_node_as_a_path_unless_it_says_why():
    used = uses_in_tree(_ROOT, skip=Path(__file__).resolve())  # this file has to name the thing it guards
    problems = allowlist_problems(used, _ALLOWED)
    assert "unexplained" not in problems, (
        f"{ {path: used[path] for path in problems['unexplained']} }: a file names a /dev node as a PATH. Anything that writes there by replacing (a registry, an "
        "atomic write) turns the device into a regular file when the suite runs as root. Give the test a tmp_path store; if the use only builds text (a shell line) "
        "or opens for reading, add it to _ALLOWED with why."
    )
    assert "stale" not in problems, f"{problems['stale']}: no longer name a device; delete them from _ALLOWED so the list stays true"
    assert problems == {}, problems


def test_the_allowlist_check_names_a_use_nobody_explained_an_entry_nobody_needs_and_an_entry_without_a_reason():
    used = {"tests/a.py": [(3, "os.devnull")], "tests/b.py": [(5, '"/dev/null"')]}
    assert allowlist_problems(used, {"tests/a.py": "text only", "tests/b.py": "text only"}) == {}
    assert allowlist_problems(used, {"tests/a.py": "text only"}) == {"unexplained": ["tests/b.py"]}
    assert allowlist_problems(used, {"tests/a.py": "x", "tests/b.py": "y", "tests/c.py": "z"}) == {"stale": ["tests/c.py"]}
    assert allowlist_problems(used, {"tests/a.py": "x", "tests/b.py": "  "}) == {"unreasoned": ["tests/b.py"]}


def test_the_tree_scan_reads_the_folders_skips_the_named_file_and_is_not_fooled_by_invalid_python(tmp_path):
    for folder in ("tests", "src", "scripts", "other"):
        (tmp_path / folder).mkdir()
    (tmp_path / "tests" / "a.py").write_text("import os\nx = os.devnull\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("y = '/dev/null'\n", encoding="utf-8")
    (tmp_path / "scripts" / "d.py").write_text("w = b'/dev/full'\n", encoding="utf-8")
    (tmp_path / "other" / "c.py").write_text("z = '/dev/null'\n", encoding="utf-8")
    (tmp_path / "tests" / "self.py").write_text("import os\nx = os.devnull\n", encoding="utf-8")
    (tmp_path / "tests" / "fixture.py").write_text("def (:\n", encoding="utf-8")  # deliberately invalid Python that does not name a device: never parsed
    assert uses_in_tree(tmp_path, skip=tmp_path / "tests" / "self.py") == {
        "tests/a.py": [(2, "os.devnull")],
        "src/b.py": [(1, '"/dev/null"')],
        "scripts/d.py": [(1, '"/dev/full"')],
    }
    assert set(uses_in_tree(tmp_path)) == {"tests/a.py", "tests/self.py", "src/b.py", "scripts/d.py"}
    assert _SCANNED == ("tests", "src", "scripts"), "the scan reads the three folders whose code runs on a developer's or a runner's machine"
    (tmp_path / "tests" / "unreadable.py").write_text("def (:  # os.devnull\n", encoding="utf-8")
    with pytest.raises(SyntaxError):  # a file that names a device and cannot be parsed is not "clean": the scan says so instead of skipping it
        uses_in_tree(tmp_path)


def test_the_scan_sees_each_way_to_name_a_device_and_nothing_else():
    src = (
        "import os\nfrom os import devnull\nimport subprocess\n"
        "a = os.devnull\nb = '/dev/null'\nc = 'cmd 2>/dev/null'\nd = subprocess.DEVNULL\ne = f'{x}/dev/null'\nf = other.devnull\n"
    )
    assert [how for _line, how in devnull_uses(src)] == ["from os import devnull", "os.devnull", '"/dev/null"']
    assert devnull_uses("x = 1\n") == []


def test_the_scan_follows_aliases_modules_getattr_bytes_and_every_whole_dev_path():
    src = (
        "import os as _os\n"  # 1
        "import os.path as osp\n"  # 2
        "import posixpath\n"  # 3
        "import ntpath\n"  # 4
        "from os.path import devnull as d\n"  # 5: flagged
        "a = _os.devnull\n"  # 6: flagged
        "b = osp.devnull\n"  # 7: flagged
        "c = posixpath.devnull\n"  # 8: flagged
        "n = ntpath.devnull\n"  # 9: flagged
        "e = getattr(_os, 'devnull')\n"  # 10: flagged
        "f = b'/dev/null'\n"  # 11: flagged
        "g = '/dev/full'\n"  # 12: flagged
        "h = '/dev/zero'\n"  # 13: flagged
        "i = '/dev/random'\n"  # 14: flagged
        "j = 'see /dev/null for more'\n"  # 15: a longer string
        "k = '/dev/'\n"  # 16: no name
        "m = nt.devnull\n"  # 17: not an alias of an os module
        "o = _os.path.devnull\n"  # 18: flagged
        "p = getattr(other, 'devnull')\n"  # 19
    )
    assert [line for line, _how in devnull_uses(src)] == [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 18]


def test_what_the_scan_cannot_see_is_stated():
    """Pinned so that teaching the scan one of these is a decision and not an accident (and so the module docstring stays true)."""
    for src in (
        "from pathlib import Path\nx = Path('/dev') / 'null'\n",
        "x = '/dev/' + 'null'\n",
        "x = Path('/dev', 'null')\n",
        "x = '--out=/dev/null'\n",
        "import sys\nx = sys.modules['os'].devnull\n",
        "x = name\n",  # a variable that happens to hold a device path is invisible
    ):
        assert devnull_uses(src) == [], src


def test_a_node_that_is_not_a_device_is_named_with_its_path():
    assert node_problem("/dev/null", stat.S_IFCHR | 0o666) is None
    for mode, word in ((stat.S_IFREG | 0o644, "a regular file"), (stat.S_IFDIR | 0o755, "a directory"), (stat.S_IFIFO | 0o600, "not a character device")):
        got = node_problem("/dev/full", mode) or ""
        assert word in got and got.startswith("/dev/full is "), (mode, word)
    assert "mknod" in (node_problem("/dev/null", stat.S_IFREG | 0o644) or "")


@pytest.mark.skipif(sys.platform == "win32", reason="a unix socket stands in for a device node, and the Windows leg has no such node to protect")
@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="a unix socket stands in for a device node, and this platform has none")
def test_a_registry_replaces_whatever_is_at_its_store_path_which_is_why_a_device_cannot_be_one(tmp_path, monkeypatch):
    """The premise of the scan, with a node a non-root user can make: the store path held a socket and now holds a regular file.

    (A FIFO would be the other stand-in, but the registry reads its store before writing, and opening a FIFO with no writer for reading never returns.
    The socket is bound by a RELATIVE name from inside ``tmp_path``: a socket path is limited to about 104 bytes, which a macOS temporary folder exceeds.)"""
    store = tmp_path / "store.json"
    monkeypatch.chdir(tmp_path)
    node = socket.socket(socket.AF_UNIX)
    try:
        node.bind(store.name)
        assert stat.S_ISSOCK(os.stat(store).st_mode)
        reg = DamageRegistry(path_fn=lambda: store)
        reg._note_verified_damage(FILE_CORPUS, ["articles"], path=None, at="2026-10-06T02:00:00+00:00")
        assert reg.flush_durable() is True
        assert stat.S_ISREG(os.stat(store).st_mode), "the registry no longer replaces its store; the /dev hazard may be gone and this guard can be relaxed"
    finally:
        node.close()


@pytest.mark.skipif(not os.path.exists("/dev/zero"), reason="needs a character device to stand in for the nodes")
def test_the_check_reads_the_node_it_is_given(tmp_path):
    """The check on stand-ins: a character device is fine; a regular file, a folder and a missing path are each named, and an optional node may be absent."""
    assert check_node("/dev/zero") is None
    file = tmp_path / "null"
    file.write_text('{"files": {}}', encoding="utf-8")
    assert "a regular file" in (check_node(str(file)) or "")
    assert "a directory" in (check_node(str(tmp_path)) or "")
    assert "cannot be read" in (check_node(str(tmp_path / "missing")) or "")
    assert damaged_nodes(("/dev/zero",)) == []
    assert len(damaged_nodes(("/dev/zero", str(file), str(tmp_path)))) == 2
    gone = str(tmp_path / "gone")
    assert damaged_nodes((gone,)) != [] and damaged_nodes((gone,), frozenset({gone})) == []
    assert damaged_nodes((str(file),), frozenset({str(file)})) != [], "an optional node that is present must still be a device"


def test_the_canary_watches_every_node_a_test_could_plausibly_replace():
    """Shrinking the list is a decision: ``/dev/null`` is the one that was hit, but the registry's hazard is any path under ``/dev`` a test might name."""
    assert set(_NODES) == {"/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom"}
    optional = set(_OPTIONAL_NODES)
    assert optional == {"/dev/full"} and optional <= set(_NODES), "only a node that some platforms lack may be absent"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows' null device is not a character-device node of the file system")
def test_the_dev_nodes_are_still_character_devices():
    """Named ``test_zz_...`` so that in a serial run it runs after every other test."""
    assert damaged_nodes() == [], damaged_nodes()
