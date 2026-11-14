"""R686: a volume restore never writes decrypted data into the backup's own folder, a manifest that lists a
volume twice is refused, and what a restore writes is bounded by the plaintext size the manifest declares.

Each test fails on the code before R686: the legacy reassembly decrypted every volume to ``<volume>.plain``
beside it (a crash left plaintext on the user's backup drive), read a repeated volume again, and wrote
whatever the volumes held; the member-streamed reader did the last two as well."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.backup import folder_backup
from src.backup.import_scan import leftover_plaintext, scan_import_folder
from src.backup.volumes import (
    MANIFEST_NAME,
    VolumeError,
    read_volume_set,
    remove_leftover_plaintext,
    write_volume_set,
)

ROOT = Path(__file__).resolve().parents[1]
PW = "pw-r686"
SECRET = b"THE-PLAINTEXT-MARKER-" * 4000  # about 84 KB, several volumes at 16 KiB


def _legacy_set(tmp: Path) -> Path:
    src = tmp / "archive.bin"
    src.write_bytes(SECRET)
    out = tmp / "backup-drive"
    write_volume_set(src, out, PW, volume_size=16 * 1024)
    src.unlink()
    return out


def _rewrite(out: Path, edit) -> None:
    m = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    edit(m)
    (out / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


def _plaintext_files(folder: Path) -> list[str]:
    return sorted(
        p.name
        for p in folder.rglob("*")
        if p.is_file() and b"THE-PLAINTEXT-MARKER" in p.read_bytes()
    )


def test_a_restore_killed_midway_leaves_no_plaintext_beside_the_backup(tmp_path):
    from src.backup.stream_backup import sweep_stale_backup_temps

    out = _legacy_set(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    # A hard crash: the process dies right after the first volume is decrypted, so no finally runs.
    script = f"""
import os, sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
import src.backup.volumes as v
from src.backup.artifact import read_volume_backup
real = v.decrypt_file
def dying(src, dst, pw):
    real(src, dst, pw)
    os._exit(7)
v.decrypt_file = dying
read_volume_backup(Path({str(out)!r}), {PW!r}, Path({str(data)!r}))
"""
    res = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "OO_DATA_DIR": str(tmp_path / "data")},
    )
    assert res.returncode == 7, res.stderr
    assert _plaintext_files(out) == [], "nothing decrypted is left on the backup drive"
    assert not list(out.glob("*.plain"))
    left = list(data.glob(".restore-*"))
    assert len(left) == 1 and _plaintext_files(left[0]), (
        "the working copy was in the restore's own staging"
    )
    # The next start: the staging's owner is dead, so the janitor removes it at once, whatever its age.
    assert sweep_stale_backup_temps(data) == 1
    assert _plaintext_files(data) == [] and not list(data.glob(".restore-*"))


def test_a_completed_restore_leaves_no_working_copy_anywhere(tmp_path):
    out = _legacy_set(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    read_volume_set(out, PW, staging / "_reassembled.zip")
    assert (staging / "_reassembled.zip").read_bytes() == SECRET
    assert sorted(p.name for p in staging.iterdir()) == ["_reassembled.zip"]
    assert _plaintext_files(out) == []


def test_a_manifest_that_lists_a_volume_twice_is_refused(tmp_path):
    out = _legacy_set(tmp_path)
    _rewrite(out, lambda m: m["volumes"].append(dict(m["volumes"][0])))
    (tmp_path / "st").mkdir()
    with pytest.raises(VolumeError, match="more than once"):
        read_volume_set(out, PW, tmp_path / "st" / "_reassembled.zip")
    assert list((tmp_path / "st").iterdir()) == []


def test_what_is_written_is_bounded_by_the_declared_plaintext_size(tmp_path):
    out = _legacy_set(tmp_path)
    _rewrite(out, lambda m: m.__setitem__("plaintext_bytes", 1000))
    (tmp_path / "st").mkdir()
    with pytest.raises(VolumeError, match="more data than its manifest declares"):
        read_volume_set(out, PW, tmp_path / "st" / "_reassembled.zip")
    assert list((tmp_path / "st").iterdir()) == [], (
        "the partial archive and the working copy are gone"
    )


def test_the_reassembly_preflights_what_it_will_really_write(tmp_path, monkeypatch):
    out = _legacy_set(tmp_path)
    (tmp_path / "st").mkdir()
    monkeypatch.setattr(folder_backup, "free_bytes", lambda _p: 10 * 1024)
    from src.backup.artifact import BackupSpaceError

    with pytest.raises(BackupSpaceError):
        read_volume_set(out, PW, tmp_path / "st" / "_reassembled.zip")
    assert list((tmp_path / "st").iterdir()) == []


# ------------------------------------------------------------------ the member-streamed set (oo-volumes-2)
def _stream_set(tmp: Path) -> Path:
    from tests.test_stream_backup import _backup, _make_corpus

    corpus = tmp / "corpus.db"
    _make_corpus(corpus, rows=60)
    dest = tmp / "stream-drive"
    _backup(tmp, dest, corpus)
    return dest


def test_a_streamed_set_that_lists_a_volume_twice_is_refused(tmp_path):
    dest = _stream_set(tmp_path)

    def dup(m):
        corpus = next(mm for mm in m["members"] if mm["name"] == "corpus.db")
        corpus["volumes"].append(corpus["volumes"][0])

    _rewrite(dest, dup)
    from src.backup.stream_backup import read_stream_backup

    with pytest.raises(VolumeError, match="more than once"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")


def test_a_streamed_member_is_bounded_by_its_declared_plaintext_size(tmp_path):
    dest = _stream_set(tmp_path)

    def shrink(m):
        m.pop(
            "signature", None
        )  # anyone can strip or re-sign: the bound must hold for an unsigned set too
        corpus = next(mm for mm in m["members"] if mm["name"] == "corpus.db")
        corpus["plaintext_bytes"] = 100

    _rewrite(dest, shrink)
    from src.backup.stream_backup import read_stream_backup

    with pytest.raises(VolumeError, match="more data than the backup's manifest declares"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert not list((tmp_path / "st").glob(".restore-*")), "the staging dir is removed"


# ------------------------------------------------------------------ copies an earlier interrupted restore left
def _with_leftovers(tmp: Path) -> Path:
    out = _legacy_set(tmp)
    m = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    first = m["volumes"][0]["name"]
    (out / (first + ".plain")).write_bytes(SECRET[:100])
    (out / "my-notes.plain").write_text("the user's own file", encoding="utf-8")
    return out


def test_the_scan_names_only_the_copies_the_manifest_explains(tmp_path):
    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    assert leftover_plaintext(out) == [first + ".plain"]
    found = scan_import_folder(tmp_path)["found"]["corpus"]
    assert found[0]["leftover_plaintext"] == [first + ".plain"]
    assert (out / (first + ".plain")).exists(), "a scan deletes nothing"


def test_removal_takes_only_named_leftovers_and_never_anything_else(tmp_path):
    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    removed = remove_leftover_plaintext(
        out, [first + ".plain", "my-notes.plain", "../archive.bin", first]
    )
    assert removed == {"removed": [first + ".plain"], "failed": []}
    assert (out / "my-notes.plain").exists() and (out / first).exists()
    assert leftover_plaintext(out) == []


def test_the_removal_endpoint_and_the_page_offer_it_only_on_the_operators_yes(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    with TestClient(app) as c:
        # without the operator's yes the server removes nothing, whoever calls it (R692)
        refused = c.post(
            "/api/backup/import-scan/remove-leftover-plaintext",
            json={"path": str(out), "names": [first + ".plain"]},
        )
        assert refused.status_code == 400 and (out / (first + ".plain")).exists()
        r = c.post(
            "/api/backup/import-scan/remove-leftover-plaintext",
            json={"path": str(out), "names": [first + ".plain", "my-notes.plain"], "confirm": True},
        )
    assert r.status_code == 200 and r.json() == {"removed": [first + ".plain"], "failed": []}
    from tests.js_source_helper import function_body

    body = function_body((ROOT / "src/static/app-backup.js").read_text("utf-8"), "_uxImLeftoverPlaintext")
    assert "confirm(" in body and body.index("confirm(") < body.index(
        "remove-leftover-plaintext"
    ), "the yes comes first"


# ------------------------------------------------------------------ the second round of reads
def _corpus_member(m):
    return next(mm for mm in m["members"] if mm["name"] == "corpus.db")


def test_a_negative_declared_size_cannot_cancel_another_out_of_the_preflight(tmp_path):
    dest = _stream_set(tmp_path)

    def cancel(m):
        m.pop("signature", None)
        other = next(mm for mm in m["members"] if mm["name"] != "corpus.db")
        _corpus_member(m)["plaintext_bytes"] += 10**15
        other["plaintext_bytes"] = -(10**15)

    _rewrite(dest, cancel)
    from src.backup.stream_backup import read_stream_backup

    with pytest.raises(VolumeError, match="not a whole number of bytes"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")


def test_a_volume_reached_under_a_second_name_is_refused(tmp_path):
    dest = _stream_set(tmp_path)
    m = json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
    vname = _corpus_member(m)["volumes"][0]
    os.link(dest / vname, dest / ("alias-" + vname))

    def alias(m):
        m.pop("signature", None)
        v = next(x for x in m["volumes"] if x["name"] == vname)
        m["volumes"].append({**v, "name": "alias-" + vname})
        _corpus_member(m)["volumes"].append("alias-" + vname)

    _rewrite(dest, alias)
    from src.backup.stream_backup import read_stream_backup

    with pytest.raises(VolumeError, match="same file"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    (dest / ("alias-" + vname)).unlink()
    (dest / ("alias-" + vname)).symlink_to(dest / vname)
    with pytest.raises(VolumeError, match="a link to another file"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")


def test_names_that_differ_only_by_case_or_a_trailing_dot_are_one_volume():
    from src.backup.volumes import require_unique_volumes

    for twin in ("VOL-00001.OOENC", "vol-00001.ooenc.", "vol-00001.ooenc "):
        with pytest.raises(VolumeError, match="more than once"):
            require_unique_volumes(["vol-00001.ooenc", twin])


def test_verify_refuses_a_repeated_volume_too(tmp_path):
    dest = _stream_set(tmp_path)
    _rewrite(dest, lambda m: _corpus_member(m)["volumes"].append(_corpus_member(m)["volumes"][0]))
    from src.backup.stream_backup import verify_stream_backup

    with pytest.raises(VolumeError, match="more than once"):
        verify_stream_backup(dest)


def test_the_legacy_reader_refuses_a_repeat_before_it_repairs_anything(tmp_path):
    out = _legacy_set(tmp_path)
    _rewrite(out, lambda m: m["volumes"].append(dict(m["volumes"][0])))
    second = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][1]["name"]
    (out / second).write_bytes(b"damaged")  # a bad volume: the old order repaired before it checked
    called = []
    (tmp_path / "st").mkdir()
    with pytest.raises(VolumeError, match="more than once"):
        read_volume_set(
            out,
            PW,
            tmp_path / "st" / "_reassembled.zip",
            recover=lambda m, bad: called.append(bad) or [],
        )
    assert called == []


@pytest.mark.parametrize(
    "edit",
    [
        lambda m: m.__setitem__(
            "kind", "something-else"
        ),  # only oo-volumes-1 ever wrote a .plain copy
        lambda m: m["volumes"].append({"name": "my-notes"}),  # a name the writer never gives
        lambda m: m["volumes"].append({"name": "C:my-notes"}),  # a Windows drive-relative name
        lambda m: m["volumes"].append(
            {"name": m["volumes"][0]["name"] + ".plain"}
        ),  # a listed volume
    ],
)
def test_a_crafted_manifest_cannot_get_another_file_offered_for_removal(tmp_path, edit):
    out = _legacy_set(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    (out / "my-notes.plain").write_text("the user's own file", encoding="utf-8")
    (out / (first + ".plain")).write_bytes(b"x")
    _rewrite(out, edit)
    names = leftover_plaintext(out)
    assert "my-notes.plain" not in names and "C:my-notes.plain" not in names
    m = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    listed = {v["name"] for v in m["volumes"]}
    assert not (set(names) & listed), "a listed volume is never offered as a leftover"
    remove_leftover_plaintext(out, ["my-notes.plain", "C:my-notes.plain", first + ".plain"])
    assert (out / "my-notes.plain").exists()
    if first + ".plain" in listed:
        assert (out / (first + ".plain")).exists()


def test_only_an_oo_volumes_1_manifest_explains_a_leftover(tmp_path):
    out = _with_leftovers(tmp_path)
    assert leftover_plaintext(out)
    _rewrite(out, lambda m: m.__setitem__("kind", "oo-volumes-2"))
    assert leftover_plaintext(out) == []


def test_a_copy_that_cannot_be_removed_is_named_and_the_rest_still_go(tmp_path, monkeypatch):
    out = _legacy_set(tmp_path)
    names = [
        v["name"]
        for v in json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][:2]
    ]
    for n in names:
        (out / (n + ".plain")).write_bytes(b"x")
    real = os.unlink

    def stuck(path, *a, **kw):
        if str(path).endswith(names[0] + ".plain"):
            raise PermissionError("in use")
        return real(path, *a, **kw)

    from src.backup import volumes as volumes_module
    from tests.os_scope import scope_os

    scope_os(monkeypatch, volumes_module, unlink=stuck, supports_dir_fd=os.supports_dir_fd | {stuck})
    res = remove_leftover_plaintext(out, [n + ".plain" for n in names])
    assert res == {"removed": [names[1] + ".plain"], "failed": [names[0] + ".plain"]}


def test_the_scan_keeps_the_writers_volume_names_in_sync():
    import re

    from src.backup import import_scan, volumes

    src = Path(volumes.__file__).read_text("utf-8")
    assert 'f"vol-{idx:05d}.ooenc"' in src
    assert import_scan._V1_VOLUME_NAME.match("vol-00001.ooenc")
    assert import_scan._V1_KIND == volumes.VOLUME_KIND
    assert re.compile(import_scan._V1_VOLUME_NAME.pattern).match("vol-12345.ooenc")


def test_a_backup_folder_reached_through_a_link_can_still_be_cleaned(tmp_path):
    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    link = tmp_path / "shortcut"
    link.symlink_to(out, target_is_directory=True)
    assert remove_leftover_plaintext(link, [first + ".plain"]) == {
        "removed": [first + ".plain"],
        "failed": [],
    }
    assert (out / "my-notes.plain").exists()


def test_a_link_a_path_outside_and_an_unlisted_name_are_each_refused(tmp_path):
    """R692 (2): the removal takes only a vol-NNNNN.ooenc.plain copy the folder's own manifest explains, never a link
    under that name, never a path that leaves the folder and never a name the manifest does not explain."""
    import os

    out = _legacy_set(tmp_path)
    names = [v["name"] for v in json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"]]
    assert len(names) >= 2
    outside = tmp_path / "outside.txt"
    outside.write_text("not the backup's", encoding="utf-8")
    try:
        os.symlink(outside, out / (names[0] + ".plain"))
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot make a link here")
    (out / (names[1] + ".plain")).write_bytes(b"a real leftover")
    (out / "vol-99999.ooenc.plain").write_bytes(b"unlisted")
    assert leftover_plaintext(out) == [names[1] + ".plain"], "the link and the unlisted name are not offered"
    r = remove_leftover_plaintext(
        out, [names[0] + ".plain", str(outside), "../outside.txt", "vol-99999.ooenc.plain", names[1] + ".plain"]
    )
    assert r == {"removed": [names[1] + ".plain"], "failed": []}
    assert outside.read_text(encoding="utf-8") == "not the backup's"
    assert (out / (names[0] + ".plain")).is_symlink() and (out / "vol-99999.ooenc.plain").exists()


def test_the_remove_button_answers_only_the_persons_own_click():
    from tests.js_source_helper import function_body

    body = function_body((ROOT / "src/static/app-backup.js").read_text("utf-8"), "_uxImLeftoverPlaintext")
    i = body.index("isTrusted !== true")
    assert i < body.index("confirm(") < body.index("remove-leftover-plaintext")


def test_a_listed_name_in_another_case_and_a_trailing_newline_are_never_offered(tmp_path):
    """R692 follow-up: a copy whose name a case-insensitive drive would take for a listed volume, and a manifest name with
    a trailing newline (which ``$`` let through), are never offered for removal."""
    out = _legacy_set(tmp_path)
    m = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    first = m["volumes"][0]["name"]
    (out / (first + ".plain")).write_bytes(b"x")
    m["volumes"].append({"name": (first + ".plain").upper()})
    m["volumes"].append({"name": "vol-77777.ooenc\n"})
    (out / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    import contextlib

    with contextlib.suppress(OSError):  # a platform that refuses the name has nothing to offer either
        (out / "vol-77777.ooenc\n.plain").write_bytes(b"y")
    assert leftover_plaintext(out) == []
    assert remove_leftover_plaintext(out, [first + ".plain", "vol-77777.ooenc\n.plain"]) == {"removed": [], "failed": []}
    assert (out / (first + ".plain")).exists()


def test_what_the_removal_checks_is_the_folder_it_removes_from(tmp_path, monkeypatch):
    """R692 follow-up: the scan and the removal go through ONE folder handle, so a folder swapped between the check and
    the removal cannot turn the removal onto another folder's files."""
    from src.backup import import_scan

    if not getattr(import_scan, "can_scan_by_handle", lambda: True)():
        pytest.skip("no folder handles on this platform")
    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    other = tmp_path / "other"
    other.mkdir()
    for p in out.iterdir():  # a second folder holding the very same names
        (other / p.name).write_bytes(p.read_bytes())
    moved = tmp_path / "moved"

    def swap_after(real):
        def run(*a, **k):
            res = real(*a, **k)
            if not moved.exists():
                out.rename(moved)
                other.rename(out)
            return res

        return run

    for name in ("leftovers_in_handle", "leftover_plaintext"):  # whichever does the check, the swap follows it
        if hasattr(import_scan, name):
            monkeypatch.setattr(import_scan, name, swap_after(getattr(import_scan, name)))
    assert remove_leftover_plaintext(out, [first + ".plain"]) == {"removed": [first + ".plain"], "failed": []}
    assert not (moved / (first + ".plain")).exists(), "the copy goes from the folder that was checked"
    assert (out / (first + ".plain")).exists(), "the folder swapped in afterwards is untouched"
