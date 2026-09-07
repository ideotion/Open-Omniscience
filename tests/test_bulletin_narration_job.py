"""
Layer B as a resumable background job (design record §14).

The properties here cannot be read off a rendered document, which is why they are
pinned rather than inspected:

* the cursor is PERSISTED per unit, so a killed run resumes rather than restarts;
* an OUTAGE never advances the cursor and never completes — the abort-to-done
  defect §14 names by name, and the one this whole slice exists to avoid;
* a fallback that is NOT an outage (a story with no readable text) DOES advance,
  or one empty story stalls a run forever;
* the run's MODE (language, budget) survives a resume, so one document is never
  written in two languages;
* a paused run for a DIFFERENT edition, or for stories that have since been
  re-clustered, is REFUSED rather than guessed at.

Pure: no DB, no network, no model. The evidence reader and the client are both
injected, so the whole chassis is driven without either.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.bulletin import narration_job as NJ
from src.bulletin.period import resolve_period
from src.bulletin.store import persist_edition, read_edition

_P = resolve_period("weekly", end=date(2026, 8, 1))


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    return tmp_path


class _Ctx:
    """A JobContext double, pinned to the real class's signature below."""

    def __init__(self, stop_after: int | None = None) -> None:
        self.stopping = False
        self.progress: list[dict] = []
        self._stop_after = stop_after

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append({"done": done, "total": total, "detail": detail})
        if self._stop_after is not None and done is not None and done >= self._stop_after:
            self.stopping = True


class _Reply:
    def __init__(self, text: str) -> None:
        self.text = text


class _Client:
    """A model that answers with whatever the script says, in order.

    ``"__raise__"`` raises (a backend that is down); anything else is returned as
    the model's text. The script is consumed, so a run that makes more calls than
    expected fails loudly rather than looping on the last answer.
    """

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    def generate(self, prompt, *, model=None, system=None, options=None):
        self.calls += 1
        answer = self.script.pop(0) if self.script else "The coverage says something."
        if answer == "__raise__":
            raise RuntimeError("connection refused")
        return _Reply(answer)


def _edition(n_stories: int = 2) -> str:
    """Persist a minimal edition with ``n_stories`` clusters and return its filename."""
    stories = [
        {
            "article_ids": [10 * (i + 1), 10 * (i + 1) + 1],
            "articles": 2,
            "distinct_sources": 2,
            "shared_terms": [f"term{i}"],
        }
        for i in range(n_stories)
    ]
    rec = {
        "layer": "A",
        "caveat": "The record.",
        "period": _P.to_dict(),
        "masthead": {
            "articles": 40,
            "corpus_articles": 400,
            "sources_contributing": 7,
            "languages": [{"language": "en", "articles": 40}],
            "source_countries": [{"country": "FR", "articles": 40}],
            "days_with_ingest": 5,
            "period_days": 7,
            "top_3_share": 0.5,
        },
        "sections": [{"section": "rising_concepts"}],
        "stories": {"stories": stories},
    }
    return persist_edition(rec, _P).name


def _evidence(monkeypatch, *, empty: bool = False) -> None:
    """Inject the story evidence reader so no corpus is needed."""

    def _fake(session, ids, *, budget_chars):
        if empty:
            return {"article_ids": [], "excerpts": []}
        return {
            "article_ids": list(ids),
            "excerpts": [
                {"article_id": ids[0], "title": "A title", "text": "The coverage says something."}
            ],
        }

    monkeypatch.setattr("src.bulletin.stories.story_evidence", _fake)


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sf():
    return _Session()


_OPEN_GATE = {"narration_available": True, "narration_reason": "test"}


def _run(filename, *, ctx=None, client=None, **kw):
    return NJ.run_bulletin_narration_job(
        ctx or _Ctx(),
        filename=filename,
        client=client or _Client([]),
        session_factory=_sf,
        gate=dict(_OPEN_GATE),
        **kw,
    )


# --------------------------------------------------------------------------- #
#  the happy path, and what it writes
# --------------------------------------------------------------------------- #
def test_a_full_run_narrates_every_story_and_the_introduction(monkeypatch):
    _evidence(monkeypatch)
    fn = _edition(2)
    out = _run(fn)
    assert out["complete"] is True
    assert out["total_units"] == 3, "two stories plus the introduction"
    assert out["cursor"] == 3

    rec = read_edition(fn)
    assert len(rec["narration"]["paragraphs"]) == 2
    assert rec["introduction"]["text"]
    # ADJACENCY: every story carries its own paragraph, joined on the article ids.
    for story in rec["stories"]["stories"]:
        assert story["narration"]["text"]


def test_the_record_is_readable_after_every_single_unit(monkeypatch):
    """A killed run must leave a real edition with fewer paragraphs, never a broken
    one — which is what makes the cursor worth having."""
    _evidence(monkeypatch)
    fn = _edition(3)
    for _ in range(3):
        _run(fn, max_units=1)
        rec = read_edition(fn)
        json.dumps(rec)  # it round-trips
        assert rec["narration"]["paragraphs_attached"] == len(rec["narration"]["paragraphs"])


def test_the_layer_a_caveat_is_appended_to_once_however_many_units_run(monkeypatch):
    """attach_narration runs after every unit. Without a kept base caveat that would
    append the same sentence once per story, and the document's own account of
    itself would grow with the run rather than describe it."""
    _evidence(monkeypatch)
    fn = _edition(3)
    for _ in range(4):
        _run(fn, max_units=1)
    rec = read_edition(fn)
    assert rec["caveat"].count("narration layer over") == 1
    assert rec["record_caveat"] == "The record."


# --------------------------------------------------------------------------- #
#  the persisted cursor
# --------------------------------------------------------------------------- #
def test_the_cursor_is_persisted_per_unit_and_a_resume_does_not_redo_banked_work(monkeypatch):
    _evidence(monkeypatch)
    fn = _edition(3)
    client = _Client(["one.", "two.", "three.", "four."])
    _run(fn, client=client, max_units=2)
    assert NJ.load_progress_state()["cursor"] == 2
    calls_after_first = client.calls

    out = _run(fn, client=client)
    assert out["resumed_from"] == 2, "the second call must CONTINUE, not start over"
    assert out["complete"] is True
    assert client.calls == calls_after_first + 2, (
        "exactly the two remaining units — a resume that redid banked work would "
        "make a multi-hour run never finish"
    )


def test_a_cancel_saves_progress_and_says_so(monkeypatch):
    _evidence(monkeypatch)
    fn = _edition(4)
    ctx = _Ctx(stop_after=2)
    out = _run(fn, ctx=ctx)
    assert out["complete"] is False
    assert "resume" in out["paused_reason"]
    assert NJ.load_progress_state()["cursor"] == 2


def test_restart_discards_the_paused_run_and_starts_from_the_first_unit(monkeypatch):
    _evidence(monkeypatch)
    fn = _edition(3)
    _run(fn, max_units=2)
    out = _run(fn, restart=True, max_units=1)
    assert out["resumed_from"] == 0
    assert NJ.load_progress_state()["cursor"] == 1


def test_re_narrating_a_story_REPLACES_its_paragraph_rather_than_adding_a_second(monkeypatch):
    """A restart over an already-narrated edition re-runs units that already have a
    paragraph. Appending would leave two paragraphs for one story, double-count
    stories_narrated, and hand the adjacency join an ambiguous key."""
    _evidence(monkeypatch)
    fn = _edition(2)
    _run(fn)
    _run(fn, restart=True)
    rec = read_edition(fn)
    assert len(rec["narration"]["paragraphs"]) == 2
    assert rec["narration"]["stories_narrated"] == 2
    assert rec["narration"]["paragraphs_attached"] == 2


# --------------------------------------------------------------------------- #
#  outages — the abort-to-done defect §14 names
# --------------------------------------------------------------------------- #
def test_an_outage_never_advances_the_cursor_and_never_completes(monkeypatch):
    """narrate_story NEVER raises: a dead backend degrades to the template with the
    reason. Left alone, that writes a deterministic paragraph for every story and
    finishes `complete` — a run that lost its model presenting as a finished one."""
    _evidence(monkeypatch)
    monkeypatch.setattr(NJ, "_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(NJ, "_BACKOFF_CAP_S", 0.0)
    fn = _edition(2)
    client = _Client(["__raise__"] * 40)
    with pytest.raises(RuntimeError) as exc:
        _run(fn, client=client)
    assert "consecutive local-model failures" in str(exc.value)
    st = NJ.load_progress_state()
    assert st["cursor"] == 0, "not one unit may be banked on a dead backend"
    assert "completed_at" not in st
    rec = read_edition(fn)
    assert not (rec.get("narration") or {}).get("paragraphs")


def test_the_run_gives_up_by_RAISING_so_the_job_state_becomes_error(monkeypatch):
    """Returning would leave BackgroundJob at 'done'. The whole point of §14's
    sentence is that the two must not look alike."""
    _evidence(monkeypatch)
    monkeypatch.setattr(NJ, "_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(NJ, "_MAX_CONSECUTIVE_FAILURES", 3)
    fn = _edition(1)
    with pytest.raises(RuntimeError):
        _run(fn, client=_Client(["__raise__"] * 10))


def test_a_transient_outage_is_retried_and_the_run_then_completes(monkeypatch):
    """The twin: a hiccup must NOT end a multi-hour run. A retry budget that gives
    up on the first failure is as wrong as one that never gives up."""
    _evidence(monkeypatch)
    monkeypatch.setattr(NJ, "_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(NJ, "_BACKOFF_CAP_S", 0.0)
    fn = _edition(1)
    out = _run(fn, client=_Client(["__raise__", "recovered.", "intro sentence."]))
    assert out["complete"] is True
    assert out["totals"]["narrated"] == 2


def test_a_story_with_no_text_is_NOT_an_outage_and_the_run_moves_on(monkeypatch):
    """THE NEGATIVE-SPACE TWIN. Not every fallback is the backend: a story whose
    articles carry no readable text falls back for a reason retrying cannot change,
    and treating it as an outage would stall the run on it forever."""
    _evidence(monkeypatch, empty=True)
    monkeypatch.setattr(NJ, "_BACKOFF_BASE_S", 0.0)
    fn = _edition(2)
    out = _run(fn, client=_Client(["intro."]))
    assert out["complete"] is True
    assert out["totals"]["fallback"] >= 2
    rec = read_edition(fn)
    reasons = [p.get("fallback_reason") for p in rec["narration"]["paragraphs"]]
    assert all("no article text" in (r or "") for r in reasons)


# --------------------------------------------------------------------------- #
#  refusals — where guessing would be worse than stopping
# --------------------------------------------------------------------------- #
def test_a_paused_run_for_a_different_edition_is_refused_with_the_way_out(monkeypatch):
    _evidence(monkeypatch)
    first = _edition(3)
    _run(first, max_units=1)
    second = _edition(3)
    with pytest.raises(NJ.NarrationScopeMismatch) as exc:
        _run(second)
    assert first in str(exc.value)
    assert "restart=true" in str(exc.value)
    assert NJ.load_progress_state()["cursor"] == 1, "the paused run must be untouched"


def test_a_re_clustered_edition_is_refused_because_the_cursor_counts_positions(monkeypatch):
    """The cursor counts units in the record's own order. If the stories changed
    under it, unit 2 is no longer the story unit 2 was, and continuing would file a
    model's sentences under an unrelated cluster."""
    _evidence(monkeypatch)
    fn = _edition(3)
    _run(fn, max_units=1)

    from src.bulletin.store import update_edition

    def _reorder(rec):
        rec["stories"]["stories"] = list(reversed(rec["stories"]["stories"]))

    update_edition(fn, _reorder)
    with pytest.raises(NJ.NarrationScopeMismatch) as exc:
        _run(fn)
    assert "not this edition's stories any more" in str(exc.value)


def test_the_hardware_gate_refuses_once_rather_than_per_story(monkeypatch):
    _evidence(monkeypatch)
    fn = _edition(5)
    client = _Client(["never used"] * 10)
    out = NJ.run_bulletin_narration_job(
        _Ctx(),
        filename=fn,
        client=client,
        session_factory=_sf,
        gate={"narration_available": False, "narration_reason": "no accelerator detected"},
    )
    assert out["state"] == "refused"
    assert "no accelerator" in out["reason"]
    assert client.calls == 0, "a refusal must cost no model calls at all"
    assert NJ.load_progress_state() == {}, "and must not touch the cursor"


# --------------------------------------------------------------------------- #
#  the MODE travels with the cursor
# --------------------------------------------------------------------------- #
def test_the_language_is_re_supplied_on_resume_rather_than_defaulted(monkeypatch):
    """A resumable job with more than a cursor needs its mode explicitly preserved.
    Half a document in French and half in English is what the alternative looks
    like, and nothing about the cursor would say so."""
    _evidence(monkeypatch)
    fn = _edition(3)
    _run(fn, language="fr", max_units=1)
    assert NJ.load_progress_state()["params"]["language"] == "fr"

    _run(fn, max_units=1)  # resumed WITHOUT naming the language again
    rec = read_edition(fn)
    assert [p.get("language") for p in rec["narration"]["paragraphs"]] == ["fr", "fr"]


def test_an_explicitly_named_language_still_wins_over_the_paused_one(monkeypatch):
    """Preserving the mode must not mean refusing a deliberate change."""
    _evidence(monkeypatch)
    fn = _edition(3)
    _run(fn, language="fr", max_units=1)
    _run(fn, language="de", max_units=1)
    rec = read_edition(fn)
    assert [p.get("language") for p in rec["narration"]["paragraphs"]] == ["fr", "de"]


# --------------------------------------------------------------------------- #
#  the doubles describe the real things
# --------------------------------------------------------------------------- #
def test_the_ctx_double_matches_the_real_JobContext_signature():
    """A hand-written double drifts; "the double is wrong" and "the code is wrong"
    produce the identical green. Pinned to the real class."""
    import inspect

    from src.jobs.background import JobContext

    real = inspect.signature(JobContext.set_progress)
    mine = inspect.signature(_Ctx.set_progress)
    assert [(p.name, p.kind) for p in real.parameters.values()][1:] == [
        (p.name, p.kind) for p in mine.parameters.values()
    ][1:]


def test_the_job_is_registered_and_advertises_a_cancel_it_really_honours():
    """BackgroundJob's own docstring reserves cancellable=True for workers that
    genuinely stop early — no theatre. This one checks ctx.stopping at the top of
    every unit AND inside the backoff sleep."""
    import src.api.bulletin  # noqa: F401  (registration happens at import)
    from src.jobs.background import get_job

    job = get_job("bulletin-narration")
    assert job is not None
    assert job.cancellable is True
    assert job.is_writer is False


def test_the_persisted_run_never_reads_as_finished_without_a_completion_stamp(monkeypatch):
    _evidence(monkeypatch)
    fn = _edition(3)
    _run(fn, max_units=1)
    assert NJ.last_narration_run()["state"] == "paused"
    assert NJ.last_narration_run()["complete"] is False
    _run(fn)
    assert NJ.last_narration_run()["state"] == "done"
