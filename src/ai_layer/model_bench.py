"""The COMPARATIVE model bench (2026-08-01 rulings 14-16).

The maintainer's question is "does the ruled default model deserve to stay the
default, and how do the small candidates compare?" — and the honest answer is a
MEASUREMENT, not an opinion. This module runs every roster model, on every backend
that actually serves it, over the SAME frozen inputs, and reports every metric
ALONE.

Five tasks per (model, backend), each already shipped and reused whole:

===============  =========================================================
perception       ``run_perception_eval_against_model`` — the who/where/when
                 gold harness, per language and field, hallucination apart
triage           the frozen keyword batch through ``run_triage_batch`` —
                 format validity, unsure share, throughput, canaries, and
                 accuracy against the graded anchors
source_tags      the frozen source sample against the closed tag vocabulary
                 — validity plus canaries
langdetect       the perception gold texts, whose language is already
                 declared and reviewed, scored as a detector
latency          ``run_llm_bench`` — per-prompt-shape timing
===============  =========================================================

THE RULES THIS FILE ENFORCES, all of them recorded rulings:

* **No composite, no winner.** Nothing here adds two metrics together or ranks
  models. The report is a table the maintainer reads; the default-model decision
  is theirs, made on verified logs (the ai-proposed → claude-verified →
  maintainer-merged chain).
* **The roster is a REQUEST list.** Every tag is matched EXACTLY against the
  backend's own installed list at run time; an absent tag is REPORTED and skipped,
  never substituted with a close one.
* **Same questions or no comparison.** Every run records the frozen batch's digest,
  and a resume whose digest moved is refused rather than blending two input sets.
* **Model and backend are never conflated.** The same weights are quantized
  differently by Ollama and vLLM, so every row is labelled model + backend +
  quantization and "mistral:7b" on two backends is two rows, not one.
* **Sequential loading** (ruling 16): all five tasks complete for one pair before
  the next, so a run costs one model load per pair rather than one per task.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from src.ai_layer import bench_batch as BB

_LOG = logging.getLogger("ai_layer.model_bench")

MODEL_BENCH_SCHEMA = "oo-model-bench-1"
BENCH_CURSOR_SCHEMA = "oo-model-bench-cursor-1"

BENCH_TASKS: tuple[str, ...] = ("perception", "triage", "source_tags", "langdetect", "latency")
BENCH_BACKENDS: tuple[str, ...] = ("ollama", "vllm")

#: The ruled roster (ruling 15) as a REQUEST list. Nothing here asserts that a tag
#: exists: ``verify_roster`` matches each one EXACTLY against the backend's own
#: installed list at run time and refuses what is absent. The maintainer's named
#: LiquidAI candidate is deliberately NOT written in — see ``UNRESOLVED_CANDIDATES``.
DEFAULT_ROSTER: tuple[str, ...] = (
    "ministral-3:8b-instruct-2512-q4_K_M",  # the current Ollama default
    "ministral-3:3b-instruct-2512-q4_K_M",
    "mistral:7b",
    "gemma4:e4b",
    "qwen3.5:4b",
    "granite4.1",
)

#: Models the maintainer named whose EXACT tag could not be verified from this
#: machine. Writing a guessed tag into the roster would be a fabricated catalog
#: entry (the burn this project already took once), so the candidate travels as a
#: note and the operator supplies the verified tag via ``extra_models``.
UNRESOLVED_CANDIDATES: tuple[dict, ...] = (
    {
        "named": "LiquidAI LFM2.5-8B-A1B",
        "note": (
            "Named by the maintainer for this bench. Its exact Ollama tag / Hugging Face "
            "repo has not been verified, so it is not written into the roster as though it "
            "existed. Verify the tag on the rig, then pass it in `extra_models`; an absent "
            "tag is refused, never substituted."
        ),
    },
)

_QUANT_RE = re.compile(r"(?:^|[-_:.])(q\d[_a-z0-9]*|fp\d+|bf\d+|int\d+|awq|gptq)\b", re.IGNORECASE)

_CURSOR_FILENAME = "bench_progress_state.json"


def quantization_of(tag: str) -> str | None:
    """The quantization the TAG itself states, or ``None``.

    Never inferred: an Ollama tag usually says ``q4_K_M``, a Hugging Face repo id
    usually says nothing, and guessing "probably fp16" would put a number in the
    report that nobody measured.
    """
    m = _QUANT_RE.search(tag or "")
    return m.group(1) if m else None


def pair_key(backend: str, model: str) -> str:
    return f"{backend}|{model}"


# --------------------------------------------------------------------------- #
#  Roster resolution.
# --------------------------------------------------------------------------- #
def resolve_pairs(
    *,
    models: list[str],
    installed_by_backend: dict[str, list[str] | None],
) -> tuple[list[dict], list[dict]]:
    """Which (model, backend) pairs can actually run, and why the rest cannot.

    ``installed_by_backend`` maps a backend to its installed tags, or ``None`` when
    the backend itself is unreachable (a different fact from "the model is missing",
    and reported as such).
    """
    from src.ai_layer.triage import verify_roster

    runnable: list[dict] = []
    skipped: list[dict] = []
    for backend in sorted(installed_by_backend):
        installed = installed_by_backend[backend]
        if installed is None:
            skipped.append(
                {
                    "backend": backend,
                    "model": None,
                    "reason": "backend-unreachable",
                    "detail": f"{backend} is not reachable from this machine right now",
                }
            )
            continue
        v = verify_roster(models, list(installed))
        for tag in v["runnable"]:
            runnable.append(
                {
                    "backend": backend,
                    "model": tag,
                    "quantization": quantization_of(tag),
                    "key": pair_key(backend, tag),
                }
            )
        for tag in v["missing"]:
            skipped.append(
                {
                    "backend": backend,
                    "model": tag,
                    "reason": "not-installed",
                    "detail": (
                        f"{tag!r} is not an installed tag on {backend} — install the EXACT tag "
                        "or drop it from the roster. A close tag would benchmark a different "
                        "model than the one named."
                    ),
                }
            )
    return runnable, skipped


# --------------------------------------------------------------------------- #
#  The five tasks.
# --------------------------------------------------------------------------- #
def _task_perception(client, *, model: str, backend: str, keep_alive: str | None) -> dict:
    from src.ai_layer.perception import run_perception_eval_against_model

    return run_perception_eval_against_model(
        client, model=model, backend_name=backend, keep_alive=keep_alive
    )


def _task_triage(
    client,
    *,
    model: str,
    batch: dict,
    anchors: dict | None,
    keep_alive: str | None,
    chunk: int = 25,
    ctx=None,
    monotonic=time.monotonic,
) -> dict:
    from src.ai_layer import triage as T
    from src.ai_layer.triage_job import CANARIES, CANARY_EXPECTED

    items = [
        T.TriageItem(
            term=k["term"],
            language=k.get("language"),
            mention_count=k.get("mention_count"),
            article_count=k.get("article_count"),
        )
        for k in batch.get("keywords", [])
    ]
    lang_of = {k["term"]: (k.get("language") or "unknown") for k in batch.get("keywords", [])}
    verdicts: dict[str, dict] = {}
    keywords_in = verdicts_out = parse_failures = unsure = 0
    wall = 0.0
    canary_failed: list[dict] = []
    batches = 0
    for i in range(0, len(items), max(1, chunk)):
        if ctx is not None and getattr(ctx, "stopping", False):
            break
        out = T.run_triage_batch(
            client,
            items[i : i + max(1, chunk)],
            model=model,
            canaries=CANARIES,
            canary_expected=CANARY_EXPECTED,
            keep_alive=keep_alive,
            monotonic=monotonic,
        )
        pb = out["parsed"]
        batches += 1
        keywords_in += pb.keywords_in
        verdicts_out += pb.verdicts_out
        parse_failures += pb.parse_failures
        unsure += pb.unsure_count
        wall += float(out.get("wall_s") or 0.0)
        verdicts.update(pb.verdicts)
        canary_failed.extend(out["canary"].get("failed") or [])
    # PER-LANGUAGE (E-S3): the batch is stratified by language precisely so a
    # multilingual roster can be read per language — reporting only a pooled number
    # would hide the thing the stratification exists to expose, and it is the
    # evidence the per-language task gates read.
    by_language: dict[str, dict] = {}
    for term, lang in lang_of.items():
        b = by_language.setdefault(lang, {"asked": 0, "valid": 0, "unsure": 0})
        b["asked"] += 1
        v = verdicts.get(term)
        if v:
            b["valid"] += 1
            if v["verdict"] == "unsure":
                b["unsure"] += 1
    for b in by_language.values():
        b["format_validity"] = round(b["valid"] / b["asked"], 4) if b["asked"] else None
        b["pct_unsure"] = round(b["unsure"] / b["valid"], 4) if b["valid"] else None
    return {
        "status": "ok",
        "batches": batches,
        "keywords_in": keywords_in,
        "verdicts_out": verdicts_out,
        "parse_failures": parse_failures,
        "unsure": unsure,
        "wall_s": round(wall, 3),
        "format_validity": T.format_validity_rate(keywords_in, verdicts_out),
        "pct_unsure": T.pct_unsure(unsure, verdicts_out),
        "valid_verdicts_per_s": T.valid_verdicts_per_sec(verdicts_out, wall),
        "by_language": by_language,
        "canary": {"ok": not canary_failed, "failed": canary_failed},
        "anchor_accuracy": (
            T.anchor_accuracy(verdicts, anchors["anchors"]) if anchors and anchors.get("anchors")
            else {
                "status": "unmeasured",
                "reason": (
                    "no graded anchors exist yet — grade a sitting first. Agreement between "
                    "models is not correctness."
                ),
            }
        ),
        "verdicts": {t: v["verdict"] for t, v in verdicts.items()},
        "kinds": {t: v["kind"] for t, v in verdicts.items()},
    }


def _task_source_tags(client, *, model: str, batch: dict, keep_alive: str | None) -> dict:
    from src.ai_layer import source_tags as ST
    from src.ai_layer.source_tags_job import CANARIES, CANARY_EXPECTED

    vocabulary = list(batch.get("source_tag_vocabulary") or [])
    rows = batch.get("sources") or []
    if not vocabulary or not rows:
        return {
            "status": "unmeasured",
            "reason": (
                "the frozen batch carries no source evidence or no tag vocabulary — "
                "rebuild it on a corpus that has sources with tags."
            ),
        }
    items = [
        ST.SourceTagItem(
            domain=r["domain"],
            article_count=int(r.get("article_count") or 0),
            mention_count=int(r.get("mention_count") or 0),
            language=r.get("language"),
            top_terms=tuple(r.get("top_terms") or ()),
        )
        for r in rows
    ]
    out = ST.run_source_tag_batch(
        client,
        items,
        vocabulary=vocabulary,
        model=model,
        canaries=CANARIES,
        canary_expected=CANARY_EXPECTED,
        keep_alive=keep_alive,
    )
    pb = out["parsed"]
    validity = round(pb.tagged_out / pb.sources_in, 4) if pb.sources_in else None
    lang_of = {r["domain"]: (r.get("language") or "unknown") for r in rows}
    # `pb.tags` keys the domains that came back with a VALID line — an empty tuple
    # there is the explicit "none" answer, which is an answer; `missing` is the
    # absence of one. The two must not be folded together.
    answered = set(pb.tags)
    by_language: dict[str, dict] = {}
    for domain, lang in lang_of.items():
        b = by_language.setdefault(lang, {"asked": 0, "answered": 0})
        b["asked"] += 1
        if domain in answered:
            b["answered"] += 1
    for b in by_language.values():
        b["format_validity"] = round(b["answered"] / b["asked"], 4) if b["asked"] else None
    return {
        "status": "ok",
        "vocabulary_size": len(vocabulary),
        "sources_in": pb.sources_in,
        "tagged_out": pb.tagged_out,
        "assigned": pb.assigned_count,
        "answered_none": pb.none_count,
        "parse_failures": pb.parse_failures,
        "missing": len(pb.missing),
        "format_validity": validity,
        "by_language": by_language,
        "canary": {
            "ok": bool(out["canary"].get("ok", True)),
            "failed": out["canary"].get("failed") or [],
            "skipped": out["canary"].get("skipped") or [],
        },
        "wall_s": round(float(out.get("wall_s") or 0.0), 3),
        "method": (
            "Every answer must come from the corpus's OWN closed tag vocabulary; a tag "
            "outside it is malformed and counted, never coerced to the nearest real tag. "
            "'answered none' is a legitimate answer, reported apart from a failure to answer."
        ),
    }


def _task_langdetect(client, *, model: str, keep_alive: str | None) -> dict:
    """Score language detection against texts whose language is already declared.

    Reuses the perception gold set rather than inventing a second one: its cases
    already carry a reviewed ``language``, and writing fresh sentences in twelve
    languages here would be exactly the fabrication this project refuses. The
    honest limit travels with the number — these are ONE-SENTENCE texts, harder
    than the article leads the production detector sees, so the figure is a floor.
    """
    from src.ai_layer.langdetect_llm import detect_language_llm
    from src.analytics.perception_eval import PERCEPTION_GOLD

    per_lang: dict[str, dict] = {}
    per_answer: dict[str, dict] = {}
    correct = wrong = refused = 0
    t0 = time.monotonic()
    for case in PERCEPTION_GOLD:
        got = detect_language_llm(client, "", case.text, model=model, keep_alive=keep_alive)
        bucket = per_lang.setdefault(case.language, {"n": 0, "correct": 0, "wrong": 0, "refused": 0})
        bucket["n"] += 1
        if got is None:
            refused += 1
            bucket["refused"] += 1
        elif got == case.language:
            correct += 1
            bucket["correct"] += 1
        else:
            wrong += 1
            bucket["wrong"] += 1
        if got is not None:
            # Keyed by the model's own ANSWER, not by the gold language. This is
            # PRECISION, and it is the only measure a gate on the answer can honestly
            # use: recall per true language says nothing about whether the label the
            # model just emitted can be trusted. Free to compute here, and applying a
            # recall figure to an answer would be a silent substitution.
            a = per_answer.setdefault(got, {"answered": 0, "correct": 0})
            a["answered"] += 1
            if got == case.language:
                a["correct"] += 1
    for a in per_answer.values():
        a["precision"] = round(a["correct"] / a["answered"], 4) if a["answered"] else None
    answered = correct + wrong
    total = correct + wrong + refused
    return {
        "status": "ok",
        "n": total,
        "correct": correct,
        "wrong": wrong,
        "refused": refused,
        "accuracy_over_answered": round(correct / answered, 4) if answered else None,
        "accuracy_over_all": round(correct / total, 4) if total else None,
        "by_language": per_lang,
        "by_answer": per_answer,
        "wall_s": round(time.monotonic() - t0, 3),
        "method": (
            "One call per gold case; the reply must BE a known ISO 639-1 code. Two "
            "denominators are reported apart and never blended: accuracy over the cases the "
            "model ANSWERED, and accuracy over ALL cases (a refusal counts against the "
            "second, not the first — refusing is a different behaviour from being wrong). "
            "'by_language' is keyed by the TRUE language (recall); 'by_answer' by the "
            "model's own label (precision). They answer different questions and are never "
            "read as each other."
        ),
        "caveat": (
            "The gold texts are single sentences, shorter than the article leads the "
            "production detector reads, so these figures are a FLOOR for this model, not its "
            "production accuracy. Per-language n is tiny — read each row with its n."
        ),
    }


def _task_latency(client, *, model: str, backend: str, repeats: int) -> dict:
    from src.monitoring.llm_bench import run_llm_bench

    return run_llm_bench(repeats=repeats, client=client, model=model, backend_name=backend)


def bench_one_pair(
    client,
    *,
    model: str,
    backend: str,
    batch: dict,
    anchors: dict | None,
    repeats: int = 2,
    keep_alive: str | None = None,
    triage_chunk: int = 25,
    tasks: tuple[str, ...] = BENCH_TASKS,
    ctx=None,
) -> dict:
    """Run every task for ONE (model, backend), in order, on one loaded model.

    A task that raises is recorded as an error and the others still run: one broken
    metric must not cost the whole pair, and a silently missing task would read as
    "not applicable" rather than "it failed".
    """
    out: dict = {
        "model": model,
        "backend": backend,
        "quantization": quantization_of(model),
        "quantization_note": (
            None
            if quantization_of(model)
            else "the tag does not state a quantization; none is inferred"
        ),
        "batch_digest": batch.get("digest"),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "tasks": {},
    }
    for name in tasks:
        if ctx is not None and getattr(ctx, "stopping", False):
            out["tasks"][name] = {"status": "cancelled"}
            continue
        if ctx is not None:
            ctx.set_progress(detail=f"{backend} · {model} · {name}")
        try:
            # Dispatched by NAME rather than through a table: the tasks take genuinely
            # different arguments, and a table lookup would let an unknown name fall
            # through to whichever branch happened to be last — measuring one task
            # under another's name.
            if name == "perception":
                res = _task_perception(client, model=model, backend=backend, keep_alive=keep_alive)
            elif name == "triage":
                res = _task_triage(
                    client,
                    model=model,
                    batch=batch,
                    anchors=anchors,
                    keep_alive=keep_alive,
                    chunk=triage_chunk,
                    ctx=ctx,
                )
            elif name == "source_tags":
                res = _task_source_tags(client, model=model, batch=batch, keep_alive=keep_alive)
            elif name == "langdetect":
                res = _task_langdetect(client, model=model, keep_alive=keep_alive)
            elif name == "latency":
                res = _task_latency(client, model=model, backend=backend, repeats=repeats)
            else:
                raise ValueError(f"unknown bench task {name!r}")
        except Exception as exc:  # noqa: BLE001 - one task must not end the pair
            _LOG.warning("bench task %s failed for %s/%s", name, backend, model, exc_info=True)
            res = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"[:300]}
        out["tasks"][name] = res
    out["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return out


# --------------------------------------------------------------------------- #
#  Model loading / switching.
# --------------------------------------------------------------------------- #
def _default_unload(client, *, backend: str, model: str) -> dict:
    """Free the model after its pair completes so the next one is not benched with
    two models resident (ruling 16: minimise load/unload churn, but do not measure a
    model while another still holds the memory)."""
    if backend != "ollama":
        return {"unloaded": False, "reason": "only Ollama keeps a model resident between calls"}
    try:
        client.generate("", model=model, keep_alive="0")
        return {"unloaded": True}
    except Exception as exc:  # noqa: BLE001 - never fail a completed pair over cleanup
        return {"unloaded": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def _default_switch(*, backend: str, model: str) -> dict:
    """Point a backend at ``model``. Ollama loads per request, so this is a no-op
    there; vLLM serves ONE model per server, so switching is a lifecycle restart.

    Never downloads: the weights must already be present, because a pull is a
    consented task-manager job and the bench is not allowed to start one.
    """
    if backend != "vllm":
        return {"switched": False, "reason": "ollama loads the requested model per call"}
    from src.llm import vllm_lifecycle

    vllm_lifecycle.stop()
    started = vllm_lifecycle.start(model)
    return {"switched": True, "detail": started}


# --------------------------------------------------------------------------- #
#  The resumable cursor.
# --------------------------------------------------------------------------- #
def _cursor_path() -> Path:
    return BB.bench_dir() / _CURSOR_FILENAME


def load_cursor() -> dict | None:
    p = _cursor_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt cursor is a fresh start, not a crash
        return None
    return data if isinstance(data, dict) and data.get("schema") == BENCH_CURSOR_SCHEMA else None


def save_cursor(cursor: dict) -> Path:
    p = _cursor_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursor, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def clear_cursor() -> None:
    _cursor_path().unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
#  The run.
# --------------------------------------------------------------------------- #
def run_model_bench(
    ctx,
    *,
    models: list[str] | None = None,
    extra_models: list[str] | None = None,
    backends: tuple[str, ...] | list[str] = BENCH_BACKENDS,
    repeats: int = 2,
    tasks: tuple[str, ...] = BENCH_TASKS,
    triage_chunk: int = 25,
    restart: bool = False,
    allow_backend_switch: bool = False,
    batch: dict | None = None,
    anchors: dict | None = None,
    clients: dict | None = None,
    installed_by_backend: dict[str, list[str] | None] | None = None,
    unload=_default_unload,
    switch=_default_switch,
    persist: bool = True,
) -> dict:
    """``BackgroundJob`` worker: bench every runnable (model, backend) pair.

    Resumable PER PAIR: a cancelled or crashed run keeps the pairs it finished, and
    the next run picks up the rest — but only if the frozen batch is unchanged. A
    digest that moved means the questions moved, so the run REFUSES to resume and
    asks for a restart rather than assembling one table out of two input sets.
    """
    batch = batch or BB.load_frozen_batch()
    if anchors is None:
        anchors = BB.load_anchors()
    requested = list(models or DEFAULT_ROSTER) + list(extra_models or [])
    requested = list(dict.fromkeys(t for t in requested if t))

    if installed_by_backend is None:
        installed_by_backend = _installed_by_backend(tuple(backends))
    if clients is None:
        clients = _clients_for(tuple(backends))

    runnable, skipped = resolve_pairs(models=requested, installed_by_backend=installed_by_backend)

    cursor = None if restart else load_cursor()
    if cursor and cursor.get("batch_digest") != batch.get("digest"):
        return {
            "schema": MODEL_BENCH_SCHEMA,
            "status": "refused",
            "reason": "frozen-batch-changed",
            "detail": (
                "the saved run was measured over a different frozen batch "
                f"({cursor.get('batch_digest')} vs {batch.get('digest')}). Resuming would put "
                "answers to two different question sets in one table. Restart the bench "
                "(restart=true) to measure every model over the current batch."
            ),
        }
    results: dict[str, dict] = dict((cursor or {}).get("results") or {})
    run_id = (cursor or {}).get("run_id") or datetime.now().strftime("%Y%m%d-%H%M%S")

    todo = [p for p in runnable if p["key"] not in results]
    total = len(runnable)
    # Count only pairs of THIS roster: a cursor can legitimately carry a pair that is
    # no longer runnable (a model uninstalled between runs), and counting it would put
    # "7 of 6" on the progress line.
    def _done() -> int:
        return sum(1 for p in runnable if p["key"] in results)

    for pair in todo:
        if ctx is not None and getattr(ctx, "stopping", False):
            break
        backend, model = pair["backend"], pair["model"]
        if ctx is not None:
            ctx.set_progress(done=_done(), total=total, detail=f"{backend} · {model} · loading")
        client = clients.get(backend)
        if client is None:
            results[pair["key"]] = {
                "model": model,
                "backend": backend,
                "status": "error",
                "detail": f"no client for backend {backend}",
            }
            continue
        switch_note = None
        if backend == "vllm":
            if allow_backend_switch:
                try:
                    switch_note = switch(backend=backend, model=model)
                except Exception as exc:  # noqa: BLE001
                    results[pair["key"]] = {
                        "model": model,
                        "backend": backend,
                        "status": "error",
                        "detail": f"could not switch vLLM to this model: {exc}"[:300],
                    }
                    continue
            else:
                switch_note = {
                    "switched": False,
                    "reason": (
                        "vLLM serves one model per server; switching restarts it. Not done "
                        "automatically — pass allow_backend_switch to let the bench restart "
                        "the server between models."
                    ),
                }
        pair_result = bench_one_pair(
            client,
            model=model,
            backend=backend,
            batch=batch,
            anchors=anchors,
            repeats=repeats,
            triage_chunk=triage_chunk,
            tasks=tasks,
            ctx=ctx,
        )
        if switch_note:
            pair_result["backend_switch"] = switch_note
        try:
            pair_result["unload"] = unload(client, backend=backend, model=model)
        except Exception as exc:  # noqa: BLE001
            pair_result["unload"] = {"unloaded": False, "reason": str(exc)[:200]}
        results[pair["key"]] = pair_result
        if persist:
            save_cursor(
                {
                    "schema": BENCH_CURSOR_SCHEMA,
                    "run_id": run_id,
                    "batch_digest": batch.get("digest"),
                    "results": results,
                }
            )
        if ctx is not None:
            ctx.set_progress(done=_done(), total=total, detail=f"{backend} · {model} · done")

    cancelled = bool(ctx is not None and getattr(ctx, "stopping", False))
    report = assemble_report(
        results,
        batch=batch,
        anchors=anchors,
        skipped=skipped,
        runnable=runnable,
        requested=requested,
        run_id=run_id,
        cancelled=cancelled,
    )
    if persist:
        report["path"] = str(save_report(report))
        if not cancelled and _done() >= total:
            clear_cursor()
    return report


def _installed_by_backend(backends: tuple[str, ...]) -> dict[str, list[str] | None]:
    from src.llm.backend import get_client_with_name

    out: dict[str, list[str] | None] = {}
    for backend in backends:
        try:
            _, client = get_client_with_name(backend=backend)
            out[backend] = list(client.list_installed())
        except Exception as exc:  # noqa: BLE001 - unreachable is a fact, not a crash
            _LOG.info("bench: backend %s unreachable (%s)", backend, exc)
            out[backend] = None
    return out


def _clients_for(backends: tuple[str, ...]) -> dict:
    from src.llm.backend import get_client_with_name

    out: dict = {}
    for backend in backends:
        try:
            _, out[backend] = get_client_with_name(backend=backend)
        except Exception:  # noqa: BLE001
            continue
    return out


def assemble_report(
    results: dict[str, dict],
    *,
    batch: dict,
    anchors: dict | None,
    skipped: list[dict],
    runnable: list[dict],
    requested: list[str],
    run_id: str,
    cancelled: bool = False,
) -> dict:
    """The side-by-side artifact: one row per (model, backend), every metric alone."""
    from src.ai_layer.triage import pairwise_agreement

    verdicts_by_pair = {
        key: r["tasks"]["triage"]["verdicts"]
        for key, r in results.items()
        if isinstance(r.get("tasks"), dict)
        and isinstance(r["tasks"].get("triage"), dict)
        and r["tasks"]["triage"].get("verdicts")
    }
    return {
        "schema": MODEL_BENCH_SCHEMA,
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "cancelled" if cancelled else "complete",
        "frozen_batch": {
            "digest": batch.get("digest"),
            "built_at": batch.get("built_at"),
            "n_keywords": batch.get("n_keywords") or len(batch.get("keywords") or []),
            "n_sources": batch.get("n_sources") or len(batch.get("sources") or []),
            "vocabulary_size": len(batch.get("source_tag_vocabulary") or []),
            "keyword_strata": batch.get("keyword_strata") or [],
        },
        # "available", not "graded": the project's no-composite walkers ban the
        # substring "grade" in KEYS (which is also why "degraded" is never a key), and
        # a guard that trips on an honest field name is a guard nobody keeps.
        "anchors": {
            "available": bool(anchors and anchors.get("anchors")),
            "n": (anchors or {}).get("n", 0),
        },
        "requested_models": requested,
        "unresolved_candidates": list(UNRESOLVED_CANDIDATES),
        "pairs_run": [p["key"] for p in runnable if p["key"] in results],
        "pairs_pending": [p["key"] for p in runnable if p["key"] not in results],
        "skipped": skipped,
        "results": results,
        "pairwise_verdict_agreement": (
            pairwise_agreement(verdicts_by_pair) if len(verdicts_by_pair) > 1 else None
        ),
        "method": (
            "Every model runs the SAME frozen inputs (digest above) on every backend that "
            "serves it, five tasks per pair, all tasks completed before the next model is "
            "loaded. Each metric is reported ALONE, per (model, backend, task, language): "
            "there is no composite, no ranking and no winner column, because the tasks "
            "measure different things and a blend would hide which one moved."
        ),
        "caveat": (
            "Measured on THIS machine, at THIS moment, over a SAMPLE of the corpus. The same "
            "weights are quantized differently by Ollama and vLLM, so a model's two rows are "
            "two different artifacts and must not be averaged. Two models agreeing is not "
            "either being right — read agreement beside the graded anchors, and read every "
            "per-language row with its n."
        ),
    }


def _report_path(run_id: str) -> Path:
    return BB.bench_dir() / f"oo-model-bench-{run_id}.json"


def save_report(report: dict) -> Path:
    path = _report_path(str(report.get("run_id") or datetime.now().strftime("%Y%m%d-%H%M%S")))
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def summarize_report(report: dict) -> dict:
    """The report WITHOUT the per-term verdict/kind maps.

    Those maps are what make ``pairwise_verdict_agreement`` computable and what a
    verification session re-judges, so they stay in the artifact on disk — but they
    are hundreds of entries per pair, and the diagnostics bundle is meant to stay
    bounded. Every METRIC survives; only the raw per-term answers are dropped, and
    the summary says so rather than looking like a shorter run.
    """
    out = dict(report)
    results = {}
    for key, pair in (report.get("results") or {}).items():
        pair = dict(pair)
        tasks = dict(pair.get("tasks") or {})
        triage = tasks.get("triage")
        if isinstance(triage, dict):
            triage = {k: v for k, v in triage.items() if k not in ("verdicts", "kinds")}
            triage["per_term_answers"] = "omitted from this summary — in the full artifact"
            tasks["triage"] = triage
        pair["tasks"] = tasks
        results[key] = pair
    out["results"] = results
    out["summarized"] = True
    return out


def last_model_bench_report(*, summary: bool = False) -> dict:
    """The newest saved bench artifact (read-only; never runs a bench)."""
    try:
        files = sorted(BB.bench_dir().glob("oo-model-bench-*.json"))
    except Exception as exc:  # noqa: BLE001
        return {"schema": MODEL_BENCH_SCHEMA, "available": False, "note": str(exc)[:200]}
    if not files:
        return {
            "schema": MODEL_BENCH_SCHEMA,
            "available": False,
            "note": (
                "no comparative model bench has been run yet — it is a heavy operator bench, "
                "run from Settings → Diagnostics on the machine that hosts the models."
            ),
        }
    path = files[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"schema": MODEL_BENCH_SCHEMA, "available": False, "note": str(exc)[:200]}
    data["available"] = True
    data["filename"] = path.name
    return summarize_report(data) if summary else data


__all__ = [
    "BENCH_BACKENDS",
    "BENCH_TASKS",
    "DEFAULT_ROSTER",
    "MODEL_BENCH_SCHEMA",
    "UNRESOLVED_CANDIDATES",
    "assemble_report",
    "bench_one_pair",
    "clear_cursor",
    "last_model_bench_report",
    "load_cursor",
    "pair_key",
    "quantization_of",
    "resolve_pairs",
    "run_model_bench",
    "save_report",
    "summarize_report",
]
