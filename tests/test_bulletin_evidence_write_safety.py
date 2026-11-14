"""The plaintext evidence archive is written owner-only, never through a link, once at a time, and only on an acknowledged warning.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

PR #1984's security read of ``POST /api/bulletin/evidence/build`` (given a button by that PR) found the write
used a plain ``open``: 0644 under the usual umask while the corpus it copies is 0600, following a symlink planted
at the predictable ``.oopart`` name, and writing into a file someone else had created there (in a shared folder,
that hands them the corpus). It also took a relative or empty destination against the server's working directory,
never expanded ``~``, enforced the plain-text warning only in the page, and let two writes race on one temp name.
"""

from __future__ import annotations

import os
import stat
import sys
import zipfile
from datetime import date

import pytest
from fastapi import HTTPException

from src.api import bulletin as route
from src.bulletin.evidence import build_evidence_archive
from src.bulletin.period import resolve_period
from tests.test_bulletin_evidence import _corpus

_P = resolve_period("weekly", end=date(2026, 8, 1))
_NAME = "20260731-OOS-weekly-evidence.zip"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes and symlinks")


@posix_only
def test_the_archive_is_owner_only_from_its_first_byte(tmp_path):
    old = os.umask(0o022)
    try:
        rep = build_evidence_archive(_corpus(2), {"layer": "A"}, _P, tmp_path)
    finally:
        os.umask(old)
    assert stat.S_IMODE(os.stat(rep["path"]).st_mode) == 0o600
    assert zipfile.ZipFile(rep["path"]).testzip() is None


@posix_only
def test_a_symlink_at_the_temp_name_is_refused_and_its_target_untouched(tmp_path):
    target = tmp_path / "victim.txt"
    target.write_text("keep me")
    (tmp_path / (_NAME + ".oopart")).symlink_to(target)
    with pytest.raises(ValueError, match="in the way"):
        build_evidence_archive(_corpus(2), {"layer": "A"}, _P, tmp_path)
    assert target.read_text() == "keep me"
    assert (tmp_path / (_NAME + ".oopart")).is_symlink(), "a link that is not ours is never removed either"
    assert not (tmp_path / _NAME).exists()


def test_our_own_leftover_temp_file_is_replaced_not_reused(tmp_path):
    left = tmp_path / (_NAME + ".oopart")
    left.write_bytes(b"half an archive from an interrupted run")
    rep = build_evidence_archive(_corpus(1), {"layer": "A"}, _P, tmp_path)
    assert not left.exists()
    assert zipfile.ZipFile(rep["path"]).testzip() is None


def test_a_failed_move_into_place_leaves_no_plaintext_temp_behind(tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("cannot move")

    monkeypatch.setattr("src.bulletin.evidence.os.replace", _boom)
    with pytest.raises(OSError):
        build_evidence_archive(_corpus(1), {"layer": "A"}, _P, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_destination_must_be_a_full_path_and_tilde_is_expanded(monkeypatch, tmp_path):
    for bad in ("", "   ", "relative/dir", "./here", "..", "x"):
        with pytest.raises(HTTPException) as exc:
            route._evidence_dest(bad)
        assert exc.value.status_code == 400, bad
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert route._evidence_dest("~/arch") == os.path.normpath(os.path.join(str(tmp_path), "arch"))
    assert route._evidence_dest(str(tmp_path) + "/a/../b") == os.path.normpath(str(tmp_path) + "/b")


def test_the_build_route_refuses_without_the_plaintext_acknowledgement(monkeypatch, tmp_path):
    monkeypatch.setattr(route, "_require_gate", lambda: {})
    called = []
    monkeypatch.setattr("src.bulletin.evidence.build_evidence_archive", lambda *a, **k: called.append(1) or {})
    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {})
    with pytest.raises(HTTPException) as exc:
        route.evidence_build_route(cadence="weekly", dest=str(tmp_path), edition_file="", plaintext_ack=False, db=None)
    assert exc.value.status_code == 400 and "plain text" in str(exc.value.detail)
    assert not called
    route.evidence_build_route(cadence="weekly", dest=str(tmp_path), edition_file="", plaintext_ack=True, db=None)
    assert called == [1]


def test_a_second_write_while_one_runs_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(route, "_require_gate", lambda: {})
    monkeypatch.setattr("src.bulletin.facts.layer_a", lambda *_a, **_k: {})
    seen = []

    def _inner(*_a, **_k):
        with pytest.raises(HTTPException) as exc:
            route.evidence_build_route(cadence="weekly", dest=str(tmp_path), edition_file="", plaintext_ack=True, db=None)
        seen.append(exc.value.status_code)
        return {}

    monkeypatch.setattr("src.bulletin.evidence.build_evidence_archive", _inner)
    route.evidence_build_route(cadence="weekly", dest=str(tmp_path), edition_file="", plaintext_ack=True, db=None)
    assert seen == [409]
    assert route._EVIDENCE_WRITE.acquire(blocking=False), "the lock is released after the write"
    route._EVIDENCE_WRITE.release()
