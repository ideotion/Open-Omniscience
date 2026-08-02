"""Per-language task gates, read off the comparative bench (E-S3, ruling 16).

The who/where/when extractor has been eval-gated since B6: a language the harness
never cleared is honestly skipped. This module extends that shape to the other
per-language AI tasks, using the E-S2 bench artifact as the evidence — the same
tri-state, the same conservatism:

* ``True``  — MEASURED and cleared for this language.
* ``False`` — MEASURED and failed a stated floor.
* ``None``  — NOT MEASURED. Refuses, exactly like a failure, but says *unmeasured*
  rather than *failed*. The third state exists so the reason can be honest, never
  to grant permission on an absence of measurement.

WHICH DIRECTION EACH TASK IS GATED IN is not a detail — it is what makes each gate
mean anything:

* **triage** and **source tags** know the item's language BEFORE the call
  (``Keyword.language`` / ``Source.language``), so they gate SELECTION: do not ask
  about a language this model cannot judge.
* **language detection** does NOT know the language before the call — that is the
  whole question — so gating its INPUT is incoherent. It gates the ANSWER: refuse
  to STORE a label the bench measured this model getting wrong. That needs
  PRECISION over the model's own labels, which is why the bench records
  ``by_answer`` beside ``by_language``; applying a recall figure to an answer would
  be a silent substitution of one measure for another.

THE FLOORS BELOW ARE JUDGEMENTS, and are written here rather than buried so the
first real bench run can revise them on evidence. They are deliberately low: the
gold sets are small, and a floor invented above what their power supports would be
a number nobody measured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

#: Share of the items ASKED that must come back as a valid, echo-matched answer for
#: a language to be worth asking about. Below this the model is not judging that
#: language, it is garbling it. A judgement, revisable on the first real bench run.
MIN_FORMAT_VALIDITY = 0.5

#: Share of a label's uses that must be CORRECT before that label may be stored.
#: Precision, not recall (see the module docstring). A judgement — but note that
#: below 0.5 the label is wrong more often than right, which is a floor no reading
#: of the evidence makes generous.
MIN_ANSWER_PRECISION = 0.5

#: Below this many observations a per-language figure is reported but NOT used as a
#: gate: one case deciding a language's fate is a coin toss wearing a number.
MIN_OBSERVATIONS = 2

GATED_TASKS: tuple[str, ...] = ("triage", "source_tags", "langdetect")


def _unmeasured(what: str) -> dict:
    return {
        "active": None,
        "reason": f"no bench evidence for {what} — UNMEASURED, never tested",
        "checks": [],
    }


def _from_validity(rows: dict, *, task: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for lang, m in (rows or {}).items():
        if not isinstance(m, dict):
            continue
        asked = int(m.get("asked") or 0)
        validity = m.get("format_validity")
        if validity is None or asked < MIN_OBSERVATIONS:
            out[lang] = _unmeasured(
                f"{task} in {lang}"
                + (f" (only {asked} item(s) benched)" if asked else "")
            )
            continue
        check = f"format validity {validity} over {asked} item(s)"
        if validity < MIN_FORMAT_VALIDITY:
            out[lang] = {
                "active": False,
                "reason": f"{task} failed the bench in {lang}: {check}, below {MIN_FORMAT_VALIDITY}",
                "checks": [check],
            }
        else:
            out[lang] = {
                "active": True,
                "reason": f"{task} cleared the bench in {lang}: {check}",
                "checks": [check],
            }
    return out


def _from_precision(rows: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for label, m in (rows or {}).items():
        if not isinstance(m, dict):
            continue
        answered = int(m.get("answered") or 0)
        precision = m.get("precision")
        if precision is None or answered < MIN_OBSERVATIONS:
            out[label] = _unmeasured(
                f"the label {label!r}"
                + (f" (used on only {answered} case(s) in the bench)" if answered else "")
            )
            continue
        check = f"precision {precision} over {answered} use(s) of this label"
        if precision < MIN_ANSWER_PRECISION:
            out[label] = {
                "active": False,
                "reason": f"the label {label!r} failed the bench: {check}, below {MIN_ANSWER_PRECISION}",
                "checks": [check],
            }
        else:
            out[label] = {
                "active": True,
                "reason": f"the label {label!r} cleared the bench: {check}",
                "checks": [check],
            }
    return out


def _pick_pair(report: dict | None, *, model: str | None, backend: str | None) -> dict | None:
    """The bench row for a (model, backend), or the only row when unambiguous.

    Never falls back to "some other model's numbers": a gate built from a different
    model's measurements would be a fabricated verdict about the model actually
    running. When the caller names a model that was not benched, the answer is no
    evidence — which the tri-state can say.
    """
    results = (report or {}).get("results") or {}
    if not results:
        return None
    if model:
        for row in results.values():
            if row.get("model") != model:
                continue
            if backend and row.get("backend") != backend:
                continue
            return row
        return None
    return list(results.values())[0] if len(results) == 1 else None


def gate_from_bench(
    report: dict | None, task: str, *, model: str | None = None, backend: str | None = None
) -> dict[str, dict]:
    """Per-language (or per-label) verdicts for ``task``, from a bench artifact.

    An empty dict means NO evidence at all — every language then reads as "never
    evaluated" through :func:`task_gate`, never as cleared.
    """
    if task not in GATED_TASKS:
        raise ValueError(f"unknown gated task {task!r}")
    row = _pick_pair(report, model=model, backend=backend)
    tasks = (row or {}).get("tasks") or {}
    if task == "langdetect":
        payload = tasks.get("langdetect") or {}
        if payload.get("status") != "ok":
            return {}
        return _from_precision(payload.get("by_answer") or {})
    payload = tasks.get(task) or {}
    if payload.get("status") != "ok":
        return {}
    return _from_validity(payload.get("by_language") or {}, task=task)


def task_gate(key: str | None, gate: dict[str, dict]) -> tuple[bool, str]:
    """Whether ``key`` (a language, or a proposed label) may proceed.

    Binary and conservative, like the perception gate it mirrors: only ``active is
    True`` proceeds. Absence from the gate is "never evaluated" — never assumed safe
    by omission.
    """
    if not key:
        return False, "no language"
    entry = gate.get(key)
    if entry is None:
        return False, "never evaluated"
    active = entry.get("active")
    reason = str(entry.get("reason") or "")
    if active is None:
        return False, reason or "unmeasured"
    return bool(active), reason


def answer_vetoed(label: str | None, gate: dict[str, dict]) -> tuple[bool, str]:
    """Has the bench MEASURED this label and found it wrong more often than right?

    A DELIBERATE ASYMMETRY with :func:`task_gate`, and the reason is worth stating
    because the two look alike and behave oppositely on unmeasured input.

    :func:`task_gate` licenses: it guards an opt-in capability that starts from
    nothing, so "unmeasured" must refuse — running it there would be unmeasured work.
    This one VETOES: language detection already runs, by default, over every language
    the model can name, and the gold set covers thirteen of them. Refusing every
    unmeasured label would silently disable detection for every language the gold set
    was simply never written for — an over-tight gate reading as conservative while
    deleting data that works.

    So only a MEASURED FAILURE stops a label. An unmeasured label proceeds exactly as
    it did before any bench existed, and the caller reports which state it was in.
    """
    if not label:
        return False, ""
    entry = gate.get(label)
    if entry is None:
        return False, ""
    if entry.get("active") is False:
        return True, str(entry.get("reason") or f"the bench failed the label {label!r}")
    return False, ""


def current_task_gate(task: str, *, model: str | None = None) -> dict[str, dict]:
    """The live gate for ``task`` from the newest saved bench artifact.

    Read-only and cheap. A missing artifact yields ``{}`` — every key then reads as
    never evaluated, which is the honest state before anyone has benched anything.
    """
    try:
        from src.ai_layer.model_bench import last_model_bench_report

        report = last_model_bench_report(summary=True)
    except Exception:  # noqa: BLE001 - no artifact is an absence, not a crash
        return {}
    if not report.get("available"):
        return {}
    return gate_from_bench(report, task, model=model)


__all__ = [
    "GATED_TASKS",
    "MIN_ANSWER_PRECISION",
    "MIN_FORMAT_VALIDITY",
    "MIN_OBSERVATIONS",
    "answer_vetoed",
    "current_task_gate",
    "gate_from_bench",
    "task_gate",
]
