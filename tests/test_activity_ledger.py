"""The Activity Ledger's shape and grammar (0.5 slice S05-09 S5, Q1120 = a).

Three things are pinned here:

1. THE GRAMMAR. An entry in a category the plan reserves for human judgment
   (source admission, keyword pruning, coordination) may not claim a decision: its
   sentence ends in a measurement verb and carries no decision verb. Every entry has
   all seven fields, and ``undo`` agrees with ``reversible``. Checked by construction
   (``LedgerEntry`` raises), and by a mutation sweep over every decision verb.
2. COVERAGE. An automated action without a ledger entry fails here: every kind of the
   scheduler's housekeeping lane, every pass-tail ride-along the scheduler reports and
   every background task it registers must map to a registered action, and every
   registered action must have a call site that records it.
3. TRANSLATION. Every sentence and frame an entry can carry is a key in all twelve
   locales, with its placeholders intact (the window writes entries in the UI language).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from src.monitoring import activity_ledger as al
from tests.js_source_helper import function_body, object_literal

_ROOT = Path(__file__).resolve().parent.parent
_RUNNER = _ROOT / "src" / "scheduler" / "runner.py"


def _entry(**kw):
    base = {
        "action": "test", "category": "collection", "what_happened": "Collection pass: 3 stored",
        "why": "Why.", "touched": "Touched.", "caveat": "Caveat.", "budget": "Budget.",
        "reversible": False,
    }
    base.update(kw)
    return al.LedgerEntry(**base)


# --------------------------------------------------------------------------- #
#  1. The grammar
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("category", sorted(al.RESERVED_CATEGORIES))
@pytest.mark.parametrize("verb", sorted(al.DECISION_VERBS))
def test_a_reserved_entry_ending_in_a_decision_verb_is_refused(category, verb):
    with pytest.raises(al.LedgerGrammarError):
        _entry(category=category, what_happened=f"Candidate sources: 3 {verb}")


@pytest.mark.parametrize("category", sorted(al.RESERVED_CATEGORIES))
@pytest.mark.parametrize("verb", sorted(al.DECISION_VERBS))
def test_a_decision_verb_anywhere_in_a_reserved_sentence_is_refused(category, verb):
    """Not only at the end: "3 enabled and 2 measured" still claims the decision."""
    with pytest.raises(al.LedgerGrammarError):
        _entry(category=category, what_happened=f"Sources: 3 {verb}, 2 measured")


@pytest.mark.parametrize("category", sorted(al.RESERVED_CATEGORIES))
@pytest.mark.parametrize("verb", sorted(al.MEASUREMENT_VERBS))
def test_a_reserved_entry_ending_in_a_measurement_verb_is_accepted(category, verb):
    e = _entry(category=category, what_happened=f"Candidate sources: 3 {verb}.")
    assert e.as_record()["reserved"] is True


@pytest.mark.parametrize("category", sorted(al.RESERVED_CATEGORIES))
def test_a_reserved_entry_ending_in_any_other_word_is_refused(category):
    """An allowlist, not only a denylist: a verb nobody thought to bar is still refused."""
    for text in ("Sources: 3 activated", "Sources handled", "3 sources"):
        with pytest.raises(al.LedgerGrammarError):
            _entry(category=category, what_happened=text)


def test_a_non_reserved_category_may_say_what_it_did():
    assert _entry(category="maintenance", what_happened="Orphan rows removed").category == "maintenance"


@pytest.mark.parametrize("field", ["what_happened", "why", "touched", "caveat", "budget"])
def test_every_field_is_required(field):
    with pytest.raises(al.LedgerGrammarError):
        _entry(**{field: "  "})


def test_undo_agrees_with_reversible():
    with pytest.raises(al.LedgerGrammarError):
        _entry(reversible=True)
    with pytest.raises(al.LedgerGrammarError):
        _entry(reversible=False, undo="Settings -> Sources")
    assert _entry(reversible=True, undo="Settings -> Sources").undo


def test_an_unknown_category_is_refused():
    with pytest.raises(al.LedgerGrammarError):
        _entry(category="decisions")


def test_the_registry_itself_obeys_the_grammar():
    """Validated at import too; re-run here so a failure names the action."""
    al.validate_registry()
    for aid, a in al.ACTIONS.items():
        al.check_grammar(a.category, a.what)
        assert a.category in al.CATEGORIES, aid


def test_every_reserved_action_is_a_measurement():
    reserved = {aid for aid, a in al.ACTIONS.items() if a.category in al.RESERVED_CATEGORIES}
    # Today's reserved actions, named so a new one is a visible diff here.
    assert reserved == {"lane:world_discovery", "lane:qualification", "discovery"}


def test_a_deletion_in_a_reserved_category_is_still_stated():
    """The grammar bars CLAIMING a decision in the sentence; it must not push a real
    change out of sight. The offline discovery pass deletes pending candidates its
    noise filters reject, and the entry's `touched` says so in so many words."""
    e = al.build_entry("discovery", {"enabled": True, "created": 4, "pruned_noise": 2})
    assert e.what_happened.endswith("staged")
    assert "2 pending candidate(s)" in e.touched and "deleted" in e.touched


# --------------------------------------------------------------------------- #
#  Building and storing entries
# --------------------------------------------------------------------------- #


def test_an_entry_carries_its_counts_and_its_frames():
    e = al.build_entry("lane:qualification",
                       {"enabled": True, "evaluated": 5, "qualified": 2, "disqualified": 1},
                       type("S", (), {"qualification_per_pass": 5,
                                      "qualification_recheck_per_pass": 2})())
    r = e.as_record()
    assert r["what_happened"] == "Qualification criteria: 5 candidate source(s) measured"
    assert r["touched"] == "Qualification stamps: 2 met the criteria, 1 did not"
    assert r["budget"] == "Up to 5 candidate(s) and 2 re-check(s) per pass"
    assert r["frames"]["what_happened"] == al.ACTIONS["lane:qualification"].what
    assert r["vars"]["evaluated"] == 5 and r["reserved"] is True
    assert r["reversible"] is False and r["undo"] is None


def test_a_skip_and_a_failure_read_as_such():
    s = al.build_entry("lane:world_discovery", {"enabled": True, "skipped": "airplane mode engaged"})
    assert s.what_happened == al.SKIPPED_FRAME and s.note == "airplane mode engaged"
    f = al.build_entry("lane:crawl", {"error": True})
    assert f.what_happened == al.FAILED_FRAME


def test_a_result_of_an_odd_shape_reads_as_zeros():
    e = al.build_entry("collection-pass", {"articles_stored": "many", "sources_processed": None})
    assert e.what_happened == "Collection pass: 0 article(s) stored from 0 source(s) read"
    assert al.build_entry("collection-pass", None).vars["stored"] == 0


def test_counts_only_nothing_from_the_result_leaks_in(tmp_path, monkeypatch):
    """The file is plaintext in the data folder: no URL, domain, title or query."""
    monkeypatch.setattr(al, "data_dir", lambda: tmp_path)
    al.record("discovery", {"enabled": True, "created": 1,
                            "citation": [{"domain": "secret.example", "url": "https://secret.example/x"}],
                            "catalog": ["https://leak.example"]})
    text = (tmp_path / al.LEDGER_FILE).read_text(encoding="utf-8")
    assert "secret.example" not in text and "leak.example" not in text and "http" not in text


def test_record_appends_and_reads_back_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "data_dir", lambda: tmp_path)
    al.record("collection-pass", {"articles_stored": 1, "sources_processed": 1})
    al.record("briefing", {"cards": [{}, {}, {}]})
    entries = al.read_entries()
    assert [e["action"] for e in entries] == ["briefing", "collection-pass"]
    assert entries[0]["what_happened"] == "Home briefing: 3 card(s) surfaced"
    for line in (tmp_path / al.LEDGER_FILE).read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["schema"] == al.LEDGER_SCHEMA


def test_record_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(al, "data_dir", lambda: blocker)  # a FILE where a folder should be
    assert al.record("collection-pass", {}) is None
    assert al.record("no-such-action", {}) is None


def test_the_file_is_compacted(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "data_dir", lambda: tmp_path)
    for i in range(12):
        al.record("collection-pass", {"articles_stored": i})
    assert al.compact_if_needed(max_lines=5) == 7
    assert [e["vars"]["stored"] for e in al.read_entries()] == [11, 10, 9, 8, 7]


def test_the_endpoint_serves_the_newest_entries(tmp_path, monkeypatch):
    from src.api import jobs

    monkeypatch.setattr(al, "data_dir", lambda: tmp_path)
    for i in range(3):
        al.record("collection-pass", {"articles_stored": i})
    out = jobs.jobs_ledger(limit=2)
    assert out["count"] == 2 and [e["vars"]["stored"] for e in out["entries"]] == [2, 1]
    assert set(out["reserved"]) == set(al.RESERVED_CATEGORIES)


# --------------------------------------------------------------------------- #
#  2. Coverage: an automated action without an entry fails here
# --------------------------------------------------------------------------- #


def test_every_housekeeping_kind_is_a_registered_action():
    from src.scheduler.runner import _LANE_KINDS, _LANE_STEPS

    for kind in set(_LANE_STEPS) | set(_LANE_KINDS):
        assert f"lane:{kind}" in al.ACTIONS, f"housekeeping kind {kind!r} has no ledger action"


def test_the_lane_writes_one_entry_per_kind_it_runs(tmp_path, monkeypatch):
    from src.scheduler import runner

    monkeypatch.setattr(al, "data_dir", lambda: tmp_path)
    ran = []

    def ok(kind):
        def step(session, fetcher, settings):
            ran.append(kind)
            return {"enabled": True}
        return step

    def boom(session, fetcher, settings):
        raise RuntimeError("down")

    steps = {k: ok(k) for k in runner._LANE_STEPS}
    steps["crawl"] = boom
    steps["law"] = lambda s, f, c: {"enabled": False}  # switched off: did not act
    monkeypatch.setattr(runner, "_LANE_STEPS", steps)
    monkeypatch.setattr(runner, "_lane_pending_kinds", lambda settings: set(steps))
    monkeypatch.setattr("src.ingest.fetch_release.wrap_fetcher", lambda f, s: f)

    class _Session:
        def rollback(self):
            pass

    runner.run_housekeeping_lane(_Session(), object(), runner.SchedulerSettings())
    by_action = {e["action"]: e for e in al.read_entries(limit=100)}
    expected = {f"lane:{k}" for k in steps if k != "law"}
    assert set(by_action) == expected
    assert by_action["lane:crawl"]["what_happened"] == al.FAILED_FRAME


#: The pass-tail ride-alongs the scheduler reports in its run result, and the action
#: each one records. A NEW `result["..."] = ...` key in runner.py must be listed here,
#: with its action, or with the reason it is not a separate automated action.
_RESULT_KEYS = {
    "discovery": "discovery",
    "ai_auto": "ai-auto",
    "langdetect_auto": "langdetect-auto",
    "source_enrich": "source-enrichment",
}
_RESULT_KEYS_NOT_ACTIONS = {
    # The operator's own opt-in export of the articles the pass just stored (export_dir,
    # off by default): the pass's own output, counted in the collection-pass entry.
    "delta_export",
}
#: Background tasks the scheduler registers, and their action.
_BG_TASKS = {
    "qualification": "lane:qualification", "backfill": "lane:backfill", "briefing": "briefing",
    # The lane itself: one entry per kind it runs (test_the_lane_writes_one_entry_per_kind_it_runs).
    "housekeeping": "lane:*",
}


def _runner_tree():
    return ast.parse(_RUNNER.read_text(encoding="utf-8"))


def test_every_ride_along_the_scheduler_reports_is_ledgered():
    keys = set()
    for node in ast.walk(_runner_tree()):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "result" and isinstance(tgt.slice, ast.Constant)
                        and isinstance(tgt.slice.value, str)):
                    keys.add(tgt.slice.value)
    unknown = keys - set(_RESULT_KEYS) - _RESULT_KEYS_NOT_ACTIONS
    assert not unknown, f"new pass-tail ride-along(s) with no ledger action: {sorted(unknown)}"
    for action in _RESULT_KEYS.values():
        assert action in al.ACTIONS


def test_every_background_task_the_scheduler_starts_is_ledgered():
    src = _RUNNER.read_text(encoding="utf-8")
    kinds = set(re.findall(r'_bgtasks\.register\(\s*"([a-z_-]+)"', src))
    assert kinds, "the scan found no task registrations; the pattern has drifted"
    assert kinds <= set(_BG_TASKS), f"unledgered background task kind(s): {sorted(kinds - set(_BG_TASKS))}"


def test_every_registered_action_has_a_call_site():
    src = _RUNNER.read_text(encoding="utf-8")
    recorded = set(re.findall(r'_activity\(\s*"([a-z:_-]+)"', src))
    if '_activity(f"lane:{kind}"' in src:
        recorded |= {a for a in al.ACTIONS if a.startswith("lane:")}
    missing = set(al.ACTIONS) - recorded
    assert not missing, f"registered action(s) nothing records: {sorted(missing)}"
    assert recorded <= set(al.ACTIONS), f"recorded but unregistered: {sorted(recorded - set(al.ACTIONS))}"


def test_the_scheduler_hook_is_silent_and_skips_what_did_not_act(monkeypatch):
    from src.scheduler import runner

    calls = []
    monkeypatch.setattr(al, "record", lambda *a, **k: calls.append(a))
    runner._activity("discovery", {"enabled": False})
    assert calls == []
    runner._activity("discovery", {"enabled": True, "created": 1})
    assert len(calls) == 1

    def boom(*a, **k):
        raise RuntimeError("disk")

    monkeypatch.setattr(al, "record", boom)
    runner._activity("discovery", {"enabled": True})  # must not raise


# --------------------------------------------------------------------------- #
#  3. Translation
# --------------------------------------------------------------------------- #


def _locales():
    d = _ROOT / "src" / "static" / "locales"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))}


def _ledger_strings():
    out = {al.SKIPPED_FRAME, al.FAILED_FRAME}
    for a in al.ACTIONS.values():
        out |= {a.what, a.touched, a.why, a.caveat, a.budget}
        if a.undo:
            out.add(a.undo)
    return sorted(out)


@pytest.mark.parametrize("key", _ledger_strings())
def test_every_ledger_sentence_is_keyed_x12(key):
    want = sorted(re.findall(r"\{(\w+)\}", key))
    for code, d in _locales().items():
        assert key in d and d[key].strip(), f"{code}.json has no key {key!r}"
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, f"{code}.json changes the placeholders of {key!r}"


def test_the_window_names_every_category_and_is_keyed_x12():
    js = (_ROOT / "src" / "static" / "taskmanager.js").read_text(encoding="utf-8")
    block = object_literal(js, "LEDGER_CATEGORY")
    labels = dict(re.findall(r'"([a-z-]+)":\s*"([^"]+)"', block))
    assert set(labels) == set(al.CATEGORIES)
    for code, d in _locales().items():
        for label in labels.values():
            assert label in d, f"{code}.json has no category label {label!r}"


def test_the_ledger_lens_lives_in_the_existing_task_manager():
    """A lens inside the EXISTING window (invariants #4 and #20 untouched): one more tab on
    /tasks, reading the one endpoint, with every field -- the caveat included -- drawn
    visibly, never behind a toggle."""
    html = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    js = (_ROOT / "src" / "static" / "taskmanager.js").read_text(encoding="utf-8")
    assert 'data-panel="ledger" role="tab" data-i18n>Ledger' in html and 'id="p-ledger"' in html
    body = function_body(js, "renderLedger")
    assert "/api/jobs/ledger" in body
    for label in ("Why", "Touched", "Budget", "Caveat", "Undo"):
        assert f'row("{label}"' in body, f"the {label} field is not drawn"
    assert "hidden" not in body and "<details" not in body, "a ledger field is behind a toggle"
