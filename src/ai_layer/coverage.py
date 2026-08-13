"""Whole-article coverage for the background sweeps.

RULING (maintainer, 2026-08-10), verbatim: *"We need to change that articles are
truncated for background sweeps, it's not acceptable. Background sweeps should
process entire articles, otherwise it won't work."*

WHAT THE SWEEPS DID BEFORE. Cut the article at a hardcoded 6,000 characters (4,000 for
the qualification classifier), run the model on that, and — for perception — record a
disclosure saying so. The disclosure was honest and the result was still wrong for this
corpus: against a ~22 KB average article and a 412 KB tail, a who/where/when pass read
the opening of every long article and nothing else, so the AI layer was systematically
blind to article BODIES. A disclosure makes a gap visible; it does not fill it.

WHAT REPLACES IT. The article is split into parts that each FIT the window and together
ARE the article (``context.chunk_text``'s exact-coverage property), every part is sent,
and the parts are combined by whatever the sweep's own output shape demands — a union
for a set of extracted items, a stated rule for a label. Nothing is dropped, so nothing
needs disclosing; what IS disclosed is the part COUNT, because coverage is bought with
calls and the operator should see the bill.

THE BUDGET IS TWO-SIDED, and this is the half that was missing. ``budget_chars`` already
existed on the perception adapter and NO caller ever passed it, so every sweep ran at
the hardcoded constant regardless of the machine. Wiring the operator's setting straight
through would have been WORSE than the gap: on the field machine
``llm_max_context_length`` was 8192 while vLLM had computed ``max_model_len`` 2048 from
free VRAM, so the "fixed" budget would have been ~26,600 characters against a window
that accepts ~2,000 — every sweep call failing on a machine where they currently
succeed. The budget is therefore ``min(what the operator configured, what the backend
will actually serve)``, with the second half READ from the backend rather than assumed.

AND THE WINDOW HAS TO BE SENT, not just sized for. Ollama serves each model's own
default ``num_ctx`` (2048 on many builds) unless it is told otherwise, and the sweeps
never told it — so sizing a 26,000-character part for a configured 8192-token window
would have handed the daemon a prompt it silently cuts, reintroducing at the server
exactly the truncation this module removes at the client. The governing token count
therefore travels back to the caller in the basis and is sent as ``num_ctx``; vLLM's
mapper drops the key and REPORTS the drop (its window is fixed at server start, so
there is nothing to ask for).

COST, stated rather than discovered. Parts scale as ``len(article) / budget``, so a
small serving window is paid in calls: a 40,000-character article is one call at a 40k
budget and twenty at 2k. There is deliberately NO cap on parts — a cap is truncation
wearing a different name, which is the thing being removed. The lever is the WINDOW, not
the coverage, which is why the resolved budget and both of its inputs travel with every
result.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time

from src.ai_layer.context import (
    SWEEP_OUTPUT_RESERVE_TOKENS,
    chunk_text,
    dominant_script,
    text_budget_chars,
)

#: How long a resolved serving window is reused. The probe behind it shells out to
#: ``nvidia-smi``; running that per ARTICLE would make the fix cost more than the
#: truncation it removes. Five minutes is short enough that a backend switch or a
#: restarted server is picked up within a batch or two, and long enough that a
#: 25-article batch resolves once.
WINDOW_TTL_S = 300.0

_window_cache: dict[str, tuple[float, dict]] = {}


def reset_window_cache() -> None:
    """Forget the resolved window.

    For tests, and for a caller that has just switched backends and therefore KNOWS the
    cached answer describes the old one — the arbitration path changes which server is
    running, and a stale window there would size prompts for a machine state that no
    longer exists.
    """
    _window_cache.clear()


def _resolve_window(backend_name: str | None) -> dict:
    name = (backend_name or "").strip().lower()
    if not name:
        try:
            from src.llm.backend import resolve_backend

            name = (resolve_backend().get("backend") or "").strip().lower()
        except Exception as exc:  # noqa: BLE001 - resolution is advisory here
            return {
                "tokens": None,
                "source": f"the backend could not be resolved ({type(exc).__name__})",
                "backend": None,
            }
    if name == "vllm":
        # ASK THE SERVER FIRST. Its model card carries the window it was actually
        # started with; anything else here is a re-derivation of an estimate against a
        # card whose free memory the running server has itself changed. The two
        # diverge in BOTH directions -- a server started while another process held
        # the card keeps its small window after that process releases, and a
        # re-derivation run while vLLM is resident reads a nearly-full card -- so the
        # difference is not a safety margin, it is a wrong number either way. A
        # prompt sized above the server's real window is refused with a 400, which is
        # exactly the field failure this replaces.
        try:
            from src.llm.vllm_client import VllmClient

            served = VllmClient().served_window()
            if served:
                return {
                    "tokens": int(served),
                    "source": "the running vLLM server's own max_model_len (/v1/models)",
                    "backend": "vllm",
                }
        except Exception:  # noqa: BLE001 - fall through to the estimate below
            pass
        # No server to ask (not started yet, or a build whose model card omits the
        # field). The estimate is the honest fallback and is LABELLED as one -- it
        # describes what a start right now would choose, not what is being served.
        try:
            from src.llm.backend import detect_gpu
            from src.llm.vllm_lifecycle import compute_server_args

            gpu = detect_gpu() or {}
            args = (
                compute_server_args(gpu.get("vram_mb"), vram_free_mb=gpu.get("vram_free_mb"))
                or {}
            )
            n = args.get("max_model_len")
            return {
                "tokens": int(n) if n else None,
                "source": (
                    "an ESTIMATE from current free VRAM — the running server could not "
                    "be asked, so this is what a start now would choose, not what is "
                    "being served"
                ),
                "backend": "vllm",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "tokens": None,
                "source": f"vLLM's window could not be read ({type(exc).__name__})",
                "backend": "vllm",
            }
    # Ollama's real limit is per model and not exposed by a cheap call. Reporting None
    # is the honest answer: the caller then governs on the operator's own setting AND
    # sends it as num_ctx, so the daemon serves the window we sized for instead of its
    # own default.
    return {
        "tokens": None,
        "source": (
            "Ollama serves each model's own default window unless it is sent num_ctx, "
            "so its ceiling is not readable here — the configured window governs and "
            "is sent with the request"
        ),
        "backend": name or None,
    }


def serving_window_tokens(backend_name: str | None = None) -> dict:
    """What the running backend will ACTUALLY accept, in tokens, and how we know.

    A configured setting and a serving limit are DIFFERENT NUMBERS, and the field runs
    proved it: the operator's setting said 8192 while vLLM had computed 2048 from free
    VRAM. Reporting the setting as though it governed would size every prompt for a
    window that does not exist.

    ``{"tokens": int | None, "source": str, "backend": str | None}`` — ``None`` is an
    honest "could not be read", never a guessed number.
    """
    key = "backend:" + (backend_name or "auto").strip().lower()
    now = time.monotonic()
    hit = _window_cache.get(key)
    if hit and (now - hit[0]) < WINDOW_TTL_S:
        return hit[1]
    out = _resolve_window(backend_name)
    _window_cache[key] = (now, out)
    return out


def _read_configured_tokens() -> int | None:
    try:
        from src.config.app_settings import load_settings

        n = getattr(load_settings(), "llm_max_context_length", None)
        return int(n) if n and int(n) > 0 else None
    except Exception:  # noqa: BLE001 - settings are advisory here
        return None


def _configured_tokens() -> int | None:
    """The operator's configured window, cached on the SAME clock as the probe.

    ``load_settings`` reads the encrypted KV store, so this is a database read; per
    ARTICLE it would be a real cost for a value that changes when a human edits a
    setting. Cached here rather than passed down from the batch, because the per-ARTICLE
    part of the budget is not this number — it is the SCRIPT (see ``sweep_text_budget``).
    """
    now = time.monotonic()
    hit = _window_cache.get("__configured__")
    if hit and (now - hit[0]) < WINDOW_TTL_S:
        return hit[1].get("tokens")
    tokens = _read_configured_tokens()
    _window_cache["__configured__"] = (now, {"tokens": tokens})
    return tokens


def sweep_text_budget(
    text: str | None = None, *, backend_name: str | None = None
) -> tuple[int, dict]:
    """Characters of article text ONE sweep call may carry, and how that was decided.

    ``min(configured, serving)``. Either half may honestly be missing; with BOTH
    missing the answer is the pre-existing constant, so a machine that can tell us
    nothing behaves exactly as it did before rather than getting a guessed budget.

    CALL THIS PER ARTICLE, not once per batch. Both expensive inputs are cached on a
    shared TTL (the nvidia-smi probe and the settings read), but the third input is the
    article's own SCRIPT, and that is not shared: a token buys ~4 Latin characters and
    ~1.2 CJK ones, so sizing a Chinese article's parts with a Latin article's ratio
    makes them ~3x too big — they overflow the window and the server truncates them
    silently, which is the exact defect this module exists to remove.

    Returns ``(budget_chars, basis)``. The basis carries ``num_ctx`` — the token count
    that governed — because the caller must SEND it (Ollama) as well as size for it.
    """
    script = dominant_script(text or "")
    configured = _configured_tokens()
    serving = serving_window_tokens(backend_name)
    serving_tokens = serving.get("tokens")
    candidates = [t for t in (configured, serving_tokens) if isinstance(t, int) and t > 0]
    tokens = min(candidates) if candidates else None

    if tokens is None:
        governing = "neither the configured window nor the backend's could be read"
    elif serving_tokens and tokens == serving_tokens and tokens != configured:
        governing = "the backend's serving window"
    elif configured and tokens == configured and tokens != serving_tokens:
        governing = "the operator's configured window"
    else:
        governing = "both windows agree"

    # A sweep's reply is bounded by its PARSER (three lines, or N terms of <=80 chars,
    # or one word), not by a writer's inclination, so it reserves far less of the window
    # for output than a summary does — which is what makes whole-article coverage
    # affordable on a small window. See SWEEP_OUTPUT_RESERVE_TOKENS.
    budget = text_budget_chars(tokens, script, output_reserve=SWEEP_OUTPUT_RESERVE_TOKENS)
    return budget, {
        "budget_chars": budget,
        "num_ctx": tokens,
        "script": script,
        "configured_tokens": configured,
        "serving_tokens": serving_tokens,
        "serving_source": serving.get("source"),
        "backend": serving.get("backend"),
        "governing": governing,
        "output_reserve_tokens": SWEEP_OUTPUT_RESERVE_TOKENS,
        "method": (
            "min(the operator's configured context, what the backend will actually "
            "serve), minus reserve for the prompt and for a CONSTRAINED reply, "
            "converted to characters by a per-script rule of thumb — an ESTIMATE, not "
            "a tokenizer"
        ),
    }


def split_for_sweep(text: str | None, budget_chars: int) -> tuple[list[str], dict]:
    """Split an article into parts that each fit and TOGETHER ARE the article.

    Returns ``(parts, coverage)``. ``coverage`` is the shape every sweep reports, so a
    multi-part run is legible in the tally without each sweep inventing its own words.
    ``complete`` is True by construction here — it exists so a reader does not have to
    infer completeness from the absence of a truncation field, which is precisely how
    the old disclosure got skimmed.
    """
    body = text or ""
    parts = chunk_text(body, budget_chars)
    cov: dict = {
        "parts": len(parts),
        "chars": len(body),
        "budget_chars": budget_chars,
        "complete": True,
    }
    if len(parts) > 1:
        cov["note"] = (
            f"read in {len(parts)} parts to cover all {len(body)} characters — every "
            "part was sent to the model; the parts are combined, not sampled"
        )
    return parts, cov


def merge_items(per_part: list[list[str]], *, limit: int | None = None) -> list[str]:
    """Union item lists from consecutive parts, de-duplicated, ROUND-ROBIN.

    Round-robin is the load-bearing detail. Concatenating the parts and cutting at
    ``limit`` would take every item from the first part or two — reinstating exactly
    the head bias the chunking removes, while looking like full coverage. Taking one
    item from each part in turn lets every part contribute before any part contributes
    twice.

    De-duplication is case-insensitive keeping the FIRST form, matching
    ``extract.parse_terms``' own convention so a proper noun's casing survives.
    """
    out: list[str] = []
    seen: set[str] = set()
    depth = max((len(p) for p in per_part), default=0)
    for i in range(depth):
        for part in per_part:
            if i >= len(part):
                continue
            item = (part[i] or "").strip()
            if not item:
                continue
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if limit is not None and len(out) >= limit:
                return out
    return out


__all__ = [
    "WINDOW_TTL_S",
    "merge_items",
    "reset_window_cache",
    "serving_window_tokens",
    "split_for_sweep",
    "sweep_text_budget",
]
