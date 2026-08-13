"""The context window is derived from the model in front of us, not from a model class.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIELD REPORT 2026-08-13. A sweep failed ten times over with::

    vLLM error for model 'mistralai/Ministral-3-3B-Instruct-2512': Client error
    '400 Bad Request' ... This model's maximum context length is 2048 tokens.
    — retrying in 60s in case it comes back (9/10)

The maintainer's reading was that the model takes far more than 2048, and it was
right: 2048 was OUR OWN ``--max-model-len``. Four separate things produced that line
and each has a test here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import src.llm.vllm_lifecycle as V
from src.llm.backend import outage_detail
from src.llm.ollama import is_context_overflow
from src.llm.vllm_lifecycle import compute_server_args, kv_mb_per_token

# The real body vLLM returns, quoted so the tests are driven by the server's own words.
VLLM_OVERFLOW = (
    "This model's maximum context length is 2048 tokens. However, you requested 2940 "
    "tokens (2616 in the messages, 324 in the completion). Please reduce the length of "
    "the messages or completion."
)


def _snapshot(tmp_path: Path, cfg: dict) -> str:
    rev = tmp_path / "snapshots" / "rev0"
    rev.mkdir(parents=True)
    (rev / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return str(tmp_path)


def _with_snapshot(root: str):
    return patch.object(V, "model_cache_state", lambda m: {"cached": True, "path": root})


# --------------------------------------------------------------------------- #
#  1. The KV figure comes from the checkpoint's own shape.
# --------------------------------------------------------------------------- #


def test_the_formula_rederives_the_hand_computed_7B_constant(tmp_path):
    """The strongest available check that the arithmetic is right.

    ``_KV_MB_PER_TOKEN``'s comment derives 0.5 MB/token by hand for a 7B-class model:
    "2 (K and V) x 32 layers x 32 heads x 128 head dim x 2 bytes (fp16) = 512 KB". Fed
    that same shape, the config reader must land on exactly that number -- if it does
    not, one of the two is wrong and this catches it without needing a GPU.
    """
    root = _snapshot(tmp_path, {
        "num_hidden_layers": 32, "num_attention_heads": 32,
        "hidden_size": 4096, "torch_dtype": "float16",
    })
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("some/7b")
    assert mb == pytest.approx(V._KV_MB_PER_TOKEN)
    assert basis["grouped_query"] is False


def test_a_grouped_query_model_costs_several_times_less_and_says_so(tmp_path):
    """The whole point of reading the config. GQA shares KV heads across attention
    heads, so the cache is a fraction of what the multi-head constant assumes -- and
    that fraction is the difference between a 2048-token window and a useful one."""
    root = _snapshot(tmp_path, {
        "num_hidden_layers": 26, "num_attention_heads": 24, "num_key_value_heads": 8,
        "head_dim": 128, "torch_dtype": "bfloat16",
    })
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("some/3b")
    assert mb < V._KV_MB_PER_TOKEN / 3
    assert basis["grouped_query"] is True
    assert basis["kv_heads"] == 8 and basis["attention_heads"] == 24


def test_head_dim_is_read_not_assumed(tmp_path):
    """``head_dim`` is NOT always ``hidden_size // num_attention_heads`` -- newer
    configs publish it precisely because it can differ. Deriving it when it is stated
    would compute the wrong cache size for exactly those models."""
    root = _snapshot(tmp_path, {
        "num_hidden_layers": 4, "num_attention_heads": 8, "num_key_value_heads": 8,
        "hidden_size": 512,  # would imply head_dim 64
        "head_dim": 128,     # ...but the model says 128
        "torch_dtype": "float16",
    })
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("some/odd")
    assert basis["head_dim"] == 128
    assert mb == pytest.approx((2 * 4 * 8 * 128 * 2) / 1024**2)


def test_a_quantised_checkpoint_does_not_shrink_the_KV_estimate(tmp_path):
    """An FP8 repo quantises the WEIGHTS; the KV cache still runs at the compute dtype.
    Reading 1 byte/element off the repo NAME would under-reserve the cache, which is
    the direction that fails at startup rather than the direction that costs context."""
    root = _snapshot(tmp_path, {
        "num_hidden_layers": 8, "num_attention_heads": 8, "num_key_value_heads": 8,
        "head_dim": 128, "torch_dtype": "bfloat16",
    })
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("some/model-FP8-quantized")
    assert basis["bytes_per_element"] == 2.0
    assert mb == pytest.approx((2 * 8 * 8 * 128 * 2) / 1024**2)


def test_an_unreadable_config_returns_None_never_a_guess(tmp_path):
    """A missing reading must not become a generous number -- the caller keeps the
    conservative fallback, which is the whole reason the fallback still exists."""
    root = _snapshot(tmp_path, {"unrelated": True})  # no shape fields at all
    with _with_snapshot(root):
        assert kv_mb_per_token("some/model") is None
    with patch.object(V, "model_cache_state", lambda m: {"cached": False, "path": None}):
        assert kv_mb_per_token("never/downloaded") is None


# --------------------------------------------------------------------------- #
#  2. What that does to the window.
# --------------------------------------------------------------------------- #


def test_the_field_machine_stops_hitting_the_2048_floor():
    """THE REPORTED DEFECT. On the 8 GB card this app is designed around, the old
    constants floored max_model_len at 2048 the moment free VRAM fell below ~6.5 GB --
    which is any card also holding a display server. With the model's real figures the
    same free memory buys a window that can carry an article."""
    old = compute_server_args(8192, vram_free_mb=int(5.0 * 1024))
    assert old["max_model_len"] == 2048, "the floor the field report hit"

    new = compute_server_args(
        8192, vram_free_mb=int(5.0 * 1024), weight_footprint_gb=4.0, kv_mb_per_token=0.1016
    )
    assert new["max_model_len"] >= 8192
    assert "config" in new["method"]


def test_an_unmeasurable_model_is_byte_identical_to_before():
    """The negative-space twin. A machine that can tell us nothing must behave exactly
    as it did -- the fix buys context from a MEASUREMENT, never from optimism."""
    assert compute_server_args(8192, vram_free_mb=8192)["max_model_len"] == 5120
    assert compute_server_args(8192)["max_model_len"] == 5120
    assert compute_server_args(None)["max_model_len"] == 4096


def test_the_window_never_exceeds_what_the_checkpoint_supports():
    """vLLM REFUSES to start when --max-model-len is above the model's own
    max_position_embeddings, so a budget that ignores it turns a working start into a
    failed one. It binds below the 2048 floor too: a 1024-position model must be asked
    for 1024, and the floor exists to protect an unreadable budget, not to override a
    published limit."""
    roomy = compute_server_args(8192, vram_free_mb=8192, weight_footprint_gb=4.0,
                                kv_mb_per_token=0.1016)
    capped = compute_server_args(8192, vram_free_mb=8192, weight_footprint_gb=4.0,
                                 kv_mb_per_token=0.1016, model_max_tokens=8192)
    assert roomy["max_model_len"] > 8192
    assert capped["max_model_len"] == 8192

    tiny = compute_server_args(8192, vram_free_mb=8192, weight_footprint_gb=4.0,
                               kv_mb_per_token=0.1016, model_max_tokens=1024)
    assert tiny["max_model_len"] == 1024, "the model's ceiling binds below our floor"


def test_a_smaller_kv_figure_can_only_grow_the_window():
    """Monotonic, and STRICTLY so at a fixed budget -- a `>=` here would be satisfied
    by a constant, which is precisely the defect being fixed (the old code returned
    the same floor for every card)."""
    big = compute_server_args(8192, vram_free_mb=8192, weight_footprint_gb=4.0,
                              kv_mb_per_token=0.5)["max_model_len"]
    small = compute_server_args(8192, vram_free_mb=8192, weight_footprint_gb=4.0,
                                kv_mb_per_token=0.125)["max_model_len"]
    assert small > big


# --------------------------------------------------------------------------- #
#  3. A context overflow is deterministic, so it is not an outage.
# --------------------------------------------------------------------------- #


def test_the_servers_own_words_identify_an_overflow():
    assert is_context_overflow(RuntimeError(VLLM_OVERFLOW))
    assert is_context_overflow("context length exceeded")


def test_a_real_outage_is_not_mistaken_for_an_overflow():
    """The twin. Misreading a connection failure as an overflow would shrink the batch
    forever against a backend that is simply down -- and stop the retry that is the
    correct answer there."""
    assert not is_context_overflow(RuntimeError("Connection refused"))
    assert not is_context_overflow(RuntimeError("read timed out"))
    assert not is_context_overflow(None)
    assert not is_context_overflow(RuntimeError("model 'x' not found, try pulling it"))


# --------------------------------------------------------------------------- #
#  4. The clause that named the cause survives the retry line's budget.
# --------------------------------------------------------------------------- #


def test_the_retry_line_keeps_the_clause_that_names_our_own_prompt():
    """REPRODUCES THE FIELD LINE. The composed message is
    ``<status> <url> — <the server's words>``, and the text up to "2048 tokens." is
    199 characters against a 200-character budget -- so a head truncation landed one
    character past the full stop and delivered a sentence that reads as a fact about
    the MODEL, with the clause naming our oversized prompt cut off.
    """
    composed = (
        "vLLM error for model 'mistralai/Ministral-3-3B-Instruct-2512': Client error "
        "'400 Bad Request' for url 'http://127.0.0.1:8001/v1/chat/completions' — "
        + VLLM_OVERFLOW
    )
    # The trap is real: a head cut at the budget stops exactly there.
    assert len(composed[: composed.index("2048 tokens.") + len("2048 tokens.")]) == 199

    line = outage_detail(None, RuntimeError(composed))
    assert "you requested 2940 tokens" in line, "the actionable half must survive"
    assert "2616 in the messages" in line


def test_a_message_with_no_reason_still_truncates_from_the_head():
    """Unchanged behaviour for everything that has no reason to protect."""
    line = outage_detail(None, RuntimeError("x" * 400))
    assert line.startswith("xxx") and line.endswith("…")
