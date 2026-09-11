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

    assert set(rebuilt) == set(original), "every member must survive the split"
    assert rebuilt == original, "and survive it byte-for-byte"


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
        assert "NNNof" in readme["volume_name_pattern"], "the rest are nameable from here"
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
    (d / dv.MANIFEST_NAME).write_text(json.dumps({"kind": "oo-volumes-1", "volumes": []}))
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
    assert dv.volume_max_bytes() == 9 * 1024 * 1024, "a bad value falls back, never crashes"


# --------------------------------------------------------------------------- #
# The routes. Additive by construction: the single-file download is untouched, so an
# operator who can send one file is never made to collect several.
# --------------------------------------------------------------------------- #


@pytest.fixture
def _diag_dir(tmp_path, monkeypatch):
    """Point the diagnostics archive directory at a tmp dir for the route tests."""
    from src.api import diagnostics as d

    root = tmp_path / "diagnostics"
    root.mkdir()
    monkeypatch.setattr(d, "_all_diagnostics_dir", lambda: root)
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
    assert set(vol_dir.glob("*.zip")) == {vol_dir / v["name"] for v in m3["volumes"]}


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
    it should not reach, but makes 'a/x.json' and 'b/x.json' land on one file -- trading
    a traversal for a silently lost member, which is the failure this module is least
    allowed to have."""
    src = tmp_path / "oo-all-diagnostics-20260911-1200.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("a/x.json", os.urandom(120_000))
        z.writestr("b/x.json", os.urandom(120_000))

    vol_dir = tmp_path / "vols"
    manifest = dv.write_volume_set(src, vol_dir, cap=40_000)
    assert sorted(manifest["split_members"]) == ["a/x.json", "b/x.json"]

    dest = tmp_path / "rebuilt"
    written = dv.reassemble_split_members(vol_dir, dest)
    assert len(set(written)) == 2, "each member keeps its own file"

    with zipfile.ZipFile(src) as s:
        for base in ("a/x.json", "b/x.json"):
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
