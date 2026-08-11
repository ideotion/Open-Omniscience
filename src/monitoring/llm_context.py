"""What a bigger context window costs, and what it buys — measured, not argued.

Maintainer ask 2026-08-10: "I'm not sure we've tested context size management. We
should add a test to see the impact of increased context size."

The decision has two halves and they pull in opposite directions, which is exactly why
it needs measuring rather than a rule of thumb:

* **What it COSTS.** Every extra token of prompt is paid on every call, in latency and
  in KV cache. On vLLM the cache is also what limits how many requests fit at once, so
  a bigger window is paid a second time in lost concurrency. This module measures the
  first cost directly — same model, same concurrency, prompts of increasing size — and
  reports the second as the configured limit it would compete with.
* **What it BUYS.** Coverage of the corpus that actually exists. A budget of 6,000
  characters over a corpus whose articles run to 40,000 is not a context setting, it is
  a decision to read the first sixth of every long article. The coverage half is read
  from the shipped ``article_length`` diagnostic, so it is this operator's corpus and
  not a general claim.

Put together, they answer the only question worth asking: at what point does a longer
window stop buying coverage worth the latency.

WHAT THIS DOES NOT DO. It does not restart the server at several ``max_model_len``
values. That would measure the KV-cache cost end to end, and it is the honest next
step — but each level is a full model reload, so it belongs in the deep bench beside
the model switch rather than in a check measured in minutes. What is reported instead
is the SERVING limit as a fact, so a prompt size that would not fit today is named
rather than silently attempted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from src.monitoring.llm_bench import _one_call, _prompt_of, _SHAPES_BY_ID
from src.monitoring.llm_throughput import _run_level

SCHEMA = "oo-llm-context-1"

#: Prompt sizes swept, in characters. Chosen to bracket what a news corpus actually
#: contains: 2k is a wire brief, 6k is the constant every background sweep used before
#: this was measurable, 24k is a long feature, 48k is the tail.
DEFAULT_SIZES = (2000, 6000, 12000, 24000, 48000)
DEFAULT_CALLS = 4


def _serving_limit_tokens(backend_name: str | None) -> dict:
    """What the running backend will actually accept, and how we know.

    A configured setting and a serving limit are DIFFERENT NUMBERS and the field runs
    proved it: the operator's setting said 8192 while vLLM had computed 2048 from free
    VRAM. Reporting the setting as though it governed would misdescribe every result
    below it.
    """
    if backend_name == "vllm":
        try:
            from src.llm.backend import detect_gpu
            from src.llm.vllm_lifecycle import compute_server_args

            gpu = detect_gpu() or {}
            args = (
                compute_server_args(
                    gpu.get("vram_mb"), vram_free_mb=gpu.get("vram_free_mb")
                )
                or {}
            )
            return {
                "tokens": args.get("max_model_len"),
                "source": "vLLM's computed max_model_len (derived from VRAM at start)",
            }
        except Exception as exc:  # noqa: BLE001
            return {"tokens": None, "source": f"could not be read ({exc})"}
    try:
        from src.config.app_settings import load_settings

        n = getattr(load_settings(), "llm_max_context_length", None)
        return {
            "tokens": int(n) if n else None,
            "source": "the operator's configured context length (Ollama)",
            "note": (
                "Ollama is not SENT this value by the background sweeps today — it "
                "serves each model's own default window. The number is what the "
                "operator asked for, not necessarily what the daemon used."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"tokens": None, "source": f"could not be read ({exc})"}


def corpus_coverage(sizes=DEFAULT_SIZES, *, report: dict | None = None) -> dict:
    """What share of THIS corpus each budget reads in full.

    Uses the shipped ``article_length`` diagnostic's own histogram rather than a fresh
    scan. Absent (never run), the answer is an honest gap: a coverage figure invented
    from a guessed distribution would be the most misleading number on the page,
    because it is the half of the trade the operator cannot check by eye.
    """
    # Deliberately NOT computed here. ``article_length_report`` is a full scan of the
    # articles table; running it inside a bench would make a minutes-long check into a
    # corpus-long one, and silently. The caller passes the report if it has one.
    if not report:
        return {
            "available": False,
            "reason": (
                "the corpus's article-length distribution has not been measured — run "
                "the article-length diagnostic, then this becomes a real coverage curve "
                "instead of a guess"
            ),
        }
    return {"available": True, "source": "the article-length diagnostic", "report": report}


def run_context_bench(
    *,
    sizes=DEFAULT_SIZES,
    calls: int = DEFAULT_CALLS,
    concurrency: int = 1,
    client=None,
    model: str | None = None,
    backend_name: str | None = None,
) -> dict:
    """Latency and throughput at increasing prompt size, on one model, one concurrency.

    Concurrency is held FIXED and stated: sweeping both at once produces a surface
    nobody can read, and the question here is what a longer prompt costs, not how it
    interacts with batching.
    """
    started = time.monotonic()
    if client is None:
        try:
            from src.api.llm import active_model
            from src.llm.backend import get_client_with_name, resolve_backend

            resolved = resolve_backend()
            if not resolved.get("available"):
                return {
                    "schema": SCHEMA,
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "available": False,
                    "reason": resolved.get("reason") or "no local LLM backend is reachable",
                    "note": (
                        "No figures are reported. A context curve measured against an "
                        "unreachable backend would be invented."
                    ),
                }
            backend_name, client = get_client_with_name()
            model = model or active_model()
        except Exception as exc:  # noqa: BLE001
            return {
                "schema": SCHEMA,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "available": False,
                "reason": f"could not resolve a backend: {type(exc).__name__}: {exc}",
            }

    _sid, _name, _chars, system = _SHAPES_BY_ID["perception"]
    limit = _serving_limit_tokens(backend_name)

    # One warmup, excluded: the first call carries model load and would land entirely
    # on the smallest size, which is the baseline every other one is read against.
    _one_call(client, model=model or "", prompt=_prompt_of(min(sizes)), system=system)

    from src.ai_layer.context import estimate_tokens

    rows: list[dict] = []
    for chars in sizes:
        est = estimate_tokens(chars, "latin")
        over = bool(limit.get("tokens") and est > int(limit["tokens"]))
        level = _run_level(
            client,
            model=model or "",
            prompt=_prompt_of(chars),
            system=system,
            calls=max(1, calls),
            workers=max(1, concurrency),
        )
        rows.append(
            {
                "prompt_chars": chars,
                "estimated_prompt_tokens": est,
                "beyond_serving_limit": over,
                **level,
            }
        )

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "available": True,
        "backend": backend_name,
        "model": model,
        "concurrency": concurrency,
        "calls_per_size": calls,
        "serving_limit": limit,
        "sizes": rows,
        "coverage": corpus_coverage(sizes),
        "reading": _reading(rows, limit),
        "elapsed_s": round(time.monotonic() - started, 2),
        "method": (
            "The same deterministic prompt shape at increasing character counts, at a "
            "FIXED concurrency, at temperature 0, after one excluded warmup. Token "
            "counts are ESTIMATES from a per-script characters-per-token rule of thumb "
            "— this has no tokenizer, and a derived number is never presented as a "
            "measured one."
        ),
        "caveat": (
            "Measured on THIS machine with THIS model. It measures what a longer PROMPT "
            "costs, not what a larger configured WINDOW costs: raising max_model_len "
            "also enlarges the KV cache and takes concurrency away, which needs a "
            "server restart per level to measure and is not done here."
        ),
    }


def _reading(rows: list[dict], limit: dict) -> dict:
    """The cost curve in one sentence, or an honest refusal."""
    usable = [r for r in rows if r.get("n")]
    if len(usable) < 2:
        return {
            "readable": False,
            "reason": "fewer than two sizes produced a timing, so there is no curve to read",
        }
    first, last = usable[0], usable[-1]
    # ``call_wall_p50_s`` is _run_level's OWN key. An earlier cut read ``wall_p50_s``,
    # which does not exist there, and every run published `note: None` — a reading that
    # silently said nothing rather than saying it could not read. The guard below makes
    # a wrong key LOUD instead of empty.
    p50_a, p50_b = first.get("call_wall_p50_s"), last.get("call_wall_p50_s")
    out: dict = {
        "readable": True,
        "smallest": {"prompt_chars": first["prompt_chars"], "call_wall_p50_s": p50_a},
        "largest": {"prompt_chars": last["prompt_chars"], "call_wall_p50_s": p50_b},
    }
    if not (p50_a and p50_b):
        out["note"] = (
            "the levels produced calls but no median wall time, so the cost curve "
            "cannot be read from this run"
        )
    if p50_a and p50_b:
        # Round ONCE, publish that, and build the sentence from the PUBLISHED numbers.
        # An earlier cut published `round(raw, 2)` and formatted the RAW value into the
        # note, which is two roundings of one quantity: a raw 0.9549 publishes 0.95 and
        # prints "1.0x the wall time", so the sentence contradicted the field beside it.
        # Rare, but real -- a macOS CI runner landed in that band (2026-08-11) and the
        # self-consistency test caught it. Deriving both from `ratio`/`span` makes the
        # agreement structural rather than something each future edit has to remember.
        ratio = round(p50_b / p50_a, 2)
        span = round(last["prompt_chars"] / max(1, first["prompt_chars"]), 2)
        out["latency_ratio"] = ratio
        out["size_ratio"] = span
        # Sub-linear is the interesting case and the common one: prompt processing is
        # parallel, so N times the text is usually far less than N times the wall.
        out["note"] = (
            f"{span:.0f}x the prompt cost {ratio:.1f}x the wall time. "
            + (
                "Sub-linear — prompt tokens are processed in parallel, so a longer "
                "article is cheaper than its length suggests."
                if ratio < span * 0.8
                else "Roughly proportional to length on this machine."
            )
        )
    refused = [r["prompt_chars"] for r in rows if r.get("beyond_serving_limit")]
    if refused:
        out["beyond_serving_limit"] = refused
        out["limit_note"] = (
            f"{len(refused)} size(s) estimate past this backend's serving limit of "
            f"{limit.get('tokens')} tokens. Their rows are measurements of what the "
            "backend did with an over-long prompt (refuse, or truncate its own way) — "
            "not of the model reading that much text."
        )
    return out


__all__ = ["DEFAULT_SIZES", "SCHEMA", "corpus_coverage", "run_context_bench"]
