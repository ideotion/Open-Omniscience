"""ONE backup-format bump, and every older format still restores (gate row K, Q215 ⛔ = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RESTORE MATRIX these pin, because "every backup made before this PR must still
restore after it" is the whole risk of a format bump:

    oo-backup-2 (the format every existing backup carries) -> this build   ACCEPTED
    oo-backup-3 (what this build writes)                   -> this build   ACCEPTED
    oo-backup-1 (a schema no build ever wrote)             -> this build   REFUSED, by name
    a tampered member                                      -> this build   REFUSED, by name

THE OLD-FORMAT FIXTURE IS GENUINELY SIGNED, not a resigned copy. It is built by the
REAL writer with ``BACKUP_SCHEMA`` patched to the old literal, so the manifest carries
that literal and the Ed25519 signature covers it -- which is what an artifact taken by
last week's build looks like. A fixture made by rewriting a manifest after the fact has
a broken signature, so it would exercise the signature refusal rather than the schema
acceptance, and the test would pass for the wrong reason.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _build_backup(schema: str | None = None) -> bytes:
    """A single-file artifact written by the REAL builder, optionally under an older
    format literal."""
    import os
    import tempfile

    from src.backup import artifact as art

    fd, tmp = tempfile.mkstemp(suffix=".oobak")
    os.close(fd)
    dest = Path(tmp)
    dest.unlink(missing_ok=True)
    original = art.BACKUP_SCHEMA
    if schema is not None:
        art.BACKUP_SCHEMA = schema
    try:
        art.write_backup_v2(dest, passphrase=None)
        return dest.read_bytes()
    finally:
        art.BACKUP_SCHEMA = original
        dest.unlink(missing_ok=True)


def _manifest_of(blob: bytes) -> dict:
    zin = zipfile.ZipFile(io.BytesIO(blob))
    return json.loads(zin.read("manifest.json"))["manifest"]


def _tamper_member(blob: bytes, name: str) -> bytes:
    """Flip one byte of a member WITHOUT touching the manifest -- so the manifest's
    recorded sha256 no longer matches, which is what a corrupted or altered archive
    looks like."""
    zin = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == name:
                data = data + b"\x00tampered"
            zout.writestr(item, data)
    return out.getvalue()


# --------------------------------------------------------------------------- #
#  The bump itself
# --------------------------------------------------------------------------- #
def test_this_build_writes_the_new_format():
    from src.backup.artifact import ACCEPTED_BACKUP_SCHEMAS, BACKUP_SCHEMA

    assert BACKUP_SCHEMA == "oo-backup-3"
    assert BACKUP_SCHEMA in ACCEPTED_BACKUP_SCHEMAS


def test_every_format_this_build_ever_wrote_is_still_accepted():
    """Membership of ``ACCEPTED_BACKUP_SCHEMAS`` is a PROMISE (D7, Q215 ⛔ = a), so the
    guard is on the set, not on the current literal: a future bump that dropped
    ``oo-backup-2`` would strand every backup an operator already holds."""
    from src.backup.artifact import ACCEPTED_BACKUP_SCHEMAS

    assert "oo-backup-2" in ACCEPTED_BACKUP_SCHEMAS
    assert "oo-backup-3" in ACCEPTED_BACKUP_SCHEMAS


def test_only_the_INNER_format_was_bumped_never_the_volume_container():
    """ONE bump, never two. The volume set's slicing, parity and manifest are
    unchanged, so bumping its kind would tell an older build it cannot read a set it
    can read perfectly -- and the honest refusal belongs one layer in, where the
    members really did change."""
    from src.backup.volumes import _KNOWN_KINDS

    assert "oo-volumes-2" in _KNOWN_KINDS
    assert not any(k.startswith("oo-volumes-3") for k in _KNOWN_KINDS), (
        "the volume container was bumped too; the brief asks for ONE bump"
    )


def test_a_new_backup_declares_the_new_schema(client):
    assert _manifest_of(_build_backup())["backup_schema"] == "oo-backup-3"


# --------------------------------------------------------------------------- #
#  The restore matrix
# --------------------------------------------------------------------------- #
def test_an_oo_backup_2_artifact_still_restores(client, tmp_path):
    """THE ONE THAT MATTERS. Every backup made before this PR carries `oo-backup-2`."""
    blob = _build_backup(schema="oo-backup-2")
    assert _manifest_of(blob)["backup_schema"] == "oo-backup-2"
    dest = tmp_path / "old.oobak"
    dest.write_bytes(blob)

    r = client.post("/api/backup/legacy/restore", json={"path": str(dest)})

    assert r.status_code == 200, r.text


def test_an_oo_backup_3_artifact_restores(client, tmp_path):
    dest = tmp_path / "new.oobak"
    dest.write_bytes(_build_backup())

    r = client.post("/api/backup/legacy/restore", json={"path": str(dest)})

    assert r.status_code == 200, r.text


def test_a_schema_no_build_ever_wrote_is_refused_BY_NAME(client, tmp_path):
    """The anti-vacuity twin of the two above: a reader that accepted everything would
    pass both and still be broken. The refusal must NAME the schema, because an
    operator holding an unreadable artifact needs to know which one it is."""
    blob = _build_backup()
    zin = zipfile.ZipFile(io.BytesIO(blob))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "manifest.json":
                env = json.loads(data)
                env["manifest"]["backup_schema"] = "oo-backup-1"
                data = json.dumps(env).encode("utf-8")
            zout.writestr(item, data)
    dest = tmp_path / "ancient.oobak"
    dest.write_bytes(out.getvalue())

    r = client.post("/api/backup/legacy/restore", json={"path": str(dest)})

    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "oo-backup-1" in detail and "schema" in detail.lower()


def test_a_tampered_member_is_refused_BY_NAME(client, tmp_path):
    """A member whose bytes no longer match the manifest's recorded sha256 refuses the
    whole restore, and the refusal names the member -- the format bump must not have
    weakened the per-member hash check that makes a self-signed artifact merely
    consistent rather than trusted."""
    blob = _tamper_member(_build_backup(), "corpus.db")
    dest = tmp_path / "tampered.oobak"
    dest.write_bytes(blob)

    r = client.post("/api/backup/legacy/restore", json={"path": str(dest)})

    assert r.status_code >= 400
    detail = str(r.json().get("detail", ""))
    assert "corpus.db" in detail, f"the refusal does not name the bad member: {detail}"


def test_the_recorded_artifact_kind_is_the_one_the_artifact_CARRIED(tmp_path):
    """``merge_batches.artifact_kind`` is the operator's own record of what they
    restored. Stamping every restore with the CURRENT literal would make an
    `oo-backup-2` restore read as an `oo-backup-3` one and no later reader could tell
    them apart."""
    from src.backup.artifact import _finalize_staged

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "corpus.db").write_bytes(b"")
    (staging / "manifest.json").write_text(
        json.dumps({"manifest": {"backup_schema": "oo-backup-2", "members": []}}),
        encoding="utf-8",
    )

    staged = _finalize_staged(staging, was_encrypted=False)

    assert staged.kind == "oo-backup-2"


def test_the_signature_gate_covers_EVERY_signed_format(tmp_path):
    """THE FAILURE-OPEN CASE. ``prepare_staged_corpus`` demanded a verified signature
    only for the literal ``oo-backup-2``; left as a literal, the bump would have
    silently stopped demanding one on exactly the format this build writes. Driven
    against BOTH literals so neither can regress alone."""
    from src.backup.artifact import StagedArtifact
    from src.backup.merge import MergeError, prepare_staged_corpus

    for schema in ("oo-backup-2", "oo-backup-3"):
        staged = StagedArtifact(
            kind=schema,
            staging_dir=tmp_path,
            corpus_path=tmp_path / "corpus.db",
            custody_path=None,
            manifest={},
            signature_state="unsigned",
            origin_fingerprint="unsigned",
        )
        with pytest.raises(MergeError) as exc:
            prepare_staged_corpus(staged)
        assert "unsigned" in str(exc.value), (
            f"{schema} was merged without a verified signature -- the gate failed OPEN"
        )
