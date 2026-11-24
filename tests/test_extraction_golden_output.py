"""R824 step 1 (row 405): the OUTPUT digest guards the hand-bumped indexer versions.

``configs/indexer_pin.json`` / ``configs/www_indexer_pin.json`` police the versions with a CODE digest, and a ``--same``
judgement is only a sentence. ``configs/extraction_digests.json`` records, per engine, the digest of the rows a real
baseline pass writes over the golden corpus (``tests/fixtures/extraction_golden/``) and the environment it ran in.
These tests are red when the rows moved while the version stayed (the main guard), and when the version moved without the
digest being re-recorded with it (``scripts/indexer_pin.py --bump`` does both).

The digest depends on the environment (optional dictionaries, switches, Python, Unicode, data files). Where this run's
environment differs from the recorded one the main guard SKIPS and names the components; ``OO_GOLDEN_OUTPUT_REQUIRED=1``
turns that skip into a failure, for the CI job whose environment holds the authoritative digest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.analytics import engine_identity as ei
from src.analytics import golden_output as go

ROOT = Path(__file__).resolve().parents[1]
DIGESTS = ROOT / "configs" / "extraction_digests.json"
VERSIONS = {"kw": "INDEXER_VERSION", "www": "WWW_INDEXER_VERSION"}
PINS = {"kw": "indexer_pin.json", "www": "www_indexer_pin.json"}
#: The script each UI language's text is written in (Japanese: kana as well as Han).
LANG_SCRIPT = {
    "ar": "Arabic", "bn": "Bengali", "de": "Latin", "en": "Latin", "es": "Latin", "fr": "Latin", "hi": "Devanagari",
    "id": "Latin", "ja": "Han", "pt": "Latin", "ru": "Cyrillic", "zh": "Han",
}
HOW = (
    "The rows index_article writes for the golden corpus changed while {const} did not. A --same judgement was wrong, or "
    'nobody judged: python scripts/indexer_pin.py{eng} --bump "what changed" (re-records the output digest at the new '
    "version). Rows: {rows}"
)


def _recorded() -> dict:
    return json.loads(DIGESTS.read_text(encoding="utf-8"))


_GOLDEN_IN_A_FRESH_PROCESS = (
    "import json, sys; from src.analytics import golden_output as g; "
    "sys.stdout.write(json.dumps({s: g.golden_output(s) for s in g.STAGES}))"
)


def _golden_in_a_fresh_process() -> dict:
    """The pass runs in a FRESH interpreter, never in the test process: a cache another test filled (a gazetteer, a dictionary, a
    switch) changed the www rows under xdist, and the guard must judge the code and the environment, not the tests that ran before it."""
    out = subprocess.run(
        [sys.executable, "-c", _GOLDEN_IN_A_FRESH_PROCESS],
        capture_output=True, text=True, cwd=ROOT, env={**os.environ, "OO_DB_PLAINTEXT": "1", "OO_NO_SCHEDULER": "1"}, check=False,
    )
    assert out.returncode == 0, out.stderr[-4000:]
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def golden():
    return _golden_in_a_fresh_process()


@pytest.mark.parametrize("stage", go.STAGES)
def test_the_rows_have_not_moved_while_the_version_stayed(stage, golden):
    """THE MAIN GUARD."""
    rec = _recorded()[stage]
    if rec["version"] != getattr(ei, VERSIONS[stage]):
        pytest.fail("the version moved without the output digest: see test_the_version_and_the_output_digest_move_together")
    diffs = go.environment_differences(rec["environment"], golden[stage]["environment"])
    if diffs:
        msg = f"the {stage} output digest was recorded in another environment (differs in: {', '.join(diffs)}); cannot judge here"
        if os.environ.get("OO_GOLDEN_OUTPUT_REQUIRED") == "1":
            pytest.fail(msg + " -- and OO_GOLDEN_OUTPUT_REQUIRED=1 says this job must")
        pytest.skip(msg)
    eng = "" if stage == "kw" else " --engine www"
    assert golden[stage]["output_digest"] == rec["output_digest"], HOW.format(
        const=VERSIONS[stage], eng=eng, rows=golden[stage]["rows"]
    )


@pytest.mark.parametrize("stage", go.STAGES)
def test_the_version_and_the_output_digest_move_together(stage):
    rec = _recorded()[stage]
    pin = json.loads((ROOT / "configs" / PINS[stage]).read_text(encoding="utf-8"))
    assert rec["version"] == getattr(ei, VERSIONS[stage]) == pin["version"], (
        "the version constant, its pin and the recorded output digest must move together: scripts/indexer_pin.py --bump"
    )
    assert len(rec["output_digest"]) == 64


def test_the_fixture_covers_every_ui_language_by_the_script_of_its_text():
    fx = go.load_fixture()
    by_lang: dict[str, list[str]] = {}
    for a in fx["articles"]:
        by_lang.setdefault(a.get("language"), []).append(a.get("text") or "")
    for lang, script in LANG_SCRIPT.items():
        texts = [t for t in by_lang.get(lang, []) if go.main_script(t) == script]
        assert len(texts) >= 15, f"{lang}: {len(texts)} articles written in {script}"
        if lang == "ja":
            assert all(go.script_counts(t).get("Hiragana") for t in texts), "Japanese text carries kana"
    covered = go.scripts_covered(fx)
    assert set(LANG_SCRIPT.values()) | {"Hiragana", "Katakana"} <= set(covered)
    assert covered == _recorded()["kw"]["scripts_covered"]
    assert 180 <= len(fx["articles"]) <= 260


def test_the_fixture_exercises_the_stage_cases():
    fx = go.load_fixture()
    arts = fx["articles"]
    refuted = [a for a in arts if a.get("language") in LANG_SCRIPT and go.main_script(a["text"])
               and go.main_script(a["text"]) != LANG_SCRIPT[a["language"]]]
    assert len(refuted) >= 2, "a language tag the text's own script refutes"
    assert any(not (a.get("text") or "").strip() for a in arts), "an empty article"
    assert any("<script" in (a.get("text") or "") for a in arts), "markup"
    assert any("import " in (a.get("text") or "") for a in arts), "code-like lines"
    assert any(a.get("language") is None for a in arts) and any(a.get("country") is None for a in arts)
    names = {s["name"] for s in fx["sources"]}
    assert sum(1 for a in arts if a["source"] in (a.get("text") or "")) >= 12, "sources naming themselves"
    assert names


def test_the_computation_is_deterministic(golden):
    again = _golden_in_a_fresh_process()
    for stage in go.STAGES:
        assert again[stage]["output_digest"] == golden[stage]["output_digest"]


def _subset():
    fx = go.load_fixture()
    keep = [a for a in fx["articles"] if a["id"].startswith(("en-", "fr-"))]
    return {"sources": [s for s in fx["sources"] if s["name"] in {a["source"] for a in keep}], "articles": keep}


def test_a_changed_row_changes_the_digest(monkeypatch):
    """Remove the guard and it must notice: one changed place name and one changed sentiment move their stage's digest."""
    fx = _subset()
    base = go.run_pass(fx)
    import src.analytics.sentiment as sentiment
    import src.timemap.whostore as whostore

    real_loc, real_sent = whostore.extract_locations, sentiment.score_article

    def _loc(text, **kw):
        out = real_loc(text, **kw)
        if "Toronto" in text and out:
            out = [dict(out[0], name=out[0]["name"] + "x"), *out[1:]]
        return out

    monkeypatch.setattr(whostore, "extract_locations", _loc)
    moved = go.run_pass(fx)
    assert go.digest_of(moved["www"]) != go.digest_of(base["www"])
    assert go.digest_of(moved["kw"]) == go.digest_of(base["kw"]), "a place change is not a keyword change"

    def _sent(text, lang):
        # The core-only install has no VADER, so the real scorer returns None there: the
        # mock gives every article a score, so the changed row exists on every install.
        score, label = real_sent(text, lang)
        return (0.25 if score is None else score + 0.5), (label or "positive")

    monkeypatch.setattr(sentiment, "score_article", _sent)
    moved2 = go.run_pass(fx)
    assert go.digest_of(moved2["kw"]) != go.digest_of(base["kw"])


def test_the_pass_writes_alpha2_whatever_the_live_store_holds():
    """The digest moved with the live store's country form (alpha-3 in a migrated corpus, or a parallel test's data directory):
    the pass pins its own form, so a machine with a migrated corpus judges --same against the same rows CI does."""
    from src.database.country_form import writing_in

    fx = _subset()
    plain = go.run_pass(fx)
    with writing_in("alpha3"):
        under_alpha3 = go.run_pass(fx)
    assert go.digest_of(under_alpha3["www"]) == go.digest_of(plain["www"])
    assert go.digest_of(under_alpha3["kw"]) == go.digest_of(plain["kw"])


def test_the_www_golden_rows_cover_every_script_the_www_rules_handle():
    """R824 addition 2: no ACK path for a stage without golden coverage of the scripts it handles. The www rules are Latin-script only
    (161 place patterns and the entity character classes), the golden www rows are Latin, and the corpus holds texts in every other UI
    script that today yield no www row -- so a rule that starts matching one of them moves the digest, and indexer_pin.py --same
    --engine www refuses until the golden rows hold that script."""
    rows = go.run_pass()["www"]
    handled, covered = go.www_rule_scripts(), go.www_golden_scripts(rows)
    assert handled == ["Latin"], f"the www rules now match {handled}: extend the golden corpus's www coverage, then update this test"
    assert set(handled) <= set(covered)
    fx = go.load_fixture()
    non_latin = {go.main_script(a["text"]) for a in fx["articles"] if a.get("text")} - {"Latin", None}
    assert {"Arabic", "Bengali", "Cyrillic", "Devanagari", "Han"} <= non_latin, non_latin


def test_same_for_www_is_refused_when_its_rules_reach_an_uncovered_script(tmp_path, monkeypatch):
    """The refusal itself: the script runs with a stand-in rule set that also matches Cyrillic."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("indexer_pin_under_test", ROOT / "scripts" / "indexer_pin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dig = _recorded()
    for stage in dig:
        dig[stage]["environment"] = go.environment(stage)
    (tmp_path / "extraction_digests.json").write_text(json.dumps(dig), encoding="utf-8")
    monkeypatch.setenv("OO_EXTRACTION_DIGESTS", str(tmp_path / "extraction_digests.json"))
    monkeypatch.setattr(go, "www_rule_scripts", lambda: ["Cyrillic", "Latin"])
    with pytest.raises(SystemExit, match="Cyrillic"):
        mod._refuse_same_on_output("www")
    monkeypatch.setattr(go, "www_rule_scripts", lambda: ["Latin"])
    mod._refuse_same_on_output("www")  # covered, unchanged output: no refusal


def test_the_police_module_is_not_part_of_the_engine():
    assert "src/analytics/golden_output.py" not in ei.engine_files()
    assert "src/analytics/golden_output.py" not in ei.NOT_OUTPUT_AFFECTING
    assert not any("extraction_golden" in f or "extraction_digests" in f for f in ei.engine_files())


# --- the script: --same is checked against the output ------------------------------------------------------------ #

def _scratch(tmp_path, digests_edit=None, pin_digest="0" * 64):
    """Copies of the kw pin (its digest moved, so --same is not refused for 'nothing changed'), the module and the
    digests file, edited by ``digests_edit``."""
    pin = tmp_path / "indexer_pin.json"
    data = json.loads((ROOT / "configs" / "indexer_pin.json").read_text(encoding="utf-8"))
    data["digest"] = pin_digest
    data["log"][-1]["digest"] = pin_digest
    pin.write_text(json.dumps(data), encoding="utf-8")
    shutil.copy(ROOT / "src" / "analytics" / "engine_identity.py", tmp_path / "engine_identity.py")
    dig = _recorded()
    if digests_edit:
        digests_edit(dig)
    (tmp_path / "extraction_digests.json").write_text(json.dumps(dig), encoding="utf-8")
    env = {**os.environ, "OO_INDEXER_PIN": str(pin), "OO_INDEXER_MODULE": str(tmp_path / "engine_identity.py")}
    return env, pin


def _run(env, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "indexer_pin.py"), *args],
                          capture_output=True, text=True, cwd=ROOT, env=env)


def test_same_is_refused_when_the_output_changed(tmp_path, golden):
    if go.environment_differences(_recorded()["kw"]["environment"], golden["kw"]["environment"]):
        pytest.skip("recorded in another environment; the refusal would be 'cannot judge here'")
    env, pin = _scratch(tmp_path, lambda d: d["kw"].update(output_digest="f" * 64))
    out = _run(env, "--same", "only a docstring changed in store.py")
    assert out.returncode != 0 and "the output changed" in out.stderr + out.stdout and "--bump" in out.stderr + out.stdout
    assert json.loads(pin.read_text(encoding="utf-8"))["digest"] == "0" * 64, "nothing was recorded"


def test_same_is_refused_in_another_environment(tmp_path):
    env, _ = _scratch(tmp_path, lambda d: d["kw"]["environment"].update(python="2.7"))
    out = _run(env, "--same", "only a docstring changed in store.py")
    assert out.returncode != 0 and "cannot judge here" in out.stderr + out.stdout and "python" in out.stderr + out.stdout


def test_same_passes_when_the_output_is_unchanged(tmp_path, golden):
    if go.environment_differences(_recorded()["kw"]["environment"], golden["kw"]["environment"]):
        pytest.skip("recorded in another environment")
    env, pin = _scratch(tmp_path)
    out = _run(env, "--same", "only a docstring changed in store.py")
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(pin.read_text(encoding="utf-8"))["log"][-1]["kind"] == "same"


def test_record_output_refuses_when_a_digest_is_recorded(tmp_path):
    env, _ = _scratch(tmp_path)
    out = _run(env, "--record-output")
    assert out.returncode != 0 and "already recorded" in out.stderr + out.stdout


def test_record_output_refuses_when_the_version_moved(tmp_path):
    env, pin = _scratch(tmp_path, lambda d: d.pop("kw"))
    data = json.loads(pin.read_text(encoding="utf-8"))
    data["version"] += 1
    pin.write_text(json.dumps(data), encoding="utf-8")
    out = _run(env, "--record-output")
    assert out.returncode != 0 and "refused" in out.stderr + out.stdout
    assert "kw" not in json.loads((tmp_path / "extraction_digests.json").read_text(encoding="utf-8"))
