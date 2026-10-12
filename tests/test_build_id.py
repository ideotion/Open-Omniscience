"""The build identity a boot record carries (B1, 2026-10-07): commit, source hash, schema head."""

from __future__ import annotations

from pathlib import Path

from src.monitoring import build_id


def test_the_fingerprint_follows_the_bytes_and_the_names(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    one = build_id.source_fingerprint(tmp_path)
    assert one["files"] == 1 and one["bytes"] == 6
    assert build_id.source_fingerprint(tmp_path) == one
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert build_id.source_fingerprint(tmp_path)["source_fingerprint"] != one["source_fingerprint"]
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    assert build_id.source_fingerprint(tmp_path)["files"] == 2


def test_git_commit_reads_head_without_a_subprocess(tmp_path, monkeypatch):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    sha = "ab" * 20
    (git / "refs" / "heads" / "main").write_text(sha + "\n", encoding="utf-8")
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert build_id.git_commit(tmp_path) == sha
    (git / "HEAD").write_text(("cd" * 20) + "\n", encoding="utf-8")
    assert build_id.git_commit(tmp_path) == "cd" * 20
    assert build_id.git_commit(tmp_path / "nowhere") is None


def test_schema_head_agrees_with_alembic():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(build_id.__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "migrations"))
    assert build_id.schema_head() == ScriptDirectory.from_config(cfg).get_current_head()


def test_schema_head_is_none_without_exactly_one_head(tmp_path):
    assert build_id.schema_head(tmp_path) is None


def test_build_identity_is_cached_and_complete():
    build_id._reset_for_tests()
    first = build_id.build_identity()
    assert set(first) == {"commit", "source_fingerprint", "files", "bytes", "schema_head", "took_ms"}
    assert build_id.build_identity() == first


_SHA40 = "0123456789abcdef0123456789abcdef01234567"


def test_git_commit_is_a_whole_object_id_or_nothing(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(_SHA40 + "\n", encoding="utf-8")
    assert build_id.git_commit(tmp_path) == _SHA40
    (git / "HEAD").write_text(_SHA40 * 2 + "\n", encoding="utf-8")  # neither 40 nor 64: cut to nothing, never to a prefix
    assert build_id.git_commit(tmp_path) is None
    (git / "HEAD").write_text("a" * 64 + "\n", encoding="utf-8")
    assert build_id.git_commit(tmp_path) == "a" * 64
    (git / "HEAD").write_text("not a commit\n", encoding="utf-8")
    assert build_id.git_commit(tmp_path) is None


def test_git_commit_resolves_a_relative_gitdir_from_the_file_it_is_in(tmp_path):
    real = tmp_path / "modules" / "m"
    real.mkdir(parents=True)
    (real / "HEAD").write_text(_SHA40 + "\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").write_text("gitdir: ../modules/m\n", encoding="utf-8")
    assert build_id.git_commit(work) == _SHA40
