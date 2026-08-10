"""Sampling for the constrained-output sweeps: greedy decoding, decided in ONE place.

WHY THIS EXISTS. ``vllm_client`` learned to map ``options`` onto OpenAI sampling
fields on 2026-07-31, precisely so a caller asking for ``temperature: 0`` would stop
being silently ignored. No production caller ever asked. Every sweep in this package
called ``client.generate(prompt, model=..., system=..., keep_alive=...)`` and nothing
else, so each one ran at the SERVER's default temperature -- 1.0 on an
OpenAI-compatible backend. A capability with no caller is a dead end, and this is that
shape one level down: the plumbing was correct and unused.

WHAT TEMPERATURE 0 ACTUALLY BUYS, stated precisely because the obvious claim is wrong.
It does NOT prevent hallucination. A model invents just as freely under greedy decoding;
it simply invents the SAME thing each time. What it buys is that a difference between
two runs is a difference in the INPUT or in our code, never in the dice -- which is the
only condition under which a gate decision means anything. The perception eval decides
which languages are allowed to store extractions; run under sampling, "Arabic passed"
and "Arabic failed" can both be true of the same model on the same gold set, and the
language that ends up disabled is the one the coin landed on.

WHAT IT DOES NOT GUARANTEE. Greedy decoding is deterministic for a given execution, not
bit-identical across them: vLLM batches concurrent requests continuously, and a
different batch composition changes the order of floating-point reductions inside the
kernels, which can flip a token where two candidates are near-tied. So repeated runs
become CLOSE and comparable rather than provably identical, and a report that promised
identity would be promising something the hardware does not owe.

SCOPE. The constrained-output paths only -- the ones whose reply is parsed against a
fixed vocabulary, an echo-back, or a label set. Prose written for a person to read
(bulk summarise/translate) is deliberately left alone here; the Bulletin's narration
already sets its own temperature 0 for its own reason (an edition regenerated should
read the same), and that decision stays where the prose lives.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
import os

_LOG = logging.getLogger("ai_layer.sampling")

#: An operator who wants to measure what sampling costs can set this. Anything
#: unparseable falls back to greedy and says so once -- a typo in an env var must never
#: silently restore the behaviour this module exists to remove.
TEMPERATURE_ENV = "OO_LLM_SWEEP_TEMPERATURE"

#: The default. ``top_p`` is a no-op under greedy decoding (the argmax token is always
#: inside the nucleus) and is sent anyway so the intent is explicit rather than inherited
#: from whatever the server happens to default to. ``seed`` likewise costs nothing and
#: makes any residual sampling reproducible if an operator raises the temperature.
DEFAULT_TEMPERATURE = 0.0

_warned = False


def sweep_temperature() -> float:
    """The temperature every constrained-output sweep runs at."""
    global _warned
    raw = os.getenv(TEMPERATURE_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_TEMPERATURE
    try:
        value = float(raw)
    except ValueError:
        if not _warned:
            _LOG.warning(
                "%s=%r is not a number; running greedy (temperature %.1f) instead",
                TEMPERATURE_ENV,
                raw,
                DEFAULT_TEMPERATURE,
            )
            _warned = True
        return DEFAULT_TEMPERATURE
    if value < 0:
        if not _warned:
            _LOG.warning(
                "%s=%r is negative; running greedy (temperature %.1f) instead",
                TEMPERATURE_ENV,
                raw,
                DEFAULT_TEMPERATURE,
            )
            _warned = True
        return DEFAULT_TEMPERATURE
    return value


def sweep_options() -> dict[str, float | int]:
    """Sampling options for one constrained-output call.

    Both backends accept these: Ollama takes them in its ``options`` dict natively, and
    ``vllm_client.openai_sampling_params`` maps all three onto the OpenAI-compatible
    body. A caller passes the result straight through as ``options=``.
    """
    return {"temperature": sweep_temperature(), "top_p": 1.0, "seed": 0}


__all__ = [
    "DEFAULT_TEMPERATURE",
    "TEMPERATURE_ENV",
    "sweep_options",
    "sweep_temperature",
]
