"""Phase 2 is a list you approve, not a switch you flip.

Maintainer's design, 2026-08-11: "1 produce all AI-less content from what the local
database currently contains, then 2 detailed list all content and work that the
local AI would have to tackle to enhance the bulletin, as an option (appearing after
phase 1 has been produced)."

On the CPU-only machines this app is built for, a sweep over every card corpus is an
hour of a saturated fan. A checkbox that hides that is not consent, which is why the
plan states the call count exactly — and refuses to state a duration it has not
measured on this machine.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.bulletin.render import render
from src.bulletin.worklist import ai_worklist


def _edition(**kw) -> dict:
    base = {
        "period": {"cadence": "weekly", "start": "2026-08-04", "last_day": "2026-08-10",
                   "days": 7},
        "masthead": {"articles": 100},
        "sections": [],
    }
    base.update(kw)
    return base


_STORIES = {
    "stories": [
        {"shared_terms": ["alerta", "vientos"], "articles": 115, "article_ids": list(range(115))},
        {"shared_terms": ["fifa"], "articles": 17, "article_ids": [200, 201],
         "narration": {"narrated": True, "text": "done"}},
    ]
}
_CARDS = {
    "section": "cards",
    "types": [
        {"type": "rising", "cards": [
            {"title": "retraites", "corpus_articles": 115},
            {"title": "diet", "corpus_articles": 0},  # a query, not a set
        ]},
        {"type": "echo_chamber", "cards": [{"title": "echo", "corpus_articles": 9}]},
    ],
}


# --------------------------------------------------------------------------- #
#  what it counts
# --------------------------------------------------------------------------- #
def test_it_counts_one_call_per_story_still_to_narrate():
    plan = ai_worklist(_edition(stories=_STORIES))
    job = next(j for j in plan["jobs"] if j["kind"] == "narrate_stories")
    assert job["units"] == 1, "the already-narrated story is not re-counted"
    assert job["calls"] == 1
    assert job["already_done"] == 1


def test_a_card_with_no_fixed_article_set_is_not_counted():
    """Its selection is a query or a whole-corpus distribution, so there is nothing
    for a model to read. Counting it would inflate the plan with work that cannot run."""
    plan = ai_worklist(_edition(sections=[_CARDS]))
    job = next(j for j in plan["jobs"] if j["kind"] == "extract_from_card_corpora")
    assert job["units"] == 2, "two cards carry a corpus; the third does not"
    assert job["articles_total"] == 124
    assert "diet" not in str(job["corpora"])


def test_translation_counts_only_the_articles_the_document_names():
    cards = {
        "section": "cards",
        "types": [{"type": "rising", "cards": [{"title": "c", "corpus_articles": 3, "article_rows": [
            {"id": 1, "title": "fr one", "asserted": {"language": "fr"}, "deduced": {}},
            {"id": 2, "title": "en one", "asserted": {"language": "en"}, "deduced": {}},
            {"id": 3, "title": "mystery", "asserted": {}, "deduced": {}},
        ]}]}],
    }
    plan = ai_worklist(_edition(sections=[cards]), target_lang="en")
    job = next(j for j in plan["jobs"] if j["kind"] == "translate_named_articles")
    assert job["units"] == 1, "only the French one needs translating"
    assert job["already_in_target"] == 1
    assert job["language_unknown"] == 1, (
        "an article with no recorded language is listed, never assumed either way"
    )


def test_no_target_language_means_no_translation_job():
    plan = ai_worklist(_edition(sections=[_CARDS]))
    assert not [j for j in plan["jobs"] if j["kind"] == "translate_named_articles"]


def test_an_edition_with_nothing_to_add_says_so():
    plan = ai_worklist(_edition())
    assert plan["jobs"] == []
    assert plan["calls_total"] == 0


# --------------------------------------------------------------------------- #
#  no fabricated ETA
# --------------------------------------------------------------------------- #
def test_without_a_measurement_it_reports_calls_and_refuses_a_duration():
    plan = ai_worklist(_edition(stories=_STORIES, sections=[_CARDS]))
    assert plan["calls_total"] == 3
    assert plan["duration"]["known"] is False
    assert plan["duration"]["seconds"] is None
    assert "latency bench" in plan["duration"]["reason"], (
        "and it names the instrument that would produce the number"
    )


def test_with_a_measured_per_call_figure_it_does_the_arithmetic_and_shows_it():
    plan = ai_worklist(_edition(stories=_STORIES, sections=[_CARDS]), per_call_s=20.0)
    assert plan["duration"]["known"] is True
    assert plan["duration"]["seconds"] == 60.0
    assert "measured per call" in plan["duration"]["method"]


def test_concurrency_divides_the_wall_clock_not_the_calls():
    plan = ai_worklist(
        _edition(stories=_STORIES, sections=[_CARDS]), per_call_s=20.0, concurrency=2
    )
    assert plan["calls_total"] == 3, "the work does not shrink"
    assert plan["duration"]["seconds"] == 30.0


def test_a_plan_is_never_marked_as_having_run():
    assert ai_worklist(_edition(stories=_STORIES))["ran"] is False


# --------------------------------------------------------------------------- #
#  how it reads
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_plan_says_it_is_a_plan_before_it_says_anything_else(fmt):
    ed = _edition(stories=_STORIES, sections=[_CARDS])
    ed["ai_worklist"] = ai_worklist(ed)
    text = render(ed, fmt)
    assert "a plan" in text
    assert "nothing below has run" in text.lower()
    assert "3 model call(s)" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_each_job_says_what_is_lost_by_skipping_it(fmt):
    """The layer is removable, so the plan states what skipping costs. "Nothing the
    record states is lost" is the sentence that makes the option a real option."""
    ed = _edition(stories=_STORIES, sections=[_CARDS])
    ed["ai_worklist"] = ai_worklist(ed)
    text = render(ed, fmt)
    assert "If skipped" in text
    assert "deterministic sentence" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_an_edition_without_a_plan_prints_no_plan_section(fmt):
    """Phase 2 appears only once a caller has attached it — that is what "an option
    appearing after phase 1" means."""
    text = render(_edition(stories=_STORIES), fmt)
    assert "could add" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_rendered_plan_never_states_a_duration_it_has_not_measured(fmt):
    ed = _edition(stories=_STORIES, sections=[_CARDS])
    ed["ai_worklist"] = ai_worklist(ed)
    text = render(ed, fmt)
    assert "No duration is offered" in text
    assert "minute" not in text.replace("minute(s)", "")


# --------------------------------------------------------------------------- #
#  the caller
# --------------------------------------------------------------------------- #
#  Everything above tests a pure function that nothing in src/ called. The
#  renderer reads ``edition["ai_worklist"]`` and only these tests ever wrote it,
#  so the maintainer's "option appearing after phase 1 has been produced" could
#  not appear at all — the recorded dead-end shape, where a capability is built,
#  tested, green, and unreachable. These tests are the ones that would fail if
#  the route were dropped again.
@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # The Bulletin is hardware-gated and this sandbox has no GPU. The override is
    # the real mechanism, not a patch around it: it is what a maintainer on
    # impractical hardware would set, and it keeps the gate itself in the path.
    monkeypatch.setenv("OO_LLM_ALLOW_IMPRACTICAL_HW", "1")

    from src.api.main import app
    from src.bulletin.period import resolve_period
    from src.bulletin.store import persist_edition

    # The cards carry named articles here, unlike _CARDS above, so the translation
    # job has something to count — a route test whose fixture cannot produce the job
    # it is named for would pass for the wrong reason.
    cards = json.loads(json.dumps(_CARDS))
    cards["types"][0]["cards"][0]["article_rows"] = [
        {"id": 1, "title": "une grève", "asserted": {"language": "fr"}, "deduced": {}},
        {"id": 2, "title": "a strike", "asserted": {"language": "en"}, "deduced": {}},
    ]
    ed = _edition(stories=_STORIES, sections=[cards])
    name = persist_edition(ed, resolve_period("weekly")).name
    with TestClient(app) as c:
        yield c, name


def test_the_plan_is_reachable_from_a_persisted_edition(client):
    c, name = client
    r = c.get(f"/api/bulletin/editions/{name}/ai-plan")
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["ran"] is False
    assert plan["calls_total"] == 3
    assert plan["duration"]["known"] is False


def test_the_route_passes_the_operators_measurement_through(client):
    c, name = client
    dur = c.get(f"/api/bulletin/editions/{name}/ai-plan?per_call_s=20&concurrency=2").json()[
        "duration"
    ]
    assert dur["known"] is True
    assert dur["seconds"] == 30.0, "3 calls x 20s over 2 lanes"
    assert dur["per_call_s"] == 20.0 and dur["concurrency"] == 2
    assert "measured per call" in dur["method"]


def test_a_target_language_adds_the_translation_job(client):
    c, name = client
    plain = c.get(f"/api/bulletin/editions/{name}/ai-plan").json()
    assert not [j for j in plain["jobs"] if j["kind"] == "translate_named_articles"]
    assert plain["calls_total"] == 3

    asked = c.get(f"/api/bulletin/editions/{name}/ai-plan?target_lang=en").json()
    job = next(j for j in asked["jobs"] if j["kind"] == "translate_named_articles")
    assert job["units"] == 1, "the French one; the English one is already in target"
    assert job["already_in_target"] == 1
    assert asked["calls_total"] == 4


def test_an_unknown_edition_is_a_404_not_an_empty_plan(client):
    c, _ = client
    assert c.get("/api/bulletin/editions/nope.json/ai-plan").status_code == 404
    assert c.get("/api/bulletin/editions/..%2Fsecret.json/ai-plan").status_code in (400, 404)


def test_the_document_carries_the_plan_only_when_asked(client):
    c, name = client
    plain = c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown").text
    assert "could add" not in plain

    withplan = c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown&include_plan=1").text
    assert "What the local AI could add — a plan" in withplan
    assert "nothing below has run" in withplan.lower()
    assert "3 model call(s)" in withplan


def test_the_rendered_plan_describes_the_document_the_operator_selected(client):
    """A section the operator excluded is not in the published document, so offering
    to run a model over it would be planning work for a page nobody will read."""
    c, name = client
    full = c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown&include_plan=1").text
    assert "Read each card's own articles" in full

    trimmed = c.get(
        f"/api/bulletin/editions/{name}/render?fmt=markdown&include_plan=1&exclude_sections=cards"
    ).text
    assert "Read each card's own articles" not in trimmed
    assert "One grounded paragraph per story cluster" in trimmed, "the stories still stand"


def test_asking_for_the_plan_never_writes_it_into_the_record(client):
    """The plan is derived FROM the record. Persisting it would make a re-read of an
    edition carry a proposal among its measurements."""
    c, name = client
    c.get(f"/api/bulletin/editions/{name}/render?fmt=markdown&include_plan=1")
    c.get(f"/api/bulletin/editions/{name}/ai-plan?per_call_s=20")
    assert "ai_worklist" not in c.get(f"/api/bulletin/editions/{name}").json()
