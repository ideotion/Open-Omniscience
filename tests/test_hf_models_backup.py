"""The Hugging Face weights cache rides the large-data backup.

FIELD REPORT 2026-08-11: "While looking at a backup file, i noticed vLLM models were
not saved, only ollama models." True, and by construction: ``collect_model_items``
enumerates the Ollama store and nothing else, so on a machine that serves with vLLM the
backup carried no weights — and reported success, because from its own point of view it
had copied everything it knew about. The same shape as the 2026-08-11 Ollama-store
lesson one store over.

The fix is mostly about SIZE and SAFETY rather than about finding the files. An HF repo
keeps its bytes once in ``blobs/<sha>`` and reaches them through symlinks under
``snapshots/<rev>/``; copying both would store every multi-GB weight twice, and storing
the links would collide with the restore's flat refusal of symlinks (a 2026-07-25 fix
for a live-reproduced arbitrary-file copy). So: copy the snapshot entries, resolving the
link, and skip ``blobs/``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from pathlib import Path

from src.backup.folder_backup import (
    _CATEGORIES,
    collect_hf_model_items,
    restore_folder_backup,
    write_folder_backup,
)

_BLOB = b"w" * 4096  # stands in for a weight file: big enough that doubling would show


def _hf_cache(root: Path, *, repo: str = "models--org--tiny", rev: str = "abc123") -> Path:
    """A cache with HF's real shape: bytes once in blobs/, reached by symlink."""
    hub = root / "hub" / repo
    (hub / "blobs").mkdir(parents=True)
    (hub / "snapshots" / rev).mkdir(parents=True)
    (hub / "refs").mkdir(parents=True)
    (hub / "refs" / "main").write_text(rev, encoding="utf-8")
    for name, body in (("model.safetensors", _BLOB), ("config.json", b'{"a":1}')):
        sha = f"sha256-{name}"
        (hub / "blobs" / sha).write_bytes(body)
        (hub / "snapshots" / rev / name).symlink_to(Path("..") / ".." / "blobs" / sha)
    return root


def test_the_weights_vllm_serves_are_collected_at_all(tmp_path) -> None:
    items = collect_hf_model_items(_hf_cache(tmp_path / "hf"))
    rels = {it.rel for it in items}
    assert "hub/models--org--tiny/snapshots/abc123/model.safetensors" in rels
    assert "hub/models--org--tiny/refs/main" in rels, (
        "without refs/ the restored cache has weights nothing resolves to"
    )
    assert all(it.category == "hf_models" for it in items)


def test_the_bytes_are_carried_exactly_once(tmp_path) -> None:
    """THE LOAD-BEARING ONE. blobs/ and snapshots/ hold the same bytes; taking both
    would double a multi-GB backup, and _atomic_copy follows the link so it really
    would be bytes, not links."""
    items = collect_hf_model_items(_hf_cache(tmp_path / "hf"))
    assert not any("/blobs/" in it.rel for it in items), "blobs/ is reached through the snapshot"
    weight = [it for it in items if it.rel.endswith("model.safetensors")]
    assert len(weight) == 1
    assert weight[0].size == len(_BLOB), "the size is the TARGET's, which is what gets copied"
    assert sum(it.size for it in items) < 2 * len(_BLOB), "one copy of the weights, not two"


def test_a_dangling_link_is_dropped_rather_than_backed_up_as_nothing(tmp_path) -> None:
    """An interrupted fetch leaves the link and not the blob. Copying it would fail
    mid-run; counting it would inflate the preflight against a file that is not there."""
    root = _hf_cache(tmp_path / "hf")
    snap = root / "hub" / "models--org--tiny" / "snapshots" / "abc123"
    (snap / "ghost.bin").symlink_to(Path("..") / ".." / "blobs" / "sha256-missing")
    assert not any(it.rel.endswith("ghost.bin") for it in collect_hf_model_items(root))


def test_partial_and_lock_files_are_skipped(tmp_path) -> None:
    root = _hf_cache(tmp_path / "hf")
    hub = root / "hub" / "models--org--tiny"
    (hub / "snapshots" / "abc123" / "half.bin.incomplete").write_bytes(b"x")
    (hub / "refs" / "main.lock").write_bytes(b"")
    rels = {it.rel for it in collect_hf_model_items(root)}
    assert not any(r.endswith((".incomplete", ".lock")) for r in rels)


def test_an_absent_cache_is_empty_not_an_error(tmp_path) -> None:
    assert collect_hf_model_items(tmp_path / "nothing-here") == []


def test_a_round_trip_restores_a_loadable_cache(tmp_path) -> None:
    """End to end through the REAL writer and restorer: what comes back must be what
    the app's own probe calls cached — the config file present under snapshots/<rev>/,
    reachable without a symlink anywhere in the restored tree."""
    src = _hf_cache(tmp_path / "hf")
    dest, live = tmp_path / "drive", tmp_path / "restored"
    write_folder_backup(dest, collect_hf_model_items(src))
    out = restore_folder_backup(dest, categories=["hf_models"], targets={"hf_models": live})
    assert out["restored"] > 0 and out["refused_symlinks"] == 0

    snap = live / "hub" / "models--org--tiny" / "snapshots" / "abc123"
    assert (snap / "config.json").is_file(), "vLLM's own stated precondition"
    assert (snap / "model.safetensors").read_bytes() == _BLOB
    refs = live / "hub" / "models--org--tiny" / "refs" / "main"
    assert refs.read_text(encoding="utf-8") == "abc123"
    # Plain files, not links: the restore refuses symlinks outright, so a design that
    # needed them would have been refused by its own safety guard.
    assert not any(p.is_symlink() for p in live.rglob("*"))


def test_the_default_restore_target_is_where_vllm_will_look(tmp_path, monkeypatch) -> None:
    """A caller that names no target must land the weights where the server is spawned
    pointed at — not beside the Ollama store, and not nowhere."""
    import src.llm.model_store as ms

    src = _hf_cache(tmp_path / "hf")
    dest, live = tmp_path / "drive", tmp_path / "app-hf"
    write_folder_backup(dest, collect_hf_model_items(src))
    monkeypatch.setattr(ms, "hf_home", lambda: live)
    out = restore_folder_backup(dest, categories=["hf_models"])  # no targets=
    assert out["restored"] > 0
    assert (live / "hub" / "models--org--tiny" / "snapshots" / "abc123" / "config.json").is_file()


def test_the_category_is_wired_end_to_end() -> None:
    """The enumerator existing is not the feature; every seam that decides what a
    backup contains has to know the category, or it is collected and never copied."""
    import src.api.backup_v2 as b2
    from src.backup.folder_backup import collect_items

    assert "hf_models" in _CATEGORIES
    assert "hf_models" in b2._FOLDER_CATEGORIES
    assert "hf_models" in b2._folder_categories(None), "the default set must include it"
    assert "include_hf" in collect_items.__code__.co_varnames

    src_api = Path(b2.__file__).read_text(encoding="utf-8")
    src_fb = Path("src/backup/folder_backup.py").read_text(encoding="utf-8")
    # The manager's own start() is the path a real backup takes; the API plan is what
    # the preflight quotes. Both must pass the flag, or the tickbox is decorative.
    assert src_api.count('include_hf="hf_models" in cats') == 1
    assert src_fb.count('include_hf="hf_models" in cats') == 1


def test_unticking_models_excludes_the_weights(tmp_path, monkeypatch) -> None:
    """The other direction: a category the operator did not ask for must not add
    several GB to their backup."""
    import src.backup.folder_backup as fb

    monkeypatch.setattr(fb, "collect_model_items", lambda *_a, **_k: [])
    monkeypatch.setattr(fb, "collect_hf_model_items", lambda *_a, **_k: [object()])
    assert fb.collect_items(include_wiki=False, include_osm=False,
                            include_models=False, include_hf=False) == []
    assert len(fb.collect_items(include_wiki=False, include_osm=False,
                                include_models=False, include_hf=True)) == 1
