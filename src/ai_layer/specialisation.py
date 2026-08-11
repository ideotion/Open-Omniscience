"""Several models, each with a speciality — is the one cell that justifies it real?

Design of record: ``docs/design/MULTI_MODEL_SPECIALISATION_2026-08-10.md``. The ask,
verbatim: *"add to the test the possibility (and the impact of) having several models,
each with their specialty, for example Qwen for language detection only and Mistral's
for the rest. ... should each model run for a certain batch size each, then unload /
load the other, and run another on the same article batch? In this case, what should
the batch size be?"*

WHAT THE 10 AUGUST RUNS ACTUALLY SHOWED. Exactly one cell of the comparison justifies a
second model: Qwen3.5 0.8B was 100 % on language ID and 2.4x faster than Ministral,
and 0 % at every other task. Everything else in that table says "use Ministral". So this
is not "which models should we mix" — it is whether that ONE cell is worth the cost of
switching, and **n was 17**. Seventeen single-sentence gold cases is an anecdote, and
building a task-to-model map on it would be building a knob for a setup that may turn
out to be slower.

Hence the order here, which is the design doc's own: the gate first, the shapes second.
If the advantage does not survive a few hundred real articles, the answer is "one model"
— a real finding, and cheaper to act on than the machinery it would have justified.

THERE IS NO GOLD LABEL IN THE CORPUS, and pretending otherwise is the one thing that
would make this whole measurement worthless. The gold set has reviewed languages and is
n=17; the corpus has two INDEPENDENT signals, neither of them truth:

  * ``detected_language`` — py3langid, a trained offline model, written only above its
    own confidence floor;
  * ``language`` — what the publisher asserted in ``<html lang>``.

So what is measured at scale is AGREEMENT, reported per reference and never blended into
an "accuracy". Where the two references agree with each other, that subset is the
strongest available reference and gets its own row — still agreement, still labelled.
Disagreement does not say who is wrong.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
import time

_LOG = logging.getLogger("ai_layer.specialisation")

#: The two article-shaped tasks a per-article pipeline actually runs. Triage operates on
#: keywords and source-tags on sources, so neither can be measured "over the same article
#: sample" — they stay in the comparative bench, where their unit is their own.
PIPELINE_TASKS: tuple[str, ...] = ("langdetect", "perception")

#: Batch sizes from the ask. Kept as data so the report can name what it swept rather
#: than a reader inferring it from the rows.
DEFAULT_BATCH_SIZES: tuple[int, ...] = (100, 300, 1000)

#: How much agreement the small model has to keep before a two-model setup is worth
#: measuring at all. NOT a quality bar and not a pass/fail on the model: it is the point
#: below which the ONE cell that motivates specialisation has stopped existing, so the
#: shapes underneath would be measuring a trade nobody would take. Stated, so a reader
#: can disagree with the number rather than with a verdict.
ADVANTAGE_MARGIN = 0.02


def _norm_lang(code: str | None) -> str | None:
    """``en-US`` -> ``en``. The corpus stores whatever the publisher wrote, and the
    house rule is store-raw / normalise-on-read; comparing a model's ``en`` against a
    stored ``en-US`` would manufacture a disagreement out of a region subtag."""
    if not code:
        return None
    try:
        from src.analytics.managed import normalize_lang

        return normalize_lang(code) or None
    except Exception:  # noqa: BLE001 - a normaliser must never break a measurement
        c = str(code).strip().lower().replace("_", "-")
        return c.split("-", 1)[0] or None


def language_references(article) -> dict:
    """The reference labels available for one article, each named.

    Two signals, kept apart on purpose. ``agreed`` is populated only when both exist AND
    match — the strongest reference this corpus can offer, and still not truth.
    """
    detected = _norm_lang(getattr(article, "detected_language", None))
    asserted = _norm_lang(getattr(article, "language", None))
    return {
        "detected": detected,
        "asserted": asserted,
        "agreed": detected if (detected and asserted and detected == asserted) else None,
    }


def measure_language_agreement(
    articles,
    *,
    client,
    model: str,
    backend: str | None = None,
    keep_alive: str | None = None,
) -> dict:
    """THE GATE. How often does this model's language label match each reference?

    One call per article, over a fixed sample. Reported per reference with its own n and
    never averaged together, because the two references disagree with each other on real
    corpora and a blended figure would hide exactly that.

    A refusal is counted apart from a wrong answer throughout — refusing to label is a
    different behaviour from mislabelling, and the production detector treats them
    differently too (a refusal stores nothing; a wrong label would be stored).
    """
    refs = ("detected", "asserted", "agreed")
    tally: dict[str, dict] = {r: {"n": 0, "match": 0, "differ": 0} for r in refs}
    refused = 0
    answered = 0
    errors: list[str] = []
    t0 = time.monotonic()

    from src.ai_layer.langdetect_llm import detect_language_llm

    for art in articles:
        text = getattr(art, "content", None) or ""
        title = getattr(art, "title", None) or ""
        if not text.strip():
            continue
        try:
            got = _norm_lang(
                detect_language_llm(client, title, text, model=model, keep_alive=keep_alive)
            )
        except Exception as exc:  # noqa: BLE001 - one bad article never ends the sweep
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if got is None:
            refused += 1
            continue
        answered += 1
        available = language_references(art)
        for r in refs:
            ref = available[r]
            if not ref:
                continue
            tally[r]["n"] += 1
            if ref == got:
                tally[r]["match"] += 1
            else:
                tally[r]["differ"] += 1

    for r in refs:
        row = tally[r]
        row["agreement"] = round(row["match"] / row["n"], 4) if row["n"] else None

    total = answered + refused
    return {
        "model": model,
        "backend": backend,
        "n_answered": answered,
        "n_refused": refused,
        "n_total": total,
        "answer_rate": round(answered / total, 4) if total else None,
        "by_reference": tally,
        "wall_s": round(time.monotonic() - t0, 3),
        "errors": errors[:5],
        "n_errors": len(errors),
        "method": (
            "One call per article over a fixed sample. AGREEMENT with each reference is "
            "reported alone, never averaged: 'detected' is py3langid (an offline model, "
            "written only above its own confidence floor), 'asserted' is the publisher's "
            "own <html lang>, and 'agreed' is the subset where those two match each "
            "other. A refusal is counted apart from a disagreement."
        ),
        "caveat": (
            "This is AGREEMENT, not accuracy — the corpus carries no reviewed language "
            "labels, so where a model and a reference differ this cannot say which is "
            "right. The only accuracy figure available is over the 17-case reviewed gold "
            "set, and it is that figure's small n this measurement exists to widen."
        ),
    }


def compare_language_models(results: list[dict]) -> dict:
    """Does the small model's advantage survive the bigger sample?

    Compares on the STRONGEST reference that has data — the subset where py3langid and
    the publisher agree — and falls back through the others when it does not, naming
    which it used. No composite: the answer is a comparison on one stated reference, with
    both models' figures and both n's beside it.
    """
    usable = [r for r in results if r.get("n_answered")]
    if len(usable) < 2:
        return {
            "verdict": "not-measurable-here",
            "reason": "fewer than two models produced any answers",
            "n_models": len(usable),
        }
    for ref in ("agreed", "detected", "asserted"):
        rows = [(r, r["by_reference"][ref]) for r in usable]
        if any(row["n"] == 0 for _, row in rows):
            continue
        ranked = sorted(rows, key=lambda pair: pair[1]["agreement"] or 0.0, reverse=True)
        best, best_row = ranked[0]
        second, second_row = ranked[1]
        margin = (best_row["agreement"] or 0.0) - (second_row["agreement"] or 0.0)
        return {
            "reference": ref,
            "leader": best["model"],
            "leader_agreement": best_row["agreement"],
            "leader_n": best_row["n"],
            "runner_up": second["model"],
            "runner_up_agreement": second_row["agreement"],
            "runner_up_n": second_row["n"],
            "margin": round(margin, 4),
            "margin_threshold": ADVANTAGE_MARGIN,
            "specialisation_worth_measuring": margin >= ADVANTAGE_MARGIN,
            "rows": [
                {
                    "model": r["model"],
                    "backend": r.get("backend"),
                    "agreement": row["agreement"],
                    "n": row["n"],
                    "refused": r["n_refused"],
                    "wall_s": r["wall_s"],
                }
                for r, row in ranked
            ],
            "method": (
                f"Compared on the '{ref}' reference, the strongest one with data for "
                "every model. The margin is a difference between two agreement rates on "
                "the same articles — it is not a score, and it says nothing about which "
                "model is right where they differ."
            ),
            "caveat": (
                "A margin under the threshold means the ONE cell that motivates a second "
                "model has not survived the larger sample, so the shapes below would be "
                "measuring the cost of a trade nobody would take. It does not mean the "
                "models are equally good at anything else."
            ),
        }
    return {
        "verdict": "not-measurable-here",
        "reason": (
            "no reference had data for every model — the sample carries no language "
            "labels this comparison could use"
        ),
    }


# --------------------------------------------------------------------------- #
#  The switch, which is the whole experiment
#
#  A two-model setup on one 8 GB card cannot hold both, so every crossing is
#  stop → free VRAM → start → load weights, timed by the field runs at roughly
#  60-90 s. That number is what every shape below is competing against, and it is
#  measured rather than assumed because the two backends do not switch the same way:
#  Ollama drops residency and reloads lazily on the next call (the model itself pays,
#  later), while vLLM must be stopped and restarted (the switch pays, now). Timing both
#  with one stopwatch and calling the result "switch cost" would compare two different
#  mechanisms.
# --------------------------------------------------------------------------- #


def _real_switch(*, backend: str, model: str | None) -> dict:
    from src.llm.arbitration import hand_gpu_to

    return hand_gpu_to(backend, model=model)


def timed_switch(*, backend: str, model: str | None, switch=None) -> dict:
    """One hand-over, timed, with a REFUSAL reported as a refusal.

    The trap this exists to avoid is stated in the design doc: a configuration whose
    switches silently failed would look like the fastest one in the table. So the
    outcome is read, not assumed — ``hand_gpu_to`` waits for the port to go quiet and
    refuses when a stop did not take, and a refusal here means the run afterwards was
    served by whatever was already loaded.
    """
    fn = switch or _real_switch
    t0 = time.monotonic()
    try:
        out = fn(backend=backend, model=model)
    except Exception as exc:  # noqa: BLE001 - a failed switch is data, not a crash
        return {
            "backend": backend,
            "model": model,
            "wall_s": round(time.monotonic() - t0, 3),
            "ok": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    wall = round(time.monotonic() - t0, 3)
    ok = bool(out.get("ready") or out.get("ok"))
    return {
        "backend": backend,
        "model": model,
        "wall_s": wall,
        "ok": ok,
        "reason": None if ok else (out.get("reason") or "the backend did not report ready"),
        "detail": out,
    }


def _run_task_over(
    articles,
    *,
    task: str,
    client,
    model: str,
    keep_alive: str | None = None,
) -> dict:
    """One task over one list of articles. Returns counts and wall — never a score."""
    done = failed = 0
    t0 = time.monotonic()
    if task == "langdetect":
        from src.ai_layer.langdetect_llm import detect_language_llm

        for art in articles:
            try:
                detect_language_llm(
                    client,
                    getattr(art, "title", None) or "",
                    getattr(art, "content", None) or "",
                    model=model,
                    keep_alive=keep_alive,
                )
                done += 1
            except Exception:  # noqa: BLE001 - one article never ends a phase
                failed += 1
    elif task == "perception":
        from src.ai_layer.perception import llm_perception_extract

        for art in articles:
            try:
                llm_perception_extract(
                    client,
                    getattr(art, "content", None) or "",
                    model=model,
                    language=getattr(art, "language", None),
                    keep_alive=keep_alive,
                )
                done += 1
            except Exception:  # noqa: BLE001
                failed += 1
    else:  # pragma: no cover - PIPELINE_TASKS is the closed set
        raise ValueError(f"unknown pipeline task {task!r}")
    return {"task": task, "model": model, "done": done, "failed": failed,
            "wall_s": round(time.monotonic() - t0, 3)}


def run_shape(
    articles,
    *,
    shape: str,
    assignment: dict,
    clients: dict,
    batch_size: int | None = None,
    switch=None,
    keep_alive: str | None = None,
) -> dict:
    """Run the whole pipeline over ONE sample in one of the three shapes.

    ``assignment`` maps a task to ``{"backend": ..., "model": ...}``. It is a parameter
    rather than a setting on purpose: the design doc's own rule is that the map is the
    thing the maintainer would configure IF the measurement says specialisation is worth
    it, so building it as a knob first would be building for an answer nobody has yet.

    The shapes:

    ``one``      every task with one model, no switches — the baseline everything else
                 has to beat.
    ``phased``   the whole sample through task A's model, ONE switch, then the rest.
                 Switches per corpus = 1.
    ``batched``  the ask's own proposal: N articles through A, switch, the same N
                 through B, switch back, next N. Switches = 2 x (corpus / N).

    Switch time is accumulated as its OWN line, never folded into the task walls — it is
    the number the design turns on, and a total that hid it inside "perception took
    longer" would answer a different question.
    """
    tasks = list(PIPELINE_TASKS)
    items = list(articles)
    switches: list[dict] = []
    phases: list[dict] = []
    current: tuple[str, str] | None = None

    def _ensure(task: str) -> dict | None:
        nonlocal current
        spec = assignment[task]
        want = (spec["backend"], spec["model"])
        if current == want:
            return None
        sw = timed_switch(backend=want[0], model=want[1], switch=switch)
        sw["for_task"] = task
        # The FIRST hand-over is the initial load, which every shape pays including the
        # one-model baseline — counting it as a crossing would charge 'phased' for a cost
        # its baseline also has and make the doc's own arithmetic (one crossing per
        # corpus) read as two.
        sw["initial"] = not switches
        switches.append(sw)
        # Only claim the backend is serving what we asked for when it SAID so. A refused
        # switch leaves the previous model in place, and recording it as current would
        # then suppress every later switch — the fastest-looking run in the table.
        current = want if sw["ok"] else current
        return sw

    t0 = time.monotonic()
    if shape in ("one", "phased"):
        # ONE LOOP, TWO SHAPES, and that is the point rather than a shortcut. Both run
        # the whole sample through each task in turn; what separates them is the
        # ASSIGNMENT — 'one' maps every task to the same model, so ``_ensure`` finds the
        # backend already current and no switch happens at all. Writing them as separate
        # branches would have implied a structural difference that does not exist, and
        # the absence of one is itself evidence for the doc's prediction that batch size
        # is the wrong knob.
        for task in tasks:
            _ensure(task)
            spec = assignment[task]
            phases.append(
                _run_task_over(
                    items, task=task, client=clients[spec["backend"]],
                    model=spec["model"], keep_alive=keep_alive,
                )
            )
    elif shape == "batched":
        n = int(batch_size or 0)
        if n <= 0:
            raise ValueError("the batched shape needs a positive batch_size")
        for start in range(0, len(items), n):
            chunk = items[start : start + n]
            for task in tasks:
                _ensure(task)
                spec = assignment[task]
                phases.append(
                    _run_task_over(
                        chunk, task=task, client=clients[spec["backend"]],
                        model=spec["model"], keep_alive=keep_alive,
                    )
                )
    else:
        raise ValueError(f"unknown shape {shape!r}")

    wall = time.monotonic() - t0
    switch_s = round(sum(s["wall_s"] for s in switches), 3)
    refused = [s for s in switches if not s["ok"]]
    n = len(items)
    return {
        "shape": shape,
        "batch_size": batch_size if shape == "batched" else None,
        "n_articles": n,
        "wall_s": round(wall, 3),
        "switch_s": switch_s,
        "switch_share": round(switch_s / wall, 4) if wall > 0 else None,
        "switches": len(switches),
        "crossings": len([s for s in switches if not s.get("initial")]),
        "initial_load_s": round(sum(s["wall_s"] for s in switches if s.get("initial")), 3),
        "switches_refused": len(refused),
        "articles_per_hour": round(n / wall * 3600, 1) if wall > 0 else None,
        "phases": phases,
        "switch_detail": switches,
        "trustworthy": not refused,
        "method": (
            "Wall-clock over ONE fixed article sample, with time spent switching "
            "accumulated separately and never folded into a task's own wall. "
            "articles_per_hour is this run's own arithmetic (n / wall), not a per-call "
            "latency multiplied by anything."
        ),
        "caveat": (
            None
            if not refused
            else (
                f"{len(refused)} switch(es) were REFUSED, so at least one phase ran on a "
                "model it did not ask for. The timings below are real and the comparison "
                "is not: a run whose switches silently failed is the fastest-looking row "
                "in any such table."
            )
        ),
    }


__all__ = [
    "ADVANTAGE_MARGIN",
    "DEFAULT_BATCH_SIZES",
    "PIPELINE_TASKS",
    "compare_language_models",
    "language_references",
    "measure_language_agreement",
    "run_shape",
    "timed_switch",
]
