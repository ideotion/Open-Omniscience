"""S6.2 / DAT-01: the wiki dumps, OSM extracts and model weights INSIDE the signed artifact.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The top parked item of the 2026-07-12 closeout, and the reason both the wiki-dump-inclusion
and the models-in-backup rulings sat unbuilt: one portable artifact should be able to carry
these, so restoring a machine needs one thing rather than an encrypted artifact plus a
folder copy whose association with it is the operator's memory.

What is pinned here, in the order the risk runs:

  * THE PATH GUARDS, on BOTH the verify and the restore path, for EVERY manifest field that
    becomes a filesystem path -- not only the one called ``name``. That is the 2026-07-10
    lesson stated as a test: a self-signed hostile backup turning a member field into an
    arbitrary-file write is the failure mode that already happened once here, and
    ``file_members`` adds two more such fields (``category``, ``rel``) which are composed
    into the LIVE data directory rather than into disposable staging.
  * The negative space of the option: a backup that was not asked to carry them carries
    none, and its manifest says so rather than omitting the block.
  * Additive placement: an existing local file is KEPT, never replaced.
  * Honest reporting: a member named in the index but absent from the artifact is reported,
    never invented; a placement that escapes its category is refused and counted.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.backup.folder_backup import BackupItem, place_artifact_file_members
from src.backup.stream_backup import (
    CorpusSource,
    MemberFile,
    _no_freeze,
    collect_blob_members,
    read_stream_backup,
    verify_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import MANIFEST_NAME, VolumeError, load_manifest

VOL = 65536


def _corpus(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
    )
    con.executemany(
        "INSERT INTO articles(hash, content) VALUES(?,?)",
        [(f"h{i:04d}", "x" * 500) for i in range(40)],
    )
    con.commit()
    con.close()
    return path


def _blobs(tmp: Path) -> list[BackupItem]:
    """Two categories, so a placement bug that ignores `category` cannot pass by luck."""
    (tmp / "src").mkdir(exist_ok=True)
    dump = tmp / "src" / "enwiki.bz2"
    dump.write_bytes(b"DUMP" * 5000)
    blob = tmp / "src" / "blobfile"
    blob.write_bytes(b"WEIGHTS" * 3000)
    return [
        BackupItem("wiki_dumps", "enwiki/pages.bz2", dump, dump.stat().st_size),
        BackupItem("models", "blobs/sha256-abc", blob, blob.stat().st_size),
    ]


@pytest.fixture
def stub_items(monkeypatch, tmp_path):
    """Stub the ENUMERATOR, not `collect_blob_members`, so the real category filtering,
    member-name construction and skip-by-flag all run in every test below. The
    enumerator's own skip-non-`done` rule is the folder backup's and is tested there --
    what matters here is that this path delegates to it rather than re-implementing it."""
    import src.backup.folder_backup as fb

    items = _blobs(tmp_path)
    seen: dict = {}

    def fake_collect_items(**kw):
        seen.update(kw)
        return [it for it in items if _wanted(it.category, kw)]

    def _wanted(cat: str, kw: dict) -> bool:
        return {
            "wiki_dumps": kw.get("include_wiki"),
            "osm_regions": kw.get("include_osm"),
            "models": kw.get("include_models"),
            "hf_models": kw.get("include_hf"),
        }.get(cat, False)

    monkeypatch.setattr(fb, "collect_items", fake_collect_items)
    return seen


def _backup(tmp: Path, dest: Path, **kw):
    corpus = _corpus(tmp / "corpus.db")
    side = tmp / "app_settings.json"
    side.write_text('{"k": 1}', encoding="utf-8")
    return write_stream_backup(
        dest,
        "pw",
        corpus_source=CorpusSource(
            path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze
        ),
        side_members=[MemberFile("app_settings.json", "state", side)],
        volume_size=VOL,
        **kw,
    )


# --------------------------------------------------------------------------- #
# The option is opt-in, and its absence is stated
# --------------------------------------------------------------------------- #
def test_a_backup_not_asked_to_carry_them_carries_none(tmp_path, stub_items):
    """The negative space of the whole feature. The 2026-06-21 ruling copies these AS-IS,
    never encrypted, because that is what makes 100 GB feasible -- so carrying them inside
    is a different trade, not an upgrade, and the default must be the behaviour that
    shipped."""
    dest = tmp_path / "d"
    _backup(tmp_path, dest)
    m = load_manifest(dest)
    assert m["file_members"] == [], "absence is published as an empty index, not omitted"
    assert not [x for x in m["members"] if x["role"] == "blob"]
    assert stub_items == {}, "the enumerator is not even consulted"


def test_an_unknown_category_selects_nothing(tmp_path, stub_items):
    assert collect_blob_members(["not_a_category"]) == []
    assert collect_blob_members([]) == []
    assert stub_items == {}, "an empty selection must not walk the stores"


def test_the_categories_asked_for_are_the_flags_passed_to_the_enumerator(tmp_path, stub_items):
    """Delegation, asserted: the skip-non-`done` rule holds here because this path calls
    the folder backup's enumerator, and a second implementation would be free to drift
    from it silently."""
    got = collect_blob_members(["wiki_dumps", "models"])
    assert stub_items == {
        "include_wiki": True,
        "include_osm": False,
        "include_models": True,
        "include_hf": False,
    }
    assert sorted(mf.name for mf, _ in got) == [
        "blobs/models/blobs/sha256-abc",
        "blobs/wiki_dumps/enwiki/pages.bz2",
    ]
    # The placement pair comes back WITH the member rather than being split back out of
    # the name later: the name is built from the pair here, so re-deriving it downstream
    # would be two sources for one fact, free to drift the day the naming changes.
    for mf, where in got:
        assert where["name"] == mf.name
        assert mf.name == f"blobs/{where['category']}/{where['rel']}"


# --------------------------------------------------------------------------- #
# Round trip: in, out, and back into the live folders
# --------------------------------------------------------------------------- #
def test_the_files_ride_inside_and_come_back_out_byte_for_byte(tmp_path, stub_items):
    dest = tmp_path / "d"
    _backup(tmp_path, dest, include_blobs=["wiki_dumps", "models"])
    m = load_manifest(dest)

    idx = {fm["rel"]: fm for fm in m["file_members"]}
    assert sorted(idx) == ["blobs/sha256-abc", "enwiki/pages.bz2"]
    assert idx["enwiki/pages.bz2"]["category"] == "wiki_dumps"
    assert idx["blobs/sha256-abc"]["category"] == "models"
    # They are ordinary members: sliced, encrypted, parity-covered, checksum-verified on
    # reassembly like everything else. Nothing about the artifact is special-cased.
    blob_members = [x for x in m["members"] if x["role"] == "blob"]
    assert len(blob_members) == 2
    assert all(len(x["volumes"]) >= 1 for x in blob_members)
    assert verify_stream_backup(dest, "pw")["ok"] is True

    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "stage")
    assert len(staged.file_members) == 2

    wiki, models = tmp_path / "live-wiki", tmp_path / "live-models"
    out = place_artifact_file_members(
        staged.staging_dir,
        staged.file_members,
        targets={"wiki_dumps": wiki, "models": models},
    )
    assert out["placed"] == 2 and out["skipped"] == 0
    assert out["refused"] == [] and out["missing"] == []
    src_items = {it.rel: it for it in _blobs(tmp_path)}
    assert (wiki / "enwiki/pages.bz2").read_bytes() == src_items["enwiki/pages.bz2"].src.read_bytes()
    assert (models / "blobs/sha256-abc").read_bytes() == src_items["blobs/sha256-abc"].src.read_bytes()


def test_their_bytes_enter_the_volume_sizing_and_the_disk_preflight(tmp_path, stub_items, monkeypatch):
    """Blobs are the largest members by orders of magnitude, so leaving them out of these
    two numbers fails in the two most expensive directions available: the adaptive sizing
    exists to keep N+M under the GF(2^8) 255-volume ceiling, and a preflight that promised
    a backup the drive cannot hold would refuse after twenty gigabytes of writing -- which
    is not a refusal. Asserted at the call, because a comment claiming it is not a check."""
    import src.backup.stream_backup as sb

    seen: dict = {}
    real = sb._preflight_dest

    def spy(dest, corpus_bytes, side_bytes, parity_fraction, *, reuse_possible=False):
        seen["side_bytes"] = side_bytes
        return real(dest, corpus_bytes, side_bytes, parity_fraction, reuse_possible=reuse_possible)

    monkeypatch.setattr(sb, "_preflight_dest", spy)
    blob_bytes = sum(it.size for it in _blobs(tmp_path))
    _backup(tmp_path, tmp_path / "d", include_blobs=["wiki_dumps", "models"])
    assert seen["side_bytes"] >= blob_bytes, "the blob bytes are counted, not just the side members"


def test_placement_never_overwrites_a_local_file(tmp_path, stub_items):
    """The additive rule the folder restore already keeps: a differing local dump is the
    operator's, and a restore that replaced it would be destroying data to deliver data."""
    dest = tmp_path / "d"
    _backup(tmp_path, dest, include_blobs=["wiki_dumps"])
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "stage")

    wiki = tmp_path / "live-wiki"
    (wiki / "enwiki").mkdir(parents=True)
    (wiki / "enwiki/pages.bz2").write_bytes(b"MINE")
    out = place_artifact_file_members(
        staged.staging_dir, staged.file_members, targets={"wiki_dumps": wiki}
    )
    assert out["placed"] == 0 and out["skipped"] == 1
    assert (wiki / "enwiki/pages.bz2").read_bytes() == b"MINE"


def test_an_index_entry_the_artifact_does_not_carry_is_reported_never_invented(tmp_path):
    out = place_artifact_file_members(
        tmp_path / "empty-staging",
        [{"name": "blobs/wiki_dumps/x", "category": "wiki_dumps", "rel": "x"}],
        targets={"wiki_dumps": tmp_path / "live"},
    )
    assert out["placed"] == 0
    assert out["missing"] == [{"category": "wiki_dumps", "rel": "x"}]
    assert not (tmp_path / "live" / "x").exists()


def test_nothing_to_place_is_not_an_error(tmp_path):
    out = place_artifact_file_members(tmp_path, [])
    assert out["placed"] == 0 and out["skipped"] == 0
    assert out["refused"] == [] and out["missing"] == []


# --------------------------------------------------------------------------- #
# THE HOSTILE MANIFEST -- every path-bearing field, on BOTH paths
# --------------------------------------------------------------------------- #
def _tamper(dest: Path, **fields) -> None:
    """Edit the manifest WITHOUT re-signing. The guard runs before the signature check by
    design -- a name is refused for being a traversal, not for failing a signature anyone
    could have produced -- so the tamper does not need to be plausible to be a real test."""
    p = dest / MANIFEST_NAME
    m = json.loads(p.read_text(encoding="utf-8"))
    m["file_members"] = [
        {
            "name": "blobs/wiki_dumps/enwiki/pages.bz2",
            "category": "wiki_dumps",
            "rel": "enwiki/pages.bz2",
            **fields,
        }
    ]
    p.write_text(json.dumps(m), encoding="utf-8")


HOSTILE = [
    pytest.param({"rel": "../../../../etc/cron.d/oo"}, id="rel-traversal"),
    pytest.param({"rel": "/etc/cron.d/oo"}, id="rel-absolute"),
    pytest.param({"rel": "..\\..\\windows\\system32\\x"}, id="rel-backslash"),
    pytest.param({"rel": "C:/windows/x"}, id="rel-drive"),
    pytest.param({"rel": ""}, id="rel-empty"),
    pytest.param({"name": "../../../../etc/passwd"}, id="name-traversal"),
    pytest.param({"category": "../.."}, id="category-traversal"),
    pytest.param({"category": "keys"}, id="category-unknown"),
    pytest.param({"category": ""}, id="category-empty"),
]


@pytest.mark.parametrize("fields", HOSTILE)
def test_a_hostile_file_member_is_refused_on_the_restore_path(tmp_path, stub_items, fields):
    dest = tmp_path / "d"
    _backup(tmp_path, dest, include_blobs=["wiki_dumps"])
    _tamper(dest, **fields)
    with pytest.raises(VolumeError) as exc:
        read_stream_backup(dest, "pw", staging_root=tmp_path / "stage")
    assert "signature" not in str(exc.value), (
        "refused for the path, not for a signature anyone could have produced"
    )


@pytest.mark.parametrize("fields", HOSTILE)
def test_a_hostile_file_member_is_refused_on_the_verify_path(tmp_path, stub_items, fields):
    """The 2026-07-10 lesson names BOTH paths, because a verify that reads a field a
    restore would refuse invites the operator to trust the artifact first."""
    dest = tmp_path / "d"
    _backup(tmp_path, dest, include_blobs=["wiki_dumps"])
    _tamper(dest, **fields)
    with pytest.raises(VolumeError):
        verify_stream_backup(dest, "pw")


@pytest.mark.parametrize(
    ("entry", "why"),
    [
        pytest.param({"name": "m", "rel": "../x"}, "unsafe rel", id="rel-traversal"),
        pytest.param({"name": "m", "rel": "/etc/x"}, "unsafe rel", id="rel-absolute"),
        pytest.param({"name": "m", "rel": ""}, "empty rel", id="rel-empty"),
        # `name` is joined onto STAGING to find the bytes, so an unguarded one is an
        # arbitrary READ copied into the live directory under an innocuous rel. It is
        # refused for being an unsafe NAME -- not for anything about the category, which
        # is fine here: a refusal that names the wrong field sends a reader hunting it.
        pytest.param({"name": "../../etc/passwd", "rel": "x"}, "unsafe name", id="name-traversal"),
        pytest.param({"name": "", "rel": "x"}, "empty name", id="name-empty"),
    ],
)
def test_the_placement_function_guards_its_own_inputs_and_names_the_real_reason(
    tmp_path, entry, why
):
    """It is public, and its docstring says a guard reached from somewhere else is not a
    guard on this function -- so it must hold without the manifest check upstream."""
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / "m").write_bytes(b"x")
    live = tmp_path / "live"
    out = place_artifact_file_members(
        tmp_path / "staging",
        [{"category": "wiki_dumps", **entry}],
        targets={"wiki_dumps": live},
    )
    assert out["placed"] == 0
    assert out["refused"][0]["why"] == why
    assert not live.exists() or not any(live.rglob("*"))


def test_a_symlinked_live_directory_cannot_carry_a_placement_out_of_its_root(tmp_path):
    """The containment BELT, on the only input shape that reaches it: a rel with no `..`
    and no absolute prefix, under a root whose subdirectory is a symlink pointing away.
    The field guards above cannot see this -- only resolving the composed path can -- and
    a belt that is never asserted is a comment. `is_relative_to`, never a string prefix,
    because a sibling directory shares one."""
    outside = tmp_path / "live-old"  # shares the prefix, is NOT inside
    outside.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    (live / "sub").symlink_to(outside, target_is_directory=True)
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / "m").write_bytes(b"PLANTED")

    out = place_artifact_file_members(
        tmp_path / "staging",
        [{"name": "m", "category": "wiki_dumps", "rel": "sub/x"}],
        targets={"wiki_dumps": live},
    )
    assert out["placed"] == 0
    assert out["refused"] == [
        {"category": "wiki_dumps", "rel": "sub/x", "why": "outside its category"}
    ]
    assert not (outside / "x").exists(), "nothing may be written outside the category root"


def test_an_unknown_category_at_placement_is_refused_not_joined(tmp_path):
    (tmp_path / "staging").mkdir()
    out = place_artifact_file_members(
        tmp_path / "staging",
        [{"name": "m", "category": "keys", "rel": "signing.key"}],
        targets={"wiki_dumps": tmp_path / "live"},
    )
    assert out["placed"] == 0
    assert out["refused"][0]["why"] == "unknown category"


def test_no_restore_double_describes_an_artifact_the_engine_could_not_produce():
    """A ``read_volume_backup`` stubbed to ``object()`` is a double with no fields.

    This one is here because it already cost a red suite: six doubles in
    ``test_volume_job.py`` were fixed when ``file_members`` was added, three more in
    ``test_import_phase_progress.py`` were not (they live in a file about progress
    counters, which no grep for "backup" reaches), and a fourth in
    ``test_restore_refusal_names_the_actor.py`` stayed green only because its own double
    raises before the job reads that far -- so it would have bitten the NEXT field
    instead. The tempting repair is a ``getattr`` default in ``_run_restore``; that is a
    permanent hole in production to accommodate a fixture, since every real artifact has
    the field.

    So the rule is structural: patch it with the real dataclass
    (``tests.backup_helper.staged_artifact``), never with a bare object. Comment-stripped,
    because this docstring necessarily contains the pattern it forbids.
    """
    import re

    root = Path(__file__).resolve().parent
    offenders = []
    seen = 0
    for path in sorted(root.glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        # Drop docstrings and comments: an explanation of the rule quotes the rule.
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)
        src = re.sub(r"^\s*#.*$", "", src, flags=re.M)
        for line in src.splitlines():
            if "read_volume_backup" not in line or "setattr" not in line:
                continue
            seen += 1
            if re.search(r":\s*object\(\)", line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert seen >= 5, (
        "this guard found almost no read_volume_backup doubles, so it is not reading what "
        "it claims to -- check the pattern before trusting the green"
    )
    assert not offenders, (
        "a restore double must be a real StagedArtifact "
        "(tests.backup_helper.staged_artifact), not object():\n  " + "\n  ".join(offenders)
    )
