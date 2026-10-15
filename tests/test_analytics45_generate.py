"""The rows the app's own walk code wrote from the stand-in world, and what the readers then say about them.

``scripts/analytics45_generate.py`` runs the lane's real code (``WikiClient``, ``WikiWalker``, ``WikiEventStream``,
``drain_once``, the pageview refresh) against ``src/testing/wiki_standin.py`` and prints the PLAN. The look judges the
page against that plan; this judges the READERS against it, so the look is never judging the page against a fiction.
None of it is Wikipedia: the world is seeded and invented, and every record says so.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_ASK = r"""
import json
from src.database.session import SessionLocal
from src.versioned.store import lane_session
from src.wiki import cross_edition as X
from src.scheduler.settings import load_settings
eds = tuple(load_settings().wiki_lane_editions)
with lane_session("wiki") as lane:
    divs = {q: X.divergence(lane, q, editions=eds) for q in ("Q34", "Q42", "Q7001", "Q7002")}
    cands = X.divergence_candidates(lane)
with SessionLocal() as corpus:
    att = {e: X.attention(corpus, edition=e) for e in eds}
print(json.dumps({"divs": divs, "att": att, "cands": cands}, default=str))
"""


def _run(code_args: list[str], data_dir: Path) -> str:
    env = {**os.environ, "OO_DATA_DIR": str(data_dir), "OO_DB_PLAINTEXT": "1", "OO_AUTOSEED": "0", "OO_NO_SCHEDULER": "1"}
    env.pop("DATABASE_URL", None)  # it overrides OO_DATA_DIR
    done = subprocess.run([sys.executable, *code_args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2500:]
    return done.stdout


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    data = tmp_path_factory.mktemp("a45g") / "state"
    truth = json.loads(_run([str(ROOT / "scripts" / "analytics45_generate.py")], data))
    got = json.loads(_run(["-c", _ASK], data).strip().splitlines()[-1])
    return truth, got


def test_every_record_names_the_world_a_stand_in(generated):
    truth, _got = generated
    assert "stand-in" in truth["label"] and "NOT Wikipedia" in truth["label"]
    assert {c: v["source"] for c, v in truth["redirect_shares"].items()} == {
        "en": "measured 2026-10-06", "de": "measured 2026-10-06", "fr": "measured 2026-10-06",
        "es": "measured 2026-10-06", "ar": "ASSUMED", "it": "ASSUMED"}, "an unmeasured share must say it is assumed"


def test_the_divergence_reader_says_what_the_walk_stored(generated):
    truth, got = generated
    for qid, plan in truth["divergence"].items():
        div = got["divs"][qid]
        by = {r["edition"]: r for r in div["editions"]}
        three = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "ar": "ara", "it": "ita"}
        for row in plan["rows"]:
            code = next(c for c, a in three.items() if a == row["edition"])
            assert (by[code]["state"] == "found") == row["found"], (qid, code)
            if row["found"]:
                assert by[code]["length_bytes"] == row["size"], (qid, code)
                assert by[code]["changes_in_window"] == row["changes"], (qid, code)  # None = unknown, never 0
    # the three absences and the three kinds of change count the look then reads off the page
    q34 = {r["edition"]: r for r in got["divs"]["Q34"]["editions"]}
    assert q34["es"]["state"] == "walk-never-ran" and q34["ar"]["state"] == "none-after-complete-walk"
    assert q34["fr"]["changes_in_window"] is None and q34["de"]["changes_in_window"] == 0 and q34["en"]["changes_in_window"] == 3


def test_the_suggestions_are_the_plans_in_the_plans_order(generated):
    truth, got = generated
    items = [(c["qid"], c["changes_in_window"], c["editions_found"]) for c in got["cands"]["items"]]
    assert items[: len(truth["suggestions"])] == [(s["qid"], s["changes"], s["found_in"]) for s in truth["suggestions"]]


def test_the_attention_reader_counts_the_press_the_plan_wrote(generated):
    truth, got = generated
    assert sorted(truth["attention"]) == sorted(got["att"])
    for edition, plan in truth["attention"].items():
        rows = got["att"][edition]["rows"]
        assert len(rows) == len(plan), edition
        for row, want in zip(rows, plan, strict=True):
            assert (row["rank"], row["views"]) == (want["rank"], want["views"]), (edition, want["rank"])
            if want["day"] is None:
                assert row["not_counted"] == "unsearchable"
            else:
                assert (row["press_day"], row["press_7d"]) == (want["day"], want["week"]), (edition, want["rank"])


def test_the_walk_stopped_mid_pass_in_en_and_never_ran_in_es(generated):
    truth, _got = generated
    assert truth["walk"]["en"]["complete"] is False
    assert truth["walk"]["en"]["pages_seen"] < truth["walk"]["en"]["edition_articles"]
    assert "es" not in truth["walk"] and all(truth["walk"][c]["complete"] for c in ("de", "fr", "ar", "it"))


# ---- the stand-in itself ------------------------------------------------------------------ #
def test_the_world_is_seeded_and_the_measured_shares_hold_exactly():
    from src.testing.wiki_standin import PLAN, World

    a, b = World(7), World(7)
    assert [p.title for p in a.pages["de"]] == [p.title for p in b.pages["de"]] and a.sse_text() == b.sse_text()
    assert [p.title for p in World(8).pages["de"]] != [p.title for p in a.pages["de"]]
    for code, (total, share, _src) in PLAN.items():
        assert len(a.pages[code]) == total
        assert sum(1 for p in a.pages[code] if not p.redirect) == round(total * share), code


def test_a_window_is_fifty_titles_with_the_redirects_filtered_out_after_it():
    from src.testing.wiki_standin import World

    w = World(7)
    first = w.walk_payload("en", {"gaplimit": 50})
    assert len(first["query"]["pages"]) == sum(1 for p in w.pages["en"][:50] if not p.redirect) < 50
    assert first["continue"]["gapcontinue"] == w.pages["en"][50].title.replace(" ", "_")
    last = w.walk_payload("en", {"gaplimit": 50, "gapcontinue": w.pages["en"][-10].title.replace(" ", "_")})
    assert "continue" not in last and last["batchcomplete"] is True  # the pass is over


def test_the_session_answers_two_apis_and_refuses_everything_else_loudly():
    from src.testing.wiki_standin import StandInSession, World

    s = StandInSession(World(7))
    assert s.get("https://en.wikipedia.org/w/api.php", params={"meta": "siteinfo", "siprop": "statistics"}).json()["query"]
    for url in ("https://example.org/", "https://xx.wikipedia.org/w/api.php", "https://wikimedia.org/other"):
        with pytest.raises(RuntimeError):
            s.get(url, params={"meta": "siteinfo"})
    with pytest.raises(RuntimeError):
        s.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "prop": "revisions"})


def test_the_generator_refuses_a_remote_connection_and_a_used_data_directory(tmp_path):
    code = (
        "import sys, socket; sys.path.insert(0, 'scripts'); import analytics45_generate as g; g._install_socket_tripwire()\n"
        "for fn in (lambda: socket.getaddrinfo('example.org', 443), lambda: socket.socket().connect(('93.184.216.34', 443))):\n"
        "    try: fn()\n"
        "    except OSError as e: print('refused', 'analytics45_generate' in str(e))\n"
        "    else: print('REACHED')\n"
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); print('loopback ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.stdout.split() == ["refused", "True", "refused", "True", "loopback", "ok"], done.stdout + done.stderr
    (tmp_path / "x").write_text("a store someone uses")
    env = {**os.environ, "OO_DATA_DIR": str(tmp_path)}
    env.pop("DATABASE_URL", None)
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "analytics45_generate.py")], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and "not empty" in done.stderr


def test_the_look_judges_a_generated_state_by_the_same_keys_as_the_seeded_one():
    spec = importlib.util.spec_from_file_location("a45_look", ROOT / "scripts" / "analytics45_look.py")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        look = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(look)
    finally:
        sys.path.pop(0)
    truth = {
        "label": "stand-in", "followed": ["en", "de", "fr", "es", "ar"],
        "suggestions": [{"qid": "Q42", "changes": 9, "found_in": 2}, {"qid": "Q34", "changes": 3, "found_in": 4}],
        "divergence": {"Q42": {"rows": [{"edition": "eng", "found": True}, {"edition": "spa", "found": False}]},
                       "Q34": {"rows": [{"edition": "eng", "found": True, "size_text": "8.8", "changes": 3, "bar": "75%"}]}},
        "attention": {"en": [{"views": 5, "day": 1, "week": 2}, {"views": 4, "day": None, "week": None}], "de": [{"views": 3, "day": 0, "week": 0}]},
    }
    gen, seed = look.generated_expectations(truth), look.seed_expectations()
    assert set(seed) <= set(gen), "the generated expectations must answer every question the seeded ones do"
    assert gen["att"]["en"] == [("1", "2"), None] and gen["cands"] == [("Q42", [9, 2]), ("Q34", [3, 4])]
