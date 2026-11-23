"""Row 340 (R800): a backup's signature shows the content is unchanged, never where it came from.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The key that signed a backup travels in the same file, so a verified signature proves only that the
content is unchanged since that key signed it. The app states exactly two things about a signer:
"signed by this installation" (the key equals this installation's own) or "signed by another
installation, key <fp>" -- a fact, never a tampering warning. Stored values (``origin_fingerprint``,
the provenance tag's ``origin``) are read as they are and never rewritten (R755); the relation is
computed when it is shown.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.backup import artifact
from src.backup.artifact import SIGNER_RELATIONS, signer_relation

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"
KEY = "ab" * 32
OTHER = "cd" * 32


def test_signer_relation_states_only_what_the_comparison_shows():
    assert signer_relation(KEY, KEY) == "this-installation"
    assert signer_relation(KEY.upper(), KEY) == "this-installation"
    assert signer_relation(KEY, OTHER) == "another-installation"
    assert signer_relation(KEY, None) == "not-compared"
    for stored in ("unsigned", "unknown-origin", "local", "", None, "ab" * 31):
        # row 345: a stored value that is not a key cannot tell unsigned from a failed signature
        assert signer_relation(stored, KEY) == "unverified", stored
    assert signer_relation("bad-signature", KEY) == "bad-signature"
    assert set(SIGNER_RELATIONS) == {
        "this-installation",
        "another-installation",
        "not-compared",
        "unsigned",
        "bad-signature",
        "unverified",
    }


def test_the_merge_gate_words_what_was_checked(tmp_path):
    from src.backup.artifact import ACCEPTED_BACKUP_SCHEMAS, StagedArtifact
    from src.backup.merge import MergeError, prepare_staged_corpus

    for state, words in (
        ("unsigned", "artifact manifest is not signed"),
        ("bad-signature", "artifact manifest signature does not match its content"),
    ):
        staged = StagedArtifact(
            kind=ACCEPTED_BACKUP_SCHEMAS[0],
            staging_dir=tmp_path,
            corpus_path=tmp_path / "c.db",
            custody_path=None,
            manifest={},
            signature_state=state,
            origin_fingerprint="unsigned",
        )
        with pytest.raises(MergeError) as exc:
            prepare_staged_corpus(staged)
        msg = str(exc.value)
        assert msg.startswith(words), msg
        assert "origin" not in msg and "allow_unverified" in msg


def test_volume_verify_names_the_signing_key_and_compares_it(tmp_path, monkeypatch):
    from src.backup.stream_backup import verify_stream_backup
    from tests.test_stream_backup import _backup, _make_corpus

    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)

    mine = artifact.this_installation_key()
    assert mine, "the backup was signed with this installation's key, which must be readable"
    rep = verify_stream_backup(dest)
    assert rep["ok"] is True and rep["signature"] == "verified"
    assert rep["signer_key"] == mine and rep["signed_by"] == "this-installation"

    monkeypatch.setattr(artifact, "this_installation_key", lambda: OTHER)
    rep = verify_stream_backup(dest)
    assert rep["ok"] is True, "another installation's key is a fact, never a failure"
    assert rep["signed_by"] == "another-installation" and rep["signer_key"] == mine

    monkeypatch.setattr(artifact, "this_installation_key", lambda: None)
    assert verify_stream_backup(dest)["signed_by"] == "not-compared"


def test_alternates_add_the_signer_to_arrived_tags_only():
    from src.backup.alternates import _with_signer

    item = {
        "imported_provenance": {"origin": KEY, "arrived": {"batch": 1}},
        "local_provenance": {"origin": "local", "arrived": None},
    }
    out = _with_signer(item, KEY)
    assert out["imported_provenance"]["signed_by"] == "this-installation"
    assert out["imported_provenance"]["origin"] == KEY, "the stored value is kept as it is"
    assert "signed_by" not in out["local_provenance"]
    assert (
        _with_signer({"imported_provenance": {"origin": KEY, "arrived": {"batch": 1}}}, OTHER)[
            "imported_provenance"
        ]["signed_by"]
        == "another-installation"
    )


def test_the_p0_pass_names_whose_key_signed_never_an_origin():
    from src.monitoring.p0_validation import _acceptance_bars, _signed_by_words

    assert (
        _signed_by_words("this-installation", KEY) == f"signed by this installation, key {KEY[:16]}"
    )
    assert (
        _signed_by_words("another-installation", KEY)
        == f"signed by another installation, key {KEY[:16]}"
    )
    assert _signed_by_words("not-compared", KEY) == f"signed by key {KEY[:16]}"
    assert _signed_by_words("unsigned", None) == "signer key not recorded"
    bar = _acceptance_bars()["p0_1_verify"]
    assert "never shows who made the backup" in bar


def test_the_ui_helpers_and_the_words_x12():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "backup_signer_row340_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    js = (STATIC / "app-backup.js").read_text(encoding="utf-8")
    assert "Arrived from {origin}" not in js
    assert 'String(b.origin || "").slice(0, 12)' not in js
    assert 'ooLabelHtml(esc(t("signature"))' not in js
    keys = [
        "Content unchanged since it was signed",
        "Signed by this installation, key {fp}",
        "Signed by another installation, key {fp}",
        "Signed by key {fp}",
        "Not signed",
        "Signature does not match its content",
        "Arrived in the restore of {date}",
    ]
    locales = sorted((STATIC / "locales").glob("*.json"))
    assert len(locales) == 12
    for f in locales:
        loc = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert loc.get(k), (f.stem, k)
            if "{fp}" in k:
                assert "{fp}" in loc[k], (f.stem, k)
        for gone in ("Arrived from {origin}, restore of {date}", "signature"):
            assert gone not in loc, (f.stem, gone)
