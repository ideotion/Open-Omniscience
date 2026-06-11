"""
The DB-reliability TORTURE SUITE -- the batch's acceptance metric.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling (2026-06-11): "if it's not entirely reliable, it should not
exist" -- a failed test here BLOCKS the merge-restore feature. Scenarios per
docs/design/DB_RELIABILITY_02_DESIGN.md §7:

    T1  interrupted import mid-merge  -> live DB byte-identical
    T2  duplicate floods              -> idempotent, zero growth
    T3  wrong passphrase              -> loud, zero partial state
    T4  cross-version restore         -> staged upgrade; floor/alien refusals BY NAME
    T5  plaintext<->encrypted round trips -> logically identical corpus
    T6  divergent corpora merge       -> FK remap + conflicts reported + local wins
    T7  crash AT the swap boundary    -> live DB byte-identical
    T8  FTS truth after merge         -> planted token findable, counts reconcile
    T9  custody chains                -> verified-not-trusted, never spliced
    T10 settings sanctity             -> merge never alters local settings

Every scenario runs in subprocesses with their own OO_DATA_DIR, because the
engine binds at import time and half the scenarios end in SIGKILL.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"


def _run(data_dir: Path, *args: str, expect_kill: bool = False) -> dict:
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=180,
    )
    if expect_kill:
        assert proc.returncode == -9, (
            f"expected SIGKILL, got rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        )
        return {}
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    last = proc.stdout.strip().splitlines()[-1]
    return json.loads(last)


def _file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def corpora(tmp_path_factory):
    """Corpus A (the live machine), corpus B (the foreign machine) + B's artifact."""
    root = tmp_path_factory.mktemp("torture")
    a, b = root / "A", root / "B"
    a.mkdir(), b.mkdir()
    art = root / "corpusB.oobak.ooenc"
    out_b = _run(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-torture",
                 "--custody", "ok")
    assert out_b.get("artifact")
    _run(a, "build", "A", "--custody", "ok")
    return {"A": a, "B": b, "artifact": art, "root": root}


# --------------------------------------------------------------------------- #
#  T6 + T8 + T10: the divergent merge, the heart
# --------------------------------------------------------------------------- #
def test_t6_divergent_merge_full(corpora):
    a, art = corpora["A"], corpora["artifact"]
    preview = _run(a, "merge", str(art), "--passphrase", "pw-torture")["report"]
    assert preview["committed"] is False
    assert preview["verification"]["ok"] is True
    assert preview["plan"]["articles"] == {"new": 2, "duplicate": 1, "conflict": 0}
    # The commodity disagreement is REPORTED with both values, local kept (never averaged).
    cp = preview["plan"]["commodity_prices"]
    assert cp["conflict"] == 1 and cp["conflicts"][0]["incoming"] != cp["conflicts"][0]["local"]

    report = _run(a, "merge", str(art), "--passphrase", "pw-torture", "--commit")["report"]
    assert report["committed"] is True
    assert report["verification"]["ok"] is True
    assert report["verification"]["foreign_key_violations"] == 0
    assert report["verification"]["fts_matches_articles"] is True
    # T10: local settings are sacred.
    assert report["side_files"]["state"]["app_settings.json"]["action"] == "kept-local"
    assert (json.loads((a / "app_settings.json").read_text())["theme"]) == "light"
    # Events store unioned; both corpora's unique days present.
    ev = json.loads((a / "calendar_feed_imports.json").read_text())["holidays"]["events"]
    assert {"fp-shared", "fp-A", "fp-B"} <= set(ev)
    assert sorted(ev["fp-shared"]["sources"]) == ["feedA", "feedB"]
    # T8: a token unique to B's corpus is findable through FTS in A afterwards.
    assert _run(a, "fts-find", "unique")["matches"] >= 2
    # Pre-restore snapshot exists for rollback.
    assert Path(report["pre_restore_snapshot"]).exists()


def test_t2_duplicate_flood_is_idempotent(corpora):
    a, art = corpora["A"], corpora["artifact"]
    before = _run(a, "dump")["dump"]
    for _ in range(3):
        rep = _run(a, "merge", str(art), "--passphrase", "pw-torture", "--commit")["report"]
        news = {k: v["new"] for k, v in rep["plan"].items()
                if isinstance(v, dict) and v.get("new")}
        assert news == {}, f"re-merge created rows: {news}"
    assert _run(a, "dump")["dump"] == before


def test_t9_custody_verified_not_trusted(corpora):
    a = corpora["A"]
    state = _run(a, "verify-custody")
    assert state["local_ok"] is True, "local chain must stay intact after merges"
    assert state["imported"] and all(c["verified"] for c in state["imported"])
    # A tampered foreign chain imports as verified=false -- the failure is evidence.
    root = corpora["root"]
    bad_dir = root / "B-tampered"
    bad_dir.mkdir()
    bad_art = root / "tampered.oobak.ooenc"
    _run(bad_dir, "build", "B", "--artifact", str(bad_art), "--passphrase", "pw-torture",
         "--custody", "tampered")
    rep = _run(a, "merge", str(bad_art), "--passphrase", "pw-torture", "--commit")["report"]
    assert rep["custody"]["verified"] is False and rep["custody"]["problems"]
    state2 = _run(a, "verify-custody")
    assert state2["local_ok"] is True
    assert any(not c["verified"] for c in state2["imported"])


# --------------------------------------------------------------------------- #
#  T1 + T7: interruption -- the live DB must be byte-identical afterwards
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="SIGKILL-based crash injection is POSIX-only; the swap/staging "
    "guarantees themselves are platform-neutral and fully exercised on POSIX",
)
@pytest.mark.parametrize("kill_at", ["_merge_wiki", "swap"])
def test_t1_t7_kill_leaves_live_db_untouched(corpora, kill_at):
    a, art = corpora["A"], corpora["artifact"]
    live = a / "open_omniscience.db"
    before = _file_sha(live)
    _run(a, "merge", str(art), "--passphrase", "pw-torture", "--commit",
         "--kill-at", kill_at, expect_kill=True)
    assert _file_sha(live) == before, f"live DB changed after SIGKILL at {kill_at}"
    # The crashed run's staging dir is left behind -- the boot janitor reclaims it.
    leftovers = list(a.glob(".restore-*"))
    assert leftovers, "expected an orphaned staging dir from the killed run"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="depends on the SIGKILL scenario above leaving an orphaned staging dir",
)
def test_staging_janitor_reclaims_orphans(corpora):
    a = corpora["A"]
    env = dict(os.environ, OO_DATA_DIR=str(a), OO_NO_SCHEDULER="1")
    code = (
        "from src.backup.artifact import cleanup_stale_staging;"
        "print(cleanup_stale_staging(max_age_hours=0))"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(_REPO), env=env, timeout=60)
    assert proc.returncode == 0
    assert int(proc.stdout.strip().splitlines()[-1]) >= 1
    assert not list(a.glob(".restore-*"))


# --------------------------------------------------------------------------- #
#  T3: wrong passphrase -- loud, typed, nothing staged
# --------------------------------------------------------------------------- #
def test_t3_wrong_passphrase_is_loud(corpora):
    a, art = corpora["A"], corpora["artifact"]
    out = _run(a, "merge", str(art), "--passphrase", "WRONG", "--commit")
    assert out["error"] == "EncryptionError"
    out2 = _run(a, "merge", str(art))  # encrypted artifact, no passphrase at all
    assert out2["error"] == "ArtifactError" and "passphrase" in out2["message"]


# --------------------------------------------------------------------------- #
#  T4: cross-version -- staged upgrade works; refusals name what they refuse
# --------------------------------------------------------------------------- #
def test_t4_cross_version_restore(corpora, tmp_path):
    a = corpora["A"]
    old = tmp_path / "old-schema.db"
    _run(a, "make-old", str(old), "a3b4c5d6e7f8")  # previous head, pre-merge-tables
    rep = _run(a, "merge", str(old), "--commit")["report"]
    assert rep["committed"] is True and rep["artifact_kind"] == "legacy-db"
    assert rep["artifact_schema_rev"] == "a3b4c5d6e7f8"
    assert rep["plan"]["articles"]["new"] == 1  # the old corpus's story arrived
    assert _run(a, "fts-find", "old")["matches"] >= 1

    floorless = tmp_path / "floorless.db"
    _run(a, "make-old", str(floorless), "a3b4c5d6e7f8", "--strip-version")
    out = _run(a, "merge", str(floorless), "--commit")
    assert out["error"] == "MergeError" and "0.0.8 baseline" in out["message"]

    alien = tmp_path / "alien.db"
    _run(a, "make-old", str(alien), "a3b4c5d6e7f8", "--alien-version")
    out2 = _run(a, "merge", str(alien), "--commit")
    assert out2["error"] == "MergeError" and "feedfacecafe" in out2["message"]


# --------------------------------------------------------------------------- #
#  T5: plaintext <-> encrypted round trips preserve the corpus exactly
# --------------------------------------------------------------------------- #
def test_t5_round_trips_preserve_content(corpora, tmp_path_factory):
    root = tmp_path_factory.mktemp("roundtrip")
    a = corpora["A"]
    dump_a = _run(a, "dump")["dump"]

    plain_art = root / "a-plain.oobak"
    env = dict(os.environ, OO_DATA_DIR=str(a), OO_NO_SCHEDULER="1")
    code = (
        "from pathlib import Path; from src.backup.artifact import write_backup_v2;"
        f"write_backup_v2(Path({str(plain_art)!r}))"
    )
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(_REPO), env=env, timeout=120).returncode == 0

    c = root / "C"
    c.mkdir()
    out = _run(c, "merge", str(plain_art), "--commit")
    assert "report" in out, f"merge into fresh corpus failed: {out}"
    rep = out["report"]
    assert rep["committed"] and rep["verification"]["ok"]

    enc_art = root / "c-enc.oobak.ooenc"
    env_c = dict(os.environ, OO_DATA_DIR=str(c), OO_NO_SCHEDULER="1")
    code2 = (
        "from pathlib import Path; from src.backup.artifact import write_backup_v2;"
        f"write_backup_v2(Path({str(enc_art)!r}), passphrase='round-pw')"
    )
    assert subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True,
                          cwd=str(_REPO), env=env_c, timeout=120).returncode == 0

    d = root / "D"
    d.mkdir()
    rep2 = _run(d, "merge", str(enc_art), "--passphrase", "round-pw", "--commit")["report"]
    assert rep2["committed"] and rep2["verification"]["ok"]

    dump_d = _run(d, "dump")["dump"]
    assert dump_d == dump_a, "A -> plaintext -> C -> encrypted -> D lost or altered content"


# --------------------------------------------------------------------------- #
#  Symmetry: merge(A,B) and merge(B,A) agree on content
# --------------------------------------------------------------------------- #
def test_merge_symmetry(tmp_path_factory):
    """merge(A,B) and merge(B,A) agree on every NON-conflicting domain. On
    conflicting observations (the deliberate XAU price disagreement) each side
    keeps ITS local value -- the kept-local policy makes merge asymmetric there
    BY DESIGN, and both directions must report that conflict rather than hide it."""
    root = tmp_path_factory.mktemp("symmetry")
    a1, b1 = root / "A1", root / "B1"
    a1.mkdir(), b1.mkdir()
    art_b = root / "b.oobak"
    art_a = root / "a.oobak"
    _run(b1, "build", "B", "--artifact", str(art_b))
    _run(a1, "build", "A", "--artifact", str(art_a))
    rep_ab = _run(a1, "merge", str(art_b), "--commit")["report"]
    rep_ba = _run(b1, "merge", str(art_a), "--commit")["report"]
    assert rep_ab["verification"]["ok"] and rep_ba["verification"]["ok"]
    # Both directions surface the same disagreement (mirrored).
    assert rep_ab["plan"]["commodity_prices"]["conflict"] == 1
    assert rep_ba["plan"]["commodity_prices"]["conflict"] == 1
    da, db = _run(a1, "dump")["dump"], _run(b1, "dump")["dump"]
    da.pop("commodity_prices"), db.pop("commodity_prices")  # the kept-local divergence
    assert da == db, "merge(A,B) and merge(B,A) disagree outside the reported conflict"
