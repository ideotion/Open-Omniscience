"""Backups must stage on the DATA DIR (real disk), never the system temp dir.

Field report 2026-06-18: a backup failed with "[Errno 28] No space left on
device" on a box with dozens of GB free disk, because /tmp is tmpfs (RAM-backed)
on Fedora/Qubes and building a ~460 MB snapshot + zip there exhausted RAM. The
fix routes every create-path temp file to data_dir(); these guard it.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "api" / "backup_v2.py"


def test_staging_dir_is_the_data_dir(monkeypatch, tmp_path):
    import src.api.backup_v2 as bv2

    target = tmp_path / "oo-data"
    monkeypatch.setattr(bv2, "data_dir", lambda: target)
    got = bv2._staging_dir()
    assert got == str(target)
    assert target.is_dir()  # created on demand


def test_no_backup_temp_file_falls_back_to_system_tmp():
    """Every mkstemp on the create path must pass dir=_staging_dir() — never the
    default /tmp (tmpfs). A regression here re-introduces the OOM/Errno-28 bug."""
    src = _SRC.read_text(encoding="utf-8")
    calls = re.findall(r"tempfile\.mkstemp\([^)]*\)", src)
    assert calls, "expected mkstemp calls in backup_v2.py"
    for call in calls:
        assert "dir=_staging_dir()" in call, (
            f"backup temp file must stage on the data dir, not /tmp: {call}"
        )
