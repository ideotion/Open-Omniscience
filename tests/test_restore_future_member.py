"""A backup that carries a member this build does not know still restores, and the member is ignored (R755 F6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The schema-freeze audit (``docs/product/SCHEMA_FREEZE_AUDIT.md`` F6) freezes the backup writers at their current
identifiers and lets a later build add a NEW member only if an older reader ignores it. This is that older reader,
proved: the real writer, with its collector wrapped to add one member of an unknown role (signed with the rest, so the
signature check passes for the right reason), and the real restore path in a second data directory. The restore must
succeed, record the kind the artifact carries, and leave the unknown member unplaced.

The subprocess pair and the helper are the restore fixture matrix's (``tests/test_restore_fixture_matrix.py``), for
the reason that file gives: the engine is a module-level singleton, so one process cannot write from A and restore into B.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HELPER = _ROOT / "tests" / "_fixture_backup_helper.py"


def _current_schema() -> str:
    from src.backup.artifact import BACKUP_SCHEMA

    return BACKUP_SCHEMA


def _run(mode: str, data_dir: Path, dest: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "OO_DATA_DIR": str(data_dir),
        "OO_DB_PLAINTEXT": "1",
        "OO_NO_SCHEDULER": "1",
        "OO_AUTOSEED": "0",
        "OO_FIXTURE_DEST": str(dest),
        "OO_FIXTURE_SCHEMA": _current_schema(),
        "OO_FIXTURE_TRUST": "1",
        "OO_FIXTURE_EXTRA_MEMBER": "1",
    }
    env.pop("OO_DB_PASSPHRASE", None)
    proc = subprocess.run([sys.executable, str(_HELPER), mode], capture_output=True, text=True, cwd=_ROOT, env=env,
                          timeout=600)
    assert proc.returncode == 0, f"{mode} failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def restored(tmp_path_factory) -> dict:
    base = tmp_path_factory.mktemp("future-member")
    dest = base / "open-omniscience-future-member.oobak"
    seeded = _run("seed", base / "origin", dest)
    assert seeded["schema_written"] == _current_schema()
    out = _run("restore", base / "target", dest)
    out["_dest"] = str(dest)
    return out


def test_the_artifact_really_carries_the_unknown_member(restored):
    """Anti-vacuity: a writer that silently dropped the extra member would make the restore below prove nothing."""
    import zipfile

    from tests._fixture_backup_helper import EXTRA_MEMBER_NAME

    with zipfile.ZipFile(restored["_dest"]) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))["manifest"]
    assert EXTRA_MEMBER_NAME in names
    assert any(m.get("name") == EXTRA_MEMBER_NAME and m.get("role") == "future-pack" for m in manifest["members"])


def test_a_backup_with_a_member_this_build_does_not_know_restores(restored):
    assert restored["restore_ok"] is True
    assert restored["artifact_kind"] == _current_schema()
    # The payloads the restore does know still arrive (the same ones the fixture matrix checks).
    assert restored["countries"] and restored["translations"]


def test_the_unknown_member_is_ignored_never_placed(restored):
    assert restored["extra_member_placed"] is False
