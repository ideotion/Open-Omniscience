"""Audit 0.5.0 A-016: the legacy restore's 2 GiB cap is checked on the file's size BEFORE it is read into memory."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api import backup_v2


def test_a_file_over_the_cap_is_refused_before_a_byte_is_read(tmp_path, monkeypatch):
    big = tmp_path / "huge.bak"
    with big.open("wb") as fh:
        fh.truncate(backup_v2._MAX_RESTORE_BYTES + 1)  # sparse: no disk is spent
    monkeypatch.setattr(backup_v2, "check_memory_before_staging", lambda: None)

    def never(self, *a, **k):
        raise AssertionError("the file was read although it is over the cap")

    monkeypatch.setattr(Path, "read_bytes", never)
    with pytest.raises(HTTPException) as raised:
        backup_v2.restore_legacy_path(str(big), None)
    assert raised.value.status_code == 413
    assert "2 GiB" in str(raised.value.detail)
