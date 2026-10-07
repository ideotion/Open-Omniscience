"""A restore that failed on a ``UnicodeError`` is answered by its class and a fixed note, never by its words.

A ``UnicodeError``'s text names a character and its offset, which is a piece of a key that no scrub knows (one character matches
no held shape). ``classify_restore_error`` used to write ``str(exc)`` into its sentence, and the legacy route's 500 and the volume
restore's status are both made from it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.backup.merge import MergeError, classify_restore_error, restore_failure_text
from src.monitoring.secret_scrub import UNICODE_WITHHELD

_KEY = "pass\udcffword-of-the-backup"


def _unicode_failure() -> Exception:
    try:
        try:
            _KEY.encode("utf-8")
        except UnicodeError as inner:
            raise RuntimeError("could not use the key") from inner
    except RuntimeError as exc:
        return exc
    raise AssertionError("unreachable")


def test_a_unicode_error_in_the_chain_is_classified_by_class_and_a_fixed_note():
    out = classify_restore_error("restore", _unicode_failure())
    assert UNICODE_WITHHELD in out and out.startswith("could not restore this backup: ")
    assert "udcff" not in out and "position" not in out and "surrogate" not in out


def test_the_sentence_a_restore_is_answered_with_never_carries_the_character_or_its_offset():
    for failure in (_unicode_failure(), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")):
        out = restore_failure_text("restore", failure, "unrelated-secret")
        assert UNICODE_WITHHELD in out
        assert "0xff" not in out and "invalid start byte" not in out and "udcff" not in out


def test_a_refusal_keeps_its_own_message_and_any_other_failure_is_classified():
    assert restore_failure_text("restore", MergeError("the corpus is too large"), "a-secret") == "the corpus is too large"
    assert restore_failure_text("restore", RuntimeError("disk full"), "a-secret") == "could not restore this backup: disk full"


def test_the_legacy_route_and_the_volume_job_answer_a_unicode_failure_by_class_only(tmp_path):
    from src.api.backup_v2 import _restore_error
    from src.backup.volume_job import VolumeBackupManager

    assert UNICODE_WITHHELD in _restore_error("restore", _unicode_failure(), "x-secret").detail

    def fail(*_a, **_k):
        raise _unicode_failure()

    mgr = VolumeBackupManager()
    mgr._run_restore(tmp_path / "set", "backup-passphrase", False, None, fail)
    state = mgr.status()
    assert state["state"] == "error" and UNICODE_WITHHELD in state["error"]
    assert "udcff" not in state["error"] and "surrogate" not in state["error"]


@pytest.mark.parametrize("action", ["restore", "import"])
def test_the_class_only_sentence_names_the_action(action):
    assert classify_restore_error(action, _unicode_failure()).startswith(f"could not {action} this backup: ")
