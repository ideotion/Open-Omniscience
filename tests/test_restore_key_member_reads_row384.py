"""Row 384: a member at an app key name that is not a regular file, or is longer than any key file, is refused as not
read and the import goes on; nothing is read past the check (the row 336/342/341 treatment for key members).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.backup import merge
from src.custody import keyfile
from tests.test_restore_key_rewrap import CUSTODY_ED, CUSTODY_ML, EVIDENCE, HERE, SOURCE, _hold, _ml_blob, _stage, _wrapped
from tests.test_restore_key_rewrap import _nothing_held_unless_a_test_holds_one  # noqa: F401 - the same isolation

posix_only = pytest.mark.skipif(os.name == "nt", reason="FIFOs and /dev/zero")


def _swap(staged, name: str, make) -> None:
    path = staged.staging_dir / name
    path.unlink()
    make(path)


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda p: p.mkdir(), id="folder"),
        pytest.param(lambda p: os.mkfifo(p), id="fifo", marks=posix_only),
        pytest.param(lambda p: os.symlink("/dev/zero", p), id="link-to-dev-zero", marks=posix_only),
        pytest.param(lambda p: p.write_bytes(b"x" * (keyfile.MAX_KEY_FILE_BYTES + 1)), id="longer-than-any-key"),
    ],
)
def test_an_app_name_that_is_no_key_file_is_refused_unread(tmp_path, monkeypatch, make):
    _hold(monkeypatch, HERE)
    staged, live = _stage(tmp_path, {EVIDENCE: b"placeholder"}, SOURCE)
    _swap(staged, EVIDENCE, make)
    out = merge.merge_side_files(staged)["keys"]  # no error: the import goes on
    why = {e["name"]: e["reason"] for e in out["not_placed"]}
    assert why == {EVIDENCE: merge._KEY_UNREADABLE}, out
    assert out["restored"] == [] and not os.path.lexists(live / EVIDENCE)


def test_an_unreadable_half_refuses_its_pair(tmp_path, monkeypatch):
    _hold(monkeypatch, HERE)
    staged, live = _stage(
        tmp_path,
        {
            CUSTODY_ED: _wrapped(Ed25519PrivateKey.generate(), SOURCE),
            CUSTODY_ML: _ml_blob(),
            EVIDENCE: _wrapped(Ed25519PrivateKey.generate(), HERE),
        },
        SOURCE,
    )
    _swap(staged, CUSTODY_ML, lambda p: p.mkdir())
    out = merge.merge_side_files(staged)["keys"]
    why = {e["name"]: e["reason"] for e in out["not_placed"]}
    assert why == {CUSTODY_ED: merge._KEY_PAIR_HALF, CUSTODY_ML: merge._KEY_UNREADABLE}, out
    assert not (live / CUSTODY_ED).exists() and not (live / CUSTODY_ML).exists()
    assert EVIDENCE in out["restored"]


def test_a_key_of_exactly_the_cap_is_still_read(tmp_path):
    p = tmp_path / "k"
    p.write_bytes(b"k" * keyfile.MAX_KEY_FILE_BYTES)
    assert merge._read_key_member(p) == b"k" * keyfile.MAX_KEY_FILE_BYTES
    p.write_bytes(b"k" * (keyfile.MAX_KEY_FILE_BYTES + 1))
    assert merge._read_key_member(p) is None
    assert merge._read_key_member(tmp_path / "missing") is None


def test_the_reason_is_translated_in_every_locale():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    files = sorted(root.glob("*.json"))
    assert len(files) == 12
    for f in files:
        assert merge._KEY_UNREADABLE in json.loads(f.read_text(encoding="utf-8")), f.name
