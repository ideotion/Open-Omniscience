"""Side-by-side translation evidence, for a human (or Claude) to judge.

WHY THIS EXISTS SEPARATELY FROM THE BENCH'S TRANSLATION TASK. That task answers what
a machine can decide alone: did the model return the language it was asked for, did it
hand back the source unchanged, how fast. It runs on every model with nobody watching.

It cannot answer whether a translation is any GOOD. That needs reference translations
this corpus does not have, and inventing an adequacy number would be worse than
reporting none -- a fabricated quality figure survives into decisions long after the
reason it was invented is forgotten. So the judgement happens OUTSIDE the app, by the
person reading the outputs, which is the chain this project already runs on
(ai-proposed -> claude-verified -> maintainer-merged). What the app owes that reader is
EVIDENCE laid out so differences are visible: the same source, the same target, every
model's answer adjacent.

THREE DIRECTIONS, not one (maintainer 2026-08-11: "translations should not only be
foreign towards english, but also in between foreign languages"). The third is the one
that exposes small models: many pivot through English internally, so a French->German
translation is really French->English->German and loses twice. A probe that only ever
translated into English would never see it.

Sources are REAL CORPUS ARTICLES, stratified by language so a dominant language cannot
fill the sample, and FROZEN with a digest so every model answers identical questions.

PRIVACY: the artifact contains excerpts of the operator's own articles. It is written
locally and shared only by an explicit act, like every other diagnostic here -- but
unlike most of them it carries corpus TEXT, and the report says so on its face.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime

_LOG = logging.getLogger("ai_layer.translation_probe")

TRANSLATION_PROBE_SCHEMA = "oo-translation-probe-1"

#: The app's UI languages, by code -> the name a prompt names them with.
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "fr": "French", "de": "German", "es": "Spanish",
    "pt": "Portuguese", "ru": "Russian", "ar": "Arabic", "zh": "Chinese",
    "ja": "Japanese", "hi": "Hindi", "bn": "Bengali", "id": "Indonesian",
}

#: Enough text for a difference in quality to be visible, and short enough that one
#: model's whole sitting stays readable. Cut at a sentence boundary so no model is
#: judged on a fragment that stops mid-clause -- that would penalise whichever model
#: tried hardest to finish the thought.
EXCERPT_CHARS = 900
_SENTENCE_END = re.compile(r"(?<=[.!?。！？।])\s")

DEFAULT_ARTICLES = 6
DEFAULT_TARGETS_PER_SOURCE = 3


def excerpt(text: str, *, limit: int = EXCERPT_CHARS) -> str:
    """A bounded excerpt ending at a sentence boundary where one exists."""
    s = " ".join((text or "").split())
    if len(s) <= limit:
        return s
    cut = s[:limit]
    ends = list(_SENTENCE_END.finditer(cut))
    return (cut[: ends[-1].end()] if ends else cut).strip()


def choose_targets(
    source_lang: str,
    *,
    n: int = DEFAULT_TARGETS_PER_SOURCE,
    available: tuple[str, ...] | None = None,
) -> list[str]:
    """Targets for one source language, covering the three directions that matter.

    Always includes English (the common case) and at least one OTHER foreign language
    (the case that exposes a model pivoting through English). A source that is already
    English gets foreign targets only -- translating English to English measures
    nothing.

    Deterministic: the same source language always yields the same targets, so two
    models are asked the same questions and a re-run is comparable with the last one.
    """
    codes = list(available or tuple(LANGUAGE_NAMES))
    others = [c for c in codes if c != source_lang]
    picked: list[str] = []
    if source_lang != "en" and "en" in others:
        picked.append("en")
    # Walk the remaining languages from a per-source-language offset, so different
    # sources exercise different pairs rather than every row using the same two.
    rest = [c for c in others if c not in picked and c != "en"]
    if rest:
        start = sum(ord(ch) for ch in source_lang) % len(rest)
        for i in range(len(rest)):
            if len(picked) >= n:
                break
            picked.append(rest[(start + i) % len(rest)])
    for c in others:  # top up if the corpus offered few languages
        if len(picked) >= n:
            break
        if c not in picked:
            picked.append(c)
    return picked[:n]


def build_translation_set(
    articles: list[dict],
    *,
    targets_per_source: int = DEFAULT_TARGETS_PER_SOURCE,
    now=None,
) -> dict:
    """Freeze the questions: which excerpts, into which languages, in what order.

    Pure -- the corpus read lives in :func:`collect_translation_sources` -- so the
    assembly is testable without a database. The digest covers exactly the fields that
    define the questions, so an identical selection re-runs as the same set and a
    changed one is visibly a different sitting.
    """
    items: list[dict] = []
    for a in articles:
        src_lang = (a.get("language") or "").strip().lower()
        if not src_lang or src_lang not in LANGUAGE_NAMES:
            continue  # a language we cannot name in a prompt is not a question we can ask
        body = excerpt(a.get("text") or "")
        if not body:
            continue
        for tgt in choose_targets(src_lang, n=targets_per_source):
            items.append(
                {
                    "article_id": a.get("id"),
                    "source_language": src_lang,
                    "target_language": tgt,
                    "direction": (
                        "from-english" if src_lang == "en"
                        else ("to-english" if tgt == "en" else "foreign-to-foreign")
                    ),
                    "title": a.get("title"),
                    "text": body,
                }
            )
    payload = {
        "schema": TRANSLATION_PROBE_SCHEMA,
        "built_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "n_items": len(items),
        "n_articles": len({i["article_id"] for i in items}),
        "languages": sorted({i["source_language"] for i in items}),
        "directions": {
            d: sum(1 for i in items if i["direction"] == d)
            for d in ("to-english", "from-english", "foreign-to-foreign")
        },
        "items": items,
    }
    raw = json.dumps(
        [(i["article_id"], i["source_language"], i["target_language"], i["text"]) for i in items],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    payload["digest"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return payload


def collect_translation_sources(
    session,
    *,
    n_articles: int = DEFAULT_ARTICLES,
    scan_limit: int = 4000,
    min_chars: int = 400,
) -> list[dict]:
    """Read the corpus once: real articles, stratified by language.

    EQUAL QUOTA PER LANGUAGE, not proportional. A corpus skews, and a proportional
    sample would reproduce that skew inside a probe whose whole point is comparing
    languages -- leaving the languages most likely to break with no row at all.

    Quarantined articles are excluded (they are the nav-soup class, and translating
    a menu measures nothing). The asserted language is preferred and the deduced one
    used only when it is absent, so the two classes are not silently blended.
    """
    from src.database.models import Article

    rows = (
        session.query(
            Article.id, Article.title, Article.content,
            Article.language, Article.detected_language,
        )
        .filter(Article.quarantined.isnot(True))
        .order_by(Article.id.desc())
        .limit(max(1, scan_limit))
        .all()
    )
    by_lang: dict[str, list[dict]] = {}
    for r in rows:
        lang = (r[3] or r[4] or "").strip().lower().split("-")[0]
        if lang not in LANGUAGE_NAMES:
            continue
        text = r[2] or ""
        if len(text) < min_chars:
            continue
        by_lang.setdefault(lang, []).append(
            {"id": r[0], "title": r[1], "text": text, "language": lang,
             "language_basis": "asserted" if r[3] else "deduced"}
        )
    # Round-robin across languages until the quota is met: with fewer languages than
    # slots this fills up from the ones that exist rather than returning short.
    out: list[dict] = []
    order = sorted(by_lang, key=lambda k: (-len(by_lang[k]), k))
    i = 0
    while len(out) < n_articles and any(by_lang.values()):
        lang = order[i % len(order)]
        if by_lang[lang]:
            out.append(by_lang[lang].pop(0))
        i += 1
        if i > len(order) * n_articles + len(order):
            break
    return out


def run_translation_probe(
    clients: dict,
    *,
    models: list[tuple[str, str]],
    tset: dict,
    keep_alive: str | None = None,
    ctx=None,
    allow_backend_switch: bool = False,
    switch=None,
) -> dict:
    """Translate every frozen item with every model, keeping the answers verbatim.

    ``models`` is a list of ``(backend, model)``. Grouped in the report by ITEM, with
    each model's answer beside the others, because the comparison a reader makes is
    "these two answers to the same question", not "this model's list of answers".

    ONE MODEL AT A TIME, all of its items, then the next. The report is still grouped
    by item -- that is a rendering decision and it has not changed -- but the CALL
    order used to follow it, items outer and models inner, so consecutive calls almost
    always asked a different model than the one before. Two things went wrong with
    that on a real machine (field report 2026-08-12: "the CPU is loaded 100% (all
    cores), while gpu is quite often idle"):

      * every call was a model switch. On vLLM a switch is a server restart; on Ollama
        it is a load. Paying that per CALL rather than per MODEL turns an N-item,
        M-model sitting into N x M handovers instead of M.
      * with Ollama's own default keep_alive, the models it was cycled through all
        STAY resident for five minutes -- so a roster of several oversubscribes the
        card, and Ollama spills the overflow onto the CPU. All cores busy, GPU idle,
        exactly as reported.

    The bench already had this discipline (``_grouped_by_backend``, whose docstring
    puts the cost at "tens of seconds each way"); its sibling probe did not.

    ``allow_backend_switch`` defaults to FALSE for the same reason the bench's does:
    handing the card over stops and starts servers, and a function that does that
    merely by being called makes it a side effect of every test and every other caller
    that drives this path. The entry point (:func:`run_translation_comparison`) opts
    in, because there the operator asked for a sitting on this machine.
    """
    from src.ai_layer.model_bench import _default_switch, _translate_system, bounded_error

    if switch is None:
        switch = _default_switch
    items = list(tset.get("items") or [])
    total = len(items) * max(1, len(models))
    done = 0
    # answers[item_index] preserves the by-ITEM grouping the report is built on, while
    # the loop below walks models on the outside.
    answers: list[list[dict]] = [[] for _ in items]
    switches: list[dict] = []

    for backend, model in models:
        if ctx is not None and getattr(ctx, "stopping", False):
            break
        client = clients.get(backend)
        if client is None:
            continue
        # Hand the card over ONCE for this model, not once per item. Without this the
        # probe ran whatever happened to be holding the GPU: on a dual-backend machine
        # a vLLM pair is refused outright (the client will not answer as a model its
        # server was not started with) and an Ollama pair runs against VRAM vLLM is
        # still holding -- which is to say, on the CPU.
        note = None
        if allow_backend_switch:
            try:
                note = switch(backend=backend, model=model)
            except Exception as exc:  # noqa: BLE001 - a failed handover is data
                note = {"ready": False, "reason": bounded_error(exc, 200)}
            switches.append({"backend": backend, "model": model, **(note or {})})
            if note is not None and note.get("ready") is False:
                # Recording five refusals under this model's name would read as "this
                # model translates badly", when nothing was ever asked of it.
                for i in range(len(items)):
                    answers[i].append(
                        {
                            "backend": backend,
                            "model": model,
                            # A FIELD, not a substring of the prose. The renderer has to
                            # tell "we asked and it went wrong" from "we never asked",
                            # and sniffing the error text for "not asked" would be one
                            # reword away from silently calling this a failure again.
                            "asked": False,
                            "translation": "",
                            "chars": 0,
                            "wall_s": None,
                            "error": (
                                f"not asked: {backend} did not come up for this model "
                                f"({note.get('reason') or 'no reason reported'})"
                            )[:300],
                        }
                    )
                done += len(items)
                continue
        for i, item in enumerate(items):
            if ctx is not None and getattr(ctx, "stopping", False):
                break
            system = _translate_system(LANGUAGE_NAMES[item["target_language"]])
            t0 = time.monotonic()
            try:
                res = client.generate(
                    item["text"], model=model, system=system,
                    options={"temperature": 0}, keep_alive=keep_alive,
                )
                out = (getattr(res, "text", "") or "").strip()
                err = None
            except Exception as exc:  # noqa: BLE001 - a failed call is data
                out, err = "", bounded_error(exc, 300)
            wall = time.monotonic() - t0
            done += 1
            if ctx is not None:
                ctx.set_progress(done=done, total=total,
                                 detail=f"{backend} · {model} · {item['target_language']}")
            answers[i].append(
                {
                    "backend": backend,
                    "model": model,
                    "asked": True,
                    "translation": out,
                    "chars": len(out),
                    "wall_s": round(wall, 3),
                    "error": err,
                }
            )

    results = [{**item, "answers": answers[i]} for i, item in enumerate(items)]
    return {
        "schema": TRANSLATION_PROBE_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "batch_digest": tset.get("digest"),
        "models": [f"{b}|{m}" for b, m in models],
        "n_items": len(results),
        "languages": tset.get("languages"),
        "directions": tset.get("directions"),
        # What the card actually did, published rather than merely collected: a
        # handover that was REFUSED is the reason a model's column is empty, and a
        # reader who can only see the empty column has to guess why.
        "handovers": switches,
        "items": results,
        "method": (
            "Real corpus excerpts, stratified by language with an EQUAL quota each so a "
            "dominant language cannot fill the sample, frozen with a digest so every "
            "model answers identical questions. Each item is translated by every model "
            "with the app's PRODUCTION translate prompt at temperature 0, and the "
            "answers are kept verbatim and grouped by item so two answers to the same "
            "question sit side by side. Three directions are covered: into English, out "
            "of English, and between two foreign languages — the last because a model "
            "that pivots through English internally loses twice, and a probe that only "
            "translated into English would never see it."
        ),
        "caveat": (
            "NO QUALITY SCORE IS COMPUTED HERE, and none can be: adequacy and fluency "
            "need reference translations this corpus does not have. This file is "
            "EVIDENCE for a reader to judge, not a measurement — the numbers beside "
            "each answer are its length and its wall time, nothing more."
        ),
        "privacy": (
            "This file contains excerpts of your own articles. It is written locally "
            "and shared only if you send it."
        ),
    }


def render_comparison_markdown(report: dict) -> str:
    """The same evidence laid out to be READ: one heading per question, the models'
    answers under it. A reader comparing two translations should not have to hold a
    JSON path in their head to do it."""
    out: list[str] = [
        "# Translation comparison",
        "",
        f"- generated: {report.get('generated_at')}",
        f"- batch digest: `{report.get('batch_digest')}`",
        f"- models: {', '.join(report.get('models') or [])}",
        f"- directions: {report.get('directions')}",
        "",
        f"> {report.get('caveat')}",
        "",
        f"> {report.get('privacy')}",
        "",
    ]
    for n, item in enumerate(report.get("items") or [], 1):
        src, tgt = item["source_language"], item["target_language"]
        out += [
            f"## {n}. {src} → {tgt}  ·  _{item['direction']}_",
            "",
            f"**Source** (article {item.get('article_id')}, {src}):",
            "",
            "> " + (item.get("text") or "").replace("\n", " "),
            "",
        ]
        for a in item.get("answers") or []:
            head = f"### {a['backend']} | {a['model']}"
            # NOT ASKED IS NOT FAILED, and this is the boundary where that distinction
            # was being thrown away. The probe already refuses to record a refused
            # handover as five bad translations -- and then the markdown, which is the
            # artifact a person actually reads, labelled every one of them "failed".
            # A model that was never given the card has produced no evidence about
            # itself in either direction.
            if a.get("asked") is False:
                out += [head, "", f"_not asked — {a.get('error') or 'no reason reported'}_",
                        "", "_Nothing was measured for this model on this item._", ""]
                continue
            if a.get("error"):
                out += [head, "", f"_failed:_ `{a['error']}`", ""]
                continue
            out += [head, "", f"_{a['chars']} chars · {a['wall_s']}s_", "",
                    (a.get("translation") or "_(empty)_").replace("\n", " "), ""]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
#  Persistence (mirrors perception_job's dated-artifact convention)
# --------------------------------------------------------------------------- #
def _dir():
    from src.paths import data_dir

    d = data_dir() / "triage"  # the one AI-run archive, shared with the other probes
    d.mkdir(parents=True, exist_ok=True)
    return d


def _export_path(ext: str = "json"):
    return _dir() / f"oo-translation-probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{ext}"


def run_and_persist_translation_probe(
    *,
    models: list[str] | None = None,
    n_articles: int = DEFAULT_ARTICLES,
    targets_per_source: int = DEFAULT_TARGETS_PER_SOURCE,
    clients: dict | None = None,
    session=None,
    ctx=None,
) -> dict:
    """Sample the corpus, translate with every model, persist BOTH forms.

    Two files on purpose: the JSON is the record (re-readable, diffable against a
    later sitting), the Markdown is the thing a person actually reads to compare two
    translations. Writing only the first would leave the reader doing JSON archaeology
    to answer "which of these is better", which is the entire question.

    ``models`` are ``backend|model`` identifiers; absent, every installed roster pair
    is used, so the default run compares what this machine can actually serve.
    """
    from src.ai_layer.model_bench import (
        BENCH_BACKENDS,
        DEFAULT_ROSTER,
        _clients_for,
        _installed_by_backend,
        resolve_pairs,
    )

    own_session = session is None
    if own_session:
        from src.database.session import SessionLocal

        session = SessionLocal()
    try:
        articles = collect_translation_sources(session, n_articles=n_articles)
    finally:
        if own_session:
            session.close()

    tset = build_translation_set(articles, targets_per_source=targets_per_source)
    if not tset["n_items"]:
        return {
            "schema": TRANSLATION_PROBE_SCHEMA,
            "available": False,
            "note": (
                "no corpus article long enough, unquarantined, and in a language this "
                "app can name was found — nothing to ask, and an empty sitting is "
                "reported rather than filled with invented text."
            ),
        }

    if clients is None:
        clients = _clients_for(tuple(BENCH_BACKENDS))
    if models is None:
        # The same resolution the bench uses, so this probe compares exactly the pairs
        # the bench does -- a second, drifting notion of "which models" is how two
        # reports about one machine start disagreeing.
        installed = _installed_by_backend(tuple(BENCH_BACKENDS), wanted=list(DEFAULT_ROSTER))
        runnable, _skipped = resolve_pairs(
            models=list(DEFAULT_ROSTER), installed_by_backend=installed
        )
        pairs = [(p["backend"], p["model"]) for p in runnable]
    else:
        pairs = [(m.split("|", 1)[0], m.split("|", 1)[1]) for m in models if "|" in m]

    # The operator asked for a sitting on THIS machine, so the card is handed to each
    # model in turn -- the opt-in the low-level function deliberately does not take on
    # its own. Without it the probe measures whatever happened to be holding the GPU,
    # which on a dual-backend machine means the CPU.
    from src.llm.arbitration import current_holder, restore_or_release

    try:
        prior = current_holder()
    except Exception:  # noqa: BLE001 - an unreadable prior state is not a crash
        prior = None
    try:
        out = run_translation_probe(
            clients, models=pairs, tset=tset, ctx=ctx, allow_backend_switch=True
        )
    finally:
        # Leave the machine as it was found -- INCLUDING "nothing was serving", which
        # is a state a run has to be able to restore rather than a case to skip. In a
        # `finally` because a run that failed half way through has still moved the
        # card, and the operator's machine should not be left on a model this probe
        # chose. Best-effort: a restore that fails is reported, never raised over the
        # result the run did produce.
        try:
            _restore_note = restore_or_release(prior)
        except Exception as exc:  # noqa: BLE001
            _restore_note = {"restored": False, "reason": str(exc)[:200]}
    out["backend_restore"] = _restore_note
    jpath = _export_path("json")
    jpath.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    mpath = jpath.with_suffix(".md")
    mpath.write_text(render_comparison_markdown(out), encoding="utf-8")
    out["available"] = True
    out["path"] = str(jpath)
    out["markdown_path"] = str(mpath)
    return out


def last_translation_probe(*, markdown: bool = False) -> dict:
    """The newest saved sitting (read-only; never runs a probe)."""
    try:
        files = sorted(_dir().glob("oo-translation-probe-*.json"))
        if not files:
            return {
                "schema": TRANSLATION_PROBE_SCHEMA,
                "available": False,
                "note": (
                    "no translation comparison has been run yet — run it from "
                    "Settings → AI, or POST /api/diagnostics/translation-probe."
                ),
            }
        path = files[-1]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["available"] = True
        data["filename"] = path.name
        if markdown:
            md = path.with_suffix(".md")
            data["markdown"] = md.read_text(encoding="utf-8") if md.is_file() else None
        return data
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {"schema": TRANSLATION_PROBE_SCHEMA, "available": False, "error": str(exc)[:300]}
