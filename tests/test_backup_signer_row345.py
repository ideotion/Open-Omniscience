"""Row 345 (R800 item 1): a signature that was present but did not match is never shown as "Not signed".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A bad-signature backup merged with ``allow_unverified`` used to be stored as ``"unsigned"``, so its rows
read "Not signed". New merges store ``"bad-signature"`` (an additive value; earlier rows are not
rewritten, R755). A stored ``"unsigned"`` cannot tell the two apart, so it reads "No verified
signature"; "Not signed" stays only where the live state is known (a verify, a restore report).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.backup.artifact import StagedArtifact, signer_relation

STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
KEY = "ab" * 32


def _staged(tmp_path: Path, state: str, fp: str = "unsigned") -> StagedArtifact:
    return StagedArtifact(
        kind="oo-backup-3",
        staging_dir=tmp_path,
        corpus_path=tmp_path / "c.db",
        custody_path=None,
        manifest={},
        signature_state=state,
        origin_fingerprint=fp,
    )


def test_new_merges_store_a_failed_signature_as_such(tmp_path):
    from src.backup.merge import _stored_signer

    assert _stored_signer(_staged(tmp_path, "bad-signature")) == "bad-signature"
    assert _stored_signer(_staged(tmp_path, "unsigned")) == "unsigned"
    assert _stored_signer(_staged(tmp_path, "verified", KEY)) == KEY


def test_the_live_report_knows_which_one_it_was(tmp_path):
    from src.backup.merge import _signed_by

    assert _signed_by(_staged(tmp_path, "bad-signature")) == "bad-signature"
    assert _signed_by(_staged(tmp_path, "unsigned")) == "unsigned"


def test_a_stored_record_reads_by_what_it_can_tell():
    assert signer_relation("bad-signature", KEY) == "bad-signature"
    assert signer_relation("unsigned", KEY) == "unverified", (
        "an old row may have held a failed signature"
    )


def test_the_volume_verify_names_a_failed_signature(tmp_path):
    from src.backup.stream_backup import verify_stream_backup
    from src.backup.volumes import MANIFEST_NAME
    from tests.test_stream_backup import _backup, _make_corpus

    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus)
    dest = tmp_path / "dest"
    _backup(tmp_path, dest, corpus)
    mp = dest / MANIFEST_NAME
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["signature"]["signature"] = "00" * 64
    mp.write_text(json.dumps(m), encoding="utf-8")
    rep = verify_stream_backup(dest)
    assert rep["signature"] == "bad-signature" and rep["signed_by"] == "bad-signature"
    assert rep["signer_key"] is None


def test_a_failed_signature_is_never_grouped_as_a_signer(tmp_path):
    """Plan's check: nothing that keys by the stored signer treats "bad-signature" as a key or files it
    with genuine signers. The custody chain id files every non-key under "unknown-origin"; the display
    never compares it with this installation's key; a stored "bad-signature" cannot equal a 64-hex key,
    which is what the alternates and provenance group on."""
    import re

    from src.backup.merge import _custody_chain_id, _stored_signer

    assert _custody_chain_id("bad-signature") == "unknown-origin"
    assert _custody_chain_id("unsigned") == "unknown-origin"
    assert _custody_chain_id(KEY) == KEY
    assert _custody_chain_id(KEY.upper()) == KEY.upper(), "a chain id is kept as written"
    stored = _stored_signer(_staged(tmp_path, "bad-signature", KEY))
    assert stored == "bad-signature" and not re.fullmatch(r"[0-9a-fA-F]{64}", stored)
    for local in (KEY, "bad-signature", None):
        assert signer_relation(stored, local) == "bad-signature"


def test_the_word_x12():
    locales = sorted((STATIC / "locales").glob("*.json"))
    assert len(locales) == 12
    for f in locales:
        assert json.loads(f.read_text(encoding="utf-8")).get("No verified signature"), f.stem
    js = (STATIC / "app-backup.js").read_text(encoding="utf-8")
    assert 'if (!/^[0-9a-f]{64}$/i.test(k)) return t("No verified signature");' in js
