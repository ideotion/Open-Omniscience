"""The one-click Ministral install, and the licence gate it had to pass first.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer request 2026-07-29: "automate the ministral installation with a dedicated
button, the version adapted to below 8Gb Vram hardware."

HISTORY, kept because the reversal is the point. The entry was first held OUT of
``MODEL_CATALOG``: that list advertises "verified against https://ollama.com/library
this cycle", this cycle had already REMOVED two entries rather than ship them on faith,
and ``AI_LAYER_STRATEGY_2026-07-29.md`` §2.4 set an explicit gate — "one page fetch of
the model card settles it and must happen before any catalog entry." That fetch could
not be performed in-session (ollama.com and huggingface.co both 403 through the egress
allowlist), so the entry shipped as a separate, self-describing suggestion carrying its
own UNCONFIRMED licence.

The maintainer then performed the fetch. All three Ministral 3 cards carry
``license: apache-2.0`` and the verbatim line "This model is licensed under the Apache
2.0 License."; the repos are ungated. The gate is met, so the entry now sits in the
catalog on the same terms as its peers, and these tests assert the POST-fetch state —
including two corrections the fetch forced: the short tag ``ministral-3:3b`` does exist
(same digest), and the card names ELEVEN languages, not four.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.llm.ollama import MINISTRAL_SUGGESTION, MODEL_CATALOG

_OLLAMA_PY = Path(__file__).resolve().parents[1] / "src" / "llm" / "ollama.py"
# The pull endpoint's own validation regex — a suggestion the UI offers with a button
# MUST satisfy it, or the button could only ever 400.
_PULL_RE = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"


def test_the_tag_pins_the_quantisation_explicitly():
    """CORRECTED 2026-07-29 by a real fetch of ollama.com/library: the short form
    ``ministral-3:3b`` DOES exist and carries the SAME digest as this one — one image,
    two names. The earlier claim that it was unverifiable was wrong. The long form is
    kept because it pins the quantisation, not because the short one is invalid.

    ``ministral-3:latest`` must never be used: it resolves to the 8B image."""
    assert MINISTRAL_SUGGESTION["tag"] == "ministral-3:3b-instruct-2512-q4_K_M"
    assert "latest" not in MINISTRAL_SUGGESTION["tag"]


def test_the_tag_would_actually_be_pullable():
    import re

    assert re.match(_PULL_RE, MINISTRAL_SUGGESTION["tag"]), (
        "a one-click button whose tag fails the endpoint's own validation is a dead button"
    )


def test_it_carries_the_vllm_counterpart_so_the_button_can_pick_per_backend():
    """2026-07-30: the default-model install resolves WHICH backend will serve and
    fetches that backend's artifact. Ollama wants the quantised image; vLLM wants the
    HuggingFace weights. One entry carries both, so the two can never drift apart into
    different model families."""
    assert MINISTRAL_SUGGESTION["vllm_model"] == "mistralai/Ministral-3-3B-Instruct-2512"
    assert MINISTRAL_SUGGESTION["tag"] != MINISTRAL_SUGGESTION["vllm_model"], (
        "they are genuinely different artifacts — installing one does not install the other"
    )


def test_it_IS_in_the_verified_catalog_now_that_the_licence_was_read():
    """SUPERSEDED 2026-07-29. It was held OUT while the licence was only search-verified,
    because MODEL_CATALOG advertises itself as verified and this cycle already removed
    two entries rather than ship them on faith. The maintainer then FETCHED the model
    card (apache-2.0, ungated, all three sizes), which is exactly the gate §2.4 set — so
    it now belongs in the list on the same terms as its peers."""
    tags = {m["tag"] for m in MODEL_CATALOG}
    assert MINISTRAL_SUGGESTION["tag"] in tags


def test_the_licence_is_now_asserted_because_it_was_actually_read():
    """The inverse of the earlier guard, and deliberately so. While the finding was
    single-sourced the entry had to say UNCONFIRMED; once the card itself was read
    (apache-2.0, verbatim "This model is licensed under the Apache 2.0 License."),
    continuing to hedge would understate what is known. `verification` still records HOW
    it is known, so the claim never floats free of its evidence."""
    assert MINISTRAL_SUGGESTION["license"] == "Apache-2.0"
    assert "model card" in MINISTRAL_SUGGESTION["verification"]


def test_the_caveats_name_every_known_unknown():
    """Caveats visible by default: a user must be able to read what is NOT known before
    clicking, not after."""
    blob = " ".join(MINISTRAL_SUGGESTION["caveats"]).lower()
    assert "ollama" in blob and "0.13.1" in blob, (
        "the version gate is REAL and newer than the tested version — an operator must "
        "read it here rather than discover it through a failed pull"
    )
    # CORRECTED: the card enumerates ELEVEN languages, not the four the earlier caveat
    # claimed. The substantive gap is what survives — none of this corpus's nine.
    assert "11 languages" in blob
    for lang in ("ru", "hi", "bn", "mr"):
        assert lang in blob, f"{lang} must be named as unenumerated"


def test_it_fits_the_stated_vram_budget():
    """The maintainer asked for the variant suited to sub-8 GB VRAM. ~3.0 GB of weights
    leaves real headroom for context where mistral:7b (~4.4 GB) does not."""
    assert MINISTRAL_SUGGESTION["max_vram_gb"] == 8
    assert MINISTRAL_SUGGESTION["size"] == "~3.0 GB"


def test_the_catalog_contract_comment_still_stands():
    """The contract that made this entry wait is still what admits it now."""
    src = _OLLAMA_PY.read_text(encoding="utf-8")
    assert "ollama.com/library this" in src
    assert "rather than shipped on faith" in src


def test_the_catalog_ast_invariant_is_unaffected():
    """The repo invariant parses MODEL_CATALOG via AST. A sibling module-level constant
    must not leak into it (that test asserts over the catalog list only)."""
    tree = ast.parse(_OLLAMA_PY.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found[node.target.id] = node.value
    assert "MODEL_CATALOG" in found and isinstance(found["MODEL_CATALOG"], ast.List)
    assert "MINISTRAL_SUGGESTION" in found and isinstance(found["MINISTRAL_SUGGESTION"], ast.Dict)
