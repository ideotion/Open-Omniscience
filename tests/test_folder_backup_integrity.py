"""A folder backup records what it wrote, signs it, and refuses to restore rot.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP THIS CLOSES, and it was disclosed rather than hidden: ``verify_folder_backup``'s
own docstring said Wikipedia dumps and OSM extracts "carry NO stored checksum ... so they
are SIZE-verified only", with the reason given as "re-hashing tens of GB every run defeats
the point". That reason is about VERIFY, not about WRITE. The copy already streams every
byte, so hashing during it costs nothing, and recording the result turns verification from
impossible into a choice. Until then a 20 GB dump that rotted on an external drive verified
``ok`` on its byte count and RESTORED silently into the live data directory.

Three things are pinned here, and the third is the data-safety one:

  1. the write path records a sha256 per member and SIGNS the manifest (the file lives on
     an editable drive, so recorded checksums are worth what the evidence that they are
     ours is worth);
  2. verify checks them, and still reports honestly for a backup that has none;
  3. RESTORE verifies while copying and discards a member whose bytes do not match --
     before it reaches the live data directory, never after.

The negative space is asserted throughout: an older backup must still restore, an
unsigned manifest must not be called a failure, a healthy file must not be refused, and a
recorded checksum must never be invented for a file nobody hashed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    function_body,
    python_function_source,
    read_static,
    strip_comments,
)

from src.backup.folder_backup import (
    MANIFEST_NAME,
    BackupItem,
    restore_folder_backup,
    verify_folder_backup,
    write_folder_backup,
)


def _item(tmp: Path, rel: str, body: bytes, category: str = "wiki_dumps") -> BackupItem:
    src = tmp / "live" / category / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(body)
    return BackupItem(category=category, rel=rel, src=src, size=len(body))


def _manifest(dest: Path) -> dict:
    return json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))


def _entry(dest: Path, category: str, rel: str) -> dict:
    return next(
        e for e in _manifest(dest)["categories"][category] if e["rel"] == rel
    )


# --------------------------------------------------------------------------- #
#  1. the write path records and signs
# --------------------------------------------------------------------------- #
def test_every_copied_file_carries_the_sha256_of_the_bytes_written(tmp_path):
    import hashlib

    body = b"enwiki-pages-articles" * 500
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "enwiki.xml.bz2", body)])

    got = _entry(dest, "wiki_dumps", "enwiki.xml.bz2")
    assert got["sha256"] == hashlib.sha256(body).hexdigest()


def test_the_manifest_is_signed(tmp_path):
    from src.backup.folder_backup import folder_manifest_signature_state

    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])

    assert folder_manifest_signature_state(_manifest(dest)) == "verified"


def test_an_edited_manifest_no_longer_verifies(tmp_path):
    """The point of signing it: the manifest lives on a drive anyone can edit, so a
    recorded checksum is only worth the evidence that it is the one we wrote.

    The edit is deliberately one that changes NO file check -- every file is still
    present, the right size and the right bytes. A first draft rewrote a ``sha256``
    instead, which trips a checksum_mismatch as well, so ``ok is False`` held whether or
    not the signature was consulted: the mutation that stops a bad signature failing the
    verdict survived the whole matrix against it. This fixture leaves the signature as
    the only thing wrong, so it cannot."""
    from src.backup.folder_backup import folder_manifest_signature_state

    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])

    m = _manifest(dest)
    m["created_at"] = "1999-01-01T00:00:00+00:00"
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    assert folder_manifest_signature_state(_manifest(dest)) == "bad-signature"
    out = verify_folder_backup(dest)
    assert out["signature_state"] == "bad-signature"
    assert out["summary"]["checksum_mismatch"] == 0, (
        "the fixture must leave the signature as the ONLY defect, or this passes for a "
        "reason that has nothing to do with signing"
    )
    assert out["ok"] is False


def test_a_refresh_carries_the_checksum_of_a_file_it_skipped(tmp_path):
    """It must not re-read a hundred gigabytes to keep an integrity value it already
    has -- nor lose it. Proven by making the SOURCE unreadable: a second pass that
    needed the bytes could not produce this digest at all."""
    body = b"immutable dump" * 100
    dest = tmp_path / "drive"
    item = _item(tmp_path, "d.bin", body)
    write_folder_backup(dest, [item])
    first = _entry(dest, "wiki_dumps", "d.bin")["sha256"]

    item.src.unlink()  # a skip must not touch the source at all
    out = write_folder_backup(dest, [item])

    assert out["skipped"] == 1 and out["copied"] == 0
    assert _entry(dest, "wiki_dumps", "d.bin")["sha256"] == first


def test_a_changed_size_does_not_inherit_the_old_checksum(tmp_path):
    """NEGATIVE SPACE for the carry-forward: the reuse key includes the size, so a file
    that is not the one that was hashed cannot keep its digest."""
    import hashlib

    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "d.bin", b"old")])
    grown = b"a much longer body than before"
    write_folder_backup(dest, [_item(tmp_path, "d.bin", grown)])

    assert _entry(dest, "wiki_dumps", "d.bin")["sha256"] == hashlib.sha256(grown).hexdigest()


def test_a_checksum_is_omitted_rather_than_invented(tmp_path):
    """NEGATIVE SPACE. A file this pass skipped, whose earlier manifest carried no
    checksum, has no digest to record -- and "not hashed" must not render as a value."""
    dest = tmp_path / "drive"
    item = _item(tmp_path, "legacy.bin", b"pre-checksum backup" * 10)
    write_folder_backup(dest, [item])

    m = _manifest(dest)  # strip the checksums, as a pre-2026-09-07 backup has none
    for lst in m["categories"].values():
        for e in lst:
            e.pop("sha256", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    write_folder_backup(dest, [item])  # a pure skip: nothing is read, nothing is hashed

    got = _entry(dest, "wiki_dumps", "legacy.bin")
    assert "sha256" not in got
    assert _manifest(dest)["files_without_checksum"] == 1


# --------------------------------------------------------------------------- #
#  2. verify uses them
# --------------------------------------------------------------------------- #
def test_verify_content_checks_a_dump_and_catches_rot(tmp_path):
    """THE CASE THAT USED TO PASS: same size, different bytes."""
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "enwiki.bin", b"A" * 4096)])
    assert verify_folder_backup(dest)["ok"] is True

    (dest / "wiki_dumps" / "enwiki.bin").write_bytes(b"B" * 4096)  # identical length

    out = verify_folder_backup(dest)
    assert out["ok"] is False
    assert out["summary"]["checksum_mismatch"] == 1
    assert out["summary"]["size_only"] == 0, "a dump is no longer size-only"


def test_verify_reports_an_older_backup_as_unsigned_without_failing_it(tmp_path):
    """NEGATIVE SPACE. A backup written before signing existed is a real backup;
    refusing it would strand data. It is reported, never silently upgraded."""
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])

    m = _manifest(dest)
    m.pop("signature", None)
    for lst in m["categories"].values():
        for e in lst:
            e.pop("sha256", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    out = verify_folder_backup(dest)
    assert out["signature_state"] == "unsigned"
    assert out["ok"] is True, "an unsigned older backup is not a failed one"
    assert out["summary"]["size_only"] == 1, "and it is honest that nothing was hashed"


def test_a_malformed_recorded_checksum_is_unverifiable_not_a_match(tmp_path):
    """NEGATIVE SPACE. Manifest values are untrusted: a truncated or non-hex digest must
    fall back to size_only, never be compared against and never read as a pass."""
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])
    m = _manifest(dest)
    m["categories"]["wiki_dumps"][0]["sha256"] = "not-a-digest"
    m.pop("signature", None)  # the edit invalidates it; this test is about the digest
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    out = verify_folder_backup(dest)
    assert out["summary"]["checksum_mismatch"] == 0
    assert out["summary"]["size_only"] == 1


# --------------------------------------------------------------------------- #
#  3. restore refuses rot -- the data-safety half
# --------------------------------------------------------------------------- #
def test_restore_refuses_a_member_whose_bytes_rotted_on_the_drive(tmp_path):
    dest, live = tmp_path / "drive", tmp_path / "restored"
    write_folder_backup(dest, [_item(tmp_path, "enwiki.bin", b"A" * 4096)])
    (dest / "wiki_dumps" / "enwiki.bin").write_bytes(b"B" * 4096)  # same size

    out = restore_folder_backup(dest, categories=["wiki_dumps"],
                                targets={"wiki_dumps": live})

    assert out["corrupt_refused"] == 1
    assert out["corrupt"][0]["rel"] == "enwiki.bin"
    assert out["restored"] == 0
    assert not (live / "enwiki.bin").exists(), (
        "a corrupt member must never reach the live data directory -- not even briefly "
        "enough for the app to read it as its own"
    )


def test_restore_still_copies_a_healthy_member(tmp_path):
    """NEGATIVE SPACE, and it is the one that matters most: a check that refuses
    everything would look identical in the test above and destroy the feature."""
    dest, live = tmp_path / "drive", tmp_path / "restored"
    body = b"a perfectly good dump" * 200
    write_folder_backup(dest, [_item(tmp_path, "ok.bin", body)])

    out = restore_folder_backup(dest, categories=["wiki_dumps"],
                                targets={"wiki_dumps": live})

    assert out["corrupt_refused"] == 0 and out["restored"] == 1
    assert (live / "ok.bin").read_bytes() == body
    assert out["restored_unverified"] == 0


def test_an_older_backup_with_no_checksums_still_restores_and_says_so(tmp_path):
    """NEGATIVE SPACE. No recorded checksum is not a reason to refuse a real backup --
    but the files were NOT content-verified and must not be counted as if they were."""
    dest, live = tmp_path / "drive", tmp_path / "restored"
    write_folder_backup(dest, [_item(tmp_path, "legacy.bin", b"y" * 128)])
    m = _manifest(dest)
    for lst in m["categories"].values():
        for e in lst:
            e.pop("sha256", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    out = restore_folder_backup(dest, categories=["wiki_dumps"],
                                targets={"wiki_dumps": live})

    assert out["restored"] == 1 and out["corrupt_refused"] == 0
    assert out["restored_unverified"] == 1, "a gap is published as a gap"
    assert (live / "legacy.bin").exists()


@pytest.mark.parametrize("rel", ["../escape.bin", "/etc/passwd", "a/../../escape.bin"])
def test_a_hostile_manifest_never_becomes_a_path(tmp_path, rel):
    """The recorded 2026-07-10 rule: every manifest field that becomes a filesystem path
    is guarded on BOTH the verify and the restore paths, because a manifest is
    self-signed and anyone can produce one.

    Restore is guarded by construction -- it walks the tree and never reads a name from
    the manifest -- so the hostile name can only be planted for verify, which must refuse
    it rather than stat or hash whatever it resolves to."""
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])
    m = _manifest(dest)
    m["categories"]["wiki_dumps"].append({"category": "wiki_dumps", "rel": rel, "size": 1})
    m.pop("signature", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    out = verify_folder_backup(dest)
    assert out["summary"]["traversal_refused"] == 1
    assert out["ok"] is False


def test_a_sibling_directory_that_merely_shares_the_prefix_is_refused(tmp_path):
    """The prefix-vs-containment trap, which the ledger records biting once already
    (``_owned_by_app``): ``<root>/wiki_dumps_evil`` STARTS WITH ``<root>/wiki_dumps`` and
    is a different directory. ``_safe_member_path`` compares path COMPONENTS, so it
    refuses -- but nothing proved that: the three escapes above all land outside the base
    without sharing its prefix, so a mutation swapping the containment check for
    ``startswith`` survived the whole matrix. This is the case that separates them.
    """
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])
    evil = dest / "wiki_dumps_evil"
    evil.mkdir()
    (evil / "planted.bin").write_bytes(b"z")

    m = _manifest(dest)
    m["categories"]["wiki_dumps"].append(
        {"category": "wiki_dumps", "rel": "../wiki_dumps_evil/planted.bin", "size": 1}
    )
    m.pop("signature", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    out = verify_folder_backup(dest)
    assert out["summary"]["traversal_refused"] == 1, (
        "a sibling directory sharing the category's name prefix is still outside it"
    )
    assert out["ok"] is False


def test_a_hostile_category_never_becomes_a_path(tmp_path):
    """``category`` is the OTHER half of ``<root>/<category>/<rel>`` -- the field the
    2026-07-10 lesson says gets missed because it is not the one called "name"."""
    dest = tmp_path / "drive"
    write_folder_backup(dest, [_item(tmp_path, "a.bin", b"x" * 64)])
    m = _manifest(dest)
    m["categories"]["../../etc"] = [{"category": "../../etc", "rel": "passwd", "size": 1}]
    m.pop("signature", None)
    (dest / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")

    out = verify_folder_backup(dest)
    assert out["summary"]["traversal_refused"] == 1
    assert out["ok"] is False


# --------------------------------------------------------------------------- #
# The refusal has to REACH the operator, or the discard is honest only in the
# engine. A member the restore turned away is a file that is now missing from
# the live data directory; a run that dropped three and printed "Done." reads as
# a complete restore, and the absence surfaces later as a mystery.
# --------------------------------------------------------------------------- #
def test_the_folder_restore_refusal_node_suite() -> None:
    """What the caveat SAYS, driven as real code (extracted from the shipped module).

    Required by ``test_every_node_suite_has_a_driver``: an unrun node suite looks
    exactly like a passing one.
    """
    proc = subprocess.run(
        [
            "node",
            str(Path(__file__).resolve().parents[1] / "tests" / "folder_restore_refusal_node_test.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_both_folder_restore_consumers_render_the_refusal() -> None:
    """The wiring the node suite cannot see: that the helper is actually CALLED.

    Two surfaces read a folder restore's result -- the live panel's own progress line
    and the unified-import summary rendered afterwards -- and a refusal that reaches
    neither is a discard the operator never learns about. Asserted as calls in the
    parsed source of each consumer, not as the identifier appearing somewhere in the
    file, so deleting the render cannot pass because the name survives in a comment.
    """
    src = strip_comments(read_static("app-backup.js"))

    live = function_body(src, "_fbRefresh")
    assert "_fbRefusalLines(p)" in live, (
        "the live folder panel prints Done. without asking what was refused"
    )
    assert "card-caveat" in live, (
        "a refusal is not a muted footnote -- invariant #23 puts caveats in the visible line"
    )

    last = function_body(src, "_uxShowLastCompletedSummary")
    assert "caveat: _fbRefusalLines(p)" in last, (
        "the post-hoc import summary is the artifact an operator reads afterwards; a "
        "restore that discarded rotted members is not a clean one"
    )
    summary = function_body(src, "_renderImportSummary")
    assert "s2.caveat" in summary and "refusalLine" in summary, (
        "the summary collects `caveat` from its inputs but never renders it -- a "
        "payload with no reader is the dead-end shape"
    )
    assert "+ refusalLine +" in summary, "the caveat is built and then not concatenated in"


def test_the_restore_journal_records_what_it_turned_away() -> None:
    """The journal is what survives the app being killed, so it carries the refusals too.

    It also stops recording ``copied``: ``restore_folder_backup`` has never returned that
    field, so every restore journal carried ``copied: null`` -- a field that reads as
    "nothing was copied" where the truth is that a restore has no such number.
    """
    src = python_function_source(
        (Path(__file__).resolve().parents[1] / "src" / "backup" / "folder_backup.py").read_text(
            encoding="utf-8"
        ),
        "_run_restore",
    )
    assert "corrupt_refused=res.get(\"corrupt_refused\")" in src
    assert "restored_unverified=res.get(\"restored_unverified\")" in src
    assert "restored=res.get(\"restored\")" in src
    assert "copied=res.get(\"copied\")" not in src, (
        "a restore does not copy; that field was always null here"
    )
