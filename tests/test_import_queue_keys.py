"""One import run, many backups, any passphrases (2026-11-15).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's ask: a run must import backups locked with different passphrases, while the usual case (every backup
shares one) is typed once. So the run carries DEFAULT keys (the backup's, and the corpus store passphrase of the
instance that made the backup) and each item may carry its own. Pinned here: each item's restore gets the right pair,
no key ever reaches the queue file, every key is scrubbed, and all of them are dropped when the run ends. Plus the
early wrong-passphrase refusal, which must refuse an intact volume and never a damaged one.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.backup.import_queue import ImportQueueManager


class _FakeVolumes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def start_restore(self, path, passphrase, **kw):
        self.calls.append((path, passphrase, kw.get("corpus_passphrase")))
        return {}

    def status(self):
        return {"state": "done", "summary": {"report": {"plan": {}}}, "progress": {"phase": "done"}}

    def cancel(self):
        pass


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    import src.backup.volume_job as VJ
    import src.scheduler.runner as R

    monkeypatch.setattr(R, "pause_for_exclusive_operation", lambda *a, **k: True)
    monkeypatch.setattr(R, "resume_after_exclusive_operation", lambda *a, **k: None)
    vols = _FakeVolumes()
    monkeypatch.setattr(VJ, "get_volume_manager", lambda: vols)
    mgr = ImportQueueManager(state_path=tmp_path / "q.json")
    mgr._checkpoint_k = 1  # one restore per item: the keys, not the checkpoint groups, are under test
    mgr._vols = vols  # type: ignore[attr-defined]
    return mgr


def _drain(mgr, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if mgr.status()["state"] != "running":
            return mgr.status()
        time.sleep(0.02)
    raise AssertionError("queue never finished")


def test_typed_once_every_backup_gets_the_runs_keys(queue):
    queue.start(
        [{"kind": "corpus", "path": "/b/1"}, {"kind": "corpus", "path": "/b/2"}],
        passphrase="shared backup words",
        corpus_passphrase="shared store words",
    )
    assert _drain(queue)["state"] == "done"
    assert queue._vols.calls == [
        ("/b/1", "shared backup words", "shared store words"),
        ("/b/2", "shared backup words", "shared store words"),
    ]


def test_a_backup_with_its_own_keys_uses_them_and_only_it(queue):
    queue.start(
        [
            {"kind": "corpus", "path": "/b/1"},
            {"kind": "corpus", "path": "/b/2", "passphrase": "other backup words"},
            {"kind": "corpus", "path": "/b/3", "corpus_passphrase": "other store words"},
        ],
        passphrase="shared backup words",
    )
    assert _drain(queue)["state"] == "done"
    assert queue._vols.calls == [
        ("/b/1", "shared backup words", None),
        ("/b/2", "other backup words", None),
        ("/b/3", "shared backup words", "other store words"),
    ]


def test_no_key_reaches_the_queue_file_or_the_status_and_all_are_dropped(queue, tmp_path):
    keys = ("shared backup words", "shared store words", "own backup words", "own store words")
    queue.start(
        [{"kind": "corpus", "path": "/b/1", "passphrase": keys[2], "corpus_passphrase": keys[3]}],
        passphrase=keys[0],
        corpus_passphrase=keys[1],
    )
    st = _drain(queue)
    on_disk = (tmp_path / "q.json").read_text(encoding="utf-8")
    shown = json.dumps(st)
    for k in keys:
        assert k not in on_disk and k not in shown
    assert queue._secrets() == ()
    assert queue._keys_for({"id": "0-corpus"}) == ("", "")


def test_a_failure_quoting_any_key_is_scrubbed(queue, monkeypatch):
    def boom(item, *, hold=False):
        raise RuntimeError("could not open with own store words or shared backup words")

    monkeypatch.setattr(queue, "_run_corpus", boom)
    queue.start(
        [{"kind": "corpus", "path": "/b/1", "corpus_passphrase": "own store words"}],
        passphrase="shared backup words",
    )
    st = _drain(queue)
    err = st["items"][0]["error"] or ""
    assert "own store words" not in err and "shared backup words" not in err


# --------------------------------------------------------------------------- #
#  the early wrong-passphrase refusal
# --------------------------------------------------------------------------- #
def _one_volume(tmp_path: Path, passphrase: str) -> tuple[Path, dict]:
    from src.backup.volumes import _sha256_file
    from src.safety.crypto import encrypt_file

    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"x" * 300_000)
    vol = tmp_path / "v0001.ooenc"
    encrypt_file(plain, vol, passphrase)
    m = {"volumes": [{"name": vol.name, "sha256": _sha256_file(vol)}], "members": [{"name": "corpus.db", "volumes": [vol.name]}]}
    return vol, m


def _signed_here(m: dict, tmp_path: Path, monkeypatch) -> dict:
    """``m`` signed by this installation's own key (a key file of the test's own, never the suite's)."""
    import src.reporting.evidence as EV
    from src.backup.stream_backup import _sign_manifest

    monkeypatch.setattr(EV, "_default_key_path", lambda: tmp_path / "keys" / "evidence_ed25519.pem")
    return {**m, "signature": _sign_manifest(m)}


def test_an_unchanged_volume_that_does_not_open_is_refused_at_once(tmp_path, monkeypatch):
    from src.backup.stream_backup import WrongBackupPassphrase, _refuse_a_wrong_backup_passphrase

    _vol, m = _one_volume(tmp_path, "the right words")
    m = _signed_here(m, tmp_path, monkeypatch)
    _refuse_a_wrong_backup_passphrase(tmp_path, m, "the right words")  # the right key passes silently
    with pytest.raises(WrongBackupPassphrase, match="wrong passphrase for this backup"):
        _refuse_a_wrong_backup_passphrase(tmp_path, m, "the wrong words")


def test_an_unsigned_list_is_still_refused_but_never_called_a_wrong_passphrase(tmp_path):
    """R795: without a signature by this installation, "does not open" cannot be told apart from "was changed"."""
    from src.backup.stream_backup import (
        REASON_UNSIGNED,
        BackupPassphraseUnchecked,
        _refuse_a_wrong_backup_passphrase,
    )

    _vol, m = _one_volume(tmp_path, "the right words")
    _refuse_a_wrong_backup_passphrase(tmp_path, m, "the right words")
    with pytest.raises(BackupPassphraseUnchecked, match="could not check the passphrase for this backup") as refused:
        _refuse_a_wrong_backup_passphrase(tmp_path, m, "the wrong words")
    assert refused.value.reason == REASON_UNSIGNED
    assert "wrong passphrase for" not in str(refused.value) and "intact" not in str(refused.value)


def test_a_damaged_or_missing_volume_gives_no_verdict(tmp_path):
    """The checksum pass and parity recovery own damage: the early check must never refuse a set they could restore."""
    from src.backup.stream_backup import _refuse_a_wrong_backup_passphrase

    vol, m = _one_volume(tmp_path, "the right words")
    data = bytearray(vol.read_bytes())
    data[-5] ^= 0xFF
    vol.write_bytes(bytes(data))
    _refuse_a_wrong_backup_passphrase(tmp_path, m, "the right words")
    _refuse_a_wrong_backup_passphrase(tmp_path, m, "the wrong words")
    vol.unlink()
    _refuse_a_wrong_backup_passphrase(tmp_path, m, "the wrong words")


def test_the_key_check_reads_one_chunk_of_a_many_chunk_file(tmp_path):
    from src.safety.crypto import encrypt_file, stream_key_opens

    plain = tmp_path / "plain.bin"
    plain.write_bytes(bytes(range(256)) * 40_000)  # about 10 MB: several chunks
    enc = tmp_path / "f.ooenc"
    encrypt_file(plain, enc, "the right words")
    assert stream_key_opens(enc, "the right words") is True
    assert stream_key_opens(enc, "the wrong words") is False
    small = tmp_path / "s.bin"
    small.write_bytes(b"tiny")
    enc1 = tmp_path / "s.ooenc"
    encrypt_file(small, enc1, "the right words")
    assert stream_key_opens(enc1, "the right words") is True


def test_a_set_whose_passphrase_is_certainly_wrong_is_named_and_nothing_else_is(tmp_path, monkeypatch):
    from src.backup.stream_backup import STREAM_KIND, backup_passphrase_is_wrong

    _vol, m = _one_volume(tmp_path, "the right words")
    m = _signed_here({"kind": STREAM_KIND, **m}, tmp_path, monkeypatch)
    (tmp_path / "volumes.json").write_text(json.dumps(m), encoding="utf-8")
    assert backup_passphrase_is_wrong(tmp_path, "the wrong words") is True
    assert backup_passphrase_is_wrong(tmp_path, "the right words") is False
    assert backup_passphrase_is_wrong(tmp_path / "nowhere", "the wrong words") is False  # unreadable: no verdict


def test_the_run_is_refused_before_anything_starts_when_one_backup_key_is_wrong(queue, monkeypatch, tmp_path):
    """A typo in one backup's own passphrase must not cost the backups staged with it: the whole run is checked first."""
    import src.backup.stream_backup as SB

    seen: list[tuple[str, str]] = []

    def wrong(path, key):
        seen.append((path, key))
        return ("wrong", None) if path == "/b/2" else ("none", None)

    monkeypatch.setattr(SB, "backup_passphrase_check", wrong)
    with pytest.raises(ValueError, match="Wrong passphrase for two") as err:
        queue.start(
            [{"kind": "corpus", "path": "/b/1"}, {"kind": "corpus", "path": "/b/2", "label": "two", "passphrase": "typo words"}],
            passphrase="shared backup words",
        )
    assert "typo words" not in str(err.value)
    assert seen == [("/b/1", "shared backup words"), ("/b/2", "typo words")]
    assert queue.status()["state"] == "idle" and queue._vols.calls == []
    assert queue._secrets() == ()


def test_keys_are_dropped_even_when_the_run_itself_raises(queue, monkeypatch):
    def boom():
        raise RuntimeError("the run fell over")

    monkeypatch.setattr(queue, "_run_with_keys", boom)
    queue._passphrase, queue._item_keys = "held words", {"0-corpus": ("own words", "")}
    with pytest.raises(RuntimeError):
        queue._run()
    assert queue._secrets() == ()
