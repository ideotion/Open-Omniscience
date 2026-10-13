"""S3 of the read: when no passphrase opens the corpus member, a non-driver failure to open it is named by class."""

from __future__ import annotations

import sqlite3

import pytest

from src.backup import stream_backup
from src.backup.volumes import VolumeError


def _fail_with(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr("src.database.connect.connect", boom)


def test_a_file_failure_is_named_by_its_class(monkeypatch, tmp_path):
    _fail_with(monkeypatch, PermissionError("/secret/path denied"))
    with pytest.raises(VolumeError) as ei:
        stream_backup._export_plaintext_with_keys(tmp_path / "a", tmp_path / "b", ["k1"])
    assert "PermissionError" in str(ei.value) and "/secret/path" not in str(ei.value)


def test_a_driver_failure_is_not_named(monkeypatch, tmp_path):
    _fail_with(monkeypatch, sqlite3.OperationalError('near "horse-battery": syntax error'))
    with pytest.raises(VolumeError) as ei:
        stream_backup._export_plaintext_with_keys(tmp_path / "a", tmp_path / "b", ["k1"])
    assert "OperationalError" not in str(ei.value) and "horse-battery" not in str(ei.value)
