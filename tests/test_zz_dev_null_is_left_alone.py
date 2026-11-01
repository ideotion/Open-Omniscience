"""No test hands ``/dev/null`` to something that writes by replacing, and ``/dev/null`` is still a device when the suite is done.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. Three tests pointed a ``DamageRegistry`` at ``Path(os.devnull)`` as its store. The registry persists by writing a temporary file
beside the store and ``os.replace``-ing it over the store path. A non-root user cannot rename into ``/dev``, so on a CI runner the write failed, the
registry swallowed it (a store that cannot be written never takes the app down) and the test passed. ROOT can: a full-suite run in a root container
(a Docker image, a cloud sandbox) ended with ``/dev/null`` a regular file holding ``{"files": {"corpus": ...}}`` (measured 2026-11-01), and from that
moment every ``stdin=subprocess.DEVNULL`` read the registry's JSON, every ``2>/dev/null`` filled a file, and a test far from the cause went red
(``test_diff_installed_versions`` read a JSON object where it expected empty input). Nothing in the failing test names the culprit.

What this pins:

* a static scan: no file under ``tests/`` or ``src/`` names ``os.devnull`` or the whole string ``"/dev/null"`` as a PATH. A redirect (``subprocess.DEVNULL``,
  ``2>/dev/null`` inside a longer shell string) is not one. An allowlist entry says why a use is safe, and an entry no file needs any more fails, so the
  list can only be as long as the truth;
* the premise: a registry REPLACES whatever is at its store path (a unix socket stands in for a device node, which a non-root user can make);
* the symptom: this file sorts last, so its check runs after every other test, and fails when ``/dev/null`` is no longer a character device. It cannot name
  the culprit (the scan does); it names the damage at the end of the run instead of leaving it for the next one.

What it does not see: a path built from a variable that happens to hold ``/dev/null``, or a test that replaces some other node of ``/dev`` (``/dev/zero``,
``/dev/urandom``). The canary checks ``/dev/null`` only.
"""

from __future__ import annotations

import ast
import os
import socket
import stat
import sys
from pathlib import Path

import pytest

from src.database.damage import FILE_CORPUS, DamageRegistry

_ROOT = Path(__file__).resolve().parents[1]
_SCANNED = ("tests", "src")
#: Files that name ``/dev/null`` and are safe, each with why. Keyed by the repository path with forward slashes.
_ALLOWED = {
    "tests/test_ci_installed_versions_step.py": "the text of a mutated shell step (``rewrite(_SUMMARY, \"/dev/null\")``); nothing opens the path",
}


def devnull_uses(source: str) -> list[tuple[int, str]]:
    """``(line, how)`` for each place ``source`` names ``/dev/null`` as a path: ``os.devnull``, ``from os import devnull``, or the string ``"/dev/null"`` alone."""
    found: list[tuple[int, str]] = []
    tree = ast.parse(source)
    in_f_string = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}  # ``f"{base}/dev/null"`` is not the device
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "devnull" and isinstance(node.value, ast.Name) and node.value.id == "os":
            found.append((node.lineno, "os.devnull"))
        elif isinstance(node, ast.ImportFrom) and node.module == "os" and any(a.name == "devnull" for a in node.names):
            found.append((node.lineno, "from os import devnull"))
        elif isinstance(node, ast.Constant) and node.value == "/dev/null" and id(node) not in in_f_string:
            found.append((node.lineno, '"/dev/null"'))
    return sorted(found)


def uses_in_tree(root: Path, scanned: tuple[str, ...] = _SCANNED, *, skip: Path | None = None) -> dict[str, list[tuple[int, str]]]:
    """``{repository path: uses}`` over every ``.py`` under ``root/<each of scanned>``, except ``skip``."""
    found: dict[str, list[tuple[int, str]]] = {}
    for top in scanned:
        for path in sorted((root / top).rglob("*.py")):
            if skip is not None and path == skip:
                continue
            text = path.read_text(encoding="utf-8")
            if "devnull" in text or "/dev/null" in text:  # parse only what can contain one: a fixture of deliberately invalid Python must not turn this red
                uses = devnull_uses(text)
                if uses:
                    found[path.relative_to(root).as_posix()] = uses
    return found


def allowlist_problems(used: dict[str, list[tuple[int, str]]], allowed: dict[str, str]) -> dict[str, list[str]]:
    """What is wrong between the files that name ``/dev/null`` and the allowlist: ``unexplained`` (a use with no entry), ``stale`` (an entry no
    file needs any more) and ``unreasoned`` (an entry with no reason). Empty lists are left out."""
    out = {
        "unexplained": sorted(set(used) - set(allowed)),
        "stale": sorted(set(allowed) - set(used)),
        "unreasoned": sorted(path for path, why in allowed.items() if not why.strip()),
    }
    return {key: names for key, names in out.items() if names}


def devnull_problem(mode: int) -> str | None:
    """What is wrong with a ``/dev/null`` whose ``st_mode`` is ``mode``; ``None`` when it is a character device."""
    if stat.S_ISCHR(mode):
        return None
    kind = "a regular file" if stat.S_ISREG(mode) else "a directory" if stat.S_ISDIR(mode) else "not a character device"
    return f"/dev/null is {kind}, so every redirect and every DEVNULL read in this machine now sees a file some test or tool wrote"


def check_devnull(path: str = os.devnull) -> str | None:
    """What is wrong with the null device at ``path`` right now; ``None`` when it is a character device."""
    try:
        mode = os.stat(path).st_mode
    except OSError as exc:
        return f"/dev/null cannot be read ({type(exc).__name__})"
    return devnull_problem(mode)


def test_no_test_or_source_file_names_dev_null_as_a_path_unless_it_says_why():
    used = uses_in_tree(_ROOT, skip=Path(__file__).resolve())  # this file has to name the thing it guards
    problems = allowlist_problems(used, _ALLOWED)
    assert "unexplained" not in problems, (
        f"{ {path: used[path] for path in problems['unexplained']} }: a file names /dev/null as a PATH. Anything that writes there by replacing (a registry, an "
        "atomic write) turns the device into a regular file when the suite runs as root. Give the test a tmp_path store; if the use only builds text (a shell line) "
        "or opens for reading, add it to _ALLOWED with why."
    )
    assert "stale" not in problems, f"{problems['stale']}: no longer name /dev/null; delete them from _ALLOWED so the list stays true"
    assert problems == {}, problems


def test_the_allowlist_check_names_a_use_nobody_explained_an_entry_nobody_needs_and_an_entry_without_a_reason():
    used = {"tests/a.py": [(3, "os.devnull")], "tests/b.py": [(5, '"/dev/null"')]}
    assert allowlist_problems(used, {"tests/a.py": "text only", "tests/b.py": "text only"}) == {}
    assert allowlist_problems(used, {"tests/a.py": "text only"}) == {"unexplained": ["tests/b.py"]}
    assert allowlist_problems(used, {"tests/a.py": "x", "tests/b.py": "y", "tests/c.py": "z"}) == {"stale": ["tests/c.py"]}
    assert allowlist_problems(used, {"tests/a.py": "x", "tests/b.py": "  "}) == {"unreasoned": ["tests/b.py"]}


def test_the_tree_scan_reads_both_folders_skips_the_named_file_and_is_not_fooled_by_invalid_python(tmp_path):
    for folder in ("tests", "src", "other"):
        (tmp_path / folder).mkdir()
    (tmp_path / "tests" / "a.py").write_text("import os\nx = os.devnull\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("y = '/dev/null'\n", encoding="utf-8")
    (tmp_path / "other" / "c.py").write_text("z = '/dev/null'\n", encoding="utf-8")
    (tmp_path / "tests" / "self.py").write_text("x = os.devnull\n", encoding="utf-8")
    (tmp_path / "tests" / "fixture.py").write_text("def (:\n", encoding="utf-8")  # deliberately invalid Python that does not name the device: never parsed
    assert uses_in_tree(tmp_path, skip=tmp_path / "tests" / "self.py") == {"tests/a.py": [(2, "os.devnull")], "src/b.py": [(1, '"/dev/null"')]}
    assert set(uses_in_tree(tmp_path)) == {"tests/a.py", "tests/self.py", "src/b.py"}
    (tmp_path / "tests" / "unreadable.py").write_text("def (:  # os.devnull\n", encoding="utf-8")
    with pytest.raises(SyntaxError):  # a file that names the device and cannot be parsed is not "clean": the scan says so instead of skipping it
        uses_in_tree(tmp_path)


def test_the_scan_sees_each_way_to_name_dev_null_and_nothing_else():
    src = (
        "import os\nfrom os import devnull\nimport subprocess\n"
        "a = os.devnull\nb = '/dev/null'\nc = 'cmd 2>/dev/null'\nd = subprocess.DEVNULL\ne = f'{x}/dev/null'\nf = other.devnull\n"
    )
    assert [how for _line, how in devnull_uses(src)] == ["from os import devnull", "os.devnull", '"/dev/null"']
    assert devnull_uses("x = 1\n") == []


def test_a_dev_null_that_is_not_a_device_is_named():
    assert devnull_problem(stat.S_IFCHR | 0o666) is None
    for mode, word in ((stat.S_IFREG | 0o644, "a regular file"), (stat.S_IFDIR | 0o755, "a directory"), (stat.S_IFIFO | 0o600, "not a character device")):
        assert word in (devnull_problem(mode) or ""), (mode, word)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="a unix socket stands in for a device node, and this platform has none")
def test_a_registry_replaces_whatever_is_at_its_store_path_which_is_why_dev_null_cannot_be_one(tmp_path):
    """The premise of the scan, with a node a non-root user can make: the store path held a socket and now holds a regular file.

    (A FIFO would be the other stand-in, but the registry reads its store before writing, and opening a FIFO with no writer for reading never returns.)"""
    store = tmp_path / "store.json"
    node = socket.socket(socket.AF_UNIX)
    try:
        try:
            node.bind(str(store))
        except OSError as exc:  # a long temporary folder name does not fit a socket path
            pytest.skip(f"cannot bind a unix socket at {store}: {exc}")
        assert stat.S_ISSOCK(os.stat(store).st_mode)
        reg = DamageRegistry(path_fn=lambda: store)
        reg._note_verified_damage(FILE_CORPUS, ["articles"], path=None, at="2026-10-06T02:00:00+00:00")
        assert reg.flush_durable() is True
        assert stat.S_ISREG(os.stat(store).st_mode), "the registry no longer replaces its store; the /dev/null hazard may be gone and this guard can be relaxed"
    finally:
        node.close()


@pytest.mark.skipif(not os.path.exists("/dev/zero"), reason="needs a character device other than the null device to stand in for it")
def test_the_check_reads_the_node_it_is_given(tmp_path):
    """The check on stand-ins: a character device is fine, a regular file, a folder and a missing path are each named."""
    assert check_devnull("/dev/zero") is None
    file = tmp_path / "null"
    file.write_text('{"files": {}}', encoding="utf-8")
    assert "a regular file" in (check_devnull(str(file)) or "")
    assert "a directory" in (check_devnull(str(tmp_path)) or "")
    assert "cannot be read" in (check_devnull(str(tmp_path / "missing")) or "")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows' null device is not a character-device node of the file system")
def test_dev_null_is_still_a_character_device():
    """Named ``test_zz_...`` so it runs after every other test of a full run."""
    assert check_devnull() is None, check_devnull()
