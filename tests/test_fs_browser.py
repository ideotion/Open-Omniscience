"""Server-side folder picker: lists subdirs only, traversal-safe (P1 #8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.api.files import list_directory


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir()
    (root / ".hidden").mkdir()
    (root / "a_file.txt").write_text("x", encoding="utf-8")
    return root


def test_lists_only_subdirectories(tmp_path):
    root = _tree(tmp_path)
    out = list_directory(str(root))
    names = [e["name"] for e in out["entries"]]
    assert names == ["alpha", "beta"]  # sorted, folders only, hidden excluded
    assert "a_file.txt" not in names  # NEVER expose file names
    assert out["path"] == str(root.resolve())
    assert out["parent"] == str(root.parent)
    assert out["writable"] is True


def test_show_hidden_includes_dot_dirs(tmp_path):
    root = _tree(tmp_path)
    names = [e["name"] for e in list_directory(str(root), show_hidden=True)["entries"]]
    assert ".hidden" in names


def test_nonexistent_path_falls_back_to_home_not_an_error(tmp_path):
    out = list_directory(str(tmp_path / "does-not-exist"))
    assert out["path"] == str(Path.home())  # graceful fallback, never a 500


def test_a_file_path_falls_back_to_home(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    assert list_directory(str(f))["path"] == str(Path.home())


def test_entries_are_bounded(tmp_path, monkeypatch):
    import src.api.files as files

    monkeypatch.setattr(files, "_MAX_ENTRIES", 3)
    root = tmp_path / "many"
    root.mkdir()
    for i in range(10):
        (root / f"d{i:02d}").mkdir()
    out = files.list_directory(str(root))
    assert len(out["entries"]) == 3 and out["truncated"] is True


def test_empty_path_lists_home(tmp_path):
    assert list_directory(None)["path"] == str(Path.home())
