"""The import queue's early passphrase check never follows a volume link out of the chosen backup folder.

Security read of #2022 (2026-11-16): ``backup_passphrase_is_wrong`` ran before the restore's own volume checks, so a volume
that is a symbolic link to a file elsewhere was opened and hashed in full, and the answer told whether that file hashed to the
manifest's value. The restore itself refuses such a volume by name; the early check now refuses to read it too."""

from __future__ import annotations

import json
import os

import pytest

from src.backup.stream_backup import STREAM_KIND, backup_passphrase_is_wrong
from src.backup.volumes import _sha256_file
from src.safety.crypto import encrypt_file

pytestmark = pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symbolic links")


def _set(tmp_path, *, link: bool):
    outside, chosen = tmp_path / "outside", tmp_path / "chosen"
    outside.mkdir()
    chosen.mkdir()
    plain = outside / "p.bin"
    plain.write_bytes(b"x" * 4096)
    target = outside / "elsewhere.ooenc"
    encrypt_file(plain, target, "right")
    volume = chosen / "v0001.ooenc"
    if link:
        try:
            os.symlink(target, volume)
        except OSError:
            pytest.skip("this system does not let the test make a symbolic link")
    else:
        volume.write_bytes(target.read_bytes())
    manifest = {"kind": STREAM_KIND, "volumes": [{"name": "v0001.ooenc", "sha256": _sha256_file(target)}],
                "members": [{"name": "corpus.db", "volumes": ["v0001.ooenc"]}]}
    (chosen / "volumes.json").write_text(json.dumps(manifest), encoding="utf-8")
    return chosen, target


def test_a_volume_that_links_out_of_the_folder_is_never_read(tmp_path, monkeypatch):
    chosen, target = _set(tmp_path, link=True)
    import src.backup.stream_backup as sb

    opened = []
    real = sb.stream_key_opens
    monkeypatch.setattr(sb, "stream_key_opens", lambda p, pw, **kw: opened.append(p) or real(p, pw, **kw))
    hashed = []
    real_hash = sb._digest_matches  # the stream reader hashes a volume through this since row 312
    monkeypatch.setattr(sb, "_digest_matches", lambda p, want, **kw: hashed.append(p) or real_hash(p, want, **kw))
    assert backup_passphrase_is_wrong(chosen, "wrong") is False  # no verdict: the restore refuses the link by name
    assert opened == [] and hashed == []


def test_a_real_volume_still_gets_its_early_verdict(tmp_path):
    chosen, _ = _set(tmp_path, link=False)
    assert backup_passphrase_is_wrong(chosen, "wrong") is True
    assert backup_passphrase_is_wrong(chosen, "right") is False
