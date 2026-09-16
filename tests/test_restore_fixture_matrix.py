"""THE CI FIXTURE RESTORE: one OLD-format artifact, all five row-K payloads (gate row K).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row K closes on, among other things, "a CI restore of a fixture backup proves each of
the five members round-trips". This is that restore, end to end through the REAL writer
and the REAL legacy restore path -- not five handler tests that each stub the other four.

    (1) the alpha-2/alpha-3 normaliser (Q310)        FRA -> fr, DEU -> de, and the scan says 0
    (2) all rings ride the backup (Q409 = b)         local placed, shipped carried, never overriding
    (3) keyword_translations (Q404)                  the row and its full provenance
    (4) the fetch/scrape history (the Q701 note)     validators carried, last_checked_at not
    (5) the legacy single-file restore (Q215 = a)    it IS the path this test drives

WHY TWO SUBPROCESSES. ``data_dir()`` re-reads the environment per call, but
``live_db_path()`` resolves through ``src.database.session.engine``, a module-level
singleton frozen at import. An in-process "write from A, restore into B" would write and
restore against ONE database -- a self-restore, which sees every row as a duplicate and
can never exercise a handler. The helper is ``tests/_fixture_backup_helper.py``.

THE FIXTURE IS GENUINELY OLD-FORMAT. The writer runs with ``BACKUP_SCHEMA`` set to the
PREVIOUS literal, so the manifest carries it and the Ed25519 signature covers it -- what
an artifact taken by last week's build actually looks like. A manifest rewritten after
the fact has a broken signature, so such a fixture would exercise the signature refusal
rather than the schema acceptance and would pass for the wrong reason.
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
#: The format every backup taken before this PR carries.
_PREVIOUS_SCHEMA = "oo-backup-2"


def _run(mode: str, data_dir: Path, dest: Path, *, trust: bool = True) -> dict:
    env = {
        **os.environ,
        "OO_DATA_DIR": str(data_dir),
        "OO_DB_PLAINTEXT": "1",
        "OO_NO_SCHEDULER": "1",
        "OO_AUTOSEED": "0",
        "OO_FIXTURE_DEST": str(dest),
        "OO_FIXTURE_SCHEMA": _PREVIOUS_SCHEMA,
        "OO_FIXTURE_TRUST": "1" if trust else "0",
    }
    env.pop("OO_DB_PASSPHRASE", None)
    proc = subprocess.run(
        [sys.executable, str(_HELPER), mode],
        capture_output=True, text=True, cwd=_ROOT, env=env, timeout=600,
    )
    assert proc.returncode == 0, f"{mode} failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def restored(tmp_path_factory) -> dict:
    """Build the old-format fixture in one data dir, restore it into another. Module
    scope: the pair costs two full app boots, and every assertion below reads the same
    restore -- which is also the point, since they are claims about ONE artifact."""
    base = tmp_path_factory.mktemp("fixture-matrix")
    dest = base / "open-omniscience-fixture.oobak"
    seeded = _run("seed", base / "origin", dest)
    assert seeded["schema_written"] == _PREVIOUS_SCHEMA
    assert seeded["current_schema"] != _PREVIOUS_SCHEMA, (
        "the fixture was written under the CURRENT format; this test would then prove "
        "nothing about older backups"
    )
    out = _run("restore", base / "target", dest)
    out["_seeded"] = seeded
    return out


# --------------------------------------------------------------------------- #
#  The restore itself
# --------------------------------------------------------------------------- #
def test_an_artifact_in_the_PREVIOUS_format_restores(restored):
    """THE ONE THAT MATTERS: every backup an operator already holds carries the previous
    literal, and the bump must not have stranded a single one of them."""
    assert restored["restore_ok"] is True
    assert restored["artifact_kind"] == _PREVIOUS_SCHEMA, (
        "the restore recorded the CURRENT format for an older artifact; no later reader "
        "could then tell what was actually restored"
    )


# --------------------------------------------------------------------------- #
#  (1) the normaliser, and the gate's own artifact
# --------------------------------------------------------------------------- #
def test_payload_1_the_country_codes_are_normalised_on_a_REAL_restore(restored):
    """The fixture stores ``FRA``, ``DEU`` and ``fr``. A restore that carried them
    through unchanged would leave the corpus holding one country in two spellings."""
    assert restored["countries"] == ["de", "fr", "fr"], restored["countries"]


def test_payload_1_the_duplicate_key_scan_reports_zero(restored):
    """Row K's acceptance clause, on the CI fixture. The operator's own run against a
    real pre-migration backup is the other half and is `not-measurable-here`."""
    scan = restored["scan"]
    assert scan["duplicates"] == 0, scan
    # Anti-vacuity: a scan that looked at nothing would also answer 0.
    assert len(scan["columns"]) >= 8, scan["columns"]
    assert "sources.country" in scan["columns"]


def test_payload_1_the_restore_reports_the_live_corpus_form_gap(restored):
    """The 0.5 precondition, measured on every restore rather than assumed. The staged
    copy is normalised toward ``CANONICAL_COUNTRY_FORM``; the live corpus is not touched.
    So the day that constant flips, a live corpus still on the other form turns every
    value-keyed join into a miss. 0 here says the two agree."""
    block = restored["country_codes_block"]
    assert block is not None, "the restore report carries no country-code block at all"
    gap = block["live_corpus_in_target_form"]
    assert gap["off_form"] == 0, gap
    assert gap["columns_checked"] >= 5, gap
    assert block["rows_converted"] >= 2, (
        f"the fixture's alpha-3 codes were not converted: {block}"
    )


# --------------------------------------------------------------------------- #
#  (2) rings
# --------------------------------------------------------------------------- #
def test_payload_2_a_local_ring_rides_the_backup_and_is_placed(restored):
    assert restored["local_ring_present"] is True
    assert "fixture-local-ring" in restored["ring_ids"], (
        "the operator's own ring did not survive the restore"
    )
    rings = restored["rings_block"]
    assert rings["restored"] == ["rings/local/keyword_rings_local.yml"], rings
    assert rings["refused"] == [], rings


def test_payload_2_shipped_rings_are_carried_but_NEVER_placed(restored):
    """Q409 = b says all rings ride the backup; the design note says a restored shipped
    ring must never override a newer release's own. Both, at once: the member travels
    and is reported, and nothing is written over the running release's files."""
    rings = restored["rings_block"]
    assert sorted(rings["carried_not_placed"]) == [
        "rings/shipped/keyword_equivalents.yml",
        "rings/shipped/keyword_rings_generated.yml",
    ], rings
    # ...and the release's own rings are still the ones loaded.
    assert len(restored["ring_ids"]) > 100, (
        "the shipped ring set is missing after the restore"
    )


# --------------------------------------------------------------------------- #
#  (3) keyword_translations
# --------------------------------------------------------------------------- #
def test_payload_3_a_keyword_translation_round_trips_with_its_provenance(restored):
    assert restored["translations"] == [
        ["chat", "fr", "en", "cat", "fixture-m1", "kw-translate-v1"]
    ], restored["translations"]


# --------------------------------------------------------------------------- #
#  (4) the fetch history
# --------------------------------------------------------------------------- #
def test_payload_4_the_fetch_history_is_adopted_when_trusted(restored):
    rows = restored["fetch_rows"]
    assert len(rows) == 1, rows
    assert rows[0]["etag"] == '"fixture-etag"', rows
    assert rows[0]["skip_until"] is True, rows
    assert rows[0]["last_checked_at"] is False, (
        "a foreign last_checked_at was adopted; the coverage report would then claim "
        "reach this instance never had"
    )


def test_payload_4_the_report_says_what_the_toggle_did(restored):
    block = restored["fetch_history_block"]
    assert block is not None, (
        "the restore report carries no fetch-history block, so an operator who "
        "untrusted a history has no way to see what they declined"
    )
    assert block["trusted"] is True
    assert block["available"] == 1 and block["adopted"] == 1, block


def test_payload_4_an_UNTRUSTED_restore_of_the_same_fixture_adopts_NOTHING(
    tmp_path_factory, restored
):
    """The other direction, on the same artifact. Driven separately because it needs its
    own empty corpus -- a second restore into the first one would see duplicates."""
    base = tmp_path_factory.mktemp("fixture-untrusted")
    dest = Path(restored["_seeded"]["dest"])
    out = _run("restore", base / "target", dest, trust=False)

    assert out["fetch_rows"] == [], out["fetch_rows"]
    block = out["fetch_history_block"]
    assert block["trusted"] is False and block["adopted"] == 0, block
    assert block["available"] == 1, (
        "a bare zero cannot tell 'you declined it' from 'there was nothing there'"
    )
    # ...and declining the HISTORY declines nothing else.
    assert out["countries"] == ["de", "fr", "fr"]
    assert len(out["translations"]) == 1
