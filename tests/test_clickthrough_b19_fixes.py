"""Batch B19 of the 2026-09-26 delegated click-through, pinned: the last tail. An import
item's own word (Q1) and a volume backup's phase and volume count (Q2) travel as keyed
phrases inside the job label's frame; a task's "model {model}" line travels as a frame
beside the unchanged English detail (Q5); the AI activity answer carries the keyed twin
of the label the pill names, and the coordinator's own lines are frames (Q7); the reader's
subjectivity method and caveat are keyed (Q9); the paused chip is one keyed string (Q10);
and the bulk qualification run's progress lines and ending reason travel as frames, the
English strings unchanged (Q12). /tasks' times (Q3), counts (Q6), session durations (Q8)
and the shipped-verdict plural (Q11) are behaviour, run in the node suite.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced first, in Chromium against a seeded state (fr, ar, zh). CI runs no
browser, so the behaviour runs as real, EXTRACTED code under node
(``tests/clickthrough_b19_node_test.js``); what is a contract between two files -- a
server frame and the key that translates it -- is pinned here from the server's own
functions.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(key: str) -> None:
    want = sorted(re.findall(r"\{(\w+)\}", key))
    for code, d in _locales().items():
        assert key in d, f"{code}.json has no key {key!r}"
        assert d[key].strip(), f"{code}.json has an empty value for {key!r}"
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
            f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
        )


def _frame_keys(frame: str | None, values: dict | None) -> list[str]:
    """Every key a frame and its nested keyed phrases need, depth first."""
    if not frame:
        return []
    out = [frame]
    for v in (values or {}).values():
        if isinstance(v, dict) and v.get("i18n"):
            out += _frame_keys(v["i18n"], v.get("vars"))
    return out


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b19_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- Q1: the import item's own word ---------------------------------------------------- #

@pytest.mark.parametrize("sent,word", [
    ("Large data", "Large data"),
    ("Données volumineuses", "Large data"),     # queued from a French page
    ("大数据", "Large data"),                    # ... or a Chinese one
    ("Infolettres", "Newsletters"),
])
def test_an_import_item_word_goes_out_as_its_key_in_any_language(monkeypatch, sent, word):
    import src.api.jobs as jobs
    import src.backup.import_queue as iq

    class _Q:
        def status(self):
            return {"state": "running", "items_total": 2, "items_done": 0, "stages_done": 1, "stages_total": 4,
                    "current": {"id": "0-blobs", "kind": "blobs", "path": "/media/usb/oo", "label": sent},
                    "live": {}}

    monkeypatch.setattr(iq, "get_import_queue", lambda: _Q())
    (row,) = jobs._import_queue_jobs()
    assert row["label"] == f"Importing {sent}", "the English label is the API's answer, unchanged"
    assert row["label_i18n"] == "Importing {label}"
    assert row["label_vars"] == {"label": {"i18n": word}}
    _keyed_everywhere(word)


def test_a_file_name_stays_data(monkeypatch):
    import src.api.jobs as jobs
    import src.backup.import_queue as iq

    class _Q:
        def status(self):
            return {"state": "running", "items_total": 1, "items_done": 0, "stages_done": 0, "stages_total": 3,
                    "current": {"kind": "corpus", "path": "/x/corpus-2026.oo", "label": "corpus-2026.oo"}}

    monkeypatch.setattr(iq, "get_import_queue", lambda: _Q())
    (row,) = jobs._import_queue_jobs()
    assert row["label_vars"] == {"label": "corpus-2026.oo"}


# --- Q2: the volume backup's phase and volume count ------------------------------------ #

def _volume_row(monkeypatch, mode, phase, vols):
    import src.api.jobs as jobs
    import src.backup.volume_job as vj

    class _V:
        def status(self):
            p = {"phase": phase} if phase else {}
            if vols:
                p["volumes_written"] = vols
            return {"state": "running", "running": True, "mode": mode, "progress": p}

    monkeypatch.setattr(vj, "get_volume_manager", lambda: _V())
    (row,) = jobs._volume_backup_jobs()
    return row


def test_a_volume_backup_label_is_keyed_beside_the_unchanged_english(monkeypatch):
    row = _volume_row(monkeypatch, "backup", "parity", 5)
    assert row["label"] == "Backing up (volumes + parity) — parity, 5 volumes"
    assert row["label_i18n"] == "{verb} — {phase}, {volumes}"
    assert row["label_vars"] == {"verb": {"i18n": "Backing up (volumes + parity)"},
                                 "phase": {"i18n": "Writing parity…"},
                                 "volumes": {"i18n": "{n} volumes", "vars": {"n": 5}}}
    one = _volume_row(monkeypatch, "backup", "volumes", 1)
    assert one["label_vars"]["volumes"] == {"i18n": "{n} volume", "vars": {"n": 1}}, "one volume is not 'volumes'"
    for key in _frame_keys(row["label_i18n"], row["label_vars"]) + _frame_keys(one["label_i18n"], one["label_vars"]):
        _keyed_everywhere(key)


def test_a_restore_phase_and_an_unnamed_stage(monkeypatch):
    merging = _volume_row(monkeypatch, "restore", "merging", None)
    assert merging["label"] == "Restoring — merging"
    assert merging["label_i18n"] == "{verb} — {phase}"
    assert merging["label_vars"] == {"verb": {"i18n": "Restoring"}, "phase": {"i18n": "Merging (additive)…"}}
    # A sub-second housekeeping stage the backup dialog does not name either is left out
    # of the keyed label -- never shown as its code.
    stage = _volume_row(monkeypatch, "restore", "corpus_epoch_bump", None)
    assert stage["label"] == "Restoring — corpus_epoch_bump"
    assert stage["label_i18n"] == "Restoring" and stage["label_vars"] == {}
    for row in (merging, stage):
        for key in _frame_keys(row["label_i18n"], row["label_vars"]):
            _keyed_everywhere(key)


def test_every_named_volume_phase_is_keyed_x12():
    import src.api.jobs as jobs

    for table in (jobs._VOLUME_BACKUP_PHASES, jobs._VOLUME_RESTORE_PHASES):
        for key in table.values():
            _keyed_everywhere(key)
    # The in-app dialog names the same phases with the same keys (app-backup.js).
    backup_js = read_static("app-backup.js")
    for key in set(jobs._VOLUME_BACKUP_PHASES.values()) | set(jobs._VOLUME_RESTORE_PHASES.values()):
        assert f't("{key}")' in backup_js, f"{key!r} is not the dialog's own key"


# --- Q5: the model detail line ---------------------------------------------------------- #

def test_a_task_detail_frame_reaches_the_job_row():
    import src.api.jobs as jobs
    from src.monitoring import tasks

    tok = tasks.register("llm", "Summarizing 12 article(s)", detail="model llama3:8b", total=12,
                         label_i18n="Summarizing {n} article(s)", label_vars={"n": 12},
                         detail_i18n="model {model}", detail_vars={"model": "llama3:8b"})
    try:
        (row,) = [r for r in jobs._task_jobs() if r["id"] == f"task:{tok}"]
        assert row["detail"] == "model llama3:8b", "the English detail is unchanged"
        assert row["detail_i18n"] == "model {model}" and row["detail_vars"] == {"model": "llama3:8b"}
        # A new detail replaces its frame: an old frame would write the OLD sentence.
        tasks.update(tok, detail="warming up")
        (row,) = [r for r in jobs._task_jobs() if r["id"] == f"task:{tok}"]
        assert row["detail"] == "warming up" and "detail_i18n" not in row
    finally:
        tasks.finish(tok)
    _keyed_everywhere("model {model}")


def test_a_background_job_publishes_a_framed_detail_and_keeps_the_english():
    from src.jobs.background import BackgroundJob, Framed, JobContext

    job = BackgroundJob("b19-framed-detail", "x", lambda ctx: None)
    ctx = JobContext(job)
    ctx.set_progress(detail=Framed("model m1", "model {model}", model="m1"))
    st = job.status()
    assert st["detail"] == "model m1" and type(st["detail"]) is str
    assert st["detail_i18n"] == "model {model}" and st["detail_vars"] == {"model": "m1"}
    ctx.set_progress(detail="plain")
    st = job.status()
    assert st["detail"] == "plain" and st["detail_i18n"] is None and st["detail_vars"] is None


def test_every_model_detail_producer_sends_its_frame():
    llm = (_ROOT / "src" / "api" / "llm.py").read_text(encoding="utf-8")
    ai = (_ROOT / "src" / "api" / "ai.py").read_text(encoding="utf-8")
    sites = llm.count('detail=f"model {model}"') + ai.count('detail=f"model {model}"')
    framed = (llm.count('detail_i18n="model {model}", detail_vars={"model": model}')
              + ai.count('detail_i18n="model {model}", detail_vars={"model": model}'))
    assert sites == framed == 5, (sites, framed)
    assert 'detail=Framed(f"model {mdl}", "model {model}", model=mdl)' in ai


# --- Q7: what the AI pill names ------------------------------------------------------------ #

def test_the_activity_answer_carries_the_label_frame():
    pytest.importorskip("fastapi")
    from src.api.llm import llm_activity
    from src.monitoring import tasks

    tok = tasks.register("llm", "Summarizing “Harbour festival”",
                         label_i18n="Summarizing “{title}”", label_vars={"title": "Harbour festival"})
    try:
        a = llm_activity()
    finally:
        tasks.finish(tok)
    assert a["label"] == "Summarizing “Harbour festival”"
    assert a["label_i18n"] == "Summarizing “{title}”" and a["label_vars"] == {"title": "Harbour festival"}


def test_every_batch_hold_reason_is_a_key():
    """A hold reason is the pill's label while a user batch owns the model; it is a fixed
    sentence, written through t() on the page, so each one must be keyed."""
    reasons = set()
    for path in (_ROOT / "src").rglob("*.py"):
        for m in re.finditer(r'user_batch_hold\(\s*"([^"]+)"\s*\)', path.read_text(encoding="utf-8")):
            reasons.add(m.group(1))
    llm = (_ROOT / "src" / "api" / "llm.py").read_text(encoding="utf-8")
    assert 'user_batch_hold(f"bulk {op}")' in llm
    reasons |= {"bulk summarize", "bulk translate", "background AI sweeps", "all enabled sweeps are up to date"}
    assert len(reasons) >= 8, reasons
    for r in reasons:
        _keyed_everywhere(r)


def test_the_coordinator_lines_the_pill_names_are_frames():
    src = (_ROOT / "src" / "ai_layer" / "coordinator.py").read_text(encoding="utf-8")
    assert 'detail=Framed("all enabled sweeps are up to date",' in src
    assert '"turn {turns} — {n} sweep advanced" if len(due) == 1 else "turn {turns} — {n} sweeps advanced"' in src
    for key in ("turn {turns} — {n} sweep advanced", "turn {turns} — {n} sweeps advanced"):
        _keyed_everywhere(key)


def test_the_pill_owns_its_text_and_is_repainted_on_a_switch():
    index = read_static("index.html")
    assert re.search(r'<span id="llm"[^>]*\bdata-i18n-dyn\b', index), (
        "the walker reverted the pill's working title to the markup's 'AI status'"
    )
    body = strip_comments(function_body(read_static("app-ai-tools.js"), "_paintAiPill"))
    assert 'el.textContent = t("AI")' in body and "_jobLabel(_aiBusyLabel, t)" in body
    boot = read_static("app-boot.js")
    assert 'if (typeof _paintAiPill === "function") _paintAiPill();' in boot


# --- Q9: the subjectivity method and caveat -------------------------------------------------- #

def test_the_subjectivity_method_and_caveat_are_keyed_and_translated():
    from src.analytics.subjectivity import _CAVEAT, _METHOD

    for key in (_METHOD, _CAVEAT):
        _keyed_everywhere(key)
        for code, d in _locales().items():
            if code != "en":
                assert d[key] != key, f"{code}.json leaves {key[:30]!r}… in English"
    body = function_body(read_static("reader.js"), "renderSubjectivity")
    assert "esc(T((d && d.method)" in body and "esc(T((d && d.caveat)" in body


# --- Q10: the paused chip ---------------------------------------------------------------------- #

def test_the_paused_chip_is_one_keyed_string():
    body = strip_comments(function_body(read_static("app-core.js"), "_paintActivity"))
    assert 'T("Collecting paused…")' in body
    assert 'T("Collecting paused") + "…"' not in body
    _keyed_everywhere("Collecting paused…")


# --- Q12: the qualification run's lines -------------------------------------------------------- #

def _run_qualification(monkeypatch):
    import src.catalog.qualify_job as qj
    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.jobs.background import BackgroundJob, JobContext
    from src.scheduler import memguard

    job = BackgroundJob("b19-qualify", "x", lambda ctx: None)
    seen: list[dict] = []

    class _Ctx(JobContext):
        def set_progress(self, **kw):
            super().set_progress(**kw)
            seen.append(job.status())

    def _pass(db, fetcher, n, now, **kw):
        activate_kill_switch()      # the next turn of the loop sees airplane mode
        return {"evaluated": 5, "qualified": 3, "disqualified": 1, "no_evidence": 1, "trial_fetch_errors": 0}

    class _Sess:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(qj, "qualification_pass", _pass)
    monkeypatch.setattr(qj, "initial_backlog_estimate", lambda db: {"unqualified": 40, "due_disqualified": 0})
    monkeypatch.setattr(qj, "freeze_cohort", lambda *a, **k: {})
    monkeypatch.setattr(memguard.memory_guard, "poll", lambda: False)
    clear_kill_switch()
    try:
        result = qj.run_bulk_qualification(_Ctx(job), fetcher=object(), session_factory=_Sess, sleep_s=0)
    finally:
        clear_kill_switch()
    return seen, result


def test_the_qualification_lines_travel_as_frames_beside_the_unchanged_english(monkeypatch):
    seen, result = _run_qualification(monkeypatch)
    first, so_far, final = seen[0], seen[1], seen[-1]
    assert first["detail"] == "starting…" and first["detail_i18n"] == "starting…"
    assert so_far["detail"] == "3 qualified · 1 disqualified · 1 no-evidence so far"
    assert so_far["detail_i18n"] == "so far: {qualified} · {disqualified} · {no_evidence}"
    assert so_far["detail_vars"] == {
        "qualified": {"i18n": "{n} sources qualified", "vars": {"n": 3}},
        "disqualified": {"i18n": "{n} source disqualified", "vars": {"n": 1}},
        "no_evidence": {"i18n": "{n} source with no evidence yet", "vars": {"n": 1}},
    }
    airplane = "airplane mode engaged — progress is saved, start again to resume"
    assert final["detail"] == f"{airplane} (3 qualified · 1 disqualified · 1 no-evidence)"
    assert final["detail_i18n"] == "{reason} ({qualified} · {disqualified} · {no_evidence})"
    assert final["detail_vars"]["reason"] == {"i18n": airplane, "vars": {}}
    assert result["paused_reason"] == airplane and type(result["paused_reason"]) is str
    assert result["paused_reason_i18n"] == airplane and result["paused_reason_vars"] == {}
    json.dumps(result)      # the result rides the status endpoint as JSON
    for st in seen:
        for key in _frame_keys(st["detail_i18n"], st["detail_vars"]):
            _keyed_everywhere(key)


@pytest.mark.parametrize("key", [
    "cancelled — progress is saved (each source's status), start again to resume",
    "paused: {reason} — progress is saved, start again once memory recovers",
    "declined on this machine: {reason} — nothing was judged; restart the app with {env}=1 to run it anyway",
    "stopped after {n} consecutive batches with no evidence to judge — the remaining candidates could not be "
    "evaluated (no reachable feed / no prior articles); they stay unqualified and will be retried on a later run",
    "finished: nothing left to judge ({qualified} · {disqualified} · {no_evidence})",
])
def test_every_other_qualification_frame_is_sent_and_keyed(key):
    src = (_ROOT / "src" / "catalog" / "qualify_job.py").read_text(encoding="utf-8")
    flat = re.sub(r'"\s*\n\s*"', "", src)       # adjacent literals joined, as Python joins them
    assert key in flat, f"qualify_job.py no longer sends {key!r}"
    _keyed_everywhere(key)


# --- Q3 / Q6 / Q8: the new unit and direction frames ------------------------------------------- #

@pytest.mark.parametrize("key", [
    "in {t}", "{t} ago", "running for {t}", "{n} core", "{n} cores", "{n} thread", "{n} threads", "{n} d",
    "{growth}× ({window} vs {baseline})",
])
def test_the_new_frames_are_keyed_x12(key):
    _keyed_everywhere(key)


def test_russian_and_arabic_many_frames_are_labels():
    """A count's 'many' frame reads as a label in ru/ar ("ядер: {n}"), as B17's pairs do:
    one plural form cannot agree with every number there."""
    loc = _locales()
    for key in ("{n} volumes", "{n} cores", "{n} threads"):
        for code in ("ru", "ar"):
            assert loc[code][key].endswith(": {n}"), (code, key, loc[code][key])
