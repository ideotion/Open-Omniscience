"""The wheel-layout checker (R380): what it asks of a wheel's file list, and that it fails when the wheel lacks a file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``scripts/check_wheel_layout.py`` reads the file list of a built wheel and compares it with the tracked tree (every tracked file under ``src/``,
``configs/``, ``migrations/``, ``docs/legal/`` and ``docs/i18n/`` must be in the wheel, bar the named exemptions) and with a short list of
anchors. The CI step that builds the wheel and runs the checker is pinned in ``tests/test_ci_wheel_layout_step.py``; this file pins the checker
itself, on synthetic file lists, so that it is the checker and not a lucky wheel that is under test.

The guard proves itself: every anchor is dropped from a synthetic wheel in turn, a whole tree is dropped, and a file of a kind no glob
mentions is dropped; each must be named. The lists are pinned EXACTLY (a shrunk list fails, and so does a grown one that no test was edited for).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("check_wheel_layout", _ROOT / "scripts" / "check_wheel_layout.py")
assert _SPEC is not None and _SPEC.loader is not None
cwl = importlib.util.module_from_spec(_SPEC)
sys.modules["check_wheel_layout"] = cwl
_SPEC.loader.exec_module(cwl)


def _tracked() -> list[str]:
    """A small tracked tree: the anchors, files of a kind a glob could forget, a migration version, the legal and quick-start trees, an exempt
    README, and docs and scripts that do not ship."""
    return [
        *cwl.ANCHORS,
        "src/api/routes.py",
        "src/static/app.js",
        "src/analytics/new_table.json",
        "configs/rings.json",
        "configs/new_kind.toml",
        "migrations/versions/0001_first.py",
        "docs/legal/fr/CGU.md",
        "docs/i18n/es/QUICKSTART.md",
        "docs/CHANGES.md",
        "docs/ledger/OPEN_QUEUE.md",
        "docs/audit/01_report.md",
        "scripts/check_wheel_layout.py",
        "tests/test_something.py",
        *cwl.NOT_SHIPPED,
    ]


def _wheel(tracked: list[str]) -> list[str]:
    """What a correct wheel of that tree carries: the runtime trees (bar the exempt files) and the anchors, nothing else."""
    return [p for p in tracked if (cwl.tree_of(p) is not None and p not in cwl.NOT_SHIPPED) or p in cwl.ANCHORS]


def test_a_wheel_that_carries_what_the_tree_needs_has_no_problems():
    tracked = _tracked()
    assert cwl.problems(tracked, _wheel(tracked)) == []


def test_docs_beyond_the_legal_and_quick_start_trees_and_the_anchors_are_deliberately_not_asked_for():
    """``docs/*.md`` ships (package-data) but only the manual is asked for; the developer trees never ship."""
    tracked = _tracked()
    for path in ("docs/CHANGES.md", "docs/ledger/OPEN_QUEUE.md", "docs/audit/01_report.md"):
        assert path in tracked and path not in _wheel(tracked)
    assert cwl.problems(tracked, _wheel(tracked)) == []


@pytest.mark.parametrize("path", ["docs/legal/fr/CGU.md", "docs/i18n/es/QUICKSTART.md"])
def test_a_legal_or_quick_start_file_the_wheel_lacks_is_named(path):
    """No anchor covers these two (a missing translation falls back to French or English without an error), so the derived rule is what catches them."""
    tracked = _tracked()
    found = cwl.problems(tracked, [p for p in _wheel(tracked) if p != path])
    assert len(found) == 1 and path in found[0], found


@pytest.mark.parametrize("anchor", cwl.ANCHORS)
def test_every_anchor_missing_from_the_wheel_is_named(anchor):
    tracked = _tracked()
    wheel = [p for p in _wheel(tracked) if p != anchor]
    found = cwl.problems(tracked, wheel)
    assert any(anchor in line and "anchor" in line for line in found), found


@pytest.mark.parametrize("anchor", cwl.ANCHORS)
def test_an_anchor_lost_from_the_tree_as_well_still_fails(anchor):
    """A rule derived from the tree passes vacuously when the tree loses the file too: the anchors are read against the wheel alone."""
    tracked = [p for p in _tracked() if p != anchor]
    wheel = [p for p in _wheel(_tracked()) if p != anchor]
    assert any(anchor in line for line in cwl.problems(tracked, wheel))


@pytest.mark.parametrize("path", ["configs/new_kind.toml", "src/analytics/new_table.json"])
def test_a_tracked_file_of_a_kind_no_glob_lists_is_named_with_what_to_do(path):
    tracked = _tracked()
    wheel = [p for p in _wheel(tracked) if p != path]
    found = cwl.problems(tracked, wheel)
    assert len(found) == 1
    assert path in found[0] and "package-data" in found[0] and "NOT_SHIPPED" in found[0]


@pytest.mark.parametrize("tree", cwl.RUNTIME_TREES)
def test_a_whole_runtime_tree_missing_names_each_of_its_files(tree):
    tracked = _tracked()
    wheel = [p for p in _wheel(tracked) if not p.startswith(tree + "/")]
    found = cwl.problems(tracked, wheel)
    for path in (p for p in tracked if p.startswith(tree + "/") and p not in cwl.NOT_SHIPPED):
        assert any(path in line for line in found), (path, found)


def test_an_exempt_file_may_be_absent_or_present_in_the_wheel():
    tracked = _tracked()
    wheel = _wheel(tracked)
    assert cwl.problems(tracked, wheel) == []
    assert cwl.problems(tracked, [*wheel, *cwl.NOT_SHIPPED]) == []


def test_an_exemption_for_a_file_no_longer_tracked_is_reported_as_stale():
    tracked = [p for p in _tracked() if p not in cwl.NOT_SHIPPED]
    found = cwl.problems(tracked, _wheel(tracked))
    assert len(found) == len(cwl.NOT_SHIPPED)
    assert all("NOT_SHIPPED" in line and "no longer tracked" in line for line in found)


def test_the_lists_are_pinned_exactly_so_that_changing_them_takes_an_edit_here():
    assert cwl.RUNTIME_TREES == ("src", "configs", "migrations", "docs/legal", "docs/i18n")
    assert cwl.ANCHORS == (
        "src/api/main.py",
        "src/static/index.html",
        "src/catalog/data/public_suffix_list.dat",
        "src/geo/data/dbip_country_lite.csv.gz",
        "configs/sources.yml",  # R330: the sources-import route reads this file from the package root
        "migrations/env.py",
        "migrations/script.py.mako",
        "docs/USER_MANUAL.md",
        "docs/legal/CGU.md",
        "docs/legal/de/CGU.md",
        "docs/legal/de/ui.json",
        "docs/i18n/fr/QUICKSTART.md",
    )
    assert tuple(cwl.NOT_SHIPPED) == ("src/analytics/duckdb_ext/README.md",)
    assert all(reason.strip() for reason in cwl.NOT_SHIPPED.values()), "every exemption carries its reason"
    for tree in cwl.RUNTIME_TREES:
        assert any(a.startswith(tree + "/") for a in cwl.ANCHORS), f"no anchor under {tree}/"


@pytest.mark.parametrize(
    ("path", "tree"),
    [
        ("src/a.py", "src"),
        ("docs/legal/de/CGU.md", "docs/legal"),
        ("docs/i18n/fr/QUICKSTART.md", "docs/i18n"),
        ("docs/USER_MANUAL.md", None),
        ("docs/legalese/x.md", None),
        ("srcs/a.py", None),
        ("scripts/a.py", None),
    ],
)
def test_the_tree_of_a_path_matches_whole_directories_only(path, tree):
    assert cwl.tree_of(path) == tree


def test_the_anchors_and_exemptions_exist_in_the_real_tree():
    """An anchor that names a file the tree does not have would redden CI on its own; an exemption for a missing file is stale."""
    for path in (*cwl.ANCHORS, *cwl.NOT_SHIPPED):
        assert (_ROOT / path).is_file(), f"{path} is not in the repository"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_tracked_files_reads_git_without_quoting_odd_paths(tmp_path):
    """``git ls-files -z`` returns raw paths: a name with a space or a non-ASCII letter is not C-quoted into a string that matches nothing."""
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    for name in ("src/plain.py", "src/with space.py", "src/accentué.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")
    run("add", "-A")
    assert sorted(cwl.tracked_files(tmp_path)) == sorted(["src/plain.py", "src/with space.py", "src/accentué.py"])


@pytest.mark.skipif(shutil.which("git") is None or not (_ROOT / ".git").exists(), reason="not a git checkout")
def test_the_real_tracked_tree_carries_every_anchor_and_every_runtime_tree():
    tracked = set(cwl.tracked_files())
    assert set(cwl.ANCHORS) <= tracked
    for tree in cwl.RUNTIME_TREES:
        assert any(cwl.tree_of(p) == tree for p in tracked), f"nothing is tracked under {tree}/"


# --- reading a real zip and the command line ----------------------------------------------------------------------------------------------------


def _write_wheel(path: Path, names: list[str], generator: str | None = "Generator: setuptools (84.2.1)") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name in names:
            zf.writestr(name, "x")
        zf.writestr("open_omniscience-0.5.0.dist-info/RECORD", "")
        if generator is not None:
            zf.writestr("open_omniscience-0.5.0.dist-info/WHEEL", f"Wheel-Version: 1.0\n{generator}\nRoot-Is-Purelib: true\n")
    return path


def test_dist_info_is_not_part_of_the_app_tree(tmp_path):
    wheel = _write_wheel(tmp_path / "w.whl", ["src/a.py"])
    assert cwl.wheel_names(wheel) == ["src/a.py"]


def test_the_generator_line_is_read_from_the_wheel_or_its_absence_is_stated(tmp_path):
    assert cwl.generator_line(_write_wheel(tmp_path / "a.whl", ["src/a.py"])) == "Generator: setuptools (84.2.1)"
    assert "not stated" in cwl.generator_line(_write_wheel(tmp_path / "b.whl", ["src/a.py"], generator=None))


def test_the_command_line_passes_on_a_complete_wheel_and_says_what_it_counted(tmp_path, monkeypatch, capsys):
    tracked = _tracked()
    monkeypatch.setattr(cwl, "tracked_files", lambda root=cwl.ROOT: tracked)
    wheel = _write_wheel(tmp_path / "ok.whl", _wheel(tracked))
    assert cwl.main([str(wheel)]) == 0
    out = capsys.readouterr().out
    assert "layout ok" in out and f"{len(_wheel(tracked))} files" in out and "setuptools (84.2.1)" in out


def test_the_command_line_fails_on_an_incomplete_wheel_and_names_the_file(tmp_path, monkeypatch, capsys):
    tracked = _tracked()
    monkeypatch.setattr(cwl, "tracked_files", lambda root=cwl.ROOT: tracked)
    wheel = _write_wheel(tmp_path / "bad.whl", [p for p in _wheel(tracked) if p != "configs/sources.yml"])
    assert cwl.main([str(wheel)]) == 1
    out = capsys.readouterr().out
    assert "problem(s) in the wheel's layout" in out and "configs/sources.yml" in out and "setuptools (84.2.1)" in out


@pytest.mark.parametrize("argv", [[], ["a.whl", "b.whl"], ["no-such-wheel.whl"]])
def test_the_command_line_refuses_anything_but_exactly_one_existing_wheel(argv, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cwl, "tracked_files", lambda root=cwl.ROOT: pytest.fail("a usage error must not read the tree"))
    assert cwl.main(argv) == 2
    assert capsys.readouterr().out == ""
