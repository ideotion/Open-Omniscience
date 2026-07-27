"""Per-stage timing + the enlarged import connection cache (field-feedback
Session A §4, "instrument first, own the machine, then optimize").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers: merge_corpus's optional cache_mb tuning (never changes merge results,
never breaks a merge if the PRAGMA itself fails), and run_restore's
report["timings"] -- present on every return path (refused, preview,
committed), the real per-merge-step breakdown, and the load-bearing
exception-safety property (a real failure inside an instrumented stage
propagates UNCHANGED, never swallowed by the timer).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Article, Base, Source

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.0.9",
    "alembic_rev": "head",
    "manifest": None,
}


def _build_corpus(path: Path, sources: list[dict], articles: list[dict]) -> None:
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with sessionmaker(bind=engine, future=True)() as s:
        dom_to_id: dict[str, int] = {}
        for spec in sources:
            src = Source(name=spec.get("name", spec["domain"]), domain=spec["domain"])
            s.add(src)
            s.flush()
            dom_to_id[spec["domain"]] = src.id
        for spec in articles:
            s.add(
                Article(
                    url=spec["url"], canonical_url=spec.get("canonical_url", spec["url"]),
                    source_id=dom_to_id[spec["source_domain"]], title=spec.get("title", spec["hash"]),
                    content=spec["content"], hash=spec["hash"], language="en", created_at=now,
                )
            )
        s.commit()
    engine.dispose()


# --------------------------------------------------------------------------- #
# merge_corpus(cache_mb=...) — the "own the machine" resource-tuning knob.
# --------------------------------------------------------------------------- #


def test_cache_mb_never_changes_the_merge_result(tmp_path):
    art = {"url": "https://s.example/a", "source_domain": "s.example", "hash": "hCACHE",
           "content": "incoming"}
    working_a, staged_a = tmp_path / "wa.db", tmp_path / "sa.db"
    working_b, staged_b = tmp_path / "wb.db", tmp_path / "sb.db"
    _build_corpus(working_a, [{"domain": "s.example"}], [])
    _build_corpus(staged_a, [{"domain": "s.example"}], [art])
    _build_corpus(working_b, [{"domain": "s.example"}], [])
    _build_corpus(staged_b, [{"domain": "s.example"}], [dict(art)])

    counts_a, _ = merge_corpus(staged_a, working_a, _BATCH_META, cache_mb=None)
    counts_b, _ = merge_corpus(staged_b, working_b, _BATCH_META, cache_mb=256)
    assert counts_a == counts_b  # a pure resource knob -- identical outcome either way


def test_cache_mb_pragma_is_traced_on_the_connection(tmp_path, monkeypatch):
    """A behavioural proof (not just a source-grep): the exact PRAGMA the
    knob's docstring promises is really executed on the merge connection --
    via sqlite3's own trace callback, so no fragile attribute-patching of a
    C-extension connection object is needed."""
    import src.database.connect as connect_mod

    real_connect = connect_mod.connect
    traced: list[str] = []

    def _spy_connect(*a, **kw):
        con = real_connect(*a, **kw)
        con.set_trace_callback(traced.append)
        return con

    monkeypatch.setattr(connect_mod, "connect", _spy_connect)

    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    _build_corpus(working, [{"domain": "s.example"}], [])
    _build_corpus(staged, [{"domain": "s.example"}], [])

    merge_corpus(staged, working, _BATCH_META, cache_mb=256)
    assert any("cache_size=-262144" in t for t in traced)  # -256 * 1024 KiB

    traced.clear()
    merge_corpus(staged, working, _BATCH_META, cache_mb=None)
    assert not any("cache_size" in t for t in traced)  # no knob given -> no PRAGMA at all


def test_a_broken_cache_pragma_never_breaks_the_merge(tmp_path, monkeypatch):
    """'best-effort (a tuning-PRAGMA failure must never break a merge)' --
    proven, not just asserted: a connection whose cache_size PRAGMA raises
    must still let the merge complete normally."""
    import src.database.connect as connect_mod

    real_connect = connect_mod.connect

    class _BoomOnCachePragma:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a, **kw):
            if "cache_size" in sql:
                raise RuntimeError("PRAGMA rejected by this build")
            return self._real.execute(sql, *a, **kw)

        def __getattr__(self, name):
            return getattr(self._real, name)

    def _spy_connect(*a, **kw):
        return _BoomOnCachePragma(real_connect(*a, **kw))

    monkeypatch.setattr(connect_mod, "connect", _spy_connect)

    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    art = {"url": "https://s.example/a", "source_domain": "s.example", "hash": "hBOOM",
           "content": "incoming"}
    _build_corpus(working, [{"domain": "s.example"}], [])
    _build_corpus(staged, [{"domain": "s.example"}], [art])

    counts, _ = merge_corpus(staged, working, _BATCH_META, cache_mb=256)
    assert counts["articles"]["new"] == 1  # the merge succeeded despite the PRAGMA failing


# --------------------------------------------------------------------------- #
# run_restore's report["timings"] -- through the REAL sync REST endpoints
# (mirrors tests/test_restore_preview_robust_errors.py's proven pattern: a
# real write_backup_v2 artifact, POSTed back to the app's own preview/commit
# endpoints -- fast, in-process, exercises the actual production call sites).
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _build_backup(passphrase=None) -> bytes:
    import os
    import tempfile

    from src.backup.artifact import write_backup_v2

    fd, tmp = tempfile.mkstemp(suffix=".oobak")
    os.close(fd)
    dest = Path(tmp)
    dest.unlink(missing_ok=True)
    write_backup_v2(dest, passphrase=passphrase)
    try:
        return dest.read_bytes()
    finally:
        dest.unlink(missing_ok=True)


def _preview(client, blob):
    return client.post(
        "/api/backup/v2/restore/preview",
        files={"file": ("b.oobak", blob, "application/octet-stream")},
    )


def _commit(client, blob):
    return client.post(
        "/api/backup/v2/restore/commit",
        files={"file": ("b.oobak", blob, "application/octet-stream")},
    )


_EXPECTED_PREVIEW_STAGES = {
    "stage_a:decrypt", "stage_a:extract_and_verify",
    "prepare_staged", "snapshot_working_copy", "merge", "verify",
}
_EXPECTED_COMMIT_ONLY_STAGES = {
    "corpus_delta_before", "pre_restore_snapshot", "side_files_and_custody",
    "report_json_write", "swap", "corpus_delta_after", "corpus_epoch_bump",
    "event_mirror_refresh", "reindex", "quarantine_scan", "work_induced_tally",
    "prune_snapshots",
}


def test_preview_report_carries_the_stages_that_actually_ran(client):
    blob = _build_backup()
    resp = _preview(client, blob)
    assert resp.status_code == 200
    report = resp.json()
    assert report["committed"] is False

    timings = report["timings"]
    # the 14 merge_step:<name> entries also ride along (asserted separately by
    # test_the_14_merge_steps_each_get_their_own_named_timing) -- subset check here.
    assert _EXPECTED_PREVIEW_STAGES <= set(timings["stages"])
    assert not (set(timings["stages"]) & _EXPECTED_COMMIT_ONLY_STAGES)  # preview stops before commit
    assert timings["wall_s"] > 0
    for name in _EXPECTED_PREVIEW_STAGES:
        assert timings["stages"][name] >= 0  # never a fabricated negative


def test_an_encrypted_artifacts_decrypt_stage_is_genuinely_measured(client):
    """The unencrypted _build_backup() cases above still time 'decrypt' (a
    real, honest near-zero -- there was nothing to decrypt), but this test
    proves the OTHER branch: a genuinely OOENC1-wrapped upload's decrypt
    step really runs (and the preview still succeeds with the right
    passphrase)."""
    blob = _build_backup(passphrase="a-real-test-passphrase-123")
    resp = client.post(
        "/api/backup/v2/restore/preview",
        data={"passphrase": "a-real-test-passphrase-123"},
        files={"file": ("b.oobak", blob, "application/octet-stream")},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["encrypted"] is True
    assert report["timings"]["stages"]["stage_a:decrypt"] >= 0


def test_committed_restore_report_carries_every_stage(client):
    blob = _build_backup()
    resp = _commit(client, blob)
    assert resp.status_code == 200
    report = resp.json()
    assert report["committed"] is True

    timings = report["timings"]
    got = set(timings["stages"])
    assert _EXPECTED_PREVIEW_STAGES <= got  # the preview-side stages ran too
    assert _EXPECTED_COMMIT_ONLY_STAGES <= got
    assert timings["wall_s"] > 0
    # honest total: never LESS than any single recorded stage.
    assert timings["wall_s"] >= max(timings["stages"].values())


def test_the_14_merge_steps_each_get_their_own_named_timing(client):
    blob = _build_backup()
    report = _preview(client, blob).json()
    step_keys = [k for k in report["timings"]["stages"] if k.startswith("merge_step:")]
    # The exact 14 step names merge_corpus's own `steps` tuple defines
    # (src/backup/merge.py) -- proves per-step timing rides the EXISTING
    # progress_cb wrapping, with zero change to merge_corpus's internals.
    assert len(step_keys) == 14
    for k in step_keys:
        assert report["timings"]["stages"][k] >= 0


def test_a_refused_preview_still_carries_its_partial_timings(client, monkeypatch):
    """Even the earliest-possible return path (post-merge verification
    failed) must carry timings for the stages that DID run before the
    refusal -- never an empty/missing report["timings"]."""
    import src.backup.merge as merge_mod

    def _fake_verify(*a, **kw):
        return {"ok": False, "problems": ["forced for this test"]}

    monkeypatch.setattr(merge_mod, "verify_copy", _fake_verify)
    blob = _build_backup()
    resp = _preview(client, blob)
    assert resp.status_code == 200
    report = resp.json()
    assert "refused" in report
    assert _EXPECTED_PREVIEW_STAGES <= set(report["timings"]["stages"])


def test_an_exception_inside_an_instrumented_stage_still_propagates(client, monkeypatch):
    """THE load-bearing property, proven at the run_restore level (not just
    the StageTimings unit tests): wrapping a stage in the timer must NEVER
    turn a real failure into a silent success. verify_copy raising is
    reported as the real error, never swallowed into a fabricated 'ok'."""
    import src.backup.merge as merge_mod

    def _boom(*a, **kw):
        raise RuntimeError("a genuine verification crash")

    monkeypatch.setattr(merge_mod, "verify_copy", _boom)
    blob = _build_backup()
    resp = _preview(client, blob)
    assert resp.status_code == 500
    assert "a genuine verification crash" in resp.json()["detail"]


def test_a_prune_snapshots_failure_never_blocks_persisting_the_import_report(client, monkeypatch):
    """A skeptic-pass finding (2026-07-24): unlike every OTHER post-commit step
    in run_restore (corpus_delta_after, corpus_epoch_bump, event_mirror_
    refresh, reindex, quarantine_scan, work_induced_tally -- all wrapped in a
    try/except that logs and continues, "never undo a committed, additive
    restore"), _prune_snapshots() was left unguarded. This stage-timing
    rework also moved it to run BEFORE persist_import_report() (it used to
    run last) -- so an unguarded prune failure would have silently REGRESSED
    the S3.5 downloadable-report feature by skipping persist_import_report()
    entirely whenever pruning happened to fail. Proves the fix: a prune
    failure never propagates, never turns a committed restore into a
    reported failure, and never blocks the report from being persisted."""
    import src.backup.merge as merge_mod
    from src.backup.artifact import cleanup_staging, read_artifact

    def _boom(*a, **kw):
        raise OSError("simulated snapshot-directory permission failure")

    monkeypatch.setattr(merge_mod, "_prune_snapshots", _boom)
    blob = _build_backup()
    staged = read_artifact(blob, None, None)
    try:
        report = merge_mod.run_restore(staged, commit=True)
    finally:
        cleanup_staging(staged)

    assert report["committed"] is True
    assert "pruned_snapshots" not in report  # honest: never fabricate what was removed
    assert "persisted_report_path" in report  # the fix: a prune failure must not skip this
    assert report["timings"]["stages"]["prune_snapshots"] >= 0  # the stage is still timed


def test_stage_progress_cb_pings_fire_for_every_stage_in_order(client):
    """'Progress everywhere' (§4 item 2): a live phase ping fires the instant
    EACH stage begins -- in the same order the stages actually run, covering
    B/D/E/G (the stages with no callback of their own), not just the merge/
    reindex phases that already had one. Calls run_restore DIRECTLY (not
    through the endpoint, which doesn't pass stage_progress_cb yet -- that's
    the volume-job path's own, separately-tested wiring)."""
    from src.backup.artifact import cleanup_staging, read_artifact
    from src.backup.merge import run_restore

    seen: list[str] = []
    blob = _build_backup()
    staged = read_artifact(blob, None, None)
    try:
        run_restore(staged, commit=True, stage_progress_cb=seen.append)
    finally:
        cleanup_staging(staged)

    # Every stage that actually ran on a committed restore, in call order.
    assert seen == [
        "prepare_staged", "snapshot_working_copy", "merge", "verify",
        "corpus_delta_before", "pre_restore_snapshot", "side_files_and_custody",
        "report_json_write", "swap", "corpus_delta_after", "corpus_epoch_bump",
        "event_mirror_refresh", "reindex", "quarantine_scan", "work_induced_tally",
        "prune_snapshots",
    ]


def test_merge_cache_mb_is_threaded_through_run_restore(client, monkeypatch):
    """run_restore's merge_cache_mb parameter reaches merge_corpus's cache_mb
    -- proven end to end, not just by reading the source."""
    import src.backup.merge as merge_mod

    seen = {}
    real_merge_corpus = merge_mod.merge_corpus

    def _spy(*a, **kw):
        seen["cache_mb"] = kw.get("cache_mb")
        return real_merge_corpus(*a, **kw)

    monkeypatch.setattr(merge_mod, "merge_corpus", _spy)
    blob = _build_backup()
    # Call the pure function directly (not through the endpoint, which
    # doesn't set merge_cache_mb yet -- that wiring is exercised separately
    # by the volume-job "own the machine" tests).
    from src.backup.artifact import cleanup_staging, read_artifact
    from src.backup.merge import run_restore

    staged = read_artifact(blob, None, None)
    try:
        run_restore(staged, commit=False, merge_cache_mb=777)
    finally:
        cleanup_staging(staged)
    assert seen["cache_mb"] == 777


# --------------------------------------------------------------------------- #
# W5 (2026-07-26 hardware diagnostics): the pre-restore snapshot age sweep.
# The count-based half (_prune_snapshots, already shipped) is exercised
# end-to-end through the real commit endpoint here; the time-driven half
# (prune_pre_restore_snapshots_by_age) is pure-filesystem-unit-tested in
# tests/test_pre_restore_snapshot_sweep.py.
# --------------------------------------------------------------------------- #


def test_repeated_commits_prune_down_to_the_newest_keep_n(client, monkeypatch):
    """Codifies existing, previously-untested behaviour at n > _SNAPSHOT_KEEP:
    _prune_snapshots() only ever fires as a side effect of a LATER restore, so
    committing more than _SNAPSHOT_KEEP times must converge to exactly
    _SNAPSHOT_KEEP retained snapshots, never fewer (a real bug would either
    leave them all or over-prune).

    The snapshot filename's timestamp has SECOND granularity
    (pre-restore-<ts>.db); two commits landing in the same wall-clock second
    would collide on ONE filename (snapshot_preserving overwriting the
    earlier one) and understate the count -- a test-timing artifact only
    (production restores within the same second of each other are not a
    real-world concern), so freeze+advance the clock by a whole second per
    commit for a deterministic, collision-free filename sequence."""
    from datetime import timedelta

    import src.backup.merge as merge_mod
    from src.paths import data_dir

    class _AdvancingDatetime(datetime):
        _base = datetime.now(UTC)
        _step = 0

        @classmethod
        def now(cls, tz=None):
            cls._step += 1
            return cls._base + timedelta(seconds=cls._step)

    monkeypatch.setattr(merge_mod, "datetime", _AdvancingDatetime)

    blob = _build_backup()
    for _ in range(merge_mod._SNAPSHOT_KEEP + 1):
        resp = _commit(client, blob)
        assert resp.status_code == 200
    snaps = sorted(data_dir().glob("pre-restore-*.db"))
    assert len(snaps) == merge_mod._SNAPSHOT_KEEP


def test_a_committed_restore_never_deletes_its_own_fresh_snapshot(client):
    """A single commit's own just-created snapshot must always survive that
    SAME commit's prune stage -- it is always the newest, so _prune_snapshots()
    (keep-newest-N) can never remove it. Starts from a clean slate (this
    session's data_dir() is shared across this whole test file, and an
    earlier test above deliberately monkeypatches an ADVANCED clock to avoid
    its OWN filename collisions -- those synthetic future timestamps could
    otherwise sort ahead of this test's real-clock one and make it look
    'not the newest'; clearing first makes this test's own property
    independent of any other test's clock/leftover state)."""
    from src.paths import data_dir

    for stale in data_dir().glob("pre-restore-*.db"):
        stale.unlink()

    resp = _commit(client, _build_backup())
    assert resp.status_code == 200
    report = resp.json()
    assert Path(report["pre_restore_snapshot"]).exists()
    fresh_name = Path(report["pre_restore_snapshot"]).name
    assert fresh_name not in report["pruned_snapshots"]


def test_the_snapshot_is_registered_active_before_the_write_starts_not_after(client, monkeypatch):
    """Skeptic-found (data-loss + config-abuse lenses, 2026-07-26/27, LIVE
    reproduced against real production code): the OLD code registered
    ``active_staging(snapshot)`` only AFTER ``snapshot_preserving()`` had
    ALREADY written the file -- leaving a window (measured, against a real
    multi-hundred-MB corpus: the entire write duration) where a concurrent
    off-peak sweep (``prune_pre_restore_snapshots_by_age``) could see the
    file as unregistered-and-old-enough and delete it mid-write. This test's
    own synthetic corpus is tiny and writes essentially instantly, so
    checking file EXISTENCE after a pause would be meaningless/racy either
    way -- instead this asserts the mechanism directly: ``is_active_staging``
    is already True the instant ``snapshot_preserving`` is CALLED, before it
    is even allowed to proceed to the real write (paused here via a
    monkeypatch), proving registration happens strictly before the write
    starts rather than only after it returns."""
    import threading

    import src.backup.merge as merge_mod
    import src.database.connect as connect_mod
    from src.backup.stream_backup import is_active_staging

    real_snapshot_preserving = connect_mod.snapshot_preserving
    started = threading.Event()
    release = threading.Event()
    seen_paths: list[Path] = []

    def _paused_snapshot_preserving(src, dst, *a, **kw):
        # Only the pre_restore_snapshot stage's call targets a
        # "pre-restore-*.db" destination (the snapshot_working_copy stage's
        # call targets "working.db" and must run at full speed).
        if "pre-restore-" in str(dst):
            seen_paths.append(Path(dst))
            started.set()
            release.wait(timeout=5)
        return real_snapshot_preserving(src, dst, *a, **kw)

    monkeypatch.setattr(connect_mod, "snapshot_preserving", _paused_snapshot_preserving)

    result: dict = {}

    def _run_commit():
        result["resp"] = _commit(client, _build_backup())

    t = threading.Thread(target=_run_commit)
    t.start()
    try:
        assert started.wait(timeout=5), "the pre_restore_snapshot stage never started"
        assert seen_paths, "the patched snapshot_preserving was never reached"

        # THE property under test: registered as active BEFORE the real
        # write is even allowed to proceed -- not merely "eventually, after
        # the write finishes" (the old, buggy ordering).
        assert is_active_staging(seen_paths[0]), (
            "the snapshot must be registered as active BEFORE "
            "snapshot_preserving() is even called, not only after it returns"
        )
        # And the most aggressive possible concurrent sweep still can't
        # report it removed while paused (a not-yet-written file is
        # trivially never glob-matched either way, but this also proves the
        # sweep doesn't misbehave while racing an in-flight registration).
        for _ in range(20):
            removed = merge_mod.prune_pre_restore_snapshots_by_age(max_age_hours=0)
            assert seen_paths[0].name not in removed
    finally:
        release.set()
        t.join(timeout=10)
    assert not t.is_alive()
    resp = result["resp"]
    assert resp.status_code == 200
    report = resp.json()
    assert Path(report["pre_restore_snapshot"]).exists()


def test_prune_snapshots_never_deletes_a_sibling_restores_active_snapshot(client, monkeypatch):
    """Skeptic-found (race-concurrency lens, 2026-07-26, LIVE reproduced): the
    PRE-EXISTING count-based ``_prune_snapshots`` (keep-newest-N, called
    unconditionally on EVERY commit) had NO awareness of ``active_staging``
    at all -- so a THIRD/FOURTH overlapping restore's own prune call could
    delete an EARLIER, still-in-flight restore's registered snapshot the
    moment enough newer snapshots existed to push it past ``keep``. Proves
    the fix directly against ``_prune_snapshots`` (not the whole HTTP path,
    for a fast/deterministic repro): an active snapshot survives being
    pruned even when it is the OLDEST of ``keep + 1`` candidates."""
    import src.backup.merge as merge_mod
    from src.backup.stream_backup import active_staging
    from src.paths import data_dir

    for stale in data_dir().glob("pre-restore-*.db"):
        stale.unlink()

    def _make(age_hours: float) -> Path:
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(hours=age_hours)).strftime("%Y%m%dT%H%M%SZ")
        p = data_dir() / f"pre-restore-{ts}.db"
        p.write_bytes(b"fake corpus bytes")
        return p

    active_and_oldest = _make(age_hours=10)  # would be pruned first under keep=3
    _make(age_hours=3)
    _make(age_hours=2)
    _make(age_hours=1)  # 4 total snapshots -- one MUST be pruned under keep=3

    with active_staging(active_and_oldest):
        removed = merge_mod._prune_snapshots(keep=3)
        assert active_and_oldest.name not in removed
        assert active_and_oldest.exists()
    # Released -- now fair game on its own merits, exactly like the age sweep.
    removed_after = merge_mod._prune_snapshots(keep=3)
    assert active_and_oldest.name in removed_after
    assert not active_and_oldest.exists()
