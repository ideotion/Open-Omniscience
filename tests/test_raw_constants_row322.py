"""Row 322: four places that printed a raw token or an English constant inside translated UI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

1. Custody: the anchor result said "Anchored via <provider> — <English detail>", and that detail is the caveat (a local
   anchor is NOT independent third-party proof; an OpenTimestamps submission is not yet a proof of time). It is now worded
   per provider x12, the provider shown as data; the calendar counts travel as ``detail_vars``, never in the stored proof.
2. Sources: the batch ingest status lines and the per-source status pill.
3. AI check: the "not part of this check" entries (server English) are worded by a stable ``id``.
4. AI activity: the sweep notes carry a code, and the triage verdict (junk | content | unsure) is worded.

Each map shows a token it does not know exactly as sent. tests/raw_constants_row322_node_test.js runs the real functions;
this file holds the server half and keeps the client's English keys equal to the server's own words.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


def _node() -> list[str]:
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "raw_constants_row322_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[-1] == "raw constants row 322: all checks passed"
    return json.loads(lines[-2])


def test_every_word_the_maps_use_is_a_key_in_all_twelve_locales():
    keys = _node()
    assert len(keys) >= 20, keys
    files = sorted((STATIC / "locales").glob("*.json"))
    assert len(files) == 12
    for f in files:
        loc = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert loc.get(k), (f.stem, k)


def test_the_custody_caveat_keeps_its_full_strength_in_english():
    en = json.loads((STATIC / "locales" / "en.json").read_text(encoding="utf-8"))
    local = next(
        k for k in en if k.startswith("Recorded in the local anchor book. This proves only")
    )
    assert "NOT independent third-party proof" in local
    assert any("this is not a proof of time" in k for k in en)


def test_the_stored_proof_form_is_unchanged_and_the_receipt_carries_the_counts():
    from src.custody.anchor import AnchorReceipt
    from src.custody.timestamp import TimestampProof

    proof = TimestampProof(
        kind="opentimestamps",
        digest="ab",
        asserted_time=None,
        proof_b64="x",
        detail="d",
        calendars=(2, 3),
    )
    assert set(proof.to_dict()) == {"kind", "digest", "asserted_time", "proof_b64", "detail"}, (
        "the counts must never enter the signed custody entry"
    )
    assert TimestampProof.from_dict(proof.to_dict()).calendars is None
    rec = AnchorReceipt(
        provider="opentimestamps",
        merkle_root="ab",
        created_at="t",
        locator=None,
        detail="d",
        detail_vars={"calendars_reached": 2, "calendars_total": 3},
    )
    assert rec.to_dict()["detail_vars"] == {"calendars_reached": 2, "calendars_total": 3}


def test_the_ots_provider_hands_the_counts_to_the_receipt(monkeypatch):
    import src.custody.anchor as A
    from src.custody.timestamp import TimestampProof

    monkeypatch.setattr(
        A,
        "ots_stamp",
        lambda digest: TimestampProof(
            kind="opentimestamps",
            digest=digest.hex(),
            asserted_time=None,
            proof_b64="x",
            detail="d",
            calendars=(1, 3),
        ),
    )
    got = A.OpenTimestampsAnchorProvider().anchor("ab" * 32).to_dict()
    assert (
        got["detail_vars"] == {"calendars_reached": 1, "calendars_total": 3}
        and got["detail"] == "d"
    )


def test_ots_stamp_records_the_counts_beside_its_english_detail():
    src = (ROOT / "src" / "custody" / "timestamp.py").read_text(encoding="utf-8")
    body = src[src.index("def ots_stamp(") :]
    assert (
        "calendars=(reached, len(calendars))" in body
        and 'f"Submitted to {reached}/{len(calendars)}' in body
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def test_a_local_anchor_answers_with_no_counts(client):
    r = client.post("/api/custody/anchor", json={"merkle_root": "d" * 64, "provider": "local"})
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "local" and r.json()["detail_vars"] == {}


def test_the_ai_check_entries_carry_ids_and_the_client_keeps_their_english_words():
    import src.monitoring.ai_check as AC

    entries = {e["id"]: e for e in (*AC.SEPARATE_RUNS, AC.NEEDS_A_HUMAN)}
    assert set(entries) == {"model-bench", "anchor-grading"}
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    block = js[js.index("const _AI_NOT_RUN_WORDS = {") :]
    block = block[: block.index("};") + 2]
    for eid, e in entries.items():
        m = re.search(
            r'"'
            + re.escape(eid)
            + r'": \["((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"\]',
            block,
        )
        assert m, eid
        name, why, where = m.groups()
        assert name == e["name"] and why == e["why"], (
            eid,
            "the client's English drifted from the server's",
        )
        assert where == e["where"].replace("'bench the model'", "“bench the model”"), (
            eid,
            where,
            e["where"],
        )


def test_the_activity_notes_carry_codes_and_the_client_keeps_their_english_words(tmp_path):
    from src.ai_layer.activity import recent_activity

    sweeps = {s["key"]: s for s in recent_activity(directory=tmp_path)["sweeps"]}
    assert sweeps["keyword_triage"]["note_code"] == "no-run-log"
    assert sweeps["keyword_translation"]["note_code"] == "not-run"
    assert sweeps["keyword_translation"]["latest_note_code"] == "translation-stored"
    # a perception run log, so that sweep reaches its latest_note too (with no log it returns before it)
    (tmp_path / "oo-perception-extract-20260101-000000-000000.jsonl").write_text(
        json.dumps({"schema": "oo-perception-extract-batch-1", "attempted": 1}) + "\n",
        encoding="utf-8",
    )
    sweeps = {s["key"]: s for s in recent_activity(directory=tmp_path)["sweeps"]}
    assert sweeps["perception_extract"]["latest_note_code"] == "perception-stored"
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    coded = [s for s in sweeps.values() if s.get("latest_note_code")]
    assert {s["latest_note_code"] for s in coded} == {"perception-stored", "translation-stored"}
    for s in coded:
        if s.get("latest_note_code"):
            assert f't("{s["latest_note"]}")' in js, (
                s["key"],
                "the client's English drifted from the server's",
            )
    (tmp_path / "translation_sweep_progress_state.json").write_text(
        json.dumps({"target_lang": "fr", "position": 7})
    )
    tr = next(
        s
        for s in recent_activity(directory=tmp_path)["sweeps"]
        if s["key"] == "keyword_translation"
    )
    assert tr["note_code"] == "translation-progress" and tr["note_vars"] == {
        "lang": "fr",
        "n": 7,
        "unit": "keywords",
    }


def test_the_verdicts_the_client_words_are_the_triage_set():
    from src.ai_layer.triage import VERDICTS

    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    body = js[js.index("function _aiTriageVerdictWords(") :]
    body = body[: body.index("\n    }\n")]
    assert set(re.findall(r'v === "([a-z]+)"', body)) == set(VERDICTS)


def test_the_batch_statuses_the_client_words_are_the_ones_the_route_sends():
    src = (ROOT / "src" / "api" / "ingestion.py").read_text(encoding="utf-8")
    body = src[src.index("def ingest_batch_endpoint(") :]
    body = body[: body.index("\n@router")]
    sent = set(re.findall(r'"status": "([a-z_]+)"', body))
    assert sent == {"ok", "not_found", "no_feed", "error"}, sent
    js = (STATIC / "app-sources.js").read_text(encoding="utf-8")
    fn = js[js.index("function batchIngestStatusWords(") :]
    fn = fn[: fn.index("\n    }\n")]
    assert set(re.findall(r'st === "([a-z_]+)"', fn)) == sent - {"ok"}, (
        "ok is drawn as its tally, never as a word"
    )
