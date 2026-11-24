"""Row 403: a keys folder that cannot be opened is "could not read the key", never an error and never "no key".

``Path.exists()`` swallows only a missing path; on a keys folder that cannot be searched (EACCES) it raised, so
``is_this_installations_key`` and ``signing_key_state`` raised where they promise an answer. The R795 passphrase check
then stopped a restore on a raw error instead of "could not check: this installation's key could not be read", the row 339
step raised instead of withholding trust, and the export review raised instead of saying "unreadable". Now any failure to
look other than "not there" is unreadable: never this installation's own key, and never no key at all.

What the tests simulate: ``stat`` refusing with EACCES as the evidence module sees it (``scope_os``), since a real mode-000
folder cannot refuse the root user the suite may run as. That pins the new pre-check; the raise itself came from
``Path.exists()``, which these patches do not reach (reproduced by hand as a non-root user).
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import src.reporting.evidence as EV
from src.backup.stream_backup import (
    REASON_OWN_KEY_UNREADABLE,
    UNCHECKED_BACKUP_PASSPHRASE,
    WRONG_BACKUP_PASSPHRASE,
    BackupPassphraseUnchecked,
    backup_passphrase_check,
    read_stream_backup,
)
from tests.os_scope import scope_os
from tests.test_backup_passphrase_trust_r795 import _stream_set


@pytest.fixture
def own_key(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "keys" / "evidence_ed25519.pem"
    monkeypatch.setattr(EV, "_default_key_path", lambda: path)
    return path


def _keys_folder_cannot_be_opened(monkeypatch, keys: Path) -> None:
    """What ``stat`` answers under a keys folder without search permission, as the evidence module sees it."""
    real = os.stat

    def refuse(p, *a, **k):
        if Path(p).parent == keys:
            raise PermissionError(errno.EACCES, "Permission denied", str(p))
        return real(p, *a, **k)

    scope_os(monkeypatch, EV, stat=refuse)


def test_the_comparison_has_no_answer_instead_of_raising(tmp_path, own_key, monkeypatch):
    pub = EV.public_key_hex(EV.load_or_create_signing_key())
    assert EV.is_this_installations_key(pub) is True
    _keys_folder_cannot_be_opened(monkeypatch, own_key.parent)
    assert EV.is_this_installations_key(pub) is None  # never "own", never "no key"
    assert EV.is_this_installations_key("00" * 32) is None


def test_the_export_review_says_unreadable_never_none(tmp_path, own_key, monkeypatch):
    EV.load_or_create_signing_key()
    _keys_folder_cannot_be_opened(monkeypatch, own_key.parent)
    assert EV.signing_key_state() == ("unreadable", None)


def test_a_missing_key_or_folder_is_still_no_key(tmp_path, own_key):
    assert EV.is_this_installations_key("00" * 32) is False
    assert EV.signing_key_state() == ("none", None)  # no keys folder yet: export makes it and the key
    own_key.parent.mkdir(parents=True)
    assert EV.signing_key_state() == ("none", None)


def test_a_keys_path_under_a_file_is_not_own_and_promises_no_key(tmp_path, own_key):
    """ENOTDIR: not this installation's key, but export could not create one there, so the review never says "none"."""
    own_key.parent.mkdir(parents=True)
    own_key.parent.joinpath("not-a-folder").write_text("x", encoding="utf-8")
    beneath_a_file = own_key.parent / "not-a-folder" / "evidence_ed25519.pem"
    assert EV.is_this_installations_key("00" * 32, beneath_a_file) is False
    assert EV.signing_key_state(beneath_a_file) == ("unreadable", None)


def test_a_link_to_nothing_at_the_key_name_is_not_own_and_promises_no_key(tmp_path, own_key):
    own_key.parent.mkdir(parents=True)
    own_key.symlink_to(tmp_path / "gone.pem")
    assert EV.is_this_installations_key("00" * 32) is False
    assert EV.signing_key_state() == ("unreadable", None)
    assert own_key.is_symlink() and not (tmp_path / "gone.pem").exists()  # the review wrote nothing


def test_an_unreadable_key_file_is_unreadable(tmp_path, own_key):
    """(a) The key file's own read fails the same way: unreadable, never own and never none."""
    own_key.parent.mkdir(parents=True)
    own_key.write_bytes(b"not a key at all")
    assert EV.is_this_installations_key("00" * 32) is None
    assert EV.signing_key_state() == ("unreadable", None)


def test_the_restore_says_the_key_could_not_be_read(tmp_path, own_key, monkeypatch):
    """(b) The R795 check: the existing own-key-unreadable wording, never "wrong passphrase" and never "intact"."""
    dest = _stream_set(tmp_path)  # signed by this installation's own key
    assert own_key.exists()
    _keys_folder_cannot_be_opened(monkeypatch, own_key.parent)
    assert backup_passphrase_check(dest, "not the words") == ("unchecked", REASON_OWN_KEY_UNREADABLE)
    with pytest.raises(BackupPassphraseUnchecked) as refused:
        read_stream_backup(dest, "not the words", staging_root=tmp_path / "staging")
    said = str(refused.value)
    assert said == UNCHECKED_BACKUP_PASSPHRASE.format(reason=REASON_OWN_KEY_UNREADABLE)
    assert said != WRONG_BACKUP_PASSPHRASE and "wrong passphrase for" not in said and "intact" not in said


def test_the_merge_withholds_trust_when_its_own_key_cannot_be_read(tmp_path, monkeypatch):
    """Row 339: an artifact signed with this installation's key, read while its keys folder cannot be opened, is not
    called this installation's: the trust decisions it carries are withheld, and the rest imports as before."""
    from tests.test_merge_imported_annotations import _member_from_another_install

    staged = _member_from_another_install(monkeypatch, tmp_path)
    here = tmp_path / "b"
    monkeypatch.setenv("OO_DATA_DIR", str(here))
    key = here / "keys" / "evidence_ed25519.pem"
    monkeypatch.setattr(EV, "_default_key_path", lambda: key)
    staged.origin_fingerprint = EV.public_key_hex(EV.load_or_create_signing_key())
    _keys_folder_cannot_be_opened(monkeypatch, key.parent)
    from src.annotations import store
    from src.backup.merge import merge_side_files

    ann = merge_side_files(staged)["annotations"]
    assert ann["imported_authors"] == 1 and ann["errors"] == []
    assert ann["trust_withheld"]["count"] == 1
    assert store.list_authors()[0]["trusted"] is False
