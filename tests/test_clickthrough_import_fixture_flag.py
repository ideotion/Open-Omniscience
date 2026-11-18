"""The state D import fixture is one seed flag, and its passphrase never rides on argv (walk rerun 2026-11-18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every release-ritual walk recorded ``post_import_content`` as blocked, because building the fixture
was a by-hand REPL step. ``ui_clickthrough_seed.py --mini --write-import-artifact DIR`` now builds it
with the app's own volume-backup engine. These tests pin the two refusals: the flag only makes sense
with the --mini corpus, and the passphrase comes from ``OO_UIWALK_IMPORT_PASS`` or not at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SEED = _ROOT / "scripts" / "ui_clickthrough_seed.py"


def _run(args: list[str], tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    full = {k: v for k, v in os.environ.items() if k != "OO_UIWALK_IMPORT_PASS"}
    full.update({"OO_DATA_DIR": str(tmp_path / "data"), "OO_DB_PLAINTEXT": "1"}, **env)
    return subprocess.run([sys.executable, str(_SEED), *args], cwd=_ROOT, env=full,
                          capture_output=True, text=True, timeout=120)


def test_the_fixture_flag_needs_the_mini_corpus(tmp_path):
    r = _run(["--write-import-artifact", str(tmp_path / "art")], tmp_path, OO_UIWALK_IMPORT_PASS="x" * 20)
    assert r.returncode == 2 and "--mini" in r.stderr, r.stderr
    assert not (tmp_path / "art").exists()


def test_the_fixture_passphrase_comes_from_the_environment_only(tmp_path):
    r = _run(["--mini", "--write-import-artifact", str(tmp_path / "art")], tmp_path)
    assert r.returncode == 2 and "OO_UIWALK_IMPORT_PASS" in r.stderr, r.stderr
    assert not (tmp_path / "art").exists()


def test_the_seed_offers_no_passphrase_flag():
    src = _SEED.read_text(encoding="utf-8")
    assert "--import-pass" not in src and "--passphrase" not in src
    assert 'os.environ.get("OO_UIWALK_IMPORT_PASS"' in src
