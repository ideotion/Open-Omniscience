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


# The SHIPPED model's own published config, transcribed field-for-field from
# huggingface.co/mistralai/Ministral-3-3B-Instruct-2512/resolve/main/config.json and
# cross-checked against its params.json (2026-08-13, after the maintainer doubted the
# numbers this code derives).
#
# THE SHAPE IS FAITHFUL BECAUSE THE SHAPE IS THE TEST. Three things about the real file
# a flat fixture cannot exercise, and all three are live here:
#   * it is MULTIMODAL -- the transformer shape lives under `text_config` while the
#     dtype stays at the TOP level, so the reader must merge one and still find the
#     other outside it;
#   * `vision_config` carries its OWN `num_hidden_layers` (24), so a reader that
#     merged the wrong block would size the cache from the vision tower;
#   * `head_dim` is 128 while hidden_size // num_attention_heads is 3072 // 32 = 96,
#     so deriving it under-counts the cache by 25% -- the direction that OOMs.
# The quantization block is carried for the same reason: FP8 WEIGHTS must not pull the
# KV element size down with them (vLLM's --kv-cache-dtype defaults to the model dtype).
MINISTRAL_3B = {
    "dtype": "bfloat16",  # top level, and NOT `torch_dtype` -- see the test below
    "tie_word_embeddings": True,
    "vocab_size": 131072,
    "quantization_config": {
        "quant_method": "fp8",
        "activation_scheme": "static",
        "weight_block_size": None,
        "modules_to_not_convert": ["vision_tower", "multi_modal_projector", "lm_head"],
    },
    "text_config": {
        "num_hidden_layers": 26,
        "num_attention_heads": 32,
        "num_key_value_heads": 8,
        "head_dim": 128,
        "hidden_size": 3072,
        "intermediate_size": 9216,
        # 262144 is YaRN-EXTENDED, not native: factor 16 over an original_max of 16384.
        # It is still the right hard ceiling (vLLM refuses to start above it), and our
        # own _MAX_CONTEXT_TOKENS binds far below it either way.
        "max_position_embeddings": 262144,
        # EXPLICITLY null: this model does NOT use sliding-window attention, which is
        # what makes the linear KV formula correct for it all the way up. A checkpoint
        # that DID declare a window would have its cache capped at that width, so the
        # formula would over-state -- the safe direction (shorter context, still
        # starts), but a real limit worth knowing about before trusting the number.
        "sliding_window": None,
        "rope_parameters": {
            "rope_theta": 1000000.0,
            "rope_type": "yarn",
            "factor": 16.0,
            "original_max_position_embeddings": 16384,
        },
    },
    "vision_config": {
        "model_type": "pixtral",
        "num_hidden_layers": 24,  # the decoy: NOT the tower the cache is sized from
        "hidden_size": 1024,
        "image_size": 1540,
        "patch_size": 14,
    },
}
# 2 (K+V) x 26 layers x 8 kv heads x 128 head dim x 2 bytes = 106,496 B = 0.1015625 MiB
MINISTRAL_3B_KV_MB = 0.1015625


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


def test_the_shipped_model_lands_on_its_published_figure(tmp_path):
    """The other end of the bracket. The test above proves the arithmetic against a
    hand-computed constant; this one drives it with the REAL config of the one model
    this app ships, so a future edit that quietly changes the reader is caught against
    a number verified from the publisher rather than against my own arithmetic."""
    root = _snapshot(tmp_path, MINISTRAL_3B)
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("mistralai/Ministral-3-3B-Instruct-2512")
    assert mb == pytest.approx(MINISTRAL_3B_KV_MB)
    assert basis["head_dim"] == 128, "read, not derived -- 3072 // 32 would be 96"
    assert basis["bytes_per_element"] == 2.0
    assert basis["max_position_embeddings"] == 262144
    # ~5x cheaper per token than the class constant: that ratio IS the fix.
    assert mb < V._KV_MB_PER_TOKEN / 4


def test_a_multimodal_checkpoint_is_sized_from_its_TEXT_tower(tmp_path):
    """The decoy in the real file. This checkpoint carries a pixtral `vision_config`
    with its own `num_hidden_layers` (24) and `hidden_size` (1024) -- so a reader that
    merged the wrong block, or read the top level after merging nothing, would size the
    KV cache from the vision tower and be wrong by a factor that no other test here
    would notice. The text tower's 26 layers are the only ones that hold a KV cache.
    """
    root = _snapshot(tmp_path, MINISTRAL_3B)
    with _with_snapshot(root):
        _, basis = kv_mb_per_token("mistralai/Ministral-3-3B-Instruct-2512")
    assert basis["layers"] == 26, "sized from the vision tower, not the text tower"
    assert basis["kv_heads"] == 8 and basis["head_dim"] == 128


def test_fp8_weights_do_not_pull_the_KV_element_size_down_with_them(tmp_path):
    """The real checkpoint IS fp8 -- `quantization_config.quant_method` says so, and
    the weights on disk are ~4.67 GB rather than ~7.7 GB because of it. vLLM's
    --kv-cache-dtype defaults to the model's own dtype, which this file still declares
    as bfloat16, so the cache costs 2 bytes/element however the weights are stored.
    Reading 1 byte off the quantization block would halve the reservation, which is the
    direction that fails at startup rather than the direction that costs context.
    """
    root = _snapshot(tmp_path, MINISTRAL_3B)
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("mistralai/Ministral-3-3B-Instruct-2512")
    assert basis["bytes_per_element"] == 2.0
    assert mb == pytest.approx(MINISTRAL_3B_KV_MB)


def test_the_dtype_field_is_read_under_both_of_its_names(tmp_path):
    """A REAL BUG this fixture caught. transformers renamed ``torch_dtype`` to
    ``dtype``, and the shipped model's config carries only the new name -- so a reader
    that knew the old one alone fell back to a DEFAULT element size on exactly the
    model it was written for. Silent, because a plausible fallback is indistinguishable
    from a reading. Both spellings must work, and neither may become a guess.

    THE FIXTURE DECLARES float32 ON PURPOSE, and that is the whole test. bfloat16 is
    2 bytes and so is the fallback, so a bfloat16 config cannot tell a reader that read
    the field from one that read nothing -- the first draft here used the shipped
    model's own dtype and passed against a reader that had never heard of ``dtype``.
    Only a dtype whose size differs from the fallback discriminates.
    """
    for field in ("dtype", "torch_dtype"):
        cfg = {k: v for k, v in MINISTRAL_3B.items() if k != "dtype"}
        cfg[field] = "float32"
        with _with_snapshot(_snapshot(tmp_path / field, cfg)):
            mb, basis = kv_mb_per_token("some/model")
        assert basis["bytes_per_element"] == 4.0, f"{field} was not read"
        assert mb == pytest.approx(MINISTRAL_3B_KV_MB * 2)


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
#  1b. FIELD REPORT 2026-09-04. The one model this app ships reported "this model's
#      own shape could not be read", ran a 2048-token window on an 8 GiB card, and
#      failed every 4057-token synthesis call. Three separate things could produce
#      that; each has a test here, and none of them could be told apart from the
#      export, which is itself the fourth.
# --------------------------------------------------------------------------- #

#: The same shape in Mistral's OWN vocabulary. `_LOADER_CONFIG_FILES` -- the loader's
#: stated precondition, which `_loadable_revision` already honours -- is
#: ("config.json", "params.json"), and Mistral publishes the second; `kv_mb_per_token`
#: opened only the first, so such a checkpoint resolved and then read as unmeasurable.
MINISTRAL_3B_PARAMS_JSON = {
    "dim": 3072,
    "n_layers": 26,
    "n_heads": 32,
    "n_kv_heads": 8,
    "head_dim": 128,
    "vocab_size": 131072,
    "max_seq_len": 262144,
}


def _snapshot_named(tmp_path: Path, name: str, cfg: dict) -> str:
    rev = tmp_path / "snapshots" / "rev0"
    rev.mkdir(parents=True, exist_ok=True)
    (rev / name).write_text(json.dumps(cfg), encoding="utf-8")
    return str(tmp_path)


def test_a_mistral_format_checkpoint_is_read_from_params_json(tmp_path):
    """The same arithmetic under the other published vocabulary -- and it must land on
    the SAME number, because it is the same model."""
    root = _snapshot_named(tmp_path, "params.json", MINISTRAL_3B_PARAMS_JSON)
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("mistralai/Ministral-3-3B-Instruct-2512")
    assert mb == pytest.approx(MINISTRAL_3B_KV_MB)
    assert basis["head_dim"] == 128 and basis["kv_heads"] == 8 and basis["layers"] == 26
    assert basis["config_file"] == "params.json"
    assert basis["max_position_embeddings"] == 262144


def test_config_json_still_wins_when_both_are_present(tmp_path):
    """Order is the loader's own, not ours: a repo carrying both must be read the way
    vLLM reads it, so adding the second format cannot change the first's answer."""
    root = _snapshot_named(tmp_path, "config.json", MINISTRAL_3B)
    _snapshot_named(tmp_path, "params.json", {"n_layers": 99, "n_heads": 99,
                                              "n_kv_heads": 99, "head_dim": 999})
    with _with_snapshot(root):
        mb, basis = kv_mb_per_token("mistralai/Ministral-3-3B-Instruct-2512")
    assert mb == pytest.approx(MINISTRAL_3B_KV_MB)
    assert basis["config_file"] == "config.json"


def test_the_basis_says_WHICH_file_it_could_not_read(tmp_path):
    """The reporting half. The field export could say the shape was unreadable and not
    which file was missing or which field was absent, so the cause had to be inferred
    from a vLLM startup banner instead of read -- and that cost a whole round trip."""
    root = _snapshot_named(tmp_path, "config.json", {"unrelated": True})
    with _with_snapshot(root):
        basis = V.kv_basis("some/model")
    assert basis["measured"] is False
    assert "config.json" in basis["config_files_present"]
    assert "layers" in basis["reason"] and "head dim" in basis["reason"]
    assert basis["fallback_mb_per_token"] == V._KV_MB_PER_TOKEN

    with _with_snapshot(_snapshot_named(tmp_path / "b", "params.json",
                                        MINISTRAL_3B_PARAMS_JSON)):
        ok = V.kv_basis("mistralai/Ministral-3-3B-Instruct-2512")
    assert ok["measured"] is True and ok["mb_per_token"] == pytest.approx(MINISTRAL_3B_KV_MB)


def test_a_repo_shipping_both_checkpoint_formats_is_not_counted_twice(tmp_path):
    """THE ARITHMETICALLY SUFFICIENT CAUSE of the field's 2048.

    Mistral repos ship a consolidated checkpoint AND its sharded equivalent; the loader
    reads one. Summing both reported ~2x this 3B model's real weight, which spent the
    whole post-weights budget and floored the window regardless of the KV figure -- the
    old docstring called that over-count "safe", which it was until the repo doing it
    became the only repo we ship."""
    rev = tmp_path / "snapshots" / "rev0"
    rev.mkdir(parents=True)
    (rev / "params.json").write_text("{}", encoding="utf-8")
    gib = 1024**3

    def _sized(name: str, gb: float) -> None:
        with (rev / name).open("wb") as fh:
            fh.truncate(int(gb * gib))  # sparse: st_size is what the code reads

    _sized("consolidated.safetensors", 3.3)
    _sized("model-00001-of-00002.safetensors", 1.7)
    _sized("model-00002-of-00002.safetensors", 1.6)

    with _with_snapshot(str(tmp_path)):
        got = V.measured_weight_gb("mistralai/Ministral-3-3B-Instruct-2512")
    assert got == pytest.approx(3.3, abs=0.05), "one copy of the model, not both"
    assert got < 5.0, "and under the conservative class default it replaces"


def test_a_single_format_repo_is_summed_exactly_as_before(tmp_path):
    """The negative-space twin: grouping must not turn a genuinely sharded checkpoint
    into its largest shard. Every shard of one format is still added together."""
    rev = tmp_path / "snapshots" / "rev0"
    rev.mkdir(parents=True)
    (rev / "config.json").write_text("{}", encoding="utf-8")
    for i, gb in ((1, 1.7), (2, 1.6)):
        with (rev / f"model-0000{i}-of-00002.safetensors").open("wb") as fh:
            fh.truncate(int(gb * (1024**3)))
    with _with_snapshot(str(tmp_path)):
        assert V.measured_weight_gb("some/sharded") == pytest.approx(3.3, abs=0.05)


def test_the_de_double_counted_footprint_lifts_the_window_off_the_floor():
    """What the three fixes buy together on the field card, in the units the report
    quoted: 8188 MiB with 7841 free, which is what the running server was started
    from. The doubled footprint alone floored it at 2048 whatever the KV cost was."""
    doubled = compute_server_args(
        8188, vram_free_mb=7841, weight_footprint_gb=7.1,
        kv_mb_per_token=MINISTRAL_3B_KV_MB, model_max_tokens=262144,
    )
    assert doubled["max_model_len"] == 2048, "the floor the field machine ran on"

    fixed = compute_server_args(
        8188, vram_free_mb=7841, weight_footprint_gb=3.8,  # measured 3.3 + load margin
        kv_mb_per_token=MINISTRAL_3B_KV_MB, model_max_tokens=262144,
    )
    assert fixed["max_model_len"] >= 16384, "big enough for the 4057-token prompts that failed"
    assert fixed["max_model_len"] <= 262144, "and never past what the checkpoint supports"


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

    # Same card, same free memory, the model's REAL cost per token instead of a
    # 7B-class assumption. The comparison is what the fix bought; the absolute number
    # is not asserted, because it is a function of the weight margin and the graph
    # reserve and would pin those constants here rather than the property.
    for free_gb in (8.0, 7.5):
        assumed = compute_server_args(8192, vram_free_mb=int(free_gb * 1024))
        measured = compute_server_args(
            8192, vram_free_mb=int(free_gb * 1024),
            kv_mb_per_token=MINISTRAL_3B_KV_MB, model_max_tokens=262144,
        )
        assert measured["max_model_len"] > assumed["max_model_len"]
        assert measured["max_model_len"] >= 8192, "big enough to carry an article"
        assert "config" in measured["method"]

    # ...and the honest other end: a card with barely more free than the weights has
    # nothing left after them and the fragmentation reserve, so it goes BACK to the
    # floor. That is not the reported defect returning -- it is the one case where 2048
    # was always true, and publishing more would be a window built on memory the
    # utilization already declined to claim.
    tight = compute_server_args(
        8192, vram_free_mb=int(5.6 * 1024),
        kv_mb_per_token=MINISTRAL_3B_KV_MB, model_max_tokens=262144,
    )
    assert tight["max_model_len"] == 2048


def test_an_unmeasurable_model_is_byte_identical_to_before():
    """The negative-space twin. A machine that can tell us nothing must behave exactly
    as it did -- the fix buys context from a MEASUREMENT, never from optimism."""
    assert compute_server_args(8192, vram_free_mb=8192)["max_model_len"] == 5120
    assert compute_server_args(8192)["max_model_len"] == 5120
    assert compute_server_args(None)["max_model_len"] == 4096


def test_the_published_equation_reproduces_the_published_number():
    """A derivation that shows its work owes the reader that the work is the work.

    The method string names the terms it subtracted; a reader can do the division. If
    the code subtracts a term the string omits -- as it did the moment the graph-pool
    reserve came off the KV budget -- the reader checking it finds the app
    contradicting itself, which is worse than publishing no equation at all.
    """
    free_gb, weights, headroom = 7.5, 5.0, 0.15
    out = compute_server_args(
        8192, vram_free_mb=int(free_gb * 1024),
        weight_footprint_gb=weights, kv_mb_per_token=MINISTRAL_3B_KV_MB,
        model_max_tokens=262144,
    )
    # WHICH reserve, per the mode this card is actually in: an 8 GiB card runs eager
    # (see `_EAGER_MAX_VRAM_GB`), where no CUDA-graph pool is ever allocated, so the
    # equation must quote the eager reserve it really subtracted -- quoting the capture
    # reserve here would be the exact defect this test exists to catch, one mode over.
    reserve = max(V._EAGER_GRAPH_POOL_RESERVE_GB, 8.0 * 0.05)
    for term in (f"{free_gb} GB available", f"{weights} GB for weights",
                 f"{reserve} GB held back", "15% headroom",
                 f"{MINISTRAL_3B_KV_MB} MB/token", "262144-token limit"):
        assert term in out["method"], f"the method does not name {term!r}"

    kv_gb = (free_gb - weights - reserve) * (1.0 - headroom)
    hand = max(2048, min(V._MAX_CONTEXT_TOKENS, (int(kv_gb * 1024 / MINISTRAL_3B_KV_MB) // 1024) * 1024))
    assert out["max_model_len"] == min(hand, 262144)


def test_the_unmeasured_method_does_not_claim_a_subtraction_it_never_made():
    """The negative-space twin, and the one that keeps the honesty symmetric. The
    reserve is subtracted ONLY where the KV figure is measured, so naming it on the
    fallback path would be a fabricated conservatism -- an equation whose hand-computed
    answer is smaller than the number printed beside it."""
    out = compute_server_args(8192, vram_free_mb=8192)
    assert "held back" not in out["method"]
    assert "checkpoint's own" not in out["method"], "no config was read, so no ceiling"
    hand = max(2048, min(V._MAX_CONTEXT_TOKENS,
                         (int((8.0 - 5.0) * 0.85 * 1024 / V._KV_MB_PER_TOKEN) // 1024) * 1024))
    assert out["max_model_len"] == hand


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
