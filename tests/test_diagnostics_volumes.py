"""The diagnostics archive, split into volumes that fit the channel it travels through.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field session 2026-09-11: the all-diagnostics bundle would not upload, and neither
would ``keyword-log-digest.json`` pulled out and re-zipped on its own. The evidence for
a diagnosis could not reach the person making it. A cap on that one member was half the
answer; this is the other half, and what it has to guarantee is narrow and checkable:

  * NO VOLUME EXCEEDS THE CAP. That is the whole point, so it is asserted against the
    bytes on disk at several caps, including caps small enough to force the split path,
    rather than against the planner's arithmetic about itself.
  * EVERY VOLUME OPENS ALONE and says what the whole set is -- the failure mode of the
    encrypted backup codec (which this deliberately does not reuse) is that volume 3 of
    5 opens to nothing.
  * THE BYTES COME BACK EXACTLY. A diagnostics member that is quietly short is worse
    than one that is absent, because it will be read and believed.
  * AN INCOMPLETE SET REFUSES rather than producing a truncated member.
"""

from __future__ import annotations

import errno
import json
import os
import zipfile
from pathlib import Path

import pytest

from src.api import diagnostics_volumes as dv


def _build_bundle(tmp_path: Path) -> Path:
    """An archive shaped like a real all-diagnostics bundle: orientation files, a dozen
    compressible JSON logs, one member far larger than a small cap, and one payload that
    does not compress at all (so the packer cannot rely on a uniform ratio)."""
    src = tmp_path / "oo-all-diagnostics-20260911-1200.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("manifest.json", json.dumps({"members": ["log-0.json"], "ok": True}))
        z.writestr("bundle-journal.jsonl", '{"event":"begin","file":"log-0.json"}\n' * 40)
        for i in range(6):
            z.writestr(
                f"log-{i}.json",
                json.dumps([{"k": "v" * 40, "n": n} for n in range(4000)]),
            )
        z.writestr("keyword-log-digest.json", json.dumps([{"kw": f"w{n}"} for n in range(60000)]))
        z.writestr("random.bin", os.urandom(400_000))
        z.writestr("empty.txt", "")
    return src


def _members_from_volumes(vol_dir: Path, manifest: dict) -> dict[str, bytes]:
    """Every WHOLE member read straight out of the volumes, as an analyst would."""
    out: dict[str, bytes] = {}
    for v in manifest["volumes"]:
        with zipfile.ZipFile(vol_dir / v["name"]) as z:
            for n in z.namelist():
                if n == dv.README_NAME or ".part" in n:
                    continue
                out[n] = z.read(n)
    # a member cut on record boundaries is read as its pieces; the pieces are not whole members
    for m in manifest["members"]:
        if m.get("cut"):
            out.pop(m["entry"], None)
    return out


# --------------------------------------------------------------------------- #
# The packer, checked without touching a disk.
# --------------------------------------------------------------------------- #


def test_the_planner_keeps_the_callers_order_and_never_overfills_a_volume():
    """Orientation files must stay first (a reader who gets only volume 1 still learns
    what the run did), and first-fit must not pack past the budget."""
    cap = 10_000
    budget = cap - dv._overhead_reserve(cap)
    entries = [("manifest.json", 100, 100), ("a", budget // 2, 999), ("b", budget, 999)]
    plan = dv.plan_volumes(entries, cap=cap)  # (name, deflated_cost, raw_bytes)

    assert plan[0][0][0] == "manifest.json"
    for vol in plan:
        assert sum(1 for e in vol if e[3]) == 0, "nothing should be split here"
    # 'b' costs a whole budget on its own, so it cannot share with manifest.json + 'a'.
    assert len(plan) == 2


def test_a_zero_byte_member_is_carried_rather_than_dropped():
    """An empty log is a FACT about the run -- that the member produced nothing. A
    packer that skipped it would silently delete evidence."""
    plan = dv.plan_volumes([("empty.txt", 0, 0)], cap=10_000)
    assert [e[0] for vol in plan for e in vol] == ["empty.txt"]


def test_a_member_larger_than_a_whole_volume_is_split_into_consecutive_solo_volumes():
    """The case bin-packing has no answer for. Each part gets a volume to itself so
    part N is always in volume (first + N - 1) -- which is what makes the manifest's
    'concatenate the parts in order' instruction followable."""
    cap = 10_000
    budget = cap - dv._overhead_reserve(cap)
    plan = dv.plan_volumes([("big.json", budget * 4, budget * 3 + 5)], cap=cap)

    assert len(plan) == 4, "ceil(3*budget+5 / budget) parts"
    for i, vol in enumerate(plan, start=1):
        assert len(vol) == 1, "a split part shares its volume with nothing"
        entry, off, length, part_of, stored = vol[0]
        assert entry == f"big.json.part{i:04d}of0004"
        assert part_of == 4
        assert stored is True, "split parts are STORED so the byte arithmetic is exact"
        assert off == (i - 1) * budget
        assert length <= budget
    assert sum(e[0][2] for e in plan) == budget * 3 + 5, "every byte is accounted for"


def test_the_overhead_reserve_scales_so_a_small_cap_stays_usable():
    """A FLAT reserve was the first draft's real bug: 64 KiB held back from a 52 KB cap
    collapses the budget to 1 byte and shatters every member into thousands of parts."""
    assert dv._overhead_reserve(9 * 1024 * 1024) == 64 * 1024
    for cap in (4096, 52_428, 200_000, 9 * 1024 * 1024):
        assert 0 < dv._overhead_reserve(cap) < cap


def test_a_non_positive_cap_is_refused_rather_than_silently_floored():
    with pytest.raises(ValueError):
        dv.plan_volumes([("a", 1, 1)], cap=0)


# --------------------------------------------------------------------------- #
# The bytes on disk.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cap", [9 * 1024 * 1024, 500_000, 100_000])
def test_no_volume_exceeds_the_cap_and_every_byte_round_trips(tmp_path, cap):
    """The guarantee, measured on the files themselves at three caps -- the largest
    needs no split, the smallest forces several."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=cap)

    for v in manifest["volumes"]:
        actual = (vol_dir / v["name"]).stat().st_size
        assert actual <= cap, f"{v['name']} is {actual} B against a {cap} B cap"
        assert actual == v["bytes"], "the manifest must describe the file as written"

    assert dv.verify_volume_set(vol_dir)["ok"]

    with zipfile.ZipFile(src) as s:
        original = {n: s.read(n) for n in s.namelist()}
    rebuilt = _members_from_volumes(vol_dir, manifest)
    dest = tmp_path / "rebuilt"
    for path in dv.reassemble_split_members(vol_dir, dest):
        rebuilt[Path(path).name] = Path(path).read_bytes()
    for path in dv.reassemble_cut_members(vol_dir, dest):
        rebuilt[Path(path).name] = Path(path).read_bytes()

    assert set(rebuilt) == set(original), "every member must survive the split"
    cut = set(manifest["cut_members"])
    for name, data in original.items():
        if name in cut and name.endswith(".json"):  # a cut JSON document is put back by value, not by its spacing
            assert json.loads(rebuilt[name]) == json.loads(data), name
        else:  # a whole member, and a split or byte-cut one, comes back byte for byte
            assert rebuilt[name] == data, name


def test_every_volume_opens_alone_and_says_what_is_missing(tmp_path):
    """The failure this design exists to avoid: an analyst handed one volume of five
    must be able to open it AND work out what else to ask for."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)
    assert len(manifest["volumes"]) > 1, "fixture must actually produce several volumes"

    for i, v in enumerate(manifest["volumes"], start=1):
        with zipfile.ZipFile(vol_dir / v["name"]) as z:
            readme = json.loads(z.read(dv.README_NAME))
            present = {n for n in z.namelist() if n != dv.README_NAME}
        assert readme["volume_count"] == len(manifest["volumes"])
        assert readme["volume_index"] == i
        assert readme["volume_name"] == v["name"]
        assert "-part-NN-of-" in readme["volume_name_pattern"], "the rest are nameable from here"
        assert readme["volume_name"].endswith(f"-part-{i:02d}-of-{len(manifest['volumes']):02d}.zip")
        assert {m["entry"] for m in readme["members_in_this_volume"]} == present


def test_the_in_volume_index_stays_bounded_as_the_cap_shrinks(tmp_path):
    """A MEASURED defect, not a theoretical one. The first version embedded the whole
    set's member map in every volume; that map grows as the cap shrinks, so at a 20 KB
    cap each of 2164 volumes came out at 39 KB -- the index alone was double the cap and
    the module's one guarantee was false in exactly the regime it exists for."""
    src = _build_bundle(tmp_path)
    sizes = {}
    for cap in (200_000, 20_000):
        vol_dir = tmp_path / f"vols{cap}"
        manifest = dv.write_volume_set(src, vol_dir, cap=cap)
        with zipfile.ZipFile(vol_dir / manifest["volumes"][0]["name"]) as z:
            sizes[cap] = len(z.read(dv.README_NAME))
        for v in manifest["volumes"]:
            assert (vol_dir / v["name"]).stat().st_size <= cap

    assert sizes[20_000] < 20_000, "the index must fit the volume that carries it"


def test_the_in_volume_readme_carries_no_checksums_and_says_why(tmp_path):
    """A file cannot contain its own hash. The first draft wrote the checksums, appended
    the manifest, and thereby invalidated every checksum it had just recorded -- so the
    two descriptors are split by name, and the readme states where the hashes are."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)

    with zipfile.ZipFile(vol_dir / manifest["volumes"][0]["name"]) as z:
        readme = json.loads(z.read(dv.README_NAME))
    assert "volumes" not in readme, "no checksum list inside a volume"
    assert dv.MANIFEST_NAME in readme["checksums"]
    assert dv.MANIFEST_NAME in readme["full_member_map"]
    assert all("sha256" in v for v in manifest["volumes"]), "the sidecar has them"


def test_part_names_stay_in_byte_order_past_ten_thousand_parts(tmp_path):
    """A SILENT CORRUPTION found by running the splitter at its smallest cap. At a fixed
    4-digit pad, part 10000 is written "10000" and part 9999 "9999", and "10000" sorts
    BEFORE "9999" -- so a member of 10,000+ parts rejoined in the wrong order, under both
    the shell glob this module documents and its own reader, with nothing to report it:
    the checksums cover the volumes, not the rejoined member."""
    names = [dv._part_name("big.json", i, 10_000) for i in (1, 999, 9_999, 10_000)]
    assert names == sorted(names), names
    assert names[-1] == "big.json.part10000of10000"
    # The common case keeps its familiar 4-wide shape.
    assert dv._part_name("big.json", 2, 3) == "big.json.part0002of0003"


def test_a_volume_over_the_cap_is_refused_and_nothing_is_published(tmp_path, monkeypatch):
    """Whatever the planner concluded, the bytes on disk are checked -- and a set with an
    over-cap volume is withdrawn entirely rather than handed to an operator who would
    discover it at the far end of the channel, which is where this went wrong once."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    # Force the failure the planner is supposed to prevent: pack as if there were room,
    # then let the real size check catch it.
    monkeypatch.setattr(dv, "_overhead_reserve", lambda cap: 1024)
    monkeypatch.setattr(dv, "_deflated_cost", lambda data: 1)

    with pytest.raises(dv.VolumeError, match="exceeded"):
        dv.write_volume_set(src, vol_dir, cap=50_000)
    assert not list(vol_dir.glob("*.zip")), "a refused set must leave nothing behind"


def test_a_split_member_is_named_in_prose_not_left_to_be_discovered(tmp_path):
    src = _build_bundle(tmp_path)
    manifest = dv.write_volume_set(src, tmp_path / "vols", cap=100_000)
    assert manifest["split_members"], "fixture must force a split"
    for base in manifest["split_members"]:
        assert base in manifest["note"]
    assert "cat " in manifest["note"], "the note gives the actual reassembly command"


def test_a_set_with_no_split_says_so_rather_than_staying_silent(tmp_path):
    """Absence of a warning is not the same as a statement that there is nothing to warn
    about -- an operator should not have to infer it from a missing sentence."""
    src = _build_bundle(tmp_path)
    manifest = dv.write_volume_set(src, tmp_path / "vols", cap=9 * 1024 * 1024)
    assert manifest["split_members"] == []
    assert "No member is split" in manifest["note"]


# --------------------------------------------------------------------------- #
# The refusals.
# --------------------------------------------------------------------------- #


def test_verify_catches_a_truncated_volume(tmp_path):
    """The likely failure for a set that exists BECAUSE of an upload limit."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)
    victim = vol_dir / manifest["volumes"][1]["name"]
    victim.write_bytes(victim.read_bytes()[:-64])

    res = dv.verify_volume_set(vol_dir)
    assert res["ok"] is False
    assert victim.name in res["bad"]
    assert res["missing"] == [], "truncated is not the same fact as absent"


def test_verify_catches_a_damaged_manifest_zip(tmp_path):
    """The manifest zip is a file of the set like any volume: a truncated one is what a person
    would send, so it is checked against the checksum recorded for it."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)
    (mf,) = manifest["manifest_files"]
    path = vol_dir / mf["name"]
    assert dv.verify_volume_set(vol_dir)["ok"] is True
    path.write_bytes(path.read_bytes()[:-8])
    res = dv.verify_volume_set(vol_dir)
    assert res["ok"] is False and mf["name"] in res["bad"]
    path.unlink()
    res = dv.verify_volume_set(vol_dir)
    assert mf["name"] in res["missing"]


def test_verify_names_a_missing_volume_as_missing(tmp_path):
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)
    gone = vol_dir / manifest["volumes"][-1]["name"]
    gone.unlink()

    res = dv.verify_volume_set(vol_dir)
    assert res["ok"] is False
    assert gone.name in res["missing"] and gone.name in res["bad"]


def test_reassembly_refuses_an_incomplete_set_rather_than_truncating(tmp_path):
    """A member short by one part that does not SAY it is short is the worst outcome
    here: it will be read and believed."""
    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)
    assert manifest["split_members"]
    (vol_dir / manifest["volumes"][-1]["name"]).unlink()

    with pytest.raises(dv.VolumeError):
        dv.reassemble_split_members(vol_dir, tmp_path / "rebuilt")
    assert not (tmp_path / "rebuilt").exists() or not list((tmp_path / "rebuilt").iterdir())


def test_load_manifest_refuses_a_foreign_volume_set(tmp_path):
    """A backup volume set and a diagnostics one share a manifest NAME and shape on
    purpose; they are not interchangeable, and the reader must say so by kind."""
    d = tmp_path / "vols"
    d.mkdir()
    (d / dv.MANIFEST_NAME).write_text(
        json.dumps({"kind": "oo-volumes-1", "volumes": []}), encoding="utf-8"
    )
    with pytest.raises(dv.VolumeError, match="not a diagnostics volume set"):
        dv.load_manifest(d)


def test_load_manifest_refuses_a_directory_with_no_manifest(tmp_path):
    with pytest.raises(dv.VolumeError, match="no volume manifest"):
        dv.load_manifest(tmp_path)


def test_the_cap_is_env_tunable_and_floored_against_a_zero(monkeypatch):
    monkeypatch.setenv("OO_DIAG_VOLUME_MAX_MB", "25")
    assert dv.volume_max_bytes() == 25 * 1024 * 1024
    monkeypatch.setenv("OO_DIAG_VOLUME_MAX_MB", "0")
    assert dv.volume_max_bytes() == 4096
    monkeypatch.setenv("OO_DIAG_VOLUME_MAX_MB", "not-a-number")
    assert dv.volume_max_bytes() == 1_000_000, "a bad value falls back, never crashes"
    monkeypatch.delenv("OO_DIAG_VOLUME_MAX_MB")
    assert dv.volume_max_bytes() == dv.UPLOAD_PART_BYTES == 1_000_000


# --------------------------------------------------------------------------- #
# The routes. Additive by construction: the single-file download is untouched, so an
# operator who can send one file is never made to collect several.
# --------------------------------------------------------------------------- #


@pytest.fixture
def _diag_dir(tmp_path, monkeypatch):
    """Point the diagnostics archive directory at a tmp dir for the route tests."""
    from src.api.diagnostics import bundle as _diag_bundle

    root = tmp_path / "diagnostics"
    root.mkdir()
    monkeypatch.setattr(_diag_bundle, "_all_diagnostics_dir", lambda: root)
    return root


def test_the_volumes_route_refuses_before_any_archive_exists(_diag_dir):
    """404 with the command that fixes it, never an empty set that reads as 'nothing to
    report' about a bundle that was simply never built."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 404
    assert "all-job" in exc.value.detail


def test_the_volumes_route_splits_the_published_archive_and_serves_each_one(_diag_dir):
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20260911-120000.zip")

    manifest = json.loads(bytes(d.all_diagnostics_volumes().body))
    assert manifest["kind"] == dv.VOLUME_KIND
    assert manifest["source"] == "oo-all-diagnostics-20260911-120000.zip"
    assert manifest["volumes"], "a split must produce at least one volume"

    for v in manifest["volumes"]:
        resp = d.all_diagnostics_volume_download(v["name"])
        assert Path(resp.path).stat().st_size == v["bytes"]
        assert resp.media_type == "application/zip"


def test_a_volume_name_not_in_the_set_is_refused_so_a_path_cannot_be_reached(_diag_dir):
    """The name resolves against the MANIFEST, not the filesystem -- so neither a
    traversal nor a leftover file that happens to sit in the directory can be served."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20260911-120000.zip")
    d.all_diagnostics_volumes()
    (d._all_diagnostics_volumes_dir() / "not-a-volume.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)

    for bad in ("../../etc/passwd", "not-a-volume.zip"):
        with pytest.raises(HTTPException) as exc:
            d.all_diagnostics_volume_download(bad)
        assert exc.value.status_code == 404


def test_a_second_call_reuses_the_set_and_a_new_archive_replaces_it(_diag_dir):
    """Splitting is idempotent on the source archive: a second click re-serves rather
    than re-splitting, and volumes of two different bundles never share a directory
    where an operator collecting files by glob would mix them."""
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    first = _diag_dir / "oo-all-diagnostics-20260911-120000.zip"
    src.rename(first)
    m1 = json.loads(bytes(d.all_diagnostics_volumes().body))
    vol_dir = d._all_diagnostics_volumes_dir()
    stamp = (vol_dir / m1["volumes"][0]["name"]).stat().st_mtime_ns

    m2 = json.loads(bytes(d.all_diagnostics_volumes().body))
    assert m2["volumes"] == m1["volumes"]
    assert (vol_dir / m1["volumes"][0]["name"]).stat().st_mtime_ns == stamp, "not re-split"

    first.unlink()
    newer = _build_bundle(_diag_dir)
    newer.rename(_diag_dir / "oo-all-diagnostics-20260912-090000.zip")
    m3 = json.loads(bytes(d.all_diagnostics_volumes().body))
    assert m3["source"] == "oo-all-diagnostics-20260912-090000.zip"
    assert {p.name for p in vol_dir.glob("*.zip")} == (
        {v["name"] for v in m3["volumes"]} | {f["name"] for f in m3["manifest_files"]}
    )


def test_volumes_live_below_the_archive_dir_so_the_sweep_cannot_eat_them(_diag_dir):
    """Load-bearing placement, not tidiness. The build worker sweeps old archives with a
    non-recursive glob('oo-all-diagnostics-*.zip') over the archive dir, and a volume is
    named oo-all-diagnostics.001of003.zip -- beside the archives it would match that
    glob and be deleted, or be served BY _newest_all_diagnostics_archive as if one
    volume were the whole bundle."""
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20260911-120000.zip")
    d.all_diagnostics_volumes()

    assert d._all_diagnostics_volumes_dir().parent == _diag_dir
    swept = set(_diag_dir.glob("oo-all-diagnostics-*.zip"))
    assert swept == {_diag_dir / "oo-all-diagnostics-20260911-120000.zip"}
    newest = d._newest_all_diagnostics_archive()
    assert newest is not None and newest.name == "oo-all-diagnostics-20260911-120000.zip"


def test_two_split_members_with_the_same_basename_do_not_overwrite_each_other(tmp_path):
    """Flattening a rebuilt member by Path(...).name alone keeps it out of a directory
    it should not reach, but makes 'a/x.bin' and 'b/x.bin' land on one file -- trading
    a traversal for a silently lost member, which is the failure this module is least
    allowed to have."""
    src = tmp_path / "oo-all-diagnostics-20260911-1200.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("a/x.bin", os.urandom(120_000))
        z.writestr("b/x.bin", os.urandom(120_000))

    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=40_000)
    assert sorted(manifest["split_members"]) == ["a/x.bin", "b/x.bin"]

    dest = tmp_path / "rebuilt"
    written = dv.reassemble_split_members(vol_dir, dest)
    assert len(set(written)) == 2, "each member keeps its own file"

    with zipfile.ZipFile(src) as s:
        for base in ("a/x.bin", "b/x.bin"):
            assert (dest / base.replace("/", "__")).read_bytes() == s.read(base)
    for path in written:
        assert Path(path).resolve().parent == dest.resolve(), "nothing escapes dest"


def test_a_running_build_refuses_the_split_rather_than_serving_the_previous_bundle(
    _diag_dir, monkeypatch
):
    """The SAME refusal the single-file download already makes, for the same reason. The
    operator asked the NEW run a question and the previous run's bundle cannot answer it;
    splitting it and handing over the pieces would be a fabricated result wearing a fresh
    timestamp. Checked in the route rather than inherited: _newest_all_diagnostics_archive
    only skips '.part' files, so on its own it returns the previous archive mid-build."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20260911-120000.zip")
    monkeypatch.setattr(d._ALL_DIAG_JOB, "status", lambda: {"state": "running"})

    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 409
    assert "running" in exc.value.detail
    assert not list(d._all_diagnostics_volumes_dir().glob("*.zip")), "nothing was split"


# --------------------------------------------------------------------------- #
# 2026-10-01: 1,000,000-byte volumes, numbered names, a manifest zip, cuts on record boundaries.
# --------------------------------------------------------------------------- #


def _noisy_json_member(n: int) -> str:
    import random

    rnd = random.Random(5)
    return json.dumps({"rows": [{"id": i, "t": "".join(rnd.choice("0123456789abcdef") for _ in range(60))}
                                for i in range(n)], "meta": {"kind": "test"}})


def test_the_default_cap_is_one_million_bytes_and_volumes_carry_position_and_total(tmp_path):
    src = tmp_path / "oo-all-diagnostics-20261001-010000.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", "{}")
        for i in range(5):
            z.writestr(f"big-{i}.bin", os.urandom(500_000))
    manifest = dv.write_volume_set(src, tmp_path / "v")
    assert manifest["volume_max_bytes"] == 1_000_000
    n = len(manifest["volumes"])
    assert n > 2
    assert [v["name"] for v in manifest["volumes"]] == [
        f"oo-all-diagnostics-20261001-010000-part-{i:02d}-of-{n:02d}.zip" for i in range(1, n + 1)
    ]
    assert all(v["bytes"] <= 1_000_000 for v in manifest["volumes"])
    assert [f["name"] for f in manifest["manifest_files"]] == [
        "oo-all-diagnostics-20261001-010000-manifest.zip"
    ]


def test_the_manifest_zip_lists_every_volume_with_its_size_and_checksum(tmp_path):
    import hashlib

    src = _build_bundle(tmp_path)
    vol_dir = tmp_path / "v"
    manifest = dv.write_volume_set(src, vol_dir, cap=100_000)
    (mf,) = manifest["manifest_files"]
    assert (vol_dir / mf["name"]).stat().st_size <= 100_000
    assert hashlib.sha256((vol_dir / mf["name"]).read_bytes()).hexdigest() == mf["sha256"]
    with zipfile.ZipFile(vol_dir / mf["name"]) as z:
        inner = json.loads(z.read(dv.MANIFEST_NAME))
    assert inner["volumes"] == manifest["volumes"]
    assert inner["volume_names"] == manifest["volume_names"]


def test_a_json_member_larger_than_a_volume_is_cut_into_pieces_each_valid_alone(tmp_path):
    src = tmp_path / "oo-all-diagnostics-20261001-020000.zip"
    doc = _noisy_json_member(40_000)
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", "{}")
        z.writestr("report.json", doc)
    vol_dir = tmp_path / "v"
    manifest = dv.write_volume_set(src, vol_dir)  # the real 1,000,000
    assert manifest["cut_members"] == ["report.json"] and manifest["split_members"] == []
    pieces = [m for m in manifest["members"] if m.get("cut")]
    assert len(pieces) > 2 and [m["cut"]["piece"] for m in pieces] == list(range(1, len(pieces) + 1))
    for v in manifest["volumes"]:
        assert v["bytes"] <= 1_000_000
        with zipfile.ZipFile(vol_dir / v["name"]) as z:
            assert z.testzip() is None
            for name in z.namelist():
                json.loads(z.read(name))  # every file of every volume parses on its own
    (dest,) = [Path(p) for p in dv.reassemble_cut_members(vol_dir, tmp_path / "back")]
    assert json.loads(dest.read_text(encoding="utf-8")) == json.loads(doc)
    assert "report.json" in manifest["note"] and "cut on record boundaries" in manifest["note"].lower()


def test_a_log_member_is_cut_between_lines_and_a_table_repeats_its_header(tmp_path):
    src = tmp_path / "oo-all-diagnostics-20261001-030000.zip"
    import random

    rnd = random.Random(6)
    log = "".join(
        json.dumps({"i": i, "x": "".join(rnd.choice("0123456789abcdef") for _ in range(80))}) + "\n"
        for i in range(30_000)
    )
    table = "id,value\n" + "".join(
        f"{i},{''.join(rnd.choice('0123456789abcdef') for _ in range(60))}\n" for i in range(30_000)
    )
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bundle-journal.jsonl", log)
        z.writestr("table.csv", table)
    vol_dir = tmp_path / "v"
    manifest = dv.write_volume_set(src, vol_dir)
    assert sorted(manifest["cut_members"]) == ["bundle-journal.jsonl", "table.csv"]
    assert all(v["bytes"] <= 1_000_000 for v in manifest["volumes"])
    for v in manifest["volumes"]:
        with zipfile.ZipFile(vol_dir / v["name"]) as z:
            for name in z.namelist():
                if name.endswith(".csv"):
                    assert z.read(name).startswith(b"id,value\n"), "every table piece has the header"
                elif name.endswith(".jsonl"):
                    for line in z.read(name).decode().splitlines():
                        json.loads(line)  # no line is ever cut through
    back = {Path(p).name: Path(p).read_text(encoding="utf-8")
            for p in dv.reassemble_cut_members(vol_dir, tmp_path / "back")}
    assert back["bundle-journal.jsonl"] == log
    assert back["table.csv"] == table


def test_a_member_that_is_neither_a_document_nor_a_log_keeps_the_stated_byte_cut(tmp_path):
    src = tmp_path / "oo-all-diagnostics-20261001-040000.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("blob.bin", os.urandom(2_500_000))
    manifest = dv.write_volume_set(src, tmp_path / "v")
    assert manifest["split_members"] == ["blob.bin"] and manifest["cut_members"] == []
    assert "SPLIT BY BYTES" in manifest["note"]
    assert all(v["bytes"] <= 1_000_000 for v in manifest["volumes"])


def test_a_cut_json_member_too_large_to_parse_safely_here_falls_back_to_the_byte_cut(
    tmp_path, monkeypatch
):
    import src.analytics.keyword_log_scan as kls

    monkeypatch.setattr(kls, "available_bytes_now", lambda: 1_000_000)  # a machine with no room
    src = tmp_path / "oo-all-diagnostics-20261001-050000.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", _noisy_json_member(40_000))
    manifest = dv.write_volume_set(src, tmp_path / "v")
    assert manifest["split_members"] == ["report.json"], "never parsed what this machine cannot hold"
    assert all(v["bytes"] <= 1_000_000 for v in manifest["volumes"])


def test_the_route_lists_files_in_the_page_shape_manifest_first_and_serves_the_manifest_zip(_diag_dir):
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20261001-060000.zip")
    listing = json.loads(bytes(d.all_diagnostics_volumes().body))
    kinds = [f["kind"] for f in listing["files"]]
    assert kinds[0] == "manifest" and set(kinds[1:]) == {"part"}
    assert listing["download_base"] == "/api/diagnostics/all-job/volumes/"
    assert listing["part_count"] == len(listing["volumes"])
    assert all(f["bytes"] <= listing["part_max_bytes"] for f in listing["files"])
    for f in listing["files"]:
        resp = d.all_diagnostics_volume_download(f["name"])
        assert Path(resp.path).stat().st_size == f["bytes"]


def _two_archives(_diag_dir):
    """The first archive split (its listing returned), then a newer archive waiting to be split."""
    from src.api import diagnostics as d

    first = _diag_dir / "oo-all-diagnostics-20261001-060000.zip"
    _build_bundle(_diag_dir).rename(first)
    old = json.loads(bytes(d.all_diagnostics_volumes().body))
    first.unlink()
    newer = _diag_dir / "oo-all-diagnostics-20261001-070000.zip"
    _build_bundle(_diag_dir).rename(newer)
    return old, newer


def test_a_split_that_fails_leaves_the_previous_set_serving_and_no_half_written_files(
    _diag_dir, monkeypatch
):
    """R115 follow-up S1. The previous files were deleted first and the new ones written into the
    live folder, so a split that died left NO set and the half-written volumes beside nothing."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    old, _newer = _two_archives(_diag_dir)
    vol_dir = d._all_diagnostics_volumes_dir()
    before = sorted(p.name for p in vol_dir.iterdir())

    def _dies_after_one_file(src_zip, out_dir, **kw):
        (Path(out_dir) / "half-written-part-01-of-03.zip").write_bytes(b"PK" + b"0" * 1000)
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(dv, "write_volume_set", _dies_after_one_file)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 500
    assert "Input/output error" in exc.value.detail
    assert "could not split" not in exc.value.detail.lower(), "the page says that, translated"
    assert sorted(p.name for p in vol_dir.iterdir()) == before, "the set that was there is untouched"
    assert not list(_diag_dir.glob("volumes-build-*")), "the build folder goes on every path"
    for f in old["files"]:
        assert Path(d.all_diagnostics_volume_download(f["name"]).path).is_file()


def test_the_previous_set_keeps_answering_for_the_whole_length_of_the_next_split(_diag_dir, monkeypatch):
    """R115 follow-up S1: every name 404ed from the sweep to the sidecar, seconds to a minute."""
    from src.api import diagnostics as d

    old, newer = _two_archives(_diag_dir)
    real = dv.write_volume_set
    probed: list[str] = []

    def _probe_then_build(src_zip, out_dir, **kw):
        for f in old["files"]:
            probed.append(Path(d.all_diagnostics_volume_download(f["name"]).path).name)
        return real(src_zip, out_dir, **kw)

    monkeypatch.setattr(dv, "write_volume_set", _probe_then_build)
    new = json.loads(bytes(d.all_diagnostics_volumes().body))

    assert probed == [f["name"] for f in old["files"]], "the old set answered while the new one was built"
    assert new["source"] == newer.name
    vol_dir = d._all_diagnostics_volumes_dir()
    assert {p.name for p in vol_dir.iterdir()} == (
        {f["name"] for f in new["files"]} | {dv.MANIFEST_NAME}
    ), "the old files are retired once the new set is in, and nothing else is left"
    assert not list(_diag_dir.glob("volumes-build-*"))


def test_a_build_folder_a_dead_process_left_is_removed_by_the_next_split(_diag_dir):
    from src.api import diagnostics as d

    left = _diag_dir / "volumes-build-dead1234"
    left.mkdir()
    (left / "x-part-01-of-01.zip").write_bytes(b"PK" + b"0" * 100)
    _build_bundle(_diag_dir).rename(_diag_dir / "oo-all-diagnostics-20261001-080000.zip")
    d.all_diagnostics_volumes()
    assert not left.exists()


def _fake_disk(monkeypatch, *, free: int, total: int = 100 * 2**30):
    import collections
    import shutil

    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(total, total - free, free))


@pytest.mark.parametrize("earlier", ["none", "set", "files"])
def test_a_drive_without_room_is_refused_with_507_before_anything_is_written(
    _diag_dir, monkeypatch, earlier
):
    """R115 follow-up S2: the keyword path preflighted; this one ran into a full disk after the
    sweep and answered with a raw operating-system error. The text says only what is true of what
    was on the drive: a set whose sidecar loads, files whose sidecar is refused or corrupt (the
    case the first wording called "no earlier set"), or nothing."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    with_a_previous_set = earlier == "set"
    if with_a_previous_set:
        old, _newer = _two_archives(_diag_dir)
    else:
        old = None
        _build_bundle(_diag_dir).rename(_diag_dir / "oo-all-diagnostics-20261001-090000.zip")
    vol_dir = d._all_diagnostics_volumes_dir()
    if earlier == "files":
        vol_dir.mkdir(parents=True, exist_ok=True)
        (vol_dir / dv.MANIFEST_NAME).write_text("{this is not json", encoding="utf-8")
        (vol_dir / "oo-diagnostics-20260930-070500-part-01.zip").write_bytes(b"PK")
    before = sorted(p.name for p in vol_dir.iterdir())
    _fake_disk(monkeypatch, free=1 * 2**20)

    def _must_not_run(*a, **kw):
        raise AssertionError("no room: nothing may be written")

    monkeypatch.setattr(dv, "write_volume_set", _must_not_run)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 507
    assert "MiB" in exc.value.detail and "free" in exc.value.detail
    if with_a_previous_set:
        assert "The earlier set of files was not touched" in exc.value.detail
        assert "no earlier set" not in exc.value.detail
    elif earlier == "files":
        assert "Files of an earlier set are in the folder, though their list could not be read" in exc.value.detail
        assert "were not touched" in exc.value.detail
        assert "no earlier set" not in exc.value.detail and "none was written" not in exc.value.detail
    else:
        # nothing is claimed about files that were never there, and nothing about "the server": the
        # sweep of a killed build's leftovers runs before this check, so "nothing was changed" would
        # not be true in every case
        assert "There was no earlier set of files, and none was written" in exc.value.detail
        assert "not touched" not in exc.value.detail and "Nothing on the server" not in exc.value.detail
    assert sorted(p.name for p in vol_dir.iterdir()) == before
    assert not list(_diag_dir.glob("volumes-build-*"))
    if old is not None:
        for f in old["files"]:
            assert Path(d.all_diagnostics_volume_download(f["name"]).path).is_file()


def test_a_drive_with_room_for_the_archive_and_its_headroom_above_the_floor_is_not_refused(_diag_dir, monkeypatch):
    from src.analytics.keyword_log_export import _DISK_RESERVE_FLOOR
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    need = src.stat().st_size
    src.rename(_diag_dir / "oo-all-diagnostics-20261001-100000.zip")
    # The floor (512 MiB) plus the archive and its 20% headroom: exactly enough.
    _fake_disk(monkeypatch, free=int(need * 1.2) + _DISK_RESERVE_FLOOR + 1)
    assert json.loads(bytes(d.all_diagnostics_volumes().body))["volume_count"] >= 1


@pytest.mark.parametrize("with_a_previous_set", [False, True])
def test_a_drive_one_byte_short_of_the_archive_and_its_headroom_is_refused(
    _diag_dir, monkeypatch, with_a_previous_set
):
    """The other side of the test above: the room check counts the ARCHIVE'S size (a check that counted
    nothing would still refuse a nearly full drive and still pass the test of a roomy one), and it does
    not count the previous set as free (it stays until the new one is in, so for a moment all three are
    on the drive)."""
    from fastapi import HTTPException

    from src.analytics.keyword_log_export import _DISK_RESERVE_FLOOR
    from src.api import diagnostics as d

    if with_a_previous_set:
        _old, newer = _two_archives(_diag_dir)
        need = newer.stat().st_size
    else:
        src = _build_bundle(_diag_dir)
        need = src.stat().st_size
        src.rename(_diag_dir / "oo-all-diagnostics-20261001-110000.zip")
    assert need > 1_000, "the archive is big enough for the headroom to be more than a byte"
    _fake_disk(monkeypatch, free=int(need * 1.2) + _DISK_RESERVE_FLOOR - 1)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 507
    assert f"{need / 2**20:.0f} MiB" in exc.value.detail


def test_a_large_drive_that_is_nearly_full_still_takes_the_split(_diag_dir, monkeypatch):
    """What the reserve is: the floor, not one per cent of the drive. The keyword export writes
    gigabytes and keeps a share of the drive free for the database's log; the split writes about the
    archive's size, and refusing it on a 2 TB drive with 15 GiB free closed the diagnostics on exactly
    the machines that need them."""
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20261001-120000.zip")
    _fake_disk(monkeypatch, free=15 * 2**30, total=2 * 2**40)
    assert json.loads(bytes(d.all_diagnostics_volumes().body))["volume_count"] >= 1


def test_a_second_click_on_a_full_drive_re_serves_the_current_set(_diag_dir, monkeypatch):
    """The idempotent path comes BEFORE the room check: a set that is already the current one needs no
    room, so a drive that has since filled up still hands the person the files they were given."""
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20261001-130000.zip")
    first = json.loads(bytes(d.all_diagnostics_volumes().body))
    _fake_disk(monkeypatch, free=1 * 2**20)
    again = json.loads(bytes(d.all_diagnostics_volumes().body))
    assert [f["name"] for f in again["files"]] == [f["name"] for f in first["files"]]


def test_what_a_killed_publish_left_goes_even_when_the_set_is_about_to_be_replaced_and_the_drive_refuses(
    _diag_dir, monkeypatch
):
    """The sweep of files the sidecar does not name runs for whichever sidecar loads, not only for the
    current set: a newer archive that then meets a full drive (507) still clears the leftovers, which are
    a set's worth of disk and can be what lets the next press fit, and the set the person has stays."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    old, _newer = _two_archives(_diag_dir)
    vol_dir = d._all_diagnostics_volumes_dir()
    leftover = vol_dir / "older-bundle-part-01-of-02.zip"
    leftover.write_bytes(b"PK" + b"0" * 50)
    _fake_disk(monkeypatch, free=1 * 2**20)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == 507
    assert not leftover.exists()
    assert {p.name for p in vol_dir.iterdir()} == {f["name"] for f in old["files"]} | {dv.MANIFEST_NAME}


def test_a_current_set_is_re_served_and_what_a_killed_publish_left_goes(_diag_dir):
    """A publish killed between the sidecar's move and the end of its sweep, or a file the system
    refused to remove, left the previous set's files beside the new one; the re-serving path swept
    nothing, so they outlived the set they belonged to. A build folder left by a killed process goes
    on the same path."""
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20261001-140000.zip")
    first = json.loads(bytes(d.all_diagnostics_volumes().body))
    vol_dir = d._all_diagnostics_volumes_dir()
    leftover = vol_dir / "old-bundle-part-01-of-02.zip"
    leftover.write_bytes(b"PK" + b"0" * 50)
    build = _diag_dir / "volumes-build-killed"
    build.mkdir()
    (build / "half.zip").write_bytes(b"PK")
    again = json.loads(bytes(d.all_diagnostics_volumes().body))
    assert [f["name"] for f in again["files"]] == [f["name"] for f in first["files"]]
    assert not leftover.exists() and not build.exists()
    named = {f["name"] for f in first["files"]} | {dv.MANIFEST_NAME}
    assert {p.name for p in vol_dir.iterdir()} == named, "and nothing the sidecar names went with them"


@pytest.mark.parametrize(
    "code, status",
    [(errno.ENOSPC, 507), (errno.EROFS, 507), (errno.EIO, 500)]
    + ([(errno.EDQUOT, 507)] if hasattr(errno, "EDQUOT") else []),
)
def test_a_split_that_runs_out_of_room_halfway_is_the_507_the_preflight_gives(_diag_dir, monkeypatch, code, status):
    """The same condition got two statuses: 507 at the start of the split and 500 when the drive filled
    during it. Another operating-system error is still the 500 it was (it may be a bug)."""
    from fastapi import HTTPException

    from src.api import diagnostics as d

    old, _newer = _two_archives(_diag_dir)

    def _dies(src_zip, out_dir, **kw):
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(dv, "write_volume_set", _dies)
    with pytest.raises(HTTPException) as exc:
        d.all_diagnostics_volumes()
    assert exc.value.status_code == status
    assert os.strerror(code) in exc.value.detail
    if status == 507:
        assert "Free some space" in exc.value.detail
        # true on a first split too (no earlier set to touch), and true when the removal of the
        # half-written files was itself refused: they go now or at the first press the drive allows
        # it (the removal ignores its own errors, so a drive that keeps refusing keeps them, and
        # "at the next press at the latest" would promise what only a drive that obeys can keep)
        assert "The earlier set of files, if there was one, was not touched" in exc.value.detail
        assert "at the first press the drive allows it" in exc.value.detail
        assert "at the latest" not in exc.value.detail
        assert "files were removed" not in exc.value.detail
    for f in old["files"]:
        assert Path(d.all_diagnostics_volume_download(f["name"]).path).is_file()


def test_publishing_moves_the_sidecar_last_and_retires_only_what_nothing_names(tmp_path, monkeypatch):
    """The sidecar is what makes a set exist: until it moves the old one still names old files."""
    src = _build_bundle(tmp_path)
    build, out = tmp_path / "build", tmp_path / "volumes"
    out.mkdir()
    (out / "old-part-01-of-01.zip").write_bytes(b"PK" + b"0" * 50)
    (out / dv.MANIFEST_NAME).write_text(json.dumps({"kind": dv.VOLUME_KIND, "volumes": []}), encoding="utf-8")
    manifest = dv.write_volume_set(src, build, cap=100_000)

    moved: list[str] = []
    events: list[tuple[str, str]] = []
    real = os.replace
    real_unlink = Path.unlink

    def _recording_replace(a, b, *args, **kw):
        moved.append(Path(b).name)
        events.append(("replace", Path(b).name))
        return real(a, b, *args, **kw)

    def _recording_unlink(self, *args, **kw):
        events.append(("unlink", self.name))
        return real_unlink(self, *args, **kw)

    monkeypatch.setattr(os, "replace", _recording_replace)
    monkeypatch.setattr(Path, "unlink", _recording_unlink)
    got = dv.publish_volume_set(build, out)
    assert got == manifest
    assert moved[-1] == dv.MANIFEST_NAME and dv.MANIFEST_NAME not in moved[:-1]
    # "only then are the files nothing names any more removed": the old part goes after the sidecar's move
    sidecar_at = events.index(("replace", dv.MANIFEST_NAME))
    assert ("unlink", "old-part-01-of-01.zip") in events[sidecar_at:]
    assert not [e for e in events[:sidecar_at] if e[0] == "unlink"], "nothing is removed before the sidecar is in"
    assert sorted(moved[:-1]) == sorted(
        [v["name"] for v in manifest["volumes"]] + [f["name"] for f in manifest["manifest_files"]]
    )
    assert {p.name for p in out.iterdir()} == set(moved)
    assert dv.verify_volume_set(out)["ok"]


def test_a_stale_file_that_cannot_be_removed_does_not_fail_the_publish(tmp_path, monkeypatch):
    """A download holding a file open on Windows refuses its removal; the set is still in."""
    src = _build_bundle(tmp_path)
    build, out = tmp_path / "build", tmp_path / "volumes"
    out.mkdir()
    stale = out / "old-part-01-of-01.zip"
    stale.write_bytes(b"PK" + b"0" * 50)
    dv.write_volume_set(src, build, cap=100_000)

    real_unlink = Path.unlink

    def _refuses_the_stale_file(self, *a, **kw):
        if self.name == stale.name:
            raise PermissionError("in use")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", _refuses_the_stale_file)
    dv.publish_volume_set(build, out)
    assert dv.verify_volume_set(out)["ok"]
    assert stale.exists(), "left for the next publish; never served, as only a listed name is"


def test_a_set_built_under_another_cap_is_rebuilt_not_re_served(_diag_dir, monkeypatch):
    from src.api import diagnostics as d

    src = _build_bundle(_diag_dir)
    src.rename(_diag_dir / "oo-all-diagnostics-20261001-070000.zip")
    first = json.loads(bytes(d.all_diagnostics_volumes().body))
    monkeypatch.setenv("OO_DIAG_VOLUME_MAX_MB", "0.2")
    second = json.loads(bytes(d.all_diagnostics_volumes().body))
    assert first["volume_max_bytes"] == 1_000_000 and second["volume_max_bytes"] == int(0.2 * 1024 * 1024)
    assert second["volume_count"] > first["volume_count"]
