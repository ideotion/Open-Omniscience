"""The build identity a boot record carries (B1, 2026-10-07): commit, source hash, schema head."""

from __future__ import annotations

from pathlib import Path

from src.monitoring import build_id


def test_the_fingerprint_follows_the_bytes_and_the_names(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    one = build_id.source_fingerprint(tmp_path)
    assert one["files"] == 1 and one["bytes"] == 6
    assert build_id.source_fingerprint(tmp_path) == one
    (tmp_path / "a.py").write_text("x = 2\n")
    assert build_id.source_fingerprint(tmp_path)["source_fingerprint"] != one["source_fingerprint"]
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("")
    assert build_id.source_fingerprint(tmp_path)["files"] == 2


def test_git_commit_reads_head_without_a_subprocess(tmp_path, monkeypatch):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    sha = "ab" * 20
    (git / "refs" / "heads" / "main").write_text(sha + "\n")
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    assert build_id.git_commit(tmp_path) == sha
    (git / "HEAD").write_text(("cd" * 20) + "\n")
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
